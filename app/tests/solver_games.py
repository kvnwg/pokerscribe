"""Small river games with known answers, shared by the solver tests.

The half-street river game (The Mathematics of Poker, Chen and Ankenman; KNOWLEDGE.md):
one player can bet s times the pot or check, the other can only check first and then call
or fold. The bettor is polarised (the nuts or nothing), the caller holds bluff-catchers
(beat the bluffs, lose to the value). At the equilibrium:

- the bettor bets every value hand and bluffs so that bluffs are s/(1+2s) of its bets;
- the caller calls 1/(1+s) of the time (defends that share of its range).

The game below, with the pot at 100 and the board Kh 8d 5c 3s 2h:

- caller (out of position, checks first): QQ, the 6 combos. One pair of queens.
- bettor (in position): KK, 3 combos (KsKd KsKc KdKc; Kh is on the board), trips, the
  value; and JT, 16 combos (4 jacks x 4 tens), jack high, the air.
- No flush: no suit has three cards on the board. No straight: with 2 3 5 8 K only A4 or
  64 in the hand makes one, and nobody holds those. So KK beats QQ beats JT, always.
- The three ranges use different ranks, so no combo of one player shares a card with a
  combo of the other: all 19 x 6 deals happen equally often, and card removal can't move
  the closed-form numbers.

Hand-checked numbers (P = 100, value weight 3, air weight 16, c = 1/(1+s)):

    s     bet   bluff share s/(1+2s)   call 1/(1+s)   bluff combos 3s/(1+s)   each JT bluffs   bettor's value
    0.5    50   0.5/2.0  = 1/4          1/1.5  = 2/3   1.5/1.5  = 1            1/16             400/19  = 21.053
    0.75   75   0.75/2.5 = 3/10         1/1.75 = 4/7   2.25/1.75 = 9/7         9/112            3000/133 = 22.556
    1     100   1/3                     1/2            3/2                     3/32             450/19  = 23.684
    2     200   2/5                     1/3            6/3 = 2                 1/8              500/19  = 26.316

- Bluff share: bluffs / (3 + bluffs). s=0.5: 1/(3+1) = 1/4. s=0.75: (9/7)/(3+9/7) =
  (9/7)/(30/7) = 3/10. s=1: 1.5/4.5 = 1/3. s=2: 2/5. Each matches s/(1+2s).
- Caller indifferent (call = fold = 0 when facing the bet): with bluff share b, calling wins
  P + sP against a bluff and loses sP against value: b(P+sP) - (1-b)sP = 0 gives
  b = s/(1+2s). For s=1: (1/3)(200) - (2/3)(100) = 0.
- Bettor indifferent with air (bluff = check = 0): bluffing wins P when they fold and loses
  sP when they call: (1-c)P - c sP = 0 gives c = 1/(1+s). For s=1: 50 - 50 = 0. Checking
  air loses the showdown to QQ and wins nothing.
- Bettor's value per hand: only KK earns: it wins P when they fold and P + sP when they
  call, so (3/19)(P + c sP). s=0.5: (3/19)(100 + (2/3)50) = (3/19)(400/3) = 400/19.
  s=0.75: (3/19)(100 + (4/7)75) = (3/19)(1000/7) = 3000/133. s=1: (3/19)(150) = 450/19.
  s=2: (3/19)(100 + (1/3)200) = (3/19)(500/3) = 500/19. The caller gets 100 minus that.
- Value betting beats checking: KK wins P by checking and P + c sP > P by betting.
"""
from __future__ import annotations

from fractions import Fraction

from app.solver import BetSizes, RiverSpot, RiverStrategy
from app.solver.tree import fmt_amount

POT = 100.0
BOARD = ("Kh", "8d", "5c", "3s", "2h")
VALUE, AIR = 3, 16  # combos of KK and JT

# s: (bluff share of bets, call share, bettor's value per hand), from the table above
HALF_STREET = {
    0.5: (Fraction(1, 4), Fraction(2, 3), Fraction(400, 19)),
    0.75: (Fraction(3, 10), Fraction(4, 7), Fraction(3000, 133)),
    1.0: (Fraction(1, 3), Fraction(1, 2), Fraction(450, 19)),
    2.0: (Fraction(2, 5), Fraction(1, 3), Fraction(500, 19)),
}


def half_street_spot(s: float) -> RiverSpot:
    """Caller out of position (only checks, then calls or folds), bettor in position with
    one bet size, s times the pot. Stacks deep enough never to matter."""
    return RiverSpot(BOARD, POT, (100 * POT, 100 * POT), oop_range="QQ", ip_range="KK, JT",
                     oop_sizes=BetSizes((), (), False), ip_sizes=BetSizes((s,), (), False), max_raises=0)


def bet_token(s: float) -> str:
    return "b" + fmt_amount(s * POT)


def is_value(combo) -> bool:
    return combo[0][0] == "K"


def half_street_play(spot: RiverSpot, s: float, bluff: float, call: float, value_bets: float = 1.0) -> RiverStrategy:
    """The bettor bets KK with probability value_bets and each JT with probability bluff;
    the caller calls with probability call."""
    b = bet_token(s)

    def rule(node, combo):
        if node.key == "":
            return {"x": 1.0}
        if node.key == "x":
            p = value_bets if is_value(combo) else bluff
            return {b: p, "x": 1.0 - p}
        return {"c": call, "f": 1.0 - call}

    return RiverStrategy.from_rule(spot, rule)


def half_street_equilibrium(s: float) -> RiverStrategy:
    """The equilibrium from the closed form: each JT bluffs (3s/(1+s))/16, the caller calls 1/(1+s)."""
    return half_street_play(half_street_spot(s), s, bluff=(VALUE * s / (1 + s)) / AIR, call=1 / (1 + s))


def bluff_share_of_bets(strategy: RiverStrategy, s: float) -> float:
    """Share of the bettor's bets (by weight) made with air."""
    combos = strategy.spot.combos(1)
    weights = strategy.spot.weights(1)
    p_bet = strategy.probs["x"][:, strategy.tree["x"].actions.index(bet_token(s))]
    total = float((weights * p_bet).sum())
    air = float(sum(w * p for c, w, p in zip(combos, weights, p_bet) if not is_value(c)))
    return air / total


def value_bet_share(strategy: RiverStrategy, s: float) -> float:
    combos = strategy.spot.combos(1)
    p_bet = strategy.probs["x"][:, strategy.tree["x"].actions.index(bet_token(s))]
    vals = [p for c, p in zip(combos, p_bet) if is_value(c)]
    return sum(vals) / len(vals)


def call_share(strategy: RiverStrategy, s: float) -> float:
    return strategy.frequencies("x " + bet_token(s))["c"]
