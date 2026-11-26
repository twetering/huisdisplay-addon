"""Sound the hub sends with a frame: intercom messages and the station announcer.

The firmware plays raw 16 kHz mono PCM that follows the frame (X-Audio-Bytes),
so everything here produces bytes in that format.
"""

from __future__ import annotations

import datetime as dt
import logging
import math

import numpy as np
from pathlib import Path

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


JINGLE_PATHS = [Path("/share/huisdisplay/jingle.wav"), settings.data_dir / "jingle.wav"]


def _load_wav(path: Path) -> bytes | None:
    """Any PCM WAV -> 16 kHz mono s16le (what the firmware plays)."""
    import wave
    try:
        with wave.open(str(path)) as w:
            ch, rate, width, frames = w.getnchannels(), w.getframerate(), w.getsampwidth(), w.readframes(w.getnframes())
    except Exception as e:
        log.warning("jingle %s unreadable: %s", path, e)
        return None
    if width != 2:
        log.warning("jingle %s: only 16-bit WAV is supported", path)
        return None
    a = np.frombuffer(frames, "<i2").astype(np.float32)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    if rate != RATE:
        x = np.linspace(0, len(a) - 1, int(len(a) * RATE / rate))
        a = np.interp(x, np.arange(len(a)), a)
    return np.clip(a, -32768, 32767).astype("<i2").tobytes()


def station_gong() -> bytes:
    """The jingle before an announcement: your own WAV (/share/huisdisplay/jingle.wav) if present,
    otherwise three descending bell notes of our own."""
    for pth in JINGLE_PATHS:
        if pth.exists() and (pcm := _load_wav(pth)):
            return pcm
    notes = [(784, 0.55), (659, 0.55), (523, 1.1)]  # G5 E5 C5
    gap = np.zeros(int(RATE * 0.04))
    sig = np.concatenate([np.concatenate([_bell(f, d), gap]) for f, d in notes] + [np.zeros(int(RATE * 0.25))])
    return (np.clip(sig, -1, 1) * 32767).astype("<i2").tobytes()


async def tts(text: str, voice: str | None = None, max_chars: int = 400, settings_: dict | None = None) -> bytes | None:
    if not (settings.elevenlabs_api_key and text):
        return None
    try:
        r = await src._client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice or settings.tts_voice}",
            params={"output_format": "pcm_16000"}, headers={"xi-api-key": settings.elevenlabs_api_key},
            json={"text": text[:max_chars], "model_id": "eleven_flash_v2_5", "language_code": "nl",
                  **({"voice_settings": settings_} if settings_ else {})}, timeout=20)
        r.raise_for_status()
        return r.content
    except Exception as e:
        log.warning("TTS failed: %s", e)
        return None


def announcer_settings() -> dict:
    return {"stability": settings.announcer_stability, "similarity_boost": settings.announcer_similarity}


def _say_time(t: dt.datetime) -> str:
    return f"{t.hour} uur {t.minute:02d}" if t.minute else f"{t.hour} uur"


async def train_announcement(device) -> tuple[bytes, dict] | None:
    """Weekday mornings: announce a delay or cancellation of a train leaving within 45 min,
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
        if not (d["cancelled"] or d["delay"] >= settings.announce_min_delay):
            continue
        # once per train, and again only if the delay grows by a few minutes
        key = f"train:{d['planned']:%Y%m%d%H%M}:{'x' if d['cancelled'] else d['delay'] // 3}"
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
        speech = await tts(text, settings.announcer_voice, settings_=announcer_settings())
        card = {"kicker": "Omroep", "title": title, "sticker": "🚆",
                "blocks": [{"type": "text", "text": text}], "keep_seconds": 300}
        return station_gong() + (speech or b""), card
    return None


async def demo_announcement() -> tuple[bytes, dict]:
    """A sample announcement to hear what it sounds like."""
    text = ("Attentie. De sprinter naar Utrecht Centraal van 7 uur 41 heeft ongeveer 4 minuten vertraging. "
            "Verwachte vertrektijd 7 uur 45, spoor 1.")
    speech = await tts(text, settings.announcer_voice, settings_=announcer_settings())
    card = {"kicker": "Omroep · voorbeeld", "title": "07:41 heeft +4 min", "sticker": "🚆",
            "blocks": [{"type": "text", "text": text}], "keep_seconds": 120}
    return station_gong() + (speech or b""), card
