"""Watch mode: learning how each opponent plays, hand after hand."""
from typing import Dict, Optional, Sequence

from app.poker.profiles import MIN_HANDS, PlayerStats, Profiles, classify, describe
from app.recognition.tracker import HandTracker, TrackInfo
from app.state.model import Action, Field, GameState, Player
from app.state.privacy import check_outgoing_text
from app.state.text_format import render_text

NAMES = ["You", "Deja", "John", "Mike", "George"]  # 0 is you
POS = ["CO", "BTN", "SB", "BB", "HJ"]


def table(board: Sequence[str] = (), acts: Optional[Dict[str, str]] = None, names: bool = True,
          folded: Sequence[str] = (), stacks: Optional[Dict[str, float]] = None, blinds=(1.0, 2.0)) -> GameState:
    acts = acts or {}
    players = []
    for i, n in enumerate(NAMES):
        p = Player(seat=i, is_hero=i == 0, name=n if names else "", anchor=None if i == 0 else (100.0 * i, 50.0),
                   position=Field.manual(POS[i]), stack=Field.manual((stacks or {}).get(n, 1000.0)),
                   in_hand=Field.manual(n not in folded))
        if n in acts:
            p.last_action = Field.manual(Action(acts[n]))
        players.append(p)
    st = GameState(hero_cards=[Field.manual("As"), Field.manual("Kd")], board=[Field.manual(c) for c in board],
                   players=players)
    if blinds:
        st.blinds = Field.manual(blinds)
    st.pot = Field.manual(10.0)
    return st


def chips(contrib: Dict[str, float], street: Optional[Dict[str, float]] = None) -> TrackInfo:
    return TrackInfo(valid=True, contributions={NAMES.index(k): v for k, v in contrib.items()},
                     street_bets={NAMES.index(k): v for k, v in (street or {}).items()})


def key(prof: Profiles, name: str) -> str:
    return prof.key_for(Player(seat=NAMES.index(name), name=name, anchor=(100.0 * NAMES.index(name), 50.0)))


def test_counts_each_hand_once_and_credits_the_raise_to_the_raiser():
    prof = Profiles()
    blinds = {"John": 1, "Mike": 2}
    prof.update(table(), chips(blinds), 1)
    prof.update(table(acts={"George": "raise"}), chips(dict(blinds, George=6)), 1)
    prof.update(table(acts={"George": "raise"}), chips(dict(blinds, George=6)), 1)  # the same read again
    prof.update(table(acts={"Deja": "call"}), chips(dict(blinds, George=6, Deja=6)), 1)
    prof.update(table(acts={"John": "fold", "Mike": "fold"}, folded=["John", "Mike"]),
                chips(dict(blinds, George=6, Deja=6)), 1)
    g, d, j, m = (prof.stats_for(key(prof, n)) for n in ("George", "Deja", "John", "Mike"))
    assert (g.hands, g.vpip, g.pfr) == (1, 1, 1)
    assert (d.hands, d.vpip, d.pfr) == (1, 1, 0)  # matched the raise: a call
    assert (j.hands, j.vpip) == (1, 0) and (m.hands, m.vpip) == (1, 0)  # only their blinds went in
    prof.update(table(), chips(blinds), 2)  # next hand
    assert prof.stats_for(key(prof, "George")).hands == 2


def test_raise_seen_only_in_the_chips():
    """No action labels on screen (bets go straight into the pot): the chips tell it."""
    prof = Profiles()
    prof.update(table(), chips({"John": 1, "Mike": 2}), 1)
    prof.update(table(), chips({"John": 1, "Mike": 2, "George": 5}), 1)
    prof.update(table(), chips({"John": 1, "Mike": 2, "George": 5, "Deja": 5}), 1)
    g, d = prof.stats_for(key(prof, "George")), prof.stats_for(key(prof, "Deja"))
    assert g.pfr == 1 and g.vpip == 1 and d.pfr == 0 and d.vpip == 1


def test_after_the_flop_bets_calls_and_folds():
    prof = Profiles()
    pre = {"John": 2, "Mike": 2, "George": 2, "Deja": 2, "You": 2}
    prof.update(table(), chips(pre), 1)
    flop = ("Kh", "9d", "2c")
    prof.update(table(flop, acts={"George": "bet"}), chips(dict(pre, George=8), {"George": 6}), 1)
    prof.update(table(flop, acts={"George": "bet", "Deja": "call"}), chips(dict(pre, George=8, Deja=8),
                                                                           {"George": 6, "Deja": 6}), 1)
    prof.update(table(flop, acts={"George": "bet", "Deja": "call", "John": "fold"}, folded=["John"]),
                chips(dict(pre, George=8, Deja=8), {"George": 6, "Deja": 6}), 1)
    g, d, j = (prof.stats_for(key(prof, n)) for n in ("George", "Deja", "John"))
    assert g.post_aggr == 1 and g.post_calls == 0
    assert d.post_calls == 1 and d.faced_bets == 1 and d.folds_to_bet == 0
    assert j.faced_bets == 1 and j.folds_to_bet == 1
    # a "Fold" label left on screen on the next street isn't counted again
    turn = flop + ("5s",)
    prof.update(table(turn, acts={"John": "fold"}, folded=["John"]), chips(dict(pre, George=8, Deja=8)), 1)
    assert prof.stats_for(key(prof, "John")).faced_bets == 1


def _play(prof: Profiles, hand: int, who: str, move: str) -> None:
    """One hand where `who` folds, calls (limps) or raises before the flop."""
    blinds = {"John": 1, "Mike": 2}
    prof.update(table(), chips(blinds), hand)
    if move == "raise":
        prof.update(table(acts={who: "raise"}), chips(dict(blinds, **{who: 6})), hand)
    elif move == "call":
        prof.update(table(acts={who: "call"}), chips(dict(blinds, **{who: 2})), hand)
    else:
        prof.update(table(acts={who: "fold"}, folded=[who]), chips(blinds), hand)


def test_styles_from_a_dozen_hands_on():
    patterns = {
        "station": ["call"] * 6 + ["fold"] * 4 + ["call"] * 3 + ["fold"] * 5,  # 50% played, never raises
        "nit": ["fold"] * 18 + ["raise"] * 2,  # 10%
        "maniac": ["raise"] * 14 + ["fold"] * 4 + ["call"] * 2,  # 80% played, 70% raised
        "tag": ["raise"] * 4 + ["fold"] * 15 + ["call"],  # 25% played, 20% raised
        "lag": ["raise"] * 7 + ["call"] * 2 + ["fold"] * 11,  # 45% played, 35% raised
    }
    for style, moves in patterns.items():
        prof = Profiles()
        for h, mv in enumerate(moves, start=1):
            _play(prof, h, "George", mv)
            if h == MIN_HANDS - 1:
                assert prof.style_for(key(prof, "George")) is None  # too few hands yet
        assert prof.style_for(key(prof, "George")) == style, (style, prof.label_for(key(prof, "George")))


def test_labels_and_thresholds():
    assert classify(PlayerStats(hands=11, vpip=11, pfr=0)) is None
    assert classify(PlayerStats(hands=30, vpip=15, pfr=2)) == "station"
    assert classify(PlayerStats(hands=30, vpip=3, pfr=3)) == "nit"
    assert describe(PlayerStats(hands=25, vpip=12, pfr=2)) == "plays 48% of hands, raises 8%"


def test_names_and_seats():
    prof = Profiles()
    nameless = table(names=False)
    prof.update(nameless, chips({"John": 1, "Mike": 2, "George": 6}), 1)
    seat_key = prof.key_for(nameless.players[4])
    assert seat_key.startswith("seat:")
    # the name is read at that seat later: from then on the seat means that name
    prof.update(table(), chips({"John": 1, "Mike": 2}), 2)
    assert prof.key_for(nameless.players[4]) == "name:george"
    # a slightly different position on screen is still the same seat
    moved = table(names=False)
    moved.players[4].anchor = (412.0, 61.0)
    assert prof.key_for(moved.players[4]) == "name:george"
    # names are compared without case and punctuation
    assert prof.key_for(Player(seat=4, name="GEORGE.", anchor=(400.0, 50.0))) == "name:george"


def test_styles_never_reach_the_text_for_an_ai():
    prof = Profiles()
    for h in range(1, 16):
        _play(prof, h, "George", "raise" if h % 2 else "call")
    st = table()
    prof.annotate(st)
    george = st.players[4]
    assert george.style in ("lag", "maniac") and "plays" in george.style_note
    assert st.hero.style is None
    text = render_text(st)
    for word in ("lag", "maniac", "station", "plays", "George", "raises 5"):
        assert word.lower() not in text.lower(), word
    assert check_outgoing_text(text) == []
    # kept with the rest of the screen-only fields when saved
    again = Player.from_dict(george.to_dict())
    assert again.style == george.style and again.style_note == george.style_note


def test_fed_by_the_real_tracker():
    """Stacks only, no action labels: the tracker's chips are enough."""
    tracker, prof = HandTracker(), Profiles()

    def read(stacks: Dict[str, float], pot: Optional[float], hand: int) -> None:
        st = table(stacks=stacks)
        st.pot = Field.manual(pot) if pot is not None else Field()
        for p in st.players:
            p.last_action = Field()
        info = tracker.update(st)
        prof.update(st, info, hand)

    full = {n: 1000.0 for n in NAMES}
    read(full, None, 1)  # between hands
    read(dict(full, John=999, Mike=998), 3, 2)  # blinds
    read(dict(full, John=999, Mike=998, George=994), 9, 2)  # George raises to 6
    read(dict(full, John=999, Mike=998, George=994, Deja=994), 15, 2)  # Deja calls
    g, d, m = (prof.stats_for(key(prof, n)) for n in ("George", "Deja", "Mike"))
    assert (g.vpip, g.pfr) == (1, 1) and (d.vpip, d.pfr) == (1, 0) and m.vpip == 0
