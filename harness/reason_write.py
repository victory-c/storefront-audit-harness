#!/usr/bin/env python3
"""Reason + Write: turn a crawl manifest into a schema-valid audit.json.

This is the LLM step. It assembles an evidence pack from the on-disk artifacts,
asks Claude to produce an audit.json that satisfies ``schema/audit.schema.json``
*and* the cross-record invariants, then runs the real Gate B validator and feeds
any errors back for repair (bounded retries). The contract — not the prose — is
the stopping condition.

Requires ``anthropic`` and ``ANTHROPIC_API_KEY``. Without them it raises a clear
error pointing at the skill-driven path (an agent can produce audit.json by hand
following skills/storefront-audit-write/SKILL.md). Model id defaults to Opus 4.8 and
is overridable via ``STOREFRONT_AUDIT_MODEL``.
"""
from __future__ import annotations

import json
import os
import re
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from harness.validate import (  # noqa: E402
    CANONICAL_TECH_CHECKS,
    PILLARS,
    validate_audit,
)
from harness.version import HARNESS_VERSION  # noqa: E402

DEFAULT_MODEL = os.environ.get("STOREFRONT_AUDIT_MODEL", "claude-opus-4-8")
MAX_CHARS_PER_PAGE = 4000
MAX_ATTEMPTS = 3


def build_evidence_pack(manifest: dict, max_chars: int = MAX_CHARS_PER_PAGE) -> str:
    blocks = []
    for p in manifest["pages"]:
        excerpt = ""
        tp = p.get("text_path")
        if tp:
            path = tp if os.path.isabs(tp) else os.path.join(_REPO_ROOT, tp)
            try:
                with open(path, encoding="utf-8") as f:
                    excerpt = f.read()[:max_chars]
            except OSError:
                excerpt = "(text artifact unavailable)"
        blocks.append(
            f"--- PAGE {p['id']} ---\n"
            f"url: {p['url']}\npage_type: {p['page_type']}\n"
            f"status_code: {p['status_code']}\ntitle: {p.get('title')}\n"
            f"access_status: {p.get('access_status', 'unknown')}\n"
            f"screenshot_path: {p.get('screenshot_path')}\n"
            f"text_excerpt:\n{excerpt}\n")
    return "\n".join(blocks)


def _system_prompt() -> str:
    return (
        "You are Storefront Audit's runtime audit agent. You produce conversion-rate-optimization "
        "(CRO) audits for Shopify storefronts. You only make claims that are grounded in "
        "the provided crawl artifacts. You never invent evidence. You output strictly "
        "valid JSON for the requested schema and nothing else.")


def _instructions(store: str, store_url: str, manifest_ids: list) -> str:
    return f"""Produce a single JSON object: an audit report for `{store_url}` (store id "{store}").

Hard requirements (the report is rejected otherwise):
- Exactly 10 experiments spanning ALL five pillars: {", ".join(PILLARS)} (aim ~2 each).
- Every experiment.evidence.manifest_id MUST be one of these captured page ids: {manifest_ids}.
- Every technical_checks[].evidence_manifest_id is either null or one of those ids.
- For a proposed NEW page (url not among captured pages), set evidence.note to the existing
  artifact that justifies it, and point evidence.manifest_id at that existing captured page.
- expected_lift is PERCENTAGE-ONLY, e.g. "+8-14%". Dollar thresholds go in decision_rule.
- exp_id matches ^exp-[0-9a-f]{{12}}$ and is unique. confidence is an integer 0-100.
- executive_summary is 2-3 paragraphs of prose.
- competitors: 3-4 entries, each with source_url + source_type
  (search|manual|site_visit|captured_artifact) + source_manifest_id (null unless
  source_type is captured_artifact).
- technical_checks: include exactly these {len(CANONICAL_TECH_CHECKS)} checks by name:
  {CANONICAL_TECH_CHECKS}. Each status is Pass|Warn|Fail with a one-line evidence-based detail.
- store_url="{store_url}", store="{store}", harness_version="{HARNESS_VERSION}",
  generated_at is an ISO-8601 UTC timestamp.
- Treat pages marked blocked, unavailable, error, empty, or unknown as access limitations, not
  content evidence. Do not make claims about content that was not captured; explain the scope
  limitation in the executive summary and relevant technical checks.

Cite everything. Diversify pillars. Be specific to THIS store — no generic advice.
Output ONLY the JSON object."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model output.")
    return json.loads(text[start:end + 1])


def generate_audit(manifest: dict, store_url: str, store: str | None = None,
                   model: str = DEFAULT_MODEL, max_attempts: int = MAX_ATTEMPTS) -> dict:
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError(
            "reason/write needs the 'anthropic' package (pip install anthropic) and "
            "ANTHROPIC_API_KEY. Alternatively, an agent can produce audit.json by hand "
            "following skills/storefront-audit-write/SKILL.md, then validate with "
            "harness/validate.py.") from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Set it, or follow the skill-driven path "
            "(skills/storefront-audit-write/SKILL.md) to write audit.json by hand.")

    store = store or manifest.get("store", "store")
    manifest_ids = [p["id"] for p in manifest["pages"]]
    client = anthropic.Anthropic()

    base_user = (
        _instructions(store, store_url, manifest_ids)
        + "\n\n=== CRAWL ARTIFACTS ===\n"
        + build_evidence_pack(manifest))

    messages = [{"role": "user", "content": base_user}]
    last_report = None
    for attempt in range(1, max_attempts + 1):
        resp = client.messages.create(
            model=model, max_tokens=8000, system=_system_prompt(), messages=messages)
        raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        try:
            audit = _extract_json(raw)
        except (ValueError, json.JSONDecodeError) as e:
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": f"That was not valid JSON ({e}). "
                          "Return ONLY the corrected JSON object."}]
            continue
        report = validate_audit(audit, manifest)
        last_report = report
        if report.ok:
            return audit
        errors = "\n".join(f"- [{i.code}] {i.locator}: {i.message}" for i in report.errors)
        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "The audit failed validation:\n" + errors
             + "\nReturn the FULL corrected JSON object only."}]
    raise RuntimeError(
        "reason/write could not produce a valid audit within "
        f"{max_attempts} attempts. Last errors: "
        + (last_report.summary() if last_report else "n/a"))
