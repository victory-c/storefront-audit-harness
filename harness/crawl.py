#!/usr/bin/env python3
"""Crawl/capture discovered pages into artifacts + a schema-valid manifest.

``crawl_store`` calls ``discover_urls``, fetches each page, writes text/HTML (and
optionally a screenshot) artifacts, and emits ``artifacts/<store>/manifest.json``
matching ``schema/manifest.schema.json``.

Network access is isolated in ``fetch_page`` / ``_capture_screenshot`` so tests
can monkeypatch them. Screenshots are best-effort: skipped unless Playwright is
present *and* ``QOSMIC_SCREENSHOTS=1`` — never a hard dependency, never fatal.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from harness.discover_urls import (
    discover_urls,
    extract_title,
    http_get,
    normalize_url,
)
from harness.version import HARNESS_VERSION

__all__ = ["PageFetch", "fetch_page", "crawl_store", "page_id"]

DEFAULT_FETCH_TIMEOUT = 20


@dataclass
class PageFetch:
    status_code: int
    content_type: str
    body: Optional[bytes]
    text: Optional[str]
    title: Optional[str]
    is_html: bool
    error: Optional[str]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def page_id(url: str) -> str:
    """Deterministic, schema-compliant id: pg_ + first 8 sha1 hex of the
    normalized URL."""
    digest = hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:8]
    return f"pg_{digest}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rel(out_dir: str, store: str, filename: str) -> str:
    return "/".join([out_dir.rstrip("/"), store, "pages", filename])


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    import html as _html
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_page(url: str, timeout: int = DEFAULT_FETCH_TIMEOUT) -> PageFetch:
    status, body, ctype, error = http_get(url, timeout)
    if status is None:
        return PageFetch(599, "", None, None, None, False, error or "no response")
    is_html = "html" in (ctype or "")
    text, title = None, None
    if body is not None:
        decoded = body.decode("utf-8", "replace")
        if is_html:
            title = extract_title(decoded)
            text = html_to_text(decoded)
        else:
            text = decoded
    return PageFetch(status, ctype or "", body, text, title, is_html, None)


def _capture_screenshot(url: str, abs_path: str) -> bool:
    """Best-effort screenshot. Off unless QOSMIC_SCREENSHOTS is truthy and
    Playwright is importable + working. Never raises."""
    if os.environ.get("QOSMIC_SCREENSHOTS", "").lower() not in ("1", "true", "yes"):
        return False
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page()
            page.goto(url, timeout=20000, wait_until="domcontentloaded")
            page.screenshot(path=abs_path, full_page=False)
            browser.close()
        return True
    except Exception:
        return False


def _write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _write_bytes(path: str, content: bytes) -> None:
    with open(path, "wb") as f:
        f.write(content)


# --------------------------------------------------------------------------- #
# Crawl
# --------------------------------------------------------------------------- #
def crawl_store(store_url: str, store: str, out_dir: str = "artifacts",
                max_pages: int = 15) -> dict:
    discovered = discover_urls(store_url, max_pages=max_pages)

    store_dir = os.path.join(out_dir, store)
    pages_dir = os.path.join(store_dir, "pages")
    os.makedirs(pages_dir, exist_ok=True)

    pages = []
    for d in discovered:
        pid = page_id(d.url)
        fetched = fetch_page(d.url)
        timestamp = _now_iso()

        # text artifact — always written (page text or an error summary)
        text_abs = os.path.join(pages_dir, f"{pid}.txt")
        if fetched.error:
            text_content = (f"FETCH ERROR (status {fetched.status_code}) for {d.url}\n"
                            f"{fetched.error}\n")
        else:
            text_content = fetched.text if fetched.text is not None else ""
        _write_text(text_abs, text_content)
        text_rel = _rel(out_dir, store, f"{pid}.txt")

        # html artifact — only when we actually got HTML
        html_rel = None
        if fetched.is_html and fetched.body is not None:
            _write_bytes(os.path.join(pages_dir, f"{pid}.html"), fetched.body)
            html_rel = _rel(out_dir, store, f"{pid}.html")

        # screenshot — best effort
        screenshot_rel = None
        shot_abs = os.path.join(pages_dir, f"{pid}.png")
        if _capture_screenshot(d.url, shot_abs):
            screenshot_rel = _rel(out_dir, store, f"{pid}.png")

        pages.append({
            "id": pid,
            "url": d.url,
            "status_code": fetched.status_code,
            "page_type": d.page_type,
            "title": fetched.title,
            "screenshot_path": screenshot_rel,
            "text_path": text_rel,
            "html_path": html_rel,
            "discovered_from": d.discovered_from,
            "timestamp": timestamp,
        })

    parsed = normalize_url(store_url)
    from urllib.parse import urlparse
    home = f"https://{urlparse(parsed).netloc}/"

    manifest = {
        "store": store,
        "store_url": home,
        "captured_at": _now_iso(),
        "harness_version": HARNESS_VERSION,
        "pages": pages,
    }

    manifest_path = os.path.join(store_dir, "manifest.json")
    _write_text(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest
