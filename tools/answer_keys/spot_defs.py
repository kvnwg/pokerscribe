"""The 40 answer-key spots, written by hand: 30 river spots and 10 turn spots.

`python -m tools.answer_keys make-spots` turns these into data/answer_keys/spots/*.json
(range text expanded to combos, the board cards removed). Edit here, not the JSON.

Every pot is 100, so amounts read as a share of the starting pot. SPR is the effective
stack over the pot at the start of the spot. Ranges are written as whole hand classes with
optional weights, because TexasSolver takes ranges by class (README.md, "Quirks").

Polar: strong hands and air, few in between. Condensed: medium hands, no nuts. Wide: a
realistic spread of everything. The board sets "dry" (no flush, few straights) or "wet".
"""
from __future__ import annotations

from typing import Dict, List

# ------------------------------------------------------------- ranges used more than once
K72 = {  # Ks 7d 2c 4h 9s
    "condensed": "QQ-TT,88,KQo,KJ,KTs,A9s,98s,97s,87s,76s,A7s",
    "polar": "AK,KK:0.5,99:0.5,77:0.5,K9s,74s,QJs,QTs,JTs,65s,63s,A5s,A3s",
    "wide_oop": "22-QQ,A2s+,K5s+,Q9s+,J9s+,T8s+,97s+,86s+,75s+,65s,54s,A8o+,KTo+,QTo+,JTo",
    "wide_ip": "22+,A2s+,K8s+,Q9s+,J9s+,T9s,98s,87s,76s,65s,ATo+,KJo+,QJo",
}
JK8 = {  # Jc 8d 3s Ks 2h
    "condensed": "QQ-99,KTs,KQo,KJo,QJs,JTs,J9s,A8s,98s,T8s,87s",
    "polar": "AK,KK,JJ,88:0.5,KJs,QTs,T9s,A5s,A4s,76s,65s:0.5",
    "polar_oop": "KK,JJ,88,33,AK,KJs,K8s,QTs,T9s,A5s,A4s,54s,65s",
    "condensed_ip": "QQ-99,KQ,KTs,AJs,QJs,JTs,J9s,98s",
}
Q96 = {  # Qd 6c 2h 9s 4d
    "wide_oop": "22-JJ,A2s+,K9s+,Q9s+,J9s+,T8s+,97s+,86s+,75s+,64s+,53s+,ATo+,KJo+,QJo",
    "wide_ip": "33-TT,AQ,AJ,KQ,QJs,QTs,JTs,T9s,98s,87s,76s,65s,A5s,A4s",
    "condensed": "JJ-TT,88-77,AQo,KQ,QJs,QTs,Q8s,A9s,K9s,98s,T9s",
    "polar": "QQ,99,66,AQs,Q9s,53s,75s:0.5,AKo,AJs,KJs,JTs,T8s,87s",
}
KK5 = {  # Kc Kd 5h 9s 2c
    "condensed": "QQ-TT,88-66,A9s,98s,T9s,J9s,A5s,65s,AQo,AJo",
    "polar": "AK,KQ,KJs,KTs,99,55,22:0.5,QJs,JTs,T8s,87s,76s,43s,A4s,A3s",
}
AA77 = {  # As Ac 7h 7d 2s
    "condensed": "KK-88,66-33,KQ,KJs,QJs,JTs,T9s,98s,87s,76s",
    "polar": "AK,AQ,AJs,ATs,A9s,77,A2s,K7s,Q7s,65s,54s,43s,86s,T8s,96s",
}
A833 = {  # Ah 8c 3d 3s Jc
    "condensed": "AQ,AT,A9s,KJs,QJs,JTs,J9s,88:0.5,TT-99,KK-QQ",
    "polar": "AA,JJ,88,AK,AJ,A3s,KQs,KTs,QTs,T9s,97s,76s,65s,54s:0.5",
}
T44 = {  # Td 4c 4s 8h 2d
    "polar_oop": "TT,88,22,A4s,54s,T8s,A3s,65s,76s,Q9s,K9s,J9s,KQo",
    "condensed_ip": "AT,KT,QT,JTs,T9s,99,77-55,A8s,98s,87s,JJ:0.5",
}
JT89 = {  # Jh Th 8c 9h 2s
    "condensed": "AA-QQ,AJo,KJo,ATo,KTs,A9s,K9s,T9s,98s,J8s",
    "polar": "KQ,QJs,Q9s,77,T7s,AKs,A5s,K5s,76s,65s,54s,22:0.5",
}
S9876 = {  # 9s 8s 6d 7c Ks
    "condensed": "AKo,KQo,KJo,KTo,AA-QQ,99,88:0.5,98s,97s:0.5",
    "polar": "JT,T9s,T5s,54s,53s,AQs,AJs,A4s,KK,QJo,J4s,43s",
}
QJ5H = {  # Qh Jh 5h 2c 4h
    "condensed": "AQo,KQo,KJo,QTs,JTs,AJo,Q9s,J9s,TT-66,33",
    "polar": "AK,AT,A9,K9s,K8s,T9s,98s,87s,76s,63s,QQ",
}
T976 = {  # Tc 9c 7d 6c 3h
    "condensed": "AT,KT,QTs,JTs,TT:0.25,A9s,K9s,Q9s,AA-JJ",
    "polar": "J8s,85s,98s,87s,AKs,AQs,KQs,A5s,54s,42s,TT,99:0.5",
    "wide_oop": "22-99,A2s+,K9s+,Q9s+,J9s+,T8s+,97s+,86s+,75s+,64s+,54s,ATo+,KTo+,QJo",
    "wide_ip": "22+,A2s+,KTs+,QTs+,JTs,T9s,98s,87s,76s,65s,ATo+,KQo",
}
A875 = {  # 8d 7d 5s 4c Ad
    "wide_oop": "22-99,A2s+,K9s+,Q9s+,J9s+,T8s+,97s+,86s+,75s+,64s+,54s,ATo+,KTo+,QJo",
    "wide_ip": "22+,A2s+,KTs+,QTs+,JTs,T9s,98s,87s,76s,65s,ATo+,KQo",
    "condensed": "AJ,AT,A9s,A9o:0.5,K8s,Q8s,J8s,98s,88,77,TT-JJ",
    "polar": "K6s,Q6s,J6s,T6s,96s,76s,66,KQs,KJs,QJs,JTs,T9s,32s",
}
KQJ = {  # Kh Qd Jc 4s 2h
    "polar_oop": "AT,T9s,KK,QQ,KQs,KJs,A3s,A5s,65s,76s,87s,53s",
    "condensed_ip": "AK,AQ,AJ,KTs,QTs,JTs,TT-99,K9s,Q9s",
}
Q7654 = {  # 6h 5h 4d 7s Qh
    "condensed": "AQ,KQ,QJ,QT,77,66:0.5,A6s,76s:0.5,65s,AA-JJ",
    "polar": "98s,86s,83s,A8s,A3s,K3s,AKs,KJs,JTs,T9s,K9s:0.5",
}


def sizes(oop_bets, ip_bets, raises=(), allin=True, oop_raises=None, ip_raises=None) -> Dict:
    return {"oop": {"bets": list(oop_bets), "raises": list(raises if oop_raises is None else oop_raises), "allin": allin},
            "ip": {"bets": list(ip_bets), "raises": list(raises if ip_raises is None else ip_raises), "allin": allin}}


def river(id_, title, board, spr, oop, ip, sz, tags, max_raises=1, expected=None) -> Dict:
    return {"id": id_, "street": "river", "title": title, "board": board.split(), "pot": 100,
            "stacks": [spr * 100, spr * 100], "range_text": {"oop": oop, "ip": ip}, "sizes": sz,
            "max_raises": max_raises, "tags": tags, "expected": expected or []}


def turn(id_, title, board, spr, oop, ip, sz, river_sz, tags, max_raises=1) -> Dict:
    d = river(id_, title, board, spr, oop, ip, sz, tags, max_raises)
    d["street"] = "turn"
    d["river_sizes"] = river_sz
    return d


B1, B2, B3 = "Ks 7d 2c 4h 9s", "Jc 8d 3s Ks 2h", "Qd 6c 2h 9s 4d"
B4, B5, B6, B7 = "Kc Kd 5h 9s 2c", "As Ac 7h 7d 2s", "Ah 8c 3d 3s Jc", "Td 4c 4s 8h 2d"
W1, W2, W3 = "Jh Th 8c 9h 2s", "9s 8s 6d 7c Ks", "Qh Jh 5h 2c 4h"
W4, W5, W6, W7 = "Tc 9c 7d 6c 3h", "8d 7d 5s 4c Ad", "Kh Qd Jc 4s 2h", "6h 5h 4d 7s Qh"

SPOTS: List[Dict] = [
    # ------------------------------------------------------------------ trivial
    river("r01", "Trivial: OOP holds only top set, IP holds only high-card air", B1, 1,
          "KK", "QJs,T8s,65s,63s", sizes([0.5], [0.5]), ["trivial", "dry"],
          expected=[
              {"nodes": r"^x$", "actor": "ip", "action": "x", "min": 0.98,
               "why": "a bet with zero equity is only ever called or raised"},
              {"nodes": r"^b[0-9.]+$", "actor": "ip", "action": "f", "min": 0.98,
               "why": "calling with zero equity loses the call"},
          ]),
    river("r02", "Trivial: IP holds only sets, OOP holds only high-card air", B2, 1,
          "T9s,76s,54s,Q9s", "KK,JJ", sizes([0.5], [0.5]), ["trivial", "dry"],
          expected=[
              {"nodes": r"^$", "actor": "oop", "action": "x", "min": 0.98,
               "why": "a bet with zero equity is only ever called or raised"},
              {"nodes": r"^x b[0-9.]+$", "actor": "oop", "action": "f", "min": 0.98,
               "why": "calling with zero equity loses the call"},
          ]),
    river("r03", "Trivial: royal flush on the board, every hand splits", "Ah Kh Qh Jh Th", 2,
          "22+,A2s+,KQo:0.5", "99+,AK,KQ,QJs", sizes([0.5], [0.5]), ["trivial", "wet"],
          expected=[
              {"nodes": r"^b[0-9.]+$", "actor": "ip", "action": "f", "max": 0.02,
               "why": "folding gives up half the pot, calling always splits it"},
          ]),
    # ---------------------------------------------------------------- dry boards
    river("r04", "Dry K72-94, condensed OOP vs polar IP, one size", B1, 1.5,
          K72["condensed"], K72["polar"], sizes([0.5], [0.75]), ["dry", "polar", "condensed"]),
    river("r05", "Dry K72-94, polar IP with two sizes and a raise size", B1, 3,
          K72["condensed"], K72["polar"], sizes([0.5], [0.33, 1.0], [0.5]), ["dry", "polar", "condensed", "raise-size"]),
    river("r06", "Dry KJ832, SPR 0.5, small bet or all in", B2, 0.5,
          JK8["condensed"], JK8["polar"], sizes([0.25], [0.25]), ["dry", "polar", "condensed", "low-spr"]),
    river("r07", "Dry KJ832, SPR 5, three IP sizes", B2, 5,
          JK8["condensed"], JK8["polar"], sizes([0.33], [0.33, 0.75, 1.5], [0.5]),
          ["dry", "polar", "condensed", "raise-size", "three-sizes"]),
    river("r08", "Dry Q9642, two wide ranges", B3, 2,
          Q96["wide_oop"], Q96["wide_ip"], sizes([0.66], [0.66]), ["dry", "wide"]),
    river("r09", "Paired KK952, condensed OOP vs polar IP", B4, 1,
          KK5["condensed"], KK5["polar"], sizes([0.5], [0.75]), ["dry", "paired", "polar", "condensed"]),
    river("r10", "Double-paired AA772, polar IP with two sizes", B5, 2,
          AA77["condensed"], AA77["polar"], sizes([0.5], [0.5, 1.25]), ["dry", "paired", "polar", "condensed"]),
    river("r11", "Paired AJ833, SPR 4, three IP sizes up to 2x pot", B6, 4,
          A833["condensed"], A833["polar"], sizes([0.5], [0.25, 0.75, 2.0]),
          ["dry", "paired", "polar", "condensed", "three-sizes"]),
    river("r12", "Paired T8442, OOP polar lead into condensed IP", B7, 1.5,
          T44["polar_oop"], T44["condensed_ip"], sizes([0.75], [0.5]), ["dry", "paired", "polar", "condensed"]),
    river("r21", "Dry K72-94, two wide ranges, SPR 1", B1, 1,
          K72["wide_oop"], K72["wide_ip"], sizes([0.5], [0.5]), ["dry", "wide"]),
    river("r22", "Dry KJ832, OOP polar lead with two sizes", B2, 3,
          JK8["polar_oop"], JK8["condensed_ip"], sizes([0.75, 1.5], [0.5]), ["dry", "polar", "condensed"]),
    river("r27", "Double-paired AA772, SPR 0.5", B5, 0.5,
          AA77["condensed"], AA77["polar"], sizes([0.33], [0.33]), ["dry", "paired", "polar", "condensed", "low-spr"]),
    river("r28", "Paired KK952, SPR 5, IP overbets", B4, 5,
          KK5["condensed"], KK5["polar"], sizes([0.5], [1.0, 2.5]), ["dry", "paired", "polar", "condensed", "overbet"]),
    river("r30", "Dry Q9642, polar IP pot-size bet", B3, 1.5,
          Q96["condensed"], Q96["polar"], sizes([1.0], [1.0]), ["dry", "polar", "condensed"]),
    # ---------------------------------------------------------------- wet boards
    river("r13", "Wet JT982 three hearts, polar IP with two sizes", W1, 2,
          JT89["condensed"], JT89["polar"], sizes([0.33], [0.5, 1.0]), ["wet", "polar", "condensed"]),
    river("r14", "Wet JT982 three hearts, SPR 0.5", W1, 0.5,
          JT89["condensed"], JT89["polar"], sizes([0.33], [0.33]), ["wet", "polar", "condensed", "low-spr"]),
    river("r15", "Wet K9876 three spades, raise size", W2, 3,
          S9876["condensed"], S9876["polar"], sizes([0.5], [0.75], [0.5]), ["wet", "polar", "condensed", "raise-size"]),
    river("r16", "Four hearts QJ542, condensed OOP vs polar IP", W3, 1,
          QJ5H["condensed"], QJ5H["polar"], sizes([0.5], [0.33, 0.75]), ["wet", "four-flush", "polar", "condensed"]),
    river("r17", "Wet T9763 three clubs, SPR 5, three IP sizes", W4, 5,
          T976["condensed"], T976["polar"], sizes([0.5], [0.5, 1.0, 2.0], [0.5]),
          ["wet", "polar", "condensed", "raise-size", "three-sizes"]),
    river("r18", "Wet A8754 three diamonds, two wide ranges", W5, 1.5,
          A875["wide_oop"], A875["wide_ip"], sizes([0.5], [0.5]), ["wet", "wide"]),
    river("r19", "Broadway KQJ42, OOP polar pot-size lead", W6, 2,
          KQJ["polar_oop"], KQJ["condensed_ip"], sizes([1.0], [0.5]), ["wet", "polar", "condensed"]),
    river("r20", "Wet Q7654 three hearts, two IP sizes", W7, 3,
          Q7654["condensed"], Q7654["polar"], sizes([0.33], [0.33, 0.75]), ["wet", "polar", "condensed"]),
    river("r23", "Wet K9876 three spades, SPR 0.5", W2, 0.5,
          S9876["condensed"], S9876["polar"], sizes([0.25], [0.25]), ["wet", "polar", "condensed", "low-spr"]),
    river("r24", "Four hearts QJ542, SPR 5, a raise and a reraise", W3, 5,
          QJ5H["condensed"], QJ5H["polar"], sizes([0.33], [0.33], [0.5]), ["wet", "four-flush", "polar", "condensed",
                                                                            "raise-size", "reraise"], max_raises=2),
    river("r25", "Wet T9763, two wide ranges, two IP sizes", W4, 1,
          T976["wide_oop"], T976["wide_ip"], sizes([0.5], [0.33, 0.66]), ["wet", "wide"]),
    river("r26", "Wet A8754, polar IP with three sizes", W5, 2,
          A875["condensed"], A875["polar"], sizes([0.33], [0.33, 0.75, 1.5]), ["wet", "polar", "condensed", "three-sizes"]),
    river("r29", "Wet JT982, OOP polar lead into condensed IP, raise size", W1, 4,
          JT89["polar"], JT89["condensed"], sizes([0.75], [0.5], [0.5]), ["wet", "polar", "condensed", "raise-size"]),
    # ------------------------------------------------------------------ turn
    turn("t01", "Turn: dry K724, condensed OOP vs polar IP", "Ks 7d 2c 4h", 3,
         "QQ-88,KQo,KJ,KTs,A7s,98s,87s,76s,65s", "AK,KK:0.5,77:0.5,K9s,QJs,QTs,JTs,65s,A5s,A3s,T9s",
         sizes([0.5], [0.5]), sizes([0.5], [0.5]), ["dry", "polar", "condensed"]),
    turn("t02", "Turn: wet JT82 two hearts", "Jh Th 8c 2s", 2,
         "AJo,KJo,ATo,KTs,A9s,K9s,T9s,98s,J8s,QQ-99", "KQ,QJs,Q9s,97s,AKs,A5s,K5s,76s,65s,88:0.5,22",
         sizes([0.5], [0.5]), sizes([0.5], [0.5]), ["wet", "polar", "condensed"]),
    turn("t03", "Turn: three hearts QJ52, SPR 5, two river sizes", "Qh Jh 5h 2c", 5,
         "AQo,KQo,KJo,QTs,JTs,AJo,TT-66", "AK,AT,A9,K9s,T9s,98s,87s,QQ,55,22:0.5",
         sizes([0.33], [0.33]), sizes([0.5, 1.0], [0.5, 1.0]), ["wet", "polar", "condensed"]),
    turn("t04", "Turn: paired AA72, SPR 1", "As Ac 7h 2d", 1,
         "KK-88,66-33,KQ,KJs,QJs,JTs,T9s,98s,87s,76s", "AK,AQ,AJs,ATs,A9s,77,22,K7s,65s,54s,43s,86s,T8s",
         sizes([0.25], [0.25]), sizes([0.4], [0.4]), ["dry", "paired", "polar", "condensed"]),
    turn("t05", "Turn: dry KJ83, SPR 0.5", "Jc 8d 3s Ks", 0.5,
         "QQ-99,KTs,KQo,KJo,QJs,JTs,J9s,A8s,98s,T8s", "AK,KK,JJ,88:0.5,KJs,QTs,T9s,A5s,A4s,76s",
         sizes([0.2], [0.2]), sizes([0.2], [0.2]), ["dry", "polar", "condensed", "low-spr"]),
    turn("t06", "Turn: wet K986 two spades, two river sizes", "9s 8s 6d Kc", 1.5,
         "AKo,KQo,KJo,AA-QQ,99,88:0.5,98s,A9s,T9s", "JT,T7s,75s,AQs,AJs,A5s,KK,66,QJo,J7s,54s",
         sizes([0.5], [0.5]), sizes([0.25, 0.4], [0.25, 0.4]), ["wet", "polar", "condensed"]),
    turn("t07", "Turn: paired T844, SPR 4, two turn sizes", "Td 4c 4s 8h", 4,
         "AT,KT,QT,JTs,T9s,99,77-55,A8s,98s,87s", "TT,88,A4s,54s,T8s,A3s,65s,76s,Q9s,K9s,J9s,KQo",
         sizes([0.5, 1.0], [0.5, 1.0]), sizes([0.5], [0.5]), ["dry", "paired", "polar", "condensed"]),
    turn("t08", "Turn: wet 8754 two diamonds", "8d 7d 5s 4c", 2,
         "AA-88,A8s,A7s,K8s,Q8s,J8s,T8s,98s,87s", "63s,96s,T9s,65s,AKs,KQs,QJs,22,44,55",
         sizes([0.33], [0.33]), sizes([0.5], [0.5]), ["wet", "polar", "condensed"]),
    turn("t09", "Turn: AJ83 two clubs, big turn bet, two river sizes", "Ah 8c 3d Jc", 3,
         "AQ,AT,A9s,KJs,QJs,JTs,J9s,TT-99,KK-QQ,88:0.5", "AA,JJ,88,33,AK,AJ,KQs,KTs,QTs,T9s,97s,76s,65s,54s",
         sizes([0.75], [0.75]), sizes([0.5, 0.8], [0.5, 0.8]), ["dry", "polar", "condensed"]),
    turn("t10", "Turn: broadway KQJ4, SPR 5, turn raise size", "Kh Qd Jc 4s", 5,
         "AK,AQ,AJ,KTs,QTs,JTs,TT-99,K9s,Q9s", "AT,T9s,KK,QQ,KQs,KJs,A5s,65s,76s,87s,53s",
         sizes([0.5], [0.5], [0.5]), sizes([0.5], [0.5]), ["wet", "condensed", "polar", "raise-size"]),
]
