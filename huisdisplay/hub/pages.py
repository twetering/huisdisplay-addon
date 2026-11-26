"""Page renderers. Each takes a Ctx and returns (Canvas, seconds_until_refresh)."""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass, field

from . import dinner, fun, modes, strava
from . import sources as src
from .render import (BLACK, WHITE, Canvas, battery_icon, bin_icon, font, mic_icon,
                     train_icon, weather_icon)

DAYS = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
MONTHS = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
          "september", "oktober", "november", "december"]
COND_NL = {
    "sunny": "zonnig", "clear-night": "helder", "partlycloudy": "half bewolkt", "cloudy": "bewolkt",
    "rainy": "regen", "pouring": "stortbuien", "fog": "mist", "snowy": "sneeuw", "snowy-rainy": "natte sneeuw",
    "lightning": "onweer", "lightning-rainy": "onweersbuien", "windy": "winderig", "windy-variant": "winderig",
    "hail": "hagel", "exceptional": "uitzonderlijk",
}

ROTATION = ["home", "weer", "trein", "agenda", "huis", "afval"]  # every rotating page (order varies, see rotation())
TITLES = {"schaak": "Schaak", "nieuws": "Nieuws", "kunst": "Kunst", "pokemon": "Pokémon", "sport": "Sport", "home": "Nu", "weer": "Weer", "trein": "Trein", "agenda": "Agenda", "huis": "Huis",
          "afval": "Afval", "answer": "Antwoord", "recept": "Recept"}


@dataclass
class Ctx:
    battery: int | None = None
    usb: bool = True
    page: str = "home"
    answer: dict | None = None  # generative card from the assistant
    extra: dict = field(default_factory=dict)

    @property
    def interval(self) -> int:
        """Default refresh interval: every minute on USB, 15 min on battery."""
        return 60 if self.usb else 900


def day_label(d: dt.date) -> str:
    today = src.now().date()
    if d == today:
        return "vandaag"
    if d == today + dt.timedelta(days=1):
        return "morgen"
    if d == today + dt.timedelta(days=2):
        return "overmorgen"
    if (d - today).days < 7:
        return DAYS[d.weekday()]
    return f"{DAYS[d.weekday()][:2]} {d.day} {MONTHS[d.month - 1][:3]}"


def header(c: Canvas, ctx: Ctx, title: str):
    n = src.now()
    c.text((14, 7), title, font(15, "sans", "SemiBold"))
    tw = c.width(title, font(15, "sans", "SemiBold"))
    date = f"{DAYS[n.weekday()]} {n.day} {MONTHS[n.month - 1]}"
    if (mark := fun.season_mark(n)):
        date += f" {mark}"
    c.text((14 + tw + 10, 8), date, font(14, "sans", "Regular"))
    right = 386
    battery_icon(c, right - 23, 10, ctx.battery, ctx.usb)
    if ctx.usb:  # only show a clock when it will stay accurate
        c.text((right - 32, 7), f"{n:%H:%M}", font(15, "cond"), anchor="ra")
    c.line(14, 31, 386, 31)


def current_mode() -> str:
    return modes.mode_at(src.now())


def raining_soon() -> bool:
    pts = src.peek("rain")
    return bool(pts) and src.rain_summary(pts)["rain"]


def rotation() -> list[str]:
    """Page order for the side buttons; depends on time of day and rain."""
    order = modes.rotation(current_mode(), src.now(), raining_soon())
    if strava.connected():
        order.insert(order.index("trein") if order[-1] == "trein" else len(order), "sport")
    return order


def page_dots(c: Canvas, page: str):
    order = rotation()
    if page not in order:
        return
    i = order.index(page)
    n = len(order)
    x0 = 200 - (n * 10) // 2
    for k in range(n):
        x = x0 + k * 10
        if k == i:
            c.d.ellipse((x, 290, x + 5, 295), fill=BLACK)
        else:
            c.d.ellipse((x, 290, x + 5, 295), outline=BLACK)


def is_night() -> bool:
    h = src.now().hour
    return h < 7 or h >= 18


# ------------------------------------------------------------------ rain graph
def rain_graph(c: Canvas, x0: int, y0: int, w: int, h: int, pts, labels=True, dots=3):
    """Dot-matrix rain graph: columns of dots, height = intensity (log)."""
    import math
    if labels:
        f = font(12, "sans", "Medium")
        c.line(x0, y0 + 14, x0 + w, y0 + 14, w=2)
        for frac, lab in ((0, "nu"), (0.25, "+30m"), (0.5, "+1u"), (0.75, "+1½u")):
            x = x0 + int(w * frac)
            c.line(x, y0 + 10, x, y0 + 18, w=2)
            c.text((x + (0 if frac == 0 else 0), y0 - 2), lab, f, anchor="la" if frac == 0 else "ma")
        gy = y0 + 20
        gh = h - 20
    else:
        gy, gh = y0, h
    # guide lines for light / moderate / heavy
    for i in range(3):
        c.dotted_h(x0, x0 + w, gy + int(gh * (i + 0.5) / 3), 6)
    if not pts:
        return
    cols = len(pts)
    colw = w / cols
    for i, p in enumerate(pts):
        if p.mm < 0.1:
            continue
        level = min(1.0, (math.log10(p.mm) + 1) / 2)  # 0.1mm -> 0, 10mm -> 1
        rows = max(1, round(level * (gh // dots)))
        cx = x0 + i * colw
        for r in range(rows):
            yy = gy + r * dots
            for xx in range(int(cx), int(cx + colw), dots):
                c.d.rectangle((xx, yy, xx + dots - 2, yy + dots - 2), fill=BLACK)


# ------------------------------------------------------------------ building blocks
# Each block draws at (x, y) within width w and returns the y below it.
LABEL = lambda: font(11, "sans", "SemiBold")


def white_icon(c: Canvas, fn, *args):
    """Draw an icon in white (for use on black bars)."""
    tmp = Canvas()
    fn(tmp, *args)
    c.img.paste(255, (0, 0), tmp.img.point(lambda v: 255 if v < 128 else 0))


def fc_time(h: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(h["datetime"]).astimezone(src.TZ)


def rain_hint(rs: dict, hourly: list[dict]) -> str:
    """One line about rain: buienradar for the next 2h, else the hourly forecast."""
    if rs.get("rain"):
        return rs["headline"]
    n = src.now()
    for h in hourly[:12]:
        t = fc_time(h)
        if t < n - dt.timedelta(hours=1) or t > n + dt.timedelta(hours=10):
            continue
        if (h.get("precipitation") or 0) >= 0.3 or (h.get("precipitation_probability") or 0) >= 60:
            return f"Regen verwacht rond {t:%H}:00"
    return "Blijft droog"


def sun_times(states: dict) -> str:
    """'zon 8:18–16:33' (today's or the next rise/set from sun.sun)."""
    a = states.get("sun.sun", {}).get("attributes", {})
    try:
        rise = dt.datetime.fromisoformat(a["next_rising"]).astimezone(src.TZ)
        sets = dt.datetime.fromisoformat(a["next_setting"]).astimezone(src.TZ)
    except (KeyError, ValueError):
        return ""
    return f"☀ op {rise:%-H:%M} · onder {sets:%-H:%M}"


def blk_weather_now(c: Canvas, x, y, w, weather: dict, hourly: list[dict], rs: dict) -> int:
    cond = weather.get("state", "")
    temp = weather.get("attributes", {}).get("temperature")
    weather_icon(c, x + 22, y + 26, 44, cond, is_night())
    c.text((x + 52, y - 4), f"{round(temp)}°" if temp is not None else "–", font(44, "cond"))
    c.text((x, y + 56), COND_NL.get(cond, cond), font(13, "sans", "Medium"))
    temps = [h["temperature"] for h in hourly[:12] if h.get("temperature") is not None]
    if temps:
        c.text((x, y + 73), f"{round(min(temps))}° tot {round(max(temps))}°", font(12, "sans", "Regular"))
    hint = "Paraplu mee!" if rs.get("rain") else rain_hint(rs, hourly)
    c.text((x, y + 90), c.fit(hint, font(12, "sans", "SemiBold"), w), font(12, "sans", "SemiBold"))
    return y + 110


def blk_weather_day(c: Canvas, x, y, w, day: dict | None, label: str) -> int:
    c.text((x, y), label.upper(), LABEL())
    if not day:
        c.text((x, y + 18), "Geen verwachting", font(13, "sans", "Regular"))
        return y + 40
    cond = day.get("condition", "")
    weather_icon(c, x + 20, y + 42, 40, cond, False)
    hi = f"{round(day.get('temperature', 0))}°"
    c.text((x + 48, y + 16), hi, font(36, "cond"))
    if day.get("templow") is not None:
        c.text((x + 50 + c.width(hi, font(36, "cond")), y + 34), f"/ {round(day['templow'])}°", font(15, "cond"))
    c.text((x, y + 66), COND_NL.get(cond, cond), font(13, "sans", "Medium"))
    mm = day.get("precipitation") or 0
    p = day.get("precipitation_probability")
    sub = f"{p:.0f}% kans op regen" if p is not None else (f"{mm:.1f} mm regen" if mm >= 0.3 else "droog")
    c.text((x, y + 83), sub, font(12, "sans", "Regular"))
    return y + 104


def blk_trains(c: Canvas, x, y, w, data: dict | None, rows: int = 3) -> int:
    n = src.now()
    from .config import TO_SHORT
    c.text((x, y), (f"TREIN NAAR {TO_SHORT}" if TO_SHORT else "TREIN").upper(), LABEL())
    yy = y + 18
    if not data or data.get("error"):
        c.text((x, yy), (data or {}).get("error", "Geen treindata"), font(13, "sans", "Regular"))
        return yy + 20
    if data.get("disruptions"):
        tw = c.width("storing", font(11, "sans", "Bold"))
        c.rect(x + w - tw - 10, y - 2, x + w, y + 13, fill=BLACK, outline=None, r=3)
        c.text((x + w - 5, y - 1), "storing", font(11, "sans", "Bold"), fill=WHITE, anchor="ra")
    deps = [d for d in data["departures"] if d["actual"] > n][:rows]
    if not deps:
        c.text((x, yy), "Geen vertrekken", font(13, "sans", "Regular"))
        return yy + 20
    for d in deps:
        mins = max(0, round((d["actual"] - n).total_seconds() / 60))
        t = f"{d['planned']:%H:%M}"
        c.text((x, yy - 2), t, font(26, "cond"))
        tx = x + c.width(t, font(26, "cond")) + 8
        if d["cancelled"]:
            c.line(x, yy + 13, tx - 6, yy + 13, w=2)
            c.text((tx, yy + 6), "rijdt niet", font(13, "sans", "Bold"))
        else:
            if d["delay"]:
                c.rect(tx, yy + 3, tx + 30, yy + 21, fill=BLACK, outline=None, r=3)
                c.text((tx + 15, yy + 4), f"+{d['delay']}", font(13, "sans", "Bold"), fill=WHITE, anchor="ma")
            c.text((x + w, yy - 1), f"{mins} min", font(16, "sans", "SemiBold"), anchor="ra")
            c.text((x + w, yy + 18), f"spoor {d['track']}" + ("!" if d["track_changed"] else ""),
                   font(11, "sans", "Bold" if d["track_changed"] else "Regular"), anchor="ra")
        yy += 32
    return yy


def blk_events(c: Canvas, x, y, w, events: list[dict], label: str, max_y: int, empty: str = "Niets gepland") -> int:
    c.text((x, y), label.upper(), LABEL())
    yy = y + 18
    if not events:
        c.text((x, yy - 2), empty, font(22, "serifi"))
        return yy + 28
    f_t, f_e = font(14, "cond"), font(14, "sans", "Medium")
    whens = ["hele dag" if e["allday"] else f"{e['start']:%H:%M}" for e in events]
    col = max(c.width(s, f_t) for s in whens) + 8
    for i, (e, when) in enumerate(zip(events, whens)):
        if yy + 18 > max_y:
            rest = len(events) - i
            c.text((x + w, yy - 20), f"+{rest}", font(11, "sans", "SemiBold"), anchor="ra")
            break
        c.text((x, yy), when, f_t)
        c.text((x + col, yy), c.fit(e["title"], f_e, w - col), f_e)
        yy += 20
    return yy


def blk_dinner(c: Canvas, x, y, w) -> int:
    c.text((x, y), "VANAVOND OP TAFEL", LABEL())
    d = dinner.today()
    if not d:
        if dinner.busy():
            c.text((x, y + 18), "Ik zoek een recept…", font(22, "serifi"))
        else:
            c.text((x, y + 16), "Wat eten we?", font(25, "serifi"))
            c.paragraph(x, y + 50, "Houd de knop in en vraag om een recept. Het blijft hier staan; OK opent het weer.",
                        font(12, "sans", "Regular"), w, max_lines=3)
        return y + 110
    yy = y + 15
    for ln in c.wrap(d["title"], font(25, "serifi"), w, max_lines=2):
        c.text((x, yy), ln, font(25, "serifi"))
        yy += 27
    by = y + 96
    if d.get("blurb") and (room := (by - yy - 2) // 15) > 0:
        c.paragraph(x, yy + 2, d["blurb"], font(12, "sans", "Regular"), w, max_lines=room)
    c.rect(x, by, x + 26, by + 16, fill=BLACK, outline=None, r=3)
    c.text((x + 13, by + 1), "OK", font(11, "sans", "Bold"), fill=WHITE, anchor="ma")
    meta = " · ".join(v for v in ("recept", d.get("minutes", "")) if v)
    c.text((x + 32, by + 1), c.fit(meta, font(12, "sans", "Medium"), w - 32), font(12, "sans", "Medium"))
    return by + 18


def blk_shopping(c: Canvas, x, y, w, items: list[str]) -> int:
    c.text((x, y), "BOODSCHAPPEN", LABEL())
    yy = y + 18
    if not items:
        c.text((x, yy), "Lijst is leeg", font(13, "sans", "Regular"))
        return yy + 20
    f = font(13, "sans", "Medium")
    show = items if len(items) <= 5 else items[:4]  # five rows fit; otherwise four + "en nog …"
    for it in show:
        c.rect(x, yy + 3, x + 9, yy + 12)
        c.text((x + 15, yy), c.fit(it, f, w - 15), f)
        yy += 19
    if len(items) > len(show):
        c.text((x + 15, yy), f"en nog {len(items) - len(show)}", font(12, "sans", "Regular"))
        yy += 18
    return yy


def strip_rain(c: Canvas, y, rain, rs) -> int:
    c.text((14, y), rs["headline"], font(15, "sans", "SemiBold"))
    c.text((386, y + 3), "komende 2 uur", font(11, "sans", "Regular"), anchor="ra")
    rain_graph(c, 14, y + 22, 372, 30, rain, labels=False, dots=3)
    return y + 60


def waste_item(items: list[dict], n: dt.datetime) -> tuple[dict, str] | None:
    """The collection worth mentioning right now, with the message to show."""
    tomorrow = n.date() + dt.timedelta(days=1)
    for w in items[:3]:
        if w["date"] == tomorrow:
            return w, (f"Zet vanavond {w['name']} aan de straat" if n.hour >= 12 else f"Morgen {w['name']} · vanavond buiten zetten")
        if w["date"] == n.date() and n.hour < 12:
            return w, f"Vandaag wordt {w['name']} opgehaald"
    return None


def strip_waste(c: Canvas, y, msg: str) -> int:
    c.rect(14, y, 386, y + 28, fill=BLACK, outline=None, r=4)
    white_icon(c, bin_icon, 22, y + 5, 18)
    c.text((44, y + 6), msg, font(14, "sans", "SemiBold"), fill=WHITE)
    return y + 36


def package_msg(pkgs: list[dict], n: dt.datetime, evening: bool) -> str | None:
    """'PostNL vandaag 14:00–16:30' for parcels arriving today (or tomorrow, in the evening)."""
    day = n.date() + dt.timedelta(days=1 if evening else 0)
    hits = [p for p in pkgs if p["start"] and p["start"].date() == day]
    if not hits:
        return None
    if all(p["delivered"] for p in hits):
        return f"{len(hits)} pakket{'ten' if len(hits) > 1 else ''} bezorgd vandaag"
    p = next(p for p in hits if not p["delivered"])
    when = "morgen" if evening else "vandaag"
    win = f" {p['start']:%H:%M}" + (f"–{p['end']:%H:%M}" if p["end"] else "") if p["start"].hour or p["start"].minute else ""
    more = f" (+{len(hits) - 1})" if len(hits) > 1 else ""
    return f"{p['carrier']} {when}{win}{more}" + (f" · {p['name']}" if p["name"] and not more else "")


def strip_box(c: Canvas, y, label: str, msg: str) -> int:
    """Outlined bar: label in a black tab, message after it (lighter than the waste bar)."""
    c.rect(14, y, 386, y + 28, outline=BLACK, w=2, r=4)
    lw = c.width(label, font(11, "sans", "Bold")) + 14
    c.rect(14, y, 14 + lw, y + 28, fill=BLACK, outline=None, r=4)
    c.text((14 + lw // 2, y + 8), label, font(11, "sans", "Bold"), fill=WHITE, anchor="ma")
    c.text((22 + lw, y + 6), c.fit(msg, font(14, "sans", "SemiBold"), 386 - 30 - lw), font(14, "sans", "SemiBold"))
    return y + 36


def due_reminders(items: list[dict], n: dt.datetime, evening: bool) -> list[dict]:
    """Reminders due today or overdue (evening: due tomorrow)."""
    if evening:
        day = n.date() + dt.timedelta(days=1)
        return [r for r in items if r["due"] and r["due"].date() == day]
    return [r for r in items if r["due"] and r["due"].date() <= n.date()]


def reminder_msg(items: list[dict], n: dt.datetime) -> str:
    def one(r):
        t = f"{r['due']:%H:%M} " if r["timed"] else ""
        late = " (te laat)" if r["due"].date() < n.date() else ""
        return f"{t}{r['summary']}{late}"
    return " · ".join(one(r) for r in items)


def strip_countdown(c: Canvas, y, cd: "fun.Countdown") -> int:
    """'Nog 9 nachtjes slapen tot pakjesavond' with one dot per night; black on the day itself."""
    if cd.nights == 0:
        c.rect(14, y, 386, y + 30, fill=BLACK, outline=None, r=4)
        c.text((24, y + 6), f"{cd.emoji}  {cd.today_text}", font(15, "sans", "Bold"), fill=WHITE)
        return y + 38
    c.rect(14, y, 386, y + 28, outline=BLACK, w=2, r=14)
    c.text((26, y + 5), cd.emoji, font(16, "sans"))
    c.text((50, y + 6), cd.text, font(14, "sans", "SemiBold"))
    tx = 50 + c.width(cd.text, font(14, "sans", "SemiBold")) + 12
    room = (376 - tx) // 9
    for i in range(cd.nights if cd.nights <= room else 0):  # all the nights as dots, or none
        cx = 376 - i * 9
        c.d.ellipse((cx - 3, y + 11, cx + 3, y + 17), fill=BLACK)
    return y + 36


def strip_house(c: Canvas, y, s: dict) -> int:
    t = src.state_val(s, "sensor.alpstuga_air_quality_moni_temperature_sensor")
    opened = [s[e]["attributes"].get("friendly_name", e).replace(" Contact", "") for e in s
              if e.startswith("binary_sensor.") and e.endswith("_contact") and s[e]["state"] == "on"]
    lights = [e for e in s if e.startswith("light.") and s[e]["state"] == "on"]
    x = 14
    c.text((x, y), "BINNEN", LABEL())
    x += c.width("BINNEN", LABEL()) + 10
    parts = []
    if t:
        parts.append(f"{float(t):.0f}°")
    parts.append(f"{len(lights)} lamp{'en' if len(lights) != 1 else ''} aan")
    if not opened:
        parts.append("alles dicht")
    line = " · ".join(parts)
    c.text((x, y - 2), line, font(13, "sans", "Medium"))
    if opened:
        x += c.width(line + " · ", font(13, "sans", "Medium"))
        c.text((x, y - 2), c.fit("open: " + ", ".join(opened), font(13, "sans", "Bold"), 386 - x), font(13, "sans", "Bold"))
    return y + 22


def strip_hourly(c: Canvas, y, hourly: list[dict], cols: int = 7, step: int = 1, start: dt.datetime | None = None,
                 compact: bool = False) -> int:
    start = start or src.now() - dt.timedelta(minutes=30)
    slots = [h for h in hourly if fc_time(h) >= start][::step][:cols]
    if not slots:
        return y
    colw = 372 / len(slots)
    for i, h in enumerate(slots):
        cx = int(14 + i * colw + colw / 2)
        t = fc_time(h)
        night = t.hour < 7 or t.hour >= 18
        temp = f"{round(h.get('temperature', 0))}°"
        if compact:  # icon and temperature side by side, ~38 px tall
            c.text((cx, y), f"{t.hour}u", font(11, "sans", "Medium"), anchor="ma")
            weather_icon(c, cx - 12, y + 26, 20, h.get("condition", ""), night)
            c.text((cx + 2, y + 17), temp, font(15, "cond"))
            continue
        c.text((cx, y), f"{t.hour}u", font(12, "sans", "Medium"), anchor="ma")
        weather_icon(c, cx, y + 30, 26, h.get("condition", ""), night)
        c.text((cx, y + 46), temp, font(16, "cond"), anchor="ma")
    return y + (38 if compact else 62)


def day_forecast(daily: list[dict], d: dt.date) -> dict | None:
    return next((f for f in daily if fc_time(f).date() == d), None)


# ------------------------------------------------------------------ pages
async def page_home(ctx: Ctx):
    """'Nu': leads with what matters at this time of day (see modes.py)."""
    c = Canvas()
    n = src.now()
    mode = modes.mode_at(n)
    special = fun.today_special(n.date())
    header(c, ctx, "Hoera!" if special and special.birthday else modes.TITLES[mode])
    states, rain, waste, hourly, cal = await asyncio.gather(
        src.ha_states(), src.rain(), src.waste(), src.ha_forecast("hourly"), src.calendar(3))
    rs = src.rain_summary(rain)
    weather = states.get(src.settings.weather_entity, {})
    dinner.ensure()
    workday = modes.is_workday(n.date())
    tomorrow = n.date() + dt.timedelta(days=1)
    upcoming = [e for e in cal if e["end"] > n]
    today_ev = [e for e in upcoming if e["start"].date() <= n.date()]
    tomorrow_ev = [e for e in upcoming if e["start"].date() == tomorrow]

    # Top row: hero on the left, a side panel on the right.
    if mode == "ochtend" and workday:
        blk_trains(c, 14, 40, 216, await src.trains())
        blk_weather_now(c, 246, 40, 140, weather, hourly, rs)
    elif mode == "koken":
        blk_dinner(c, 14, 40, 216)
        blk_shopping(c, 246, 40, 140, await src.shopping())
    elif mode in ("avond", "nacht"):
        label = f"Morgen · {DAYS[tomorrow.weekday()]}"
        blk_events(c, 14, 40, 216, tomorrow_ev, label, 150)
        blk_weather_day(c, 246, 40, 140, day_forecast(await src.ha_forecast("daily"), tomorrow), "Weer morgen")
    else:
        if today_ev:
            blk_events(c, 14, 40, 216, today_ev, "Vandaag", 150)
        else:
            blk_events(c, 14, 40, 216, tomorrow_ev, f"Morgen · {DAYS[tomorrow.weekday()]}", 150,
                       empty="Vandaag niets gepland")
        blk_weather_now(c, 246, 40, 140, weather, hourly, rs)
    c.d.line((236, 42, 236, 146), fill=BLACK, width=1)
    c.line(14, 154, 386, 154)

    # Then strips that only appear when relevant, then fillers.
    y = 162
    if rs["rain"]:
        y = strip_rain(c, y, rain, rs)
    if (wi := waste_item(waste, n)):
        y = strip_waste(c, y, wi[1])
    evening = mode in ("avond", "nacht")
    if (air := fun.air_alert(states)) and y <= 282 - 20 - 36:  # air before fun: it asks for action
        y = strip_box(c, y, "LUCHT", f"{air[0]} · {air[1]}")
    cds = fun.all_countdowns(n.date())
    if cds and y <= 282 - 20 - 38:
        y = strip_countdown(c, y, cds[0])
    pkgs, todo = await asyncio.gather(src.packages(), src.reminders())
    if (pm := package_msg(pkgs, n, evening)) and y <= 282 - 20 - 36:
        y = strip_box(c, y, "PAKKET", pm)
    if (due := due_reminders(todo, n, evening)) and y <= 282 - 20 - 36:
        y = strip_box(c, y, "MORGEN" if evening else "TE DOEN", reminder_msg(due, n))
    bottom = 282
    fits = lambda h: y + h <= bottom - 20
    if mode == "ochtend" and workday:
        if fits(40):
            y = blk_events(c, 14, y, 372, today_ev, "Vandaag", bottom - 22) + 4
    elif mode == "koken":
        tonight = [e for e in today_ev if e["start"] > n and not e["allday"]]
        if tonight and fits(40):
            y = blk_events(c, 14, y, 372, tonight, "Vanavond", bottom - 22) + 4
        elif tomorrow_ev and fits(40):
            y = blk_events(c, 14, y, 372, tomorrow_ev, f"Morgen · {DAYS[tomorrow.weekday()]}", bottom - 22) + 4
    elif mode in ("dag", "ochtend") and not rs["rain"] and fits(40):
        y = strip_hourly(c, y, hourly, cols=7, step=1, compact=not fits(70)) + 4
    elif mode in ("avond", "nacht") and fits(56):
        # tomorrow morning's weather: coat, bike, umbrella?
        c.text((14, y), "MORGENOCHTEND", LABEL())
        start = dt.datetime.combine(tomorrow, dt.time(7), src.TZ)
        y = strip_hourly(c, y + 16, hourly, cols=6, step=1, start=start, compact=True) + 4
    if y <= bottom - 18:
        strip_house(c, bottom - 18, states)

    page_dots(c, ctx.page)
    return c, ctx.interval


async def page_weer(ctx: Ctx):
    c = Canvas()
    header(c, ctx, "Weer")
    rain, hourly, daily, states = await asyncio.gather(
        src.rain(), src.ha_forecast("hourly"), src.ha_forecast("daily"), src.ha_states())
    rs = src.rain_summary(rain)
    if rs["rain"]:  # rain coming: the radar graph leads
        c.text((14, 40), "REGEN · KOMENDE 2 UUR", LABEL())
        c.text((14, 54), rs["headline"], font(24, "sans", "Bold"))
        rain_graph(c, 14, 90, 372, 82, rain, labels=True, dots=4)
        c.line(14, 182, 386, 182)
        strip_hourly(c, 190, hourly, cols=5, step=2)
        if (st := sun_times(states)):
            c.text((386, 40), st, font(12, "sans", "Medium"), anchor="ra")
        page_dots(c, ctx.page)
        return c, ctx.interval
    # Dry: no empty radar, show the day instead.
    weather = states.get(src.settings.weather_entity, {})
    blk_weather_now(c, 14, 40, 200, weather, hourly, rs)
    n = src.now()
    x = 230
    for i in range(1, 4):  # next three days
        d = n.date() + dt.timedelta(days=i)
        f = day_forecast(daily, d)
        if not f:
            continue
        yy = 40 + (i - 1) * 36
        c.text((x, yy + 6), (day_label(d) if i == 1 else DAYS[d.weekday()]).capitalize(), font(13, "sans", "Medium"))
        weather_icon(c, x + 80, yy + 15, 24, f.get("condition", ""), False)
        c.text((386, yy + 2), f"{round(f.get('temperature', 0))}°", font(18, "cond"), anchor="ra")
        if f.get("templow") is not None:
            c.text((352, yy + 6), f"{round(f['templow'])}°", font(14, "cond"), anchor="ra")
    c.line(14, 156, 386, 156)
    strip_hourly(c, 166, hourly, cols=7, step=1)
    c.text((14, 252), "Buienradar: droog, komende 2 uur", font(12, "sans", "Regular"))
    if (st := sun_times(states)):
        c.text((386, 252), st, font(12, "sans", "Medium"), anchor="ra")
    page_dots(c, ctx.page)
    return c, max(ctx.interval, 300) if not ctx.usb else ctx.interval


async def page_trein(ctx: Ctx):
    c = Canvas()
    header(c, ctx, "Trein")
    data = await src.trains()
    n = src.now()
    train_icon(c, 14, 42, 22)
    route = " → ".join(p for p in (src.settings.ns_station_name or src.settings.ns_station, src.settings.ns_to) if p)
    c.text((40, 40), route or "Vertrektijden", font(17, "sans", "SemiBold"))
    y = 76
    if not data or data.get("error"):
        c.paragraph(14, y, (data or {}).get("error", "Geen treindata") +
                    ". Vraag een gratis key aan op apiportal.ns.nl en zet hem in de hub-instellingen.",
                    font(14, "sans", "Regular"), 372)
    else:
        deps = [d for d in data["departures"] if d["actual"] > n - dt.timedelta(minutes=1)][:5]
        for d in deps:
            mins = max(0, round((d["actual"] - n).total_seconds() / 60))
            c.text((14, y), f"{d['planned']:%H:%M}", font(24, "cond"))
            x = 84
            if d["cancelled"]:
                c.line(14, y + 15, 78, y + 15, w=2)
                c.text((x, y + 6), "Rijdt niet", font(14, "sans", "Bold"))
            else:
                if d["delay"]:
                    c.rect(x, y + 4, x + 34, y + 24, fill=BLACK, outline=None, r=3)
                    c.text((x + 17, y + 6), f"+{d['delay']}", font(14, "sans", "Bold"), fill=WHITE, anchor="ma")
                    x += 42
                c.text((x, y + 7), c.fit(f"{d['type']} {d['direction']}", font(13, "sans", "Regular"), 190), font(13, "sans", "Regular"))
                tr = f"spoor {d['track']}"
                c.text((386, y + 1), f"{mins} min", font(16, "sans", "SemiBold"), anchor="ra")
                c.text((386, y + 20), tr + (" (gewijzigd)" if d["track_changed"] else ""),
                       font(11, "sans", "Bold" if d["track_changed"] else "Regular"), anchor="ra")
            y += 38
            c.line(14, y - 3, 386, y - 3)
        if not deps:
            c.text((14, y), "Geen vertrekken gevonden", font(14, "sans", "Regular"))
        if data.get("disruptions"):
            c.rect(14, 256, 386, 284, fill=BLACK, outline=None, r=4)
            c.text((22, 262), c.fit("Storing: " + data["disruptions"][0], font(13, "sans", "SemiBold"), 356),
                   font(13, "sans", "SemiBold"), fill=WHITE)
    page_dots(c, ctx.page)
    return c, ctx.interval


async def page_agenda(ctx: Ctx):
    c = Canvas()
    header(c, ctx, "Agenda")
    events = await src.calendar(7)
    n = src.now()
    if not src.settings.gcal_ics:
        c.paragraph(14, 50, "Nog geen agenda gekoppeld. Zet de geheime iCal-URL van je Google Agenda in de hub-instellingen (Instellingen → je agenda → 'Geheim adres in iCal-indeling').",
                    font(14, "sans", "Regular"), 372)
        page_dots(c, ctx.page)
        return c, 3600
    y = 40
    last_day = None
    shown = 0
    for e in events:
        if e["end"] <= n:
            continue
        d = e["start"].date() if e["start"] > n else n.date()
        if d != last_day:
            if y > 250:
                break
            label = day_label(d)
            c.text((14, y + 4), label.capitalize(), font(13, "sans", "Bold"))
            c.text((386, y + 6), f"{d.day} {MONTHS[d.month - 1]}", font(11, "sans", "Regular"), anchor="ra")
            y += 24
            last_day = d
        if y > 266:
            break
        when = "hele dag" if e["allday"] else f"{e['start']:%H:%M}"
        c.text((22, y), when, font(15, "cond"))
        c.text((82, y), c.fit(e["title"], font(15, "sans", "Medium"), 300), font(15, "sans", "Medium"))
        y += 22
        shown += 1
    if not shown:
        c.text((14, 60), "Niets gepland deze week", font(serif_size := 26, "serifi"))
    page_dots(c, ctx.page)
    return c, max(ctx.interval, 300)


async def page_afval(ctx: Ctx):
    c = Canvas()
    header(c, ctx, "Afval")
    items = await src.waste()
    n = src.now()
    if not items:
        c.text((14, 50), "Geen afvaldata", font(16, "sans", "Medium"))
        return c, 3600
    first = items[0]
    bin_icon(c, 16, 46, 54)
    c.text((70, 42), first["name"], font(30, "sans", "Bold"))
    lbl = day_label(first["date"])
    c.text((72, 82), f"{lbl} · {DAYS[first['date'].weekday()]} {first['date'].day} {MONTHS[first['date'].month - 1]}",
           font(14, "sans", "Medium"))
    if first["date"] == n.date() + dt.timedelta(days=1):
        c.rect(14, 112, 386, 140, fill=BLACK, outline=None, r=4)
        c.text((200, 117), "Vanavond de container aan de straat", font(14, "sans", "SemiBold"), fill=WHITE, anchor="ma")
    y = 156
    for it in items[1:6]:
        c.text((14, y), it["name"], font(16, "sans", "Medium"))
        c.text((386, y), f"{day_label(it['date'])}", font(16, "sans", "Regular"), anchor="ra")
        y += 25
        c.dotted_h(14, 386, y - 4, 3)
    page_dots(c, ctx.page)
    return c, 3600


async def page_huis(ctx: Ctx):
    c = Canvas()
    header(c, ctx, "Huis")
    s = await src.ha_states()
    v = lambda e, d=None: src.state_val(s, e, d)

    def tile(x, y, w, h, label, value, sub=""):
        c.rect(x, y, x + w, y + h, outline=BLACK, r=6)
        c.text((x + 10, y + 7), label.upper(), font(10, "sans", "SemiBold"))
        c.text((x + 10, y + 21), c.fit(value, font(24, "cond"), w - 18), font(24, "cond"))
        if sub:
            c.text((x + 10, y + h - 19), c.fit(sub, font(11, "sans", "Regular"), w - 18), font(11, "sans", "Regular"))

    t = v("sensor.alpstuga_air_quality_moni_temperature_sensor")
    tile(14, 40, 120, 76, "Woonkamer", f"{float(t):.1f}°" if t else "–",
         f"{v('sensor.alpstuga_air_quality_moni_humidity_sensor', '–')}% · {str(v('sensor.luchtkwaliteit_woonkamer', '')).lower()}")
    p = v("sensor.electricity_meter_energieverbruik")
    pr = v("sensor.electricity_meter_energieproductie")
    net = (float(p or 0) - float(pr or 0))
    tile(140, 40, 120, 76, "Stroom nu", f"{net:+.1f} kW".replace("+", "") if net >= 0 else f"{net:.1f} kW",
         "teruglevering" if net < 0 else "van het net")
    lights = sorted(s[e]["attributes"].get("friendly_name", e) for e in s if e.startswith("light.") and s[e]["state"] == "on")
    tile(266, 40, 120, 76, "Lampen", f"{len(lights)} aan", ", ".join(lights[:3]))

    opened = [s[e]["attributes"].get("friendly_name", e).replace(" Contact", "") for e in s
              if e.startswith("binary_sensor.") and e.endswith("_contact") and s[e]["state"] == "on"]
    tile(14, 122, 120, 76, "Ramen/deuren", "dicht" if not opened else f"{len(opened)} open", ", ".join(opened[:2]))
    ok = lambda e: s[e]["state"] not in ("unknown", "unavailable")
    climates = [e for e in s if e.startswith("climate.") and ok(e)]
    if climates:
        ca = s[climates[0]]["attributes"]
        tile(140, 122, 120, 76, "Warmtepomp", f"{ca.get('current_temperature', '–')}°",
             f"{s[climates[0]]['state']} · doel {ca.get('temperature', '–')}°")
    kona = [e for e in s if "kona" in e and "battery" in e and "level" in e and s[e]["state"] not in ("unknown", "unavailable")]
    if kona:
        tile(266, 122, 120, 76, "Kona", f"{s[kona[0]]['state']}%", "accu")
    else:
        locks = [e for e in s if e.startswith("lock.") and ok(e)]
        if locks:
            tile(266, 122, 120, 76, "Slot", "op slot" if s[locks[0]]["state"] == "locked" else s[locks[0]]["state"],
                 s[locks[0]]["attributes"].get("friendly_name", ""))
    modes = [n for e, n in (("input_boolean.vakantiemodus", "vakantie"), ("input_boolean.nachtstand", "nacht"),
                            ("input_boolean.filmstand", "film"), ("input_boolean.gastenmodus", "gasten")) if v(e) == "on"]
    c.text((14, 210), "Modus: " + (", ".join(modes) if modes else "normaal"), font(13, "sans", "Medium"))
    batt_low = sorted((int(float(s[e]["state"])), s[e]["attributes"].get("friendly_name", e).replace(" Battery", ""))
                      for e in s if e.endswith("_battery") and s[e]["state"].replace(".", "").isdigit()
                      and float(s[e]["state"]) <= 30)
    if batt_low:
        c.text((14, 232), "Batterij bijna leeg: " + ", ".join(f"{n} {b}%" for b, n in batt_low[:3]),
               font(12, "sans", "Regular"))
    page_dots(c, ctx.page)
    return c, ctx.interval


async def page_sport(ctx: Ctx):
    c = Canvas()
    header(c, ctx, "Sport")
    if not strava.connected():
        c.text((14, 44), "🚴", font(40, "sans"))
        c.paragraph(70, 50, "Strava is nog niet gekoppeld. Open in Home Assistant de zijbalk → Huisdisplay → "
                    "Strava koppelen, en log daar één keer in bij Strava.", font(14, "sans", "Medium"), 316)
        page_dots(c, ctx.page)
        return c, 3600
    s = await strava.summary()
    if not s:
        c.text((14, 50), "Geen Strava-data", font(16, "sans", "Medium"))
        page_dots(c, ctx.page)
        return c, 900
    wk = s["week"]
    # Left: this week
    c.text((14, 40), "DEZE WEEK", LABEL())
    h, m = divmod(wk["minutes"], 60)
    big = f"{h}u{m:02d}" if wk["minutes"] else "0"
    c.text((14, 54), big, font(40, "cond"))
    c.text((16 + c.width(big, font(40, "cond")) + 6, 72), f"{wk['km']:g} km · {wk['count']}×", font(13, "sans", "Medium"))
    avg = s["avg4_minutes"]
    if avg:
        diff = wk["minutes"] - avg
        c.text((14, 102), f"{'+' if diff >= 0 else '−'}{abs(diff)} min t.o.v. gemiddelde week", font(12, "sans", "Regular"))
    # Day bars (moving time), Mon..Sun
    days = wk["days"]
    mx = max([d["minutes"] for d in days] + [avg / 3 if avg else 30, 30])
    bx, by, bw, bh = 14, 122, 26, 50
    today = src.now().weekday()
    for i, d in enumerate(days):
        x = bx + i * (bw + 4)
        hgt = int(bh * d["minutes"] / mx)
        if hgt:
            c.rect(x, by + bh - hgt, x + bw, by + bh, fill=BLACK, outline=None)
        else:
            c.line(x, by + bh, x + bw, by + bh)
        c.text((x + bw // 2, by + bh + 4), DAYS[i][:2], font(11, "sans", "Bold" if i == today else "Regular"), anchor="ma")
    # Right: last activity
    x = 236
    c.d.line((226, 42, 226, 190), fill=BLACK, width=1)
    last = s["last"]
    c.text((x, 40), "LAATSTE", LABEL())
    if last:
        yy = 54
        for ln in c.wrap(last["name"], font(21, "serifi"), 150, max_lines=2):
            c.text((x, yy), ln, font(21, "serifi"))
            yy += 23
        c.text((x, yy + 2), f"{day_label(last['start'].date())} · {last['kind_nl']}", font(12, "sans", "Medium"))
        yy += 22
        rows = [("afstand", f"{last['km']:g} km")] if last["km"] else []
        lh, lm = divmod(last["minutes"], 60)
        rows.append(("tijd", f"{lh}:{lm:02d}" if lh else f"{lm} min"))
        if last["km"] and last["kind"].endswith("Run"):
            pace = last["minutes"] / last["km"]
            rows.append(("tempo", f"{int(pace)}:{round((pace % 1) * 60):02d} /km"))
        elif last["kmh"]:
            rows.append(("gem.", f"{last['kmh']:g} km/u"))
        if last["elev"] > 20:
            rows.append(("hoogte", f"{last['elev']} m"))
        for k, v in rows[:4]:
            c.text((x, yy), k, font(12, "sans", "Regular"))
            c.text((386, yy - 1), v, font(14, "cond"), anchor="ra")
            yy += 18
    c.line(14, 200, 386, 200)
    st = s["streak_weeks"]
    c.text((14, 210), f"{st} {'week' if st == 1 else 'weken'} op rij actief" if st else "Nieuwe week, nieuwe kansen",
           font(20, "serifi"))
    recent = [a for a in s["recent"][::-1][1:4]]
    yy = 240
    for a in recent:
        c.text((14, yy), f"{day_label(a['start'].date())}", font(12, "sans", "Medium"))
        c.text((110, yy), c.fit(a["name"], font(12, "sans", "Regular"), 200), font(12, "sans", "Regular"))
        c.text((386, yy), f"{a['km']:g} km" if a["km"] else f"{a['minutes']} min", font(12, "sans", "Medium"), anchor="ra")
        yy += 15
    page_dots(c, ctx.page)
    return c, max(ctx.interval, 600)


TYPE_NL = {"normal": "normaal", "fire": "vuur", "water": "water", "grass": "gras", "electric": "elektrisch", "ice": "ijs",
           "fighting": "vechten", "poison": "gif", "ground": "grond", "flying": "vliegen", "psychic": "psychisch",
           "bug": "insect", "rock": "steen", "ghost": "geest", "dragon": "draak", "dark": "duister", "steel": "staal",
           "fairy": "fee"}


async def page_nieuws(ctx: Ctx):
    c = Canvas()
    header(c, ctx, "Nieuws")
    items, pods = await asyncio.gather(src.news(), src.podcasts())
    y = 40
    c.text((14, y), "NOS · BELANGRIJKSTE BERICHTEN", LABEL())
    y += 17
    for k, it in enumerate(items[:3]):
        for ln in c.wrap(it["title"], font(15, "sans", "Bold"), 372, 2):
            c.text((14, y), ln, font(15, "sans", "Bold"))
            y += 18
        if it["summary"] and k == 0:  # the lead gets a line of context
            c.text((14, y), c.fit(it["summary"], font(12, "sans", "Regular"), 372), font(12, "sans", "Regular"))
            y += 17
        y += 5
    if pods and y < 222:
        c.line(14, y, 386, y)
        y += 8
        c.text((14, y), "🎧  NIEUWSTE AFLEVERINGEN", LABEL())
        y += 17
        n = src.now()
        for p in pods:
            if y > 268:
                break
            new = p["when"] and (n - p["when"]).days < 3
            show = p["show"] + (" •" if new else "")
            sw = c.width(show, font(13, "sans", "Bold"))
            c.text((14, y), show, font(13, "sans", "Bold"))
            when = day_label(p["when"].date())[:9] if p["when"] else ""
            ww = c.width(when, font(11, "sans", "Regular")) + 10 if when else 0
            c.text((22 + sw, y), c.fit(p["title"], font(13, "sans", "Regular"), 372 - 8 - sw - ww), font(13, "sans", "Regular"))
            if when:
                c.text((386, y + 1), when, font(11, "sans", "Regular"), anchor="ra")
            y += 19
    page_dots(c, ctx.page)
    return c, max(ctx.interval, 600)


async def page_kunst(ctx: Ctx):
    from . import art
    c = Canvas()
    n = src.now()
    img, name, num = art.of_the_day(n.date())
    c.img.paste(img, (0, 0))
    c.rect(0, 278, 400, 300, fill=WHITE, outline=None)
    c.line(0, 278, 400, 278)
    c.text((10, 282), f"Kunst van de dag · {name} · #{num:03d}", font(12, "sans", "Medium"))
    order = rotation()
    if ctx.page in order:
        c.text((390, 282), f"{order.index(ctx.page) + 1}/{len(order)}", font(12, "sans", "Medium"), anchor="ra")
    return c, 3600


async def page_pokemon(ctx: Ctx):
    c = Canvas()
    header(c, ctx, "Pokémon")
    pk = await src.pokemon_of_the_day()
    if not pk:
        c.text((14, 50), "Geen Pokémon gevonden vandaag", font(16, "sans", "Medium"))
        page_dots(c, ctx.page)
        return c, 1800
    from PIL import Image
    pic = pk["image"].resize((170, 170), Image.LANCZOS).point(lambda v: min(255, int(v * 1.08)))
    c.img.paste(pic.convert("1").convert("L"), (218, 46))  # Floyd-Steinberg dither
    c.text((14, 40), f"POKÉMON VAN DE DAG · #{pk['id']:03d}", LABEL())
    name = pk["name"]
    size = 40
    while size > 22 and c.width(name, font(size, "serifi")) > 200:
        size -= 2
    c.text((12, 52), name, font(size, "serifi"))
    x, y = 14, 104
    for t in pk["types"]:
        lab = TYPE_NL.get(t, t)
        w = c.width(lab, font(12, "sans", "Bold")) + 16
        c.rect(x, y, x + w, y + 20, fill=BLACK, outline=None, r=10)
        c.text((x + w // 2, y + 3), lab, font(12, "sans", "Bold"), fill=WHITE, anchor="ma")
        x += w + 6
    if pk["legendary"]:
        c.text((x + 2, y + 1), "⭐ legendarisch", font(13, "sans", "SemiBold"))
    y = 136
    for lab, val in (("lengte", f"{pk['height_m']:g} m"), ("gewicht", f"{pk['weight_kg']:g} kg")):
        c.text((14, y), lab, font(13, "sans", "Regular"))
        c.text((200, y - 1), val, font(16, "cond"), anchor="ra")
        y += 21
    from . import fun
    fact = await fun.pokemon_fact(pk)
    if fact:
        c.paragraph(14, 222, fact, font(14, "sans", "Medium"), 372, 1.25, 3)
    page_dots(c, ctx.page)
    return c, 3600


async def page_schaak(ctx: Ctx):
    from . import schaak
    c = Canvas()
    header(c, ctx, "Schaak")
    title, board, tip, num, moves = schaak.of_the_day(src.now().date())
    schaak.draw_board(c, board, 22, 38, 29)
    x, w = 266, 122
    c.text((x, 38), f"STELLING VAN DE DAG", font(10, "sans", "SemiBold"))
    y = 52
    for ln in c.wrap(title, font(21, "serifi"), w, 3):
        c.text((x, y), ln, font(21, "serifi"))
        y += 22
    y += 6
    turn = "Wit aan zet" if board.turn else "Zwart aan zet"
    tw = c.width(turn, font(11, "sans", "Bold")) + 14
    if board.turn:
        c.rect(x, y, x + tw, y + 18, outline=BLACK, w=2, r=9)
        c.text((x + tw // 2, y + 2), turn, font(11, "sans", "Bold"), anchor="ma")
    else:
        c.rect(x, y, x + tw, y + 18, fill=BLACK, outline=None, r=9)
        c.text((x + tw // 2, y + 2), turn, font(11, "sans", "Bold"), fill=WHITE, anchor="ma")
    y += 28
    y = c.paragraph(x, y, tip, font(12, "sans", "Medium"), w, 1.25, 7)
    if moves:
        nl = moves.replace("N", "P").replace("B", "L").replace("R", "T").replace("Q", "D").replace("K", "K")
        parts = nl.split()
        txt = " ".join((f"{i // 2 + 1}.{m}" if i % 2 == 0 else m) for i, m in enumerate(parts))
        c.paragraph(x, max(y + 4, 236), txt, font(10, "sans", "Regular"), w, 1.2, 3)
    page_dots(c, ctx.page)
    return c, 3600


# ------------------------------------------------------------------ voice states
async def page_listening(ctx: Ctx):
    c = Canvas()
    c.rect(40, 50, 360, 250, fill=BLACK, outline=None, r=14)
    # cat ears 🐱
    for x0 in (64, 278):
        c.d.polygon([(x0, 56), (x0 + 29, 16), (x0 + 58, 56)], fill=BLACK)
        c.d.polygon([(x0 + 18, 50), (x0 + 29, 33), (x0 + 40, 50)], fill=WHITE)
    c.d.rounded_rectangle((52, 62, 348, 238), radius=10, fill=BLACK)
    # white mic on black
    tmp = Canvas()
    mic_icon(tmp, 200, 112, 52)
    mask = tmp.img.point(lambda v: 255 if v < 128 else 0)
    c.img.paste(255, (0, 0), mask)
    c.text((200, 158), "Ik luister…", font(26, "sans", "Bold"), fill=WHITE, anchor="ma")
    c.text((200, 196), "laat de knop los om te versturen", font(14, "sans", "SemiBold"), fill=WHITE, anchor="ma")
    return c, 0


async def page_thinking(ctx: Ctx):
    c = Canvas()
    c.rect(40, 50, 360, 250, fill=WHITE, outline=BLACK, w=3, r=14)
    for i in range(3):  # little paw prints walking across
        c.text((158 + i * 42, 96 + (i % 2) * 12), "🐾", font(22, "sans"), anchor="ma")
    c.text((200, 150), "Even denken…", font(24, "serifi"), anchor="ma")
    return c, 0


async def page_message(ctx: Ctx, title: str, body: str):
    c = Canvas()
    header(c, ctx, title)
    c.paragraph(14, 50, body, font(16, "sans", "Medium"), 372)
    return c, ctx.interval


PAGES = {
    "home": page_home, "weer": page_weer, "trein": page_trein, "agenda": page_agenda,
    "huis": page_huis, "afval": page_afval, "sport": page_sport, "nieuws": page_nieuws, "kunst": page_kunst,
    "pokemon": page_pokemon, "schaak": page_schaak, "listening": page_listening, "thinking": page_thinking,
}
