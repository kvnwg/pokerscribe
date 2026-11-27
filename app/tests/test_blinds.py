"""The blinds decide whether you're short-stacked, and a short stack is the only reason to
go all in with an ordinary hand. So they only come from a labelled line on the table or
from the chips the blinds put in, never from any "number/number" on screen."""
from app.poker.advice import advise
from app.recognition.amounts import has_blinds_label, parse_blinds
from app.recognition.layout import LayoutResult, _find_blinds
from app.recognition.tracker import HandTracker
from app.state.model import Field
from app.tests.test_advice import table
from app.tests.test_tracker import FULL, capture
from app.vision.ocr import TextBox


def _box(text: str) -> TextBox:
    return TextBox(text=text, x=10, y=10, w=60, h=14, confidence=0.95)


def _blinds_from(*texts: str):
    res = LayoutResult()
    _find_blinds(res, [_box(t) for t in texts], set())
    return res.blinds


def test_dates_and_counts_are_not_blinds():
    for text in ["11/26", "3/5", "Seat 3/5", "Players 4/5", "Hand #25/50", "Thu 11/26 12:43", "1/2 Pot"]:
        assert _blinds_from(text) is None, text
    assert not has_blinds_label("11/26")


def test_labelled_blinds_are_read():
    assert _blinds_from("11/26", "Blinds 1/2") == (1, 2)
    assert _blinds_from("NL Hold'em $1/$2") == (1, 2)
    assert _blinds_from("$25/$50") == (25, 50)
    assert parse_blinds("Level 3/10  Blinds 25/50") == (25, 50)
    assert parse_blinds("25/50 ante 5") == (25, 50)


def test_raises_by_the_blinds_are_not_taken_for_blinds():
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    st = capture(dict(FULL, John=999, Mike=998), pot=3)  # blinds 1/2 posted
    assert t.update(st).valid and st.blinds.value == (1, 2)
    t.update(capture(dict(FULL, John=999, Mike=1001), cards=None))  # the big blind wins it
    # next hand: two captures were missed. The small blind (Mike) raised to 6 and the big
    # blind (George) re-raised to 18: that is not a 6/18 game.
    pos = {"hero": "BTN", "Deja": "CO", "John": "HJ", "Mike": "SB", "George": "BB"}
    t.update(capture(dict(FULL, John=999, Mike=1001), cards=("Qs", "9d"), positions=pos))
    t.update(capture(dict(FULL, John=999, Mike=995), cards=("Qs", "9d"), pot=8, positions=pos))
    st = capture(dict(FULL, John=999, Mike=995, George=982), cards=("Qs", "9d"), pot=24, positions=pos)
    info = t.update(st)
    assert info.valid and st.blinds.value == (1, 2)


def test_chips_overrule_blinds_read_from_the_screen():
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    st = capture(dict(FULL, John=999, Mike=998), pot=3)
    st.blinds = Field.auto((25.0, 50.0), 0.9, 0.5)  # a misread line of text
    t.update(st)
    assert st.blinds.value == (1, 2) and st.blinds.source == "derived"


def test_q9_offsuit_deep_is_never_all_in():
    """The reported hand: about 300 chips against 400 at blinds 1/2 (150 big blinds)."""
    for pos in ["UTG", "HJ", "CO", "BTN", "SB", "BB"]:
        opp = "BB" if pos != "BB" else "SB"
        folded = [p for p in ["BTN", "SB", "BB", "UTG", "HJ", "CO"] if p not in (pos, opp, "SB", "BB")]
        for bets in [{"SB": 1, "BB": 2}, {"SB": 1, "BB": 2, opp: 6}, {"SB": 1, "BB": 2, opp: 20}]:
            bets = dict(bets)
            to_call = max(bets.values()) - bets.get(pos, 0)
            a = advise(table(["Qs", "9d"], pos, stacks={pos: 300.0, opp: 400.0}, bets=bets, folded=folded,
                             blinds=(1, 2), to_call=to_call, pot=0), budget_ms=150)
            assert a.action != "all-in", (pos, bets, a.headline, a.reason)


def test_bigger_blinds_need_two_hands_to_be_believed():
    t = HandTracker()
    pos = {"hero": "CO", "Deja": "BTN", "John": "SB", "Mike": "BB", "George": "HJ"}
    t.update(capture(FULL, cards=None, positions=pos))
    st = capture(dict(FULL, John=999, Mike=998), pot=3, positions=pos)
    assert t.update(st).valid and st.blinds.value == (1, 2)
    # a capture that already shows your call of 2, the small blind's raise to 6 and the big
    # blind's re-raise to 18: one such hand doesn't make it a 6/18 game. (With nothing of yours
    # in, it couldn't be raises: before the flop the blinds act after you.)
    t.update(capture(dict(FULL, John=999, Mike=1001), cards=None, positions=pos))
    st = capture(dict(FULL, hero=998, John=993, Mike=983), cards=("Qs", "9d"), pot=26, positions=pos)
    assert t.update(st).valid and st.blinds.value == (1, 2)


def test_blinds_that_go_up_are_believed_on_your_first_move():
    """Kevin: "the game still gets confused thinking blinds are reraises". In a tournament the
    blinds went up from 1/2 to 2/4. The tracker kept 1/2 until 2/4 had been seen in two hands,
    so the big blind's 4 was a raise to two big blinds and the hijack's open to 10 a re-raise:
    "a raise and a re-raise", fold. On your first move before the flop (not in the blinds,
    nothing put in) nobody after you has acted yet, so the blinds' chips are the blinds."""
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    st = capture(dict(FULL, John=999, Mike=998), pot=3)  # blinds 1/2
    assert t.update(st).valid and st.blinds.value == (1, 2)
    t.update(capture(dict(FULL, John=999, Mike=1001), cards=None))  # the big blind wins it
    # blinds 2/4 now: John posts 2, Mike 4, George (hijack) opens to 10, your move (cutoff)
    st = capture(dict(FULL, John=997, Mike=997, George=990), cards=("Ah", "Qs"), pot=16)
    assert t.update(st).valid and st.blinds.value == (2, 4)
    a = advise(st, budget_ms=150)
    assert "a raise and a re-raise" not in a.reason, (a.headline, a.reason)
    # the next hand's first picture is missed: the blinds carried over are the new ones
    t.update(capture(dict(FULL, John=997, Mike=997, George=1006), cards=None))  # George wins it
    t.update(capture(dict(FULL, John=995, Mike=993, George=996, Deja=990), cards=None))
    st = capture(dict(FULL, John=995, Mike=993, George=996, Deja=990, hero=990), cards=("Ah", "Qs"), pot=36)
    assert t.update(st).valid and st.blinds.value == (2, 4)


def test_a_blinds_line_beats_blinds_carried_over_from_earlier_hands():
    """The blinds went up and the first picture of the hand was missed, so the chips the blinds
    posted weren't seen alone. The 1/2 of earlier hands were carried over and overruled the
    table's own line, "Blinds 2/4", which the chips posted fit."""
    t = HandTracker()
    t.update(capture(FULL, cards=None))
    st = capture(dict(FULL, John=999, Mike=998), pot=3)
    assert t.update(st).valid and st.blinds.value == (1, 2)
    t.update(capture(dict(FULL, John=999, Mike=1001), cards=None))
    t.update(capture(dict(FULL, John=997, Mike=997), cards=None))  # 2/4 posted, no cards read yet
    st = capture(dict(FULL, John=997, Mike=997, George=990), cards=("Ah", "Qs"), pot=16)
    st.blinds = Field.auto((2.0, 4.0), 0.9, 0.5)
    t.update(st)
    assert st.blinds.value == (2, 4)
