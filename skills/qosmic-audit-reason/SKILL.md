---
name: qosmic-audit-reason
description: >
  Reason over crawl artifacts to find revenue leaks across five CRO pillars and construct
  experiments with explicit hypotheses and evidence citations. Use during the Reason phase
  of a Qosmic audit.
---

# Reason: artifacts → experiments

Input: `artifacts/<slug>/manifest.json` + the `pages/*.txt` excerpts. Output: 10 experiment
ideas, ~2 per pillar, each tied to a specific captured page (`pg_*`).

## Evidence discipline (the bar)

- One experiment = one observed leak. If you cannot point to a line in a captured artifact,
  do not write the experiment.
- A **new page** is allowed, but its evidence must cite the *existing* artifact that proves
  the need (and you set `evidence.note` to explain the link).
- Lower `confidence` when evidence is thin; never pad confidence to look certain.

## Pillar leak checklist (look for these in the artifacts)

- **Conversion** — PDP missing price/CTA/social proof; ambiguous "how to buy"; weak/empty
  cart; broken or dead-end pages (404s in the manifest); buried primary nav intent.
- **AOV** — single-SKU consumables with no bundle/sampler/kit; free-ship threshold far above
  unit price with no cart progress nudge; no cross-sell on PDP.
- **Retention** — no subscribe-and-save on a reorderable consumable; no post-purchase routine
  or email capture; loyalty/ambassador program under-leveraged.
- **Acquisition** — missing structured data / thin meta; recipe/education content not turned
  into landing pages; symptom/use-case intent with no dedicated destination.
- **Performance** — large hero/image assets; 404/5xx in the manifest; checkout/cart edge
  unreachable; slow critical pages.

## Output per experiment (hand to the Write phase)

title, pillar, affected_surface, url (existing or proposed new), evidence (`pg_*` id + url +
optional note), hypothesis (specific + falsifiable), primary_change (control→variant),
primary_kpi, decision_rule (include any $ thresholds here, not in lift), expected_lift
(percentage range), confidence (0-100). Ensure all five pillars appear.
