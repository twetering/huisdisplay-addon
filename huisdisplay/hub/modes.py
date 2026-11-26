"""Time-of-day modes: what the 'Nu' page leads with and the page order.

ochtend  weekdays 06:00-09:30 (weekend 07:00-10:30): trains, waste, today's agenda
dag      until 16:30: agenda, weather, house
koken    16:30-19:30: dinner suggestion + shopping list
avond    19:30-23:00: tomorrow (agenda, weather, waste), is the house closed up
nacht    23:00-06:00: same as avond, refreshes less often

Rain overrides everything: when buienradar sees rain in the next 2 hours the
rain strip appears on 'Nu' and the weather page moves up in the rotation.
"""

from __future__ import annotations

import datetime as dt

MODES = ("ochtend", "dag", "koken", "avond", "nacht")
TITLES = {"ochtend": "Goedemorgen", "dag": "Nu", "koken": "Koken", "avond": "Morgen", "nacht": "Welterusten"}


def is_workday(d: dt.date) -> bool:
    return d.weekday() < 5


def mode_at(t: dt.datetime) -> str:
    m = t.hour * 60 + t.minute
    start, end = (6 * 60, 9 * 60 + 30) if is_workday(t.date()) else (7 * 60, 10 * 60 + 30)
    if start <= m < end:
        return "ochtend"
    if m < start or m >= 23 * 60:
        return "nacht"
    if m < 16 * 60 + 30:
        return "dag"
    if m < 19 * 60 + 30:
        return "koken"
    return "avond"


def rotation(mode: str, t: dt.datetime, raining: bool = False) -> list[str]:
    if mode == "ochtend" and is_workday(t.date()):
        order = ["home", "trein", "nieuws", "agenda", "weer", "afval", "huis", "pokemon"]
    elif mode == "ochtend":
        order = ["home", "nieuws", "agenda", "weer", "schaak", "pokemon", "kunst", "huis", "afval", "trein"]
    elif mode == "dag":
        order = ["home", "agenda", "nieuws", "weer", "kunst", "pokemon", "schaak", "huis", "afval", "trein"]
    elif mode == "koken":
        order = ["home", "agenda", "pokemon", "schaak", "huis", "weer", "kunst", "afval", "nieuws", "trein"]
    else:
        order = ["home", "agenda", "afval", "huis", "schaak", "kunst", "weer", "pokemon", "nieuws", "trein"]
    if raining:
        order.remove("weer")
        order.insert(1, "weer")
    return order
