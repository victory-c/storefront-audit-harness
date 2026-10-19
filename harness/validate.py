#!/usr/bin/env python3
"""Contract validation for storefront-audit-harness.

Two layers:

1. **JSON Schema** (Draft 2020-12) validates the *shape* of each record in
   isolation — required fields, types, enums, patterns, lengths.
2. **Cross-record validators** enforce invariants JSON Schema cannot express:
   coverage of an enum across array items, uniqueness of one field, references
   from the audit into the crawl manifest, presence of a canonical check set,
   etc.

The validators live in a registry (``VALIDATORS``) so later eval work can append
new rules as new failure modes are discovered. Error codes are stable identifiers
(tests pin ``pillar_coverage`` and ``evidence_unresolved``).

CLI:
    python3 harness/validate.py --manifest PATH
    python3 harness/validate.py --audit PATH --manifest PATH
    python3 harness/validate.py --audit PATH
Exit code 0 if ok, else 1.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional
from urllib.parse import urlparse

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from harness.version import HARNESS_VERSION  # noqa: E402

from jsonschema import Draft202012Validator, FormatChecker  # noqa: E402

__all__ = [
    "HARNESS_VERSION",
    "Issue",
    "ValidationReport",
    "validate_manifest",
    "validate_audit",
    "PILLARS",
    "CANONICAL_TECH_CHECKS",
    "VALIDATORS",
]

SCHEMA_DIR = os.path.join(_REPO_ROOT, "schema")
MANIFEST_SCHEMA_PATH = os.path.join(SCHEMA_DIR, "manifest.schema.json")
AUDIT_SCHEMA_PATH = os.path.join(SCHEMA_DIR, "audit.schema.json")

PILLARS = ["Conversion", "AOV", "Retention", "Acquisition", "Performance"]

# Canonical technical-check names. Single source of truth so a future
# tech_checks.py emits exactly the names this validator requires.
CANONICAL_TECH_CHECKS = [
    "SSL Certificate",
    "HTTPS Redirect",
    "Sitemap",
    "Robots.txt",
    "Critical Pages Loading",
    "Meta Tags & Social Previews",
    "Structured Data",
    "Favicon",
    "Mobile-Friendly",
    "Page Speed Mobile",
    "Page Speed Desktop",
    "Broken Links",
    "Image Optimization",
    "Cookie/Privacy",
    "Checkout Reachable",
]


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass
class Issue:
    level: str  # "error" | "warn"
    code: str
    message: str
    locator: str = ""


@dataclass
class ValidationReport:
    ok: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [asdict(e) for e in self.errors],
            "warnings": [asdict(w) for w in self.warnings],
        }

    def summary(self) -> str:
        status = "OK" if self.ok else "FAIL"
        lines = [f"[{status}] {len(self.errors)} error(s), {len(self.warnings)} warning(s)"]
        for e in self.errors:
            lines.append(f"  ERROR [{e.code}] {e.locator}: {e.message}")
        for w in self.warnings:
            lines.append(f"  WARN  [{w.code}] {w.locator}: {w.message}")
        return "\n".join(lines)


def _report(errors: list, warnings: list) -> ValidationReport:
    return ValidationReport(ok=(len(errors) == 0), errors=errors, warnings=warnings)


# --------------------------------------------------------------------------- #
# Schema layer
# --------------------------------------------------------------------------- #
def _load_schema(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _schema_errors(instance: dict, schema: dict, kind: str) -> list:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    issues = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "(root)"
        issues.append(Issue("error", f"{kind}_schema", err.message, loc))
    return issues


# --------------------------------------------------------------------------- #
# Cross-record helpers
# --------------------------------------------------------------------------- #
def _manifest_ids(manifest: dict) -> set:
    return {p["id"] for p in manifest.get("pages", [])}


def _pages_by_id(manifest: dict) -> dict:
    return {p["id"]: p for p in manifest.get("pages", [])}


def _manifest_urls(manifest: dict) -> set:
    return {p["url"] for p in manifest.get("pages", [])}


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _domain_host(domain: str) -> str:
    d = domain.strip().lower()
    if "//" not in d:
        d = "http://" + d
    return _host(d)


# --------------------------------------------------------------------------- #
# Cross-record validators — each returns list[Issue]
# --------------------------------------------------------------------------- #
def _v_pillar_coverage(audit, manifest):
    present = {e["pillar"] for e in audit["experiments"]}
    missing = [p for p in PILLARS if p not in present]
    if missing:
        return [Issue("error", "pillar_coverage",
                      f"Experiments must span all 5 pillars; missing: {', '.join(missing)}.",
                      "experiments")]
    return []


def _v_exp_id_unique(audit, manifest):
    seen, dupes = set(), set()
    for e in audit["experiments"]:
        eid = e["exp_id"]
        if eid in seen:
            dupes.add(eid)
        seen.add(eid)
    if dupes:
        return [Issue("error", "exp_id_duplicate",
                      f"Duplicate exp_id(s): {', '.join(sorted(dupes))}.", "experiments")]
    return []


def _v_evidence_resolvable(audit, manifest):
    ids = _manifest_ids(manifest)
    issues = []
    for e in audit["experiments"]:
        mid = e["evidence"]["manifest_id"]
        if mid not in ids:
            issues.append(Issue("error", "evidence_unresolved",
                                 f"Experiment {e['exp_id']} cites evidence manifest_id "
                                 f"'{mid}', which is not present in the manifest.",
                                 f"experiments[{e['exp_id']}].evidence.manifest_id"))
    return issues


_ACCESS_BARRIER_RE = re.compile(
    r"(?:access barrier|blocked|bot[- ]?(?:protection|management)|challenge|"
    r"\b(?:401|403|429|503)\b|inaccessible|not accessible|unreachable|"
    r"network error|fetch error|failed to load|not assessable|could not "
    r"(?:read|inspect|load|access)|cannot (?:read|inspect|load|access))",
    re.IGNORECASE,
)


def _is_access_barrier_claim(text: str) -> bool:
    """Return whether text explicitly describes an access failure, not page content."""
    return bool(_ACCESS_BARRIER_RE.search(text or ""))


def _v_inaccessible_evidence(audit, manifest):
    pages = _pages_by_id(manifest)
    issues = []
    for e in audit["experiments"]:
        page = pages.get(e["evidence"]["manifest_id"])
        if page is None or page.get("access_status") not in {"blocked", "unavailable", "error", "empty"}:
            continue
        ev = e["evidence"]
        # Keep the exception explicit and evidence-local: a barrier keyword in a
        # recommendation title must not launder a content claim on a blocked page.
        claim_text = str(ev.get("note") or "")
        if not _is_access_barrier_claim(claim_text):
            issues.append(Issue(
                "error", "evidence_inaccessible",
                f"Experiment {e['exp_id']} cites {page.get('access_status')} page "
                f"{ev['manifest_id']} as content evidence; only an explicit access-barrier "
                "claim may cite an inaccessible page.",
                f"experiments[{e['exp_id']}].evidence.manifest_id",
            ))
    return issues


def _v_inaccessible_technical_evidence(audit, manifest):
    pages = _pages_by_id(manifest)
    issues = []
    for c in audit["technical_checks"]:
        mid = c.get("evidence_manifest_id")
        page = pages.get(mid) if mid else None
        if page is None or page.get("access_status") not in {"blocked", "unavailable", "error", "empty"}:
            continue
        if not _is_access_barrier_claim(c.get("detail", "")):
            issues.append(Issue(
                "error", "technical_check_evidence_inaccessible",
                f"Technical check '{c['check']}' cites {page.get('access_status')} page "
                f"{mid} for page-content evidence; describe only the access barrier or "
                "omit the evidence_manifest_id.",
                f"technical_checks[{c['check']}].evidence_manifest_id",
            ))
    return issues


def _v_evidence_path_consistency(audit, manifest):
    pages = _pages_by_id(manifest)
    issues = []
    for e in audit["experiments"]:
        ev = e["evidence"]
        sp = ev.get("screenshot_path")
        if sp:
            page = pages.get(ev["manifest_id"])
            if page is not None and page.get("screenshot_path") != sp:
                issues.append(Issue("warn", "evidence_path_mismatch",
                                     f"Experiment {e['exp_id']} evidence.screenshot_path "
                                     f"'{sp}' does not match manifest page "
                                     f"{ev['manifest_id']} screenshot_path "
                                     f"'{page.get('screenshot_path')}'.",
                                     f"experiments[{e['exp_id']}].evidence.screenshot_path"))
    return issues


def _v_new_page_evidence_note(audit, manifest):
    urls = _manifest_urls(manifest)
    issues = []
    for e in audit["experiments"]:
        if e["url"] not in urls:
            note = e["evidence"].get("note")
            if not (note and note.strip()):
                issues.append(Issue("warn", "new_page_evidence_note",
                                     f"Experiment {e['exp_id']} targets a URL not in the "
                                     f"manifest (likely a proposed new page) but "
                                     f"evidence.note is empty; cite the existing artifact "
                                     f"that supports the recommendation.",
                                     f"experiments[{e['exp_id']}].evidence.note"))
    return issues


def _v_competitor_source_resolvable(audit, manifest):
    ids = _manifest_ids(manifest)
    issues = []
    for c in audit["competitors"]:
        if c["source_type"] == "captured_artifact":
            sid = c.get("source_manifest_id")
            if not sid or sid not in ids:
                issues.append(Issue("error", "competitor_source_unresolved",
                                     f"Competitor '{c['name']}' has source_type "
                                     f"'captured_artifact' but source_manifest_id "
                                     f"'{sid}' is missing or not in the manifest.",
                                     f"competitors[{c['name']}].source_manifest_id"))
    return issues


def _v_technical_check_evidence_resolvable(audit, manifest):
    ids = _manifest_ids(manifest)
    issues = []
    for c in audit["technical_checks"]:
        mid = c.get("evidence_manifest_id")
        if mid is not None and mid not in ids:
            issues.append(Issue("error", "technical_check_evidence_unresolved",
                                 f"Technical check '{c['check']}' cites "
                                 f"evidence_manifest_id '{mid}', which is not present in "
                                 f"the manifest.",
                                 f"technical_checks[{c['check']}].evidence_manifest_id"))
    return issues


def _v_canonical_tech_checks(audit, manifest):
    present = {c["check"] for c in audit["technical_checks"]}
    missing = [c for c in CANONICAL_TECH_CHECKS if c not in present]
    if missing:
        return [Issue("error", "canonical_tech_checks_missing",
                      f"Missing canonical technical checks: {', '.join(missing)}.",
                      "technical_checks")]
    return []


def _v_pillar_balance(audit, manifest):
    counts = {p: 0 for p in PILLARS}
    for e in audit["experiments"]:
        counts[e["pillar"]] = counts.get(e["pillar"], 0) + 1
    singles = [p for p, n in counts.items() if n == 1]
    heavy = [p for p, n in counts.items() if n >= 3]
    if singles and heavy:
        return [Issue("warn", "pillar_balance",
                      f"Unbalanced pillar distribution {counts}: single-experiment "
                      f"pillar(s) {', '.join(singles)} while {', '.join(heavy)} carry >=3.",
                      "experiments")]
    return []


def _v_onsite_host_match(audit, manifest):
    issues = []
    store_host = _host(audit["store_url"])
    for e in audit["experiments"]:
        eh = _host(e["url"])
        if eh and store_host and eh != store_host:
            issues.append(Issue("warn", "host_mismatch",
                                 f"Experiment {e['exp_id']} url host '{eh}' differs from "
                                 f"store host '{store_host}'.",
                                 f"experiments[{e['exp_id']}].url"))
    for c in audit["competitors"]:
        ch = _domain_host(c["domain"])
        if ch and store_host and ch == store_host:
            issues.append(Issue("warn", "host_mismatch",
                                 f"Competitor '{c['name']}' domain '{c['domain']}' equals "
                                 f"the store domain.",
                                 f"competitors[{c['name']}].domain"))
    return issues


def _v_overconfidence(audit, manifest):
    issues = []
    for e in audit["experiments"]:
        if e["confidence"] > 90:
            issues.append(Issue("warn", "overconfidence",
                                 f"Experiment {e['exp_id']} confidence "
                                 f"{e['confidence']}% exceeds 90% — likely overconfident.",
                                 f"experiments[{e['exp_id']}].confidence"))
    return issues


def _v_exec_summary_paragraphs(audit, manifest):
    paras = [p for p in re.split(r"\n\s*\n", audit["executive_summary"].strip()) if p.strip()]
    n = len(paras)
    if n < 2 or n > 3:
        return [Issue("warn", "exec_summary_paragraphs",
                      f"Executive summary has {n} paragraph(s); expected 2-3.",
                      "executive_summary")]
    return []


@dataclass
class Validator:
    code: str
    needs_manifest: bool
    fn: Callable


VALIDATORS = [
    Validator("pillar_coverage", False, _v_pillar_coverage),
    Validator("exp_id_duplicate", False, _v_exp_id_unique),
    Validator("evidence_unresolved", True, _v_evidence_resolvable),
    Validator("evidence_inaccessible", True, _v_inaccessible_evidence),
    Validator("evidence_path_mismatch", True, _v_evidence_path_consistency),
    Validator("new_page_evidence_note", True, _v_new_page_evidence_note),
    Validator("competitor_source_unresolved", True, _v_competitor_source_resolvable),
    Validator("technical_check_evidence_unresolved", True, _v_technical_check_evidence_resolvable),
    Validator("technical_check_evidence_inaccessible", True, _v_inaccessible_technical_evidence),
    Validator("canonical_tech_checks_missing", False, _v_canonical_tech_checks),
    Validator("pillar_balance", False, _v_pillar_balance),
    Validator("host_mismatch", False, _v_onsite_host_match),
    Validator("overconfidence", False, _v_overconfidence),
    Validator("exec_summary_paragraphs", False, _v_exec_summary_paragraphs),
]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def validate_manifest(manifest: dict) -> ValidationReport:
    """Schema-only validation of a crawl manifest."""
    schema = _load_schema(MANIFEST_SCHEMA_PATH)
    return _report(_schema_errors(manifest, schema, "manifest"), [])


def validate_audit(audit: dict, manifest: Optional[dict] = None) -> ValidationReport:
    """Validate an audit report: schema first, then cross-record invariants.

    If schema validation fails, return immediately (cross-record validators
    assume a well-shaped document). If ``manifest`` is None, validators that
    need it are skipped and recorded as warnings.
    """
    schema = _load_schema(AUDIT_SCHEMA_PATH)
    schema_errs = _schema_errors(audit, schema, "audit")
    if schema_errs:
        return _report(schema_errs, [])

    errors, warnings = [], []
    for v in VALIDATORS:
        if v.needs_manifest and manifest is None:
            warnings.append(Issue("warn", "validator_skipped",
                                  f"Validator '{v.code}' skipped: requires a manifest, "
                                  f"none provided.", v.code))
            continue
        for issue in v.fn(audit, manifest):
            (errors if issue.level == "error" else warnings).append(issue)
    return _report(errors, warnings)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate storefront-audit-harness manifest and/or audit contracts.")
    parser.add_argument("--audit", help="Path to an audit.json")
    parser.add_argument("--manifest", help="Path to a manifest.json")
    args = parser.parse_args(argv)

    if not args.audit and not args.manifest:
        parser.error("provide --audit and/or --manifest")

    if args.audit:
        audit = _load_json(args.audit)
        manifest = _load_json(args.manifest) if args.manifest else None
        report = validate_audit(audit, manifest)
    else:
        report = validate_manifest(_load_json(args.manifest))

    print(report.summary())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
