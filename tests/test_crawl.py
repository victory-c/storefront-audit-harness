"""Unit tests for the crawl phase (network mocked via monkeypatch)."""
import json
import os
import re
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from harness import crawl  # noqa: E402
from harness.crawl import PageFetch, access_status, crawl_store, page_id  # noqa: E402
from harness.discover_urls import DiscoveredURL, TYPE_PRIORITY  # noqa: E402
from harness.validate import validate_manifest  # noqa: E402


def _du(url, page_type, src="sitemap"):
    return DiscoveredURL(url, page_type, src, TYPE_PRIORITY[page_type])


def _fixed_discovery():
    return [
        _du("https://shop.example.com/", "homepage", "seed"),
        _du("https://shop.example.com/products/widget", "product", "sitemap"),
        _du("https://shop.example.com/cart", "cart", "seed"),
    ]


def _fake_fetch(url, timeout=20):
    if url.endswith("/cart"):
        # Simulate a hard network failure (no HTTP response).
        return PageFetch(599, "", None, None, None, False, "ConnectionError: boom")
    body = b"<html><head><title>Widget</title></head><body>Buy the widget</body></html>"
    return PageFetch(200, "text/html", body, "Buy the widget", "Widget", True, None)


def _patch(monkeypatch):
    monkeypatch.setattr(crawl, "discover_urls", lambda store_url, max_pages=15: _fixed_discovery())
    monkeypatch.setattr(crawl, "fetch_page", _fake_fetch)
    monkeypatch.setattr(crawl, "_capture_screenshot", lambda url, path: False)


def test_crawl_writes_valid_manifest(tmp_path, monkeypatch):
    _patch(monkeypatch)
    manifest = crawl_store("https://shop.example.com", "example", out_dir=str(tmp_path))

    assert (tmp_path / "example" / "manifest.json").exists()
    report = validate_manifest(manifest)
    assert report.ok, report.summary()
    assert manifest["store"] == "example"
    assert manifest["store_url"] == "https://shop.example.com/"
    assert len(manifest["pages"]) == 3


def test_page_ids_are_deterministic_and_well_formed(tmp_path, monkeypatch):
    _patch(monkeypatch)
    manifest = crawl_store("https://shop.example.com", "example", out_dir=str(tmp_path))
    for p in manifest["pages"]:
        assert re.match(r"^pg_[0-9a-f]{4,}$", p["id"])
    cart = next(p for p in manifest["pages"] if p["url"].endswith("/cart"))
    assert cart["id"] == page_id("https://shop.example.com/cart")


def test_failed_fetch_records_599_and_text_artifact(tmp_path, monkeypatch):
    _patch(monkeypatch)
    manifest = crawl_store("https://shop.example.com", "example", out_dir=str(tmp_path))
    cart = next(p for p in manifest["pages"] if p["url"].endswith("/cart"))
    assert cart["status_code"] == 599
    assert cart["access_status"] == "error"
    assert cart["html_path"] is None
    assert cart["screenshot_path"] is None
    txt = tmp_path / "example" / "pages" / f"{cart['id']}.txt"
    assert txt.exists()
    assert "FETCH ERROR" in txt.read_text()


def test_scope_summary_distinguishes_accessible_and_inaccessible_pages(tmp_path, monkeypatch):
    _patch(monkeypatch)
    manifest = crawl_store("https://shop.example.com", "example", out_dir=str(tmp_path))
    assert manifest["scope"] == {
        "pages_requested": 3,
        "pages_accessible": 2,
        "pages_inaccessible": 1,
        "coverage": "partial",
        "disclaimer": "Claims are limited to captured artifacts; blocked or unavailable pages were not inspected.",
    }
    assert validate_manifest(manifest).ok


def test_scope_summary_counts_empty_pages_as_inaccessible(tmp_path, monkeypatch):
    _patch(monkeypatch)

    def fetch_with_empty_product(url, timeout=20):
        if url.endswith("/products/widget"):
            return PageFetch(200, "text/html", b"", "", None, True, None)
        return _fake_fetch(url, timeout)

    monkeypatch.setattr(crawl, "fetch_page", fetch_with_empty_product)
    manifest = crawl_store("https://shop.example.com", "example", out_dir=str(tmp_path))

    assert manifest["scope"]["pages_accessible"] == 1
    assert manifest["scope"]["pages_inaccessible"] == 2
    assert manifest["scope"]["coverage"] == "partial"


def test_crawl_rejects_unsafe_store_slugs_before_writing(tmp_path, monkeypatch):
    _patch(monkeypatch)
    for slug in ("../escape", "/tmp/escape"):
        try:
            crawl_store("https://shop.example.com", slug, out_dir=str(tmp_path))
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe slug accepted: {slug}")
    assert list(tmp_path.iterdir()) == []


def test_bot_protection_status_is_blocked_not_unavailable():
    response = PageFetch(403, "text/html", b"Just a moment", "Just a moment", None, True, None)
    assert access_status(response) == "blocked"


def test_html_page_gets_html_artifact_and_title(tmp_path, monkeypatch):
    _patch(monkeypatch)
    manifest = crawl_store("https://shop.example.com", "example", out_dir=str(tmp_path))
    product = next(p for p in manifest["pages"] if p["url"].endswith("/products/widget"))
    assert product["status_code"] == 200
    assert product["title"] == "Widget"
    assert product["html_path"] is not None
    assert (tmp_path / "example" / "pages" / f"{product['id']}.html").exists()


def test_manifest_paths_are_relative_to_out_dir(tmp_path, monkeypatch):
    _patch(monkeypatch)
    manifest = crawl_store("https://shop.example.com", "example", out_dir="artifacts")
    # Paths in the manifest use the given out_dir prefix, forward-slashed.
    home = next(p for p in manifest["pages"] if p["page_type"] == "homepage")
    assert home["text_path"].startswith("artifacts/example/pages/")
    # Clean up the artifacts written at repo root by this path-format check.
    import shutil
    shutil.rmtree(os.path.join(_REPO_ROOT, "artifacts", "example"), ignore_errors=True)
