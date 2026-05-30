"""CLI for content generation.

Subcommands:
  daily        — one blog (rotating category) + N news items for today
  blog         — generate a single blog for a given category / date / topic
  news         — fetch RSS and emit N news rewrites
  backfill     — drive the generator across a date range
  health       — quick Ollama liveness probe
  topics       — print rotation + first topic per category

Common flags:
  --dry-run    — do everything except write files
  --model NAME — override OLLAMA_MODEL for this run
  --date YYYY-MM-DD — override target date (default: today)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from generators import blog as blog_mod  # noqa: E402
from generators import news as news_mod  # noqa: E402
from generators import topics as topics_mod  # noqa: E402
from generators.llm import LLMError, get_llm, health_check  # noqa: E402
from generators.schema import load_posts  # noqa: E402

CONTENT = ROOT / "content"


def _today_iso() -> str:
    return date_cls.today().isoformat()


def _apply_model_override(model: str | None) -> None:
    if model:
        os.environ["OLLAMA_MODEL"] = model


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def cmd_health(args: argparse.Namespace) -> int:
    _apply_model_override(args.model)
    llm = get_llm()
    ok, msg = health_check(llm)
    print(f"{llm.name}: {'OK' if ok else 'FAIL'} -> {msg}")
    return 0 if ok else 1


def cmd_topics(args: argparse.Namespace) -> int:
    existing = [p.title for p in load_posts(CONTENT)]
    for cat in topics_mod.DEFAULT_ROTATION:
        topic = topics_mod.pick_topic(cat, existing_titles=existing, seed=args.seed)
        print(f"  {cat:32s} -> {topic}")
    print()
    print(f"Today's rotation pick: {topics_mod.rotate_category(_today_iso())}")
    return 0


def cmd_blog(args: argparse.Namespace) -> int:
    _apply_model_override(args.model)
    date_iso = args.date or _today_iso()
    category = args.category or topics_mod.rotate_category(date_iso)
    existing = [p.title for p in load_posts(CONTENT)]
    if args.topic:
        topic = args.topic
    elif getattr(args, "from_trends", False):
        topic = topics_mod.pick_topic_from_trends(
            category, existing_titles=existing, seed=args.seed or date_iso,
        )
    else:
        topic = topics_mod.pick_topic(
            category, existing_titles=existing, seed=args.seed or date_iso,
        )
    print(f"[blog] date={date_iso} category={category}")
    print(f"[blog] topic: {topic}")
    llm = get_llm()
    try:
        post = blog_mod.generate_blog(
            category=category,
            topic=topic,
            date_iso=date_iso,
            llm=llm,
            dry_run=args.dry_run,
        )
    except (LLMError, ValueError) as e:
        print(f"[blog] FAILED: {e}", file=sys.stderr)
        return 1
    print(f"[blog] {'(dry-run) ' if args.dry_run else ''}wrote slug={post.slug} title={post.title!r}")
    return 0


def cmd_news(args: argparse.Namespace) -> int:
    _apply_model_override(args.model)
    llm = get_llm()
    print(f"[news] fetching feeds; target max={args.max}")
    try:
        items = news_mod.generate_news_batch(
            llm=llm, max_items=args.max, dry_run=args.dry_run,
        )
    except LLMError as e:
        print(f"[news] FAILED: {e}", file=sys.stderr)
        return 1
    for n in items:
        print(f"[news] {'(dry-run) ' if args.dry_run else ''}{n.slug} :: {n.title}")
    if not items:
        print("[news] no new items.", file=sys.stderr)
        return 1
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    _apply_model_override(args.model)
    date_iso = args.date or _today_iso()
    print(f"[daily] {date_iso}")

    # Blog (topic seeded from today's tech headlines when possible)
    rc = cmd_blog(argparse.Namespace(
        date=date_iso, category=None, topic=None, seed=date_iso,
        model=None, dry_run=args.dry_run, from_trends=True,
    ))
    blog_ok = rc == 0

    # News
    rc2 = cmd_news(argparse.Namespace(
        max=args.news, model=None, dry_run=args.dry_run,
    ))
    news_ok = rc2 == 0

    if blog_ok and news_ok:
        return 0
    if not blog_ok:
        print("[daily] blog generation failed", file=sys.stderr)
    if not news_ok:
        print("[daily] news generation failed or produced no items", file=sys.stderr)
    return 1


def cmd_backfill(args: argparse.Namespace) -> int:
    _apply_model_override(args.model)
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    if end < start:
        print("end < start", file=sys.stderr)
        return 2

    llm = get_llm()
    # Determine which dates in the range should get blog posts.
    # posts_per_week=2.5 -> roughly every 2.8 days.
    blog_step = max(1, round(7 / args.posts_per_week))
    # News are LLM-only in backfill (no live RSS for historical dates).
    # We skip news in backfill by default; the daily cron handles news.

    existing_dates = {p.date_iso[:10] for p in load_posts(CONTENT)}
    cursor = start
    n_planned = 0
    n_written = 0
    n_skipped = 0
    n_failed = 0
    while cursor <= end:
        date_iso = cursor.isoformat()
        n_planned += 1
        if date_iso in existing_dates and not args.force:
            n_skipped += 1
        else:
            category = topics_mod.rotate_category(date_iso)
            existing = [p.title for p in load_posts(CONTENT)]
            topic = topics_mod.pick_topic(
                category, existing_titles=existing, seed=date_iso,
            )
            print(f"[backfill] {date_iso} {category:28s} :: {topic}")
            try:
                if not args.dry_run:
                    blog_mod.generate_blog(
                        category=category, topic=topic, date_iso=date_iso,
                        llm=llm, dry_run=False,
                    )
                n_written += 1
            except (LLMError, ValueError) as e:
                print(f"  FAILED: {e}", file=sys.stderr)
                n_failed += 1
                if args.fail_fast:
                    break
        cursor += timedelta(days=blog_step)

    print(
        f"[backfill] planned={n_planned} written={n_written} "
        f"skipped={n_skipped} failed={n_failed}"
    )
    return 0 if n_failed == 0 else 1


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="generate", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("health", help="Probe LLM endpoint")
    sp.add_argument("--model")
    sp.set_defaults(func=cmd_health)

    sp = sub.add_parser("topics", help="List rotation + topic per category")
    sp.add_argument("--seed", default=None)
    sp.set_defaults(func=cmd_topics)

    sp = sub.add_parser("blog", help="Generate one blog post")
    sp.add_argument("--category")
    sp.add_argument("--topic")
    sp.add_argument("--date", help="YYYY-MM-DD")
    sp.add_argument("--seed", default=None)
    sp.add_argument("--model")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument(
        "--from-trends", action="store_true",
        help="Seed topic from recent tech RSS headlines (used by daily)",
    )
    sp.set_defaults(func=cmd_blog)

    sp = sub.add_parser("news", help="Fetch RSS + rewrite news items")
    sp.add_argument("--max", type=int, default=3)
    sp.add_argument("--model")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_news)

    sp = sub.add_parser("daily", help="Daily run: 1 blog + N news")
    sp.add_argument("--date", help="YYYY-MM-DD")
    sp.add_argument("--news", type=int, default=2)
    sp.add_argument("--model")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_daily)

    sp = sub.add_parser("backfill", help="Backfill blog posts across a date range")
    sp.add_argument("--start", required=True, help="YYYY-MM-DD")
    sp.add_argument("--end", required=True, help="YYYY-MM-DD")
    sp.add_argument("--posts-per-week", type=float, default=2.5)
    sp.add_argument("--force", action="store_true",
                    help="Generate even on dates with existing posts")
    sp.add_argument("--fail-fast", action="store_true")
    sp.add_argument("--model")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_backfill)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
