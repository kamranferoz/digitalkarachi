#!/usr/bin/env python3
"""Restore digitalkarachi.com from Wayback Machine snapshots."""
import json, os, re, sys, time, urllib.parse, urllib.request, gzip, io, shutil
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./site")
ROOT.mkdir(parents=True, exist_ok=True)

CDX = "http://web.archive.org/cdx/search/cdx?url=digitalkarachi.com/*&output=json&filter=statuscode:200"

def fetch(url, decode_gzip=True):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (restore-dk; archive)",
        "Accept": "*/*",
    })
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                if decode_gzip and r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                # Some wayback responses are gzipped without Content-Encoding header (we forced id_)
                if decode_gzip and data[:2] == b"\x1f\x8b":
                    try: data = gzip.decompress(data)
                    except OSError: pass
                return data, r.headers.get("Content-Type", "")
        except Exception as e:
            print(f"  retry {attempt+1}: {e}", file=sys.stderr)
            time.sleep(2 + attempt*2)
    raise RuntimeError(f"failed: {url}")

def url_to_path(orig_url):
    """Map https://digitalkarachi.com/some/path?x=1 -> local file path."""
    u = urllib.parse.urlsplit(orig_url)
    path = u.path or "/"
    # query string -> append as part of name (for ?ver=...)
    if u.query:
        # for css/js we want the bare filename without the ver param, keep that
        # check extension
        ext = os.path.splitext(path)[1].lower()
        if ext in (".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".woff", ".woff2", ".ttf", ".eot", ".ico"):
            # drop the query (e.g. ?ver=1.0.4)
            pass
        else:
            # encode query into filename
            safe_q = re.sub(r"[^A-Za-z0-9._-]+", "_", u.query)
            path = path.rstrip("/") + "__" + safe_q
    if path.endswith("/"):
        path = path + "index.html"
    if path.startswith("/"):
        path = path[1:]
    if not path:
        path = "index.html"
    return path

def get_cdx():
    print("Fetching CDX listing...")
    data, _ = fetch(CDX, decode_gzip=True)
    rows = json.loads(data.decode("utf-8"))
    return rows[1:]  # skip header

def best_snapshots(rows):
    """Return mapping orig_url -> (timestamp, original) preferring latest."""
    best = {}
    for r in rows:
        _, ts, orig, mime, status, _, _ = r
        if status != "200":
            continue
        # normalize: prefer https, drop trailing index garbage
        key = orig
        cur = best.get(key)
        if not cur or ts > cur[0]:
            best[key] = (ts, orig, mime)
    return best

# Skipped URLs we don't want
SKIP_PATTERNS = [
    re.compile(r"/wp-login\.php"),
    re.compile(r"/xmlrpc\.php"),
    re.compile(r"/wp-json"),
    re.compile(r"/robots\.txt$"),
    re.compile(r"^http://digitalkarachi\.com/domain-default-img"),
    re.compile(r"^http://digitalkarachi\.com/hostinger-logo"),
]

def should_skip(url):
    return any(p.search(url) for p in SKIP_PATTERNS)

def download_all():
    rows = get_cdx()
    snaps = best_snapshots(rows)
    print(f"{len(snaps)} unique URLs in CDX")
    manifest = {}
    for url, (ts, orig, mime) in sorted(snaps.items()):
        if should_skip(orig):
            print(f"SKIP {orig}")
            continue
        wayback = f"https://web.archive.org/web/{ts}id_/{orig}"
        local = url_to_path(orig)
        dest = ROOT / local
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size > 0:
            print(f"HAVE {local}")
            manifest[orig] = local
            continue
        print(f"GET  {orig} -> {local}")
        try:
            data, ctype = fetch(wayback)
        except Exception as e:
            print(f"  FAIL: {e}", file=sys.stderr)
            continue
        dest.write_bytes(data)
        manifest[orig] = local
        time.sleep(0.3)
    (ROOT / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest

# --- Link rewriting for HTML ---
WAYBACK_RE = re.compile(r"https?://web\.archive\.org/web/\d+[a-z_]*/")
SITE_HOSTS = ("https://digitalkarachi.com", "http://digitalkarachi.com")

def html_relpath(from_local, to_local):
    """Get relative path from one local file to another."""
    return os.path.relpath(to_local, os.path.dirname(from_local)) or "."

def rewrite_html(text, source_local, manifest):
    # 1) Strip wayback toolbar / archive comments
    text = re.sub(r"<!--\s*BEGIN WAYBACK TOOLBAR INSERT.*?END WAYBACK TOOLBAR INSERT\s*-->", "", text, flags=re.S)
    text = re.sub(r"<script src=\"//archive\.org/.*?</script>", "", text, flags=re.S)
    text = re.sub(r"<link[^>]+archive\.org[^>]*>", "", text)
    # 2) Replace wayback-rewritten URLs back to originals (both forms)
    text = WAYBACK_RE.sub("", text)
    text = re.sub(r"https?:\\?/\\?/web\.archive\.org\\?/web\\?/\d+[a-z_]*\\?/", "", text)

    # 3) Rewrite digitalkarachi.com URLs to local relative paths where available
    abs_re = re.compile(r"https?:\\?/\\?/digitalkarachi\.com([^\s\"'<>)]*)")
    def abs_repl(m):
        full = m.group(0)
        path = m.group(1).replace("\\/", "/")
        # Pure fragment / schema @id like https://digitalkarachi.com/#breadcrumblist
        if path.startswith("/#") or path == "":
            frag = path[1:] if path.startswith("/") else path
            rel = html_relpath(source_local, "index.html")
            return rel + frag
        if path == "/":
            return html_relpath(source_local, "index.html")
        # Lookup in manifest
        clean = path.split("#")[0]
        for c in [f"https://digitalkarachi.com{path}",
                  f"http://digitalkarachi.com{path}",
                  f"https://digitalkarachi.com{clean}",
                  f"http://digitalkarachi.com{clean}"]:
            if c in manifest:
                local = manifest[c]
                rel = html_relpath(source_local, local)
                # preserve fragment
                if "#" in path and "#" not in rel:
                    frag = "#" + path.split("#",1)[1]
                    rel = rel + frag
                return rel
        # Not archived. For asset-like URLs leave alone; for pages, fall back to wayback nearest redirect.
        is_asset = bool(re.search(r"\.(css|js|png|jpg|jpeg|webp|svg|gif|ico|woff2?|ttf|eot|mp4|json|xml)(\?|$)", clean))
        if is_asset:
            return full
        return f"https://web.archive.org/web/2/https://digitalkarachi.com{path}"
    text = abs_re.sub(abs_repl, text)

    return text

def rewrite_css(text, source_local, manifest):
    text = WAYBACK_RE.sub("", text)
    def repl(m):
        path = m.group(1)
        for c in (f"https://digitalkarachi.com{path}", f"http://digitalkarachi.com{path}",
                  f"https://digitalkarachi.com{path.split('?')[0]}"):
            if c in manifest:
                return html_relpath(source_local, manifest[c])
        return m.group(0)
    text = re.sub(r"https?://digitalkarachi\.com([^\s\)\"']+)", lambda m: repl(m), text)
    return text

def postprocess(manifest):
    for orig, local in manifest.items():
        p = ROOT / local
        if not p.exists():
            continue
        # decide by extension
        ext = p.suffix.lower()
        if ext in (".html", ".htm") or local.endswith("index.html"):
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            new = rewrite_html(txt, local, manifest)
            p.write_text(new, encoding="utf-8")
        elif ext == ".css":
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            new = rewrite_css(txt, local, manifest)
            p.write_text(new, encoding="utf-8")
        elif ext == ".js":
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
                new = WAYBACK_RE.sub("", txt)
                p.write_text(new, encoding="utf-8")
            except Exception:
                pass

if __name__ == "__main__":
    manifest = download_all()
    print("Post-processing & rewriting links...")
    postprocess(manifest)
    print("Done.")
