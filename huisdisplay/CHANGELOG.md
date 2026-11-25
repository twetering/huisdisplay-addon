# Changelog

## 0.3.0
- Huisdisplay panel in the Home Assistant sidebar: display status, data sources, live previews.
- Home Assistant entities for online state, battery, last seen, page and firmware.
- New card blocks: countdown, bars, quote, progress, sticker, emoji_row; emoji everywhere (Noto Emoji).
- Countdowns (pakjesavond, Kerst, birthdays) on the home page; a party on the day itself.
- Little touches: cat ears while listening, paw prints while thinking, seasonal marks in the header.
- Security: previews and automation API only for Home Assistant; voice questions rate-limited.

## 0.2.2
- Fix voice questions (numpy was missing).
- No more request URLs in the log (the calendar address is secret).

## 0.2.1
- Display firmware 0.1.4: hubs can hand a display over to another hub, and it never downgrades.
- House page skips unavailable devices.

## 0.2.0
- First add-on release: time-of-day home page, rain only when it rains,
  trains, calendar, house, waste, reminders, packages, Strava, voice with Claude.
