"""Generative answer cards.

Claude answers with a small layout document (see CARD_SCHEMA); this module
lays it out on the 400x300 panel. Blocks that don't fit flow onto extra
screens, which the OK button steps through (handy for recipes).
"""

from __future__ import annotations

from .render import BLACK, WHITE, Canvas, font, weather_icon

CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short headline answer, max ~8 words. The main takeaway."},
        "accent": {"type": "string", "description": "Optional: one word from the title to set in large italic serif for emphasis."},
        "kicker": {"type": "string", "description": "Optional tiny uppercase label above the title, e.g. 'RECEPT' or 'WIJN'."},
        "blocks": {
            "type": "array",
            "description": "Body blocks, in order. Keep it glanceable: the screen is 400x300 e-ink.",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["text", "rows", "bullets", "steps", "big", "timeline", "icon_row",
                                                        "countdown", "bars", "quote", "progress", "sticker", "emoji_row"]},
                    "text": {"type": "string", "description": "for text"},
                    "rows": {"type": "array", "description": "for rows: label/value pairs (a small table)",
                             "items": {"type": "object", "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
                                       "required": ["label", "value"]}},
                    "items": {"type": "array", "items": {"type": "string"}, "description": "for bullets/steps"},
                    "value": {"type": "string", "description": "for big: a large number/word, e.g. '14°' or '23 min'"},
                    "label": {"type": "string", "description": "for big: caption next to the value"},
                    "events": {"type": "array", "description": "for timeline", "items": {"type": "object", "properties": {
                        "time": {"type": "string"}, "text": {"type": "string"}}, "required": ["time", "text"]}},
                    "number": {"type": "number", "description": "for countdown: how many (days, nights, sleeps); for progress: 0-100"},
                    "unit": {"type": "string", "description": "for countdown: e.g. 'nachtjes slapen', 'dagen'"},
                    "bars": {"type": "array", "description": "for bars: a small horizontal bar chart, longest = largest value",
                             "items": {"type": "object", "properties": {"label": {"type": "string"}, "value": {"type": "number"},
                                                                         "display": {"type": "string", "description": "text after the bar, e.g. '42 km'"}},
                                       "required": ["label", "value"]}},
                    "by": {"type": "string", "description": "for quote: who said it"},
                    "emoji": {"type": "string", "description": "for sticker: one emoji, drawn big"},
                    "emojis": {"type": "array", "description": "for emoji_row: up to 5 big emoji with a label and value",
                               "items": {"type": "object", "properties": {"emoji": {"type": "string"}, "label": {"type": "string"},
                                                                           "value": {"type": "string"}}, "required": ["emoji"]}},
                    "icons": {"type": "array", "description": "for icon_row: weather-style items", "items": {"type": "object", "properties": {
                        "label": {"type": "string"}, "condition": {"type": "string", "description": "HA weather condition, e.g. sunny, rainy, cloudy, partlycloudy"},
                        "value": {"type": "string"}}, "required": ["label", "condition", "value"]}},
                },
                "required": ["type"],
            },
        },
        "footer": {"type": "string", "description": "Optional one-line source/tip at the bottom."},
        "sticker": {"type": "string", "description": "Optional single emoji shown as a round sticker in the top-right corner, for playful cards."},
    },
    "required": ["title", "blocks"],
}


def _title(c: Canvas, card: dict, x: int, y: int, maxw: int) -> int:
    title = card.get("title", "")
    accent = (card.get("accent") or "").strip()
    if accent and accent.lower() in title.lower():
        # Big italic accent word on its own line, rest of the title above/below in sans.
        i = title.lower().index(accent.lower())
        before, word, after = title[:i].strip(), title[i:i + len(accent)], title[i + len(accent):].strip()
        if before:
            y = c.paragraph(x, y, before, font(20, "sans", "SemiBold"), maxw, 1.15, 2)
        size = 56
        while size > 28 and c.d.textbbox((0, 0), word, font=font(size, "serifi"))[2] > maxw - 8:  # bbox: italic overhang
            size -= 4
        c.text((x - 2, y - size * 0.18), word, font(size, "serifi"))
        y += int(size * 0.92)
        if after:
            y = c.paragraph(x, y, after, font(20, "sans", "SemiBold"), maxw, 1.15, 2)
        return y + 6
    for size in (26, 23, 20, 18):
        f = font(size, "sans", "Bold")
        lines = c.wrap(title, f, maxw)
        if len(lines) <= 2:
            break
    return c.paragraph(x, y, title, f, maxw, 1.12, 3) + 6


def _block_height(c: Canvas, b: dict, maxw: int) -> int:
    t = b.get("type")
    if t == "text":
        return len(c.wrap(b.get("text", ""), font(15, "sans", "Regular"), maxw)) * 19 + 6
    if t == "rows":
        return len(b.get("rows", [])) * 22 + 6
    if t in ("bullets", "steps"):
        n = 0
        for it in b.get("items", []):
            n += len(c.wrap(it, font(14, "sans", "Regular"), maxw - 22)) * 18 + 3
        return n + 4
    if t == "big":
        return 54
    if t == "timeline":
        return len(b.get("events", [])) * 21 + 6
    if t == "icon_row":
        return 84
    if t == "countdown":
        return 92
    if t == "bars":
        return len(b.get("bars", [])[:6]) * 22 + 6
    if t == "quote":
        return len(c.wrap(b.get("text", ""), font(22, "serifi"), maxw - 26)) * 25 + (22 if b.get("by") else 0) + 10
    if t == "progress":
        return 44
    if t == "sticker":
        return 76
    if t == "emoji_row":
        return 90
    return 0


def _draw_block(c: Canvas, b: dict, x: int, y: int, maxw: int, step_offset: int = 0) -> int:
    t = b.get("type")
    if t == "text":
        return c.paragraph(x, y, b.get("text", ""), font(15, "sans", "Regular"), maxw, 1.27) + 6
    if t == "rows":
        fl, fv = font(15, "sans", "Regular"), font(15, "sans", "SemiBold")
        for r in b.get("rows", []):
            lab = c.fit(r.get("label", ""), fl, maxw // 2 - 6)
            c.text((x, y), lab, fl)
            c.text((x + maxw, y), c.fit(r.get("value", ""), fv, maxw - c.width(lab, fl) - 14), fv, anchor="ra")
            y += 22
        return y + 6
    if t in ("bullets", "steps"):
        f = font(14, "sans", "Regular")
        for i, it in enumerate(b.get("items", [])):
            if t == "steps":
                c.text((x, y), f"{i + 1 + step_offset}", font(14, "cond"))
            else:
                c.d.ellipse((x + 3, y + 6, x + 8, y + 11), fill=BLACK)
            y = c.paragraph(x + 22, y, it, f, maxw - 22, 1.28) + 3
        return y + 4
    if t == "big":
        f = font(44, "cond")
        val = b.get("value", "")
        c.text((x, y - 4), val, f)
        vw = c.width(val, f)
        c.paragraph(x + vw + 12, y + 12, b.get("label", ""), font(14, "sans", "Medium"), maxw - vw - 12, 1.2, 2)
        return y + 54
    if t == "timeline":
        for e in b.get("events", []):
            c.text((x, y), e.get("time", ""), font(15, "cond"))
            c.text((x + 62, y), c.fit(e.get("text", ""), font(15, "sans", "Medium"), maxw - 62), font(15, "sans", "Medium"))
            y += 21
        return y + 6
    if t == "icon_row":
        items = b.get("icons", [])[:5]
        if items:
            cw = maxw // len(items)
            for i, it in enumerate(items):
                cx = x + i * cw + cw // 2
                c.text((cx, y), it.get("label", ""), font(12, "sans", "Medium"), anchor="ma")
                weather_icon(c, cx, y + 36, 32, it.get("condition", ""))
                c.text((cx, y + 58), it.get("value", ""), font(16, "cond"), anchor="ma")
        return y + 84
    if t == "countdown":
        n = b.get("number", b.get("value", 0))
        try:
            n = int(float(n))
        except (TypeError, ValueError):
            n = 0
        num = str(n)
        f = font(72, "serif")
        c.text((x - 2, y - 14), num, f)
        nx = x + c.width(num, f) + 12
        c.text((nx, y + 8), b.get("unit", "dagen"), font(24, "serifi"))
        c.paragraph(nx, y + 38, b.get("label", ""), font(14, "sans", "Medium"), maxw - (nx - x), 1.2, 2)
        # one dot per night left (max 31): full = still to go
        dots = min(n, 31)
        for i in range(dots):
            cx = x + 6 + i * 11
            c.d.ellipse((cx - 4, y + 76, cx + 4, y + 84), fill=BLACK)
        return y + 92
    if t == "bars":
        items = b.get("bars", [])[:6]
        vals = [abs(float(it.get("value", 0) or 0)) for it in items] or [1]
        mx = max(vals) or 1
        fl = font(13, "sans", "Medium")
        lw = min(110, max((c.width(it.get("label", ""), fl) for it in items), default=40) + 10)
        dw = max((c.width(it.get("display", ""), fl) for it in items), default=0) + 8
        bw = maxw - lw - dw
        for it, v in zip(items, vals):
            c.text((x, y + 1), c.fit(it.get("label", ""), fl, lw - 8), fl)
            ln = max(2, int(bw * v / mx))
            c.rect(x + lw, y + 3, x + lw + ln, y + 15, fill=BLACK, outline=None, r=2)
            if it.get("display"):
                c.text((x + lw + ln + 6, y + 1), it["display"], font(13, "sans", "SemiBold"))
            y += 22
        return y + 6
    if t == "quote":
        c.text((x - 4, y - 12), "“", font(64, "serif"))
        y = c.paragraph(x + 26, y, b.get("text", ""), font(22, "serifi"), maxw - 26, 1.14)
        if b.get("by"):
            c.text((x + maxw, y + 2), "— " + b["by"], font(13, "sans", "Medium"), anchor="ra")
            y += 22
        return y + 10
    if t == "progress":
        try:
            pct = max(0.0, min(100.0, float(b.get("number", b.get("value", 0)) or 0)))
        except (TypeError, ValueError):
            pct = 0.0
        c.text((x, y), b.get("label", ""), font(13, "sans", "Medium"))
        c.text((x + maxw, y), f"{pct:.0f}%", font(14, "cond"), anchor="ra")
        c.pattern(x, y + 20, x + maxw, y + 34, 3, r=7)
        c.rect(x, y + 20, x + maxw, y + 34, outline=BLACK, r=7)
        if pct > 0:
            c.rect(x, y + 20, x + max(14, int(maxw * pct / 100)), y + 34, fill=BLACK, outline=None, r=7)
        return y + 44
    if t == "sticker":
        c.text((x + 30, y + 2), b.get("emoji", "⭐"), font(60, "sans"), anchor="ma")
        c.paragraph(x + 76, y + 12, b.get("text", ""), font(16, "sans", "SemiBold"), maxw - 76, 1.2, 3)
        return y + 76
    if t == "emoji_row":
        items = b.get("emojis", [])[:5]
        if items:
            cw = maxw // len(items)
            for i, it in enumerate(items):
                cx = x + i * cw + cw // 2
                c.text((cx, y), it.get("emoji", ""), font(36, "sans"), anchor="ma")
                if it.get("label"):
                    c.text((cx, y + 50), c.fit(it["label"], font(12, "sans", "Medium"), cw - 4), font(12, "sans", "Medium"), anchor="ma")
                if it.get("value"):
                    c.text((cx, y + 66), c.fit(it["value"], font(15, "cond"), cw - 4), font(15, "cond"), anchor="ma")
        return y + 90
    return y


def _sticker(c: Canvas, emoji: str, cx: int = 352, cy: int = 76, r: int = 27):
    """Round sticker in the corner: white disc, double ring, emoji inside."""
    c.d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=WHITE, outline=BLACK, width=2)
    c.d.ellipse((cx - r + 4, cy - r + 4, cx + r - 4, cy + r - 4), outline=BLACK, width=1)
    c.text((cx, cy - 16), emoji, font(28, "sans"), anchor="ma")


def paginate(card: dict) -> list[list[dict]]:
    """Split blocks into screens. The first screen also carries the title."""
    c = Canvas()
    maxw = 356
    screens: list[list[dict]] = [[]]
    y = 40 + (18 if card.get("query") else 0) + (14 if card.get("kicker") else 0) + _title_height(c, card, _title_w(card, maxw))
    limit = 272 - (14 if card.get("footer") else 0)  # keep the footer line clear
    for b in card.get("blocks", []):
        h = _block_height(c, b, maxw)
        if y + h > limit and screens[-1]:
            # Long lists split item by item instead of jumping whole.
            if b.get("type") in ("steps", "bullets") and len(b.get("items", [])) > 1:
                items = b["items"]
                fit = []
                for it in items:
                    ih = len(c.wrap(it, font(14, "sans", "Regular"), maxw - 22)) * 18 + 3
                    if y + ih > limit:
                        break
                    fit.append(it)
                    y += ih
                if fit:
                    screens[-1].append({**b, "items": fit})
                rest = items[len(fit):]
                screens.append([{**b, "items": rest, "_offset": len(fit) + b.get("_offset", 0)}])
                y = 46 + _block_height(c, screens[-1][0], maxw)
                continue
            screens.append([])
            y = 46
        screens[-1].append(b)
        y += h
    return screens


def _title_w(card: dict, maxw: int) -> int:
    return maxw - 64 if card.get("sticker") else maxw


def _title_height(c: Canvas, card: dict, maxw: int) -> int:
    tmp = Canvas()
    return _title(tmp, card, 0, 0, maxw)


def render_card(card: dict, screen: int = 0, header_fn=None) -> Canvas:
    c = Canvas()
    if header_fn:
        header_fn(c)
    screens = paginate(card)
    screen = max(0, min(screen, len(screens) - 1))
    x, maxw = 22, 356
    c.rect(10, 38, 390, 288, outline=BLACK, w=1, r=10)
    y = 46
    if screen == 0:
        if card.get("query"):
            c.text((x, y), c.fit(f"“{card['query']}”", font(12, "sans", "Regular"), _title_w(card, maxw)), font(12, "sans", "Regular"))
            y += 18
        if card.get("kicker"):
            c.text((x, y), card["kicker"].upper(), font(10, "sans", "SemiBold"))
            y += 14
        if card.get("sticker"):
            _sticker(c, card["sticker"])
        y = _title(c, card, x, y, _title_w(card, maxw))
    for b in screens[screen]:
        y = _draw_block(c, b, x, y, maxw, b.get("_offset", 0))
    foot = card.get("footer", "")
    if len(screens) > 1:
        foot = (foot + "  ·  " if foot and screen == len(screens) - 1 else "") + f"{screen + 1}/{len(screens)}" + \
            ("  ·  OK = verder" if screen < len(screens) - 1 else "")
    if foot:
        c.text((x, 270), c.fit(foot, font(11, "sans", "Regular"), maxw), font(11, "sans", "Regular"))
    return c
