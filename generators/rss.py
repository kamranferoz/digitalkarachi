"""Minimal stdlib RSS/Atom feed fetcher with seen-URL dedup.

No third-party deps. Parses enough of RSS 2.0 and Atom 1.0 to power the
news-dispatch pipeline. Maintains a persistent seen-URL set at
`content/.seen_urls.json` so the same item isn't rewritten twice.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

CONTENT = Path(__file__).resolve().parent.parent / "content"
SEEN_FILE = CONTENT / ".seen_urls.json"

# Bundled default feed list. Edit `feeds.json` next to build.py to override.
DEFAULT_FEEDS = [
    {"name": "Hacker News (Front Page)", "url": "https://hnrss.org/frontpage", "categories": ["technology"]},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "categories": ["technology"]},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index", "categories": ["technology"]},
    {"name": "Wired AI", "url": "https://www.wired.com/feed/tag/ai/latest/rss", "categories": ["artificial-intelligence-ai", "technology"]},
    {"name": "MIT Tech Review", "url": "https://www.technologyreview.com/feed/", "categories": ["technology"]},
    {"name": "Krebs on Security", "url": "https://krebsonsecurity.com/feed/", "categories": ["security"]},
]

_ATOM_NS = "{http://www.w3.org/2005/Atom}"

UA = "DigitalKarachiBot/1.0 (+https://digitalkarachi.com)"


@dataclass
class FeedItem:
    title: str
    link: str
    summary: str
    published: str  # ISO-8601 (YYYY-MM-DD or full)
    source_name: str
    categories: list[str]

    def url_key(self) -> str:
        """Stable dedup key: canonical link, falling back to title hash."""
        if self.link:
            return self.link.split("#")[0].split("?")[0].rstrip("/")
        return "title:" + hashlib.sha1(self.title.encode()).hexdigest()[:16]


def _load_feed_config(path: Path | None = None) -> list[dict]:
    p = path or (CONTENT.parent / "feeds.json")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"WARN: {p} invalid JSON ({e}); using defaults", file=sys.stderr)
    return DEFAULT_FEEDS


def _http_get(url: str, timeout: int = 20) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  WARN: fetch {url}: {e}", file=sys.stderr)
        return None


def _strip_html(s: str) -> str:
    return _html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def _normalize_date(raw: str | None) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    # Try RFC 2822 (RSS) then ISO (Atom).
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        pass
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
    return m.group(1) if m else ""


def _parse_feed(xml_text: str, source_name: str, source_cats: list[str]) -> list[FeedItem]:
    out: list[FeedItem] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  WARN: parse {source_name}: {e}", file=sys.stderr)
        return out

    # RSS 2.0
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = item.findtext("description") or ""
        pub = item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date")
        if title and link:
            out.append(FeedItem(
                title=_html.unescape(title),
                link=link,
                summary=_strip_html(desc)[:600],
                published=_normalize_date(pub),
                source_name=source_name,
                categories=list(source_cats),
            ))

    # Atom 1.0
    if not out:
        for entry in root.iter(f"{_ATOM_NS}entry"):
            title = (entry.findtext(f"{_ATOM_NS}title") or "").strip()
            link_el = entry.find(f"{_ATOM_NS}link")
            link = link_el.get("href", "").strip() if link_el is not None else ""
            summary = entry.findtext(f"{_ATOM_NS}summary") or entry.findtext(f"{_ATOM_NS}content") or ""
            pub = entry.findtext(f"{_ATOM_NS}published") or entry.findtext(f"{_ATOM_NS}updated")
            if title and link:
                out.append(FeedItem(
                    title=_html.unescape(title),
                    link=link,
                    summary=_strip_html(summary)[:600],
                    published=_normalize_date(pub),
                    source_name=source_name,
                    categories=list(source_cats),
                ))
    return out


def fetch_recent(max_per_feed: int = 10, config_path: Path | None = None) -> list[FeedItem]:
    cfg = _load_feed_config(config_path)
    items: list[FeedItem] = []
    for f in cfg:
        url = f.get("url")
        name = f.get("name", url or "unknown")
        cats = list(f.get("categories", ["technology"]))
        if not url:
            continue
        body = _http_get(url)
        if not body:
            continue
        parsed = _parse_feed(body, name, cats)
        items.extend(parsed[:max_per_feed])
    return items


# ---------------------------------------------------------------------------
# Seen-URL persistence
# ---------------------------------------------------------------------------

def load_seen() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def save_seen(seen: set[str], cap: int = 5000) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Keep most recent N to avoid unbounded growth.
    items = list(seen)[-cap:]
    SEEN_FILE.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")


def filter_unseen(items: list[FeedItem]) -> list[FeedItem]:
    seen = load_seen()
    out = [it for it in items if it.url_key() not in seen]
    return out


def mark_seen(items: list[FeedItem]) -> None:
    seen = load_seen()
    for it in items:
        seen.add(it.url_key())
    save_seen(seen)
