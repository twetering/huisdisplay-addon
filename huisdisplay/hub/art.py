"""Generative art of the day: one of six algorithms, seeded by the date, drawn for 1-bit e-paper."""

from __future__ import annotations

import datetime as dt
import math
import random

import numpy as np
from PIL import Image, ImageDraw

W, H = 400, 278  # leaves a caption line at the bottom


def _noise(rng: random.Random, octaves=((5, 4, 1.0), (10, 8, 0.5), (20, 15, 0.25))) -> np.ndarray:
    """Smooth value noise in [0, 1]: random low-res grids upscaled bicubically and summed."""
    acc = np.zeros((H, W))
    total = 0.0
    for gx, gy, amp in octaves:
        small = np.array([[rng.random() for _ in range(gx)] for _ in range(gy)], dtype=np.float32)
        big = Image.fromarray(small * 255).convert("F").resize((W, H), Image.BICUBIC)
        acc += np.asarray(big) / 255 * amp
        total += amp
    acc /= total
    return (acc - acc.min()) / (np.ptp(acc) or 1)


def flow(rng):
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    field = _noise(rng) * math.tau * 2
    for _ in range(700):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        pts = [(x, y)]
        for _ in range(rng.randint(15, 45)):
            a = field[int(y) % H, int(x) % W]
            x, y = x + math.cos(a) * 3, y + math.sin(a) * 3
            if not (0 <= x < W and 0 <= y < H):
                break
            pts.append((x, y))
        if len(pts) > 3:
            d.line(pts, fill=0, width=1)
    return img, "Stroomveld"


def truchet(rng):
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    s = rng.choice((18, 22, 26))
    for gy in range(-1, H // s + 2):
        for gx in range(-1, W // s + 2):
            x, y = gx * s, gy * s
            r = s // 2
            if rng.random() < 0.5:
                d.arc((x - r, y - r, x + r, y + r), 0, 90, fill=0, width=3)
                d.arc((x + s - r, y + s - r, x + s + r, y + s + r), 180, 270, fill=0, width=3)
            else:
                d.arc((x + s - r, y - r, x + s + r, y + r), 90, 180, fill=0, width=3)
                d.arc((x - r, y + s - r, x + r, y + s + r), 270, 360, fill=0, width=3)
    return img, "Truchet-tegels"


def circles(rng):
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    placed: list[tuple[float, float, float]] = []
    for _ in range(4000):
        x, y, r = rng.uniform(0, W), rng.uniform(0, H), rng.uniform(3, 46)
        if any((x - a) ** 2 + (y - b) ** 2 < (r + c + 2) ** 2 for a, b, c in placed):
            continue
        placed.append((x, y, r))
        style = rng.random()
        if style < 0.25:
            d.ellipse((x - r, y - r, x + r, y + r), fill=0)
        elif style < 0.7:
            for k in range(int(r), 0, -4):
                d.ellipse((x - k, y - k, x + k, y + k), outline=0, width=1)
        else:
            d.ellipse((x - r, y - r, x + r, y + r), outline=0, width=2)
    return img, "Cirkelpakking"


def contours(rng):
    h = _noise(rng)
    bands = np.floor(h * rng.choice((14, 18, 22))).astype(int)
    edge = (bands != np.roll(bands, 1, 0)) | (bands != np.roll(bands, 1, 1))
    edge[0, :] = edge[:, 0] = False
    arr = np.where(edge, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "L"), "Hoogtelijnen"


def ridges(rng):
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    n = 44
    bumps = [(rng.uniform(140, 260), rng.uniform(15, 40), rng.uniform(0.4, 1)) for _ in range(5)]
    for i in range(n):
        base = 30 + i * (H - 40) / n
        pts = []
        for x in range(0, W + 1, 4):
            y = base
            for cx, wdt, amp in bumps:
                y -= amp * 70 * math.exp(-((x - cx) / wdt) ** 2) * (0.5 + rng.random() * 0.5) * (1 - abs(i - n / 2) / n)
            y -= rng.random() * 2
            pts.append((x, y))
        d.polygon(pts + [(W, H), (0, H)], fill=255)  # hide the lines behind
        d.line(pts, fill=0, width=2)
    return img, "Golven"


def dither_sun(rng):
    yy, xx = np.mgrid[0:H, 0:W].astype(float)
    cx, cy, r = rng.uniform(120, 280), rng.uniform(70, 120), rng.uniform(40, 60)
    horizon = H * 0.64
    glow = np.clip(1 - np.hypot(xx - cx, yy - cy) / (r * 2.6), 0, 1) ** 1.5
    disc = np.hypot(xx - cx, yy - cy) < r
    sky = 0.12 + 0.55 * (yy / horizon) + 0.6 * glow
    # sea: dark water with a broken reflection of the sun under it
    ripple = 0.5 + 0.5 * np.sin(yy * 1.7 + np.sin(xx * 0.05) * 2)
    refl = np.clip(1 - np.abs(xx - cx) / (r * (0.6 + (yy - horizon) / H)), 0, 1) * ripple
    sea = 0.15 + 0.15 * (yy - horizon) / H + 0.8 * refl
    v = np.where(yy < horizon, np.where(disc, 1.0, sky), sea)
    img = Image.fromarray(np.clip(v * 255, 0, 255).astype(np.uint8), "L").convert("1").convert("L")
    return img, "Zonsondergang (dither)"


ALGOS = [flow, truchet, circles, contours, ridges, dither_sun]


_today: dict[dt.date, tuple[Image.Image, str, int]] = {}


def of_the_day(day: dt.date) -> tuple[Image.Image, str, int]:
    """Generate (slow: up to seconds on the HA Green). Prefer `today()` from async code."""
    n = day.toordinal()
    rng = random.Random(n)
    img, name = ALGOS[n % len(ALGOS)](rng)
    return img, name, n % 1000


async def today(day: dt.date) -> tuple[Image.Image, str, int]:
    """Cached per day and generated in a worker thread, so the event loop never waits on it."""
    import asyncio
    if day not in _today:
        res = await asyncio.to_thread(of_the_day, day)
        _today.clear()
        _today[day] = res
    return _today[day]
