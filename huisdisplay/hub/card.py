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
                    "type": {"type": "string", "enum": ["text", "rows", "bullets", "steps", "big", "timeline", "icon_row"]},
                    "text": {"type": "string", "description": "for text"},
                    "rows": {"type": "array", "description": "for rows: label/value pairs (a small table)",
                             "items": {"type": "object", "properties": {"label": {"type": "string"}, "value": {"type": "string"}},
                                       "required": ["label", "value"]}},
                    "items": {"type": "array", "items": {"type": "string"}, "description": "for bullets/steps"},
                    "value": {"type": "string", "description": "for big: a large number/word, e.g. '14°' or '23 min'"},
                    "label": {"type": "string", "description": "for big: caption next to the value"},
                    "events": {"type": "array", "description": "for timeline", "items": {"type": "object", "properties": {
                        "time": {"type": "string"}, "text": {"type": "string"}}, "required": ["time", "text"]}},
                    "icons": {"type": "array", "description": "for icon_row: weather-style items", "items": {"type": "object", "properties": {
                        "label": {"type": "string"}, "condition": {"type": "string", "description": "HA weather condition, e.g. sunny, rainy, cloudy, partlycloudy"},
                        "value": {"type": "string"}}, "required": ["label", "condition", "value"]}},
                },
                "required": ["type"],
            },
        },
        "footer": {"type": "string", "description": "Optional one-line source/tip at the bottom."},
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
        while size > 28 and c.width(word, font(size, "serifi")) > maxw:
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
    return y


def paginate(card: dict) -> list[list[dict]]:
    """Split blocks into screens. The first screen also carries the title."""
    c = Canvas()
    maxw = 356
    screens: list[list[dict]] = [[]]
    y = 40 + (18 if card.get("query") else 0) + _title_height(c, card, maxw)
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
            c.text((x, y), c.fit(f"“{card['query']}”", font(12, "sans", "Regular"), maxw), font(12, "sans", "Regular"))
            y += 18
        if card.get("kicker"):
            c.text((x, y), card["kicker"].upper(), font(10, "sans", "SemiBold"))
            y += 14
        y = _title(c, card, x, y, maxw)
    for b in screens[screen]:
        y = _draw_block(c, b, x, y, maxw, b.get("_offset", 0))
    foot = card.get("footer", "")
    if len(screens) > 1:
        foot = (foot + "  ·  " if foot and screen == len(screens) - 1 else "") + f"{screen + 1}/{len(screens)}" + \
            ("  ·  OK = verder" if screen < len(screens) - 1 else "")
    if foot:
        c.text((x, 270), c.fit(foot, font(11, "sans", "Regular"), maxw), font(11, "sans", "Regular"))
    return c
