"""The reference spots, written by hand. python -m tools.reference_spots make-spots turns
them into data/reference_spots/python_solver/spots/*.json. Edit here, not the JSON.

Every pot is 100, as in data/answer_keys, so an amount is also a percent of the pot.

Known answers (py01 to py12)
----------------------------
The polar games use the board Kh 8d 5c 3s 2h (no flush or straight possible for these
hands) and three kinds of hand that share no rank, so no deal is ruled out and card
removal can't move the numbers:

- the nuts: KK (3 combos; Kh is on the board), and in py09 also 88 and 55 (3 each);
- a bluff catcher: QQ (6 combos). It beats the air and loses to the nuts;
- air: JT (16 combos), or only JTs (4 combos) in py09.

One player may bet one size, s times the pot, or check. The other may only check, then
call or fold. With V nuts and A air combos, pot P = 100 (The Mathematics of Poker;
app/tests/solver_games.py has the derivation):

- bluffs are s/(1+2s) of the bets, so V s/(1+s) combos of air bet;
- the caller calls 1/(1+s) of the time;
- every nut hand bets;
- the bettor wins V/(V+A) x P x (1 + s/(1+s)) a hand, the caller the rest of P.

By hand, V = 3 and A = 16:

    spot  s      bluff share       call share      air combos that bet   bettor's value
    py05  0.25   0.25/1.5 = 1/6    1/1.25 = 4/5    0.75/1.25 = 0.6       (3/19) x 120   = 360/19   = 18.947
    py01  0.5    0.5/2    = 1/4    1/1.5  = 2/3    1.5/1.5   = 1         (3/19) x 400/3 = 400/19   = 21.053
    py08  0.6    0.6/2.2  = 3/11   1/1.6  = 5/8    1.8/1.6   = 1.125     (3/19) x 137.5 = 412.5/19 = 21.711
    py02  0.75   0.75/2.5 = 3/10   1/1.75 = 4/7    2.25/1.75 = 9/7       (3/19) x 1000/7 = 3000/133 = 22.556
    py03  1      1/3               1/2             3/2                   (3/19) x 150   = 450/19   = 23.684
    py07  1      the same, with the bettor out of position
    py06  1.5    1.5/4    = 3/8    1/2.5  = 2/5    4.5/2.5   = 1.8       (3/19) x 160   = 480/19   = 25.263
    py04  2      2/5               1/3             6/3       = 2         (3/19) x 500/3 = 500/19   = 26.316

    (value = (3/19) x (100 + call share x bet): s = 0.25: 100 + 0.8 x 25 = 120;
    s = 0.6: 100 + 0.625 x 60 = 137.5; s = 1.5: 100 + 0.4 x 150 = 160.)

py08 is the same game where the only bet is all in for 60 into 100 (s = 0.6).

py09 has too few bluffs: 9 nut combos (KK, 88, 55) and 4 of air (JTs). A pot-sized bet
needs 9 x 1/2 = 4.5 air combos to make the caller indifferent, and there are 4. Betting
everything, bluffs are 4/13 = 0.308 of the bets, under 1/3, so calling loses:
(4/13) x 200 - (9/13) x 100 = -7.7. The caller always folds, and the bettor takes the
whole pot every hand: value 100 and 0.

py10, py11: one player holds only the nuts, the other only air. Air never bets (it is only
called by the nuts) and never calls. The nuts win the pot: value 100 and 0.

py12: a royal flush is on the board, so every hand splits. Each player gets 50, and nobody
folds to a bet (folding gives up half the pot, calling always splits it).

Realistic (py13 to py20)
------------------------
py13 to py16 are written as range text. py17 to py20 use the ranges the app builds from a
betting line (app/solver/ranges.py): any weight for any combo, which is what a solver in
the app is really given. Those four are made once by `make-spots --lines`; afterwards the
JSON files are the spots (the model in ranges.py may change, a reference spot must not).
"""
from __future__ import annotations

from fractions import Fraction
from typing import Dict, List

POT = 100
POLAR_BOARD = "Kh 8d 5c 3s 2h"
NOBODY = {"bets": [], "raises": [], "allin": False}  # this player can only check, call or fold


def one_bet(s: float) -> Dict:
    return {"bets": [s], "raises": [], "allin": False}


APP_SIZES = {"bets": [0.5, 1.0], "raises": [1.0], "allin": True}  # what the advice's bridge offers


def spot(id_, title, board, stacks, oop, ip, oop_sizes, ip_sizes, max_raises, tags, expected=None) -> Dict:
    return {"id": id_, "street": "river", "title": title, "tags": tags, "board": board.split(), "pot": POT,
            "stacks": list(stacks), "max_raises": max_raises, "sizes": {"oop": oop_sizes, "ip": ip_sizes},
            "range_text": {"oop": oop, "ip": ip}, "expected": expected or []}


def half_street(id_, s, bettor="ip") -> Dict:
    sizes = (NOBODY, one_bet(s)) if bettor == "ip" else (one_bet(s), NOBODY)
    hands = ("QQ", "KK,JT") if bettor == "ip" else ("KK,JT", "QQ")
    who = "in position" if bettor == "ip" else "out of position"
    return spot(id_, f"Known answer: nuts or air {who} bets {s:g} pot into a bluff catcher", POLAR_BOARD,
                (1000, 1000), hands[0], hands[1], sizes[0], sizes[1], 0, ["closed-form", "polar", "dry"])


NEVER_FOLD = [{"nodes": r"^b[0-9.]+$", "actor": "ip", "action": "f", "max": 0.02,
               "why": "folding gives up half the pot, calling always splits it"}]

SPOTS: List[Dict] = [
    # ------------------------------------------------------------ known answers
    half_street("py01", 0.5),
    half_street("py02", 0.75),
    half_street("py03", 1.0),
    half_street("py04", 2.0),
    half_street("py05", 0.25),
    half_street("py06", 1.5),
    half_street("py07", 1.0, bettor="oop"),
    spot("py08", "Known answer: nuts or air in position, the only bet is all in for 0.6 pot", POLAR_BOARD,
         (60, 60), "QQ", "KK,JT", NOBODY, {"bets": [], "raises": [], "allin": True}, 0,
         ["closed-form", "polar", "dry", "low-spr"]),
    spot("py09", "Known answer: too few bluffs for a pot-sized bet, the bluff catcher always folds", POLAR_BOARD,
         (1000, 1000), "QQ", "KK,88,55,JTs", NOBODY, one_bet(1.0), 0, ["closed-form", "polar", "dry"],
         expected=[{"nodes": r"^x b100$", "actor": "oop", "action": "f", "min": 0.98,
                    "why": "bluffs are at most 4 of 13 bets, under the 1/3 a call needs"}]),
    spot("py10", "Known answer: OOP holds only air, IP only the nuts", "Jc 8d 3s Ks 2h", (200, 200),
         "T9s,76s,54s,Q9s", "KK,JJ", APP_SIZES, APP_SIZES, 1, ["trivial", "dry"],
         expected=[{"nodes": r"^$", "actor": "oop", "action": "x", "min": 0.98,
                    "why": "a bet with zero equity is only ever called or raised"},
                   {"nodes": r"^x b[0-9.]+$", "actor": "oop", "action": "f", "min": 0.98,
                    "why": "calling with zero equity loses the call"}]),
    spot("py11", "Known answer: OOP holds only the nuts, IP only air", "Ks 7d 2c 4h 9s", (200, 200),
         "KK,99", "QJs,T8s,65s,63s", APP_SIZES, APP_SIZES, 1, ["trivial", "dry"],
         expected=[{"nodes": r"^x$", "actor": "ip", "action": "x", "min": 0.98,
                    "why": "a bet with zero equity is only ever called or raised"},
                   {"nodes": r"^b[0-9.]+$", "actor": "ip", "action": "f", "min": 0.98,
                    "why": "calling with zero equity loses the call"}]),
    spot("py12", "Known answer: royal flush on the board, every hand splits", "Ah Kh Qh Jh Th", (200, 200),
         "22+,A2s+,KQo:0.5", "99+,AK,KQ,QJs", APP_SIZES, APP_SIZES, 1, ["trivial", "wet"], expected=NEVER_FOLD),
    # ---------------------------------------------------------------- realistic
    spot("py13", "Dry Q7283, capped caller OOP against a polar bettor, SPR 1, the app's sizes", "Qs 7d 2c 8h 3s",
         (100, 100), "JJ-99,AQo,KQ,QJs,QTs,Q9s,A7s,87s,T8s,98s,A8s:0.5",
         "QQ,77,22,AQs,Q8s,87s:0.5,AK:0.5,KJs,JTs,T9s,65s,54s,A5s,A4s",
         APP_SIZES, APP_SIZES, 1, ["dry", "polar", "condensed"]),
    spot("py14", "Wet Th9h6c-Jh-2d, wide against wide, SPR 2.5, the app's sizes", "Th 9h 6c Jh 2d",
         (250, 250), "22-JJ,A2s+,K9s+,Q9s+,J9s+,T8s+,97s+,86s+,75s+,65s,54s,ATo+,KTo+,QTo+,JTo",
         "22+,A2s+,K8s+,Q9s+,J9s+,T9s,98s,87s,76s,65s,ATo+,KJo+,QJo",
         APP_SIZES, APP_SIZES, 1, ["wet", "wide"]),
    spot("py15", "Paired AA7-7-2, SPR 0.5: a small bet or all in", "As Ac 7h 7d 2s", (50, 50),
         "KK-88,66-33,KQ,KJs,QJs,JTs,T9s,98s,87s,76s", "AK,AQ,AJs,ATs,A9s,77,A2s,K7s,Q7s,65s,54s,43s,86s,T8s,96s",
         {"bets": [0.25], "raises": [], "allin": True}, {"bets": [0.25], "raises": [], "allin": True}, 1,
         ["paired", "polar", "condensed", "low-spr"]),
    spot("py16", "Four to a straight 9876-K, SPR 5, three bet sizes and two raises", "9s 8s 6d 7c Ks",
         (500, 500), "AKo,KQo,KJo,KTo,AA-QQ,99,88:0.5,98s,97s:0.5,JTs:0.25,T9s:0.5",
         "JT,T9s,T5s,54s,53s,AQs,AJs,A4s,KK,QJo,J4s,43s,AKs:0.5,K9s",
         {"bets": [0.33, 0.75, 1.5], "raises": [0.75], "allin": True},
         {"bets": [0.33, 0.75, 1.5], "raises": [0.75], "allin": True}, 2,
         ["wet", "polar", "condensed", "three-sizes", "overbet", "reraise"]),
]

# The four spots with the app's own ranges: (id, title, board, the betting line, who the app
# is, seats). Sizes before the flop are big blinds each player put in; after it, shares of
# the pot. "hero" is the app's seat (it plays by the charts), "villain" the opponent.
LINES: List[Dict] = [
    dict(id="py17", board="Kd 9s 4c 7h 2s", tags=["dry", "app-ranges"],
         title="The app's ranges: button opens, big blind (the app) calls; bet 66%, bet 75%, both called",
         hero_seat="BB", villain_seat="BTN", preflop=(2.5, "villain"), flop=(0.66, "villain"), turn=(0.75, "villain"),
         dead_bb=0.5),
    dict(id="py18", board="Jh Tc 6h 3d Qs", tags=["wet", "app-ranges"],
         title="The app's ranges: the app opens the button, big blind calls; the app bets 50% and 66%, both called",
         hero_seat="BTN", villain_seat="BB", preflop=(2.5, "hero"), flop=(0.5, "hero"), turn=(0.66, "hero"),
         dead_bb=0.5),
    dict(id="py19", board="Ac 8d 5s Td 4h", tags=["dry", "app-ranges"],
         title="The app's ranges: small blind re-raises the app's button open to 10, called; bet 33%, turn checked",
         hero_seat="BTN", villain_seat="SB", preflop=(10.0, "villain"), flop=(0.33, "villain"), turn=(0.0, None),
         dead_bb=1.0),
    dict(id="py20", board="8c 8h 3s Qd 6c", tags=["paired", "app-ranges"],
         title="The app's ranges: cutoff opens, the app calls on the button; flop checked, cutoff bets the pot on the turn",
         hero_seat="BTN", villain_seat="CO", preflop=(2.5, "villain"), flop=(0.0, None), turn=(1.0, "villain"),
         dead_bb=1.5),
]

STACK_BB = 100.0  # both players start the hand with this many big blinds

# What a solver must find on the spots with known answers: the value of the game for OOP
# (chips a hand, of the pot of 100), and for the polar games who bets, the bluff share of
# the bets and how often the bluff catcher calls.
KNOWN = {
    "py01": dict(bettor="ip", s=0.5, bluffs=Fraction(1, 4), calls=Fraction(2, 3), oop_value=100 - Fraction(400, 19)),
    "py02": dict(bettor="ip", s=0.75, bluffs=Fraction(3, 10), calls=Fraction(4, 7), oop_value=100 - Fraction(3000, 133)),
    "py03": dict(bettor="ip", s=1.0, bluffs=Fraction(1, 3), calls=Fraction(1, 2), oop_value=100 - Fraction(450, 19)),
    "py04": dict(bettor="ip", s=2.0, bluffs=Fraction(2, 5), calls=Fraction(1, 3), oop_value=100 - Fraction(500, 19)),
    "py05": dict(bettor="ip", s=0.25, bluffs=Fraction(1, 6), calls=Fraction(4, 5), oop_value=100 - Fraction(360, 19)),
    "py06": dict(bettor="ip", s=1.5, bluffs=Fraction(3, 8), calls=Fraction(2, 5), oop_value=100 - Fraction(480, 19)),
    "py07": dict(bettor="oop", s=1.0, bluffs=Fraction(1, 3), calls=Fraction(1, 2), oop_value=Fraction(450, 19)),
    "py08": dict(bettor="ip", s=0.6, bluffs=Fraction(3, 11), calls=Fraction(5, 8), oop_value=100 - Fraction(825, 38)),
    "py09": dict(oop_value=Fraction(0)),
    "py10": dict(oop_value=Fraction(0)),
    "py11": dict(oop_value=Fraction(100)),
    "py12": dict(oop_value=Fraction(50)),
}
