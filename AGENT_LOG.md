# AGENT_LOG.md

How this was built: a coding agent (Claude Code, Opus) did the implementation; I drove with
plan-mode gates, a QA review between every step, and hard scope boundaries. Time is
self-reported. Total ≈ **4h45m** (under the 5h ceiling).

## Time per part

| Part | What | Time |
|---|---|---|
| 1 | Runtime harness — contracts, crawl, reason/write, skills, sample outputs | ~2h35m |
| 2 | Eval system + autonomy plan (rubric, judge, scorecards, EVAL_LOOP.md) | ~1h40m |
| — | Docs (AGENT_LOG, WORKFLOWS, README) + final verification | ~30m |

### Part 1 breakdown
- **Step 1 — contracts & validation (~55m):** JSON schemas, `validate.py` (schema + 11
  cross-record validators), `run_audit.py` skeleton with real gates, fixtures, 7 tests.
- **Step 1 QA fix (~15m):** review caught that `technical_checks[].evidence_manifest_id`
  could cite a nonexistent page and still pass. Added a 12th validator + tightened the schema
  pattern + 2 tests.
- **Step 2 — crawl (~55m):** deterministic `discover_urls.py` (seeds → robots → sitemap →
  products.json → nav → quota'd selection) and `crawl.py`; 21 tests; live runs on both URLs.
- **Step 3 — reason/write (~30m):** skills (`qosmic-audit*`), `reason_write.py` (LLM +
  validate→repair loop), `render.py`, plus the two grounded `sample_output/` audits.

### Part 2 breakdown
- `eval/rubric/rubric.v1.yaml` (8 weighted, reference-free dimensions) + `eval/judge.py`
  (LLM-as-judge, composite + `needs_human_review`), wired into `run_eval.py` as Layer 2.
- Scorecards for both stores; `EVAL_LOOP.md` (the autonomy/self-improvement plan).

## Prompts I fed the agent (paraphrased)

1. "How should I implement this take-home?" → strategy: thin runtime, headline eval loop.
2. "Tighten this into a build plan — data contracts, not a memo." → manifest + audit JSON
   schemas, deterministic URL discovery, cross-record validators, single `run_audit.py`.
3. "Start with Step 1 only: schemas, validation, CLI skeleton, fixtures. Stop when 8
   verification commands pass."
4. "QA found a gap: tech-check evidence can cite a nonexistent page. Fix only that."
5. "Proceed to Step 2 only: deterministic discovery + crawl → real manifest. Run on both
   gingerpeople and zenrojas."
6. "Finish all the steps — I'll QA and fix later."

## Where the agent drove vs. where I took the wheel

**Agent drove (≈90% of keystrokes):** all schemas, validators, the crawler and its discovery
logic, the LLM reason/write and judge modules, the renderer, every test, and the first drafts
of all docs and both audit reports. It also self-verified each step against the gates.

**I took the wheel on:**
- **Scope discipline** — one step at a time, explicit "do not build X yet" boundaries, plan
  approval before any code.
- **The QA catch** — spotting the technical-check evidence hole the agent's own tests missed.
- **The WAF judgment call** — gingerpeople 403s every HTTP client (confirmed Cloudflare "Just
  a moment…"). I chose *not* to chase a browser bypass and instead ship an honest,
  access-limited audit, and let the eval flag it (`needs_human_review: true`, 64/100).
- **Honesty bar** — zenrojas is fully evidence-grounded; gingerpeople is explicitly framed as
  degraded rather than fabricating PDP content the crawler never saw.

## Known gaps (for QA)
- gingerpeople has no content-level experiments (crawl blocked); fix is a real-browser fetch
  fallback for WAF'd sites, then re-run.
- `reason_write.py` / `judge.py` need `ANTHROPIC_API_KEY`; the committed audits and Layer-2
  scores were produced by the agent acting as the audit agent / judge against the same
  contracts and rubric (noted in each scorecard's `layer2.produced_by`).
