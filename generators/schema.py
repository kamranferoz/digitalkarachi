"""Post / NewsItem dataclasses + JSON validation.

Every file under `content/posts/` and `content/news/` must conform.
`build.py` refuses to build if validation fails for any entry.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

# --- Allowed taxonomy -------------------------------------------------------
# Mirrors the CATEGORIES dict in build.py. Kept here as the canonical list so
# generators/migration can validate without importing build.py.
ALLOWED_CATEGORIES = {
    "blog", "technology", "management",
    "artificial-intelligence-ai", "blockchain", "cloud-computing",
    "data-science", "drone", "internet-of-things-iot",
    "machine-learning-ml", "quantum-computing", "robotics",
    "security", "virtual-reality-vr",
}

ALLOWED_SOURCES = {"archived", "llm", "rss-rewrite", "manual"}

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:?\d{2}|Z)?)?$"
)


class ValidationError(ValueError):
    """Raised when a stored Post/NewsItem fails schema validation."""


@dataclass
class Post:
    slug: str
    title: str
    date_iso: str
    categories: list[str]
    tags: list[str] = field(default_factory=list)
    excerpt: str = ""
    body_html: str = ""
    image: str | None = None  # site-relative path, or None for auto-placeholder
    source: str = "manual"
    source_urls: list[str] = field(default_factory=list)


@dataclass
class NewsItem:
    slug: str
    title: str
    date_iso: str
    body: str
    source: str = "manual"
    source_urls: list[str] = field(default_factory=list)


# --- Validation -------------------------------------------------------------

def _check_slug(slug: str, kind: str) -> None:
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        raise ValidationError(f"{kind}: invalid slug {slug!r}")
    if len(slug) > 120:
        raise ValidationError(f"{kind}: slug too long ({len(slug)} > 120)")


def _check_iso(value: str, kind: str, field_name: str) -> None:
    if not isinstance(value, str) or not _ISO_RE.match(value):
        raise ValidationError(f"{kind}: {field_name} {value!r} is not ISO-8601")


def _check_categories(cats: list[str], kind: str) -> None:
    if not isinstance(cats, list) or not cats:
        raise ValidationError(f"{kind}: categories must be a non-empty list")
    bad = [c for c in cats if c not in ALLOWED_CATEGORIES]
    if bad:
        raise ValidationError(
            f"{kind}: unknown categories {bad}. "
            f"Allowed: {sorted(ALLOWED_CATEGORIES)}"
        )


def _check_source(src: str, kind: str) -> None:
    if src not in ALLOWED_SOURCES:
        raise ValidationError(
            f"{kind}: source {src!r} not in {sorted(ALLOWED_SOURCES)}"
        )


def validate_post(p: Post) -> None:
    _check_slug(p.slug, "Post")
    if not p.title or not isinstance(p.title, str):
        raise ValidationError(f"Post {p.slug}: title is required")
    if len(p.title) > 200:
        raise ValidationError(f"Post {p.slug}: title too long ({len(p.title)})")
    _check_iso(p.date_iso, "Post", "date_iso")
    _check_categories(p.categories, f"Post {p.slug}")
    if not isinstance(p.tags, list):
        raise ValidationError(f"Post {p.slug}: tags must be a list")
    if not isinstance(p.excerpt, str):
        raise ValidationError(f"Post {p.slug}: excerpt must be a string")
    if not isinstance(p.body_html, str) or len(p.body_html.strip()) < 50:
        raise ValidationError(
            f"Post {p.slug}: body_html too short or missing "
            f"({len(p.body_html.strip()) if isinstance(p.body_html, str) else 'n/a'} chars)"
        )
    if p.image is not None and not isinstance(p.image, str):
        raise ValidationError(f"Post {p.slug}: image must be string or null")
    _check_source(p.source, f"Post {p.slug}")
    if not isinstance(p.source_urls, list):
        raise ValidationError(f"Post {p.slug}: source_urls must be a list")


def validate_news(n: NewsItem) -> None:
    _check_slug(n.slug, "NewsItem")
    if not n.title or not isinstance(n.title, str):
        raise ValidationError(f"NewsItem {n.slug}: title is required")
    _check_iso(n.date_iso, "NewsItem", "date_iso")
    if not isinstance(n.body, str) or len(n.body.strip()) < 30:
        raise ValidationError(
            f"NewsItem {n.slug}: body too short ({len(n.body.strip())})"
        )
    _check_source(n.source, f"NewsItem {n.slug}")
    if not isinstance(n.source_urls, list):
        raise ValidationError(f"NewsItem {n.slug}: source_urls must be a list")


# --- I/O helpers ------------------------------------------------------------

def post_from_dict(d: dict[str, Any]) -> Post:
    return Post(
        slug=d["slug"],
        title=d["title"],
        date_iso=d["date_iso"],
        categories=list(d.get("categories", [])),
        tags=list(d.get("tags", [])),
        excerpt=d.get("excerpt", ""),
        body_html=d.get("body_html", ""),
        image=d.get("image"),
        source=d.get("source", "manual"),
        source_urls=list(d.get("source_urls", [])),
    )


def news_from_dict(d: dict[str, Any]) -> NewsItem:
    return NewsItem(
        slug=d["slug"],
        title=d["title"],
        date_iso=d["date_iso"],
        body=d["body"],
        source=d.get("source", "manual"),
        source_urls=list(d.get("source_urls", [])),
    )


def load_posts(content_dir: Path) -> list[Post]:
    out: list[Post] = []
    posts_dir = content_dir / "posts"
    if not posts_dir.is_dir():
        return out
    for jf in sorted(posts_dir.glob("*.json")):
        try:
            d = json.loads(jf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValidationError(f"{jf}: invalid JSON: {e}") from e
        p = post_from_dict(d)
        validate_post(p)
        if p.slug != jf.stem:
            raise ValidationError(
                f"{jf}: slug {p.slug!r} doesn't match filename {jf.stem!r}"
            )
        out.append(p)
    return out


def load_news(content_dir: Path) -> list[NewsItem]:
    out: list[NewsItem] = []
    news_dir = content_dir / "news"
    if not news_dir.is_dir():
        return out
    for jf in sorted(news_dir.glob("*.json")):
        try:
            d = json.loads(jf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValidationError(f"{jf}: invalid JSON: {e}") from e
        n = news_from_dict(d)
        validate_news(n)
        if n.slug != jf.stem:
            raise ValidationError(
                f"{jf}: slug {n.slug!r} doesn't match filename {jf.stem!r}"
            )
        out.append(n)
    return out


def write_post(content_dir: Path, p: Post) -> Path:
    validate_post(p)
    dest = content_dir / "posts" / f"{p.slug}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(asdict(p), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return dest


def write_news(content_dir: Path, n: NewsItem) -> Path:
    validate_news(n)
    dest = content_dir / "news" / f"{n.slug}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(asdict(n), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return dest


def date_display(iso: str) -> str:
    """Human-readable date matching the original WP theme: '3 April 2024'."""
    # Accept full ISO with TZ or just YYYY-MM-DD
    base = iso[:10]
    dt = datetime.strptime(base, "%Y-%m-%d")
    return f"{dt.day} {dt.strftime('%B %Y')}"
