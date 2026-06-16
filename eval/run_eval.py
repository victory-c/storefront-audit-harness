#!/usr/bin/env python3
"""qosmic-audit-harness — eval runner.

Step 1 wires up the eval CLI and makes **Layer 1 the same validators as the
harness gate** (single source of truth — the harness and the eval can never
drift). Layer 2 (LLM judge over a versioned rubric) is stubbed.

    python3 eval/run_eval.py --audit PATH --manifest PATH \\
        [--rubric eval/rubric/rubric.v1.yaml] [--anchor target_report.md] \\
        --out eval_output/<store>_scorecard.json

Exit 0 if Layer 1 passes, else 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from harness.validate import validate_audit  # noqa: E402


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Score a Qosmic audit report.")
    parser.add_argument("--audit", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--rubric", default="eval/rubric/rubric.v1.yaml",
                        help="(accepted; Layer 2 not implemented yet)")
    parser.add_argument("--anchor", help="Calibration style reference (e.g. target_report.md)")
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip Layer 2 (LLM judge) even if an API key is present")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    audit = _load_json(args.audit)
    manifest = _load_json(args.manifest)

    report = validate_audit(audit, manifest)  # Layer 1 (same gate as the harness)

    # Layer 2 — LLM judge over the versioned rubric. Reference-free; only runs when
    # an API key is present and Layer 1 passed (no point judging a malformed report).
    layer2 = {"status": "skipped", "reason": "Layer 1 failed; judge not run."}
    if report.ok and not args.no_llm:
        try:
            from eval.judge import run_judge
            anchor_text = None
            if args.anchor and os.path.exists(args.anchor):
                with open(args.anchor, encoding="utf-8") as f:
                    anchor_text = f.read()
            layer2 = run_judge(audit, manifest, rubric_path=args.rubric, anchor_text=anchor_text)
            layer2["status"] = "ok"
        except Exception as e:
            layer2 = {"status": "skipped", "reason": str(e)}
    elif args.no_llm:
        layer2 = {"status": "skipped", "reason": "--no-llm"}

    scorecard = {
        "store": audit.get("store"),
        "audit_path": args.audit,
        "manifest_path": args.manifest,
        "layer1": report.to_json(),
        "layer2": layer2,
    }

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(scorecard, f, indent=2, ensure_ascii=False)

    print(f"Wrote scorecard to {args.out} (layer1.ok={report.ok}).")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
