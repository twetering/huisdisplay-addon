"""400x300 e-paper canvas.

Everything is drawn in 8-bit grayscale and converted at the end:
- to_1bpp(): hard threshold, so text stays crisp (grays must use pattern()).
- to_4bpp(): 16 gray levels for photos/illustrations (slower full refresh).
"""

from __future__ import annotations

import io
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 400, 300
FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
BLACK, WHITE = 0, 255

_FAMILIES = {
    "sans": "IBMPlexSans-VF.ttf",
    "cond": "IBMPlexSansCondensed-SemiBold.ttf",
    "condm": "IBMPlexSansCondensed-Medium.ttf",
    "serif": "InstrumentSerif-Regular.ttf",
    "serifi": "InstrumentSerif-Italic.ttf",
    "mono": "IBMPlexMono-Medium.ttf",
    "emoji": "NotoEmoji.ttf",
    "symbols": "NotoSansSymbols2.ttf",  # chess pieces  # monochrome outlines: emoji that survive 1 bit
}


def is_emoji(ch: str) -> bool:
    o = ord(ch)
    return o >= 0x1F000 or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or 0x2300 <= o <= 0x23FF \
        or o in (0x2122, 0x2139, 0x3030, 0x303D, 0x00A9, 0x00AE)


def _runs(s: str):
    """Split text into (is_emoji, text) runs; drop variation selectors and joiners."""
    out: list[tuple[bool, str]] = []
    for ch in s:
        if ch in "\ufe0f\ufe0e\u200d":
            continue
        e = is_emoji(ch)
        if out and out[-1][0] == e:
            out[-1] = (e, out[-1][1] + ch)
        else:
            out.append((e, ch))
    return out


@lru_cache(maxsize=128)
def font(size: int, family: str = "sans", weight: str = "Medium") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_DIR / _FAMILIES[family]), size)
    if family == "sans":
        # Thin strokes vanish at 1 bit: small text is never lighter than Medium.
        if size <= 16 and weight in ("Regular", "Light"):
            weight = "Medium"
        f.set_variation_by_name(weight)
    elif family == "emoji":
        f.set_variation_by_axes([600])  # between Regular and Bold: solid at 1 bit
    return f


def emoji_font(f: ImageFont.FreeTypeFont) -> ImageFont.FreeTypeFont:
    return font(int(f.size), "emoji")


# 4x4 Bayer matrix for ordered-dither "gray" fills that survive 1bpp.
_BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


@lru_cache(maxsize=17)
def _dither(level: int) -> Image.Image:
    """Full-screen ordered-dither tile for one gray level (built once)."""
    import numpy as np
    tile = np.where(np.array(_BAYER) < level, WHITE, BLACK).astype(np.uint8)
    return Image.fromarray(np.tile(tile, (H // 4, W // 4)), "L")


class Canvas:
    def __init__(self, bg: int = WHITE):
        self.img = Image.new("L", (W, H), bg)
        self.d = ImageDraw.Draw(self.img)
        self.gray = False  # set True when the page wants a 16-gray refresh

    # ---- text
    def text(self, xy, s: str, f, fill=BLACK, anchor="la"):
        if not any(is_emoji(ch) for ch in s):
            self.d.text(xy, s, font=f, fill=fill, anchor=anchor)
            return
        # Mixed text and emoji: draw run by run on a shared baseline.
        x, y = xy
        total = self.width(s, f)
        if anchor[0] == "m":
            x -= total / 2
        elif anchor[0] == "r":
            x -= total
        base = y + f.getmetrics()[0] if anchor[1] == "a" else y
        ef = emoji_font(f)
        for emo, run in _runs(s):
            rf = ef if emo else f
            self.d.text((x, base), run, font=rf, fill=fill, anchor="ls")
            x += self.d.textlength(run, font=rf)

    def width(self, s: str, f) -> int:
        if not any(is_emoji(ch) for ch in s):
            return int(math.ceil(self.d.textlength(s, font=f)))
        ef = emoji_font(f)
        return int(math.ceil(sum(self.d.textlength(r, font=ef if e else f) for e, r in _runs(s))))

    def fit(self, s: str, f, maxw: int) -> str:
        """Cut s to fit maxw pixels with an ellipsis. Binary search: a few measurements, whatever the length."""
        s = s[: max(8, maxw // 2)]  # no glyph is narrower than ~2 px: the rest can never fit
        if self.width(s, f) <= maxw:
            return s
        lo, hi = 0, len(s)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.width(s[:mid] + "…", f) <= maxw:
                lo = mid
            else:
                hi = mid - 1
        return s[:lo].rstrip() + "…"

    def wrap(self, s: str, f, maxw: int, max_lines: int = 99) -> list[str]:
        lines: list[str] = []
        for para in s.split("\n"):
            cur = ""
            for word in para.split():
                trial = f"{cur} {word}".strip()
                if self.width(trial, f) <= maxw:
                    cur = trial
                else:
                    if cur:
                        lines.append(cur)
                    cur = word
            lines.append(cur)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = self.fit(lines[-1] + " …", f, maxw)
        return lines

    def paragraph(self, x, y, s, f, maxw, leading=1.25, max_lines=99, fill=BLACK) -> int:
        """Draw wrapped text, return the y below it."""
        lh = int(f.size * leading)
        for line in self.wrap(s, f, maxw, max_lines):
            self.text((x, y), line, f, fill)
            y += lh
        return y

    # ---- shapes
    def line(self, x0, y0, x1, y1, w=1, fill=BLACK):
        self.d.line((x0, y0, x1, y1), fill=fill, width=w)

    def rect(self, x0, y0, x1, y1, fill=None, outline=BLACK, w=1, r=0):
        if r:
            self.d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=fill, outline=outline, width=w)
        else:
            self.d.rectangle((x0, y0, x1, y1), fill=fill, outline=outline, width=w)

    def pattern(self, x0, y0, x1, y1, level: int, r: int = 0):
        """Fill with an ordered-dither gray (level 0=black .. 16=white).
        One paste of a cached full-screen dither through a shape mask: no per-pixel Python."""
        box = (max(0, x0), max(0, y0), min(W, x1 + 1), min(H, y1 + 1))
        if box[2] <= box[0] or box[3] <= box[1]:
            return
        mask = Image.new("1", (box[2] - box[0], box[3] - box[1]), 0)
        md = ImageDraw.Draw(mask)
        rx0, ry0, rx1, ry1 = x0 - box[0], y0 - box[1], x1 - box[0], y1 - box[1]
        if r:
            md.rounded_rectangle((rx0, ry0, rx1, ry1), radius=r, fill=1)
        else:
            md.rectangle((rx0, ry0, rx1, ry1), fill=1)
        self.img.paste(_dither(level).crop(box), box[:2], mask)

    def dotted_h(self, x0, x1, y, step=4):
        for x in range(x0, x1, step):
            self.d.point((x, y), fill=BLACK)

    def paste(self, im: Image.Image, xy):
        self.img.paste(im, xy)

    # ---- output
    def to_1bpp(self) -> bytes:
        bw = self.img.point(lambda v: 255 if v >= 140 else 0, mode="1")
        return bw.tobytes()  # PIL "1" mode: MSB first, 1 = white (matches panel)

    def to_4bpp(self) -> bytes:
        import numpy as np
        q = np.frombuffer(self.img.point(lambda v: v * 15 // 255).tobytes(), np.uint8)
        return ((q[0::2] << 4) | q[1::2]).astype(np.uint8).tobytes()

    def preview_png(self, scale: int = 2) -> bytes:
        im = self.img if self.gray else self.img.point(lambda v: 255 if v >= 140 else 0)
        im = im.resize((W * scale, H * scale), Image.NEAREST)
        b = io.BytesIO()
        im.save(b, "PNG")
        return b.getvalue()


# ------------------------------------------------------------------ icons
def weather_icon(c: Canvas, cx: int, cy: int, size: int, cond: str, night: bool = False):
    """Line-art weather icons drawn from primitives (crisp at any size)."""
    s = size / 48
    w = max(2, round(2.5 * s))
    d = c.d

    def sun(x, y, r):
        d.ellipse((x - r, y - r, x + r, y + r), outline=BLACK, width=w)
        for i in range(8):
            a = i * math.pi / 4
            d.line((x + math.cos(a) * r * 1.45, y + math.sin(a) * r * 1.45,
                    x + math.cos(a) * r * 1.9, y + math.sin(a) * r * 1.9), fill=BLACK, width=w)

    def moon(x, y, r):
        d.ellipse((x - r, y - r, x + r, y + r), outline=BLACK, width=w)
        d.ellipse((x - r * 0.35, y - r * 1.25, x + r * 1.65, y + r * 0.75), fill=WHITE)
        d.arc((x - r * 0.35, y - r * 1.25, x + r * 1.65, y + r * 0.75), 100, 250, fill=BLACK, width=w)

    def cloud(x, y, sc, fill=WHITE):
        # x,y = center bottom-ish; three bumps + flat base
        r1, r2, r3 = 9 * sc, 13 * sc, 8 * sc
        parts = [(x - 11 * sc, y - 2 * sc, r1), (x + 1 * sc, y - 9 * sc, r2), (x + 13 * sc, y - 1 * sc, r3)]
        for px, py, r in parts:
            d.ellipse((px - r - w, py - r - w, px + r + w, py + r + w), fill=BLACK)
        d.rounded_rectangle((x - 20 * sc - w, y - 4 * sc - w, x + 21 * sc + w, y + 8 * sc + w), radius=8 * sc, fill=BLACK)
        for px, py, r in parts:
            d.ellipse((px - r, py - r, px + r, py + r), fill=fill)
        d.rounded_rectangle((x - 20 * sc, y - 4 * sc, x + 21 * sc, y + 8 * sc), radius=7 * sc, fill=fill)

    cond = (cond or "").lower()
    if cond in ("sunny", "clear", "clear-night", "exceptional"):
        (moon if night or cond == "clear-night" else sun)(cx, cy, 11 * s)
        return
    if cond == "partlycloudy":
        if night:
            moon(cx + 7 * s, cy - 8 * s, 8 * s)
        else:
            sun(cx + 8 * s, cy - 8 * s, 7 * s)
        cloud(cx - 2 * s, cy + 6 * s, s * 0.85)
        return
    if cond == "fog":
        for i in range(4):
            yy = cy - 10 * s + i * 7 * s
            d.line((cx - 18 * s + (i % 2) * 5 * s, yy, cx + 18 * s - ((i + 1) % 2) * 5 * s, yy), fill=BLACK, width=w)
        return
    cloud(cx, cy - 2 * s, s)
    if cond in ("rainy", "pouring", "lightning-rainy"):
        n = 3 if cond == "rainy" else 4
        for i in range(n):
            x0 = cx - 12 * s + i * (24 * s / max(1, n - 1))
            d.line((x0, cy + 12 * s, x0 - 4 * s, cy + 20 * s), fill=BLACK, width=w)
    if cond in ("snowy", "snowy-rainy"):
        for i in range(3):
            x0 = cx - 11 * s + i * 11 * s
            d.ellipse((x0 - 2 * s, cy + 14 * s, x0 + 2 * s, cy + 18 * s), fill=BLACK)
    if cond in ("lightning", "lightning-rainy"):
        d.line((cx + 2 * s, cy + 9 * s, cx - 4 * s, cy + 17 * s, cx + 3 * s, cy + 17 * s, cx - 3 * s, cy + 25 * s), fill=BLACK, width=w)
    if cond == "windy" or cond == "windy-variant":
        d.arc((cx - 6 * s, cy + 8 * s, cx + 14 * s, cy + 20 * s), 270, 90, fill=BLACK, width=w)


def battery_icon(c: Canvas, x: int, y: int, pct: int | None, charging: bool):
    c.rect(x, y, x + 20, y + 10, outline=BLACK, w=1, r=2)
    c.rect(x + 21, y + 3, x + 23, y + 7, fill=BLACK, outline=None)
    if pct is not None and pct >= 0:
        fillw = max(1, round(16 * pct / 100))
        c.rect(x + 2, y + 2, x + 2 + fillw, y + 8, fill=BLACK, outline=None)
    if charging:
        d = c.d
        d.polygon([(x + 11, y + 1), (x + 6, y + 6), (x + 10, y + 6), (x + 9, y + 10), (x + 15, y + 4), (x + 11, y + 4)], fill=WHITE, outline=BLACK)


def bin_icon(c: Canvas, x: int, y: int, h: int = 28):
    """Wheelie bin (container) icon, top-left at x,y."""
    s = h / 28
    d = c.d
    d.rectangle((x + 2 * s, y + 3 * s, x + 20 * s, y + 6 * s), fill=BLACK)
    d.polygon([(x + 4 * s, y + 7 * s), (x + 18 * s, y + 7 * s), (x + 17 * s, y + 24 * s), (x + 5 * s, y + 24 * s)], fill=BLACK)
    for i in range(3):
        xx = x + (7.5 + i * 3.5) * s
        d.line((xx, y + 10 * s, xx, y + 21 * s), fill=WHITE, width=max(1, round(s)))
    d.ellipse((x + 3 * s, y + 23 * s, x + 8 * s, y + 28 * s), fill=BLACK)
    d.ellipse((x + 14 * s, y + 23 * s, x + 19 * s, y + 28 * s), fill=BLACK)
    d.rectangle((x + 8 * s, y, x + 14 * s, y + 3 * s), outline=BLACK, width=max(1, round(1.5 * s)))


def train_icon(c: Canvas, x: int, y: int, h: int = 20):
    s = h / 20
    d = c.d
    d.rounded_rectangle((x, y, x + 16 * s, y + 15 * s), radius=4 * s, fill=BLACK)
    d.rectangle((x + 3 * s, y + 3 * s, x + 13 * s, y + 8 * s), fill=WHITE)
    d.ellipse((x + 3 * s, y + 10 * s, x + 6 * s, y + 13 * s), fill=WHITE)
    d.ellipse((x + 10 * s, y + 10 * s, x + 13 * s, y + 13 * s), fill=WHITE)
    d.line((x + 3 * s, y + 15 * s, x, y + 20 * s), fill=BLACK, width=max(1, round(2 * s)))
    d.line((x + 13 * s, y + 15 * s, x + 16 * s, y + 20 * s), fill=BLACK, width=max(1, round(2 * s)))


def mic_icon(c: Canvas, cx: int, cy: int, h: int = 60):
    s = h / 60
    d = c.d
    w = max(2, round(4 * s))
    d.rounded_rectangle((cx - 10 * s, cy - 28 * s, cx + 10 * s, cy + 6 * s), radius=10 * s, fill=BLACK)
    d.arc((cx - 18 * s, cy - 14 * s, cx + 18 * s, cy + 18 * s), 0, 180, fill=BLACK, width=w)
    d.line((cx, cy + 18 * s, cx, cy + 28 * s), fill=BLACK, width=w)
    d.line((cx - 10 * s, cy + 28 * s, cx + 10 * s, cy + 28 * s), fill=BLACK, width=w)
