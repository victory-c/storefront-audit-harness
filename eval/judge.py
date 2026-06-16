#!/usr/bin/env python3
"""Eval Layer 2: LLM-as-judge over a versioned rubric (reference-free).

Scores an audit report against the artifacts it cites — so it generalizes to
stores the eval has never seen. Each rubric dimension is scored 0-5 with a
justification; the composite is a weighted 0-100. An optional anchor file
(target_report.md, for the calibration store only) is passed as a *calibration
note*, never as ground truth.

Requires ``anthropic`` + ``ANTHROPIC_API_KEY`` and ``pyyaml`` to load the rubric.
``run_judge`` returns a dict; callers decide how to embed it in a scorecard.
"""
from __future__ import annotations

import json
import os
import re
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from harness.reason_write import build_evidence_pack  # noqa: E402

DEFAULT_JUDGE_MODEL = os.environ.get("QOSMIC_JUDGE_MODEL", "claude-sonnet-4-6")
DEFAULT_RUBRIC = os.path.join(_REPO_ROOT, "eval", "rubric", "rubric.v1.yaml")


def load_rubric(path: str = DEFAULT_RUBRIC) -> dict:
    import yaml  # lazy: only needed for Layer 2
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def compute_composite(scores: dict, rubric: dict) -> float:
    total = 0.0
    for dim in rubric["dimensions"]:
        s = scores.get(dim["id"], {}).get("score", 0)
        total += (float(s) / 5.0) * float(dim["weight"])
    return round(total * 100, 1)


def run_judge(audit: dict, manifest: dict, rubric_path: str = DEFAULT_RUBRIC,
              anchor_text: str | None = None, model: str = DEFAULT_JUDGE_MODEL) -> dict:
    try:
        import anthropic
    except ImportError as e:
        raise RuntimeError("Layer 2 needs 'anthropic' (pip install anthropic) + "
                           "ANTHROPIC_API_KEY.") from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set; cannot run Layer 2 judge.")

    rubric = load_rubric(rubric_path)
    dims = "\n".join(f"- {d['id']} (weight {d['weight']}): {d['question'].strip()}"
                     for d in rubric["dimensions"])
    anchor_note = ""
    if anchor_text:
        anchor_note = ("\nCALIBRATION NOTE (style reference only, NOT ground truth; do not "
                       "reward copying it):\n" + anchor_text[:6000])

    user = f"""Score this Qosmic audit report against the artifacts it cites. Be a harsh,
fair judge. For each dimension give an integer 0-5 and a one-sentence justification that
cites a specific experiment id or page id.

RUBRIC DIMENSIONS:
{dims}

Return ONLY JSON:
{{"dimensions": {{"<dim_id>": {{"score": <0-5>, "justification": "..."}}, ...}},
  "top_strength": "...", "top_weakness": "...", "fix_suggestion": "..."}}
{anchor_note}

=== AUDIT REPORT (JSON) ===
{json.dumps(audit, ensure_ascii=False)}

=== CITED CRAWL ARTIFACTS ===
{build_evidence_pack(manifest, max_chars=2500)}"""

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model, max_tokens=4000,
        system="You are a meticulous CRO audit evaluator. Output strict JSON only.",
        messages=[{"role": "user", "content": user}])
    raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    parsed = _extract_json(raw)
    parsed["composite"] = compute_composite(parsed.get("dimensions", {}), rubric)
    parsed["rubric_version"] = rubric.get("version")
    parsed["model"] = model
    parsed["review_threshold"] = rubric.get("review_threshold")
    parsed["needs_human_review"] = parsed["composite"] < rubric.get("review_threshold", 0)
    return parsed
