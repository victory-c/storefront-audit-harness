# Storefront Audit Harness

A standalone, evidence-grounded harness for auditing public Shopify storefronts. Point it at a
store URL to capture a bounded set of public pages, validate the crawl manifest, and optionally
produce a structured CRO report through an LLM writer. The report is only rendered after its
JSON contract and evidence references pass validation.

## Scope and limitations

This tool audits publicly reachable storefront surfaces only. It does not log in, add products
to carts, submit checkout or forms, bypass bot protection, inspect analytics, or claim that a
recommendation caused a lift. A page is evidence only when its crawl artifact is accessible.
HTTP 401/403/429/503 responses are recorded as `blocked`; network failures and other 4xx/5xx
responses are recorded separately. The manifest includes a `scope` summary and every report
must be interpreted within that captured coverage. A blocked run is a valid record of an access
barrier, not a content audit.

## Getting started

Use Python 3.10+ and install the core dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

Run a deterministic crawl and stop after Gate A (no LLM or API key required):

```bash
python run_audit.py --url https://example-store.com --store example-store --skip-write
python harness/validate.py --manifest artifacts/example-store/manifest.json
```

Artifacts are written under `artifacts/<store>/`: a manifest plus one text file per discovered
page and HTML files when an HTML response was captured. The default crawl is capped at 15 pages;
use `--max-pages` to choose a smaller or larger bounded run.

To generate a report, set an Anthropic API key and optionally select a model. The writer uses
only the captured artifacts and retries contract failures a bounded number of times:

```bash
export ANTHROPIC_API_KEY='…'
export STOREFRONT_AUDIT_MODEL='claude-opus-4-8'  # optional
python run_audit.py --url https://example-store.com --store example-store
```

If an API key is not available, an agent or operator can create `audit.json` using
`skills/storefront-audit-write/SKILL.md`, then validate and render it:

```bash
python harness/validate.py \
  --audit sample_output/example-store/audit.json \
  --manifest artifacts/example-store/manifest.json
python harness/render.py \
  --audit sample_output/example-store/audit.json \
  --out sample_output/example-store/audit.md
```

Screenshots are optional and never required for a valid crawl. Enable the best-effort Playwright
path with `STOREFRONT_AUDIT_SCREENSHOTS=1`; browser binaries must already be installed.

## Pipeline

```
URL → bounded discovery/crawl → manifest + scope summary → Gate A
    → reason/write (optional) → audit.json → Gate B → audit.md
```

The contracts are in `schema/`. `harness/validate.py` enforces both JSON-Schema shape and
cross-record rules such as unique experiments, five-pillar coverage, and evidence citations
resolving to captured page IDs. When a manifest includes `access_status`, Gate B rejects
content-level experiment and technical-check evidence cited from `blocked` or `error` pages;
explicit access-barrier findings remain valid. Manifests from older runs without that field
remain compatible. The evaluator in `eval/` adds a reference-free rubric and an optional LLM
judge; it does not turn inaccessible pages into evidence.

## Layout

| Path | Purpose |
|---|---|
| `schema/` | Manifest and audit contracts plus validator documentation |
| `harness/` | URL discovery, crawling, validation, LLM write, rendering, versioning |
| `eval/` | Contract scoring and optional rubric judge |
| `skills/` | Agent-facing crawl, reasoning, and write instructions |
| `run_audit.py` | Crawl → Gate A → optional report → Gate B → render |
| `artifacts/<store>/` | Crawl output and scope metadata |
| `sample_output/<store>/` | Checked-in example reports |

## Tests

```bash
python -m pytest tests/ -q
```

The suite covers schema validation, evidence invariants, deterministic discovery, and mocked
crawl behavior without requiring live internet access or an API key.
