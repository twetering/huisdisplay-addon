"""Strava: your own API application + a one-time login in the browser.

Setup: create an app at https://www.strava.com/settings/api (Authorization
Callback Domain: 'localhost' during development, the hub's IP later), put
STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET in the settings, then open
http://<hub>:8787/strava and click connect. Tokens live in data/strava.json
and are refreshed automatically.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import secrets
import time

from . import sources as src
from .config import settings

log = logging.getLogger("hub.strava")
FILE = settings.data_dir / "strava.json"
API = "https://www.strava.com/api/v3"
_states: set[str] = set()  # CSRF state values for the login round-trip

KIND_NL = {"Ride": "fietsrit", "VirtualRide": "virtuele rit", "EBikeRide": "e-bikerit", "GravelRide": "gravelrit",
           "MountainBikeRide": "MTB-rit", "Run": "hardlopen", "TrailRun": "trailrun", "VirtualRun": "loopband",
           "Walk": "wandeling", "Hike": "hike", "Swim": "zwemmen", "WeightTraining": "kracht",
           "Workout": "workout", "Yoga": "yoga", "Rowing": "roeien", "NordicSki": "langlaufen"}


def configured() -> bool:
    return bool(settings.strava_client_id and settings.strava_client_secret)


def connected() -> bool:
    return configured() and FILE.exists()


def authorize_url(redirect_uri: str) -> str:
    state = secrets.token_urlsafe(16)
    _states.add(state)
    from urllib.parse import urlencode
    return "https://www.strava.com/oauth/authorize?" + urlencode({
        "client_id": settings.strava_client_id, "response_type": "code", "redirect_uri": redirect_uri,
        "approval_prompt": "auto", "scope": "read,activity:read_all", "state": state})


async def finish_login(code: str, state: str) -> str:
    if state not in _states:
        raise ValueError("onbekende login-poging, begin opnieuw")
    _states.discard(state)
    r = await src._client.post("https://www.strava.com/oauth/token", data={
        "client_id": settings.strava_client_id, "client_secret": settings.strava_client_secret,
        "code": code, "grant_type": "authorization_code"})
    r.raise_for_status()
    tok = r.json()
    _save(tok)
    a = tok.get("athlete") or {}
    return f"{a.get('firstname', '')} {a.get('lastname', '')}".strip()


def _save(tok: dict):
    FILE.write_text(json.dumps({k: tok[k] for k in ("access_token", "refresh_token", "expires_at") if k in tok}))
    FILE.chmod(0o600)


async def _token() -> str:
    tok = json.loads(FILE.read_text())
    if tok["expires_at"] < time.time() + 120:
        r = await src._client.post("https://www.strava.com/oauth/token", data={
            "client_id": settings.strava_client_id, "client_secret": settings.strava_client_secret,
            "grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
        r.raise_for_status()
        tok = r.json()
        _save(tok)
    return tok["access_token"]


def week_start(t: dt.datetime) -> dt.datetime:
    return (t - dt.timedelta(days=t.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


async def summary() -> dict | None:
    """This week per day, last activity, weekly streak (from the last 12 weeks)."""
    if not connected():
        return None

    async def f():
        n = src.real_now()
        after = int((week_start(n) - dt.timedelta(weeks=11)).timestamp())
        r = await src._client.get(f"{API}/athlete/activities", params={"after": after, "per_page": 200},
                                  headers={"Authorization": f"Bearer {await _token()}"})
        r.raise_for_status()
        acts = []
        for a in r.json():
            start = dt.datetime.fromisoformat(a["start_date"].replace("Z", "+00:00")).astimezone(src.TZ)
            kind = a.get("sport_type") or a.get("type", "")
            acts.append({"name": a.get("name", ""), "kind": kind, "kind_nl": KIND_NL.get(kind, kind.lower()),
                         "start": start, "km": round(a.get("distance", 0) / 1000, 1),
                         "minutes": round(a.get("moving_time", 0) / 60), "elev": round(a.get("total_elevation_gain", 0)),
                         "kmh": round(a.get("average_speed", 0) * 3.6, 1)})
        acts.sort(key=lambda a: a["start"])
        ws = week_start(n)
        week = [a for a in acts if a["start"] >= ws]
        days = [{"km": 0.0, "minutes": 0} for _ in range(7)]
        for a in week:
            d = days[a["start"].weekday()]
            d["km"] += a["km"]
            d["minutes"] += a["minutes"]
        weeks_active = {week_start(a["start"]).date() for a in acts}
        streak, w = 0, ws.date()
        if w not in weeks_active:  # this week not started yet: count from last week
            w -= dt.timedelta(weeks=1)
        while w in weeks_active:
            streak += 1
            w -= dt.timedelta(weeks=1)
        last4 = [sum(a["minutes"] for a in acts if week_start(a["start"]).date() == (ws - dt.timedelta(weeks=k)).date())
                 for k in range(1, 5)]
        return {"week": {"km": round(sum(a["km"] for a in week), 1), "minutes": sum(a["minutes"] for a in week),
                         "count": len(week), "days": days},
                "avg4_minutes": round(sum(last4) / 4), "streak_weeks": streak,
                "last": acts[-1] if acts else None, "recent": acts[-10:]}
    return await src.cached("strava", 900, f)
