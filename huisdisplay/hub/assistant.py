"""Push-to-talk assistant: PCM -> speech-to-text -> Claude (with house tools) -> card."""

from __future__ import annotations

import io
import json
import logging
import time
import wave

import anthropic
import httpx
import numpy as np

from . import pages
from . import sources as src
from .card import CARD_SCHEMA
from .config import settings

log = logging.getLogger("hub.assistant")
_http = httpx.AsyncClient(timeout=30)
_claude: anthropic.AsyncAnthropic | None = None

HISTORY_TTL = 600  # follow-up questions within 10 minutes keep context


def _client() -> anthropic.AsyncAnthropic:
    global _claude
    if _claude is None:
        _claude = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)
    return _claude


# ------------------------------------------------------------------ audio
def pcm_to_wav(pcm: bytes, fmt: str) -> bytes:
    """Device sends 16 kHz s16le, usually stereo; keep the louder channel,
    remove DC and normalise so quiet speech still transcribes well."""
    a = np.frombuffer(pcm[: len(pcm) - len(pcm) % 4], dtype="<i2").astype(np.float32)
    if "channels=2" in fmt:
        a = a.reshape(-1, 2)
        ch = int(np.argmax(np.sqrt((a ** 2).mean(axis=0))))
        a = a[:, ch]
    a -= a.mean()
    peak = np.abs(a).max() or 1.0
    a = np.clip(a * min(20.0, 0.9 * 32767 / peak), -32767, 32767).astype("<i2")
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(a.tobytes())
    return b.getvalue()


async def transcribe(wav: bytes) -> str:
    if settings.stt_provider == "openai" and settings.openai_api_key:
        r = await _http.post("https://api.openai.com/v1/audio/transcriptions",
                             headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                             data={"model": "gpt-4o-transcribe", "language": "nl"},
                             files={"file": ("q.wav", wav, "audio/wav")})
        r.raise_for_status()
        return r.json()["text"].strip()
    if settings.elevenlabs_api_key:
        r = await _http.post("https://api.elevenlabs.io/v1/speech-to-text",
                             headers={"xi-api-key": settings.elevenlabs_api_key},
                             data={"model_id": "scribe_v1", "language_code": "nld", "tag_audio_events": "false"},
                             files={"file": ("q.wav", wav, "audio/wav")})
        r.raise_for_status()
        return r.json()["text"].strip()
    raise RuntimeError("Geen spraak-naar-tekst ingesteld (ELEVENLABS_API_KEY of OPENAI_API_KEY)")


# ------------------------------------------------------------------ tools
TOOLS = [
    {
        "name": "show_card",
        "description": "Show the final answer on the e-ink display. Call this exactly once, as your last action, for every question. "
                       "Alternatively set 'page' to open one of the built-in pages instead of a card.",
        "input_schema": {
            **CARD_SCHEMA,
            "properties": {
                **CARD_SCHEMA["properties"],
                "page": {"type": "string", "enum": ["home", "weer", "trein", "agenda", "huis", "afval"],
                         "description": "Open a built-in page instead of showing a card (title/blocks may then be empty)."},
                "keep_seconds": {"type": "integer", "description": "How long the card stays up. Default 300; recipes 1800."},
            },
        },
    },
    {
        "name": "get_home_state",
        "description": "Read current Home Assistant entities. Filter by domain (light, switch, sensor, binary_sensor, climate, cover, "
                       "lock, media_player, fan, input_boolean...) and/or a search text on entity id / name. Returns id, name, state, unit.",
        "input_schema": {"type": "object", "properties": {
            "domain": {"type": "string"}, "search": {"type": "string"}}, "additionalProperties": False},
    },
    {
        "name": "call_home_service",
        "description": "Control the house via a Home Assistant service, e.g. light.turn_off, cover.close_cover, climate.set_temperature, "
                       "input_boolean.turn_on, scene.turn_on. Only act when the user clearly asked for it.",
        "input_schema": {"type": "object", "properties": {
            "domain": {"type": "string"}, "service": {"type": "string"},
            "entity_id": {"type": "array", "items": {"type": "string"}},
            "data": {"type": "object", "description": "Extra service data, e.g. {\"brightness_pct\": 30}"}},
            "required": ["domain", "service", "entity_id"]},
    },
    {
        "name": "add_to_shopping_list",
        "description": "Add groceries to the household shopping list (Home Assistant to-do list).",
        "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "string"}}},
                         "required": ["items"]},
    },
    {
        "name": "get_shopping_list",
        "description": "Read what is on the shopping list.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_weather",
        "description": "Rain radar for the next 2 hours (Buienradar, 5-minute steps) and the hourly/daily forecast.",
        "input_schema": {"type": "object", "properties": {"daily": {"type": "boolean"}}},
    },
    {
        "name": "get_trains",
        "description": f"Upcoming train departures from {settings.ns_station_name or 'the home station'}"
                       f"{' toward ' + settings.ns_to if settings.ns_to else ''}, with delays, platforms and disruptions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_waste_calendar",
        "description": "Upcoming waste collection days (GFT, restafval, papier, PMD...) for this address.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_calendar",
        "description": "Family calendar events for the coming days.",
        "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "default": 7}}},
    },
    {
        "name": "get_reminders",
        "description": "Open items on the household reminders/to-do list (with due dates).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_reminder",
        "description": "Add a household reminder or chore, optionally due on a date (and time). It shows on the display on that day.",
        "input_schema": {"type": "object", "properties": {
            "summary": {"type": "string", "description": "Short, e.g. 'Gymtas mee'"},
            "due_date": {"type": "string", "description": "YYYY-MM-DD"},
            "due_time": {"type": "string", "description": "HH:MM, only if a time was mentioned"},
            "description": {"type": "string"}},
            "required": ["summary"]},
    },
    {
        "name": "complete_reminder",
        "description": "Mark a reminder as done (match by its text).",
        "input_schema": {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
    },
    {
        "name": "get_packages",
        "description": "Parcels on their way (PostNL), with expected delivery windows.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_strava",
        "description": "The owner's Strava training: this week, weekly streak, recent activities.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 4,
     "user_location": {"type": "approximate", **({"city": settings.place} if settings.place else {}),
                       "country": "NL", "timezone": settings.tz}},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3},
]

SYSTEM = """Je bent de huisassistent achter een klein e-ink display (400x300, zwart-wit) in de woonkamer van een gezin{PLACE}. Iemand houdt de knop ingedrukt en stelt een vraag; jij antwoordt door de tool show_card aan te roepen. Dat is altijd je laatste stap, precies één keer.

Hoe een goede kaart eruitziet:
- Nederlands, kort, op afstand leesbaar. De titel is het antwoord zelf (max ~8 woorden), niet een herhaling van de vraag.
- Kies de blokvorm die bij het antwoord past: rows voor vergelijkingen of kleine tabellen, big voor één getal, steps voor recepten en instructies, timeline voor tijden, icon_row voor weer per dag, text voor één of twee zinnen uitleg. Meestal 1–3 blokken.
- Speelsere blokken: countdown (aftellen: number + unit zoals 'nachtjes slapen'), bars (staafjes om grootte/snelheid/aantallen te vergelijken), quote (een mooie uitspraak of gedichtje), progress (hoe ver iets is, 0–100), sticker (één grote emoji met een korte zin), emoji_row (tot 5 grote emoji met label en waarde: dieren, planeten, landen).
- Emoji mogen overal in tekst en worden zwart-wit getekend; gebruik ze met mate (één of twee per kaart). 'sticker' op kaartniveau zet één emoji als rond plaatje in de hoek: leuk bij vragen van kinderen.
- In dit gezin wonen kinderen. Klinkt de vraag als van een kind (dino's, pokémon, dieren, 'hoeveel nachtjes nog'), antwoord dan speels, eenvoudig en enthousiast, met een sticker en bij voorkeur bars, emoji_row of countdown.
- Gebruik 'accent' alleen voor één sprekend woord uit de titel (wordt groot en cursief).
- Lange inhoud (recepten) mag: het display verdeelt het over schermen die met OK doorgebladerd worden. Zet dan keep_seconds op 1800.

Gereedschap:
- Huis (Home Assistant): lees eerst met get_home_state voordat je iets schakelt; schakel alleen als erom gevraagd is en meld wat je deed.
- Boodschappen: add_to_shopping_list. Bij een recept met 'zet op de lijst' voeg je de ingrediënten toe die men waarschijnlijk niet in huis heeft (geen zout/peper/olie).
- Recepten: zoek bij voorkeur op Albert Heijn Allerhande (ah.nl/allerhande) met web_search en haal het recept op met web_fetch. Noem bron en bereidingstijd kort in de footer.
- Herinneringen/klusjes ('herinner me donderdag aan de gymtas'): add_reminder met datum; 'is gedaan' → complete_reminder. Ze verschijnen op die dag op het display.
- Weer/regen, treinen, afval, agenda, pakketten en Strava hebben eigen tools; gebruik die in plaats van het web.
- Wil iemand gewoon een overzicht zien ('laat de buienradar zien', 'wanneer gaat de trein'), dan kan show_card met page volstaan.
Als je iets niet weet of niet kunt, zeg dat eerlijk op de kaart."""
SYSTEM = SYSTEM.replace("{PLACE}", f" in {settings.place}" if settings.place else "")


async def run_tool(name: str, args: dict) -> str:
    if name == "get_home_state":
        states = await src.ha_states()
        dom, q = args.get("domain"), (args.get("search") or "").lower()
        out = []
        for eid, e in states.items():
            if dom and not eid.startswith(dom + "."):
                continue
            fn = e["attributes"].get("friendly_name", "")
            if q and q not in eid.lower() and q not in fn.lower():
                continue
            item = {"id": eid, "name": fn, "state": e["state"]}
            if u := e["attributes"].get("unit_of_measurement"):
                item["unit"] = u
            if eid.startswith("climate."):
                item.update({k: e["attributes"].get(k) for k in ("current_temperature", "temperature", "hvac_action")})
            out.append(item)
        return json.dumps(out[:80], ensure_ascii=False)
    if name == "call_home_service":
        data = dict(args.get("data") or {})
        data["entity_id"] = args["entity_id"]
        await src.ha_call(args["domain"], args["service"], data)
        return "ok"
    if name == "add_to_shopping_list":
        for it in args["items"]:
            await src.ha_call("todo", "add_item", {"entity_id": settings.shopping_list, "item": it})
        return f"{len(args['items'])} items toegevoegd"
    if name == "get_shopping_list":
        res = await src.ha_call("todo", "get_items", {"entity_id": settings.shopping_list, "status": "needs_action"}, True)
        items = res["service_response"][settings.shopping_list]["items"]
        return json.dumps([i["summary"] for i in items], ensure_ascii=False)
    if name == "get_weather":
        rain = await src.rain()
        fc = await src.ha_forecast("daily" if args.get("daily") else "hourly")
        return json.dumps({"now": src.now().isoformat(timespec="minutes"),
                           "rain_summary": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in src.rain_summary(rain).items()},
                           "rain_mm_per_hour": [[p.time.strftime("%H:%M"), p.mm] for p in rain],
                           "forecast": fc[:24]}, ensure_ascii=False, default=str)
    if name == "get_trains":
        return json.dumps(await src.trains(), ensure_ascii=False, default=str)
    if name == "get_waste_calendar":
        return json.dumps((await src.waste())[:10], ensure_ascii=False, default=str)
    if name == "get_calendar":
        return json.dumps(await src.calendar(int(args.get("days", 7))), ensure_ascii=False, default=str)
    if name == "get_reminders":
        return json.dumps(await src.reminders(), ensure_ascii=False, default=str)
    if name == "add_reminder":
        data = {"entity_id": settings.reminders_list, "item": args["summary"]}
        if args.get("due_date"):
            if args.get("due_time"):
                data["due_datetime"] = f"{args['due_date']} {args['due_time']}:00"
            else:
                data["due_date"] = args["due_date"]
        if args.get("description"):
            data["description"] = args["description"]
        await src.ha_call("todo", "add_item", data)
        return "toegevoegd"
    if name == "complete_reminder":
        q = args["summary"].lower()
        items = await src.reminders()
        hit = next((r for r in items if q in r["summary"].lower() or r["summary"].lower() in q), None)
        if not hit:
            return "niet gevonden; open items: " + ", ".join(r["summary"] for r in items)
        await src.ha_call("todo", "update_item", {"entity_id": settings.reminders_list, "item": hit["uid"],
                                                  "status": "completed"})
        return f"afgevinkt: {hit['summary']}"
    if name == "get_packages":
        pk = await src.packages()
        return json.dumps(pk, ensure_ascii=False, default=str) if pk else "Geen pakketten onderweg (of PostNL is niet gekoppeld in Home Assistant)."
    if name == "get_strava":
        from . import strava
        s = await strava.summary()
        return json.dumps(s, ensure_ascii=False, default=str) if s else "Strava is nog niet gekoppeld (hub → /strava)."
    return f"onbekende tool {name}"


def _text_card(text: str, query: str) -> dict:
    return {"query": query, "title": text.split(". ")[0][:80], "blocks": [{"type": "text", "text": text}]}


async def ask(query: str, history: list[dict]) -> dict:
    """Run Claude with tools until it calls show_card. Returns the card dict."""
    n = src.now()
    from . import fun
    family = fun.describe_for_assistant(n.date())
    context = (f"Het is nu {pages.DAYS[n.weekday()]} {n:%d-%m-%Y %H:%M}."
               + (f" Gezin: {family}." if family else ""))
    messages: list[dict] = []
    for h in history:
        messages.append({"role": "user", "content": h["q"]})
        messages.append({"role": "assistant", "content": f"(Getoond op het display: {h['a']})"})
    messages.append({"role": "user", "content": f"{context}\n\nVraag: {query}"})

    for _ in range(10):
        resp = await _client().beta.messages.create(
            model=settings.claude_model,
            max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            return {"query": query, "title": "Daar kan ik niet mee helpen", "blocks": []}
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "pause_turn":
            continue
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        card = next((b.input for b in tool_uses if b.name == "show_card"), None)
        if card is not None:
            card = dict(card)
            card.setdefault("query", query)
            return card
        if not tool_uses:
            text = " ".join(b.text for b in resp.content if b.type == "text").strip()
            return _text_card(text or "Geen antwoord", query)
        results = []
        for b in tool_uses:
            try:
                out = await run_tool(b.name, b.input)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            except Exception as e:
                log.warning("tool %s failed: %s", b.name, e)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": f"Fout: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})
    return {"query": query, "title": "Dat duurde te lang", "blocks": [{"type": "text", "text": "Probeer het nog eens."}]}


async def handle_voice(pcm: bytes, fmt: str, device) -> tuple[dict, bytes | None]:
    wav = pcm_to_wav(pcm, fmt)
    (settings.data_dir / "last_voice.wav").write_bytes(wav)  # only the latest, for debugging
    t0 = time.time()
    try:
        query = await transcribe(wav)
    except Exception as e:
        log.warning("STT failed: %s", e)
        return {"title": "Ik kon je niet verstaan", "blocks": [{"type": "text", "text": str(e)}], "keep_seconds": 60}, None
    log.info("STT %.1fs: %r", time.time() - t0, query)
    if not query:
        return {"title": "Ik hoorde niets", "blocks": [{"type": "text", "text": "Houd de knop ingedrukt terwijl je praat."}],
                "keep_seconds": 30}, None
    if not settings.anthropic_api_key:
        return {"query": query, "title": "Claude is nog niet gekoppeld",
                "blocks": [{"type": "text", "text": "Zet ANTHROPIC_API_KEY in de hub-instellingen."}]}, None
    hist = [h for h in device.history if time.time() - h["t"] < HISTORY_TTL][-4:]
    t1 = time.time()
    try:
        card = await ask(query, hist)
    except anthropic.APIError as e:
        log.warning("Claude failed: %s", e)
        card = {"query": query, "title": "Claude is even niet bereikbaar", "blocks": [{"type": "text", "text": str(e)[:200]}]}
    log.info("Claude %.1fs: %s", time.time() - t1, card.get("title"))
    device.history = hist + [{"t": time.time(), "q": query, "a": json.dumps(
        {k: card.get(k) for k in ("title", "blocks")}, ensure_ascii=False)[:1500]}]
    return card, None
