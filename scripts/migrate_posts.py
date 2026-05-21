"""One-shot migration: legacy in-tree dicts → file-per-post JSON store.

Reads:
- POSTS from posts_content.py (excerpt, tags, body_html per slug)
- POST_CATEGORIES from build.py (categories per slug)
- POST_IMG_FIX from build.py (placeholder mapping for unarchived heroes)
- date_iso + img URL from site/_orig/{index,page/2/index}.html
- NEWS_ITEMS from build.py (6 hard-coded tuples)

Writes:
- content/posts/<slug>.json  (20 files)
- content/news/<slug>.json   (6 files)

Idempotent: re-running overwrites existing JSON with re-derived content.
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Import legacy data structures
from posts_content import POSTS  # noqa: E402
from build import POST_CATEGORIES, POST_IMG_FIX, NEWS_ITEMS  # noqa: E402

from generators.schema import (  # noqa: E402
    Post,
    NewsItem,
    write_post,
    write_news,
)

SITE = ROOT / "site"
CONTENT = ROOT / "content"

ART_RE = re.compile(
    r'<article[^>]*id="post-(\d+)"[^>]*class="([^"]*)"[^>]*>(.*?)</article>',
    re.S,
)


def parse_archived_meta() -> dict[str, dict]:
    """Mirror of build.parse_posts() but returns only date_iso + img per slug."""
    out: dict[str, dict] = {}
    for fn in ["_orig/index.html", "_orig/page/2/index.html"]:
        path = SITE / fn
        if not path.exists():
            print(f"  WARN: {path} missing", file=sys.stderr)
            continue
        h = path.read_text(encoding="utf-8")
        for _pid, _cls, body in ART_RE.findall(h):
            tm = re.search(
                r'<h2 class="entry-title[^"]*"><a href="([^"]+)"[^>]*>([^<]+)</a>',
                body,
            )
            if not tm:
                continue
            url, raw_title = tm.group(1), tm.group(2)
            title = html.unescape(raw_title)
            clean = url.split("?")[0].split("#")[0]
            if clean.endswith("/index.html"):
                clean = clean[: -len("/index.html")]
            parts = [p for p in clean.rstrip("/").split("/") if p and p not in ("..", ".")]
            slug = parts[-1] if parts else ""
            if not slug or slug == "index.html" or slug in out:
                continue
            im = re.search(r'<img[^>]+src="([^"]+)"', body)
            img = im.group(1) if im else ""
            if slug in POST_IMG_FIX:
                # archived hero missing → per-post auto-placeholder (image=None)
                img = None
            dm = re.search(
                r'<time[^>]*datetime="([^"]+)"[^>]*>[^<]+</time>', body
            )
            date_iso = dm.group(1) if dm else ""
            out[slug] = {"title": title, "date_iso": date_iso, "image": img}
    return out


def migrate_posts() -> int:
    meta = parse_archived_meta()
    count = 0
    for slug, body_data in POSTS.items():
        if slug not in meta:
            print(f"  WARN: {slug} not found in archived index", file=sys.stderr)
            continue
        m = meta[slug]
        p = Post(
            slug=slug,
            title=m["title"],
            date_iso=m["date_iso"],
            categories=POST_CATEGORIES.get(slug, ["blog"]),
            tags=list(body_data.get("tags", [])),
            excerpt=body_data.get("excerpt", "").strip(),
            body_html=body_data.get("body", "").strip(),
            image=m["image"] if m["image"] else None,
            source="archived",
            source_urls=[f"https://digitalkarachi.com/{slug}/"],
        )
        write_post(CONTENT, p)
        count += 1
    return count


def migrate_news() -> int:
    count = 0
    for slug, title, date_iso, body in NEWS_ITEMS:
        n = NewsItem(
            slug=slug,
            title=title,
            date_iso=date_iso,
            body=body.strip(),
            source="archived",
            source_urls=[],
        )
        write_news(CONTENT, n)
        count += 1
    return count


def main() -> int:
    CONTENT.mkdir(exist_ok=True)
    (CONTENT / "posts").mkdir(exist_ok=True)
    (CONTENT / "news").mkdir(exist_ok=True)
    n_posts = migrate_posts()
    n_news = migrate_news()
    print(f"Wrote {n_posts} posts to content/posts/")
    print(f"Wrote {n_news} news items to content/news/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
