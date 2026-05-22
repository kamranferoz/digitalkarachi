"""Build the full DigitalKarachi.com static site from extracted post metadata
and re-written article bodies. Uses the existing archived index.html as the
canonical header/footer template so styling stays identical to the original
city-blog WordPress theme.
"""
import re, os, json, html, shutil, sys
from pathlib import Path
from collections import defaultdict

from generators.schema import load_posts, load_news, date_display

SITE = Path(__file__).parent / "site"
CONTENT = Path(__file__).parent / "content"

# `POST_BODIES` is built at runtime from the JSON store (compat shim for
# legacy lookups: `POST_BODIES.get(slug, {}).get('body'/'excerpt'/'tags')`).
POST_BODIES: dict = {}

# Sitewide pagination: posts per home/archive page.
POSTS_PER_PAGE = 10

# ---------------------------------------------------------------------------
# 1. Load metadata for all 20 posts by parsing the existing index + page/2
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Featured-image fallback: deterministic Picsum URL keyed by post slug.
# Used when a post has no archived hero image (`p.image is None`).
# Picsum returns a different random photo per seed but the same one each call.
# ---------------------------------------------------------------------------
def featured_image_url(slug: str, category: str | None = None) -> str:
    # 1200x630 = ideal OG / Twitter card aspect.
    return f"https://picsum.photos/seed/{slug}/1200/630"


def _is_external_img(path: str) -> bool:
    return bool(path) and (path.startswith("http://") or path.startswith("https://"))


POST_IMG_FIX = {
    # page-2 posts whose hero images were never archived — point at local placeholder
    "a-10-year-old-tech-prodigy-has-risen-to-the-role-of-an-assistant-teacher-at-karachi-university": "wp-content/uploads/placeholder.svg",
    "discovering-a-treasure-trove-of-simple-svg-format-icons":                                       "wp-content/uploads/placeholder.svg",
    "startup-in-karachi-fixdar-a-new-dimension-to-home-maintenance-and-construction-services":       "wp-content/uploads/placeholder.svg",
    "free-hosting":                                                                                  "wp-content/uploads/placeholder.svg",
    "mastering-prompt-engineering":                                                                  "wp-content/uploads/placeholder.svg",
    "emerging-trends-in-cybersecurity":                                                              "wp-content/uploads/placeholder.svg",
    "quantum-computing-a-leap-towards-futuristic-computing":                                         "wp-content/uploads/placeholder.svg",
    "the-future-of-ai-in-healthcare":                                                                "wp-content/uploads/placeholder.svg",
    "how-to-keep-yourself-productive-while-managing-a-team":                                         "wp-content/uploads/placeholder.svg",
    "diving-into-big-data-making-decisions-just-got-a-whole-lot-easier":                             "wp-content/uploads/placeholder.svg",
}

CATEGORIES = {
    # slug -> (display name, parent slug or None)
    "blog": ("Blog", None),
    "technology": ("Technology", None),
    "management": ("Management", None),
    "artificial-intelligence-ai": ("Artificial Intelligence (AI)", "technology"),
    "blockchain": ("Blockchain", "technology"),
    "cloud-computing": ("Cloud Computing", "technology"),
    "data-science": ("Data Science", "technology"),
    "drone": ("Drone", "technology"),
    "internet-of-things-iot": ("Internet of Things (IoT)", "technology"),
    "machine-learning-ml": ("Machine Learning (ML)", "technology"),
    "quantum-computing": ("Quantum Computing", "technology"),
    "robotics": ("Robotics", "technology"),
    "security": ("Security", "technology"),
    "virtual-reality-vr": ("Virtual Reality (VR)", "technology"),
}

# Map each post slug to its category SLUGS (mirrors original WordPress taxonomy)
POST_CATEGORIES = {
    "pakistans-business-bonanza-3-days-to-launch-your-success-at-chaicon": ["blog", "management"],
    "2026-sky-breakthrough-uks-epic-drone-taxi-launch":                    ["blog", "drone", "technology"],
    "the-truth-about-full-stack-data-scientists":                         ["blog", "data-science", "technology"],
    "artificial-intelligence-takes-center-stage-at-world-economic-forum": ["artificial-intelligence-ai", "blog"],
    "bard-your-ai-companion-for-youtube-video-exploration":               ["artificial-intelligence-ai", "blog", "technology"],
    "transforming-cyber-threat-intelligence-with-language-models-and-gpt-3": ["artificial-intelligence-ai", "blog", "security", "technology"],
    "experiencing-the-magic-of-googles-reallife-ai-model":                ["artificial-intelligence-ai", "blog", "technology"],
    "phd-research-making-waves-in-the-medical-imaging-market-a-spotlight-on-ai-for-mri-patents": ["artificial-intelligence-ai", "blog", "technology"],
    "pioneering-the-next-frontier-ai-and-its-unstoppable-rise":           ["artificial-intelligence-ai", "blog", "technology"],
    "how-ai-is-transforming-the-retail-industry":                         ["artificial-intelligence-ai", "blog", "technology"],
    "a-10-year-old-tech-prodigy-has-risen-to-the-role-of-an-assistant-teacher-at-karachi-university": ["blog"],
    "discovering-a-treasure-trove-of-simple-svg-format-icons":            ["blog"],
    "startup-in-karachi-fixdar-a-new-dimension-to-home-maintenance-and-construction-services": ["blog", "management"],
    "free-hosting":                                                       ["blog", "technology"],
    "mastering-prompt-engineering":                                       ["artificial-intelligence-ai", "blog", "technology"],
    "emerging-trends-in-cybersecurity":                                   ["blog", "security", "technology"],
    "quantum-computing-a-leap-towards-futuristic-computing":              ["blog", "quantum-computing", "technology"],
    "the-future-of-ai-in-healthcare":                                     ["artificial-intelligence-ai", "blog", "technology"],
    "how-to-keep-yourself-productive-while-managing-a-team":              ["blog", "management"],
    "diving-into-big-data-making-decisions-just-got-a-whole-lot-easier":  ["blog", "data-science", "technology"],
}

# Synthetic "news" items (titles taken from the news ticker on the original homepage)
NEWS_ITEMS = [
    ("saudis-40-billion-ai-surge-pioneering-future-technology", "Saudi’s $40 Billion AI Surge: Pioneering Future Technology", "2024-03-21",
     "Saudi Arabia’s Public Investment Fund has announced a $40B vehicle dedicated entirely to artificial intelligence — the largest single allocation of sovereign capital to AI by any government in history. The plan is to build a domestic compute base, fund startups locally and in the US, and position Riyadh as a third pole between Silicon Valley and Beijing."),
    ("meetup-advanced-considerations-in-rag-performance", "Meetup: Advanced Considerations in RAG Performance", "2024-03-20",
     "Our Karachi AI meetup on March 28 will dig into the realities of running Retrieval-Augmented Generation in production: vector index choice, chunking strategies, hybrid retrieval, latency budgeting and the painful question of evaluation. Bring laptops."),
    ("openai-board-dismisses-ceo-sam-altman", "OpenAI Board Dismisses CEO Sam Altman", "2023-11-21",
     "In a move that shocked the industry, OpenAI’s board removed CEO Sam Altman, citing a loss of confidence in his communications. The reversal — Altman returning within five days after employee revolt and Microsoft pressure — is already a Harvard Business School case in the making."),
    ("us-venture-capital-funding-plummets-to-six-year-low", "US Venture Capital Funding Plummets to Six-Year Low", "2023-11-21",
     "Q3 2023 venture funding in the US fell to $36B, the lowest quarterly total since early 2017. The contraction is hitting Series B hardest; later-stage rounds are stalling while seed activity remains relatively healthy."),
    ("chinese-chatgpt-version-ernie", "Chinese ChatGPT version, Ernie!", "2023-10-18",
     "Baidu has opened public access to ERNIE Bot 4.0, its latest large language model. Early benchmarks place it within striking distance of GPT-4 on Chinese-language tasks, though independent evaluation on English tasks is still pending."),
    ("grand-offer-cyber-security-courses", "Grand Offer: Cyber Security Courses!", "2023-10-11",
     "Digital Karachi has partnered with three regional training providers to offer subsidised cyber-security certification tracks for Karachi residents. Bursaries available; women and non-binary applicants particularly encouraged."),
]

# ---------------------------------------------------------------------------
# Asset references injected into the page <head> by the hand-written template.
# Kept minimal: Google Fonts + local CSS + JS.
# ---------------------------------------------------------------------------
CDN_HEAD_BLOCK = ""  # legacy; new template handles head assets directly


def clean_html(src):
    """Strip GA/MonsterInsights tracking and broken external `digitalkarachi.com`
    asset references, then inject CDN replacements at the top of <head>.
    Safe to call on the whole page or on a head/foot fragment.
    """
    out = src

    # 0) Strip any previously-injected SR-only <h1 class="dk-sr-h1"> so that
    #    re-extracting the template from a prior build doesn't propagate it
    #    into every page.
    out = re.sub(
        r'<h1\s+class="dk-sr-h1"[^>]*>[^<]*</h1>\s*',
        '', out, flags=re.I)

    # 1) Strip the gtag.js loader and any data-cfasync/MonsterInsights inline
    #    config that references G-WPLFFHFSV7.
    out = re.sub(
        r'<script[^>]*src=["\'](?://|https?://)www\.googletagmanager\.com/[^"\']+["\'][^>]*></script>\s*',
        '', out, flags=re.I)
    # Big inline GA disable / __gaTracker shim
    out = re.sub(
        r'<script[^>]*data-cfasync=["\']false["\'][^>]*>\s*(?:var\s+disableStrs|window\.dataLayer|var\s+monsterinsights_frontend)[\s\S]*?</script>\s*',
        '', out, flags=re.I)
    # Any remaining script blocks that mention G-WPLFFHFSV7 or __gaTracker
    out = re.sub(
        r'<script[^>]*>[^<]*(?:G-WPLFFHFSV7|__gaTracker|monsterinsights)[\s\S]*?</script>\s*',
        '', out, flags=re.I)
    # dns-prefetch hints to googletagmanager
    out = re.sub(
        r'<link[^>]*rel=["\']dns-prefetch["\'][^>]*googletagmanager[^>]*/?>\s*',
        '', out, flags=re.I)

    # 2) Strip <link>/<script> tags whose href/src is an absolute reference to
    #    https://digitalkarachi.com/... — the live host is gone and these
    #    would all 404/CORS-fail. We replace them in bulk with the CDN block
    #    injected at the top of <head>.
    out = re.sub(
        r'<link\s[^>]*href=["\']https?://digitalkarachi\.com/[^"\']+["\'][^>]*/?>\s*',
        '', out, flags=re.I)
    out = re.sub(
        r'<script\s[^>]*src=["\']https?://digitalkarachi\.com/[^"\']+["\'][^>]*>\s*</script>\s*',
        '', out, flags=re.I)

    # 2b) Strip the local font CSS link. The original `wp-content/fonts/...css`
    #     embedded 264 woff2 refs to digitalkarachi.com — even though we've
    #     emptied the file, browsers may still serve stale cached content.
    #     Google Fonts is now loaded from fonts.googleapis.com via CDN_HEAD_BLOCK.
    out = re.sub(
        r'<link\s[^>]*href=["\'][^"\']*wp-content/fonts/[^"\']+["\'][^>]*/?>\s*',
        '', out, flags=re.I)

    # 3) Newsletter / wpforms form actions that point at admin-ajax — replace
    #    with a no-op so the form submit doesn't navigate to a 404.
    out = re.sub(
        r'action=["\'][^"\']*admin-ajax\.php[^"\']*["\']',
        'action="#" data-static="true"',
        out, flags=re.I)

    # 3b) Phase 2: point the header search icon (currently href="#") at the
    #     static search page. Two forms handle the attr-order variants.
    out = re.sub(
        r'(<a[^>]*class=["\'][^"\']*header-search-icon[^"\']*["\'][^>]*href=["\'])#(["\'])',
        r'\1search/\2', out, flags=re.I)
    out = re.sub(
        r'(<a[^>]*href=["\'])#(["\'][^>]*class=["\'][^"\']*header-search-icon)',
        r'\1search/\2', out, flags=re.I)

    # 3c) Phase 2: site search form action — point at /search/ which hosts
    #     the client-side search index (also reads ?s= from the query string).
    out = re.sub(
        r'(<form[^>]*role=["\']search["\'][^>]*action=["\'])[^"\']*(["\'])',
        r'\1search/\2', out, flags=re.I)

    # 4) Inject our CDN replacements right after the opening <head>.
    #    First strip any prior DK-CDN-BLOCK so we always inject the current
    #    version (lets us iterate on the block without leaving stale copies).
    out = re.sub(
        r'<!--\s*DK-CDN-BLOCK-START[\s\S]*?DK-CDN-BLOCK-END\s*-->\s*',
        '', out)
    # Legacy strip — earlier builds wrote the block without START/END markers.
    out = re.sub(
        r'<!--\s*Local restoration: CDN replacements[\s\S]*?jquery\.marquee\.min\.js"></script>\s*',
        '', out)
    out = re.sub(r'(<head[^>]*>)', r'\1' + CDN_HEAD_BLOCK, out, count=1)

    return out


# ---------------------------------------------------------------------------
# Hand-written page shell. Replaces the WP city-blog header/footer.
# Tokens (relative paths) are resolved per-page by rewrite_template().
# ---------------------------------------------------------------------------
SVG_SPRITE = '''<svg style="position:absolute;width:0;height:0" aria-hidden="true" focusable="false">
<defs>
<symbol id="i-search" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"></circle><path d="m20 20-3.5-3.5"></path></symbol>
<symbol id="i-menu" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M4 12h16M4 17h16"></path></symbol>
<symbol id="i-close" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="m6 6 12 12M18 6 6 18"></path></symbol>
<symbol id="i-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"></path></symbol>
<symbol id="i-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></symbol>
<symbol id="i-clock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"></circle><path d="M12 7v5l3 2"></path></symbol>
<symbol id="i-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 5l7 7-7 7"></path></symbol>
</defs></svg>'''


def _head_html():
    # Optional verification meta tags (Google Search Console, Bing Webmaster).
    # Set via env vars; rendered into <head> only if non-empty.
    gsc = os.environ.get("GOOGLE_SITE_VERIFICATION", "").strip()
    bing = os.environ.get("BING_SITE_VERIFICATION", "").strip()
    verify_tags = ""
    if gsc:
        verify_tags += f'<meta name="google-site-verification" content="{html.escape(gsc, quote=True)}">\n'
    if bing:
        verify_tags += f'<meta name="msvalidate.01" content="{html.escape(bing, quote=True)}">\n'

    # Optional analytics. Cookieless options preferred.
    #   PLAUSIBLE_DOMAIN     -> Plausible (cookieless). Defaults host to plausible.io.
    #   PLAUSIBLE_SRC        -> override script URL (for self-hosted instances).
    #   GA4_MEASUREMENT_ID   -> Google Analytics 4 (e.g. G-XXXXXXX).
    analytics = ""
    plausible_domain = os.environ.get("PLAUSIBLE_DOMAIN", "").strip()
    plausible_src = os.environ.get(
        "PLAUSIBLE_SRC", "https://plausible.io/js/script.js"
    ).strip()
    if plausible_domain:
        analytics += (
            f'<script defer data-domain="{html.escape(plausible_domain, quote=True)}" '
            f'src="{html.escape(plausible_src, quote=True)}"></script>\n'
        )
    ga4_id = os.environ.get("GA4_MEASUREMENT_ID", "").strip()
    if ga4_id:
        safe_ga = html.escape(ga4_id, quote=True)
        analytics += (
            f'<script async src="https://www.googletagmanager.com/gtag/js?id={safe_ga}"></script>\n'
            f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}"
            f"gtag('js',new Date());gtag('config','{safe_ga}',{{anonymize_ip:true}});</script>\n"
        )

    return '''<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
''' + verify_tags + analytics + '''<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#FAFAF7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0E0F0C" media="(prefers-color-scheme: dark)">
<title>Digital Karachi</title>
<meta name="description" content="AI, technology and the Karachi tech scene. Where Innovation Thrives.">
<link rel="canonical" href="https://digitalkarachi.com/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Digital Karachi">
<meta property="og:title" content="Digital Karachi">
<meta property="og:description" content="AI, technology and the Karachi tech scene. Where Innovation Thrives.">
<meta property="og:url" content="https://digitalkarachi.com/">
<meta property="og:image" content="https://digitalkarachi.com/wp-content/uploads/2023/09/DK-Logo-light.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Digital Karachi">
<meta name="twitter:description" content="AI, technology and the Karachi tech scene. Where Innovation Thrives.">
<link rel="icon" href="wp-content/uploads/2023/09/cropped-favicon-32x32.webp" sizes="32x32" type="image/webp">
<link rel="icon" href="wp-content/uploads/2023/09/cropped-favicon-192x192.webp" sizes="192x192" type="image/webp">
<link rel="apple-touch-icon" href="wp-content/uploads/2023/09/cropped-favicon-192x192.webp">
<link rel="alternate" type="application/rss+xml" title="Digital Karachi feed" href="feed/index.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,600;0,9..144,700;1,9..144,500&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400&display=swap" onload="this.onload=null;this.rel='stylesheet'">
<noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,600;0,9..144,700;1,9..144,500&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400&display=swap"></noscript>
<link rel="stylesheet" href="wp-content/themes/dk-modern/dk-modern.css?v=3">
<script>(function(){try{var t=localStorage.getItem('dk-theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>
<script defer src="wp-content/themes/dk-modern/dk-modern.js?v=3"></script>
</head>
<body class="dk-body">
''' + SVG_SPRITE + '''
<a class="dk-skip" href="#main">Skip to content</a>
<header class="dk-nav" role="banner">
  <div class="dk-nav-inner">
    <a class="dk-wordmark" href="index.html" aria-label="Digital Karachi — home"><em>Digital</em> Karachi</a>
    <nav class="dk-nav-links" aria-label="Primary">
      <a href="index.html">Blog</a>
      <a href="news/index.html">Tech updates</a>
      <a href="about/index.html">About</a>
      <a href="contact/index.html">Contact</a>
    </nav>
    <div class="dk-nav-tools">
      <a class="dk-icon-btn" href="search/index.html" aria-label="Search"><svg width="18" height="18"><use href="#i-search"/></svg></a>
      <button class="dk-icon-btn dk-theme-toggle" aria-label="Toggle colour theme" type="button"><svg class="dk-i-moon" width="18" height="18"><use href="#i-moon"/></svg><svg class="dk-i-sun" width="18" height="18"><use href="#i-sun"/></svg></button>
      <button class="dk-icon-btn dk-mobile-menu-btn" aria-label="Open menu" type="button"><svg width="20" height="20"><use href="#i-menu"/></svg></button>
    </div>
  </div>
</header>
<div class="dk-mobile-overlay" hidden data-open="false" aria-label="Site navigation">
  <button class="dk-icon-btn dk-close" aria-label="Close menu" type="button"><svg width="22" height="22"><use href="#i-close"/></svg></button>
  <a href="index.html">Blog</a>
  <a href="news/index.html">Tech updates</a>
  <a href="about/index.html">About</a>
  <a href="contact/index.html">Contact</a>
  <a href="search/index.html">Search</a>
</div>
<div class="dk-progress" hidden></div>
<main id="main">
'''


def _foot_html():
    return '''
</main>
<footer class="dk-footer" role="contentinfo">
  <div class="dk-footer-inner">
    <div class="dk-footer-cols">
      <div>
        <h4>Sections</h4>
        <ul>
          <li><a href="index.html">Blog</a></li>
          <li><a href="news/index.html">Tech updates</a></li>
          <li><a href="about/index.html">About</a></li>
          <li><a href="contact/index.html">Contact</a></li>
        </ul>
      </div>
      <div>
        <h4>Topics</h4>
        <ul>
          <li><a href="category/artificial-intelligence-ai/index.html">Artificial Intelligence</a></li>
          <li><a href="category/security/index.html">Cybersecurity</a></li>
          <li><a href="category/data-science/index.html">Data Science</a></li>
          <li><a href="category/cloud-computing/index.html">Cloud Computing</a></li>
        </ul>
      </div>
      <div>
        <h4>Elsewhere</h4>
        <ul>
          <li><a href="feed/index.xml">RSS feed</a></li>
          <li><a href="privacy-policy/index.html">Privacy</a></li>
          <li><a href="sitemap.xml">Sitemap</a></li>
        </ul>
      </div>
    </div>
    <div class="dk-footer-wordmark" aria-hidden="true"><em>Digital</em> Karachi</div>
    <div class="dk-footer-bottom">
      <span>© Digital Karachi · Where Innovation Thrives</span>
    </div>
  </div>
</footer>
</body>
</html>
'''


def extract_template():
    """Return hand-written HEAD_HTML / FOOT_HTML strings.

    The site no longer uses the original WP city-blog markup. We emit a
    minimal modern shell whose paths are root-relative; rewrite_template()
    re-roots them per page.
    """
    return _head_html(), _foot_html()

# ---------------------------------------------------------------------------
# Parsing the existing index + page/2 for post metadata (img/date/excerpt)
# ---------------------------------------------------------------------------
ART_RE = re.compile(r'<article[^>]*id="post-(\d+)"[^>]*class="([^"]*)"[^>]*>(.*?)</article>', re.S)

def parse_posts():
    """Load all posts from the file-per-post JSON store at `content/posts/`.

    Returns a dict (slug -> metadata) sorted by date_iso desc. The dict shape
    intentionally matches the legacy archive-scraping output so downstream
    renderers don't need to change:
        {id, slug, title, img, date_iso, date, excerpt, categories}

    Also rebuilds the `POST_BODIES` compat shim so legacy lookups like
    `POST_BODIES.get(slug, {}).get('body')` still work everywhere.
    """
    global POST_BODIES
    POST_BODIES = {}
    posts = {}
    loaded = load_posts(CONTENT)
    if not loaded:
        sys.stderr.write(
            "ERROR: No posts found in content/posts/. Run scripts/migrate_posts.py first.\n"
        )
        sys.exit(1)
    for idx, p in enumerate(loaded, start=1):
        if p.image:
            img = p.image
        else:
            primary_cat = p.categories[0] if p.categories else None
            img = featured_image_url(p.slug, primary_cat)
        posts[p.slug] = dict(
            id=str(idx),
            slug=p.slug,
            title=p.title,
            img=img,
            date_iso=p.date_iso,
            date=date_display(p.date_iso),
            excerpt=p.excerpt,
            categories=p.categories,
        )
        POST_BODIES[p.slug] = {
            "body": p.body_html,
            "excerpt": p.excerpt,
            "tags": p.tags,
        }
    # Sort by date desc
    return dict(sorted(posts.items(), key=lambda kv: kv[1]["date_iso"], reverse=True))


def load_news_items():
    """Load all news items from `content/news/`, sorted by date desc.

    Returns a list of (slug, title, date_iso, body) tuples (same shape as the
    legacy `NEWS_ITEMS` constant) so downstream code stays unchanged.
    """
    items = load_news(CONTENT)
    items.sort(key=lambda n: n.date_iso, reverse=True)
    return [(n.slug, n.title, n.date_iso, n.body) for n in items]

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------
def rel(from_path, to_path):
    """from_path / to_path are workspace-root-relative paths (POSIX)."""
    r = os.path.relpath(to_path, os.path.dirname(from_path))
    return r if r != "." else "./"

def write(target_rel, content):
    dest = SITE / target_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return target_rel

# ---------------------------------------------------------------------------
# Responsive image helper. Given a site-rooted image path (raster or webp),
# discover WordPress-style sibling size variants (`name-WxH.ext`) and emit
# `<img>` with srcset + sizes + intrinsic width/height. Prevents CLS and
# lets the browser pick a small variant on phones.
# ---------------------------------------------------------------------------
_RESPONSIVE_CACHE = {}

def _responsive_variants(site_rel_path):
    """Return [(width, height, site_rel_path), …] sorted by width ascending,
    for `.webp` siblings of the given image."""
    if site_rel_path in _RESPONSIVE_CACHE:
        return _RESPONSIVE_CACHE[site_rel_path]
    p = Path(site_rel_path)
    stem = p.stem
    # Strip a trailing -WxH or -scaled to derive the WP base name.
    base = re.sub(r'-(\d+)x(\d+)$', '', stem)
    base = re.sub(r'-scaled$', '', base)
    parent = SITE / p.parent
    out = []
    if parent.is_dir():
        for f in parent.iterdir():
            if not f.is_file() or f.suffix.lower() != ".webp":
                continue
            m = re.match(re.escape(base) + r'-(\d+)x(\d+)\.webp$', f.name)
            if m:
                out.append((int(m.group(1)), int(m.group(2)),
                            (p.parent / f.name).as_posix()))
    out.sort()
    _RESPONSIVE_CACHE[site_rel_path] = out
    return out

def responsive_img_attrs(current_path, site_rel_path, sizes_attr,
                          alt, eager=False, klass=""):
    """Build an <img> tag with srcset + sizes + width/height.
    `current_path` is the building page; `site_rel_path` is the image."""
    # External URLs (e.g. Picsum featured-image fallback): emit a plain <img>
    # with the absolute URL and a conservative width/height.
    if _is_external_img(site_rel_path):
        safe_alt = html.escape(alt)
        cls_attr = f' class="{klass}"' if klass else ''
        load_attrs = (' loading="eager" fetchpriority="high"'
                      if eager else ' loading="lazy"')
        return (f'<img{cls_attr} src="{site_rel_path}" alt="{safe_alt}"'
                f' width="1200" height="630" decoding="async"{load_attrs} />')
    # Ensure we point at the .webp twin when one exists.
    candidate = site_rel_path
    if not candidate.lower().endswith(".webp"):
        webp_path = re.sub(r'\.(jpe?g|png)$', '.webp', candidate, flags=re.I)
        if (SITE / webp_path).exists():
            candidate = webp_path

    variants = _responsive_variants(candidate)
    src_rel = rel(current_path, candidate)
    safe_alt = html.escape(alt)
    cls_attr = f' class="{klass}"' if klass else ""
    load_attrs = (' loading="eager" fetchpriority="high"'
                  if eager else ' loading="lazy"')

    if not variants:
        return (f'<img{cls_attr} src="{src_rel}" alt="{safe_alt}"'
                f' decoding="async"{load_attrs} />')

    # Largest variant gives intrinsic aspect ratio.
    max_w, max_h, _ = variants[-1]
    srcset = ", ".join(f'{rel(current_path, v[2])} {v[0]}w' for v in variants)
    return (f'<img{cls_attr} src="{src_rel}" srcset="{srcset}"'
            f' sizes="{sizes_attr}" width="{max_w}" height="{max_h}"'
            f' alt="{safe_alt}" decoding="async"{load_attrs} />')

# ---------------------------------------------------------------------------
# Template rewriter: takes the original head_html (which uses the home
# page's relative paths) and rewrites every reference for the new page's
# directory depth, and rewrites navigation/menu links to point to the
# real local pages we are now generating.
# ---------------------------------------------------------------------------
def rewrite_template(tpl, current_page_path, title, description, canonical_path):
    """
    current_page_path: workspace-relative path of the page being built
    canonical_path:    URL path to advertise (e.g. "category/blog/")
    """
    out = tpl

    # Re-root every relative href/src/action attribute for the new page's depth.
    # Anything that is not absolute (no scheme, not protocol-relative, not a
    # fragment / mailto / tel / data URI) is treated as relative-to-site-root
    # in the original archived index.html and must be re-pathed.
    def reroot_attr(m):
        attr, q, val = m.group(1), m.group(2), m.group(3)
        if not val:
            return m.group(0)
        if re.match(r'^(https?:)?//', val):
            return m.group(0)
        if val[0] in '#?' or val.startswith(('mailto:', 'tel:', 'data:', 'javascript:')):
            return m.group(0)
        # Strip a leading "./" — irrelevant for rel()
        clean = val.lstrip('./') if val.startswith('./') else val
        # If the value already begins with "../" it was added by our generator
        # for this page — leave it alone.
        if val.startswith('../'):
            return m.group(0)
        new = rel(current_page_path, clean)
        return f'{attr}={q}{new}{q}'

    out = re.sub(
        r'((?:href|src|action))=(["\'])([^"\']*)\2',
        reroot_attr,
        out,
    )

    # Handle the small number of srcset-style attributes that contain bare
    # "wp-content/..." prefixes outside of href/src.
    for prefix in ("wp-content/", "wp-includes/"):
        rerooted = rel(current_page_path, prefix.rstrip('/')) + '/'
        out = re.sub(
            r'(\s|,|"|\'|\()' + re.escape(prefix),
            lambda m, v=rerooted: m.group(1) + v,
            out,
        )

    # Rewrite the Wayback "nearest" fallback links for paths we now generate locally
    def way_repl(m):
        path = m.group(1)
        # category
        cm = re.match(r"category/([^/]+)/$", path)
        if cm:
            return rel(current_page_path, f"category/{cm.group(1)}/index.html")
        cm = re.match(r"category/technology/([^/]+)/$", path)
        if cm:
            return rel(current_page_path, f"category/{cm.group(1)}/index.html")
        # news index or item
        if path == "news/":
            return rel(current_page_path, "news/index.html")
        nm = re.match(r"news/([^/]+)/$", path)
        if nm:
            return rel(current_page_path, f"news/{nm.group(1)}/index.html")
        # author
        if path == "author/digitalkarachi-com/":
            return rel(current_page_path, "author/digitalkarachi-com/index.html")
        # tags
        tm = re.match(r"tag/([^/]+)/$", path)
        if tm:
            return rel(current_page_path, f"tag/{tm.group(1)}/index.html")
        # privacy
        if path == "privacy-policy/":
            return rel(current_page_path, "privacy-policy/index.html")
        # individual post
        if path.endswith("/") and "/" not in path[:-1]:
            return rel(current_page_path, f"{path.rstrip('/')}/index.html")
        # leave as-is
        return m.group(0)

    out = re.sub(r"https://web\.archive\.org/web/2/https://digitalkarachi\.com/([^\"' )<>]*)", way_repl, out)

    # Override <title> and meta description for this page
    out = re.sub(r"<title>[^<]*</title>", f"<title>{html.escape(title)}</title>", out, count=1)
    out = re.sub(
        r'(<meta name="description" content=")[^"]*(")',
        lambda m: m.group(1) + html.escape(description, quote=True) + m.group(2),
        out, count=1
    )
    # Update canonical
    out = re.sub(
        r'(<link rel="canonical" href=")[^"]*(")',
        lambda m: m.group(1) + f"https://digitalkarachi.com/{canonical_path}" + m.group(2),
        out, count=1
    )
    # Update Open Graph + Twitter Card tags per-page
    canonical_url = f"https://digitalkarachi.com/{canonical_path}"
    esc_title = html.escape(title, quote=True)
    esc_desc = html.escape(description, quote=True)
    out = re.sub(
        r'(<meta property="og:title" content=")[^"]*(")',
        lambda m: m.group(1) + esc_title + m.group(2), out, count=1)
    out = re.sub(
        r'(<meta property="og:description" content=")[^"]*(")',
        lambda m: m.group(1) + esc_desc + m.group(2), out, count=1)
    out = re.sub(
        r'(<meta property="og:url" content=")[^"]*(")',
        lambda m: m.group(1) + canonical_url + m.group(2), out, count=1)
    out = re.sub(
        r'(<meta name="twitter:title" content=")[^"]*(")',
        lambda m: m.group(1) + esc_title + m.group(2), out, count=1)
    out = re.sub(
        r'(<meta name="twitter:description" content=")[^"]*(")',
        lambda m: m.group(1) + esc_desc + m.group(2), out, count=1)
    # Remove the "next" link since paginated archives are page-specific
    out = re.sub(r'<link rel="next" href="[^"]*"\s*/?>', "", out)

    # Update active menu items based on current page
    out = re.sub(r'class="([^"]*?)\bcurrent-menu-item\b([^"]*?)"', r'class="\1\2"', out)
    out = re.sub(r'class="([^"]*?)\bcurrent_page_item\b([^"]*?)"', r'class="\1\2"', out)
    out = re.sub(r'\saria-current="page"', '', out)

    # Body class: change from "home blog" to a page-specific class. The caller
    # can patch this further if needed.
    out = re.sub(
        r'<body class="home blog ([^"]*)"',
        r'<body class="\1"',
        out, count=1,
    )

    return out

# ---------------------------------------------------------------------------
# Reusable page-shell builder
# ---------------------------------------------------------------------------
def page_shell(current_path, title, description, canonical, body_main, body_class="dk-page", banner_html=""):
    head = rewrite_template(HEAD_HTML, current_path, title, description, canonical)
    foot = rewrite_template(FOOT_HTML, current_path, title, description, canonical)
    # Patch body class
    head = re.sub(r'<body class="[^"]*"', f'<body class="dk-body {body_class}"', head, count=1)
    return head + banner_html + body_main + foot

# ---------------------------------------------------------------------------
# Article-card renderer (used in archives + home grid)
# ---------------------------------------------------------------------------
def render_article_card(current_path, post, variant=""):
    """variant: "" (default), "is-large", "is-wide"."""
    link = rel(current_path, f"{post['slug']}/index.html")
    img = post["img"] if _is_external_img(post["img"]) else (rel(current_path, post["img"]) if post["img"] else "")
    primary_cat = post["categories"][0] if post["categories"] else None
    cat_display = CATEGORIES.get(primary_cat, (primary_cat or "Blog", None))[0] if primary_cat else "Blog"
    cat_link = rel(current_path, f"category/{primary_cat}/index.html") if primary_cat else "#"
    excerpt = post["excerpt"] or POST_BODIES.get(post["slug"], {}).get("excerpt", "")
    excerpt_html = html.escape(excerpt[:180]) + ("…" if len(excerpt) > 180 else "")
    # Card-image sizes: full-width on phones, ~half viewport on desktop
    # (≈ 360-720 CSS px). Large/wide variants render bigger on desktop.
    if variant in ("is-large", "is-wide"):
        sizes_attr = "(max-width: 768px) 100vw, 720px"
    else:
        sizes_attr = "(max-width: 768px) 100vw, 360px"
    img_html = responsive_img_attrs(current_path, post["img"], sizes_attr,
                                     post["title"], eager=False) if post["img"] else ""
    cls = f"dk-card {variant}".strip()
    return f'''
<article class="{cls}">
  <a class="dk-card-figure" href="{link}" aria-hidden="true" tabindex="-1">{img_html}</a>
  <div class="dk-eyebrow"><a href="{cat_link}">{html.escape(cat_display)}</a></div>
  <h2 class="dk-card-title"><a href="{link}">{html.escape(post["title"])}</a></h2>
  <p class="dk-card-excerpt">{excerpt_html}</p>
  <div class="dk-card-meta"><time datetime="{post["date_iso"]}">{post["date"]}</time></div>
</article>'''

# ---------------------------------------------------------------------------
# Single-post page
# ---------------------------------------------------------------------------
def render_post_page(post, all_posts):
    slug = post["slug"]
    current = f"{slug}/index.html"
    content = POST_BODIES.get(slug)
    if not content:
        body = f"<p><em>Article body for “{post['title']}” is not available in the archive.</em></p>"
        tags = []
    else:
        body = content["body"]
        tags = content.get("tags", [])

    img = post["img"] if _is_external_img(post["img"]) else (rel(current, post["img"]) if post["img"] else "")
    primary_cat = post["categories"][0] if post["categories"] else None
    cat_name = CATEGORIES.get(primary_cat, (primary_cat or "Blog", None))[0] if primary_cat else "Blog"
    cat_link = rel(current, f"category/{primary_cat}/index.html") if primary_cat else "#"

    # Related posts: 3 posts sharing at least one category
    own_cats = set(post["categories"])
    related = [p for p in all_posts.values()
               if p["slug"] != slug and own_cats & set(p["categories"])][:3]
    if len(related) < 3:
        for p in all_posts.values():
            if p["slug"] != slug and p not in related:
                related.append(p)
                if len(related) == 3:
                    break

    related_cards = ""
    for r in related:
        rlink = rel(current, f"{r['slug']}/index.html")
        rimg_html = responsive_img_attrs(
            current, r["img"], "(max-width: 768px) 50vw, 240px",
            r["title"], eager=False) if r["img"] else ""
        related_cards += f'''
        <article class="dk-related-card">
          <a class="dk-related-card-figure" href="{rlink}" aria-hidden="true" tabindex="-1">{rimg_html}</a>
          <a class="dk-related-card-title" href="{rlink}">{html.escape(r["title"])}</a>
          <div class="dk-related-card-meta"><time datetime="{r["date_iso"]}">{r["date"]}</time></div>
        </article>'''

    tags_html = "".join(
        f'<a class="dk-tag" href="{rel(current, f"tag/{slugify(t)}/index.html")}">{html.escape(t)}</a>'
        for t in tags
    )

    desc = (POST_BODIES.get(slug, {}).get("excerpt") or post["excerpt"] or post["title"])[:155]

    # JSON-LD structured data
    import json as _json
    breadcrumb_items = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://digitalkarachi.com/"},
    ]
    if primary_cat:
        breadcrumb_items.append({"@type": "ListItem", "position": 2, "name": cat_name,
                                 "item": f"https://digitalkarachi.com/category/{primary_cat}/"})
    breadcrumb_items.append({"@type": "ListItem", "position": len(breadcrumb_items) + 1,
                             "name": post["title"], "item": f"https://digitalkarachi.com/{slug}/"})
    ld_article = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": post["title"], "description": desc,
        "datePublished": post["date_iso"],
        "dateModified": post.get("date_modified") or post["date_iso"],
        "author": {"@type": "Person", "name": "digitalkarachi.com",
                   "url": "https://digitalkarachi.com/author/digitalkarachi-com/"},
        "publisher": {"@type": "Organization", "name": "Digital Karachi",
                      "logo": {"@type": "ImageObject",
                               "url": "https://digitalkarachi.com/wp-content/uploads/2023/09/DK-Logo-light.png"}},
        "mainEntityOfPage": f"https://digitalkarachi.com/{slug}/",
        "articleSection": cat_name,
        "keywords": ", ".join(tags) if tags else cat_name,
    }
    if post["img"]:
        ld_article["image"] = post["img"] if _is_external_img(post["img"]) else f"https://digitalkarachi.com/{post['img']}"
    ld_breadcrumb = {"@context": "https://schema.org", "@type": "BreadcrumbList",
                     "itemListElement": breadcrumb_items}
    json_ld = (
        f'<script type="application/ld+json">{_json.dumps(ld_article)}</script>'
        f'<script type="application/ld+json">{_json.dumps(ld_breadcrumb)}</script>'
    )

    home_link = rel(current, "index.html")
    contact_link = rel(current, "contact/index.html")
    author_link = rel(current, "author/digitalkarachi-com/index.html")
    author_img = rel(current, "wp-content/uploads/author-dk.svg")
    # Post hero is full-width on phones, capped at ~960 CSS px on desktop.
    hero_img_html = responsive_img_attrs(
        current, post["img"],
        "(max-width: 768px) 100vw, 960px",
        post["title"], eager=True) if post["img"] else ""
    hero_html = f'<figure class="dk-article-hero">{hero_img_html}</figure>' if post["img"] else ""

    main = f'''
{json_ld}
<article class="dk-article">
  <nav class="dk-breadcrumb" aria-label="Breadcrumb">
    <a href="{home_link}">Home</a><span>/</span>
    <a href="{cat_link}">{html.escape(cat_name)}</a><span>/</span>
    <span aria-current="page">{html.escape(post["title"])[:48]}</span>
  </nav>
  <header class="dk-article-header">
    <div class="dk-eyebrow"><a href="{cat_link}">{html.escape(cat_name)}</a></div>
    <h1 class="dk-article-title">{html.escape(post["title"])}</h1>
    <div class="dk-article-meta">
      <span><a href="{author_link}">digitalkarachi.com</a></span>
      <span><time datetime="{post["date_iso"]}">{post["date"]}</time></span>
      <span><svg width="14" height="14"><use href="#i-clock"/></svg>{reading_time(body)} min read</span>
    </div>
  </header>
  {hero_html}
  <div class="dk-prose">
{body}
  </div>
  <footer class="dk-article-footer">
    {f'<div class="dk-tags">{tags_html}</div>' if tags_html else ""}
    <div class="dk-author-bio">
      <img src="{author_img}" alt="Digital Karachi author avatar" width="64" height="64" />
      <div>
        <strong>digitalkarachi.com</strong>
        <p>Independent writing on AI, technology and the Karachi tech scene. Where Innovation Thrives.</p>
      </div>
    </div>
    <aside class="dk-comments-notice" aria-label="Comments status">
      <strong>Comments are closed</strong>
      This page is a static archive of the Digital Karachi blog. Reach out via the <a href="{contact_link}">contact page</a> if you'd like to get in touch.
    </aside>
    <section class="dk-related" aria-label="Related articles">
      <h2>Related reading</h2>
      <div class="dk-related-grid">{related_cards}</div>
    </section>
  </footer>
</article>
'''
    page = page_shell(current, post["title"], desc, f"{slug}/", main, body_class="dk-single")
    # Preload the article-hero LCP image with the responsive srcset so the
    # browser can start fetching it in parallel with CSS.
    if post.get("img") and not _is_external_img(post["img"]):
        candidate = post["img"]
        if not candidate.lower().endswith(".webp"):
            webp_path = re.sub(r'\.(jpe?g|png)$', '.webp', candidate, flags=re.I)
            if (SITE / webp_path).exists():
                candidate = webp_path
        variants = _responsive_variants(candidate)
        if variants:
            srcset = ", ".join(f'{rel(current, v[2])} {v[0]}w' for v in variants)
            preload = (
                f'<link rel="preload" as="image" '
                f'imagesrcset="{srcset}" '
                f'imagesizes="(max-width: 768px) 100vw, 960px" '
                f'fetchpriority="high">\n'
            )
            page = page.replace("</head>", preload + "</head>", 1)
    write(current, page)

def slugify(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

# ---------------------------------------------------------------------------
# Archive page (used for categories, tags, author, news index)
# ---------------------------------------------------------------------------
def render_archive(current_path, title, description, canonical, posts, intro_html=""):
    if posts:
        cards = "\n".join(render_article_card(current_path, p) for p in posts)
    else:
        cards = '<p style="grid-column:span 12;color:var(--ink-mute);font-family:var(--mono);">No articles in this archive yet.</p>'
    eyebrow = "Archive"
    if "category" in canonical: eyebrow = "Category"
    elif "tag/" in canonical: eyebrow = "Tag"
    elif "author/" in canonical: eyebrow = "Author"
    elif canonical.startswith("news"): eyebrow = "Tech updates"
    main = f'''
<header class="dk-page-header">
  <div class="dk-eyebrow">{eyebrow}</div>
  <h1>{html.escape(title.split(" – ")[0] if " – " in title else title)}</h1>
  {intro_html}
</header>
<section class="dk-grid">
{cards}
</section>
'''
    return page_shell(current_path, title, description, canonical, main, body_class="dk-archive")

# ---------------------------------------------------------------------------
# Placeholder SVG image for unarchived post heroes
# ---------------------------------------------------------------------------
PLACEHOLDER_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1640 664" preserveAspectRatio="xMidYMid slice">
  <defs>
    <linearGradient id="g" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#0f766e"/>
      <stop offset="1" stop-color="#16a34a"/>
    </linearGradient>
  </defs>
  <rect width="1640" height="664" fill="url(#g)"/>
  <text x="50%" y="48%" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif" font-size="68" font-weight="700" fill="#ffffff" text-anchor="middle">Digital Karachi</text>
  <text x="50%" y="58%" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif" font-size="32" fill="#d1fae5" text-anchor="middle">Where Innovation Thrives</text>
</svg>'''


def make_placeholder_svg(title):
    """Per-post placeholder hero with the title wrapped over the gradient."""
    # crude word-wrap into up to 3 lines of ~32 chars
    words, lines, cur = title.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > 32 and cur:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
        if len(lines) == 2:
            break
    if cur:
        lines.append(cur)
    # remaining words go into the last line, ellipsised
    used = " ".join(lines)
    if len(used) < len(title):
        if len(lines) < 3:
            tail = title[len(used):].strip()
            lines.append(tail[:30] + ("…" if len(tail) > 30 else ""))
        else:
            lines[-1] = lines[-1][:28] + "…"
    lines_svg = ""
    base_y = 320 - (len(lines) - 1) * 38
    for i, line in enumerate(lines):
        y = base_y + i * 76
        lines_svg += (
            f'<text x="50%" y="{y}" font-family="-apple-system,BlinkMacSystemFont,\'Segoe UI\','
            f'Roboto,sans-serif" font-size="58" font-weight="700" fill="#ffffff" '
            f'text-anchor="middle">{html.escape(line)}</text>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1640 664" '
        'preserveAspectRatio="xMidYMid slice">'
        '<defs><linearGradient id="g" x1="0" x2="1" y1="0" y2="1">'
        '<stop offset="0" stop-color="#0f766e"/>'
        '<stop offset="1" stop-color="#16a34a"/>'
        '</linearGradient></defs>'
        '<rect width="1640" height="664" fill="url(#g)"/>'
        + lines_svg +
        '<text x="50%" y="600" font-family="-apple-system,BlinkMacSystemFont,'
        '\'Segoe UI\',Roboto,sans-serif" font-size="26" fill="#d1fae5" '
        'text-anchor="middle">digitalkarachi.com · Where Innovation Thrives</text>'
        '</svg>'
    )


AUTHOR_AVATAR_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 80">'
    '<defs><linearGradient id="ag" x1="0" x2="1" y1="0" y2="1">'
    '<stop offset="0" stop-color="#0f766e"/>'
    '<stop offset="1" stop-color="#16a34a"/>'
    '</linearGradient></defs>'
    '<circle cx="40" cy="40" r="40" fill="url(#ag)"/>'
    '<text x="50%" y="55%" dominant-baseline="middle" text-anchor="middle" '
    'font-family="-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif" '
    'font-size="34" font-weight="700" fill="#ffffff">DK</text>'
    '</svg>'
)


def reading_time(body_html):
    """Approximate reading time in minutes from a chunk of HTML."""
    text = re.sub(r'<[^>]+>', ' ', body_html or '')
    words = len(text.split())
    return max(1, round(words / 220))

# ---------------------------------------------------------------------------
# News (custom post type) — built from the news ticker on the home page
# ---------------------------------------------------------------------------
def render_news_item(news_slug, title, date_iso, body, current_path):
    news_link = rel(current_path, "news/index.html")
    home_link = rel(current_path, "index.html")
    main = f'''
<article class="dk-article">
  <nav class="dk-breadcrumb" aria-label="Breadcrumb">
    <a href="{home_link}">Home</a><span>/</span>
    <a href="{news_link}">Tech updates</a><span>/</span>
    <span aria-current="page">{html.escape(title)[:48]}</span>
  </nav>
  <header class="dk-article-header">
    <div class="dk-eyebrow">Tech update</div>
    <h1 class="dk-article-title">{html.escape(title)}</h1>
    <div class="dk-article-meta">
      <span><time datetime="{date_iso}">{date_iso}</time></span>
    </div>
  </header>
  <div class="dk-prose">
    <p>{html.escape(body)}</p>
    <p><a href="{news_link}">← Back to all tech updates</a></p>
  </div>
</article>'''
    return page_shell(current_path, title, body[:155], f"news/{news_slug}/", main, body_class="dk-news-single")

# ---------------------------------------------------------------------------
# About / Contact / Privacy / Search
# ---------------------------------------------------------------------------
def render_about():
    current = "about/index.html"
    contact_link = rel(current, "contact/index.html")
    main = f'''
<article class="dk-article">
  <header class="dk-article-header">
    <div class="dk-eyebrow">About</div>
    <h1 class="dk-article-title">About Digital Karachi</h1>
  </header>
  <div class="dk-prose">
    <p><strong>Digital Karachi</strong> is a personal publication about technology, artificial intelligence and the people building the future from Pakistan. <em>Where Innovation Thrives.</em></p>
    <h2>What we cover</h2>
    <ul>
      <li>Honest explainers of AI, machine learning and data science — written for working professionals, not for the LinkedIn algorithm.</li>
      <li>Pakistani startup stories: who is building, what is shipping, what is broken.</li>
      <li>Practical guides on cybersecurity, cloud, prompt engineering and the modern data stack.</li>
      <li>The occasional opinionated take on what the global AI race means for the Global South.</li>
    </ul>
    <h2>Who writes it</h2>
    <p>Digital Karachi is independently published. There is no parent company, no PR agency, no affiliate scheme. All opinions are the author's; mistakes will be corrected publicly when (not if) we find them.</p>
    <h2>Get in touch</h2>
    <p>Send tips, corrections or angry rebuttals via the <a href="{contact_link}">contact page</a>. We read everything.</p>
  </div>
</article>'''
    return page_shell(current, "About – Digital Karachi", "About Digital Karachi — where innovation thrives.", "about/", main, body_class="dk-page-about")

def render_contact():
    current = "contact/index.html"
    main = '''
<article class="dk-article">
  <header class="dk-article-header">
    <div class="dk-eyebrow">Contact</div>
    <h1 class="dk-article-title">Get in touch</h1>
  </header>
  <div class="dk-prose">
    <p>Have a tip, a correction, a story idea or just want to say hello? Drop us a line — we read everything.</p>
    <form class="dk-form" onsubmit="alert('Thanks! This contact form is read-only in the restored archive.'); return false;">
      <input type="text" placeholder="Your name" required />
      <input type="email" placeholder="Your email" required />
      <input type="text" placeholder="Subject" />
      <textarea placeholder="Your message" rows="6" required></textarea>
      <button type="submit">Send message</button>
    </form>
    <div class="dk-contact-info">
      <p><strong>Email</strong> hello@digitalkarachi.com</p>
      <p><strong>Twitter / X</strong> @digitalkarachi</p>
      <p><strong>Address</strong> Karachi, Pakistan</p>
    </div>
  </div>
</article>'''
    return page_shell(current, "Contact – Digital Karachi", "Get in touch with Digital Karachi.", "contact/", main, body_class="dk-page-contact")

def render_privacy():
    current = "privacy-policy/index.html"
    main = '''
<article class="dk-article">
  <header class="dk-article-header">
    <div class="dk-eyebrow">Legal</div>
    <h1 class="dk-article-title">Privacy Policy</h1>
  </header>
  <div class="dk-prose">
    <p>This privacy policy explains what limited information Digital Karachi collects when you visit this site, and how that information is used.</p>
    <h2>What we collect</h2>
    <p>This site is a static archive. It does not run server-side code, set first-party cookies or log visitor IPs. If you submit the (read-only demo) comment or contact forms, no data is stored or transmitted.</p>
    <h2>Third-party services</h2>
    <p>The original publication used Google Analytics. The tracking script has been removed in this static restoration; no analytics data is sent.</p>
    <h2>Your rights</h2>
    <p>Under Pakistan's draft Personal Data Protection Bill, the EU's GDPR and California's CCPA, you have the right to know what data is collected about you, to request its deletion, and to opt out of any tracking. Because this restoration does not collect data, no action is required to exercise those rights.</p>
    <h2>Changes</h2>
    <p>If this policy changes, the updated version will be published here. Last updated: April 2024.</p>
  </div>
</article>'''
    return page_shell(current, "Privacy Policy – Digital Karachi", "Digital Karachi privacy policy.", "privacy-policy/", main, body_class="dk-page-privacy")

def render_search(all_posts):
    current = "search/index.html"
    # Build a compact body-keyword bag per post for full-text recall.
    # Strip HTML, lowercase, drop short/stop words, dedupe; cap at 80 unique
    # tokens per post (~0.5 KB raw) so the index stays under ~200 KB total.
    _STOP = set(
        "a an the and or but if then so to of in on at by for with from is are was were "
        "be been being have has had do does did this that these those it its as not no "
        "you your we our they their he she his her them us i me my mine yours ours theirs "
        "can will would should could may might must shall about into over under more most "
        "less many much such some any all each every other another which what when where "
        "why how than too very also only just like one two three new also up down out".split()
    )
    def _bag(slug: str) -> str:
        body = POST_BODIES.get(slug, {}).get("body", "")
        text = re.sub(r"<[^>]+>", " ", body).lower()
        toks = re.findall(r"[a-z][a-z0-9\-]{3,}", text)
        seen, out = set(), []
        for t in toks:
            if t in _STOP or t in seen:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= 80:
                break
        return " ".join(out)

    index = [
        {"title": p["title"], "url": f"../{p['slug']}/",
         "excerpt": (POST_BODIES.get(p['slug'], {}).get('excerpt') or p.get('excerpt') or '')[:200],
         "categories": [CATEGORIES.get(c, (c.title(), None))[0] for c in p["categories"]],
         "kw": _bag(p["slug"])}
        for p in all_posts.values()
    ]
    import json as _json
    main = f'''
<article class="dk-article">
  <header class="dk-article-header">
    <div class="dk-eyebrow">Search</div>
    <h1 class="dk-article-title">Search the archive</h1>
  </header>
  <div class="dk-prose">
    <input type="search" id="q" class="dk-search-box" placeholder="Search articles…" autofocus aria-label="Search articles" />
    <div id="results"></div>
  </div>
</article>
<script>
const INDEX = {_json.dumps(index)};
const q = document.getElementById('q');
const out = document.getElementById('results');
function escapeHtml(s){{return String(s).replace(/[&<>"]/g, c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);}}
function render(items){{
  if(!items.length){{ out.innerHTML = '<div class="dk-search-empty">No matching articles.</div>'; return; }}
  out.innerHTML = items.map(p =>
    `<div class="dk-search-result"><h3><a href="${{p.url}}">${{escapeHtml(p.title)}}</a></h3><div class="cats">${{p.categories.map(escapeHtml).join(' · ')}}</div><p>${{escapeHtml(p.excerpt)}}</p></div>`
  ).join('');
}}
function search(){{
  const term = q.value.trim().toLowerCase();
  if(!term){{ render(INDEX); return; }}
  const tokens = term.split(/\\s+/);
  const hits = INDEX.filter(p => {{
  const hay = (p.title + ' ' + p.excerpt + ' ' + p.categories.join(' ') + ' ' + (p.kw || '')).toLowerCase();
    return tokens.every(t => hay.includes(t));
  }});
  render(hits);
}}
q.addEventListener('input', search);
const urlQ = new URLSearchParams(location.search).get('s');
if(urlQ){{ q.value = urlQ; }}
search();
</script>
'''
    return page_shell(current, "Search – Digital Karachi", "Search articles on Digital Karachi.", "search/", main, body_class="dk-page-search")

def setup_assets():
    """No-op in the reskinned build. The new design ships its own CSS/JS
    from `wp-content/themes/dk-modern/` and references no other local
    stylesheets, so we don't need to stub the old WP/Newsletter/Slick CSS.
    """
    pass


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------
def main():
    global HEAD_HTML, FOOT_HTML
    setup_assets()
    HEAD_HTML, FOOT_HTML = extract_template()

    # Inline the theme CSS to eliminate a render-blocking request. The
    # uncompressed file is ~24 KB; brotli on the server gets it to ~6 KB.
    # Removing the round-trip is the biggest remaining FCP/LCP win on slow 4G.
    try:
        css_path = SITE / "wp-content/themes/dk-modern/dk-modern.css"
        if css_path.exists():
            css_inline = css_path.read_text(encoding="utf-8")
            HEAD_HTML = re.sub(
                r'<link rel="stylesheet" href="wp-content/themes/dk-modern/dk-modern\.css\?v=\d+">',
                f'<style id="dk-theme-inline">{css_inline}</style>',
                HEAD_HTML,
                count=1,
            )
    except Exception as e:
        print(f"WARN: could not inline theme CSS: {e}")

    all_posts = parse_posts()
    print(f"Loaded {len(all_posts)} posts from content/posts/.")

    # Replace the legacy hard-coded NEWS_ITEMS with the JSON store so the
    # rest of the build pipeline (news renderer, sitemap, etc.) picks up
    # newly-generated dispatches automatically.
    global NEWS_ITEMS
    NEWS_ITEMS = load_news_items()
    print(f"Loaded {len(NEWS_ITEMS)} news items from content/news/.")

    # 0. Placeholder SVGs (generic + per-post)
    (SITE / "wp-content/uploads").mkdir(parents=True, exist_ok=True)
    (SITE / "wp-content/uploads/placeholder.svg").write_text(PLACEHOLDER_SVG, encoding="utf-8")
    (SITE / "wp-content/uploads/author-dk.svg").write_text(AUTHOR_AVATAR_SVG, encoding="utf-8")
    # Per-post placeholders for posts whose hero image was never archived —
    # each carries the post title so cards aren't visually identical.
    for slug in POST_IMG_FIX:
        if slug not in all_posts:
            continue
        per_path = f"wp-content/uploads/placeholder-{slug}.svg"
        (SITE / per_path).write_text(
            make_placeholder_svg(all_posts[slug]["title"]), encoding="utf-8")
        all_posts[slug]["img"] = per_path

    # 1. Single-post pages
    for slug, post in all_posts.items():
        render_post_page(post, all_posts)
    print(f"Wrote {len(all_posts)} post pages.")

    # 2. Category pages
    by_cat = defaultdict(list)
    for p in all_posts.values():
        for c in p["categories"]:
            by_cat[c].append(p)
    for cat_slug, posts in by_cat.items():
        cat_display = CATEGORIES.get(cat_slug, (cat_slug.title(), None))[0]
        intro = f'<p class="archive-description">All articles filed under <strong>{html.escape(cat_display)}</strong>.</p>'
        write(f"category/{cat_slug}/index.html",
              render_archive(f"category/{cat_slug}/index.html",
                             f"{cat_display} – Digital Karachi",
                             f"All Digital Karachi articles in the {cat_display} category.",
                             f"category/{cat_slug}/", posts, intro))
    # Also generate empty category pages so the sidebar links don't 404
    for cat_slug, (display, _parent) in CATEGORIES.items():
        if cat_slug in by_cat:
            continue
        write(f"category/{cat_slug}/index.html",
              render_archive(f"category/{cat_slug}/index.html",
                             f"{display} – Digital Karachi",
                             f"All Digital Karachi articles in the {display} category.",
                             f"category/{cat_slug}/", [],
                             f'<p class="archive-description">No articles in <strong>{html.escape(display)}</strong> yet — check back soon.</p>'))
    print(f"Wrote {len(CATEGORIES)} category pages.")

    # 3. Tag pages
    by_tag = defaultdict(list)
    for p in all_posts.values():
        for t in POST_BODIES.get(p["slug"], {}).get("tags", []):
            by_tag[slugify(t)].append((t, p))
    for tag_slug, items in by_tag.items():
        display = items[0][0]
        posts = [p for _, p in items]
        write(f"tag/{tag_slug}/index.html",
              render_archive(f"tag/{tag_slug}/index.html",
                             f"#{display} – Digital Karachi",
                             f"Articles tagged with #{display}.",
                             f"tag/{tag_slug}/", posts,
                             f'<p class="archive-description">Articles tagged <strong>#{html.escape(display)}</strong>.</p>'))
    print(f"Wrote {len(by_tag)} tag pages.")

    # 4. Author page
    write("author/digitalkarachi-com/index.html",
          render_archive("author/digitalkarachi-com/index.html",
                         "Articles by digitalkarachi.com",
                         "All articles published by digitalkarachi.com.",
                         "author/digitalkarachi-com/", list(all_posts.values()),
                         '<p class="archive-description">Every article on Digital Karachi, written by the editorial team.</p>'))
    print("Wrote author page.")

    # 5. News index + items
    news_main_cards = ""
    for slug, title, date_iso, body in NEWS_ITEMS:
        write(f"news/{slug}/index.html", render_news_item(slug, title, date_iso, body, f"news/{slug}/index.html"))
        news_main_cards += f'''
        <article class="dk-news-item">
          <time datetime="{date_iso}">{date_iso}</time>
          <div>
            <h2><a href="{slug}/">{html.escape(title)}</a></h2>
            <p>{html.escape(body[:240])}{'…' if len(body) > 240 else ''}</p>
          </div>
        </article>'''
    news_index_main = f'''
<header class="dk-page-header">
  <div class="dk-eyebrow">Tech updates</div>
  <h1>Short dispatches from the wider tech world</h1>
  <p>Curated news items from across AI, security, cloud and the global tech scene.</p>
</header>
<div class="dk-news-list">{news_main_cards}</div>'''
    write("news/index.html",
          page_shell("news/index.html", "Tech Updates – Digital Karachi",
                     "Tech news and short updates from Digital Karachi.",
                     "news/", news_index_main, body_class="dk-news-archive"))
    print(f"Wrote news index + {len(NEWS_ITEMS)} news items.")

    # 6. About / Contact / Privacy / Search
    write("about/index.html", render_about())
    write("contact/index.html", render_contact())
    write("privacy-policy/index.html", render_privacy())
    write("search/index.html", render_search(all_posts))
    print("Wrote about/contact/privacy/search.")

    # 7. Home + paginated archive pages (regenerated with the new design)
    render_home(all_posts)
    render_archive_pages(all_posts)

    # 8. (legacy) global menu patch — no-op in the reskinned build
    patch_global_menu()

    # 9. SEO: sitemap.xml, robots.txt, RSS feed, themed 404 page
    write_seo_files(all_posts)

    # 10. Perf/a11y final pass — lazy-load images, fix missing alts
    finalize_a11y_perf()

    print("All done.")


# ---------------------------------------------------------------------------
# SEO: sitemap.xml, robots.txt, RSS feed, themed 404 page
# ---------------------------------------------------------------------------
SITE_BASE = os.environ.get("SITE_BASE", "https://digitalkarachi.com").rstrip("/")


def write_seo_files(all_posts):
    urls = []
    # Static pages
    static_pages = [
        ("", "weekly", "1.0"),
        ("about/", "monthly", "0.6"),
        ("contact/", "monthly", "0.5"),
        ("privacy-policy/", "yearly", "0.3"),
        ("news/", "weekly", "0.7"),
    ]
    # Add page/2/, page/3/, … for the full paginated archive.
    total_pages = max(1, (len(all_posts) + POSTS_PER_PAGE - 1) // POSTS_PER_PAGE)
    for n in range(2, total_pages + 1):
        static_pages.append((f"page/{n}/", "weekly", "0.5"))
    for path, freq, prio in static_pages:
        urls.append((f"{SITE_BASE}/{path}", None, freq, prio))
    # Posts
    for slug, p in all_posts.items():
        urls.append((f"{SITE_BASE}/{slug}/", p.get("date_iso"), "monthly", "0.8"))
    # News items
    for slug, _t, date_iso, _b in NEWS_ITEMS:
        urls.append((f"{SITE_BASE}/news/{slug}/", date_iso, "monthly", "0.6"))
    # Categories
    by_cat = set()
    for p in all_posts.values():
        for c in p["categories"]:
            by_cat.add(c)
    for c in by_cat:
        urls.append((f"{SITE_BASE}/category/{c}/", None, "weekly", "0.6"))
    # Author
    urls.append((f"{SITE_BASE}/author/digitalkarachi-com/", None, "weekly", "0.5"))

    body = "\n".join(
        "  <url>\n"
        f"    <loc>{html.escape(loc)}</loc>\n"
        + (f"    <lastmod>{lm}</lastmod>\n" if lm else "")
        + f"    <changefreq>{cf}</changefreq>\n"
        f"    <priority>{pr}</priority>\n"
        "  </url>"
        for (loc, lm, cf, pr) in urls
    )
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + body + "\n</urlset>\n"
    )
    (SITE / "sitemap.xml").write_text(sitemap, encoding="utf-8")

    robots = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /wp-admin/\n"
        "Disallow: /wp-includes/\n"
        f"\nSitemap: {SITE_BASE}/sitemap.xml\n"
    )
    (SITE / "robots.txt").write_text(robots, encoding="utf-8")

    # IndexNow key file: stable 32-char hex token committed into the repo.
    # IndexNow keys are public by design; this file proves ownership of the
    # host when we ping the API. See scripts/indexnow_ping.py.
    INDEXNOW_KEY = "9b8e4f3a2c7d4a1e8f5b6c2d0a9e7f31"
    (SITE / f"{INDEXNOW_KEY}.txt").write_text(INDEXNOW_KEY, encoding="utf-8")

    # Custom-domain marker for GitHub Pages
    (SITE / "CNAME").write_text("digitalkarachi.com\n", encoding="utf-8")

    # RSS feed (newest 20 posts by date)
    posts_sorted = sorted(
        all_posts.values(),
        key=lambda p: p.get("date_iso") or "",
        reverse=True,
    )
    items = []
    for p in posts_sorted[:50]:
        body_html = POST_BODIES.get(p["slug"], {}).get("body", "")
        excerpt = re.sub(r'<[^>]+>', ' ', body_html)[:400].strip()
        pub = p.get("date_iso") or ""
        items.append(
            "    <item>\n"
            f"      <title>{html.escape(p['title'])}</title>\n"
            f"      <link>{SITE_BASE}/{p['slug']}/</link>\n"
            f"      <guid isPermaLink=\"true\">{SITE_BASE}/{p['slug']}/</guid>\n"
            f"      <pubDate>{pub}</pubDate>\n"
            f"      <description>{html.escape(excerpt)}</description>\n"
            "    </item>"
        )
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        "    <title>Digital Karachi</title>\n"
        f"    <link>{SITE_BASE}/</link>\n"
        "    <description>AI, technology and the Karachi tech scene. Where Innovation Thrives.</description>\n"
        "    <language>en-us</language>\n"
        f'    <atom:link href="{SITE_BASE}/feed/" rel="self" type="application/rss+xml"/>\n'
        + "\n".join(items)
        + "\n  </channel>\n</rss>\n"
    )
    (SITE / "feed").mkdir(parents=True, exist_ok=True)
    (SITE / "feed/index.xml").write_text(rss, encoding="utf-8")

    # Per-category RSS feeds (newest 20 posts per category)
    def _render_feed(title_text, description_text, feed_path, feed_url, posts):
        items_x = []
        for p in posts[:20]:
            body_html = POST_BODIES.get(p["slug"], {}).get("body", "")
            excerpt = re.sub(r'<[^>]+>', ' ', body_html)[:400].strip()
            pub = p.get("date_iso") or ""
            items_x.append(
                "    <item>\n"
                f"      <title>{html.escape(p['title'])}</title>\n"
                f"      <link>{SITE_BASE}/{p['slug']}/</link>\n"
                f"      <guid isPermaLink=\"true\">{SITE_BASE}/{p['slug']}/</guid>\n"
                f"      <pubDate>{pub}</pubDate>\n"
                f"      <description>{html.escape(excerpt)}</description>\n"
                "    </item>"
            )
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
            "  <channel>\n"
            f"    <title>{html.escape(title_text)}</title>\n"
            f"    <link>{SITE_BASE}/</link>\n"
            f"    <description>{html.escape(description_text)}</description>\n"
            "    <language>en-us</language>\n"
            f'    <atom:link href="{feed_url}" rel="self" type="application/rss+xml"/>\n'
            + "\n".join(items_x)
            + "\n  </channel>\n</rss>\n"
        )
        out = SITE / feed_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")

    cat_feed_count = 0
    cat_groups = defaultdict(list)
    for p in all_posts.values():
        for c in p.get("categories", []):
            cat_groups[c].append(p)
    for cat_slug, posts in cat_groups.items():
        cat_display = CATEGORIES.get(cat_slug, (cat_slug.title(), None))[0]
        cat_posts = sorted(posts, key=lambda p: p.get("date_iso") or "", reverse=True)
        _render_feed(
            f"{cat_display} – Digital Karachi",
            f"Latest articles in {cat_display} from Digital Karachi.",
            f"category/{cat_slug}/feed/index.xml",
            f"{SITE_BASE}/category/{cat_slug}/feed/",
            cat_posts,
        )
        cat_feed_count += 1
    print(f"Wrote {cat_feed_count} per-category RSS feeds.")

    # Themed 404 page
    not_found_main = (
        '<section class="dk-404">'
        '<div class="num">404</div>'
        '<p>That page is not in the archive — but plenty more reading awaits.</p>'
        '<a class="cta" href="./">Return home</a>'
        '</section>'
    )
    (SITE / "404.html").write_text(
        page_shell("404.html", "Page not found – Digital Karachi",
                   "The page you requested could not be found.",
                   "404.html", not_found_main, body_class="dk-404-page"),
        encoding="utf-8")

    print("Wrote sitemap.xml, robots.txt, feed/index.xml, 404.html.")


# ---------------------------------------------------------------------------
# Phase 5: lazy-load images and ensure every <img> has an alt attribute.
# Skips the first <img> on each page (likely above-the-fold) by marking it
# eager so LCP isn't penalised.
# ---------------------------------------------------------------------------
def finalize_a11y_perf():
    img_pat = re.compile(r'<img\b([^>]*)>', re.IGNORECASE)
    # Pre-compute which uploads have a sibling .webp on disk so we can swap
    # <img src="…jpg|png"> → "…webp" cheaply during the post-process pass.
    webp_swaps = {}
    uploads = SITE / "wp-content" / "uploads"
    if uploads.exists():
        for p in uploads.rglob("*.webp"):
            stem = p.with_suffix("")
            for ext in (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"):
                orig = stem.with_suffix(ext)
                if orig.exists():
                    rel_orig = orig.relative_to(SITE).as_posix()
                    rel_webp = p.relative_to(SITE).as_posix()
                    webp_swaps[rel_orig] = rel_webp

    src_pat = re.compile(r'\bsrc=(["\'])([^"\']+?)\1', re.IGNORECASE)

    def swap_src_to_webp(attrs):
        def repl(m):
            quote, val = m.group(1), m.group(2)
            # Strip query string for lookup, then re-attach.
            base, _, qs = val.partition("?")
            # Normalise: drop any leading "../" segments to reach a path
            # rooted at the site (the keys in webp_swaps are site-relative).
            probe = base.lstrip("./")
            while probe.startswith("../"):
                probe = probe[3:]
            if probe in webp_swaps:
                new_base = webp_swaps[probe]
                # Preserve the original relative prefix the page used so
                # subdirectory pages still resolve the link correctly.
                prefix_len = len(base) - len(probe)
                new_val = base[:prefix_len] + new_base
                if qs:
                    new_val += "?" + qs
                return f'src={quote}{new_val}{quote}'
            return m.group(0)
        return src_pat.sub(repl, attrs)

    for path in SITE.rglob("*.html"):
        try:
            txt = path.read_text(encoding="utf-8")
        except Exception:
            continue

        seen = {"n": 0}

        def patch(m):
            attrs = m.group(1)
            seen["n"] += 1
            # Swap raster src → webp if a sibling exists.
            attrs = swap_src_to_webp(attrs)
            # Ensure alt="" if missing entirely (a11y)
            if not re.search(r'\balt\s*=', attrs, re.IGNORECASE):
                attrs = ' alt=""' + attrs
            # Eager-load the first image (likely LCP), lazy-load the rest
            if not re.search(r'\bloading\s*=', attrs, re.IGNORECASE):
                if seen["n"] == 1:
                    attrs = ' loading="eager" fetchpriority="high"' + attrs
                else:
                    attrs = ' loading="lazy"' + attrs
            if not re.search(r'\bdecoding\s*=', attrs, re.IGNORECASE):
                attrs = ' decoding="async"' + attrs
            return f'<img{attrs}>'

        new = img_pat.sub(patch, txt)
        # Also swap srcset entries and bare src in <source> tags.
        def srcset_swap(m):
            attr, q, val = m.group(1), m.group(2), m.group(3)
            parts = []
            for piece in val.split(","):
                piece = piece.strip()
                if not piece:
                    continue
                bits = piece.split(None, 1)
                url = bits[0]
                desc = (" " + bits[1]) if len(bits) > 1 else ""
                base, _, qs = url.partition("?")
                probe = base.lstrip("./")
                while probe.startswith("../"):
                    probe = probe[3:]
                if probe in webp_swaps:
                    prefix_len = len(base) - len(probe)
                    base = base[:prefix_len] + webp_swaps[probe]
                new_url = base + (("?" + qs) if qs else "")
                parts.append(new_url + desc)
            return f'{attr}={q}{", ".join(parts)}{q}'

        new = re.sub(
            r'\b(srcset)=(["\'])([^"\']+)\2',
            srcset_swap,
            new,
        )
        # Demote duplicate site-title <h1> wordmark to <p> so each page has
        # exactly one <h1> (the page/post title) for screen readers.
        new = re.sub(
            r'<h1(\s+class="site-title")>',
            r'<p\1 role="heading" aria-level="1">',
            new,
        )
        new = new.replace(
            '<p class="site-title" role="heading" aria-level="1"><a href="../index.html" rel="home">Digital Karachi</a></h1>',
            '<p class="site-title" role="heading" aria-level="1"><a href="../index.html" rel="home">Digital Karachi</a></p>',
        )
        # Generic close-tag fixup (the path depth varies)
        new = re.sub(
            r'(<p class="site-title"[^>]*>\s*<a [^>]*>Digital Karachi</a>\s*)</h1>',
            r'\1</p>', new,
        )
        if new != txt:
            path.write_text(new, encoding="utf-8")
    print("Applied lazy-load + alt fallbacks to all <img> tags.")

# ---------------------------------------------------------------------------
# Home page: editorial featured hero + asymmetric grid for the remaining
# posts, with a "More" link to /page/2/ for the second 10.
# ---------------------------------------------------------------------------
def _render_home_main(current_path, posts, page_num=1, total_pages=1):
    """Render the home-grid <main> body for `posts`, with featured hero on page 1."""
    page2_link = rel(current_path, "page/2/index.html")
    if page_num == 1 and posts:
        featured = posts[0]
        rest = posts[1:]
        f_link = rel(current_path, f"{featured['slug']}/index.html")
        f_cat = featured["categories"][0] if featured["categories"] else None
        f_cat_name = CATEGORIES.get(f_cat, (f_cat or "Blog", None))[0] if f_cat else "Blog"
        f_cat_link = rel(current_path, f"category/{f_cat}/index.html") if f_cat else "#"
        f_excerpt = featured["excerpt"] or POST_BODIES.get(featured["slug"], {}).get("excerpt", "")
        # Featured hero is the LCP image: eager-load + responsive srcset.
        f_img_html = responsive_img_attrs(
            current_path, featured["img"],
            "(max-width: 768px) 100vw, 960px",
            featured["title"], eager=True) if featured["img"] else ""
        hero = f'''
<section class="dk-hero" aria-label="Featured article">
  <a href="{f_link}" aria-label="{html.escape(featured["title"])}">
    <figure class="dk-hero-figure">{f_img_html}</figure>
  </a>
  <div class="dk-eyebrow"><a href="{f_cat_link}">{html.escape(f_cat_name)}</a> · Featured</div>
  <h1 class="dk-hero-title"><a href="{f_link}">{html.escape(featured["title"])}</a></h1>
  <p class="dk-hero-excerpt">{html.escape(f_excerpt[:240])}{'…' if len(f_excerpt) > 240 else ''}</p>
  <div class="dk-hero-meta dk-meta"><time datetime="{featured["date_iso"]}">{featured["date"]}</time> · {reading_time(POST_BODIES.get(featured["slug"], {}).get("body", ""))} min read</div>
</section>'''
    else:
        rest = posts
        hero = ""

    # Build asymmetric grid. Pattern: large, regular, regular | wide, wide | regular, regular, regular | …
    grid_cards = []
    for i, p in enumerate(rest):
        if i == 0:
            v = "is-large"
        elif i in (3, 4):
            v = "is-wide"
        else:
            v = ""
        grid_cards.append(render_article_card(current_path, p, variant=v))

    section_title = '<div class="dk-section-title">Latest writing</div>' if page_num == 1 else ""

    # Pagination nav: shown when there is more than one archive page.
    pager_html = ""
    if total_pages > 1:
        parts = []
        if page_num > 1:
            prev_path = "index.html" if page_num == 2 else f"page/{page_num - 1}/index.html"
            parts.append(f'<a class="dk-pager-prev" href="{rel(current_path, prev_path)}">← Newer</a>')
        parts.append(f'<span class="dk-pager-status">Page {page_num} of {total_pages}</span>')
        if page_num < total_pages:
            next_path = f"page/{page_num + 1}/index.html"
            parts.append(f'<a class="dk-pager-next" href="{rel(current_path, next_path)}">Older →</a>')
        pager_html = '<nav class="dk-pager" aria-label="Pagination">' + "".join(parts) + '</nav>'

    return f'''
{hero}
{section_title}
<section class="dk-grid">
{"".join(grid_cards)}
</section>
{pager_html}
'''


def render_home(all_posts):
    posts = list(all_posts.values())
    total_pages = max(1, (len(posts) + POSTS_PER_PAGE - 1) // POSTS_PER_PAGE)
    page1 = posts[:POSTS_PER_PAGE]
    body = _render_home_main("index.html", page1, page_num=1, total_pages=total_pages)
    desc = "AI, technology and the Karachi tech scene. Where Innovation Thrives."
    page = page_shell("index.html", "Digital Karachi — Where Innovation Thrives",
                      desc, "", body, body_class="dk-home")
    # Inject an LCP preload for the featured hero image so the browser can
    # start the fetch in parallel with CSS, ahead of the parser reaching <img>.
    if page1 and page1[0].get("img"):
        featured = page1[0]
        candidate = featured["img"]
        if not candidate.lower().endswith(".webp"):
            webp_path = re.sub(r'\.(jpe?g|png)$', '.webp', candidate, flags=re.I)
            if (SITE / webp_path).exists():
                candidate = webp_path
        variants = _responsive_variants(candidate)
        if variants:
            srcset = ", ".join(f'{v[2]} {v[0]}w' for v in variants)
            preload = (
                f'<link rel="preload" as="image" '
                f'imagesrcset="{srcset}" '
                f'imagesizes="(max-width: 768px) 100vw, 960px" '
                f'fetchpriority="high">\n'
            )
        else:
            preload = (
                f'<link rel="preload" as="image" href="{candidate}" '
                f'fetchpriority="high">\n'
            )
        page = page.replace("</head>", preload + "</head>", 1)
    write("index.html", page)
    print("Wrote home page.")


def render_archive_pages(all_posts, per_page=POSTS_PER_PAGE):
    """Render `page/2/`, `page/3/`, … for every chunk of older posts.

    Page 1 lives at `index.html` and is rendered by `render_home()`.
    """
    posts = list(all_posts.values())
    total_pages = max(1, (len(posts) + per_page - 1) // per_page)
    written = 0
    for page_num in range(2, total_pages + 1):
        start = (page_num - 1) * per_page
        chunk = posts[start : start + per_page]
        if not chunk:
            continue
        target = f"page/{page_num}/index.html"
        body = _render_home_main(target, chunk, page_num=page_num, total_pages=total_pages)
        header = (
            '<header class="dk-page-header">'
            '<div class="dk-eyebrow">Archive</div>'
            f'<h1>More from Digital Karachi · Page {page_num}</h1>'
            '<p>Continuing on from the front page.</p>'
            '</header>'
        )
        body = header + body
        page = page_shell(
            target,
            f"Page {page_num} – Digital Karachi",
            "Older articles from Digital Karachi.",
            f"page/{page_num}/",
            body,
            body_class=f"dk-archive dk-page-{page_num}",
        )
        write(target, page)
        written += 1
    print(f"Wrote {written} archive pages (page/2 … page/{total_pages}).")


# Backwards-compat alias for any older call sites.
def render_page_2(all_posts):
    render_archive_pages(all_posts)


def patch_global_menu():
    """No-op. The new hand-written template ships a fixed nav so there's no
    per-page menu patching needed."""
    pass

if __name__ == "__main__":
    main()
