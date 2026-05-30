"""Long-form blog post generator.

Asks the configured LLM for a structured JSON object, validates it, slugifies
the title (mirroring `build.slugify`), de-duplicates against the JSON store,
and writes `content/posts/<slug>.json`.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path

from generators.llm import LLM, LLMError
from generators.schema import (
    ALLOWED_CATEGORIES,
    Post,
    load_posts,
    validate_post,
    write_post,
)

CONTENT = Path(__file__).resolve().parent.parent / "content"

SYSTEM_PROMPT = """You are a senior technology editor for Digital Karachi, an English-language tech publication with a Pakistani and global readership. You write practical, opinionated, technically precise long-form articles for engineers, founders, and product leaders. You avoid hype, fluff, and AI-tells. You never invent specific companies, executives, statistics, dollar amounts, or product launches. You speak in plain English with a working-engineer tone. You favor short paragraphs, concrete examples, and clear structure."""

USER_PROMPT_TEMPLATE = """Write a long-form article for Digital Karachi.

CATEGORY: {category_display}
TOPIC: {topic}
TARGET DATE: {date_display}
TARGET LENGTH: 1100-1600 words (count carefully).

CONSTRAINTS:
- The TOPIC may reference a current trend from the headline seed. You may discuss that theme in general, analytical terms. Do NOT invent specific quotes, statistics, dollar amounts, or dated events beyond what the topic implies. Prefer patterns and trade-offs over breaking-news claims.
- Do NOT include phrases like "as an AI", "in conclusion", "in today's fast-paced world", "in the digital age", or other AI cliches.
- Use ONLY these HTML tags in body_html: <h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <blockquote>, <code>. Do not include <h1>, <html>, <body>, <head>, scripts, or images. No raw URLs.
- Open with a punchy 2-3 sentence lede in a <p>, NOT a heading.
- Use 3-5 <h2> sections. Each section has 2-5 paragraphs. At least one <ul> or <ol> somewhere.
- Tags must be lowercase, hyphenated, 1-3 words each, 4-7 tags total.
- Excerpt: a single sentence, 18-30 words, no trailing ellipsis.

Return STRICT JSON with exactly these keys and no others:
{{
  "title": "60-95 character article title in headline case, no trailing period",
  "excerpt": "single-sentence summary",
  "tags": ["tag-one", "tag-two", "..."],
  "body_html": "<p>...</p><h2>...</h2><p>...</p>..."
}}"""


def slugify(s: str) -> str:
    """Mirror of build.slugify so generated slugs match site routing."""
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _category_display(slug: str) -> str:
    # Light mirror of build.CATEGORIES display names (kept local to avoid
    # importing build.py from the generator).
    table = {
        "artificial-intelligence-ai": "Artificial Intelligence (AI)",
        "machine-learning-ml": "Machine Learning (ML)",
        "internet-of-things-iot": "Internet of Things (IoT)",
        "virtual-reality-vr": "Virtual Reality (VR)",
        "quantum-computing": "Quantum Computing",
        "cloud-computing": "Cloud Computing",
        "data-science": "Data Science",
    }
    return table.get(slug, slug.replace("-", " ").title())


def _date_display(date_iso: str) -> str:
    dt = datetime.strptime(date_iso[:10], "%Y-%m-%d")
    return f"{dt.day} {dt.strftime('%B %Y')}"


def _word_count(body_html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", body_html or "")
    return len(re.findall(r"\b\w+\b", text))


def _existing_slugs_titles() -> tuple[set[str], list[str]]:
    posts = load_posts(CONTENT)
    return ({p.slug for p in posts}, [p.title for p in posts])


def _unique_slug(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    for suffix in range(2, 20):
        cand = f"{base}-{suffix}"
        if cand not in taken:
            return cand
    raise LLMError(f"Cannot find unique slug for base {base!r}")


def generate_blog(
    *,
    category: str,
    topic: str,
    date_iso: str,
    llm: LLM,
    dry_run: bool = False,
) -> Post:
    """Generate one blog post and (unless dry_run) write it to disk.

    Always returns the constructed Post. Raises LLMError / ValueError on
    invalid LLM output or duplicate.
    """
    if category not in ALLOWED_CATEGORIES:
        raise ValueError(f"Unknown category {category!r}")

    base_prompt = USER_PROMPT_TEMPLATE.format(
        category_display=_category_display(category),
        topic=topic,
        date_display=_date_display(date_iso),
    )

    MIN_WORDS = 650
    MAX_ATTEMPTS = 4
    last_short_wc: int | None = None
    data: dict | None = None
    title = excerpt = body_html = ""
    tags: list = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        prompt = base_prompt
        if last_short_wc is not None:
            prompt += (
                f"\n\nIMPORTANT: The previous attempt produced only {last_short_wc} words. "
                "You MUST write at least 1100 words. EXPAND every <h2> section with more "
                "concrete examples, longer paragraphs, and additional sub-points. "
                "Do not be terse. Aim for 1300-1600 words."
            )
        data = llm.complete(
            prompt,
            system=SYSTEM_PROMPT,
            json_mode=True,
            temperature=0.75,
            max_tokens=4096,
        )
        if not isinstance(data, dict):
            raise LLMError(f"Expected dict from LLM, got {type(data).__name__}")

        title = (data.get("title") or "").strip()
        excerpt = (data.get("excerpt") or "").strip()
        tags = data.get("tags") or []
        body_html = (data.get("body_html") or "").strip()

        if not title or not body_html:
            raise LLMError(f"LLM omitted title or body_html: keys={list(data)}")

        wc = _word_count(body_html)
        if wc >= MIN_WORDS:
            break
        last_short_wc = wc
        if attempt < MAX_ATTEMPTS:
            print(
                f"  WARN: attempt {attempt} body too short ({wc} words); retrying with stronger prompt",
                file=__import__("sys").stderr,
            )
    else:
        raise LLMError(f"Body too short ({last_short_wc} words) after {MAX_ATTEMPTS} attempts for title {title!r}")

    # Light post-processing
    title = html.unescape(title).rstrip(".").strip()
    # Some models emit ALL-CAPS titles; soften to title case while preserving
    # well-known acronyms. Detect via alphabetic-char ratio so titles like
    # "RUNNING 1:1s WITH PEOPLE" (one stray lowercase 's') still get caught.
    alpha = [c for c in title if c.isalpha()]
    if alpha and (sum(1 for c in alpha if c.isupper()) / len(alpha)) >= 0.85:
        _ACRONYMS = {
            "AI", "ML", "IoT", "VR", "AR", "API", "LLM", "GPU", "CPU", "SDK",
            "SaaS", "IaaS", "PaaS", "CI", "CD", "DevOps", "MLOps", "GPT",
            "HTTP", "HTTPS", "URL", "SQL", "JSON", "XML", "HTML", "CSS",
            "TLS", "SSL", "DNS", "VPN", "SoC", "ROS", "UAV", "GIS", "UK",
            "US", "USA", "EU", "QA", "QC",
        }
        _ACR_MAP = {a.upper(): a for a in _ACRONYMS}
        def _cap(word: str) -> str:
            # Strip non-alpha to look up acronym (e.g. "IoT:" -> "IOT")
            stripped = re.sub(r"[^A-Za-z]", "", word).upper()
            if stripped in _ACR_MAP:
                # Replace alphabetic core with canonical acronym form,
                # preserving surrounding punctuation.
                canon = _ACR_MAP[stripped]
                return re.sub(r"[A-Za-z]+", canon, word, count=1)
            return word.capitalize()
        title = " ".join(_cap(w) for w in title.split(" "))
    if not (40 <= len(title) <= 110):
        # Soft-coerce length without failing; just warn via shorter clamp.
        title = title[:110].rstrip()
    tags = [
        slugify(str(t))[:40]
        for t in tags
        if isinstance(t, (str, int)) and str(t).strip()
    ][:8]

    base_slug = slugify(title)
    if not base_slug:
        raise LLMError(f"Could not slugify title {title!r}")

    taken, existing_titles = _existing_slugs_titles()
    slug = _unique_slug(base_slug, taken)

    # Defensive dup-check on title (slug uniquification handles slug dup)
    from generators.topics import is_duplicate
    if is_duplicate(title, existing_titles, threshold=0.70):
        raise LLMError(f"Title too similar to existing post: {title!r}")

    # Categories: ensure topical category + always include 'blog' suffix
    # (mirrors POST_CATEGORIES convention in the migrated data).
    categories = [category]
    if category != "blog":
        categories.append("blog")
    # Add 'technology' as a parent when the category lives under it.
    tech_children = {
        "artificial-intelligence-ai", "blockchain", "cloud-computing",
        "data-science", "drone", "internet-of-things-iot",
        "machine-learning-ml", "quantum-computing", "robotics",
        "security", "virtual-reality-vr",
    }
    if category in tech_children and "technology" not in categories:
        categories.append("technology")

    post = Post(
        slug=slug,
        title=title,
        date_iso=date_iso if "T" in date_iso else f"{date_iso}T09:00:00+05:00",
        categories=categories,
        tags=tags,
        excerpt=excerpt[:280],
        body_html=body_html,
        image=None,  # auto-placeholder at build time
        source="llm",
        source_urls=[],
    )
    validate_post(post)

    if not dry_run:
        write_post(CONTENT, post)
    return post
