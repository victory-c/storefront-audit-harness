#!/usr/bin/env python3
"""storefront-audit-harness — single audit command.

Pipeline and gates:

    Crawl  -> manifest.json  -> Gate A: validate_manifest        (Step 2, live)
    Reason/Write -> audit.json -> Gate B: validate_audit(...)     (Step 3, pending)
    Render -> audit.md                                           (Step 3, pending)

Step 2 implements real discovery + crawl. Use --skip-write to run
discovery + crawl + Gate A and stop before reason/write (which still raises
NotImplementedError until Step 3).

    python3 run_audit.py --url https://gingerpeople.com --store gingerpeople --skip-write
    python3 run_audit.py --url https://gingerpeople.com --validate-only \\
        --audit tests/fixtures/audit.valid.json \\
        --manifest tests/fixtures/manifest.valid.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from harness.crawl import crawl_store  # noqa: E402
from harness.discover_urls import site_host  # noqa: E402
from harness.validate import validate_audit, validate_manifest  # noqa: E402

ARTIFACTS_DIR = "artifacts"


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def default_store_slug(url: str) -> str:
    return site_host(url).split(".")[0] or "store"


def reason_and_write(url: str, store, manifest: dict) -> dict:
    from harness.reason_write import generate_audit
    return generate_audit(manifest, url, store)


def write_outputs(audit: dict, out_root: str, store: str) -> tuple:
    from harness.render import render_markdown
    out_dir = os.path.join(out_root, store)
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "audit.json")
    md_path = os.path.join(out_dir, "audit.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(audit) + "\n")
    return json_path, md_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a Storefront Audit Shopify CRO audit (Step 2: crawl -> manifest + Gate A).")
    parser.add_argument("--url", required=True, help="Shopify storefront URL")
    parser.add_argument("--store", help="Short store slug (e.g. gingerpeople)")
    parser.add_argument("--out", default="sample_output/", help="Output directory")
    parser.add_argument("--audit", help="Pre-built audit.json (skips reason/write)")
    parser.add_argument("--manifest", help="Pre-built manifest.json (skips crawl)")
    parser.add_argument("--validate-only", action="store_true",
                        help="Only run Gate A/B against supplied --manifest/--audit")
    parser.add_argument("--skip-crawl", action="store_true",
                        help="Reserved for later steps")
    parser.add_argument("--skip-write", action="store_true",
                        help="Run discovery + crawl + Gate A, then stop before reason/write")
    parser.add_argument("--max-pages", type=int, default=15,
                        help="Max pages to crawl (default 15)")
    args = parser.parse_args(argv)

    # --- Crawl phase / manifest ---
    if args.manifest:
        manifest = _load_json(args.manifest)
    elif args.validate_only:
        print("ERROR: --validate-only requires --manifest (no crawler runs in this mode).",
              file=sys.stderr)
        return 1
    else:
        store = args.store or default_store_slug(args.url)
        print(f"== Crawling {args.url} (store='{store}', max_pages={args.max_pages}) ==")
        manifest = crawl_store(args.url, store, out_dir=ARTIFACTS_DIR,
                               max_pages=args.max_pages)
        print(f"Captured {len(manifest['pages'])} page(s) -> "
              f"{ARTIFACTS_DIR}/{store}/manifest.json")

    report_a = validate_manifest(manifest)
    print("== Gate A: manifest ==")
    print(report_a.summary())
    if not report_a.ok:
        print("Gate A failed — aborting.", file=sys.stderr)
        return 1

    if args.skip_write:
        print("Manifest validated; stopping before reason/write (--skip-write).")
        return 0

    store = args.store or manifest.get("store") or default_store_slug(args.url)

    # --- Reason/write phase / audit ---
    if args.audit:
        audit = _load_json(args.audit)
    elif args.validate_only:
        print("ERROR: --validate-only requires --audit (no writer runs in this mode).",
              file=sys.stderr)
        return 1
    else:
        print("== Reason/Write: generating audit.json ==")
        audit = reason_and_write(args.url, store, manifest)

    report_b = validate_audit(audit, manifest)
    print("== Gate B: audit ==")
    print(report_b.summary())
    if not report_b.ok:
        print("Gate B failed — aborting.", file=sys.stderr)
        return 1

    if not args.validate_only:
        json_path, md_path = write_outputs(audit, args.out, store)
        print(f"Wrote {json_path} and {md_path}")
    print("Gates A and B passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
