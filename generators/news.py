"""Short news-dispatch generator (LLM-rewritten from RSS feed items)."""
from __future__ import annotations

import re
from datetime import date as date_cls
from pathlib import Path

from generators.blog import slugify
from generators.llm import LLM, LLMError
from generators.rss import FeedItem, fetch_recent, filter_unseen, mark_seen
from generators.schema import (
    NewsItem,
    load_news,
    validate_news,
    write_news,
)

CONTENT = Path(__file__).resolve().parent.parent / "content"

SYSTEM_PROMPT = """You are a tech newsroom editor. You rewrite news leads into short, neutral, factually conservative dispatches suitable for a daily tech bulletin. You never add information that is not in the source. You never speculate. You never use marketing adjectives. Plain English, working-journalist tone."""

USER_PROMPT_TEMPLATE = """Rewrite the following source item as a short news dispatch for Digital Karachi.

SOURCE TITLE: {title}
SOURCE SUMMARY: {summary}
SOURCE LINK: {link}
PUBLISHER: {publisher}

OUTPUT REQUIREMENTS:
- Length: 110-180 words.
- Tone: neutral, factual, no hype.
- Do NOT add facts that aren't in the source. If unsure, omit.
- Do NOT use phrases like "breaking", "game-changing", "revolutionary".
- The first sentence is the dispatch lead.
- Do not include the source link in prose; we keep it as a structured field.

Return STRICT JSON with these keys only:
{{
  "title": "tightened 50-90 character headline in headline case, no trailing period",
  "body": "the rewritten 110-180 word dispatch as plain text, no HTML tags"
}}"""


def _existing_news_slugs() -> set[str]:
    return {n.slug for n in load_news(CONTENT)}


def _unique_slug(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    for i in range(2, 30):
        cand = f"{base}-{i}"
        if cand not in taken:
            return cand
    raise LLMError(f"Cannot find unique news slug for base {base!r}")


def rewrite_item(item: FeedItem, llm: LLM) -> NewsItem:
    prompt = USER_PROMPT_TEMPLATE.format(
        title=item.title,
        summary=item.summary or "(no summary provided)",
        link=item.link,
        publisher=item.source_name,
    )
    data = llm.complete(
        prompt,
        system=SYSTEM_PROMPT,
        json_mode=True,
        temperature=0.4,
        max_tokens=512,
    )
    if not isinstance(data, dict):
        raise LLMError(f"Expected dict from LLM, got {type(data).__name__}")

    title = (data.get("title") or "").strip().rstrip(".")
    body = re.sub(r"\s+", " ", (data.get("body") or "")).strip()
    if not title or len(body.split()) < 70:
        raise LLMError(f"News rewrite too short for {item.title!r} (words={len(body.split())})")

    date_iso = item.published or date_cls.today().isoformat()
    base_slug = slugify(title)[:80]
    if not base_slug:
        raise LLMError(f"Could not slugify rewritten title {title!r}")
    slug = _unique_slug(base_slug, _existing_news_slugs())

    return NewsItem(
        slug=slug,
        title=title,
        date_iso=date_iso,
        body=body,
        source="rss-rewrite",
        source_urls=[item.link] if item.link else [],
    )


def generate_news_batch(
    *,
    llm: LLM,
    max_items: int = 3,
    dry_run: bool = False,
) -> list[NewsItem]:
    """Fetch RSS, dedup, rewrite up to `max_items`, write to disk."""
    raw = fetch_recent(max_per_feed=8)
    fresh = filter_unseen(raw)
    # Prefer most recently published items first.
    fresh.sort(key=lambda f: f.published or "", reverse=True)

    out: list[NewsItem] = []
    used: list[FeedItem] = []
    for item in fresh:
        if len(out) >= max_items:
            break
        try:
            n = rewrite_item(item, llm)
            validate_news(n)
        except LLMError as e:
            print(f"  SKIP {item.title!r}: {e}")
            continue
        if not dry_run:
            write_news(CONTENT, n)
        out.append(n)
        used.append(item)

    if not dry_run and used:
        mark_seen(used)
    return out
