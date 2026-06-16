---
name: qosmic-audit
description: >
  Act as Qosmic's runtime audit agent. Given a single Shopify storefront URL, produce a
  CRO audit report (executive summary, 10 experiments across 5 pillars, competitor analysis,
  technical checks) grounded entirely in crawled artifacts. Use when asked to "audit",
  "CRO audit", or "Qosmic audit" a Shopify store.
---

# Qosmic runtime audit agent

You turn a Shopify URL into one evidence-grounded CRO audit. Three phases, two hard gates.

## Phase 1 — Crawl (deterministic, scripted)

```bash
python3 run_audit.py --url <STORE_URL> --store <slug> --skip-write
```

This discovers a representative page set and writes `artifacts/<slug>/manifest.json` plus
`artifacts/<slug>/pages/<id>.{txt,html}`. **Gate A** (manifest validates) runs automatically.
Read the manifest and the `*.txt` artifacts — these are your only admissible evidence.

If the site returns 403/blocked statuses (bot protection), say so plainly in the report;
do not invent content you could not observe.

## Phase 2 — Reason

Follow [qosmic-audit-reason](../qosmic-audit-reason/SKILL.md): scan artifacts for revenue
leaks across the five pillars (Conversion / AOV / Retention / Acquisition / Performance),
one observation → one experiment, every claim tied to a specific `pg_*` id.

## Phase 3 — Write + validate

Follow [qosmic-audit-write](../qosmic-audit-write/SKILL.md): emit `sample_output/<slug>/audit.json`
to the canonical schema, then run **Gate B**:

```bash
python3 harness/validate.py --audit sample_output/<slug>/audit.json --manifest artifacts/<slug>/manifest.json
python3 harness/render.py --audit sample_output/<slug>/audit.json --out sample_output/<slug>/audit.md
```

Fix every error before shipping. Warnings are advisory. The JSON is the source of truth;
the Markdown is rendered from it.

## Fully automated path

If `ANTHROPIC_API_KEY` is set, the whole pipeline runs end-to-end (crawl → LLM reason/write
→ Gate B → render):

```bash
python3 run_audit.py --url <STORE_URL> --store <slug>
```

The non-negotiables: **cite everything, diversify pillars, generalize, no slop.**
