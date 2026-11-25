"""Settings for the hub.

Locally they come from display/hub/.env (and the parent project .env for HA_URL/HA_TOKEN).
As a Home Assistant add-on they come from /data/options.json, and HA itself
is reached through the Supervisor proxy with SUPERVISOR_TOKEN.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

HUB_DIR = Path(__file__).resolve().parent.parent
load_dotenv(HUB_DIR / ".env")
load_dotenv(HUB_DIR.parent.parent / ".env")  # parent project .env: HA_URL, HA_TOKEN

_options: dict = {}
if Path("/data/options.json").exists():
    _options = json.loads(Path("/data/options.json").read_text())


def opt(name: str, default: str = "") -> str:
    v = _options.get(name.lower())
    if v not in (None, ""):
        return str(v)
    return os.environ.get(name.upper(), default)


@dataclass
class Settings:
    ha_url: str = field(default_factory=lambda: "http://supervisor/core" if os.environ.get("SUPERVISOR_TOKEN") else opt("HA_URL", "http://homeassistant.local:8123"))
    ha_token: str = field(default_factory=lambda: os.environ.get("SUPERVISOR_TOKEN") or opt("HA_TOKEN"))
    anthropic_api_key: str = field(default_factory=lambda: opt("ANTHROPIC_API_KEY"))
    claude_model: str = field(default_factory=lambda: opt("CLAUDE_MODEL", "claude-opus-5-5"))
    stt_provider: str = field(default_factory=lambda: opt("STT_PROVIDER", "elevenlabs"))
    elevenlabs_api_key: str = field(default_factory=lambda: opt("ELEVENLABS_API_KEY"))
    openai_api_key: str = field(default_factory=lambda: opt("OPENAI_API_KEY"))
    ns_api_key: str = field(default_factory=lambda: opt("NS_API_KEY"))
    place: str = field(default_factory=lambda: opt("PLACE"))  # town, for the assistant and web search
    ns_station: str = field(default_factory=lambda: opt("NS_STATION"))  # station code, e.g. UT
    ns_station_name: str = field(default_factory=lambda: opt("NS_STATION_NAME"))  # label for the station
    ns_to: str = field(default_factory=lambda: opt("NS_TO"))  # label for the destination
    ns_toward: str = field(default_factory=lambda: opt("NS_TOWARD"))  # direction/via stations, comma separated
    gcal_ics: list[str] = field(default_factory=lambda: [u.strip() for u in opt("GCAL_ICS").split(",") if u.strip()])
    postcode: str = field(default_factory=lambda: opt("POSTCODE"))
    housenumber: str = field(default_factory=lambda: opt("HOUSENUMBER"))
    lat: float | None = field(default_factory=lambda: float(opt("LAT")) if opt("LAT") else None)  # default: HA's home
    lon: float | None = field(default_factory=lambda: float(opt("LON")) if opt("LON") else None)
    weather_entity: str = field(default_factory=lambda: opt("WEATHER_ENTITY", "weather.forecast_home"))
    dinner_prefs: str = field(default_factory=lambda: opt("DINNER_PREFS", "gezin met een jong kind, afwisselend, gewone avondmaaltijd"))
    dinner_auto: bool = field(default_factory=lambda: opt("DINNER_AUTO", "false").lower() in ("1", "true", "yes", "ja"))
    reminders_list: str = field(default_factory=lambda: opt("REMINDERS_LIST", "todo.huishouden"))
    strava_client_id: str = field(default_factory=lambda: opt("STRAVA_CLIENT_ID"))
    strava_client_secret: str = field(default_factory=lambda: opt("STRAVA_CLIENT_SECRET"))
    shopping_list: str = field(default_factory=lambda: opt("SHOPPING_LIST", "todo.shopping_list"))
    tz: str = field(default_factory=lambda: opt("TZ", "Europe/Amsterdam"))
    hub_redirect: str = field(default_factory=lambda: opt("HUB_REDIRECT"))  # send displays to this hub (fw >= 0.1.4)
    port: int = field(default_factory=lambda: int(opt("PORT", "8787")))
    firmware_dir: Path = field(default_factory=lambda: Path(opt("FIRMWARE_DIR", str(HUB_DIR / "firmware"))))
    data_dir: Path = field(default_factory=lambda: Path("/data") if Path("/data/options.json").exists() else HUB_DIR / "data")


settings = Settings()
TO_SHORT = (settings.ns_to or "").replace(" Centraal", "").replace(" Centrum", "")
settings.data_dir.mkdir(parents=True, exist_ok=True)
