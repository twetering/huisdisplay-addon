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
| `chime_volume` | Sound for important moments, 0 (off) to 3 (loud): rain coming, a reminder due, waste tonight, a party morning, or a card from an automation with `"chime": "alert"` |
| `quiet_start`, `quiet_end` | No chimes in between (alerts from automations still sound) |
| `speak_answers`, `tts_voice` | Say answers out loud (ElevenLabs voice id) |
| `announce_delays`, `announcer_voice` | Weekday mornings: a station gong and an announcement when a train within 45 minutes is 5+ minutes late or cancelled |
| `podcasts` | `Name|feed-url`, comma separated: newest episodes on the news page |
| `news_feed` | RSS feed for the headlines (default: NOS) |
| `countdowns` | `emoji Name|MM-DD|days`, comma separated: e.g. `🎁 Pakjesavond|12-05|21` |

The rain radar uses the home location from Home Assistant.

The **Huisdisplay** panel in the sidebar shows the display's status, every data source, and live previews of all pages and card types. Previews and the automation API (`/api/card`, `/api/page`) only answer Home Assistant itself; the display needs nothing but its frame, voice and firmware endpoints.

The add-on also keeps `binary_sensor.huisdisplay_online`, `sensor.huisdisplay_battery`, `sensor.huisdisplay_last_seen`, `sensor.huisdisplay_page` and `sensor.huisdisplay_firmware` up to date, for dashboards and automations. Firmware updates for the display
are served from this add-on: the display installs them by itself.

## Intercom

Let the display say something from anywhere in Home Assistant (a script, an automation, a dashboard button):

```yaml
action: hassio.addon_stdin
data:
  addon: 0cda7abf_huisdisplay
  input:
    say: "Het eten is klaar!"
    from: zolder        # optional, shown on the card
    chime: ding         # optional: ding, soft, alert, party
```

`input` can also carry `card` (a card like the assistant makes) or `page`. On USB the display
checks every 10 seconds; on battery the message waits until it wakes.
