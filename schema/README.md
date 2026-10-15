# Contracts: manifest + audit

Two JSON Schemas (Draft 2020-12) plus a set of cross-record validators define what a valid
audit run looks like. **JSON Schema validates *shape*** (required fields, types, enums,
patterns, lengths) one record at a time; **`harness/validate.py` enforces *cross-record
invariants*** that JSON Schema cannot express. Both schemas use
`additionalProperties: false`, so unknown keys are rejected.

## Why `audit.json` before `audit.md`

The writer emits a machine-readable `audit.json`, which is validated against
`audit.schema.json` **and** the crawl manifest, **before** any markdown is rendered.
Markdown is a presentation of an already-valid object — never the source of truth. This is
what prevents reports that *read* correctly but silently violate the contract (missing
fields, all-Conversion experiments, fabricated evidence paths, unresolved screenshots).

## `manifest.schema.json` — crawl artifacts

One record per captured page. Top-level: `store`, `store_url` (uri), `captured_at`
(date-time), `harness_version`, `pages` (≥1). New manifests also include `scope`, a
machine-readable coverage summary. Each page requires `id` (`^pg_[0-9a-f]{4,}$`),
`url` (uri), `status_code` (100–599), `page_type` (enum), `title`, `screenshot_path`,
`text_path`, `html_path` (the four may be `null` but the keys are required),
`discovered_from` (enum), `timestamp` (date-time). The manifest is the ground truth every
audit claim must cite. `access_status` records whether a page was accessible, blocked by
the site or bot protection, unavailable, errored, or empty; inaccessible pages are not
evidence for content claims.

## `audit.schema.json` — the report

Top-level: `store`, `store_url`, `generated_at`, `harness_version`, `executive_summary`
(≥300 chars), `experiments` (**exactly 10**), `competitors` (3–4), `technical_checks`
(13–18). Sub-objects:

- **experiment** — `exp_id` (`^exp-[0-9a-f]{12}$`), `title`, `pillar` (enum of 5), `affected_surface`,
  `url` (may be a not-yet-existing *new page*), `evidence`, `hypothesis`, `primary_change`,
  `primary_kpi`, `decision_rule`, `expected_lift`, `confidence` (0–100). `expected_lift` is
  **percentage-only** (`^\+?\d{1,3}(–|-)\d{1,3}%$`); dollar thresholds (e.g. "AOV rises by
  ≥$3") belong in `decision_rule`.
- **evidence** — `manifest_id` (must resolve to a manifest page), `url`, `screenshot_path`
  (nullable), `note` (nullable; used by new-page experiments to cite the existing artifact).
- **competitor** — `name`, `domain`, `positioning`, `makes_easier`, `store_edge`,
  `pattern_to_adapt`, plus source provenance: `source_url`, `source_type`
  (`search` | `manual` | `site_visit` | `captured_artifact`), `source_manifest_id`
  (nullable; when non-null it must match `^pg_[0-9a-f]{4,}$`, and it is required to resolve
  to a manifest page when the source was a captured artifact). The `source_*` fields extend
  "cite everything" to the competitor table.
- **technical_check** — `check`, `status` (`Pass` | `Warn` | `Fail`), `detail`,
  `evidence_manifest_id` (nullable; when non-null it must match `^pg_[0-9a-f]{4,}$` and
  resolve to a manifest page).

## Cross-record validators (`harness/validate.py`)

Errors fail the gate; warnings are reported but pass. Validators requiring the manifest are
skipped (with a warning) when no manifest is supplied. They live in a registry
(`VALIDATORS`) so new rules can be appended as new failure modes are found.

| Code | Level | Needs manifest | Checks |
|---|---|---|---|
| `pillar_coverage` | error | no | the 10 experiments span all 5 pillars |
| `exp_id_duplicate` | error | no | all `exp_id` values are unique |
| `evidence_unresolved` | error | yes | every `evidence.manifest_id` exists in the manifest |
| `evidence_path_mismatch` | warn | yes | non-null `evidence.screenshot_path` matches the manifest page |
| `new_page_evidence_note` | warn | yes | new-page experiments (url not in manifest) carry a non-empty `evidence.note` |
| `competitor_source_unresolved` | error | yes | `captured_artifact` competitors have a resolving `source_manifest_id` |
| `technical_check_evidence_unresolved` | error | yes | non-null `technical_checks[].evidence_manifest_id` resolves to a manifest page |
| `canonical_tech_checks_missing` | error | no | all 15 canonical check names are present |
| `pillar_balance` | warn | no | no pillar has a lone experiment while another carries ≥3 |
| `host_mismatch` | warn | no | experiment URLs share the store host; competitor domain ≠ store domain |
| `overconfidence` | warn | no | flags any `confidence > 90` |
| `exec_summary_paragraphs` | warn | no | executive summary is 2–3 paragraphs |

The 15 canonical technical-check names are defined once as `CANONICAL_TECH_CHECKS` in
`harness/validate.py` so the future `tech_checks.py` emits exactly the names this validator
requires.
