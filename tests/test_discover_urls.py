"""Unit tests for deterministic URL discovery (no live network)."""
import os
import random
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from harness.discover_urls import (  # noqa: E402
    DiscoveredURL,
    TYPE_PRIORITY,
    _dedupe_key,
    classify_nav_link,
    classify_url,
    extract_links,
    extract_sitemaps_from_robots,
    normalize_url,
    parse_sitemap_xml,
    select_representative,
)


def _u(url, page_type, discovered_from="sitemap"):
    return DiscoveredURL(url, page_type, discovered_from, TYPE_PRIORITY[page_type])


# --------------------------------------------------------------------------- #
# Normalization / dedupe
# --------------------------------------------------------------------------- #
def test_normalize_forces_https_and_root_slash():
    assert normalize_url("gingerpeople.com") == "https://gingerpeople.com/"
    assert normalize_url("http://x.com") == "https://x.com/"


def test_normalize_lowercases_host_strips_trailing_slash_keeps_path_case():
    assert normalize_url("https://www.Example.com/Path/") == "https://www.example.com/Path"


def test_dedupe_treats_www_and_non_www_as_same():
    assert _dedupe_key("https://www.x.com/a/") == _dedupe_key("https://x.com/a")
    assert _dedupe_key("https://x.com/") == _dedupe_key("http://X.com")


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def test_classify_url_by_path():
    assert classify_url("https://x.com/") == "homepage"
    assert classify_url("https://x.com/products/widget") == "product"
    assert classify_url("https://x.com/collections/all") == "collection"
    assert classify_url("https://x.com/pages/faq") == "content"
    assert classify_url("https://x.com/blogs/news/post") == "blog"
    assert classify_url("https://x.com/policies/refund-policy") == "policy"
    assert classify_url("https://x.com/cart") == "cart"
    assert classify_url("https://x.com/sitemap.xml") == "sitemap"
    assert classify_url("https://x.com/robots.txt") == "robots"
    assert classify_url("https://x.com/some-random-page") == "other"


def test_classify_nav_link_bumps_keywords_to_content():
    assert classify_nav_link("https://x.com/where-to-buy") == "content"
    assert classify_nav_link("https://x.com/pages/faq") == "content"
    assert classify_nav_link("https://x.com/random") == "other"


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #
def test_extract_sitemaps_from_robots_case_insensitive():
    robots = (
        "User-agent: *\n"
        "Disallow: /admin\n"
        "Sitemap: https://x.com/sitemap.xml\n"
        "sitemap: https://x.com/sitemap_products_1.xml\n"
    )
    assert extract_sitemaps_from_robots(robots) == [
        "https://x.com/sitemap.xml",
        "https://x.com/sitemap_products_1.xml",
    ]


def test_parse_sitemap_index_returns_sitemaps():
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<sitemap><loc>https://x.com/sitemap_products_1.xml</loc></sitemap>'
        '<sitemap><loc>https://x.com/sitemap_pages_1.xml</loc></sitemap>'
        '</sitemapindex>'
    )
    sitemaps, pages = parse_sitemap_xml(xml)
    assert pages == []
    assert sitemaps == [
        "https://x.com/sitemap_products_1.xml",
        "https://x.com/sitemap_pages_1.xml",
    ]


def test_parse_sitemap_urlset_returns_pages():
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<url><loc>https://x.com/products/a</loc></url>'
        '<url><loc>https://x.com/products/b</loc></url>'
        '</urlset>'
    )
    sitemaps, pages = parse_sitemap_xml(xml)
    assert sitemaps == []
    assert pages == ["https://x.com/products/a", "https://x.com/products/b"]


def test_parse_sitemap_handles_garbage():
    assert parse_sitemap_xml("not xml at all") == ([], [])


def test_extract_links_resolves_and_filters():
    html = (
        '<a href="/products/widget">w</a>'
        '<a href="https://x.com/pages/faq">faq</a>'
        '<a href="mailto:hi@x.com">mail</a>'
        '<a href="#section">anchor</a>'
    )
    links = extract_links(html, "https://x.com/")
    assert "https://x.com/products/widget" in links
    assert "https://x.com/pages/faq" in links
    assert not any(l.startswith("mailto:") for l in links)
    assert not any(l.endswith("#section") for l in links)


# --------------------------------------------------------------------------- #
# Representative selection
# --------------------------------------------------------------------------- #
def _sample_set():
    return [
        _u("https://x.com/", "homepage", "seed"),
        _u("https://x.com/cart", "cart", "seed"),
        _u("https://x.com/robots.txt", "robots", "seed"),
        _u("https://x.com/sitemap.xml", "sitemap", "seed"),
        _u("https://x.com/products/a", "product"),
        _u("https://x.com/products/b", "product"),
        _u("https://x.com/products/c", "product"),
        _u("https://x.com/products/d", "product"),
        _u("https://x.com/products/e", "product"),
        _u("https://x.com/collections/all", "collection"),
        _u("https://x.com/collections/sale", "collection"),
        _u("https://x.com/collections/extra", "collection"),
        _u("https://x.com/pages/faq", "content"),
        _u("https://x.com/pages/contact", "content"),
        _u("https://x.com/blogs/news/post", "blog"),
        _u("https://x.com/policies/refund-policy", "policy"),
        _u("https://x.com/some-other", "other"),
    ]


def test_selection_spread_and_quotas():
    sel = select_representative(_sample_set(), max_pages=15)
    types = [d.page_type for d in sel]
    assert "homepage" in types
    assert "cart" in types
    assert "product" in types
    assert "collection" in types
    assert "content" in types
    assert types.count("product") <= 4
    assert types.count("collection") <= 2
    # 'other' has a zero quota and must be excluded.
    assert "other" not in types


def test_selection_is_deterministic_under_shuffle():
    data = _sample_set()
    rng = random.Random(42)
    shuffled = data[:]
    rng.shuffle(shuffled)
    a = [d.url for d in select_representative(data, max_pages=15)]
    b = [d.url for d in select_representative(shuffled, max_pages=15)]
    assert a == b


def test_selection_dedupes_www_variants():
    data = [
        _u("https://x.com/", "homepage", "seed"),
        _u("https://www.x.com/", "homepage", "nav"),
    ]
    sel = select_representative(data, max_pages=15)
    assert len([d for d in sel if d.page_type == "homepage"]) == 1
