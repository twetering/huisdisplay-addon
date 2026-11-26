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
import collections
import datetime as dt
import hashlib
import html
import ipaddress
import logging
import os
import time
from dataclasses import dataclass, field

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse

from . import audio, chime, dinner, pages, sources, strava
from .card import paginate, render_card
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hub")
# httpx logs full URLs at INFO, including the secret calendar address: keep it quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)
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
    ip: str = ""
    host: str = ""
    chimed: set = field(default_factory=set)  # events this display already chimed for
    pending_chime: str | None = None          # asked for by a pushed card
    pending_audio: bytes | None = None        # intercom message or announcement, sent with the next frame
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
    d.ip = req.client.host if req.client else ""
    if d.id not in ("preview", "test"):
        d.host = req.headers.get("host", "")  # how the display reaches us: also the LAN address for links
    return d


# Who may see previews and push cards: this machine, and Home Assistant itself
# (core + ingress live on the Supervisor network). Displays only need /api/frame,
# /api/voice and /api/firmware.bin.
_TRUSTED = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "::1/128", "172.30.32.0/23")]


def trusted(req: Request) -> bool:
    try:
        ip = ipaddress.ip_address(req.client.host if req.client else "")
    except ValueError:
        return False
    return any(ip in n for n in _TRUSTED)


def forbidden() -> Response:
    return HTMLResponse("<p style='font:16px system-ui;margin:40px'>Open het Huisdisplay via Home Assistant "
                        "(zijbalk → Huisdisplay).</p>", status_code=403)


def online(d: Device) -> bool:
    return time.time() - d.last_seen < (180 if d.usb else 1900)  # one missed poll is fine


def real_devices() -> list[Device]:
    return [d for d in devices.values() if d.id not in ("preview", "test")]


async def _publish_to_ha():
    """Mirror the display's state into Home Assistant entities (only when running as the add-on)."""
    devs = sorted(real_devices(), key=lambda d: d.last_seen, reverse=True)
    if not devs or not os.environ.get("SUPERVISOR_TOKEN"):
        return
    d = devs[0]
    seen = dt.datetime.fromtimestamp(d.last_seen, dt.timezone.utc).isoformat()
    ents = {
        "binary_sensor.huisdisplay_online": ("on" if online(d) else "off",
                                             {"device_class": "connectivity", "friendly_name": "Huisdisplay online"}),
        "sensor.huisdisplay_battery": (d.battery if d.battery is not None else "unknown",
                                       {"device_class": "battery", "unit_of_measurement": "%", "state_class": "measurement",
                                        "friendly_name": "Huisdisplay batterij"}),
        "sensor.huisdisplay_last_seen": (seen, {"device_class": "timestamp", "friendly_name": "Huisdisplay laatst gezien"}),
        "sensor.huisdisplay_page": (d.page, {"friendly_name": "Huisdisplay pagina", "icon": "mdi:tablet"}),
        "sensor.huisdisplay_firmware": (d.fw or "unknown", {"friendly_name": "Huisdisplay firmware", "icon": "mdi:chip",
                                                             "power": "usb" if d.usb else "accu"}),
    }
    for eid, (state, attrs) in ents.items():
        await sources._client.post(f"{settings.ha_url}/api/states/{eid}", headers=sources._ha_headers(),
                                   json={"state": state, "attributes": attrs})


_last_ns_check = 0.0


async def _announcer():
    """Weekday mornings: fetch NS departures every minute, whatever page the display shows,
    and queue an announcement for each display. USB displays pick it up within 10 s."""
    global _last_ns_check
    if not audio.in_window(sources.now()) or time.time() - _last_ns_check < settings.announce_interval * 60 - 5:
        return
    _last_ns_check = time.time()
    await sources.trains()  # refreshes the 60 s cache
    for d in real_devices():
        if d.pending_audio is None and (ann := await audio.train_announcement(d)):
            show_card(d, ann[1])
            d.pending_audio = ann[0]
            log.info("announcement queued for %s: %s", d.id, ann[1]["title"])


async def _background():
    """Every minute: NS announcer (mornings) and mirror the display into HA.
    Every 5 minutes: warm the rain cache (it drives the page order) and the dinner suggestion."""
    tick = 0
    while True:
        for job in (_announcer, _publish_to_ha) + ((sources.rain, dinner.ensure) if tick % 5 == 0 else ()):
            try:
                r = job()
                if asyncio.iscoroutine(r):
                    await r
            except Exception:
                log.exception("background job %s", getattr(job, "__name__", job))
        tick += 1
        await asyncio.sleep(60)


async def handle_message(msg) -> int:
    """A message from Home Assistant (add-on stdin, or POST /api/say):
    "text"  or  {"say": "...", "from": "zolder", "card": {...}, "page": "...", "chime": "ding"}."""
    if isinstance(msg, str):
        msg = {"say": msg}
    targets = real_devices() or list(devices.values())
    if msg.get("demo") == "omroep":
        pcm, card = await audio.demo_announcement()
        for d in targets:
            show_card(d, card)
            d.pending_audio = pcm
        return len(targets)
    if msg.get("page"):
        for d in targets:
            d.page, d.card = msg["page"], None
    if msg.get("card"):
        for d in targets:
            show_card(d, msg["card"])
    text = (msg.get("say") or "").strip()
    if text:
        sender = (msg.get("from") or "").strip()
        pcm = await audio.tts(text, msg.get("voice"))
        card = {"kicker": f"Intercom{' · ' + sender if sender else ''}", "title": text, "sticker": "📢",
                "blocks": [], "keep_seconds": 180}
        if len(text) > 60:  # long message: short title, full text below
            card["title"], card["blocks"] = f"Bericht{' van ' + sender if sender else ''}", [{"type": "text", "text": text}]
        for d in targets:
            show_card(d, card)
            d.pending_chime = msg.get("chime", "ding")
            d.pending_audio = pcm
        log.info("intercom to %d display(s): %s", len(targets), text[:60])
    elif msg.get("chime"):
        for d in targets:
            d.pending_chime = msg["chime"]
    return len(targets)


async def _stdin_reader():
    """hassio.addon_stdin delivers one JSON value per line on stdin."""
    import json
    import sys
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return  # stdin closed
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            msg = line
        try:
            await handle_message(msg)
        except Exception:
            log.exception("stdin message failed")


@app.on_event("startup")
async def _startup():
    asyncio.create_task(_background())
    if os.environ.get("SUPERVISOR_TOKEN"):
        asyncio.create_task(_stdin_reader())


@app.post("/api/jingle")
async def api_jingle(req: Request):
    """Upload your own announcement jingle (16-bit WAV) from the panel."""
    if not trusted(req):
        return forbidden()
    data = await req.body()
    if not data:
        (settings.data_dir / "jingle.wav").unlink(missing_ok=True)
        return {"ok": True, "jingle": "standaard"}
    if len(data) > 3_000_000 or data[:4] != b"RIFF":
        return Response("Alleen WAV-bestanden tot 3 MB", status_code=400)
    tmp = settings.data_dir / "jingle.tmp.wav"
    tmp.write_bytes(data)
    if not audio._load_wav(tmp):
        tmp.unlink()
        return Response("Dit WAV-bestand kan ik niet lezen (16-bit PCM nodig)", status_code=400)
    tmp.replace(settings.data_dir / "jingle.wav")
    return {"ok": True, "jingle": "eigen"}


@app.post("/api/say")
async def api_say(req: Request, body: dict):
    if not trusted(req):
        return forbidden()
    return {"ok": True, "devices": await handle_message(body)}


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
    real = d.id not in ("preview", "test")
    c, n = await render_for(d, d.page)
    if real and d.usb:
        n = min(n, 10)  # check often on USB: intercom messages arrive within seconds (unchanged = 304)
    if not d.usb and not nav and (night := chime.night_wait(sources.now())):
        n = night  # on battery: sleep through the night, the morning page will be fresh
    extra = {}
    if real and (ch := await chime.decide(d)):
        extra["X-Chime"] = ch
    sound = b""
    if real and d.pending_audio:
        sound, d.pending_audio = d.pending_audio, None
        extra["X-Audio-Bytes"] = str(len(sound))
    return frame_response(c, n, d, d.page, None if (nav or extra) else req.headers.get("If-None-Match"),
                          extra=sound, extra_headers=extra or None)


@app.post("/api/voice")
async def api_voice(req: Request):
    d = device_from(req)
    pcm = await req.body()
    # Anyone on the wifi can reach this endpoint: cap the cost of a runaway client.
    now = time.time()
    while _voice_times and now - _voice_times[0] > 600:
        _voice_times.popleft()
    if len(_voice_times) >= 20:
        log.warning("voice rate limit hit from %s", d.ip)
        show_card(d, {"title": "Even pauze", "sticker": "⏳",
                      "blocks": [{"type": "text", "text": "Al heel veel vragen gesteld. Probeer het over een paar minuten weer."}],
                      "keep_seconds": 60})
        c, n = await render_for(d, d.page)
        return frame_response(c, n, d, d.page, extra=b"")
    _voice_times.append(now)
    from . import assistant  # imported lazily: optional dependencies
    card, audio = await assistant.handle_voice(pcm, req.headers.get("X-Audio", ""), d)
    dinner.remember(card)
    show_card(d, card)
    c, n = await render_for(d, d.page)
    extra_headers = {"X-Audio-Bytes": str(len(audio))} if audio else None
    return frame_response(c, n, d, d.page, extra=audio or b"", extra_headers=extra_headers)


_voice_times: collections.deque = collections.deque()


def show_card(d: Device, card: dict):
    if card.get("chime") in ("ding", "alert", "party", "soft"):
        d.pending_chime = card["chime"]
    if card.get("page") in pages.PAGES:
        d.page, d.card = card["page"], None
        return
    d.card = card
    d.card_screen = 0
    d.card_until = time.time() + card.get("keep_seconds", CARD_TTL)
    d.page = "answer"


@app.post("/api/card")
async def api_card(req: Request, card: dict):
    if not trusted(req):
        return forbidden()
    for d in real_devices() or devices.values():
        show_card(d, card)
    return {"ok": True, "devices": len(devices)}


@app.post("/api/page")
async def api_page(req: Request, body: dict):
    if not trusted(req):
        return forbidden()
    for d in devices.values():
        d.page, d.card = body.get("page", "home"), None
    return {"ok": True}


def lan_base(req: Request) -> str:
    """The hub's address as the display uses it (ingress requests come in on an internal one)."""
    host = next((d.host for d in real_devices() if getattr(d, "host", "")), "") or req.headers.get("host", "")
    return f"http://{host}" if host else ""


@app.get("/strava", response_class=HTMLResponse)
async def strava_page(req: Request):
    host = req.url.hostname or "localhost"
    if not strava.configured():
        body = ("<p>Maak een app op <a href='https://www.strava.com/settings/api'>strava.com/settings/api</a> "
                f"(Authorization Callback Domain: <code>{html.escape(host)}</code>) en vul "
                "<code>strava_client_id</code> en <code>strava_client_secret</code> in bij de add-on-instellingen.</p>")
    else:
        url = strava.authorize_url(str(req.url_for("strava_callback")))
        state = "Gekoppeld. Opnieuw koppelen kan altijd." if strava.connected() else "Nog niet gekoppeld."
        body = (f"<p>{state}</p><p><a class=btn href='{html.escape(url)}'>Koppel met Strava</a></p>"
                f"<p class=muted>Lukt het niet (<i>redirect_uri invalid</i>)? Zet in je Strava-app bij "
                f"<a href='https://www.strava.com/settings/api'>strava.com/settings/api</a> het "
                f"<b>Authorization Callback Domain</b> op <code>{html.escape(host)}</code>.</p>")
    return f"""<!doctype html><meta name=viewport content='width=device-width'><title>Strava</title>
<style>body{{font:16px/1.5 system-ui;margin:40px auto;max-width:560px;padding:0 16px}}.btn{{display:inline-block;background:#fc4c02;color:#fff;
padding:10px 16px;border-radius:8px;text-decoration:none;font-weight:600}}.muted{{color:#666;font-size:14px}}code{{background:#eee;padding:1px 5px;border-radius:4px}}</style>
<h2>Strava koppelen</h2>{body}"""


@app.get("/strava/callback", response_class=HTMLResponse)
async def strava_callback(code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return f"<p>Niet gekoppeld: {html.escape(error or 'geen code')}</p>"
    try:
        who = await strava.finish_login(code, state)
    except Exception as e:
        log.warning("strava login failed: %s", e)
        return f"<p>Koppelen mislukt: {html.escape(str(e))}</p>"
    sources.invalidate("strava")
    return f"<!doctype html><style>body{{font:16px system-ui;margin:40px}}</style><h2>Gekoppeld met Strava</h2><p>Hoi {html.escape(who)}! De pagina Sport staat nu op het display.</p>"


@app.get("/api/firmware.bin")
async def api_firmware():
    f = settings.firmware_dir / "firmware.bin"
    if not f.exists():
        return Response(status_code=404)
    return Response(content=f.read_bytes(), media_type="application/octet-stream")


@app.get("/api/devices")
async def api_devices(req: Request):
    if not trusted(req):
        return forbidden()
    return [{"id": d.id, "page": d.page, "battery": d.battery, "usb": d.usb, "fw": d.fw, "ip": d.ip,
             "online": online(d), "seen_s_ago": round(time.time() - d.last_seen)} for d in real_devices()]


@app.get("/preview/{page}.png")
async def preview(req: Request, page: str, screen: int = 0, battery: int = 80, usb: bool = True, at: str = "",
                  day: str = "", card: str = ""):
    """Preview a page; ?at=07:30 (and ?day=2026-11-28) pretend it's another time; ?card= a demo card."""
    if not trusted(req):
        return forbidden()
    if at or day:
        n = sources.real_now()
        if day:
            n = n.replace(year=int(day[:4]), month=int(day[5:7]), day=int(day[8:10]))
        if at:
            n = n.replace(hour=int(at[:2]), minute=int(at[3:5]))
        sources.set_now(n)
    d = Device("preview", battery=battery, usb=usb)
    if page == "answer":
        d.card = DEMO_CARDS.get(card, _demo_card)
        d.card_screen = screen
        d.card_until = time.time() + 60
    c, _ = await render_for(d, page)
    return Response(content=c.preview_png(2), media_type="image/png")


def _ago(t: float) -> str:
    s = int(time.time() - t)
    return f"{s} s" if s < 90 else f"{s // 60} min" if s < 5400 else f"{s // 3600} u"


SOURCE_NAMES = {"ha:states": "Home Assistant", "ha:forecast:hourly": "Weer (uur)", "ha:forecast:daily": "Weer (dag)",
                "rain": "Buienradar", "trains": "NS", "waste": "Afvalkalender", "calendar": "Google Agenda",
                "ha:shopping": "Boodschappenlijst", "ha:reminders": "Herinneringen", "strava": "Strava",
                "ha:location": "Locatie (HA)"}


@app.get("/", response_class=HTMLResponse)
async def index(req: Request):
    """Control panel: shown in the Home Assistant sidebar through ingress (relative URLs!)."""
    if not trusted(req):
        return forbidden()
    t = int(time.time())
    img = lambda q, cap, cls="": (f"<figure class='{cls}'><img loading=lazy src='preview/{q}&t={t}' alt=''>"
                                  f"<figcaption>{html.escape(cap)}</figcaption></figure>")
    devs = real_devices()
    dev_rows = "".join(
        f"<tr><td><span class='dot {'ok' if online(d) else 'bad'}'></span>{'online' if online(d) else 'offline'}</td>"
        f"<td>{d.battery if d.battery is not None else '–'}%{' ⚡' if d.usb else ''}</td><td>{html.escape(d.fw or '–')}</td>"
        f"<td>{html.escape(pages.TITLES.get(d.page, d.page))}</td><td>{_ago(d.last_seen)} geleden</td>"
        f"<td class=muted>{html.escape(d.ip)}</td></tr>" for d in devs) or \
        "<tr><td colspan=6 class=muted>Nog geen display gezien sinds de start van de hub.</td></tr>"
    src_rows = "".join(
        f"<tr><td><span class='dot {'ok' if h['ok'] else 'bad'}'></span>{html.escape(SOURCE_NAMES.get(k, k))}</td>"
        f"<td>{_ago(h['t'])} geleden</td><td class=muted>{html.escape(h['error'])}</td></tr>"
        for k, h in sorted(sources.health.items(), key=lambda kv: (kv[1]['ok'], SOURCE_NAMES.get(kv[0], kv[0]))))
    order = pages.rotation()
    day_imgs = "".join(img(f"home.png?at={a}", f"{lbl} · {a}") for a, lbl in
                       (("07:30", "Ochtend"), ("11:00", "Dag"), ("17:30", "Koken"), ("21:00", "Avond")))
    page_imgs = "".join(img(f"{p}.png?", pages.TITLES.get(p, p)) for p in order if p != "home")
    card_imgs = "".join(img(f"answer.png?card={k}", v.get("kicker") or v["title"]) for k, v in DEMO_CARDS.items())
    voice_imgs = img("listening.png?", "Ik luister") + img("thinking.png?", "Even denken")
    strava_state = "gekoppeld" if strava.connected() else ("klaar om te koppelen" if strava.configured() else "niet ingesteld")
    lan = lan_base(req)
    strava_link = f"<a href='{html.escape(lan)}/strava' target=_blank rel=noopener>Strava koppelen ↗</a>" if lan else ""
    return f"""<!doctype html><html lang=nl><meta charset=utf-8><meta name=viewport content='width=device-width'>
<meta http-equiv=refresh content=120><title>Huisdisplay</title>
<style>
:root{{--bg:#f4f5f2;--card:#fff;--ink:#16181a;--muted:#6a6f6b;--line:#dfe2dc;--ok:#2e7d32;--bad:#c62828;--paper:#e6e6df}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111312;--card:#1b1d1c;--ink:#ecedea;--muted:#9aa09b;--line:#2c302d;--ok:#66bb6a;--bad:#ef5350}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,sans-serif;padding:20px max(16px,env(safe-area-inset-left))}}
h1{{font-size:22px;margin:0 0 2px}}h2{{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:28px 0 10px}}
.muted{{color:var(--muted)}}.top{{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px}}
.panel{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:6px 14px;overflow-x:auto}}
table{{border-collapse:collapse;width:100%}}td{{padding:8px 10px 8px 0;border-bottom:1px solid var(--line);white-space:nowrap}}tr:last-child td{{border:0}}
.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px}}.ok{{background:var(--ok)}}.bad{{background:var(--bad)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}}
figure{{margin:0}}img{{width:100%;aspect-ratio:4/3;display:block;background:var(--paper);border-radius:8px;border:1px solid var(--line);mix-blend-mode:normal}}
figcaption{{font-size:12px;color:var(--muted);margin-top:4px}}.cols{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
@media (max-width:760px){{.cols{{grid-template-columns:1fr}}}}a{{color:inherit}}
.chip{{padding:6px 11px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--ink);font:inherit;font-size:13px;cursor:pointer}}
.chip:hover,button:focus-visible{{border-color:var(--ink)}}
</style>
<div class=top><div><h1>Huisdisplay</h1><span class=muted>Hub {html.escape(firmware_version() and 'met firmware ' + firmware_version())} · modus {html.escape(pages.current_mode())} · Strava {strava_state}</span></div>
<div class=muted>{strava_link}</div></div>
{INTERCOM_HTML}
<div class=cols>
<div><h2>Display</h2><div class=panel><table>{dev_rows}</table></div></div>
<div><h2>Bronnen</h2><div class=panel><table>{src_rows or "<tr><td class=muted>Nog niets opgehaald.</td></tr>"}</table></div></div>
</div>
<h2>Nu, door de dag</h2><div class=grid>{day_imgs}</div>
<h2>Pagina's (in de volgorde van nu)</h2><div class=grid>{page_imgs}</div>
<h2>Kaartjes</h2><div class=grid>{card_imgs}</div>
<h2>Spraak</h2><div class=grid>{voice_imgs}</div>
<p class=muted style='margin-top:24px'>Previews tonen live data. Deze pagina ververst elke twee minuten.</p>"""


INTERCOM_CHIPS = ("Het eten is klaar!", "Bedtijd, Thomas!", "Kom je even naar beneden?", "Tanden poetsen!")
INTERCOM_HTML = ("""<h2>Intercom</h2><div class=panel style='padding:14px'>
<form id=say style='display:flex;gap:8px;flex-wrap:wrap'>
<input id=say_text placeholder='Wat moet het display zeggen?' required style='flex:3 1 260px;padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit'>
<input id=say_from placeholder='van (bijv. zolder)' style='flex:1 1 120px;padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink);font:inherit'>
<button style='padding:9px 16px;border:0;border-radius:8px;background:var(--ink);color:var(--bg);font:inherit;font-weight:600;cursor:pointer'>Zeg het</button></form>
<div style='display:flex;gap:6px;flex-wrap:wrap;margin-top:10px'>
""" + "".join(f"<button class=chip data-say='{html.escape(t)}'>{html.escape(t)}</button>" for t in INTERCOM_CHIPS) + """
<button class=chip data-demo=omroep>🚆 Voorbeeld omroep</button>
<label class=chip style='cursor:pointer'>🎵 Eigen omroepdeuntje (WAV)<input id=jingle type=file accept='.wav,audio/wav' hidden></label></div>
<div id=say_msg class=muted style='margin-top:8px;min-height:1.2em'></div></div>
<script>
const post = async (body) => {
  const m = document.getElementById('say_msg'); m.textContent = 'Versturen…';
  try { const r = await fetch('api/say', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify(body)});
        m.textContent = r.ok ? 'Verstuurd. Op USB hoor je het binnen 10 seconden.' : 'Lukte niet (' + r.status + ')'; }
  catch (e) { m.textContent = 'Lukte niet: ' + e; }
};
document.getElementById('say').addEventListener('submit', e => { e.preventDefault();
  post({say: document.getElementById('say_text').value, from: document.getElementById('say_from').value});
  document.getElementById('say_text').value = ''; });
document.getElementById('jingle').addEventListener('change', async e => {
  const f = e.target.files[0]; if (!f) return;
  const m = document.getElementById('say_msg'); m.textContent = 'Uploaden…';
  const r = await fetch('api/jingle', {method:'POST', body: f});
  m.textContent = r.ok ? 'Deuntje opgeslagen. Druk op Voorbeeld omroep om het te horen.' : await r.text(); });
document.querySelectorAll('button.chip').forEach(b => b.addEventListener('click', () =>
  post(b.dataset.demo ? {demo: b.dataset.demo} : {say: b.dataset.say, from: document.getElementById('say_from').value})));
</script>
""")


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

# Examples of every block type, for the control panel.
DEMO_CARDS = {
    "wijn": _demo_card,
    "sint": {"query": "hoe lang nog tot pakjesavond?", "kicker": "Sinterklaas", "title": "Nog 9 nachtjes slapen", "sticker": "🎁",
             "blocks": [{"type": "countdown", "number": 9, "unit": "nachtjes", "label": "tot pakjesavond, vrijdag 5 december"},
                        {"type": "text", "text": "Vanavond je schoen zetten? Vergeet de wortel niet 🥕"}]},
    "dino": {"query": "wat is de grootste dinosaurus?", "kicker": "Dino's", "title": "Argentinosaurus was de reus",
             "accent": "Argentinosaurus", "sticker": "🦕",
             "blocks": [{"type": "bars", "bars": [{"label": "Argentinosaurus", "value": 35, "display": "35 m"},
                                                  {"label": "Diplodocus", "value": 26, "display": "26 m"},
                                                  {"label": "T. rex", "value": 12, "display": "12 m"},
                                                  {"label": "Bus", "value": 12, "display": "12 m"}]}]},
    "spreuk": {"kicker": "Spreuk van de dag", "title": "Over doorzetten",
               "blocks": [{"type": "quote", "text": "Ik heb het nog nooit gedaan, dus ik denk dat ik het wel kan.", "by": "Pippi Langkous"},
                          {"type": "progress", "number": 90, "label": "Jaar voorbij"}]},
    "dieren": {"query": "welk dier is het snelst?", "kicker": "Dieren", "title": "De slechtvalk wint", "sticker": "🏆",
               "blocks": [{"type": "emoji_row", "emojis": [{"emoji": "🦅", "label": "slechtvalk", "value": "390 km/u"},
                                                           {"emoji": "🐆", "label": "jachtluipaard", "value": "110"},
                                                           {"emoji": "🐎", "label": "paard", "value": "88"},
                                                           {"emoji": "🐢", "label": "schildpad", "value": "0,3"}]}]},
}


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
