"""Sound the hub sends with a frame: intercom messages and the station announcer.

The firmware plays raw 16 kHz mono PCM that follows the frame (X-Audio-Bytes),
so everything here produces bytes in that format.
"""

from __future__ import annotations

import datetime as dt
import logging
import math

import numpy as np

from . import sources as src
from .config import settings

log = logging.getLogger("hub.audio")
RATE = 16000


def _bell(freq: float, secs: float, amp: float = 0.32) -> np.ndarray:
    """A soft station-bell tone: fundamental plus a few partials, quick attack, long decay."""
    t = np.arange(int(RATE * secs)) / RATE
    env = np.minimum(t / 0.008, 1) * np.exp(-t * 3.2)
    wave = (np.sin(2 * math.pi * freq * t) + 0.35 * np.sin(2 * math.pi * freq * 2.01 * t)
            + 0.12 * np.sin(2 * math.pi * freq * 3.02 * t))
    return wave * env * amp


def station_gong() -> bytes:
    """Three descending bell notes (our own, in the spirit of a station announcement)."""
    notes = [(784, 0.55), (659, 0.55), (523, 1.1)]  # G5 E5 C5
    gap = np.zeros(int(RATE * 0.04))
    sig = np.concatenate([np.concatenate([_bell(f, d), gap]) for f, d in notes] + [np.zeros(int(RATE * 0.25))])
    return (np.clip(sig, -1, 1) * 32767).astype("<i2").tobytes()


async def tts(text: str, voice: str | None = None, max_chars: int = 400) -> bytes | None:
    if not (settings.elevenlabs_api_key and text):
        return None
    try:
        r = await src._client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice or settings.tts_voice}",
            params={"output_format": "pcm_16000"}, headers={"xi-api-key": settings.elevenlabs_api_key},
            json={"text": text[:max_chars], "model_id": "eleven_flash_v2_5", "language_code": "nl"}, timeout=20)
        r.raise_for_status()
        return r.content
    except Exception as e:
        log.warning("TTS failed: %s", e)
        return None


def _say_time(t: dt.datetime) -> str:
    return f"{t.hour} uur {t.minute:02d}" if t.minute else f"{t.hour} uur"


async def train_announcement(device) -> tuple[bytes, dict] | None:
    """Weekday mornings: announce a delay (5+ min) or cancellation of a train leaving within 45 min,
    once per train, like on the platform. Returns (pcm, card) or None."""
    n = src.now()
    if not settings.announce_delays or n.weekday() >= 5 or not (6 <= n.hour < 10):
        return None
    data = src.peek("trains")
    if not data or data.get("error"):
        return None
    for d in data["departures"]:
        if not (n < d["planned"] <= n + dt.timedelta(minutes=45)):
            continue
        if not (d["cancelled"] or d["delay"] >= 5):
            continue
        key = f"train:{d['planned']:%Y%m%d%H%M}:{'x' if d['cancelled'] else d['delay'] // 5}"
        if key in device.chimed:
            continue
        device.chimed.add(key)
        what = f"De {d['type'].lower()} naar {d['direction']} van {_say_time(d['planned'])}"
        if d["cancelled"]:
            text = f"Attentie. {what} rijdt vandaag niet. Excuses voor het ongemak."
            title = f"{d['planned']:%H:%M} rijdt niet"
        else:
            text = (f"Attentie. {what} heeft ongeveer {d['delay']} minuten vertraging. "
                    f"Verwachte vertrektijd {_say_time(d['actual'])}, spoor {d['track']}.")
            title = f"{d['planned']:%H:%M} heeft +{d['delay']} min"
        speech = await tts(text, settings.announcer_voice)
        card = {"kicker": "Omroep", "title": title, "sticker": "🚆",
                "blocks": [{"type": "text", "text": text}], "keep_seconds": 300}
        return station_gong() + (speech or b""), card
    return None
