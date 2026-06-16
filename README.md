# qosmic-audit-harness

A runtime harness that turns any coding agent into **Qosmic's Shopify CRO audit agent**:
point it at a storefront URL, get one evidence-grounded audit report — plus a **self-improving
eval system** around it.

> The original take-home brief is preserved in [BRIEF.md](BRIEF.md). The eval/autonomy story
> is the headline: [EVAL_LOOP.md](EVAL_LOOP.md).

## The shape of it

```
URL ──▶ Crawl ──▶ manifest.json ──▶ [Gate A] ──▶ Reason ──▶ Write ──▶ audit.json ──▶ [Gate B] ──▶ audit.md
                  (artifacts on disk)                                  (validated)              (rendered)
                                                              │
                                         eval/run_eval.py ◀───┘   Layer 1 = the same gate
                                         Layer 2 = reference-free LLM-judge over a rubric → scorecard
```

The load-bearing idea: **contracts first.** A report is a validated JSON object before it is
ever Markdown, and the harness writer and the evaluator share the exact same validation code,
so they can never drift. Evidence discipline is mechanical — every claim must cite a real
crawled page (`pg_*`), enforced by the validator, not by vibes.

## Quickstart

```bash
pip install -r requirements.txt    # core is stdlib + jsonschema; anthropic/pyyaml are optional

# Step 2 — crawl to a validated manifest (no LLM, deterministic):
python3 run_audit.py --url https://zenrojas.com --store zenrojas --skip-write
python3 harness/validate.py --manifest artifacts/zenrojas/manifest.json

# Full pipeline (needs ANTHROPIC_API_KEY for reason/write):
python3 run_audit.py --url https://zenrojas.com --store zenrojas

# Validate any audit against the contract (Gate B), then render + score:
python3 harness/validate.py --audit sample_output/zenrojas/audit.json --manifest artifacts/zenrojas/manifest.json
python3 harness/render.py   --audit sample_output/zenrojas/audit.json --out sample_output/zenrojas/audit.md
python3 eval/run_eval.py    --audit sample_output/zenrojas/audit.json --manifest artifacts/zenrojas/manifest.json --out eval_output/zenrojas_scorecard.json
```

No API key? An agent produces `audit.json` by hand following `skills/qosmic-audit-write/`,
then validates with the same gate — that's how the committed sample outputs were made.

## Layout

| Path | What |
|---|---|
| `schema/` | The two contracts (`manifest`, `audit`) + `schema/README.md` (every validator) |
| `harness/` | `discover_urls`, `crawl`, `validate`, `reason_write`, `render`, `version` |
| `eval/` | `run_eval` (Layer 1+2), `judge`, `rubric/rubric.v1.yaml` |
| `skills/` | `qosmic-audit` + `-reason` / `-write` — the agent-facing runtime harness |
| `run_audit.py` | Single command: crawl → Gate A → reason/write → Gate B → render |
| `artifacts/<store>/` | Crawl output: `manifest.json` + `pages/*.{txt,html}` |
| `sample_output/<store>/` | `audit.json` (validated) + `audit.md` (rendered) |
| `eval_output/` | Per-store scorecards (Layer 1 gate + Layer 2 rubric scores) |
| `AGENTS.md` | Agent entry point. Deliverable docs: `EVAL_LOOP.md`, `AGENT_LOG.md`, `WORKFLOWS.md` |

## Sample outputs (run on both required stores)

- **zenrojas** — 15 pages crawled (HTTP 200), a fully evidence-grounded audit. Eval composite
  **81.0** (auto-pass). This is the showcase of generalization to an uncalibrated store.
- **gingerpeople** — every surface returns a Cloudflare "Just a moment…" **403** to HTTP
  clients, so the audit is honestly scoped to the access barrier and its cross-pillar
  consequences (no fabricated content). Eval composite **64.0 → `needs_human_review: true`** —
  the eval correctly flags its own thin input. Fixing it means a real-browser fetch fallback.

## Tests

```bash
python3 -m pytest tests/ -q
```

Covers the contract validators, deterministic URL discovery, and the crawl (network mocked —
no live internet needed).
