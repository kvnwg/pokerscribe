"""River ranges worked out from the betting so far (app/solver/ranges.py)."""
import numpy as np
import pytest

from app.poker.history import HERO, OTHER, VILLAIN, Line, StreetLine
from app.solver import ranges as R
from app.solver.ranking import BoardRanker, hand_value
from app.solver.spot import canonical

BOARD = ("Ac", "8d", "5c", "2h", "Js")
U = R._universe()


def at(weights, combo):
    return float(weights[U.index[canonical(combo)]])


def share(rng, wanted):
    """The share of a range's weight on the combos `wanted` picks."""
    total = sum(w for _, w in rng)
    return sum(w for c, w in rng if wanted(c)) / total


def strength(rng, board=BOARD):
    """The range's average place among all hands on the board (0 worst, 1 best)."""
    ranker = BoardRanker(board)
    everyone = sorted(ranker.value(c) for c in U.combos if c[0] not in board and c[1] not in board)
    total = sum(w for _, w in rng)
    return sum(w * np.searchsorted(everyone, ranker.value(c)) for c, w in rng) / (total * len(everyone))


def two_pair_or_better(combo, board=BOARD):
    return hand_value(list(combo) + list(board)) >> 20 >= 2


RAISED = StreetLine(2.5, VILLAIN)  # the button raised before the flop, the hero called in the big blind
SEATS = dict(hero_in_position=False, hero_seat="BB", villain_seat="BTN")


def ranges(flop, turn, pre=RAISED, **kw):
    return R.river_ranges(BOARD, Line(pre, flop, turn), **{**SEATS, **kw})


# ------------------------------------------------------------- the universe
def test_every_combo_once_strongest_first():
    assert len(U.combos) == 1326 == len(set(U.combos))
    assert U.classes[0] == "AA" and U.pct[0] == pytest.approx(6 / 1326)
    assert U.pct[-1] == pytest.approx(1.0) and list(U.pct) == sorted(U.pct)
    assert all(c == canonical(c) for c in U.combos)


# ----------------------------------------------------------- flop and turn
def test_street_scores_made_hands_in_order():
    score, draw = R.street_scores(("Kh", "7h", "2c"))
    # a set, top pair top kicker, ace high, nothing
    assert at(score, ("7s", "7d")) > at(score, ("As", "Kd")) > at(score, ("Ah", "3d")) > at(score, ("4s", "3h"))
    assert at(score, ("7s", "7d")) > 0.99 and at(score, ("4s", "3h")) < 0.02
    assert at(score, ("Kh", "2d")) == -1.0  # uses a board card
    assert at(draw, ("As", "Kd")) == 0


def test_draws_are_found_and_lifted():
    score, draw = R.street_scores(("Kh", "7h", "2c"))
    # two hearts on the board: any two hearts is a flush draw, and plays like a weak pair (0.70)
    assert at(draw, ("9h", "8h")) == 2 and at(score, ("9h", "8h")) == pytest.approx(0.70)
    assert at(draw, ("Jh", "Td")) == 0  # one heart is not a draw
    score, draw = R.street_scores(("9h", "8c", "2d"))
    assert at(draw, ("Jh", "Td")) == 2  # open-ended: a queen or a seven
    assert at(draw, ("7s", "6s")) == 2  # open-ended: a ten or a five
    assert at(draw, ("Js", "7d")) == 1 and at(score, ("Js", "7d")) == pytest.approx(0.50)  # only a ten
    assert at(draw, ("As", "Kd")) == 0 and at(score, ("As", "Kd")) > 0.5  # ace high beats most hands with nothing
    # a flush draw with a straight draw
    score, draw = R.street_scores(("9h", "8h", "2d"))
    assert at(draw, ("Jh", "Th")) == 3 and at(score, ("Jh", "Th")) == pytest.approx(0.85)
    # the turn: the same draws are worth less with one card to come
    score, draw = R.street_scores(("9h", "8h", "2d", "Kc"))
    assert at(draw, ("Jh", "Th")) == 3 and at(score, ("Jh", "Th")) == pytest.approx(0.75)


def test_a_made_hand_is_not_a_draw():
    score, draw = R.street_scores(("9h", "8c", "7d"))
    assert at(draw, ("Jh", "Td")) == 0 and at(score, ("Jh", "Td")) > 0.99  # the straight is made
    # one card of a suit to a three-flush board is a draw only with a jack or better
    _, draw = R.street_scores(("9h", "8h", "2h"))
    assert at(draw, ("Qh", "3d")) == 2 and at(draw, ("4h", "3d")) == 0


def test_straight_outs_ignore_cards_that_help_everyone():
    mask = sum(1 << R.RANK_INDEX[r] for r in "9876")  # four to a straight on the board
    outs = R._straight_outs(mask)
    # a ten or a five completes it for everyone; jack-king adds nothing of its own
    assert outs[R.RANK_INDEX["K"], R.RANK_INDEX["J"]] == 0


def test_place_within_a_range():
    score = np.array([0.1, 0.5, 0.5, 0.9])
    q = R._place(score, np.array([1.0, 1.0, 1.0, 1.0]))
    # the weakest has half of its own quarter below it; the two level ones share the middle
    assert list(q) == pytest.approx([0.125, 0.5, 0.5, 0.875])
    # weights: a range that is mostly the strong hand puts the others near the bottom
    q = R._place(score, np.array([1.0, 0.0, 0.0, 9.0]))
    assert list(q) == pytest.approx([0.05, 0.1, 0.1, 0.55])


def test_bets_calls_and_checks():
    q = np.linspace(0.0, 1.0, 101)
    none = np.zeros(101, dtype=np.int8)
    small, big = R.bets(q, none, 0.33, 3), R.bets(q, none, 1.5, 3)
    assert small[-1] == pytest.approx(1.0, abs=0.01) and big[-1] == pytest.approx(1.0, abs=0.01)  # the top always bets
    # value hands: the top 0.5 / (1 + 1.3 x 0.33) = 35% for a small bet, 0.5 / (1 + 1.3 x 1.5) = 17% for a big one
    assert small[80] > 0.9 > 0.2 > big[70]
    assert big[50] == pytest.approx(R.MERGED) and big[0] > big[50]  # the weakest hands bluff more than the middle bets
    draws = R.bets(q, np.full(101, 2, dtype=np.int8), 0.66, 3)
    assert draws[50] == pytest.approx(R.SEMI[3])
    follow = R.bets(q, none, 0.66, 3, follows=True)
    assert follow[50] == pytest.approx(R.FOLLOW_MERGED) and follow[0] > R.bets(q, none, 0.66, 3)[0]
    # a call of a pot-sized bet keeps 0.85 / 2 = 42.5% of the range, and half of the very top
    c = R.calls(q, 1.0)
    assert c[40] < 0.01 and c[75] > 0.99 and c[100] == pytest.approx(0.5, abs=0.06)
    assert R.calls(q, 0.33)[45] > 0.9 > 0.1 > R.calls(q, 2.0)[45]
    # a check thins out the hands that bet, far more when nobody acts behind
    last, first = R.checks(q, none, 3, True), R.checks(q, none, 3, False)
    assert last[-1] == pytest.approx(1 - R.BETS_LAST, abs=0.01)
    assert first[-1] == pytest.approx(1 - R.BETS_FIRST, abs=0.01)
    assert last[50] > 0.9 and first[50] > 0.9


def test_styles_change_bets_and_calls():
    q = np.linspace(0.0, 1.0, 101)
    none = np.zeros(101, dtype=np.int8)
    assert R.bets(q, none, 0.66, 4, "station")[0] == pytest.approx(R.MERGED)  # a station that bets isn't bluffing
    assert R.bets(q, none, 0.66, 4, "maniac")[0] > R.bets(q, none, 0.66, 4)[0]
    assert R.calls(q, 0.66, "station")[30] > 0.9 > 0.1 > R.calls(q, 0.66, "nit")[45]


# ------------------------------------------------------------ before the flop
def test_pot_types():
    assert [R.pot_type(x) for x in (1.0, 1.2, 2.0, 5.5, 6.0, 16.0, 22.0)] == [
        "limped", "limped", "raised", "raised", "3bet", "3bet", "4bet"]


def test_the_hero_plays_the_charts():
    opened = R.preflop_weights("BTN", "BB", 2.5, True, HERO)
    assert at(opened, ("As", "Ah")) == 1.0 and at(opened, ("9s", "8d")) == 1.0  # 98o opens on the button
    assert at(opened, ("7s", "2h")) < 0.05
    defended = R.preflop_weights("BB", "BTN", 2.5, False, HERO)
    assert at(defended, ("7s", "6d")) == 1.0 and at(defended, ("7s", "2h")) < 0.05
    assert at(defended, ("As", "Ah")) == R.TRAP  # aces would usually have re-raised
    three_bet = R.preflop_weights("BB", "BTN", 9.0, True, HERO)
    assert at(three_bet, ("As", "Ah")) == 1.0 and at(three_bet, ("7s", "6d")) < 0.05
    # raising players who only called: the tighter list
    assert at(R.preflop_weights("BTN", "HJ", 4.0, True, HERO), ("9s", "8d")) < 0.05


def test_loose_styles_are_wider_and_tight_ones_narrower():
    def width(style, *args):
        return R.preflop_weights(*args, style).sum() / 1326

    call = ("CO", "HJ", 2.5, False)  # called a raise with players still to act
    assert width("station", *call) > 2 * width(None, *call) > 2 * width("nit", *call)
    assert at(R.preflop_weights(*call, "station"), ("Ks", "Td")) > 0.7  # king-ten offsuit: a station calls
    assert at(R.preflop_weights(*call, "nit"), ("Ks", "Td")) < 0.1
    opened = ("BTN", "BB", 2.5, True)
    assert width("maniac", *opened) > width(None, *opened) > width("nit", *opened)
    assert width("station", *opened) < 0.3  # a station that raises has a hand
    # the same hands whoever holds them: no style means a typical player, close to the charts
    assert width(None, *opened) == pytest.approx(width(HERO, *opened), abs=0.05)


def test_what_was_seen_of_a_player_replaces_the_style():
    call = ("CO", "HJ", 2.5, False)
    # a player seen playing 60% of hands calls with far more than the label "lag" (33%) says
    seen = R.preflop_weights(*call, "lag", rates=(0.60, 0.40))
    assert seen.sum() > 1.5 * R.preflop_weights(*call, "lag").sum()
    assert at(seen, ("Ks", "7d")) > 0.5 > at(R.preflop_weights(*call, "lag"), ("Ks", "7d"))
    # and no style yet, but a few hands seen: already wider or narrower than the typical player
    assert R.preflop_weights(*call, None, rates=(0.10, 0.08)).sum() < R.preflop_weights(*call, None).sum()
    # the hero's hands never depend on it
    assert np.array_equal(R.preflop_weights(*call, HERO, rates=(0.9, 0.9)), R.preflop_weights(*call, HERO))
    loose = ranges(StreetLine(0.0), StreetLine(0.0), pre=StreetLine(2.5, HERO), hero_seat="BTN", villain_seat="BB",
                   hero_in_position=True, villain_rates=(0.6, 0.1))
    tight = ranges(StreetLine(0.0), StreetLine(0.0), pre=StreetLine(2.5, HERO), hero_seat="BTN", villain_seat="BB",
                   hero_in_position=True, villain_rates=(0.12, 0.1))
    assert len(loose.villain) > len(tight.villain) and loose.hero == tight.hero


def test_limped_pots():
    bb = R.preflop_weights("BB", "HJ", 1.0, None, None)
    assert at(bb, ("7s", "2h")) == 1.0 and at(bb, ("As", "Ah")) == pytest.approx(R.TRAP, abs=0.01)
    limp = R.preflop_weights("HJ", "BB", 1.0, None, "station")
    assert at(limp, ("Js", "8d")) > 0.7 and at(limp, ("7s", "2h")) < 0.01  # a station plays about half of all hands
    assert at(limp, ("As", "Ah")) < 0.3  # they'd have raised
    # called a raise from a seat that acts before the raiser: they limped, then called
    limp_call = R.preflop_weights("CO", "SB", 4.0, False, "station")
    assert at(limp_call, ("Qs", "Td")) > 0.9 and at(limp_call, ("As", "Ah")) < 0.3
    assert at(limp_call, ("Js", "8d")) < at(limp, ("Js", "8d"))  # some of the weakest limps fold to the raise


def test_unknown_raiser_goes_by_the_seats():
    # the earlier seat opens, the later one calls; a re-raise comes from the later seat
    assert np.array_equal(R.preflop_weights("BTN", "BB", 2.5, None), R.preflop_weights("BTN", "BB", 2.5, True))
    assert np.array_equal(R.preflop_weights("BB", "BTN", 2.5, None), R.preflop_weights("BB", "BTN", 2.5, False))
    assert np.array_equal(R.preflop_weights("BB", "BTN", 9.0, None), R.preflop_weights("BB", "BTN", 9.0, True))
    plain = R.preflop_weights(None, None, 2.5, None)
    assert at(plain, ("As", "Ah")) > 0.99 and at(plain, ("7s", "2h")) < 0.01


def test_bigger_pots_before_the_flop_mean_fewer_hands():
    sizes = [R.preflop_weights("BTN", "BB", x, True).sum() for x in (2.5, 9.0, 22.0)]
    assert sizes[0] > 3 * sizes[1] > 3 * sizes[2]


# ------------------------------------------------------ what wasn't recorded
def test_fill_in_from_the_pot_size():
    def sizes(pot, line=None):
        f = R.fill_in(line, pot)
        return tuple(None if s.size is None else round(s.size, 2) for s in f.streets)

    # 2 x 1 + 1 dead = 3 big blinds: nobody raised, nobody bet
    assert sizes(3.0) == (1.0, 0.0, 0.0)
    # 2 x 2.75 + 1 = 6.5: one raise, checked through
    assert sizes(6.5) == (2.75, 0.0, 0.0)
    # 12 = 6.5 x 1.846: one bet of (1.846 - 1) / 2 = 0.42 pots, put on the flop
    assert sizes(12.0) == (2.75, 0.42, 0.0)
    # 40 = 6.5 x 6.15: more than one bet explains (3.5x), so two of (sqrt(6.15) - 1) / 2 = 0.74
    assert sizes(40.0) == (2.75, 0.74, 0.74)
    # 150 is too much for a single-raised pot (two 1.25-pot bets reach 6.5 x 12.25 = 80): a re-raised pot
    assert sizes(150.0)[0] == 9.0
    # what is known stays: a raise to 2.5 and a half-pot turn bet leave 24 / (6 x 2) = 2x for the flop: 0.5
    known = Line(StreetLine(2.5, VILLAIN), StreetLine(), StreetLine(0.5, HERO))
    filled = R.fill_in(known, 24.0)
    assert filled.preflop == known.preflop and filled.turn == known.turn
    assert filled.flop == StreetLine(pytest.approx(0.5), None)
    # no pot size: a typical raise, and unknown rounds stay unknown
    assert sizes(None) == (2.75, None, None)
    assert sizes(None, Line(StreetLine(1.0))) == (1.0, None, None)


# ------------------------------------------------------------------- ranges
def test_ranges_are_clean_weighted_combos():
    est = ranges(StreetLine(0.66, VILLAIN), StreetLine(0.66, VILLAIN))
    for rng in (est.hero, est.villain):
        combos = [c for c, _ in rng]
        assert R.MIN_COMBOS <= len(rng) <= R.MAX_COMBOS and len(set(combos)) == len(combos)
        assert all(c == canonical(c) and not set(c) & set(BOARD) for c in combos)
        assert all(R.PRUNE <= w <= 1.0 for _, w in rng) and max(w for _, w in rng) == 1.0
    assert not est.guessed and est.line.flop == StreetLine(0.66, VILLAIN)


def test_someone_who_bet_every_round_has_a_stronger_hand():
    barrels = ranges(StreetLine(0.75, VILLAIN), StreetLine(0.75, VILLAIN))
    checked = ranges(StreetLine(0.0), StreetLine(0.0))
    assert strength(barrels.villain) > strength(checked.villain) + 0.1
    assert share(barrels.villain, two_pair_or_better) > 3 * share(checked.villain, two_pair_or_better)
    # and it has some hands with nothing left in it: the bluffs
    nothing = lambda c: hand_value(list(c) + list(BOARD)) >> 20 == 0  # noqa: E731
    assert 0.03 < share(barrels.villain, nothing) < 0.5


def test_a_caller_keeps_the_middle_of_the_range():
    est = ranges(StreetLine(0.75, VILLAIN), StreetLine(0.75, VILLAIN))  # the hero called twice
    checked = ranges(StreetLine(0.0), StreetLine(0.0))
    assert strength(est.hero) > strength(checked.hero) + 0.1
    # seven-deuce never got here by calling a raise and two bets
    assert all(c != canonical(("7s", "2d")) for c, _ in est.hero)


def test_who_bet_matters():
    theirs = ranges(StreetLine(0.75, VILLAIN), StreetLine(0.0))
    mine = ranges(StreetLine(0.75, HERO), StreetLine(0.0))
    other = ranges(StreetLine(0.75, OTHER), StreetLine(0.0))
    unknown = ranges(StreetLine(0.75, None), StreetLine(0.0))
    assert theirs.villain != mine.villain and theirs.hero != mine.hero
    # a third player's bet: both of the two left called it, so each looks like the caller
    assert other.villain == mine.villain and other.hero == theirs.hero
    # not known whose bet: neither the bettor's range nor the caller's
    assert unknown.villain not in (theirs.villain, mine.villain)
    # the caller's range has given up its nothing hands; the bettor's has kept some as bluffs
    nothing = lambda c: hand_value(list(c) + list(BOARD[:3])) >> 20 == 0 and not {"A"} & {c[0][0], c[1][0]}  # noqa: E731
    assert share(theirs.villain, nothing) > share(mine.villain, nothing)


def test_bigger_bets_mean_stronger_hands():
    small = ranges(StreetLine(0.0), StreetLine(0.33, VILLAIN))
    big = ranges(StreetLine(0.0), StreetLine(1.5, VILLAIN))
    board4 = BOARD[:4]
    pair_or_better = lambda c: hand_value(list(c) + list(board4)) >> 20 >= 1  # noqa: E731
    assert len(big.villain) < len(small.villain)
    assert share(big.hero, pair_or_better) > share(small.hero, pair_or_better)  # calling a big bet takes a hand


def test_the_opponents_style_changes_their_range_only():
    plain = ranges(StreetLine(0.66, HERO), StreetLine(0.0), pre=StreetLine(2.5, HERO), hero_seat="BTN",
                   villain_seat="BB", hero_in_position=True)
    station = ranges(StreetLine(0.66, HERO), StreetLine(0.0), pre=StreetLine(2.5, HERO), hero_seat="BTN",
                     villain_seat="BB", hero_in_position=True, villain_style="station")
    assert plain.hero == station.hero
    assert len(station.villain) > len(plain.villain)  # a station got here with far more hands


def test_position_changes_what_a_check_means():
    # checking behind (last to act) gives up more strong hands than checking first
    line = Line(StreetLine(2.5, HERO), StreetLine(0.0), StreetLine(0.0))
    first = R.river_ranges(BOARD, line, hero_in_position=True, hero_seat="BTN", villain_seat="BB")
    last = R.river_ranges(BOARD, line, hero_in_position=False, hero_seat="BTN", villain_seat="BB")
    assert share(last.villain, two_pair_or_better) < share(first.villain, two_pair_or_better)


def test_guessed_from_the_pot_when_nothing_was_recorded():
    small = R.river_ranges(BOARD, None, pot_bb=6.5, **SEATS)
    big = R.river_ranges(BOARD, None, pot_bb=60.0, **SEATS)
    assert small.guessed and big.guessed
    assert (small.line.flop.size, small.line.turn.size) == (0.0, 0.0) and big.line.flop.size > 0.5
    assert strength(big.villain) > strength(small.villain) + 0.05  # a big pot: stronger hands on both sides
    assert strength(big.hero) > strength(small.hero) + 0.05
    partly = R.river_ranges(BOARD, Line(RAISED, StreetLine(0.5, VILLAIN), StreetLine()), pot_bb=12.0, **SEATS)
    assert partly.guessed and partly.line.turn == StreetLine(0.0)
    nothing_known = R.river_ranges(BOARD, None, hero_in_position=True)
    assert nothing_known.guessed and len(nothing_known.villain) >= R.MIN_COMBOS


def test_an_odd_line_still_leaves_a_range():
    # a re-re-raised pot, then two overbets: very few hands fit, but never fewer than the floor
    est = ranges(StreetLine(2.0, VILLAIN), StreetLine(2.0, VILLAIN), pre=StreetLine(25.0, VILLAIN))
    assert len(est.villain) >= R.MIN_COMBOS and len(est.hero) >= R.MIN_COMBOS


def test_the_rivers_own_bets_do_not_change_the_ranges():
    a = R.river_ranges(BOARD, Line(RAISED, StreetLine(0.0), StreetLine(0.0), river=()), **SEATS)
    b = R.river_ranges(BOARD, Line(RAISED, StreetLine(0.0), StreetLine(0.0), river=((VILLAIN, 50.0),)), **SEATS)
    assert a.villain is b.villain and a.hero is b.hero  # worked out once per hand
    assert b.line.river == ((VILLAIN, 50.0),)


def test_bad_boards_are_refused():
    with pytest.raises(ValueError):
        R.river_ranges(BOARD[:4], None, hero_in_position=True)
    with pytest.raises(ValueError):
        R.river_ranges(BOARD[:4] + ("Ac",), None, hero_in_position=True)
