"""Data sources. Each fetcher is cached for a sensible time, and returns plain
dicts/lists so pages and the assistant can both use them. Failures return
None (pages show a quiet placeholder rather than crashing)."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import httpx

from .config import settings

log = logging.getLogger("hub.sources")
TZ = ZoneInfo(settings.tz)
_client = httpx.AsyncClient(timeout=15, headers={"User-Agent": "huisdisplay/0.1"})
_cache: dict[str, tuple[float, object]] = {}
_locks: dict[str, asyncio.Lock] = {}


_now_override: ContextVar[dt.datetime | None] = ContextVar("now_override", default=None)


def real_now() -> dt.datetime:
    return dt.datetime.now(TZ)


def now() -> dt.datetime:
    """Current time; previews can pretend it's another time of day (set_now)."""
    return _now_override.get() or real_now()


def set_now(t: dt.datetime | None) -> None:
    _now_override.set(t)


async def cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        try:
            val = await fn()
        except Exception as e:  # keep serving stale data on errors
            log.warning("%s failed: %s", key, e)
            return hit[1] if hit else None
        _cache[key] = (time.time(), val)
        return val


def peek(key: str):
    """Last cached value without fetching (for sync code like the page order)."""
    hit = _cache.get(key)
    return hit[1] if hit else None


def invalidate(prefix: str) -> None:
    for k in list(_cache):
        if k.startswith(prefix):
            del _cache[k]


# ------------------------------------------------------------------ Home Assistant
def _ha_headers():
    return {"Authorization": f"Bearer {settings.ha_token}", "Content-Type": "application/json"}


async def ha_states() -> dict[str, dict]:
    async def f():
        r = await _client.get(f"{settings.ha_url}/api/states", headers=_ha_headers())
        r.raise_for_status()
        return {e["entity_id"]: e for e in r.json()}
    return await cached("ha:states", 20, f) or {}


async def ha_call(domain: str, service: str, data: dict, return_response: bool = False):
    url = f"{settings.ha_url}/api/services/{domain}/{service}"
    if return_response:
        url += "?return_response"
    r = await _client.post(url, headers=_ha_headers(), json=data)
    r.raise_for_status()
    if not return_response:  # a write: re-read states and lists next time
        invalidate("ha:states")
        invalidate("ha:shopping")
        invalidate("ha:reminders")
    return r.json()


async def todo_items(entity: str) -> list[dict]:
    res = await ha_call("todo", "get_items", {"entity_id": entity, "status": "needs_action"}, True)
    return res["service_response"][entity]["items"]


def _parse_due(v) -> dt.datetime | None:
    if not v:
        return None
    try:
        if len(v) == 10:
            return dt.datetime.combine(dt.date.fromisoformat(v), dt.time(0), TZ)
        return dt.datetime.fromisoformat(v).astimezone(TZ)
    except ValueError:
        return None


async def reminders() -> list[dict]:
    """Open items on the household to-do list: {uid, summary, due (datetime|None), timed}."""
    async def f():
        out = []
        for it in await todo_items(settings.reminders_list):
            due = it.get("due")
            out.append({"uid": it.get("uid"), "summary": it.get("summary", ""), "due": _parse_due(due),
                        "timed": bool(due and len(due) > 10), "description": it.get("description", "")})
        return sorted(out, key=lambda r: (r["due"] is None, r["due"] or now()))
    return await cached("ha:reminders", 60, f) or []


async def packages() -> list[dict]:
    """Parcels on their way, from the PostNL integration (HACS: arjenbos/ha-postnl).

    Its sensors carry 'enroute'/'delivered' lists; the 'distribution' one is for
    parcels you send, so it's skipped."""
    states = await ha_states()
    out = []
    for eid, e in states.items():
        a = e.get("attributes", {})
        if not eid.startswith("sensor.") or not isinstance(a.get("enroute"), list) or eid.endswith("distribution"):
            continue
        for p in a["enroute"]:
            start = _parse_due(p.get("expected_from") or p.get("planned_from") or p.get("expected_datetime") or p.get("planned_date"))
            end = _parse_due(p.get("expected_to") or p.get("planned_to"))
            out.append({"carrier": "PostNL", "name": p.get("name", ""), "status": p.get("status_message", ""),
                        "start": start, "end": end, "delivered": False})
        today = now().date()
        for p in a.get("delivered") or []:
            d = _parse_due(p.get("delivery_date"))
            if d and d.date() == today:
                out.append({"carrier": "PostNL", "name": p.get("name", ""), "status": "bezorgd",
                            "start": d, "end": None, "delivered": True})
    return sorted(out, key=lambda p: p["start"] or now() + dt.timedelta(days=30))


async def shopping() -> list[str]:
    async def f():
        res = await ha_call("todo", "get_items", {"entity_id": settings.shopping_list, "status": "needs_action"}, True)
        return [i["summary"] for i in res["service_response"][settings.shopping_list]["items"]]
    return await cached("ha:shopping", 60, f) or []


async def ha_forecast(kind: str = "hourly") -> list[dict]:
    async def f():
        res = await ha_call("weather", "get_forecasts", {"entity_id": settings.weather_entity, "type": kind}, True)
        return res["service_response"][settings.weather_entity]["forecast"]
    return await cached(f"ha:forecast:{kind}", 900, f) or []


def state_val(states: dict, eid: str, default=None):
    e = states.get(eid)
    if not e or e["state"] in ("unknown", "unavailable"):
        return default
    return e["state"]


async def home_location() -> tuple[float, float]:
    """LAT/LON from the settings, else the home location configured in Home Assistant."""
    if settings.lat is not None and settings.lon is not None:
        return settings.lat, settings.lon

    async def f():
        r = await _client.get(f"{settings.ha_url}/api/config", headers=_ha_headers())
        r.raise_for_status()
        j = r.json()
        return j["latitude"], j["longitude"]
    return await cached("ha:location", 86400, f) or (52.09, 5.12)


# ------------------------------------------------------------------ Buienradar
@dataclass
class RainPoint:
    time: dt.datetime
    mm: float  # mm/h


async def rain() -> list[RainPoint]:
    """Precipitation forecast for the next 2 hours in 5-minute steps."""
    async def f():
        lat, lon = await home_location()
        r = await _client.get("https://gpsgadget.buienradar.nl/data/raintext",
                              params={"lat": f"{lat:.2f}", "lon": f"{lon:.2f}"})
        r.raise_for_status()
        pts = []
        base = real_now()
        for line in r.text.strip().splitlines():
            v, hhmm = line.split("|")
            h, m = map(int, hhmm.strip().split(":"))
            t = base.replace(hour=h, minute=m, second=0, microsecond=0)
            if t < base - dt.timedelta(hours=1):
                t += dt.timedelta(days=1)
            v = int(v)
            mm = 10 ** ((v - 109) / 32) if v > 0 else 0.0
            pts.append(RainPoint(t, round(mm, 2)))
        return pts
    return await cached("rain", 300, f) or []


def rain_summary(pts: list[RainPoint]) -> dict:
    """Headline like 'Regen 13:10–13:55' or 'Droog tot 11:30'."""
    if not pts:
        return {"headline": "Geen buiendata", "rain": False}
    wet = [p for p in pts if p.mm >= 0.1]
    if not wet:
        return {"headline": "Droog, komende 2 uur", "short": "Droog", "rain": False}
    start = wet[0].time
    end = start
    for p in pts[pts.index(wet[0]):]:
        if p.mm < 0.1:
            break
        end = p.time
    peak = max(p.mm for p in wet)
    kind = "Lichte regen" if peak < 1 else ("Regen" if peak < 4 else "Flinke buien")
    if start <= now() + dt.timedelta(minutes=5):
        head = f"{kind} tot {end:%H:%M}" if end < pts[-1].time else f"{kind}, aanhoudend"
    else:
        head = f"{kind} {start:%H:%M}–{end:%H:%M}"
    return {"headline": head, "short": f"{kind.split()[0] if kind != 'Regen' else 'Regen'} {start:%H:%M}", "rain": True,
            "start": start, "end": end, "peak": peak}


# ------------------------------------------------------------------ NS
async def trains() -> dict | None:
    if not settings.ns_api_key:
        return {"error": "Geen NS API-key ingesteld"}
    if not settings.ns_station:
        return {"error": "Geen vertrekstation ingesteld"}

    async def f():
        r = await _client.get("https://gateway.apiportal.ns.nl/reisinformatie-api/api/v2/departures",
                              params={"station": settings.ns_station, "maxJourneys": 25},
                              headers={"Ocp-Apim-Subscription-Key": settings.ns_api_key})
        r.raise_for_status()
        out = []
        for d in r.json()["payload"]["departures"]:
            route = [s.get("mediumName", "") for s in d.get("routeStations", [])]
            # NS lists only a few stations along the way, so match direction OR any via-station.
            toward = [t.strip().lower() for t in settings.ns_toward.split(",") if t.strip()]
            hay = [d.get("direction", "").lower()] + [s.lower() for s in route]
            if toward and not any(t in h for t in toward for h in hay):
                continue
            planned = dt.datetime.fromisoformat(d["plannedDateTime"]).astimezone(TZ)
            actual = dt.datetime.fromisoformat(d.get("actualDateTime", d["plannedDateTime"])).astimezone(TZ)
            out.append({
                "planned": planned, "actual": actual,
                "delay": max(0, round((actual - planned).total_seconds() / 60)),
                "track": d.get("actualTrack") or d.get("plannedTrack", ""),
                "track_changed": bool(d.get("actualTrack") and d.get("actualTrack") != d.get("plannedTrack")),
                "direction": d.get("direction", ""),
                "type": d.get("product", {}).get("longCategoryName", d.get("trainCategory", "")),
                "cancelled": bool(d.get("cancelled")),
                "messages": [m.get("message", "") for m in d.get("messages", []) if m.get("message")],
            })
        dis = []
        try:
            r2 = await _client.get("https://gateway.apiportal.ns.nl/reisinformatie-api/api/v3/disruptions/station/" + settings.ns_station,
                                   headers={"Ocp-Apim-Subscription-Key": settings.ns_api_key})
            if r2.status_code == 200:
                for x in r2.json():
                    dis.append(x.get("title") or x.get("titleSections", [[{}]])[0][0].get("value", ""))
        except Exception:
            pass
        return {"departures": out, "disruptions": [d for d in dis if d]}
    return await cached("trains", 60, f)


# ------------------------------------------------------------------ Afval
WASTE_NAMES = {
    "gft": "GFT", "restafval": "Restafval", "papier": "Papier", "pmd": "PMD",
    "takken": "Snoeiafval", "milieubus": "Milieubus", "kerstbomen": "Kerstbomen",
}


async def waste() -> list[dict]:
    if not (settings.postcode and settings.housenumber):
        return []

    async def f():
        r = await _client.get("https://api.mijnafvalwijzer.nl/webservices/appsinput/", params={
            "apikey": "5ef443e778f41c4f75c69459eea6e6ae0c2d92de729aa0fc61653815fbd6a8ca",
            "method": "postcodecheck", "postcode": settings.postcode, "street": "",
            "huisnummer": settings.housenumber, "toevoeging": "", "app_name": "afvalwijzer",
            "platform": "web", "afvaldata": real_now().date().isoformat(), "langs": "nl"})
        r.raise_for_status()
        d = r.json()
        items = d["ophaaldagen"]["data"] + d.get("ophaaldagenNext", {}).get("data", [])
        today = real_now().date()
        out = []
        for x in items:
            day = dt.date.fromisoformat(x["date"])
            if day >= today and x["type"] in WASTE_NAMES:
                out.append({"date": day, "type": x["type"], "name": WASTE_NAMES[x["type"]]})
        return sorted(out, key=lambda x: x["date"])
    return await cached("waste", 6 * 3600, f) or []


# ------------------------------------------------------------------ Agenda
async def calendar(days: int = 7) -> list[dict]:
    if not settings.gcal_ics:
        return []
    import icalendar
    import recurring_ical_events

    async def f():
        start = real_now().replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + dt.timedelta(days=days)
        events = []
        for url in settings.gcal_ics:
            r = await _client.get(url)
            r.raise_for_status()
            cal = icalendar.Calendar.from_ical(r.content)
            for ev in recurring_ical_events.of(cal).between(start, end):
                s = ev.get("DTSTART").dt
                e = ev.get("DTEND").dt if ev.get("DTEND") else s
                allday = not isinstance(s, dt.datetime)
                if allday:
                    s = dt.datetime.combine(s, dt.time(0), TZ)
                    e = dt.datetime.combine(e, dt.time(0), TZ)
                else:
                    s, e = s.astimezone(TZ), e.astimezone(TZ)
                events.append({"title": str(ev.get("SUMMARY", "")), "start": s, "end": e,
                               "allday": allday, "location": str(ev.get("LOCATION", "") or "")})
        return sorted(events, key=lambda x: (x["start"], not x["allday"]))
    return await cached("calendar", 600, f) or []
