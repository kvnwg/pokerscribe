"""Preflop charts: sizes in line with published 6-max 100bb solver charts, key hands in
the right place, solver spot checks, every chart line readable, and only the documented
answers ever come back."""
import pytest

from app.poker import charts
from app.poker.ranges import PREFLOP_RANKING

HANDS = list(PREFLOP_RANKING)  # all 169 starting-hand classes
OPEN_SEATS = ["UTG", "UTG+1", "UTG+2", "MP", "LJ", "HJ", "CO", "BTN", "SB", "BTN/SB"]
RESPONDERS = ["UTG+1", "UTG+2", "MP", "LJ", "HJ", "CO", "BTN", "SB", "BB"]
ODD = [None, "BB", "??"]  # seats the reader might hand over by mistake


def combos(cls):
    if len(cls) == 2:
        return 6
    return 4 if cls.endswith("s") else 12


def share(pred, hands=HANDS):
    """Share of the given hands (by combinations) for which pred(hand) is true."""
    total = sum(combos(c) for c in hands)
    return sum(combos(c) for c in hands if pred(c)) / total


def open_share(pos):
    return share(lambda c: charts.opens(pos, c))


def defend_share(pos, opener):
    return share(lambda c: charts.vs_open(pos, opener, c) != "fold")


def in_position(opened_from, reraiser):
    # same rule as the advice: a blind that re-raises acts first after the flop, except
    # that the small blind is out of position against the big blind
    return reraiser in ("SB", "BB") and opened_from != "SB"


# --- every chart line reads ---------------------------------------------------------------

def chart_lines():
    for name, line in charts.OPEN.items():
        yield f"OPEN {name}", line, False
    for key, (raise_txt, call_txt) in charts.VS_OPEN.items():
        yield f"VS_OPEN {key} raise", raise_txt, False
        yield f"VS_OPEN {key} call", call_txt, key[0] == "SB"  # the small blind never flats
    for key, (raise_txt, call_txt) in charts.VS_3BET.items():
        yield f"VS_3BET {key} raise", raise_txt, False
        yield f"VS_3BET {key} call", call_txt, False
    for name, pair in (("VS_4BET", charts.VS_4BET), ("SQUEEZE", charts.SQUEEZE),
                       ("COLD_VS_3BET", charts.COLD_VS_3BET)):
        yield f"{name} raise", pair[0], False
        yield f"{name} call", pair[1], False
    for name, line in charts.ISO.items():
        yield f"ISO {name}", line, False
    yield "OVERLIMP", charts.OVERLIMP, False


@pytest.mark.parametrize("name,line,may_be_empty", list(chart_lines()), ids=lambda v: str(v)[:40])
def test_every_chart_line_parses(name, line, may_be_empty):
    if may_be_empty and not line:
        return
    classes = charts._classes(line)
    assert classes, name
    assert classes <= set(HANDS), (name, sorted(classes - set(HANDS)))


def test_a_hand_sits_in_one_list_only():
    pairs = list(charts.VS_OPEN.items()) + list(charts.VS_3BET.items()) + [
        ("VS_4BET", charts.VS_4BET), ("SQUEEZE", charts.SQUEEZE), ("COLD_VS_3BET", charts.COLD_VS_3BET)]
    for key, (raise_txt, call_txt) in pairs:
        if call_txt:
            both = charts._classes(raise_txt) & charts._classes(call_txt)
            assert not both, (key, sorted(both))


# --- chart sizes --------------------------------------------------------------------------

@pytest.mark.parametrize("pos,low,high", [
    ("UTG+1", 0.09, 0.14),  # full ring early seats
    ("UTG", 0.15, 0.18),
    ("HJ", 0.19, 0.25),
    ("CO", 0.26, 0.32),
    ("BTN", 0.40, 0.48),
    ("SB", 0.40, 0.50),
    ("BTN/SB", 0.40, 0.48),  # heads-up button
])
def test_open_sizes(pos, low, high):
    assert low <= open_share(pos) <= high, (pos, open_share(pos))


def test_opens_widen_toward_the_button():
    sizes = [open_share(p) for p in ("UTG+1", "UTG", "HJ", "CO", "BTN")]
    assert sizes == sorted(sizes) and len(set(sizes)) == len(sizes), sizes


def test_full_ring_seats():
    for pos in ("UTG+1", "UTG+2", "MP"):  # six or more players still to act
        assert open_share(pos) < open_share("UTG"), pos
    assert open_share("LJ") == open_share("UTG")  # five players behind, like 6-max UTG
    assert charts.opens("BB", "AA") is None  # the big blind never opens
    assert charts.opens(None, "AA") is None


@pytest.mark.parametrize("opener,low,high", [
    ("UTG", 0.25, 0.35),
    ("HJ", 0.30, 0.40),
    ("CO", 0.37, 0.48),
    ("BTN", 0.55, 0.65),
    ("SB", 0.60, 0.70),
])
def test_big_blind_defence(opener, low, high):
    assert low <= defend_share("BB", opener) <= high, (opener, defend_share("BB", opener))


def test_defence_widens_against_later_raisers():
    bb = [defend_share("BB", o) for o in ("UTG", "HJ", "CO", "BTN", "SB")]
    assert bb == sorted(bb), bb
    sb = [defend_share("SB", o) for o in ("UTG", "HJ", "CO", "BTN")]
    assert sb == sorted(sb), sb
    btn = [defend_share("BTN", o) for o in ("UTG", "HJ", "CO")]
    assert btn == sorted(btn), btn
    assert 0.20 <= defend_share("BTN", "CO") <= 0.30
    assert 0.05 <= defend_share("SB", "UTG") <= 0.10
    assert 0.13 <= defend_share("SB", "BTN") <= 0.20


def test_small_blind_reraises_or_folds():
    for opener in ("UTG", "HJ", "CO", "BTN"):
        assert all(charts.vs_open("SB", opener, c) != "call" for c in HANDS), opener


@pytest.mark.parametrize("opened_from,reraiser,low,high", [
    # 6-max seats keep about a third to a half of the hands they opened
    ("UTG", "HJ", 0.28, 0.50), ("UTG", "BB", 0.28, 0.50), ("HJ", "CO", 0.28, 0.50),
    ("HJ", "SB", 0.28, 0.50), ("CO", "BTN", 0.28, 0.50), ("CO", "BB", 0.28, 0.50),
    ("BTN", "SB", 0.28, 0.50), ("BTN", "BB", 0.28, 0.50), ("SB", "BB", 0.28, 0.50),
    ("BTN/SB", "BB", 0.28, 0.50),
    # a full ring early seat opened only strong hands, so it keeps more of them
    ("UTG+1", "BTN", 0.45, 0.70),
])
def test_facing_a_3bet(opened_from, reraiser, low, high):
    ip = in_position(opened_from, reraiser)
    opened = [c for c in HANDS if charts.opens(opened_from, c)]
    goes_on = [c for c in HANDS if charts.vs_3bet(c, ip, opened_from) != "fold"]
    # you only ever continue with hands you opened
    assert set(goes_on) <= set(opened), sorted(set(goes_on) - set(opened))
    kept = share(lambda c: charts.vs_3bet(c, ip, opened_from) != "fold", opened)
    assert low <= kept <= high, (opened_from, reraiser, kept)
    # out of position the solver 4-bets more and calls less, so allow up to a quarter
    four_bets = share(lambda c: charts.vs_3bet(c, ip, opened_from) == "raise", opened)
    assert 0.05 <= four_bets <= 0.25, (opened_from, reraiser, four_bets)


# --- key hands ----------------------------------------------------------------------------

def test_aces_always_raise():
    for pos in OPEN_SEATS:
        assert charts.opens(pos, "AA") is True, pos
    for pos in RESPONDERS:
        for opener in OPEN_SEATS:
            assert charts.vs_open(pos, opener, "AA") == "raise", (pos, opener)
    for opener in OPEN_SEATS:
        for ip in (True, False):
            assert charts.vs_3bet("AA", ip, opener) == "raise", (opener, ip)
    assert charts.vs_4bet("AA") == "all-in"
    assert charts.cold_vs_3bet("AA") == "raise"
    assert charts.vs_squeeze_spot("AA") == "raise"
    for pos in RESPONDERS + ["UTG"]:
        assert charts.vs_limpers(pos, "AA") == "raise", pos


def test_seven_deuce_offsuit_always_folds():
    for pos in OPEN_SEATS:
        assert charts.opens(pos, "72o") is False, pos
    for pos in RESPONDERS:
        for opener in OPEN_SEATS:
            assert charts.vs_open(pos, opener, "72o") == "fold", (pos, opener)
    for opener in OPEN_SEATS:
        for ip in (True, False):
            assert charts.vs_3bet("72o", ip, opener) == "fold"
    assert charts.vs_4bet("72o") == "fold"
    assert charts.cold_vs_3bet("72o") == "fold"
    assert charts.vs_squeeze_spot("72o") == "fold"
    for pos in RESPONDERS + ["UTG"]:
        assert charts.vs_limpers(pos, "72o") == ("check" if pos == "BB" else "fold"), pos


@pytest.mark.parametrize("pos,opener", [
    ("BB", "UTG"), ("BB", "HJ"), ("BB", "CO"), ("BB", "BTN"), ("BB", "SB"),
    ("SB", "UTG"), ("SB", "HJ"), ("SB", "CO"), ("SB", "BTN"),
    ("HJ", "UTG"), ("CO", "UTG"), ("CO", "HJ"), ("BTN", "UTG"), ("BTN", "HJ"), ("BTN", "CO"),
])
def test_ace_five_suited_is_a_reraise_bluff(pos, opener):
    assert charts.vs_open(pos, opener, "A5s") == "raise"


def test_reraise_bluffs_are_polar():
    # against the button the big blind re-raises A5s (blocker, plays well) but just calls
    # the stronger-looking A8s, which would rather see a flop
    assert charts.vs_open("BB", "BTN", "A5s") == "raise"
    assert charts.vs_open("BB", "BTN", "A8s") == "call"
    for opener in ("UTG", "HJ", "CO", "BTN", "SB"):
        assert charts.vs_3bet("A5s", in_position(opener, "BB"), opener) == "raise", opener


def test_big_blind_defends_k7s_against_the_button():
    assert charts.vs_open("BB", "BTN", "K7s") == "call"
    assert charts.vs_open("BB", "BTN/SB", "K7s") == "call"  # heads-up too


# --- spot checks against solver answers (PokerBench preflop test set) ---------------------

SOLVER_OPENS = {
    "SB": "QJo KJo T8o 85s QTo J6s T9s T6s T9o 87s K9s A9o A6o K5s J9o A3s AKo 66 A5o Q3s",
    "BTN": "KTs A5o 55 KJs AQo 22 T8s K7s Q6s Q9o K8s ATo 33",
    "CO": "KJo KQo QTo AKo 98s Q6s Q7s AJo J9s A8s AJs",
    "HJ": "A9o K8s QJo AJs Q8s ATo K5s J9s 99",
    "UTG": "AKo KQo 77 99 AJo AQs",
}


@pytest.mark.parametrize("pos,hand", [(p, h) for p, hs in SOLVER_OPENS.items() for h in hs.split()])
def test_solver_opens(pos, hand):
    assert charts.opens(pos, hand) is True


SOLVER_VS_OPEN = [
    ("BB", "UTG", "AA", "raise"), ("BB", "UTG", "55", "call"), ("BB", "UTG", "K8o", "fold"),
    ("BB", "HJ", "AKs", "raise"), ("BB", "HJ", "T9o", "call"), ("BB", "HJ", "KQo", "call"),
    ("BB", "HJ", "86s", "call"), ("BB", "CO", "JTo", "call"), ("BB", "CO", "QTo", "call"),
    ("BB", "CO", "Q8s", "call"), ("BB", "BTN", "T9o", "call"), ("BB", "BTN", "AKs", "raise"),
    ("BB", "BTN", "44", "call"), ("BB", "BTN", "A8o", "call"), ("BB", "SB", "KK", "raise"),
    ("BB", "SB", "A4o", "call"), ("BB", "SB", "AQo", "raise"), ("BB", "SB", "T9o", "call"),
    ("BB", "SB", "J5s", "call"), ("BB", "SB", "AKo", "raise"), ("BB", "SB", "Q9o", "call"),
    ("BB", "SB", "98s", "raise"), ("BB", "SB", "32s", "call"), ("BB", "SB", "K7s", "call"),
    ("SB", "CO", "AJo", "raise"), ("SB", "CO", "QQ", "raise"), ("SB", "CO", "AQo", "raise"),
    ("SB", "HJ", "KQo", "raise"), ("SB", "HJ", "A5s", "raise"), ("SB", "UTG", "KQo", "raise"),
    ("SB", "UTG", "AKo", "raise"), ("SB", "BTN", "QTs", "raise"), ("CO", "UTG", "AQo", "raise"),
    ("CO", "UTG", "KJs", "raise"), ("CO", "HJ", "A3s", "raise"), ("HJ", "UTG", "AKo", "raise"),
    ("HJ", "UTG", "QQ", "raise"), ("BTN", "CO", "KJo", "raise"), ("BTN", "CO", "K9s", "raise"),
    ("BTN", "UTG", "AQs", "raise"), ("BTN", "UTG", "JTs", "call"),
]


@pytest.mark.parametrize("pos,opener,hand,want", SOLVER_VS_OPEN)
def test_solver_vs_open(pos, opener, hand, want):
    assert charts.vs_open(pos, opener, hand) == want


SOLVER_VS_3BET = [  # (seat you opened from, who re-raised, hand, solver's answer)
    ("HJ", "CO", "ATs", "raise"), ("HJ", "CO", "KJs", "raise"), ("HJ", "BTN", "AQo", "raise"),
    ("HJ", "BTN", "KQs", "raise"), ("HJ", "BTN", "AJs", "call"), ("HJ", "BB", "ATs", "call"),
    ("HJ", "SB", "AQs", "call"), ("CO", "BTN", "AQo", "raise"), ("CO", "BB", "AKs", "raise"),
    ("CO", "BB", "KK", "raise"), ("CO", "BB", "AKo", "raise"), ("CO", "SB", "AQs", "call"),
    ("UTG", "BB", "T9s", "fold"), ("UTG", "BB", "JJ", "call"), ("UTG", "BB", "AJo", "fold"),
    ("UTG", "SB", "JJ", "call"), ("UTG", "SB", "AA", "raise"), ("UTG", "SB", "AKs", "raise"),
    ("BTN", "SB", "AA", "raise"), ("BTN", "SB", "AKo", "raise"), ("BTN", "SB", "AJo", "raise"),
    ("BTN", "BB", "A9s", "call"), ("BTN", "BB", "QQ", "raise"), ("SB", "BB", "JJ", "raise"),
    ("SB", "BB", "ATs", "call"), ("SB", "BB", "T7s", "fold"), ("SB", "BB", "AJo", "raise"),
]


@pytest.mark.parametrize("opened_from,reraiser,hand,want", SOLVER_VS_3BET)
def test_solver_vs_3bet(opened_from, reraiser, hand, want):
    assert charts.vs_3bet(hand, in_position(opened_from, reraiser), opened_from) == want


# --- only the documented answers come back --------------------------------------------------

def test_opens_answers():
    for pos in OPEN_SEATS:
        assert {charts.opens(pos, c) for c in HANDS} == {True, False}, pos
    for pos in ODD:
        assert {charts.opens(pos, c) for c in HANDS} == {None}, pos


def test_vs_open_answers():
    for pos in RESPONDERS + ["UTG", "BTN/SB"] + ODD:
        for opener in OPEN_SEATS + ODD:
            got = {charts.vs_open(pos, opener, c) for c in HANDS}
            assert got <= {"raise", "call", "fold"}, (pos, opener, got)
            assert {"raise", "fold"} <= got, (pos, opener, got)


def test_vs_3bet_answers():
    for opener in OPEN_SEATS + ODD:
        for ip in (True, False):
            got = {charts.vs_3bet(c, ip, opener) for c in HANDS}
            assert got == {"raise", "call", "fold"}, (opener, ip, got)
            assert {charts.vs_3bet(c, ip) for c in HANDS} == {"raise", "call", "fold"}


def test_other_answers():
    assert {charts.cold_vs_3bet(c) for c in HANDS} == {"raise", "call", "fold"}
    assert {charts.vs_4bet(c) for c in HANDS} == {"all-in", "call", "fold"}
    assert {charts.vs_squeeze_spot(c) for c in HANDS} == {"raise", "call", "fold"}
    for pos in RESPONDERS + ["UTG", "BTN/SB"] + ODD:
        got = {charts.vs_limpers(pos, c) for c in HANDS}
        allowed = {"raise", "check"} if pos == "BB" else {"raise", "call", "fold"}
        assert got <= allowed and "raise" in got, (pos, got)
    assert charts.vs_limpers("BTN", "55") in ("raise", "call")


def test_share():
    assert charts.share("") == 0.0
    assert charts.share("AA") == pytest.approx(6 / 1326)
    assert charts.share("AKs") == pytest.approx(4 / 1326)
    assert charts.share("AKo") == pytest.approx(12 / 1326)
    for name, line in charts.OPEN.items():
        assert 0.0 < charts.share(line) < 1.0, name
    assert charts.share(charts.OPEN["BTN"]) == pytest.approx(open_share("BTN"))
