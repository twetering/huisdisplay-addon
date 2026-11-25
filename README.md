# Huisdisplay add-on for Home Assistant

Hub for the Huisdisplay: a 4.2" e-paper living-room screen (Zectrix Note4,
ESP32-S3) with custom firmware. The hub renders every page as a ready-made
1-bit frame (time-of-day home page, weather and rain radar, trains, family
calendar, house status, waste collection, Strava) and answers push-to-talk
questions with Claude as generative cards.

## Install

1. Settings → Add-ons → Add-on store → ⋮ → Repositories, add
   `https://github.com/twetering/huisdisplay-addon`.
2. Install **Huisdisplay**, fill in the settings (API keys, station, postcode),
   start it.
3. Point the display at `http://<home-assistant-ip>:8787` (setup portal on the
   display, or the `hub=` serial command).

See [huisdisplay/DOCS.md](huisdisplay/DOCS.md) for every setting.

This repository is generated from a private project; changes are published
here as new add-on versions.
