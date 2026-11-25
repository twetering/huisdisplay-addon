"""Hub HTTP server.

Device API
  GET  /api/frame?page=&nav=prev|next|ok   -> raw frame (headers describe it)
  POST /api/voice                          -> raw PCM in, answer frame out
  GET  /api/firmware.bin                   -> OTA image (version in X-Firmware)
Automation API (from Home Assistant)
  POST /api/card      {card JSON}          -> show a card on all displays
  POST /api/page      {"page": "afval"}    -> switch page
Developer
  GET  /                                   -> previews of every page
  GET  /preview/{page}.png
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse

from . import dinner, pages, sources, strava
from .card import paginate, render_card
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hub")
app = FastAPI(title="Huisdisplay hub")

CARD_TTL = 300  # seconds an answer stays on screen before going back to "Nu"


@dataclass
class Device:
    id: str
    page: str = "home"
    card: dict | None = None
    card_screen: int = 0
    card_until: float = 0
    battery: int | None = None
    usb: bool = True
    fw: str = ""
    last_seen: float = 0
    history: list = field(default_factory=list)  # recent assistant turns for follow-up questions


devices: dict[str, Device] = {}


def device_from(req: Request) -> Device:
    did = req.headers.get("X-Device", "preview")
    d = devices.setdefault(did, Device(did))
    b = req.headers.get("X-Battery", "")
    if b:
        try:
            d.battery = int(b.split(",")[0])
        except ValueError:
            pass
    d.usb = req.headers.get("X-Power", "usb") == "usb"
    d.fw = req.headers.get("X-Fw", d.fw)
    d.last_seen = time.time()
    return d


async def _background():
    """Keep the rain cache warm (it drives the page order) and make the dinner suggestion."""
    while True:
        try:
            await sources.rain()
            dinner.ensure()
        except Exception:
            log.exception("background loop")
        await asyncio.sleep(300)


@app.on_event("startup")
async def _startup():
    asyncio.create_task(_background())


def firmware_version() -> str:
    f = settings.firmware_dir / "version.txt"
    return f.read_text().strip() if f.exists() else ""


async def render_for(d: Device, page: str):
    ctx = pages.Ctx(battery=d.battery, usb=d.usb, page=page)
    if page == "answer" and d.card:
        c = render_card(d.card, d.card_screen, lambda cv: pages.header(cv, ctx, d.card.get("header", "Antwoord")))
        remaining = max(10, int(d.card_until - time.time()))
        return c, remaining
    fn = pages.PAGES.get(page, pages.page_home)
    try:
        return await fn(ctx)
    except Exception as e:  # never leave the panel on a stack trace
        log.exception("page %s failed", page)
        return await pages.page_message(ctx, pages.TITLES.get(page, page), f"Deze pagina gaf een fout: {e}")


def navigate(d: Device, nav: str):
    if d.page == "answer":
        if d.card and time.time() > d.card_until:
            d.page, d.card = "home", None
        elif nav == "ok" and d.card:
            n = len(paginate(d.card))
            if d.card_screen < n - 1:
                d.card_screen += 1
                d.card_until = time.time() + CARD_TTL
            else:
                d.page, d.card = "home", None
            return
        elif nav in ("next", "prev"):
            d.page, d.card = "home", None
            return
    order = pages.rotation()
    if d.page not in order and d.page != "answer":
        d.page = "home"
    if nav in ("next", "prev"):
        i = order.index(d.page) if d.page in order else 0
        d.page = order[(i + (1 if nav == "next" else -1)) % len(order)]
    elif nav == "ok":
        if d.page == "home" and pages.current_mode() == "koken" and (today := dinner.today()):
            show_card(d, today["card"])  # OK in cooking mode opens tonight's recipe
            return
        sources.invalidate("")  # OK on a normal page = refresh everything now
        d.page = d.page if d.page in order else "home"


def frame_response(canvas, next_s: int, d: Device, page: str, inm: str | None = None, extra: bytes = b"",
                   extra_headers: dict | None = None) -> Response:
    data = canvas.to_4bpp() if canvas.gray else canvas.to_1bpp()
    etag = '"' + hashlib.sha1(data).hexdigest()[:16] + '"'
    headers = {
        "X-Format": "4bpp" if canvas.gray else "1bpp",
        "X-Next": str(max(5, next_s or 60)),
        "X-Page": page,
        "ETag": etag,
        "Cache-Control": "no-store",
    }
    fw = firmware_version()
    if fw:
        headers["X-Firmware"] = fw
    if settings.hub_redirect:
        headers["X-Hub-Url"] = settings.hub_redirect
    if extra_headers:
        headers.update(extra_headers)
    if inm and inm == etag and not extra:
        return Response(status_code=304, headers=headers)
    return Response(content=data + extra, media_type="application/octet-stream", headers=headers)


@app.get("/api/frame")
async def api_frame(req: Request, page: str = "home", nav: str = ""):
    d = device_from(req)
    if page in ("listening", "thinking"):
        c, n = await render_for(d, page)
        return frame_response(c, 60, d, d.page)
    if page and page not in ("answer",) and not nav and d.page != "answer":
        d.page = page if page in pages.PAGES else d.page
    if d.page == "answer" and d.card and time.time() > d.card_until:
        d.page, d.card = "home", None
    if nav:
        navigate(d, nav)
    c, n = await render_for(d, d.page)
    return frame_response(c, n, d, d.page, None if nav else req.headers.get("If-None-Match"))


@app.post("/api/voice")
async def api_voice(req: Request):
    d = device_from(req)
    pcm = await req.body()
    from . import assistant  # imported lazily: optional dependencies
    card, audio = await assistant.handle_voice(pcm, req.headers.get("X-Audio", ""), d)
    dinner.remember(card)
    show_card(d, card)
    c, n = await render_for(d, d.page)
    extra_headers = {"X-Audio-Bytes": str(len(audio))} if audio else None
    return frame_response(c, n, d, d.page, extra=audio or b"", extra_headers=extra_headers)


def show_card(d: Device, card: dict):
    if card.get("page") in pages.PAGES:
        d.page, d.card = card["page"], None
        return
    d.card = card
    d.card_screen = 0
    d.card_until = time.time() + card.get("keep_seconds", CARD_TTL)
    d.page = "answer"


@app.post("/api/card")
async def api_card(card: dict):
    for d in devices.values():
        show_card(d, card)
    return {"ok": True, "devices": len(devices)}


@app.post("/api/page")
async def api_page(body: dict):
    for d in devices.values():
        d.page, d.card = body.get("page", "home"), None
    return {"ok": True}


@app.get("/strava", response_class=HTMLResponse)
async def strava_page(req: Request):
    if not strava.configured():
        body = ("<p>Maak een app op <a href='https://www.strava.com/settings/api'>strava.com/settings/api</a> "
                "(Authorization Callback Domain: <code>" + (req.url.hostname or "localhost") + "</code>) en zet "
                "STRAVA_CLIENT_ID en STRAVA_CLIENT_SECRET in de hub-instellingen. Herstart de hub en kom hier terug.</p>")
    else:
        url = strava.authorize_url(str(req.url_for("strava_callback")))
        state = "Gekoppeld. Opnieuw koppelen kan altijd." if strava.connected() else "Nog niet gekoppeld."
        body = f"<p>{state}</p><p><a href='{url}'><b>Koppel met Strava</b></a></p>"
    return f"<!doctype html><title>Strava</title><style>body{{font:16px system-ui;margin:40px;max-width:560px}}</style><h2>Strava</h2>{body}"


@app.get("/strava/callback", response_class=HTMLResponse)
async def strava_callback(code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return f"<p>Niet gekoppeld: {error or 'geen code'}</p>"
    try:
        who = await strava.finish_login(code, state)
    except Exception as e:
        log.warning("strava login failed: %s", e)
        return f"<p>Koppelen mislukt: {e}</p>"
    sources.invalidate("strava")
    return f"<!doctype html><style>body{{font:16px system-ui;margin:40px}}</style><h2>Gekoppeld met Strava</h2><p>Hoi {who}! De pagina Sport staat nu op het display.</p>"


@app.get("/api/firmware.bin")
async def api_firmware():
    f = settings.firmware_dir / "firmware.bin"
    if not f.exists():
        return Response(status_code=404)
    return Response(content=f.read_bytes(), media_type="application/octet-stream")


@app.get("/api/devices")
async def api_devices():
    return [{"id": d.id, "page": d.page, "battery": d.battery, "usb": d.usb, "fw": d.fw,
             "seen_s_ago": round(time.time() - d.last_seen)} for d in devices.values()]


@app.get("/preview/{page}.png")
async def preview(page: str, screen: int = 0, battery: int = 80, usb: bool = True, at: str = "", day: str = ""):
    """Preview a page; ?at=07:30 (and ?day=2026-11-28) pretend it's another time."""
    if at or day:
        import datetime as dt
        n = sources.real_now()
        if day:
            n = n.replace(year=int(day[:4]), month=int(day[5:7]), day=int(day[8:10]))
        if at:
            n = n.replace(hour=int(at[:2]), minute=int(at[3:5]))
        sources.set_now(n)
    d = Device("preview", battery=battery, usb=usb)
    if page == "answer":
        d.card = _demo_card
        d.card_screen = screen
        d.card_until = time.time() + 60
    c, _ = await render_for(d, page)
    return Response(content=c.preview_png(2), media_type="image/png")


@app.get("/", response_class=HTMLResponse)
async def index():
    t = int(time.time())
    fig = lambda q, cap: f"<figure><img src='/preview/{q}&t={t}' width=400><figcaption>{cap}</figcaption></figure>"
    modes_row = "".join(fig(f"home.png?at={at}", f"Nu om {at}") for at in ("07:30", "11:00", "17:30", "21:00"))
    names = pages.ROTATION + ["sport", "answer", "listening", "thinking"]
    imgs = modes_row + "".join(fig(f"{p}.png?", p) for p in names)
    return f"""<!doctype html><title>Huisdisplay hub</title><meta name=viewport content='width=device-width'>
<style>body{{font:14px system-ui;margin:20px;background:#ddd}}figure{{display:inline-block;margin:8px}}img{{background:#fff;border-radius:6px;image-rendering:pixelated}}</style>
<h2>Huisdisplay hub</h2>{imgs}"""


_demo_card = {
    "query": "welke wijn past bij paddenstoelenrisotto?",
    "kicker": "Wijn",
    "title": "Een aardse rode of een romige witte",
    "accent": "aardse",
    "blocks": [{"type": "rows", "rows": [
        {"label": "Pinot Noir", "value": "aards, zachte tannine"},
        {"label": "Chardonnay", "value": "rijk, past bij de boter"},
        {"label": "Nebbiolo", "value": "houdt van paddenstoelen"}]}],
    "footer": "Tip: schenk de Pinot licht gekoeld, 14°",
}


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
