"""Playful bits: countdowns (pakjesavond, Kerst, birthdays) and seasonal marks.

Settings (kept out of the code, they're personal):
  BIRTHDAYS   "Thomas|2019-05-17, Noor|2016-09-02"     -> counts down 30 days before
  COUNTDOWNS  "🎁 Pakjesavond|12-05|21, 🎄 Kerst|12-25|19" -> name|MM-DD|days-before-to-show
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from . import sources as src
from .config import settings

DEFAULT_COUNTDOWNS = "🎁 Pakjesavond|12-05|21, 🎄 Kerst|12-25|19"


@dataclass
class Countdown:
    name: str        # "Pakjesavond" / "Thomas"
    emoji: str
    date: dt.date
    nights: int      # nights of sleep left (0 = today)
    birthday: bool = False
    age: int | None = None

    @property
    def today_text(self) -> str:
        if self.birthday:
            return f"Hoera! {self.name} wordt vandaag {self.age}!" if self.age else f"Hoera! {self.name} is jarig!"
        return f"Vandaag is het {self.name.lower()}!"

    @property
    def text(self) -> str:
        if self.nights == 0:
            return self.today_text
        what = f"{self.name} jarig" if self.birthday else self.name.lower()
        if self.nights == 1:
            return f"Nog 1 nachtje slapen tot {what}"
        return f"Nog {self.nights} nachtjes slapen tot {what}"


def _next(md: tuple[int, int], today: dt.date) -> dt.date:
    d = dt.date(today.year, *md)
    return d if d >= today else dt.date(today.year + 1, *md)


def _split_emoji(label: str) -> tuple[str, str]:
    from .render import is_emoji
    label = label.strip()
    if label and is_emoji(label[0]):
        return label[0], label[1:].strip()
    return "⭐", label


def all_countdowns(today: dt.date | None = None) -> list[Countdown]:
    """Every upcoming countdown that is inside its show window, nearest first."""
    today = today or src.now().date()
    out: list[Countdown] = []
    for item in (settings.countdowns or DEFAULT_COUNTDOWNS).split(","):
        parts = [p.strip() for p in item.split("|")]
        if len(parts) < 2:
            continue
        try:
            m, d = (int(v) for v in parts[1].split("-"))
            window = int(parts[2]) if len(parts) > 2 else 21
        except ValueError:
            continue
        emoji, name = _split_emoji(parts[0])
        date = _next((m, d), today)
        nights = (date - today).days
        if nights <= window:
            out.append(Countdown(name, emoji, date, nights))
    for item in (settings.birthdays or "").split(","):
        parts = [p.strip() for p in item.split("|")]
        if len(parts) != 2:
            continue
        try:
            born = dt.date.fromisoformat(parts[1])
        except ValueError:
            continue
        date = _next((born.month, born.day), today)
        nights = (date - today).days
        if nights <= 30:
            out.append(Countdown(parts[0], "🎂", date, nights, birthday=True, age=date.year - born.year))
    return sorted(out, key=lambda c: c.nights)


def today_special(today: dt.date | None = None) -> Countdown | None:
    return next((c for c in all_countdowns(today) if c.nights == 0), None)


def season_mark(t: dt.datetime) -> str:
    """A tiny emoji after the date in the header, only on days that deserve one."""
    if (sp := today_special(t.date())):
        return sp.emoji
    if t.month == 12 and t.day > 5 or t.month == 1 and t.day <= 6:
        return "❄"
    if t.month == 10 and t.day == 31:
        return "🎃"
    if t.month == 4 and t.day == 27:
        return "👑"
    return ""


def describe_for_assistant(today: dt.date | None = None) -> str:
    """Family facts for Claude: names, ages, upcoming countdowns."""
    today = today or src.now().date()
    bits = []
    for item in (settings.birthdays or "").split(","):
        parts = [p.strip() for p in item.split("|")]
        if len(parts) == 2:
            try:
                born = dt.date.fromisoformat(parts[1])
            except ValueError:
                continue
            age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
            nxt = _next((born.month, born.day), today)
            bits.append(f"{parts[0]} is {age} jaar en jarig op {born.day}-{born.month} (nog {(nxt - today).days} dagen)")
    for c in all_countdowns(today):
        if not c.birthday:
            bits.append(f"{c.name}: nog {c.nights} nachtjes ({c.date:%d-%m})")
    return "; ".join(bits)


async def pokemon_fact(pk: dict) -> str:
    """Two Dutch sentences for a 7-year-old about today's Pokémon (Claude, once a day, cached)."""
    import json
    from .config import settings as s
    f = s.data_dir / "pokemon_fact.json"
    day = src.real_now().date().isoformat()
    try:
        cached = json.loads(f.read_text())
        if cached.get("day") == day and cached.get("id") == pk["id"]:
            return cached["text"]
    except Exception:
        pass
    text = ""
    if s.anthropic_api_key:
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key)
            r = await client.messages.create(
                model=s.claude_model, max_tokens=300, output_config={"effort": "low"},
                messages=[{"role": "user", "content":
                           f"Schrijf voor een kind van 7 twee korte, enthousiaste Nederlandse zinnen over de Pokémon "
                           f"{pk['name']} (type {', '.join(pk['types'])}, {pk['genus']}). Gebruik dit als bron: "
                           f"{pk['flavor_en']} Geen emoji, geen aanhalingstekens, alleen de twee zinnen."}])
            text = " ".join(b.text for b in r.content if b.type == "text").strip()
        except Exception as e:
            import logging
            logging.getLogger("hub.fun").warning("pokemon fact: %s", e)
    if text:
        f.write_text(json.dumps({"day": day, "id": pk["id"], "text": text}, ensure_ascii=False))
    return text


def air_alert(states: dict) -> tuple[str, str] | None:
    """('Zet even een raam open', 'fijnstof 32 µg/m³') when the living-room air is poor."""
    def num(eid):
        try:
            return float(states[eid]["state"])
        except (KeyError, ValueError):
            return None
    pm = num(settings.air_pm25_sensor)
    hum = num(settings.air_humidity_sensor)
    label = str(states.get(settings.air_quality_sensor, {}).get("state", "")).lower()
    if pm is not None and pm >= 50 or label in ("slecht", "zeer slecht", "poor", "very poor"):
        return "Zet een raam open, de lucht is slecht", f"fijnstof {pm:.0f} µg/m³" if pm is not None else label
    if pm is not None and pm >= 25 or label in ("matig", "moderate"):
        return "Even luchten? De lucht wordt minder", f"fijnstof {pm:.0f} µg/m³" if pm is not None else label
    if hum is not None and hum >= 70:
        return "Het is vochtig binnen, even luchten", f"vochtigheid {hum:.0f}%"
    return None
