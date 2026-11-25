"""When the display should make a sound (X-Chime header; firmware 0.1.5+).

Only for things worth looking up for, each at most once, never in quiet hours:
  ding   rain starts within 20 minutes, or a timed reminder is due now
  soft   the evening before a waste collection (18:00-21:00)
  party  the first refresh on a birthday or pakjesavond morning
  alert  a card pushed from Home Assistant with "chime": "alert" (doorbell, washer...)
"""

from __future__ import annotations

import datetime as dt

from . import fun
from . import sources as src
from .config import settings

AMP = {0: 0, 1: 1500, 2: 3500, 3: 7000}


def quiet(t: dt.datetime) -> bool:
    def hm(s: str) -> int:
        h, m = (int(v) for v in s.split(":"))
        return h * 60 + m
    try:
        a, b = hm(settings.quiet_start), hm(settings.quiet_end)
    except ValueError:
        return False
    m = t.hour * 60 + t.minute
    return m >= a or m < b if a > b else a <= m < b


def _first(device, key: str) -> bool:
    """True the first time this event is seen for this device."""
    if key in device.chimed:
        return False
    device.chimed.add(key)
    if len(device.chimed) > 200:
        device.chimed = set(sorted(device.chimed)[-100:])
    return True


async def decide(device) -> str | None:
    """The chime to play with this frame, as 'name;amplitude', or None."""
    amp = AMP.get(settings.chime_volume, 3500)
    if not amp:
        device.pending_chime = None
        return None
    n = src.now()
    pending, device.pending_chime = device.pending_chime, None
    if pending and (pending == "alert" or not quiet(n)):
        return f"{pending};{amp}"
    if quiet(n):
        return None
    sp = fun.today_special(n.date())
    if sp and _first(device, f"party:{n.date()}"):
        return f"party;{amp}"
    pts = src.peek("rain") or []
    rs = src.rain_summary(pts) if pts else {}
    if rs.get("rain") and n + dt.timedelta(minutes=2) < rs["start"] <= n + dt.timedelta(minutes=20) \
            and _first(device, f"rain:{rs['start']:%Y%m%d%H}"):
        return f"ding;{amp}"
    for r in src.peek("ha:reminders") or []:
        if r["timed"] and r["due"] and abs((r["due"] - n).total_seconds()) < 300 and _first(device, f"rem:{r['uid']}"):
            return f"ding;{amp}"
    if 18 <= n.hour < 21:
        tomorrow = n.date() + dt.timedelta(days=1)
        for w in src.peek("waste") or []:
            if w["date"] == tomorrow and _first(device, f"waste:{tomorrow}"):
                return f"soft;{amp}"
    return None


def night_wait(t: dt.datetime) -> int | None:
    """On battery at night (22:00 until the morning mode starts): sleep through instead of
    waking every 15 minutes. Returns seconds to sleep, or None during the day."""
    def wake(d: dt.date) -> dt.time:
        return dt.time(6, 0) if d.weekday() < 5 else dt.time(7, 0)
    if t.hour >= 22:
        day = t.date() + dt.timedelta(days=1)
    elif t.time() < wake(t.date()):
        day = t.date()
    else:
        return None
    target = dt.datetime.combine(day, wake(day), t.tzinfo)
    return max(900, int((target - t).total_seconds()))
