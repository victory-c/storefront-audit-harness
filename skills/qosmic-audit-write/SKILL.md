---
name: qosmic-audit-write
description: >
  Serialize a Qosmic audit to the canonical audit.json schema and pass Gate B validation.
  Use during the Write phase of a Qosmic audit, after reasoning is done.
---

# Write: audit.json to the canonical schema

Emit one JSON object to `sample_output/<slug>/audit.json`. The schema is
`schema/audit.schema.json`; the cross-record rules are in `schema/README.md`. Validate, then
render. **Generate JSON first — never write Markdown by hand.**

## Required shape

- `store`, `store_url`, `generated_at` (ISO-8601 UTC), `harness_version`.
- `executive_summary`: 2-3 paragraphs of prose, highest-level read on what's costing sales.
- `experiments`: **exactly 10**, spanning all 5 pillars. Each:
  `exp_id` (`^exp-[0-9a-f]{12}$`, unique), `title`, `pillar`, `affected_surface`, `url`,
  `evidence` {`manifest_id` (must resolve), `url`, `screenshot_path|null`, `note|null`},
  `hypothesis`, `primary_change`, `primary_kpi`, `decision_rule`,
  `expected_lift` (percentage-only, e.g. `+8-14%`), `confidence` (int 0-100).
- `competitors`: 3-4, each with `name`, `domain`, `positioning`, `makes_easier`,
  `store_edge`, `pattern_to_adapt`, `source_url`, `source_type`
  (`search|manual|site_visit|captured_artifact`), `source_manifest_id`
  (null unless `captured_artifact`).
- `technical_checks`: the 15 canonical checks (see `CANONICAL_TECH_CHECKS` in
  `harness/validate.py`), each `status` Pass|Warn|Fail with a one-line evidence-based detail.
  `evidence_manifest_id` is null or a real `pg_*` id.

## Gotchas the validator enforces

- All 5 pillars must appear (`pillar_coverage`). Aim for ~2 each (`pillar_balance` warns on skew).
- Every `evidence.manifest_id` and any non-null `*_manifest_id` must resolve to a manifest page
  (`evidence_unresolved`, `technical_check_evidence_unresolved`, `competitor_source_unresolved`).
- Dollar thresholds go in `decision_rule`, not `expected_lift`.
- `confidence > 90` warns (`overconfidence`); keep it honest.

## Validate + render

```bash
python3 harness/validate.py --audit sample_output/<slug>/audit.json --manifest artifacts/<slug>/manifest.json
python3 harness/render.py  --audit sample_output/<slug>/audit.json --out sample_output/<slug>/audit.md
```

Iterate until Gate B is clean (0 errors).
