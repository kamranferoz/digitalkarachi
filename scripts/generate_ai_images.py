#!/usr/bin/env python3
"""Generate topic-relevant hero images for every post + news item.

Primary source is the Hugging Face Inference Providers API
(black-forest-labs/FLUX.1-Krea-dev by default) — real AI-generated
imagery whose subject matter is derived from the post title + category.
Requires ``HF_TOKEN`` env var with the "Make calls to Inference
Providers" permission.

Falls back to a deterministic Pillow gradient card on hard failure so
the build never breaks.

Output:
  site/wp-content/uploads/ai/posts/<slug>.jpg
  site/wp-content/uploads/ai/news/<slug>.jpg

Usage:
  python3 scripts/generate_ai_images.py            # generate missing only
  python3 scripts/generate_ai_images.py --force    # regenerate all
  python3 scripts/generate_ai_images.py --slug X   # one only
  python3 scripts/generate_ai_images.py --only news|posts
  python3 scripts/generate_ai_images.py --no-hf    # skip HF, gradient only
"""
from __future__ import annotations
import argparse
import hashlib
import os
import sys
import time
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
CONTENT = ROOT / "content"
sys.path.insert(0, str(ROOT))

from generators.schema import load_posts, load_news  # noqa: E402

WIDTH, HEIGHT = 1200, 630
# FLUX likes multiples of 16. 1216x640 ≈ 1.9:1, very close to 1200x630.
GEN_WIDTH, GEN_HEIGHT = 1216, 640
HF_MODEL = os.environ.get("HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-Krea-dev")
HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_MAX_RETRIES = 3
HF_SLEEP_BETWEEN = 1.0  # seconds between requests to be polite
MIN_JPEG_BYTES = 25 * 1024  # < 25 KB ⇒ treated as degenerate

# ---- Category palettes & glyphs ---------------------------------------------
# Each entry: (label, glyph, [colour stops as (r,g,b)])
CATEGORY_THEMES: dict[str, tuple[str, str, list[tuple[int, int, int]]]] = {
    "artificial-intelligence-ai": ("AI",          "AI",   [(76, 29, 149),  (124, 58, 237),  (59, 130, 246)]),
    "machine-learning-ml":        ("Machine Learning", "ML",  [(15, 23, 42),   (37, 99, 235),   (14, 165, 233)]),
    "data-science":               ("Data Science", "DATA", [(6, 78, 59),    (5, 150, 105),   (16, 185, 129)]),
    "blockchain":                 ("Blockchain",  "BLOCK",[(120, 53, 15),  (217, 119, 6),   (245, 158, 11)]),
    "cloud-computing":            ("Cloud",       "CLOUD",[(14, 116, 144), (8, 145, 178),   (56, 189, 248)]),
    "quantum-computing":          ("Quantum",     "Q",    [(49, 46, 129),  (109, 40, 217),  (192, 132, 252)]),
    "security":                   ("Security",    "SEC",  [(127, 29, 29),  (220, 38, 38),   (251, 113, 133)]),
    "drone":                      ("Drone",       "DRONE",[(30, 58, 138),  (37, 99, 235),   (147, 197, 253)]),
    "robotics":                   ("Robotics",    "BOT",  [(31, 41, 55),   (75, 85, 99),    (148, 163, 184)]),
    "internet-of-things-iot":     ("IoT",         "IoT",  [(15, 76, 117),  (45, 156, 219),  (187, 222, 251)]),
    "virtual-reality-vr":         ("VR / AR",     "VR",   [(67, 20, 99),   (139, 92, 246),  (236, 72, 153)]),
    "management":                 ("Management",  "MGMT", [(17, 24, 39),   (55, 65, 81),    (156, 163, 175)]),
    "technology":                 ("Technology",  "TECH", [(15, 23, 42),   (30, 64, 175),   (56, 189, 248)]),
    "blog":                       ("Blog",        "BLOG", [(15, 23, 42),   (51, 65, 85),    (100, 116, 139)]),
}

# News topic → category mapping (mirrors news_image_url rules in build.py)
NEWS_TOPIC_RULES: list[tuple[tuple[str, ...], str]] = [
    (("ai", "gpt", "llm", "openai", "anthropic", "chatgpt", "gemini", "model"), "artificial-intelligence-ai"),
    (("quantum",), "quantum-computing"),
    (("blockchain", "crypto", "bitcoin", "ethereum", "nft"), "blockchain"),
    (("drone", "uav"), "drone"),
    (("robot",), "robotics"),
    (("security", "cyber", "hack", "breach", "ransomware", "malware"), "security"),
    (("iot", "sensor"), "internet-of-things-iot"),
    (("vr", "ar", "metaverse", "headset"), "virtual-reality-vr"),
    (("cloud", "aws", "azure", "kubernetes", "server"), "cloud-computing"),
    (("data", "analytics", "warehouse"), "data-science"),
    (("startup", "funding", "raise", "investment"), "management"),
]

DEFAULT_THEME_KEY = "technology"

# Theme-specific prompt fragments. Combined with the post title to produce
# topical, on-brand imagery.
THEME_PROMPT: dict[str, str] = {
    "artificial-intelligence-ai":  "artificial intelligence concept, glowing neural network, data flowing through circuits, holographic AI interface, futuristic, deep blue and purple tones",
    "machine-learning-ml":         "machine learning concept, data points flowing into a model, gradient lines, vector field, futuristic data visualization, cyan and blue tones",
    "data-science":                "data analytics dashboard, glowing charts and graphs, scatter plots, futuristic UI, teal and green tones",
    "blockchain":                  "blockchain network, glowing hexagonal chains, distributed nodes, golden cryptocurrency tokens, dark backdrop",
    "cloud-computing":             "modern data center, illuminated server racks, glowing fiber optic cables, cloud computing infrastructure, cyan tones",
    "quantum-computing":           "futuristic quantum computer in a research lab, glowing qubits, particle systems, blue energy, cinematic photo",
    "security":                    "cybersecurity concept, glowing padlock and shield, digital fortress, abstract code streams, dark red and crimson tones",
    "drone":                       "modern quadcopter drone in flight over a city skyline, sunset sky, aerial photography, sharp focus",
    "robotics":                    "humanoid robot in a high-tech laboratory, mechanical detail, articulated arm, cinematic lighting, photoreal",
    "internet-of-things-iot":      "internet of things, connected smart sensors and devices, glowing network links, modern home, blue tones",
    "virtual-reality-vr":          "person wearing a VR headset, immersive virtual environment, neon lights, holographic UI, vibrant",
    "management":                  "diverse business team collaborating in a bright modern office, leadership meeting, professional photography",
    "technology":                  "abstract technology concept, glowing circuit board, futuristic interface, blue and cyan tones, cinematic",
    "blog":                        "abstract editorial illustration, modern minimalist design, soft cinematic lighting, depth of field",
}

STYLE_SUFFIX = (
    "editorial hero image for a tech magazine, photoreal, sharp focus, "
    "depth of field, 16:9 composition, no text, no watermark, no logos, "
    "no captions, no signature"
)
NEGATIVE_PROMPT = (
    "text, words, letters, captions, watermark, logo, signature, frame, "
    "border, ugly, blurry, low quality, distorted, deformed"
)


def theme_for_post(categories: list[str]) -> str:
    cats = [c for c in (categories or []) if c != "blog"] + \
           [c for c in (categories or []) if c == "blog"]
    for c in cats:
        if c in CATEGORY_THEMES:
            return c
    return DEFAULT_THEME_KEY


def theme_for_news(title: str) -> str:
    tl = (title or "").lower()
    for needles, key in NEWS_TOPIC_RULES:
        if any(n in tl for n in needles):
            return key
    return DEFAULT_THEME_KEY


# ---- Rendering --------------------------------------------------------------
def _seed(slug: str) -> int:
    return int(hashlib.md5(slug.encode("utf-8")).hexdigest()[:12], 16)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return (int(a[0] + (b[0] - a[0]) * t),
            int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def _gradient_bg(stops: list[tuple[int, int, int]], angle_deg: float) -> Image.Image:
    """Linear gradient via row interpolation, then rotated for angle variety.

    Pure-pixel loops are too slow in Python; we build a 1-pixel-wide
    gradient strip and resize to canvas, then rotate.
    """
    # Build a tall 1-px gradient
    strip_h = 1024
    strip = Image.new("RGB", (1, strip_h))
    px = strip.load()
    segs = len(stops) - 1
    for y in range(strip_h):
        t = y / (strip_h - 1) * segs
        i = int(t)
        f = t - i
        if i >= segs:
            px[0, y] = stops[-1]
        else:
            px[0, y] = _lerp(stops[i], stops[i + 1], f)
    # Stretch to oversized canvas so rotation crop doesn't expose edges
    big = max(WIDTH, HEIGHT) * 2
    stretched = strip.resize((big, big), Image.Resampling.BILINEAR)
    rotated = stretched.rotate(angle_deg, resample=Image.Resampling.BILINEAR, expand=False)
    # Centre-crop to target
    left = (big - WIDTH) // 2
    top = (big - HEIGHT) // 2
    return rotated.crop((left, top, left + WIDTH, top + HEIGHT))


def _add_blobs(img: Image.Image, slug_hash: int, accent: tuple[int, int, int]) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    rng = slug_hash
    for _ in range(3):
        rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
        cx = rng % WIDTH
        rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
        cy = rng % HEIGHT
        rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
        r = 180 + (rng % 220)
        rng = (rng * 1103515245 + 12345) & 0x7FFFFFFF
        alpha = 40 + (rng % 60)
        od.ellipse((cx - r, cy - r, cx + r, cy + r),
                   fill=(accent[0], accent[1], accent[2], alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(80))
    img.paste(overlay, (0, 0), overlay)


def _grid_overlay(img: Image.Image) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    step = 60
    for off in range(-HEIGHT, WIDTH, step):
        od.line([(off, 0), (off + HEIGHT, HEIGHT)], fill=(255, 255, 255, 14), width=1)
    img.paste(overlay, (0, 0), overlay)


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_w: int) -> list[str]:
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    words = text.split()
    lines: list[str] = []
    cur: list[str] = []
    for w in words:
        trial = " ".join(cur + [w])
        bb = d.textbbox((0, 0), trial, font=font)
        if bb[2] - bb[0] <= max_w or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


def _render_gradient_fallback(slug: str, title: str, theme_key: str) -> Image.Image:
    """Last-resort renderer used only when the HF API fails."""
    label, glyph, stops = CATEGORY_THEMES[theme_key]
    h = _seed(slug)
    angle = (h % 120) - 30  # -30°…+90°
    img = _gradient_bg(stops, angle).convert("RGBA")
    accent = stops[-1]
    _add_blobs(img, h, accent)
    _grid_overlay(img)

    # Big translucent glyph badge right side
    glyph_font = _load_font(280, bold=True)
    glyph_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glyph_layer)
    bb = gd.textbbox((0, 0), glyph, font=glyph_font)
    gw, gh = bb[2] - bb[0], bb[3] - bb[1]
    gx = WIDTH - gw - 80 - bb[0]
    gy = (HEIGHT - gh) / 2 - bb[1]
    gd.text((gx, gy), glyph, font=glyph_font, fill=(255, 255, 255, 40))
    img.paste(glyph_layer, (0, 0), glyph_layer)

    d = ImageDraw.Draw(img)

    # Brand mark
    brand_font = _load_font(26, bold=True)
    d.text((70, 60), "DIGITAL KARACHI", font=brand_font, fill=(255, 255, 255, 235))

    # Category pill — drawn on its own RGBA layer with a darker tinted box
    # so the white tag label is always readable.
    tag_font = _load_font(22, bold=True)
    tag = label.upper()
    tbb = d.textbbox((0, 0), tag, font=tag_font)
    tw, th = tbb[2] - tbb[0], tbb[3] - tbb[1]
    pad_x, pad_y = 18, 10
    box_w, box_h = tw + pad_x * 2, th + pad_y * 2
    pill = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pill)
    pd.rounded_rectangle((0, 0, box_w - 1, box_h - 1),
                         radius=8, fill=(0, 0, 0, 110),
                         outline=(255, 255, 255, 160), width=1)
    pd.text((pad_x - tbb[0], pad_y - tbb[1]), tag, font=tag_font,
            fill=(255, 255, 255, 255))
    img.paste(pill, (70, 110), pill)

    # Title — wrapped, bottom-left
    if title:
        title_font = _load_font(54, bold=True)
        max_w = int(WIDTH * 0.66)
        lines = _wrap_text(title, title_font, max_w)
        if len(lines) > 4:
            lines = lines[:4]
            lines[-1] = lines[-1].rstrip() + "…"
        line_h = 64
        total_h = line_h * len(lines)
        y0 = HEIGHT - 80 - total_h
        for i, line in enumerate(lines):
            d.text((70, y0 + i * line_h), line, font=title_font,
                   fill=(255, 255, 255, 248))

    return img.convert("RGB")


# ---- HF Inference (primary source) ------------------------------------------
_hf_client = None


def _hf() -> "object | None":
    """Lazily build a singleton InferenceClient. Returns None if no token."""
    global _hf_client
    if _hf_client is not None or not HF_TOKEN:
        return _hf_client
    try:
        from huggingface_hub import InferenceClient  # type: ignore
    except ImportError:
        print("WARN: huggingface_hub not installed; falling back to gradient cards.")
        return None
    _hf_client = InferenceClient(api_key=HF_TOKEN, timeout=180)
    return _hf_client


def build_prompt(title: str, theme_key: str) -> str:
    theme = THEME_PROMPT.get(theme_key, THEME_PROMPT[DEFAULT_THEME_KEY])
    # Strip noisy punctuation from titles so they read better as prompts.
    clean = " ".join(title.split())
    return f"{clean}. {theme}. {STYLE_SUFFIX}."


def fetch_hf(prompt: str, seed: int) -> Image.Image | None:
    """Generate via HF; returns PIL.Image or None on persistent failure."""
    client = _hf()
    if client is None:
        return None
    last_err: Exception | None = None
    for attempt in range(1, HF_MAX_RETRIES + 1):
        try:
            img = client.text_to_image(  # type: ignore[attr-defined]
                prompt,
                model=HF_MODEL,
                width=GEN_WIDTH,
                height=GEN_HEIGHT,
                negative_prompt=NEGATIVE_PROMPT,
                seed=seed,
            )
            return img
        except Exception as e:  # noqa: BLE001 — broad on purpose, retry then fall back
            last_err = e
            wait = min(30, 2 ** attempt)
            print(f"  HF attempt {attempt}/{HF_MAX_RETRIES} failed ({type(e).__name__}: {e}); waiting {wait}s")
            time.sleep(wait)
    print(f"  HF gave up after {HF_MAX_RETRIES} attempts: {last_err}")
    return None


def _resize_to_target(img: Image.Image) -> Image.Image:
    """Convert generated image to the canonical 1200x630 JPEG canvas."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    src_w, src_h = img.size
    target_ratio = WIDTH / HEIGHT
    src_ratio = src_w / src_h
    if abs(src_ratio - target_ratio) < 0.01:
        return img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    # Centre-crop to target aspect, then resize.
    if src_ratio > target_ratio:
        # too wide → crop sides
        new_w = int(src_h * target_ratio)
        x0 = (src_w - new_w) // 2
        img = img.crop((x0, 0, x0 + new_w, src_h))
    else:
        # too tall → crop top/bottom
        new_h = int(src_w / target_ratio)
        y0 = (src_h - new_h) // 2
        img = img.crop((0, y0, src_w, y0 + new_h))
    return img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def _is_degenerate_image(img: Image.Image) -> bool:
    """Heuristic gate for mostly-blank outputs (common on unstable long runs)."""
    probe = img.convert("RGB").resize((96, 96), Image.Resampling.BILINEAR)
    std = ImageStat.Stat(probe).stddev
    # Very low channel variance usually means a near-solid image.
    return (sum(std) / 3.0) < 8.0


# ---- Orchestration ----------------------------------------------------------
def make_targets(only: str | None) -> list[tuple[str, str, str, str]]:
    out: list[tuple[str, str, str, str]] = []
    if only in (None, "posts"):
        for p in load_posts(CONTENT):
            out.append(("posts", p.slug, p.title, theme_for_post(p.categories)))
    if only in (None, "news"):
        for n in load_news(CONTENT):
            out.append(("news", n.slug, n.title, theme_for_news(n.title)))
    return out


def dest_path(kind: str, slug: str) -> Path:
    return SITE / "wp-content" / "uploads" / "ai" / kind / f"{slug}.jpg"


def run(only: str | None, slug_filter: str | None, force: bool,
    no_hf: bool, use_local: bool) -> int:
    if use_local:
        print("Using local Stable Diffusion (scripts/local_sd.py).")
    elif not HF_TOKEN and not no_hf:
        print("WARN: HF_TOKEN not set — will use gradient fallback for every image.")
    # Import lazily so HF-only / fallback-only runs don't import torch.
    local_gen = None
    local_reset = None
    if use_local:
        from local_sd import generate as local_gen  # type: ignore
        from local_sd import reset_pipeline as local_reset  # type: ignore
    targets = make_targets(only)
    if slug_filter:
        targets = [t for t in targets if t[1] == slug_filter]
    total = len(targets)
    skipped = ai_done = fb_done = failed = 0
    src_label = "local-sd" if use_local else (HF_MODEL if not no_hf else "gradient-only")
    print(f"Total candidates: {total} (source={src_label})")
    for i, (kind, slug, title, theme_key) in enumerate(targets, 1):
        dest = dest_path(kind, slug)
        if dest.exists() and not force:
            skipped += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        seed = _seed(slug) & 0xFFFFFFFF
        img: Image.Image | None = None
        source = "fallback"
        prompt = build_prompt(title, theme_key)
        if use_local and local_gen is not None:
            t0 = time.time()
            try:
                img = local_gen(prompt, seed, width=1024, height=576,
                                negative_prompt=NEGATIVE_PROMPT)
                img = _resize_to_target(img)
                if _is_degenerate_image(img):
                    print(f"  local SD degenerate output for {slug}; resetting and retrying once")
                    if local_reset is not None:
                        local_reset("degenerate image")
                    img = local_gen(prompt, (seed + 1) & 0xFFFFFFFF, width=1024, height=576,
                                    negative_prompt=NEGATIVE_PROMPT)
                    img = _resize_to_target(img)
                    if _is_degenerate_image(img):
                        print(f"  local SD still degenerate for {slug}; falling back")
                        img = None
                source = f"local ({time.time() - t0:.1f}s)"
            except Exception as e:
                print(f"  local SD failed for {slug}: {e}")
                img = None
        elif not no_hf:
            t0 = time.time()
            img = fetch_hf(prompt, seed)
            if img is not None:
                img = _resize_to_target(img)
                source = f"hf ({time.time() - t0:.1f}s)"
        if img is None:
            img = _render_gradient_fallback(slug, title, theme_key)
        try:
            img.save(dest, "JPEG", quality=86, optimize=True, progressive=True)
            kb = dest.stat().st_size // 1024
            ai_used = source.startswith("hf") or source.startswith("local")
            # Quality gate: if AI output is suspiciously tiny, retry with fallback
            if ai_used and dest.stat().st_size < MIN_JPEG_BYTES:
                print(f"[{i}/{total}] WARN {kind}/{slug} AI output only {kb} KB — using gradient.")
                _render_gradient_fallback(slug, title, theme_key).save(
                    dest, "JPEG", quality=86, optimize=True, progressive=True
                )
                source = "fallback (tiny)"
                kb = dest.stat().st_size // 1024
                fb_done += 1
            elif ai_used:
                ai_done += 1
            else:
                fb_done += 1
            print(f"[{i}/{total}] {source:>20s}  {kind}/{slug} → {kb} KB  ({theme_key})", flush=True)
        except Exception as e:
            failed += 1
            print(f"[{i}/{total}] FAIL save {kind}/{slug}: {e}")
            continue
        if not use_local and not no_hf and source.startswith("hf"):
            time.sleep(HF_SLEEP_BETWEEN)
    print(f"Done: ai={ai_done} fallback={fb_done} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["posts", "news"], default=None)
    ap.add_argument("--slug", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-hf", action="store_true",
                    help="Skip HF and use the gradient fallback only.")
    ap.add_argument("--local", action="store_true",
                    help="Use local Stable Diffusion (scripts/local_sd.py) instead of HF.")
    # accepted for back-compat with daily-content.yml; unused
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    return run(args.only, args.slug, args.force, args.no_hf, args.local)


if __name__ == "__main__":
    raise SystemExit(main())
