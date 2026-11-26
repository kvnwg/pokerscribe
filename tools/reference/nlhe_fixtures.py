"""Generate rules fixtures for the Rust NLHE engine (engine/crates/nlhe) with PokerKit 0.7.8.

    pip install pokerkit==0.7.8
    python tools/reference/nlhe_fixtures.py --hands 10000 --seed 20261126 \
        --out engine/crates/nlhe/tests/fixtures/pokerkit_nlhe.txt

Takes about 35 seconds. Each hand gets random settings (mostly heads-up or six-max, some 3
to 5 players; blinds; an ante half the time; mixed stacks, many of them a few big blinds or
less, and in some six-max hands a ladder of short stacks behind an opener), fixed cards
(some boards make everyone tie, for split pots and odd chips), and random legal actions
(short stacks often move all in). At every decision the file records whose turn it is, the
street, every stack, whether folding is allowed, the amount to call (0 means check), the
raise-to range, and the action taken. It also records the pots when a showdown starts and
the final stacks. engine/crates/nlhe/tests/pokerkit_fixtures.rs replays every hand and
must agree on all of it.

PokerKit is the reference for everything except one rule, where it disagrees with the
rule the engine is specified to follow ("an all-in below a full raise does not reopen
the betting for players who already acted"):

  1. PokerKit treats the first raise of a street as full whatever its size. So a limper
     facing an all-in raise of less than a big blind over the limp may re-raise. Correct:
     call or fold only.
  2. PokerKit tracks short all-ins with one list for the whole table. After two short
     all-ins add up to a full raise and a third short all-in follows, the first bettor
     faces more than a full raise in total but PokerKit says they may not raise.
     Correct: they may.

For the raise decision only, this script uses the rule as specified: a player may raise
unless they already acted on this street since the last full raise and the bet has gone
up by less than one full raise since their last action (a full raise is at least the big
blind and at least the last full raise). Everything else, including the raise sizes, the
call amounts, the order of play, side pots, returned bets and odd chips, is PokerKit's.
A step where the two disagree is flagged (D: PokerKit allows the raise and the rule does
not; A: the other way round) so the Rust test can count them. For an A step the script
clears PokerKit's short all-in list before asking for the sizes or raising, which is the
only state that blocks it there.

Showdowns: every player shows (left alone, PokerKit mucks hands that cannot win; the
result is the same). PokerKit then kills hands
that cannot win anything, rebuilds the pots without them (merging neighbours with the
same players) and gives each pot's odd chips to the first winner after the button.

Seats: PokerKit player 0 is the first seat after the button (the small blind with 3 or
more players, the big blind heads-up) and the last player is the button.

Line format, one hand per line, fields separated by " | ":
    n sb bb ante | stacks | hole cards (2 per player) and 5 board cards | steps | final stacks | pots
Cards are integers, rank * 4 + suit (rank 0 = 2 ... 12 = ace; suits c, d, h, s).
A step is "player,street,stacks,fold,call,min,max,flag,action": street 0 to 3, stacks is
every player's chips behind joined by "/", fold 0 or 1, min and max are "-" when raising
is not allowed, flag is ".", "D" or "A", and the action is f (fold), k (check), c (call)
or r<amount> (raise to). Pots are the main and side pots when the showdown starts, before
any hand is killed, as "amount:player.player..."; "-" when the hand ends without one.
"""
from __future__ import annotations

import argparse
import random
import sys
import warnings
from collections import Counter
from importlib import metadata
from pathlib import Path

from pokerkit import Automation, ChipsPushing, Mode, NoLimitTexasHoldem

RANKS = "23456789TJQKA"
SUITS = "cdhs"
AUTOMATIONS = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.HAND_KILLING,
    Automation.CHIPS_PUSHING,
    Automation.CHIPS_PULLING,
)
BLINDS = [(1, 2), (1, 2), (1, 2), (1, 3), (2, 5), (5, 10), (25, 50)]


def card_str(c: int) -> str:
    return RANKS[c // 4] + SUITS[c % 4]


def random_settings(rng: random.Random):
    r = rng.random()
    n = 2 if r < 0.45 else 6 if r < 0.9 else rng.randint(3, 5)
    sb, bb = rng.choice(BLINDS)
    ante = 0 if rng.random() < 0.5 else rng.randint(1, bb)
    stacks = []
    for _ in range(n):
        kind = rng.random()
        if kind < 0.25:
            stacks.append(rng.randint(1, 3 * bb))  # tiny: some are below the ante or a blind
        elif kind < 0.55:
            stacks.append(rng.randint(3 * bb, 25 * bb))
        else:
            stacks.append(rng.randint(25 * bb, 250 * bb))
    ladder = n == 6 and rng.random() < 0.15
    if ladder:
        # The opener (player 2) raises to 3 big blinds, then three short stacks move all in:
        # the first two add up to a full raise, the third does not. When the action is back
        # on the opener, the bet has gone up by more than a full raise since they acted.
        s3 = 3 * bb + rng.randint(1, 2 * bb - 1)
        s4 = rng.randint(max(5 * bb, s3 + 1), s3 + 2 * bb - 1)
        s5 = s4 + rng.randint(1, 2 * bb - 1)
        stacks[2] = rng.randint(40 * bb, 200 * bb)
        stacks[3:6] = [s3 + ante, s4 + ante, s5 + ante]
    return n, sb, bb, ante, stacks, ladder


def random_cards(rng: random.Random, n: int):
    deck = list(range(52))
    rng.shuffle(deck)
    if rng.random() < 0.08:
        # a broadway straight on the board with at most two cards of a suit: everyone ties,
        # which exercises split pots and odd chips
        board = []
        suits = [0, 1, 2, 3, rng.randrange(4)]
        rng.shuffle(suits)
        for rank, suit in zip((12, 11, 10, 9, 8), suits):
            board.append(rank * 4 + suit)
        deck = [c for c in deck if c not in board]
        hole = deck[: 2 * n]
    else:
        hole = deck[: 2 * n]
        board = deck[2 * n: 2 * n + 5]
    return hole, board


class RuleTracker:
    """The reopening rule as specified, tracked next to PokerKit."""

    def __init__(self, bb: int):
        self.bb = bb
        self.street = None
        self.full = bb
        self.acted = set()

    def sync(self, state) -> None:
        if state.street_index != self.street:
            self.street = state.street_index
            self.full = self.bb
            self.acted = set()

    def may_raise(self, state, i: int) -> bool:
        bets, stacks, mx = state.bets, state.stacks, max(state.bets)
        if stacks[i] <= mx - bets[i]:
            return False  # calling already puts them all in
        if not any(j != i and state.statuses[j] and stacks[j] + bets[j] > mx for j in state.player_indices):
            return False  # nobody left who could answer a raise
        return i not in self.acted or mx - bets[i] >= self.full

    def record(self, state, i: int, raise_to: int | None) -> None:
        if raise_to is None:
            self.acted.add(i)
            return
        increment = raise_to - max(state.bets)
        if increment >= self.full:
            self.full = increment
            self.acted = {i}
        else:
            self.acted.add(i)


def choose(rng: random.Random, can_fold: bool, call: int, raise_range, short: bool):
    if raise_range and short and rng.random() < 0.5:
        return "r", raise_range[1]  # short stacks often move all in
    r = rng.random()
    if call > 0:
        if can_fold and r < 0.22:
            return "f", None
        if raise_range and r < 0.55:
            return "r", pick_size(rng, *raise_range)
        return "c", None
    if raise_range and r < 0.42:
        return "r", pick_size(rng, *raise_range)
    return "k", None


def pick_size(rng: random.Random, lo: int, hi: int) -> int:
    u = rng.random()
    if u < 0.35:
        return lo
    if u < 0.6:
        return hi
    return lo + int((hi - lo) * rng.random() ** 2)


def play_hand(rng: random.Random, counts: Counter) -> str:
    n, sb, bb, ante, stacks, ladder = random_settings(rng)
    hole, board = random_cards(rng, n)
    state = NoLimitTexasHoldem.create_state(
        AUTOMATIONS, True, ante, (sb, bb), bb, stacks, n, mode=Mode.TOURNAMENT,
    )
    tracker = RuleTracker(bb)
    steps = []
    showdown_pots = None
    dealt_board = 0
    while state.status:
        if state.can_deal_hole():
            p = state.hole_dealee_index
            state.deal_hole(card_str(hole[2 * p]) + card_str(hole[2 * p + 1]))
        elif state.can_burn_card():
            state.burn_card("??")
        elif state.can_deal_board():
            k = state.board_dealing_counts[0]
            state.deal_board("".join(card_str(c) for c in board[dealt_board: dealt_board + k]))
            dealt_board += k
        elif state.can_show_or_muck_hole_cards():
            if showdown_pots is None:
                showdown_pots = ["%d:%s" % (pot.amount, ".".join(map(str, pot.player_indices)))
                                 for pot in state.pots]
            state.show_or_muck_hole_cards(True)
        elif state.actor_index is not None:
            i = state.actor_index
            tracker.sync(state)
            street = state.street_index
            can_fold = state.can_fold()
            call = state.checking_or_calling_amount
            pk_raise = state.can_complete_bet_or_raise_to()
            rule_raise = tracker.may_raise(state, i)
            flag = "."
            saved_short = None
            if rule_raise and not pk_raise:
                flag = "A"
                saved_short = list(state.consecutive_short_all_in_amounts)
                state.consecutive_short_all_in_amounts.clear()
                assert state.can_complete_bet_or_raise_to(), "rule allows a raise PokerKit still blocks"
            elif pk_raise and not rule_raise:
                flag = "D"
            raise_range = None
            if rule_raise:
                lo = state.min_completion_betting_or_raising_to_amount
                hi = state.max_completion_betting_or_raising_to_amount
                total = state.stacks[i] + state.bets[i]
                assert lo == min(total, tracker.full + max(state.bets)), "min raise differs from the rule"
                assert hi == total
                raise_range = (lo, hi)
            if flag != ".":
                counts[flag] += 1
            if ladder and street == 0 and i == 2 and raise_range and max(state.bets) <= bb \
                    and raise_range[0] <= 3 * bb <= raise_range[1]:
                kind, amount = "r", 3 * bb
            elif ladder and street == 0 and i in (3, 4, 5) and raise_range and rng.random() < 0.9:
                kind, amount = "r", raise_range[1]
            else:
                kind, amount = choose(rng, can_fold, call, raise_range, state.stacks[i] + state.bets[i] <= 12 * bb)
            if saved_short is not None and kind != "r":
                state.consecutive_short_all_in_amounts[:] = saved_short
            lo_s, hi_s = (str(raise_range[0]), str(raise_range[1])) if raise_range else ("-", "-")
            act = "r%d" % amount if kind == "r" else kind
            behind = "/".join(map(str, state.stacks))
            steps.append("%d,%d,%s,%d,%d,%s,%s,%s,%s" % (i, street, behind, int(can_fold), call, lo_s, hi_s, flag, act))
            counts["action_" + kind] += 1
            if kind == "r":
                if amount == state.stacks[i] + state.bets[i] and amount - max(state.bets) < tracker.full:
                    counts["short_all_in_raise"] += 1
                tracker.record(state, i, amount)
                state.complete_bet_or_raise_to(amount)
            elif kind == "f":
                tracker.record(state, i, None)
                state.fold()
            else:
                tracker.record(state, i, None)
                state.check_or_call()
        else:
            raise AssertionError("PokerKit is waiting for an operation this script does not handle")
    final = list(state.stacks)
    assert sum(final) == sum(stacks)
    counts["hands_%d" % n] += 1
    if sum(1 for s in final if s == 0):
        counts["hands_with_bust"] += 1
    pushes = [op for op in state.operations if isinstance(op, ChipsPushing)]
    if any(op.pot_index > 0 for op in pushes):
        counts["hands_with_side_pots"] += 1
    for op in pushes:
        winners = [a for a in op.amounts if a]
        if len(winners) > 1:
            counts["split_pots"] += 1
            if len(set(winners)) > 1:
                counts["odd_chip_splits"] += 1
    return " | ".join([
        "%d %d %d %d" % (n, sb, bb, ante),
        " ".join(map(str, stacks)),
        " ".join(map(str, hole + board)),
        " ".join(steps),
        " ".join(map(str, final)),
        " ".join(showdown_pots) if showdown_pots else "-",
    ])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--hands", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261126)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    version = metadata.version("pokerkit")
    if version != "0.7.8":
        print("expected PokerKit 0.7.8, found %s" % version, file=sys.stderr)
        return 1
    warnings.simplefilter("error")  # any PokerKit warning (for example burned chips) stops the run
    rng = random.Random(args.seed)
    counts: Counter = Counter()
    lines = [play_hand(rng, counts) for _ in range(args.hands)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        f.write("# PokerKit 0.7.8 NLHE fixtures from tools/reference/nlhe_fixtures.py, seed %d, %d hands\n"
                % (args.seed, args.hands))
        f.write("# counts: %s\n" % " ".join("%s=%d" % kv for kv in sorted(counts.items())))
        for line in lines:
            f.write(line + "\n")
    print(" ".join("%s=%d" % kv for kv in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
