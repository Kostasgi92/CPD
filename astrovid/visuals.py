"""Εικόνες: αναζήτηση στη NASA Image and Video Library και σχεδίαση γραφικών (κάρτες, υπότιτλοι)."""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .config import find_font

log = logging.getLogger(__name__)

NASA_SEARCH = "https://images-api.nasa.gov/search"
# Εικόνες που δεν είναι αστρονομικές (συνεντεύξεις τύπου, πορτρέτα κλπ.).
SKIP_WORDS = re.compile(r"briefing|press conference|portrait|meeting|award|ceremony|panel|"
                        r"visit|employee|workshop|town hall|exhibit|logo", re.I)


@dataclass
class Picture:
    path: Path
    credit: str
    title: str = ""
    url: str = ""


# ---------------------------------------------------------------- fonts / text

def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = find_font(bold)
    if path:
        return ImageFont.truetype(path, size)
    log.warning("Δεν βρέθηκε γραμματοσειρά με ελληνικούς χαρακτήρες· ορίστε ASTROVID_FONT.")
    return ImageFont.load_default(size)


def wrap(text: str, fnt: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if fnt.getlength(trial) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _text_block(draw: ImageDraw.ImageDraw, lines: list[str], fnt, center_x: int, top: int,
                fill=(255, 255, 255, 255), stroke: int = 0, spacing: float = 1.25,
                align_left: int | None = None) -> int:
    size = fnt.size
    y = top
    for ln in lines:
        if align_left is not None:
            x = align_left
        else:
            x = center_x - fnt.getlength(ln) / 2
        draw.text((x, y), ln, font=fnt, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0, 230))
        y += int(size * spacing)
    return y


# ---------------------------------------------------------------- NASA images

class NasaImages:
    def __init__(self, cache_dir: Path, session: requests.Session | None = None):
        self.cache = cache_dir
        self.cache.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.used: set[str] = set()

    def find(self, query: str, min_width: int = 1000) -> Picture | None:
        for q in _query_variants(query):
            try:
                r = self.session.get(NASA_SEARCH, params={"q": q, "media_type": "image"}, timeout=25)
                r.raise_for_status()
                items = r.json().get("collection", {}).get("items", [])
            except (requests.RequestException, ValueError) as exc:
                log.warning("NASA image search failed (%s): %s", q, exc)
                return None
            for item in items[:30]:
                data = (item.get("data") or [{}])[0]
                nasa_id = data.get("nasa_id")
                if not nasa_id or nasa_id in self.used:
                    continue
                if SKIP_WORDS.search(f"{data.get('title', '')} {data.get('description', '')[:300]}"):
                    continue
                thumb = next((l.get("href") for l in item.get("links", []) if l.get("render") == "image"), "")
                pic = self._download(nasa_id, thumb, data, min_width)
                if pic:
                    self.used.add(nasa_id)
                    return pic
        return None

    def _download(self, nasa_id: str, thumb: str, data: dict, min_width: int) -> Picture | None:
        safe = re.sub(r"[^\w\-]", "_", nasa_id)
        target = self.cache / f"{safe}.jpg"
        candidates = [thumb.replace("~thumb", s) for s in ("~large", "~orig", "~medium")] if thumb else []
        for url in candidates:
            try:
                if not target.exists():
                    r = self.session.get(url, timeout=60)
                    if r.status_code != 200:
                        continue
                    img = Image.open(BytesIO(r.content))
                    img = ImageOps.exif_transpose(img).convert("RGB")
                    if img.width < min_width:
                        continue
                    img.save(target, quality=93)
                credit = "NASA"
                who = data.get("secondary_creator") or data.get("photographer") or data.get("center")
                if who and who.upper() != "NASA":
                    credit = f"NASA / {who}"
                return Picture(target, credit[:80], data.get("title", ""),
                               f"https://images.nasa.gov/details/{nasa_id}")
            except (requests.RequestException, OSError) as exc:
                log.info("download %s failed: %s", url, exc)
        return None


def _query_variants(query: str) -> list[str]:
    words = query.split()
    variants = [query]
    if len(words) > 2:
        variants.append(" ".join(words[:2]))
    if len(words) > 1:
        variants.append(words[-1] if len(words[-1]) > 4 else words[0])
    return variants


# ---------------------------------------------------------------- image preparation

def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), size, Image.Resampling.LANCZOS, centering=(0.5, 0.45))


def starfield(size: tuple[int, int], seed: int) -> Image.Image:
    """Συνθετικό φόντο (έναστρος ουρανός με νεφέλωμα) όταν δεν βρεθεί κατάλληλη εικόνα."""
    rnd = random.Random(seed)
    w, h = size
    small = (w // 4, h // 4)
    neb = Image.new("RGB", small, (3, 4, 12))
    d = ImageDraw.Draw(neb)
    palette = [(70, 30, 120), (20, 70, 140), (140, 40, 90), (30, 110, 120), (160, 90, 40)]
    for _ in range(9):
        cx, cy = rnd.randint(0, small[0]), rnd.randint(0, small[1])
        r = rnd.randint(small[1] // 6, small[1] // 2)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rnd.choice(palette))
    neb = neb.filter(ImageFilter.GaussianBlur(small[1] // 7))
    neb = Image.blend(Image.new("RGB", small, (2, 3, 10)), neb, 0.55).resize(size, Image.Resampling.BICUBIC)
    d = ImageDraw.Draw(neb)
    for _ in range(int(w * h / 2500)):
        x, y = rnd.randrange(w), rnd.randrange(h)
        b = rnd.randint(110, 255)
        tint = rnd.choice([(b, b, b), (b, b, 255), (255, b, b - 40 if b > 40 else b)])
        rad = rnd.choice([0, 0, 0, 1, 1, 2])
        d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=tint)
    return neb


# ---------------------------------------------------------------- overlays

def scene_overlay(size: tuple[int, int], heading: str, footer: str) -> Image.Image:
    """Μόνιμα γραφικά σκηνής: τίτλος πάνω αριστερά, σκίαση κάτω, πηγές/credits κάτω δεξιά."""
    w, h = size
    s = h / 1080
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    grad = Image.new("L", (1, 256))
    for y in range(256):
        grad.putpixel((0, y), int(200 * (y / 255) ** 1.6))
    band_h = int(h * 0.36)
    band = Image.new("RGBA", (w, band_h), (0, 0, 0, 255))
    band.putalpha(grad.resize((w, band_h)))
    img.alpha_composite(band, (0, h - band_h))
    d = ImageDraw.Draw(img)
    if heading:
        f = font(int(38 * s), bold=True)
        pad = int(22 * s)
        tw = int(f.getlength(heading))
        x0, y0 = int(48 * s), int(44 * s)
        d.rounded_rectangle([x0, y0, x0 + tw + 2 * pad, y0 + f.size + int(1.3 * pad)],
                            radius=int(14 * s), fill=(8, 12, 30, 170))
        d.rectangle([x0, y0, x0 + int(6 * s), y0 + f.size + int(1.3 * pad)], fill=(120, 180, 255, 255))
        d.text((x0 + pad + int(4 * s), y0 + int(0.55 * pad)), heading, font=f, fill=(255, 255, 255, 255))
    if footer:
        f = font(int(20 * s))
        lines = wrap(footer, f, int(w * (0.6 if w >= h else 0.9)))[:3]
        y = h - int(16 * s) - len(lines) * int(f.size * 1.3)
        for ln in lines:
            d.text((w - int(36 * s) - f.getlength(ln), y), ln, font=f, fill=(220, 225, 235, 200))
            y += int(f.size * 1.3)
    return img


def subtitle_overlay(size: tuple[int, int], text: str) -> Image.Image:
    w, h = size
    s = h / 1080 if w >= h else w / 1080
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = font(int(44 * s), bold=True)
    lines = wrap(text, f, int(w * 0.82))[:3]
    bottom = h - int((80 if w >= h else 380) * (h / 1080 if w >= h else w / 1080))
    top = bottom - len(lines) * int(f.size * 1.25)
    _text_block(d, lines, f, w // 2, top, stroke=max(2, int(3 * s)))
    return img


def title_card(bg: Image.Image, title: str, subtitle: str) -> Image.Image:
    w, h = bg.size
    s = min(w, h) / 1080
    img = bg.convert("RGBA")
    img.alpha_composite(Image.new("RGBA", bg.size, (0, 0, 10, 120)))
    d = ImageDraw.Draw(img)
    ft, fs = font(int(86 * s), bold=True), font(int(40 * s))
    tl, sl = wrap(title, ft, int(w * 0.85)), wrap(subtitle, fs, int(w * 0.75))
    total = len(tl) * ft.size * 1.2 + len(sl) * fs.size * 1.3 + 40 * s
    y = int((h - total) / 2)
    y = _text_block(d, tl, ft, w // 2, y, stroke=int(3 * s), spacing=1.2)
    d.line([w // 2 - int(120 * s), y + int(10 * s), w // 2 + int(120 * s), y + int(10 * s)],
           fill=(120, 180, 255, 255), width=max(2, int(4 * s)))
    _text_block(d, sl, fs, w // 2, y + int(34 * s), fill=(215, 225, 245, 255), stroke=int(2 * s), spacing=1.3)
    return img.convert("RGB")


def references_card(size: tuple[int, int], heading: str, refs: list[str], credits_line: str,
                    note: str) -> Image.Image:
    w, h = size
    s = min(w, h) / 1080
    img = starfield(size, seed=7).convert("RGBA")
    img.alpha_composite(Image.new("RGBA", size, (0, 0, 8, 185)))
    d = ImageDraw.Draw(img)
    margin = int(70 * s)
    fh, fr, fn = font(int(52 * s), bold=True), font(int(24 * s)), font(int(21 * s))
    y = _text_block(d, [heading], fh, 0, margin, align_left=margin)
    y += int(14 * s)
    for ref in refs:
        lines = wrap(ref, fr, w - 2 * margin)[:2]
        if y + len(lines) * fr.size * 1.3 > h - int(170 * s):
            break
        y = _text_block(d, lines, fr, 0, y, fill=(225, 230, 245, 255), spacing=1.3, align_left=margin)
        y += int(10 * s)
    y = max(y + int(10 * s), h - int(150 * s))
    for text in (credits_line, note):
        lines = wrap(text, fn, w - 2 * margin)[:2]
        y = _text_block(d, lines, fn, 0, y, fill=(170, 185, 210, 255), spacing=1.3, align_left=margin)
    return img.convert("RGB")
