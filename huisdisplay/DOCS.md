# Huisdisplay

The hub talks to Home Assistant through the Supervisor, so no token is needed.
Leave a setting empty to switch that part off.

| Setting | What it does |
|---|---|
| `anthropic_api_key` | Claude, for voice questions and answer cards |
| `stt_provider` | Speech to text: `elevenlabs` (Scribe) or `openai` |
| `elevenlabs_api_key` / `openai_api_key` | Key for the chosen speech provider |
| `ns_api_key` | NS Reisinformatie key (free at apiportal.ns.nl) |
| `ns_station` | Departure station code, e.g. `UT` |
| `ns_station_name`, `ns_to` | Labels on the screen, e.g. `Utrecht` and `Amsterdam Centraal` |
| `ns_toward` | Only show trains whose direction or route contains one of these (comma separated) |
| `gcal_ics` | Secret iCal address(es) of Google Calendar, comma separated |
| `postcode`, `housenumber` | Waste collection calendar (Mijn Afvalwijzer) |
| `place` | Town name, used by the assistant and web search |
| `weather_entity` | Weather entity for forecasts |
| `shopping_list`, `reminders_list` | To-do lists for groceries and dated reminders |
| `dinner_auto`, `dinner_prefs` | Let Claude suggest a recipe every afternoon, and for whom |
| `strava_client_id`, `strava_client_secret` | Optional Strava app (callback domain: your Home Assistant IP); connect from the Huisdisplay panel |
| `birthdays` | `Name|YYYY-MM-DD`, comma separated: countdown 30 days before, a party on the day |
| `countdowns` | `emoji Name|MM-DD|days`, comma separated: e.g. `🎁 Pakjesavond|12-05|21` |

The rain radar uses the home location from Home Assistant.

The **Huisdisplay** panel in the sidebar shows the display's status, every data source, and live previews of all pages and card types. Previews and the automation API (`/api/card`, `/api/page`) only answer Home Assistant itself; the display needs nothing but its frame, voice and firmware endpoints.

The add-on also keeps `binary_sensor.huisdisplay_online`, `sensor.huisdisplay_battery`, `sensor.huisdisplay_last_seen`, `sensor.huisdisplay_page` and `sensor.huisdisplay_firmware` up to date, for dashboards and automations. Firmware updates for the display
are served from this add-on: the display installs them by itself.
