"""Submit URLs to the IndexNow API (Bing, Yandex, Seznam, etc.).

Usage:
    python3 scripts/indexnow_ping.py              # ping today's new URLs only
    python3 scripts/indexnow_ping.py --all        # ping the full sitemap
    python3 scripts/indexnow_ping.py --dry-run    # print URLs, don't submit

Reads the IndexNow key from `site/<KEY>.txt` (written by build.py).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import date as date_cls
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
HOST = "digitalkarachi.com"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/IndexNow"


def _find_key() -> tuple[str, str] | None:
    """Return (key, key_location_url) by scanning site/ for `<key>.txt`."""
    if not SITE.is_dir():
        return None
    for f in SITE.glob("*.txt"):
        # IndexNow keys are 8-128 hex chars and the filename matches the contents.
        if re.fullmatch(r"[0-9a-fA-F]{8,128}", f.stem):
            content = f.read_text(encoding="utf-8").strip()
            if content == f.stem:
                return content, f"https://{HOST}/{f.name}"
    return None


def _todays_urls(today: str) -> list[str]:
    """URLs of posts/news whose ISO date starts with `today` (YYYY-MM-DD)."""
    urls: list[str] = []
    for sub in ("posts", "news"):
        d = ROOT / "content" / sub
        if not d.is_dir():
            continue
        for jf in d.glob("*.json"):
            try:
                obj = json.loads(jf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if (obj.get("date_iso") or "").startswith(today):
                slug = obj.get("slug") or jf.stem
                prefix = "news/" if sub == "news" else ""
                urls.append(f"https://{HOST}/{prefix}{slug}/")
    return urls


def _sitemap_urls() -> list[str]:
    sm = SITE / "sitemap.xml"
    if not sm.exists():
        return []
    return re.findall(r"<loc>([^<]+)</loc>", sm.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="Ping every URL in sitemap.xml")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    key_info = _find_key()
    if not key_info:
        print("ERROR: no IndexNow key file found in site/. Run build.py first.", file=sys.stderr)
        return 1
    key, key_location = key_info

    if args.all:
        urls = _sitemap_urls()
    else:
        urls = _todays_urls(date_cls.today().isoformat())
    if not urls:
        print("No URLs to submit.")
        return 0

    print(f"[indexnow] submitting {len(urls)} URLs (key={key[:8]}…)")
    for u in urls:
        print(f"  {u}")
    if args.dry_run:
        return 0

    payload = json.dumps({
        "host": HOST,
        "key": key,
        "keyLocation": key_location,
        "urlList": urls,
    }).encode()
    req = urllib.request.Request(
        INDEXNOW_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[indexnow] HTTP {resp.status} {resp.reason}")
    except Exception as e:
        print(f"[indexnow] ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
