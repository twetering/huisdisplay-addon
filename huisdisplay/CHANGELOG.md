# Changelog

## 0.6.2
- Announcer voice settings: stability and similarity (defaults 0.2 / 0.95, good for cloned voices).

## 0.6.1
- Upload your own announcement jingle (WAV) from the panel.

## 0.6.0
- Chess position of the day: openings, traps and mini-games to set up and play from.
- Air-quality alert on the home page with a soft chime (fine dust, humidity, or the air-quality sensor).
- Sunrise and sunset on the weather page.
- Intercom form and quick buttons in the Huisdisplay panel, plus an announcer demo button.
- Announcer: every delay from 1 minute (setting), own jingle from /share/huisdisplay/jingle.wav, broadcaster voice.

## 0.5.0
- Intercom: `hassio.addon_stdin` (or `/api/say`) makes the display speak a message.
- Station announcer: gong + announcement for morning train delays and cancellations.
- New pages: Nieuws (NOS headlines + newest podcast episodes), Kunst (generative art of the day),
  Pokémon of the day (dithered artwork and a Dutch fact for kids).
- On USB the display checks every 10 seconds.

## 0.4.1
- Spoken answers kept to two short sentences.

## 0.4.0
- Display firmware 0.1.5: chimes, the green LED only lights during updates, hold DOWN to switch off also on USB.
- Chimes for rain coming, reminders, waste tonight, party mornings and automation cards (`"chime": "alert"`), with quiet hours.
- Answers are spoken out loud (ElevenLabs); switch off with `speak_answers`.
- On battery the display sleeps through the night and wakes fresh for the morning.

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
