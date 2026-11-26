"""Chess position of the day: a known opening, trap or mini-game to set up and play from.

Openings are written as moves (python-chess computes the position, so they're
always legal); mini-games as FEN. Picked by date, so the whole family sees the same one.
"""

from __future__ import annotations

import datetime as dt

import chess

from .render import BLACK, WHITE, Canvas, font

POSITIONS = [
    ("Italiaanse opening", "e4 e5 Nf3 Nc6 Bc4 Bc5", None,
     "Een klassieker. Wit wil rokeren en met c3 en d4 het midden pakken."),
    ("Herdersmat dreigt!", "e4 e5 Bc4 Nc6 Qh5", None,
     "Wit dreigt Dxf7 mat. Kan zwart f7 op tijd verdedigen?"),
    ("Spaanse opening", "e4 e5 Nf3 Nc6 Bb5 a6", None,
     "Zwart jaagt de loper weg. Ruilen of terugtrekken?"),
    ("Siciliaanse draak", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6", None,
     "Scherp! Wit valt aan op de koningsvleugel, zwart op de damevleugel."),
    ("Damegambiet", "d4 d5 c4 e6 Nc3 Nf6", None,
     "Rustig opbouwen: wie krijgt het centrum in handen?"),
    ("Londen-systeem", "d4 d5 Bf4 Nf6 e3 e6 Nf3", None,
     "Wit zet steeds dezelfde stukken neer. Handig om te leren."),
    ("Franse verdediging", "e4 e6 d4 d5 Nc3 Nf6", None,
     "Zwart valt pion e4 aan. Hoe verdedigt wit?"),
    ("Scandinavisch", "e4 d5 exd5 Qxd5 Nc3 Qa5", None,
     "De zwarte dame komt vroeg naar buiten. Kan wit haar opjagen?"),
    ("Caro-Kann", "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5", None,
     "De loper staat netjes buiten de pionnen. Wit valt hem aan met Pg3."),
    ("Koningsgambiet", "e4 e5 f4 exf4 Nf3", None,
     "Wit offert een pion voor snelle aanval. Avontuurlijk spel!"),
    ("Schotse opening", "e4 e5 Nf3 Nc6 d4 exd4 Nxd4", None,
     "Open spel met veel ruimte voor de stukken."),
    ("Vierpaardenspel", "e4 e5 Nf3 Nc6 Nc3 Nf6", None,
     "Alle paarden staan klaar. Wie ontwikkelt de lopers het slimst?"),
    ("De val van Légal", "e4 e5 Nf3 d6 Bc4 Bg4 Nc3 g6", None,
     "Wit kan de dame weggeven en toch winnen! Zie jij de eerste zet? (Pxe5)"),
    ("Gebakken lever", "e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 d5 exd5 Nxd5", None,
     "Wit kan het paard op f7 offeren. Durf jij het aan?"),
    ("Dame tegen koning", None, "8/8/8/4k3/8/8/8/4K2Q w - - 0 1",
     "Zet de zwarte koning mat. Lukt het in 10 zetten? Pas op voor pat!"),
    ("Toren tegen koning", None, "8/8/8/4k3/8/8/8/R3K3 w - - 0 1",
     "Duw de koning met je toren naar de rand. Je koning helpt mee."),
    ("Pionnenoorlog", None, "4k3/pppppppp/8/8/8/8/PPPPPPPP/4K3 w - - 0 1",
     "Alleen pionnen en koningen. Wie het eerst een dame haalt, wint!"),
    ("Dame tegen pionnen", None, "4k3/pppppppp/8/8/8/8/8/3QK3 w - - 0 1",
     "Kan wit alle pionnen pakken voordat er één een dame wordt?"),
    ("Mini-schaak", None, "1nb1kbn1/pppppppp/8/8/8/8/PPPPPPPP/1NB1KBN1 w - - 0 1",
     "Geen torens en geen dame: alleen paarden en lopers. Snel en grappig."),
    ("Torens en pionnen", None, "r3k3/pppp4/8/8/8/8/4PPPP/4K2R w - - 0 1",
     "Elk een toren en vier pionnen. Wie haalt er het eerst een dame?"),
    ("Pionnenrace", None, "8/p7/8/8/8/8/7P/k6K w - - 0 1",
     "Twee pionnen racen naar de overkant. Tel de zetten: wie is er eerst?"),
    ("Paardenspel", None, "4k3/8/8/8/8/8/8/1N2K1N1 w - - 0 1",
     "Twee paarden en een koning. Kun je de zwarte koning in de hoek drijven?"),
]

GLYPH = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
         "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟"}


def of_the_day(day: dt.date):
    n = day.toordinal()
    title, moves, fen, tip = POSITIONS[n % len(POSITIONS)]
    board = chess.Board(fen) if fen else chess.Board()
    if moves:
        for san in moves.split():
            board.push_san(san)
    return title, board, tip, n % len(POSITIONS) + 1, moves


def draw_board(c: Canvas, board: chess.Board, x0: int, y0: int, sq: int = 30):
    fp = font(int(sq * 0.92), "symbols")
    for r in range(8):
        for f in range(8):
            x, y = x0 + f * sq, y0 + (7 - r) * sq
            if (r + f) % 2 == 0:  # dark square: light dither so pieces stay readable
                c.pattern(x, y, x + sq - 1, y + sq - 1, 11)
            p = board.piece_at(chess.square(f, r))
            if p:
                cx, cy = x + sq // 2, y + sq // 2 + 1
                sym = p.symbol()
                if sym.isupper():  # white piece: white silhouette first, then the outline
                    c.d.text((cx, cy), GLYPH[sym.lower()], font=fp, fill=WHITE, anchor="mm")
                    c.d.text((cx, cy), GLYPH[sym], font=fp, fill=BLACK, anchor="mm")
                else:
                    c.d.text((cx, cy), GLYPH[sym], font=fp, fill=BLACK, anchor="mm")
    c.rect(x0 - 1, y0 - 1, x0 + 8 * sq, y0 + 8 * sq, outline=BLACK, w=2)
    fl = font(10, "sans", "Medium")
    for i in range(8):
        c.text((x0 + i * sq + sq // 2, y0 + 8 * sq + 2), "abcdefgh"[i], fl, anchor="ma")
        c.text((x0 - 4, y0 + (7 - i) * sq + sq // 2), str(i + 1), fl, anchor="rm")
