# qosmic-audit-harness — agent entry point

This repo turns a coding agent into a **Qosmic Shopify CRO audit agent**: point it at a
storefront URL, get one structured audit report. This file is the minimal contract an
agent needs to operate the harness.

> Step 1 status: only the **contract + validation layer** exists. Crawl/reason/write land
> in Steps 2/3. The eval-loop narrative lives elsewhere (later deliverable), and it will
> reference the real gates defined here.

## The three phases

1. **Crawl** — visit the storefront, capture artifacts (screenshots, page text, HTML,
   status) for a representative set of surfaces, and write `artifacts/<store>/manifest.json`.
2. **Reason** — over the manifest, identify revenue leaks across the five pillars
   (Conversion / AOV / Retention / Acquisition / Performance) and construct experiments
   with explicit hypotheses and evidence citations.
3. **Write** — emit `audit.json` (validated), then render `audit.md`.

## The two gates (hard, deterministic)

- **Gate A — manifest validates.** `harness.validate.validate_manifest(manifest)` must
  pass before reasoning begins.
- **Gate B — audit validates against schema + manifest.**
  `harness.validate.validate_audit(audit, manifest)` must pass before rendering. Gate B
  runs JSON-Schema shape checks first, then cross-record invariants (pillar coverage,
  unique experiment ids, every evidence citation resolves to a real manifest page, the
  canonical technical-check set is present, and more). Errors fail the gate; warnings are
  reported but do not.

Both gates run inside the single command and abort the run on failure — no partial reports.

## Single command

```bash
python3 run_audit.py --url https://gingerpeople.com --store gingerpeople
```

The reason/write phase (Step 3) is intentionally **not implemented yet** — without
`--skip-write` or `--audit`, the command raises a clear `NotImplementedError` after a
successful crawl.

## Step 2: crawl → manifest (implemented)

`--skip-write` runs discovery + crawl + Gate A and stops before reason/write. This is the
way to produce a manifest today:

```bash
python3 run_audit.py --url https://gingerpeople.com --store gingerpeople --skip-write
python3 run_audit.py --url https://zenrojas.com --store zenrojas --skip-write
```

Output (manifest **only** — no audit/report is generated in Step 2):

```text
artifacts/<store>/manifest.json
artifacts/<store>/pages/<page_id>.{txt,html,png}
```

Validate a produced manifest:

```bash
python3 harness/validate.py --manifest artifacts/<store>/manifest.json
```

Notes: discovery is deterministic (seeds → robots sitemaps → sitemap(s) → `products.json`
→ one-hop nav → quota'd selection). Screenshots are best-effort and skipped unless
Playwright is present and `QOSMIC_SCREENSHOTS=1`. Sites behind bot protection may return
non-200 (e.g. 403/599); those are recorded honestly and the manifest still validates.

## Step 1 verification

```bash
python3 run_audit.py --url https://gingerpeople.com --validate-only \
    --audit tests/fixtures/audit.valid.json \
    --manifest tests/fixtures/manifest.valid.json
```

See `schema/README.md` for the full contract and the list of cross-record validators.
