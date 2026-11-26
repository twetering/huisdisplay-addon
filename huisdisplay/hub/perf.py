"""Performance bookkeeping: how long each page takes to render on the hub, how long the
display takes to fetch and draw it, and whether the event loop ever gets blocked.

Everything here is cheap (a few numbers per page) and shows up in the panel, in
/api/perf and in the HA sensor `sensor.huisdisplay_render`.

Budgets (on the HA Green; a Mac is ~4x faster):
  render  < 300 ms per page  (warning in the log above SLOW_MS)
  loop    never blocked > 1 s (a blocked loop delays every display and the announcer)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field

log = logging.getLogger("hub.perf")
SLOW_MS = 800        # log a warning when one render takes longer than this
LOOP_WARN_S = 1.0    # log a warning when the event loop was blocked this long


@dataclass
class Stat:
    n: int = 0
    last: float = 0.0
    total: float = 0.0
    worst: float = 0.0
    slow: int = 0
    recent: deque = field(default_factory=lambda: deque(maxlen=50))

    def add(self, ms: float):
        self.n += 1
        self.last = ms
        self.total += ms
        self.worst = max(self.worst, ms)
        self.recent.append(ms)
        if ms > SLOW_MS:
            self.slow += 1

    def p95(self) -> float:
        r = sorted(self.recent)
        return r[min(len(r) - 1, int(len(r) * 0.95))] if r else 0.0

    def row(self) -> dict:
        return {"n": self.n, "last_ms": round(self.last), "avg_ms": round(self.total / self.n) if self.n else 0,
                "p95_ms": round(self.p95()), "max_ms": round(self.worst), "slow": self.slow}


render: dict[str, Stat] = {}     # hub side, per page
device: dict[str, Stat] = {}     # display side (request -> drawn), per page
loop_lag = Stat()                # how late the watchdog woke up
events: deque = deque(maxlen=30)  # recent notable events, newest last
started = time.time()


def note(kind: str, text: str):
    events.append({"t": time.time(), "kind": kind, "text": text})


def record_render(page: str, ms: float):
    render.setdefault(page, Stat()).add(ms)
    if ms > SLOW_MS:
        log.warning("slow render: %s took %.0f ms", page, ms)
        note("render", f"{page} {ms:.0f} ms")


def record_device(page: str, header: str):
    """X-Timing from the display: '<page>,<http_ms>,<draw_ms>,<missed>,<heap_kb>' of its previous frame."""
    try:
        pg, http_ms, draw_ms, *rest = header.split(",")
        total = float(http_ms) + float(draw_ms)
    except ValueError:
        return
    device.setdefault(pg or page, Stat()).add(total)
    if float(http_ms) > 3000:
        log.warning("display waited %s ms for %s", http_ms, pg)
        note("display", f"{pg} wachtte {http_ms} ms op de hub")


async def watchdog():
    """Sleep 0.5 s at a time; waking up late means something blocked the event loop."""
    while True:
        t = time.monotonic()
        await asyncio.sleep(0.5)
        lag = time.monotonic() - t - 0.5
        loop_lag.add(lag * 1000)
        if lag > LOOP_WARN_S:
            log.warning("event loop blocked for %.1f s", lag)
            note("loop", f"geblokkeerd {lag:.1f} s")


def memory_mb() -> float:
    try:
        import resource
        import sys
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return rss / (1024 * 1024 if sys.platform == "darwin" else 1024)
    except Exception:
        return 0.0


def snapshot() -> dict:
    return {"uptime_s": round(time.time() - started), "memory_mb": round(memory_mb()),
            "loop_lag_max_ms": round(loop_lag.worst), "loop_lag_p95_ms": round(loop_lag.p95()),
            "render": {k: v.row() for k, v in sorted(render.items())},
            "device": {k: v.row() for k, v in sorted(device.items())},
            "events": list(events)}
