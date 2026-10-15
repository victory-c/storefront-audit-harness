"""Tests for the storefront-audit-harness contract layer."""
import json
import os
import subprocess
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from harness.validate import validate_audit, validate_manifest  # noqa: E402

FIX = os.path.join(_REPO_ROOT, "tests", "fixtures")


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def _codes(issues):
    return {i.code for i in issues}


def test_valid_manifest_passes():
    report = validate_manifest(_load("manifest.valid.json"))
    assert report.ok, report.summary()


def test_valid_audit_passes_clean():
    report = validate_audit(_load("audit.valid.json"), _load("manifest.valid.json"))
    assert report.ok, report.summary()
    # The valid fixture is designed to be clean — no warnings either.
    assert report.warnings == [], report.summary()


def test_invalid_pillars_fails_with_code():
    report = validate_audit(_load("audit.invalid_pillars.json"), _load("manifest.valid.json"))
    assert not report.ok
    assert "pillar_coverage" in _codes(report.errors)


def test_invalid_evidence_fails_with_code():
    report = validate_audit(_load("audit.invalid_evidence.json"), _load("manifest.valid.json"))
    assert not report.ok
    assert "evidence_unresolved" in _codes(report.errors)


def test_invalid_technical_check_evidence_fails_with_code():
    audit = _load("audit.valid.json")
    audit["technical_checks"][0]["evidence_manifest_id"] = "pg_deadbeef"
    report = validate_audit(audit, _load("manifest.valid.json"))
    assert not report.ok
    assert "technical_check_evidence_unresolved" in _codes(report.errors)


def test_malformed_technical_check_evidence_fails_schema():
    audit = _load("audit.valid.json")
    audit["technical_checks"][0]["evidence_manifest_id"] = "not-a-page-id"
    report = validate_audit(audit, _load("manifest.valid.json"))
    assert not report.ok
    # Malformed id is caught by the schema layer before cross-record validators run.
    assert "audit_schema" in _codes(report.errors)


def test_audit_without_manifest_skips_with_warnings():
    report = validate_audit(_load("audit.valid.json"), None)
    # Schema + manifest-free validators still pass; manifest-needing ones are skipped.
    assert report.ok, report.summary()
    assert "validator_skipped" in _codes(report.warnings)


def test_run_audit_validate_only():
    cmd = [
        sys.executable, "run_audit.py", "--url", "https://gingerpeople.com",
        "--validate-only",
        "--audit", "tests/fixtures/audit.valid.json",
        "--manifest", "tests/fixtures/manifest.valid.json",
    ]
    result = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_run_eval_writes_scorecard(tmp_path):
    out = tmp_path / "scorecard.json"
    cmd = [
        sys.executable, "eval/run_eval.py",
        "--audit", "tests/fixtures/audit.valid.json",
        "--manifest", "tests/fixtures/manifest.valid.json",
        "--out", str(out),
    ]
    result = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(out.read_text())
    assert data["layer1"]["ok"] is True
    # Layer 2 runs only with an API key; without one it reports skipped (or ok if a key
    # is present in the environment).
    assert data["layer2"]["status"] in ("skipped", "ok")
