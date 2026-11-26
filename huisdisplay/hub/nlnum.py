"""Spell out numbers in Dutch before text-to-speech (TTS voices stumble over digits).

    spell("De trein van 8:28 heeft 4 minuten vertraging, spoor 14c, 6,5°")
    -> "De trein van acht uur achtentwintig heeft vier minuten vertraging, spoor veertien c, zes komma vijf graden"
"""

from __future__ import annotations

import re

UNITS = ["nul", "een", "twee", "drie", "vier", "vijf", "zes", "zeven", "acht", "negen", "tien", "elf", "twaalf",
         "dertien", "veertien", "vijftien", "zestien", "zeventien", "achttien", "negentien"]
TENS = {2: "twintig", 3: "dertig", 4: "veertig", 5: "vijftig", 6: "zestig", 7: "zeventig", 8: "tachtig", 9: "negentig"}


def words(n: int) -> str:
    if n < 0:
        return "min " + words(-n)
    if n < 20:
        return UNITS[n]
    if n < 100:
        t, u = divmod(n, 10)
        if not u:
            return TENS[t]
        unit = UNITS[u]
        return unit + ("ën" if unit.endswith("e") else "en") + TENS[t]  # tweeëntwintig, eenentwintig
    if n < 1000:
        h, r = divmod(n, 100)
        return ("honderd" if h == 1 else UNITS[h] + "honderd") + (words(r) if r else "")
    if 1100 <= n < 2000 and n % 100:  # years: negentienhonderdachtennegentig
        h, r = divmod(n, 100)
        return words(h) + "honderd" + words(r)
    if n < 1_000_000:
        th, r = divmod(n, 1000)
        return ("duizend" if th == 1 else words(th) + "duizend") + (" " + words(r) if r else "")
    m, r = divmod(n, 1_000_000)
    return ("één miljoen" if m == 1 else words(m) + " miljoen") + (" " + words(r) if r else "")


def _num(n: int) -> str:
    return "één" if n == 1 else words(n)  # a lone 1 reads as "één", not the article "een"


def _time(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return m.group(0)
    return f"{words(h)} uur" + (f" {words(mi)}" if mi else "")


def _number(m: re.Match) -> str:
    whole, frac, nxt = m.group(1), m.group(2), m.group(3) or ""
    s = _num(int(whole))
    if frac:
        s += " komma " + " ".join(words(int(d)) for d in frac) if len(frac) > 2 else " komma " + words(int(frac))
    return s + (" " + nxt if nxt and nxt.isalpha() else nxt)


def ordinal(n: int) -> str:
    special = {1: "eerste", 3: "derde", 8: "achtste"}
    if n in special:
        return special[n]
    return words(n) + ("de" if n < 20 else "ste")


def spell(text: str) -> str:
    text = re.sub(r"\b(\d{1,2})[:.](\d{2})\b(?!\d)(\s*uur)?", lambda m: _time(m), text)  # 8:28 / 08.28 (uur)
    text = re.sub(r"\b(\d{1,3})(?:e|ste|de)\b", lambda m: ordinal(int(m.group(1))), text)
    text = text.replace("%", " procent").replace("°", " graden").replace("€", "euro ")
    text = re.sub(r"(\d+)(?:,(\d+))?([A-Za-z]?)", _number, text)
    return re.sub(r"\s{2,}", " ", text).strip()
