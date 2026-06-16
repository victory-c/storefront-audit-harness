#!/usr/bin/env python3
"""Deterministic URL discovery for a Shopify storefront.

Given a store URL, produce a representative, stable set of pages to crawl. The
parsing/classification/selection logic is pure (no network) so it can be unit
tested directly; the network steps are isolated in small helpers and fail
gracefully.

Discovery order: seeds -> robots.txt sitemaps -> sitemap(s) -> products.json
fallback -> one-hop homepage nav -> representative selection with per-type
quotas. No guessed wildcard URLs: every non-seed URL comes from sitemap, nav, or
products.json.
"""
from __future__ import annotations

import html as _html
import json
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse

__all__ = [
    "DiscoveredURL",
    "discover_urls",
    "normalize_url",
    "classify_url",
    "classify_nav_link",
    "site_host",
    "extract_links",
    "extract_sitemaps_from_robots",
    "parse_sitemap_xml",
    "select_representative",
    "page_priority",
    "TYPE_ORDER",
    "TYPE_PRIORITY",
    "DEFAULT_QUOTAS",
    "http_get",
]

DEFAULT_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
}

TYPE_ORDER = [
    "homepage", "product", "collection", "cart",
    "content", "policy", "blog", "robots", "sitemap", "other",
]
TYPE_PRIORITY = {t: i for i, t in enumerate(TYPE_ORDER)}

# Representative-selection quotas (sum = 14, under the default 15 cap).
DEFAULT_QUOTAS = {
    "homepage": 1, "product": 4, "collection": 2, "cart": 1,
    "content": 3, "policy": 1, "blog": 1, "robots": 1, "sitemap": 1, "other": 0,
}

CONTENT_KEYWORDS = (
    "where-to-buy", "where_to_buy", "whereto", "find-a-store", "store-locator",
    "stockist", "locator", "faq", "contact", "shipping", "returns", "refund",
    "wholesale", "bulk", "about", "stores", "help", "support",
)


@dataclass(frozen=True)
class DiscoveredURL:
    url: str
    page_type: str
    discovered_from: str
    priority: int


# --------------------------------------------------------------------------- #
# Normalization / classification (pure)
# --------------------------------------------------------------------------- #
def ensure_scheme(url: str) -> str:
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    return url


def normalize_url(url: str) -> str:
    """Canonical form: force https, lowercase host, strip default ports, drop
    fragment/params, and trailing-slash-normalize (root stays '/')."""
    p = urlparse(ensure_scheme(url))
    netloc = p.netloc.lower()
    if netloc.endswith(":80"):
        netloc = netloc[:-3]
    elif netloc.endswith(":443"):
        netloc = netloc[:-4]
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse(("https", netloc, path, "", p.query, ""))


def site_host(url: str) -> str:
    h = urlparse(ensure_scheme(url)).netloc.lower()
    return h[4:] if h.startswith("www.") else h


def same_site(url: str, base_host: str) -> bool:
    return site_host(url) == base_host


def _dedupe_key(url: str):
    p = urlparse(ensure_scheme(url))
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return (host, path, p.query)


def classify_url(url: str) -> str:
    path = (urlparse(ensure_scheme(url)).path or "/").lower()
    if path in ("/", ""):
        return "homepage"
    if "/products/" in path:
        return "product"
    if "/collections/" in path:
        return "collection"
    if "/pages/" in path:
        return "content"
    if "/blogs/" in path:
        return "blog"
    if "/policies/" in path:
        return "policy"
    if path.startswith("/cart"):
        return "cart"
    if "sitemap" in path:
        return "sitemap"
    if "robots" in path:
        return "robots"
    return "other"


def classify_nav_link(url: str) -> str:
    """Classify a nav link, bumping generic 'other' pages to 'content' when the
    path looks like a where-to-buy / FAQ / shipping / wholesale style page."""
    pt = classify_url(url)
    if pt == "other":
        path = urlparse(ensure_scheme(url)).path.lower()
        if any(k in path for k in CONTENT_KEYWORDS):
            return "content"
    return pt


def page_priority(page_type: str) -> int:
    return TYPE_PRIORITY.get(page_type, TYPE_PRIORITY["other"])


# --------------------------------------------------------------------------- #
# Parsers (pure)
# --------------------------------------------------------------------------- #
def extract_sitemaps_from_robots(text: str) -> list:
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            out.append(line.split(":", 1)[1].strip())
    return out


def parse_sitemap_xml(data) -> tuple:
    """Return (sitemap_index_urls, page_urls). Handles namespaced sitemaps."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return [], []
    locs = [el.text.strip() for el in root.iter()
            if el.tag.lower().endswith("loc") and el.text and el.text.strip()]
    if root.tag.lower().endswith("sitemapindex"):
        return locs, []
    return [], locs


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.hrefs.append(v)


def extract_links(html: str, base_url: str) -> list:
    parser = _LinkParser()
    try:
        parser.feed(html or "")
    except Exception:
        pass
    out = []
    for href in parser.hrefs:
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        out.append(urljoin(base_url, href))
    return out


def extract_title(html: str):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    if not m:
        return None
    title = _html.unescape(m.group(1)).strip()
    title = re.sub(r"\s+", " ", title)
    return title or None


# --------------------------------------------------------------------------- #
# Selection (pure)
# --------------------------------------------------------------------------- #
def select_representative(found, max_pages: int = 15, quotas=None) -> list:
    quotas = quotas or DEFAULT_QUOTAS
    seen, deduped = set(), []
    for d in found:
        k = _dedupe_key(d.url)
        if k in seen:
            continue
        seen.add(k)
        deduped.append(d)

    by_type = {}
    for d in deduped:
        by_type.setdefault(d.page_type, []).append(d)
    for t in by_type:
        by_type[t].sort(key=lambda d: d.url)

    selected = []
    for t in TYPE_ORDER:
        q = quotas.get(t, 0)
        if q > 0:
            selected.extend(by_type.get(t, [])[:q])

    selected.sort(key=lambda d: (d.priority, d.url))
    return selected[:max_pages]


# --------------------------------------------------------------------------- #
# Network helpers (isolated, fail-soft)
# --------------------------------------------------------------------------- #
def http_get(url: str, timeout: int = DEFAULT_TIMEOUT):
    """Return (status_code | None, body_bytes | None, content_type, error)."""
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read(), resp.headers.get_content_type(), None
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read()
        except Exception:
            pass
        ctype = e.headers.get_content_type() if e.headers else ""
        return e.code, body, ctype, None
    except Exception as e:  # URLError, timeout, SSL, etc.
        return None, None, "", f"{type(e).__name__}: {e}"


def _safe_get_text(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    status, body, _ctype, _err = http_get(url, timeout)
    if status is None or body is None or status >= 400:
        return ""
    return body.decode("utf-8", "replace")


def fetch_sitemap_urls(sitemap_urls, base_host, max_files=10, max_urls=500) -> list:
    seen_files, queue, pages, files_fetched = set(), list(sitemap_urls), [], 0
    while queue and files_fetched < max_files and len(pages) < max_urls:
        sm = queue.pop(0)
        if sm in seen_files:
            continue
        seen_files.add(sm)
        files_fetched += 1
        text = _safe_get_text(sm)
        if not text:
            continue
        subs, urls = parse_sitemap_xml(text)
        for s in subs:
            if s not in seen_files:
                queue.append(s)
        for u in urls:
            if same_site(u, base_host):
                pages.append(u)
            if len(pages) >= max_urls:
                break
    return sorted(set(pages))


def fetch_product_handles(home, limit=20) -> list:
    text = _safe_get_text(urljoin(home, f"/products.json?limit={limit}"))
    if not text:
        return []
    try:
        data = json.loads(text)
    except Exception:
        return []
    handles = [p.get("handle") for p in data.get("products", []) if p.get("handle")]
    return sorted(set(handles))


def fetch_nav_links(home, base_host) -> list:
    html = _safe_get_text(home)
    if not html:
        return []
    out, seen = [], set()
    for u in extract_links(html, home):
        nu = normalize_url(u)
        if not same_site(nu, base_host):
            continue
        k = _dedupe_key(nu)
        if k in seen:
            continue
        seen.add(k)
        out.append((nu, classify_nav_link(nu)))
    return out


# --------------------------------------------------------------------------- #
# Orchestration (live)
# --------------------------------------------------------------------------- #
def discover_urls(store_url: str, max_pages: int = 15) -> list:
    p = urlparse(normalize_url(store_url))
    home = f"https://{p.netloc}/"
    base_host = site_host(home)
    found = []

    def add(url, page_type, src):
        nurl = normalize_url(url)
        if not same_site(nurl, base_host):
            return
        pt = page_type or classify_url(nurl)
        found.append(DiscoveredURL(nurl, pt, src, page_priority(pt)))

    # Seeds (always present)
    add(home, "homepage", "seed")
    add(urljoin(home, "/cart"), "cart", "seed")
    add(urljoin(home, "/robots.txt"), "robots", "seed")
    add(urljoin(home, "/sitemap.xml"), "sitemap", "seed")

    # robots.txt -> sitemap declarations
    try:
        robots_text = _safe_get_text(urljoin(home, "/robots.txt"))
        sitemaps = extract_sitemaps_from_robots(robots_text)
    except Exception:
        sitemaps = []
    if not sitemaps:
        sitemaps = [urljoin(home, "/sitemap.xml")]

    # sitemap(s)
    try:
        for u in fetch_sitemap_urls(sitemaps, base_host):
            add(u, None, "sitemap")
    except Exception:
        pass

    # Shopify products.json fallback
    try:
        for handle in fetch_product_handles(home):
            add(urljoin(home, f"/products/{handle}"), "product", "products.json")
    except Exception:
        pass

    # one-hop homepage nav
    try:
        for u, pt in fetch_nav_links(home, base_host):
            add(u, pt, "nav")
    except Exception:
        pass

    return select_representative(found, max_pages)
