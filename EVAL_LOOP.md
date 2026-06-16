# EVAL_LOOP.md — how the eval becomes autonomous & self-learning

## What exists today (the substrate the loop runs on)

Every audit is scored by a two-layer eval that already runs in this repo:

- **Layer 1 — deterministic contract gate** (`harness/validate.py`, reused verbatim by
  `eval/run_eval.py`): schema + 11 cross-record invariants (pillar coverage, evidence
  resolvability, canonical tech-check set, overconfidence, …). Binary, free, no LLM. The
  harness and the eval share this code, so a report can never pass the writer and fail the
  eval, or vice-versa.
- **Layer 2 — reference-free rubric judge** (`eval/judge.py` + `eval/rubric/rubric.v1.yaml`):
  an LLM scores 8 weighted dimensions 0–5 against the report's **own cited artifacts** (not a
  golden answer), producing a 0–100 composite and a `needs_human_review` flag at
  `review_threshold: 70`. Because it's reference-free, it scores stores it has never seen.

This already discriminates: in the committed scorecards, **zenrojas = 81.0 (auto-pass)** and
**gingerpeople = 64.0 → `needs_human_review: true`** (its crawl was bot-blocked, so the audit
is thin — the eval caught that without a human). That flag is the entry point for the loop.

## The flywheel (how it improves itself)

1. **Score everything, log every low dimension** with the judge's justification, keyed to
   `exp_id`/`pg_id`. This is structured training signal, not a number.
2. **Failure mining (weekly, automated):** cluster low-scoring dimensions across many audits.
   "Performance experiments keep losing `evidence_groundedness`" or "AOV is generic on
   single-SKU stores" become named, recurring defects.
3. **Eval rewrites the harness:** each cluster is turned into a patch to the skill bodies
   (`skills/qosmic-audit-*`) or a new Layer-1 validator in the `VALIDATORS` registry (it was
   built to be appended to). A coding agent drafts the diff; eval output → harness change.
4. **Eval-gated promotion (CI):** a candidate harness version is re-run on a frozen fleet of
   real stores; it promotes **only** if mean composite rises **and no pillar regresses**.
   This is evolutionary search over prompts with the eval as the reward — the same mechanism
   that turns "we noticed a defect" into "the defect is gone, provably."
5. **Judge calibration (meta-eval):** a small human-rated holdout tracks judge↔human
   correlation. When they drift, the rubric is versioned forward (`rubric.v2.yaml`) and the
   judge re-validated. The rubric, not the model, is the asset we improve.

## 1–3 months out, and where humans shrink

- **Month 0 (now):** humans rate a sample, own the rubric, hand-write harness fixes. The
  `needs_human_review` flag already triages *which* audits a human must look at.
- **Month 1:** humans only adjudicate (a) judge↔human disagreements and (b) audits below
  threshold. Harness fixes land as **human-approved PRs** gated by the frozen-fleet promotion
  test — agents draft, the eval decides, a human approves the merge.
- **Months 2–3:** the promotion gate auto-merges harness patches that improve held-out
  composite without pillar regression; humans review only the **rubric changelog** and the
  shrinking set of judge-confident-but-low-score "blind spots."

**The shrink mechanism:** every recurring human correction becomes either a Layer-1 validator
(deterministic, never asked again) or a rubric edit (asked once, at the rubric level). Human
attention moves from *per-report* → *per-defect-class* → *per-rubric-version*.

## The end state: real outcomes replace human judgment

The terminal reward is not the judge — it's money. As proposed experiments actually ship,
their realized lift becomes a label. The loop back-tests the judge against outcomes
("experiments the judge scored ≥4 on groundedness — did they win more often?") and recalibrates
`confidence`/`expected_lift` from data. Humans stop scoring quality and start setting the
reward function; the judge stops being the ground truth and becomes a fast, cheap proxy for it.
