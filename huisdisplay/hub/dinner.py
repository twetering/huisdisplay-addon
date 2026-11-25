"""Tonight's dinner for cooking mode.

By default only on request: a recipe asked by voice in the afternoon becomes
tonight's dinner, shown on 'Nu' in cooking mode, where OK reopens the card.
With DINNER_AUTO=true Claude also picks an Allerhande recipe by itself from
14:00 (in the background), avoiding the last two weeks of dishes.
"""

from __future__ import annotations

import asyncio
import json
import logging

from . import sources as src
from .config import settings

log = logging.getLogger("hub.dinner")
FILE = settings.data_dir / "dinner.json"
_task: asyncio.Task | None = None


def _load() -> dict:
    try:
        return json.loads(FILE.read_text())
    except Exception:
        return {"history": []}


def today() -> dict | None:
    """Today's suggestion, or None while it hasn't been made yet."""
    d = _load()
    if d.get("date") == src.real_now().date().isoformat() and d.get("card"):
        return d
    return None


def ensure(force: bool = False) -> None:
    """Start generating today's suggestion in the background if needed."""
    global _task
    if not settings.dinner_auto or not settings.anthropic_api_key or (_task and not _task.done()):
        return
    if not force and (today() or src.real_now().hour < 14):
        return
    _task = asyncio.create_task(_generate())


def busy() -> bool:
    return bool(_task and not _task.done())


def remember(card: dict) -> None:
    """Keep a recipe card asked by voice (after noon) as tonight's dinner."""
    if src.real_now().hour < 12 or not any(b.get("type") == "steps" for b in card.get("blocks", [])):
        return
    _save(dict(card))


def _save(card: dict) -> None:
    d = _load()
    n = src.real_now()
    blurb = next((b.get("text", "") for b in card["blocks"] if b.get("type") == "text"), "")
    minutes = ""
    for b in card["blocks"]:
        for r in b.get("rows") or []:
            if r.get("label", "").lower().startswith(("tijd", "bereiding")):
                minutes = r.get("value", "")
    card.pop("query", None)
    card["keep_seconds"] = 1800
    hist = (d.get("history", []) + [{"date": n.date().isoformat(), "title": card.get("title", "")}])[-30:]
    FILE.write_text(json.dumps({"date": n.date().isoformat(), "title": card.get("title", ""), "blurb": blurb,
                                "minutes": minutes, "card": card, "history": hist}, ensure_ascii=False, indent=1))
    log.info("dinner: %s", card.get("title"))


async def _generate():
    from . import assistant
    d = _load()
    recent = [h["title"] for h in d.get("history", [])][-14:]
    n = src.real_now()
    weekday = n.weekday() < 5
    weather = ""
    try:
        fc = await src.ha_forecast("daily")
        if fc:
            weather = f" Het wordt vandaag max {round(fc[0].get('temperature', 0))}° ({fc[0].get('condition', '')})."
    except Exception:
        pass
    query = (
        "Stel het avondeten voor vandaag voor: kies één recept van Albert Heijn Allerhande "
        f"voor dit huishouden ({settings.dinner_prefs}). "
        f"{'Het is doordeweeks, dus max 40 minuten.' if weekday else 'Het is weekend, mag iets uitgebreider.'}"
        f" Seizoensgebonden.{weather}"
        + (f" Niet een van deze recente gerechten: {', '.join(recent)}." if recent else "")
        + " Zoek het op met web_search en haal het recept op met web_fetch zodat ingrediënten en stappen kloppen."
        " Toon het daarna met show_card: kicker 'Vanavond', titel = naam van het gerecht, "
        "eerste blok een text-blok met één smakelijke zin (max 14 woorden), dan rows met Tijd en Personen, "
        "dan bullets met de ingrediënten, dan steps met de bereiding. Footer: bron. keep_seconds 1800."
    )
    try:
        card = await assistant.ask(query, [])
    except Exception as e:
        log.warning("dinner suggestion failed: %s", e)
        return
    if not card.get("blocks"):
        log.warning("dinner suggestion came back empty: %s", card.get("title"))
        return
    _save(card)
