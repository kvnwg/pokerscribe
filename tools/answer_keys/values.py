"""What an answer is worth, worked out from its strategy alone.

A RESULT gives both players' strategies and no values. From the strategies this module
works out, exactly (every deal, with card removal, no sampling):

- each player's EV when both follow the answer, in chips per hand;
- how often play reaches each decision node, and how often each action is taken there;
- what a perfect counter-strategy wins against it (a best response), hence its
  exploitability.

It handles river spots and turn spots. On a turn spot every pair of combos is dealt each of
the 44 river cards neither of them holds, all as likely as each other.

Payoffs are app/solver's: the pot at the start of the spot is nobody's yet, the winner gets
it plus what the loser put in during the spot, the loser loses what they put in, and a
split gives each half the pot. The two EVs add up to the pot, and

    exploitability = (best response as OOP + best response as IP - pot) / 2

Inside, every payoff is counted from half the pot (as if each player had put half of it
in), which makes the game zero-sum; half the pot is added back to the values that leave
this module.

For a river spot these are the numbers of app/solver/exploitability.py (the tests check
that they agree). compare.py uses app/solver's own checker for the exploitability of river
spots, and this module for turn spots and for the EVs, reach and frequencies of both.
turn_solver.py solves a spot on the same Game (the exact turn reference).

TexasSolver's rule. TexasSolver gives each river card a weight of 1/46 where the exact
weight is 1/44 (it leaves out the opponent's two cards: 52 - 4 on the board - 2 in hand),
so in its game everything after the river card counts 44/46 as much as a fold on the turn.
Game(spot, river_cards=46) values an answer by that rule: it gives TexasSolver's own
reported exploitability on every turn spot, to the fifth decimal. By the exact rule the same
answers are 0.4% to 0.7% of the pot from an equilibrium (docs/research/PHASE4.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

import numpy as np

from app.solver.ranking import matchups
from app.solver.spot import IP, OOP, PLAYER_NAMES, parse_combo

from .spots import Decision, decision_nodes, deck_left

RIVER_CARDS = 44  # river cards left for a pair of combos on a turn board: 52 - 4 - 2 - 2
TEXASSOLVER_RIVER_CARDS = 46  # what TexasSolver divides by instead
EPS = 1e-9


@dataclass(frozen=True)
class Evaluation:
    """value: chips per hand for (oop, ip) when both follow the answer.
    reach[node]: the chance that play gets to the node (the river card's chance included).
    line_reach[node]: the same once the node's river card is known to come, so that a
    river node of a turn spot can be held against a threshold; equal to reach elsewhere.
    freq[node]: how often each action of the node is taken by the combos that get there, in
    the node's action order; None when the answer never gets there.
    filled_rows: combos the answer left out at some node (played evenly here)."""

    pot: float
    value: Tuple[float, float]
    reach: Dict[str, float]
    line_reach: Dict[str, float]
    freq: Dict[str, Optional[np.ndarray]]
    filled_rows: int


class Game:
    """A spot ready to be valued: its tree, its ranges and its showdown tables.

    river_cards: what each river card of a turn spot is weighted by, as 1 / river_cards.
    44 is exact; 46 is TexasSolver's rule (see the module text). River spots ignore it."""

    def __init__(self, spot: Mapping, river_cards: int = RIVER_CARDS):
        self.spot = spot
        self.nodes: Dict[str, Decision] = decision_nodes(spot)
        self.pot = float(spot["pot"])
        self.stack = float(min(spot["stacks"]))
        self.turn = spot["street"] == "turn"
        self.combos = tuple(list(spot["ranges"][name]) for name in PLAYER_NAMES)
        self.weights = tuple(np.array([float(w) for w in spot["ranges"][name].values()]) for name in PLAYER_NAMES)
        self.actor = {key: PLAYER_NAMES.index(node.actor) for key, node in self.nodes.items()}
        hands = tuple([parse_combo(c) for c in self.combos[p]] for p in (OOP, IP))
        board = list(spot["board"])
        # tables[card] = (meets, wins), both shaped (oop combos, ip combos): the weight of
        # each deal, and that weight signed by who wins (+ OOP, - IP, 0 for a split). The
        # key None is the street the spot starts on: for a turn spot, "meets" is then 1 for
        # every pair of combos that can be dealt, and "wins" adds up every river card.
        self.tables: Dict[Optional[str], Tuple[np.ndarray, np.ndarray]] = {}
        if not self.turn:
            self.cards: Tuple[str, ...] = ()
            outcome, possible = matchups(board, hands[OOP], hands[IP])
            meets = possible.astype(float)
            self.tables[None] = (meets, outcome * meets)
        else:
            self.cards = tuple(deck_left(board))
            shape = (len(hands[OOP]), len(hands[IP]))
            count, all_wins = np.zeros(shape), np.zeros(shape)
            for card in self.cards:
                keep = [np.array([card not in c for c in hands[p]]) for p in (OOP, IP)]
                live = [[c for c, k in zip(hands[p], keep[p]) if k] for p in (OOP, IP)]
                meets, wins = np.zeros(shape), np.zeros(shape)
                if live[OOP] and live[IP]:
                    outcome, possible = matchups(board + [card], live[OOP], live[IP])
                    block = np.ix_(keep[OOP], keep[IP])
                    meets[block] = possible
                    wins[block] = outcome * possible
                count += meets
                all_wins += wins
                self.tables[card] = (meets / river_cards, wins / river_cards)
            if not np.all((count == 0) | (count == RIVER_CARDS)):
                raise AssertionError("A pair of combos should have exactly 44 river cards left.")
            self.tables[None] = ((count > 0).astype(float), all_wins / river_cards)
        self.total = float(self.weights[OOP] @ self.tables[None][0] @ self.weights[IP])
        if self.total <= 0:
            raise ValueError("Every deal clashes: the two ranges share a card in every pairing.")
        # the chance of each river card (None: no card to wait for)
        self.card_share: Dict[Optional[str], float] = {None: 1.0}
        for card in self.cards:
            self.card_share[card] = float(self.weights[OOP] @ self.tables[card][0] @ self.weights[IP]) / self.total

    # ------------------------------------------------------------- the tree
    def river_card(self, node: Decision) -> Optional[str]:
        """The river card in the key of a river node of a turn spot (None anywhere else)."""
        if not (self.turn and node.street == "river"):
            return None
        return next(t for t in node.key.split() if t in self.tables)

    def child(self, node: Decision, action: str, before: float):
        """Where an action leads. `before` is what each player put in on earlier streets.
        ("node", key, 0), ("fold", None, what the folder has put in), ("show", None, what
        each player has put in), or ("deal", the key before the river card, what each put
        in on the turn)."""
        key = f"{node.key} {action}".strip()
        if key in self.nodes:
            return "node", key, 0.0
        if action == "f":
            return "fold", None, before + node.put_in[self.actor[node.key]]
        matched = max(node.put_in)  # a call matches the bet; after a check both are equal
        if self.turn and node.street == "turn" and matched < self.stack - EPS:
            return "deal", key, matched
        return "show", None, before + matched  # all in on the turn: every river card, no more betting

    # ------------------------------------------------------- the strategies
    def strategy_arrays(self, nodes: Mapping[str, Mapping]) -> Tuple[Dict[str, np.ndarray], int]:
        """The answer's node records as arrays shaped (combos of the actor, actions), and
        how many rows had to be filled in evenly because the answer left the combo out.
        Combos that hold the river card of a node can't be there, so they don't count."""
        out: Dict[str, np.ndarray] = {}
        filled = 0
        for key, node in self.nodes.items():
            rec = nodes[key]
            if tuple(rec["actions"]) != node.actions:
                raise ValueError(f"{key!r}: actions {rec['actions']} differ from {list(node.actions)}.")
            rows = rec["strategy"]
            card = self.river_card(node)
            combos = self.combos[self.actor[key]]
            n = len(node.actions)
            arr = np.full((len(combos), n), 1.0 / n)
            for i, combo in enumerate(combos):
                row = rows.get(combo)
                if row is None:
                    filled += not (card and card in (combo[:2], combo[2:]))
                    continue
                p = np.array([max(0.0, float(row[a])) for a in node.actions])
                if p.sum() > 0:
                    arr[i] = p / p.sum()
            out[key] = arr
        return out, filled

    # ------------------------------------------------------------- the values
    def evaluate(self, nodes: Mapping[str, Mapping]) -> Evaluation:
        """EVs, reach and action frequencies when both players follow the answer."""
        sigma, filled = self.strategy_arrays(nodes)
        reach: Dict[str, float] = {}
        line_reach: Dict[str, float] = {}
        freq: Dict[str, Optional[np.ndarray]] = {}
        half = self.pot / 2

        def walk(key: str, card: Optional[str], before: float, r_oop: np.ndarray, r_ip: np.ndarray) -> float:
            """OOP's chips from this node on, summed over every deal that gets here."""
            node = self.nodes[key]
            meets, wins = self.tables[card]
            oop_acts = self.actor[key] == OOP
            s = sigma[key]
            mass = r_oop * (meets @ r_ip) if oop_acts else r_ip * (r_oop @ meets)
            here = float(mass.sum())
            reach[key] = here / self.total
            line_reach[key] = reach[key] / self.card_share[card] if self.card_share[card] > 0 else 0.0
            freq[key] = (mass @ s) / here if here > 0 else None
            total = 0.0
            for a, action in enumerate(node.actions):
                q_oop, q_ip = (r_oop * s[:, a], r_ip) if oop_acts else (r_oop, r_ip * s[:, a])
                kind, child, chips = self.child(node, action, before)
                if kind == "node":
                    total += walk(child, card, before, q_oop, q_ip)
                elif kind == "fold":
                    total += (-(half + chips) if oop_acts else half + chips) * float(q_oop @ meets @ q_ip)
                elif kind == "show":
                    total += (half + chips) * float(q_oop @ wins @ q_ip)
                else:
                    for river in self.cards:
                        total += walk(f"{child} {river}", river, chips, q_oop, q_ip)
            return total

        v = walk("", None, 0.0, self.weights[OOP], self.weights[IP]) / self.total
        return Evaluation(self.pot, (half + v, half - v), reach, line_reach, freq, filled)

    def best_response(self, sigma: Mapping[str, np.ndarray], player: int) -> float:
        """Chips per hand a perfect counter-strategy wins as `player` against the other
        player's part of `sigma` (arrays from strategy_arrays)."""
        half = self.pot / 2

        def values(key: str, card: Optional[str], before: float, opp: np.ndarray) -> np.ndarray:
            """For each of the player's combos: the best it can do from this node on, summed
            over the opponent's combos (weighted by how often each gets here)."""
            node = self.nodes[key]
            mine = self.actor[key] == player
            best = None
            for a, action in enumerate(node.actions):
                v = after(node, action, card, before, opp if mine else opp * sigma[key][:, a])
                if best is None:
                    best = v
                else:
                    best = np.maximum(best, v) if mine else best + v
            return best

        def after(node: Decision, action: str, card: Optional[str], before: float, opp: np.ndarray) -> np.ndarray:
            kind, child, chips = self.child(node, action, before)
            if kind == "node":
                return values(child, card, before, opp)
            if kind == "deal":
                total = 0.0
                for river in self.cards:
                    total = total + values(f"{child} {river}", river, chips, opp)
                return total
            meets, wins = self.tables[card]
            if kind == "fold":
                m = meets @ opp if player == OOP else opp @ meets
                return (-(half + chips) if self.actor[node.key] == player else half + chips) * m
            return (half + chips) * (wins @ opp if player == OOP else -(opp @ wins))

        root = values("", None, 0.0, self.weights[1 - player])
        return half + float(self.weights[player] @ root) / self.total

    def exploitability(self, nodes: Mapping[str, Mapping]) -> Tuple[float, int]:
        """(exploitability of the answer as a share of the pot, rows filled in evenly)."""
        sigma, filled = self.strategy_arrays(nodes)
        best = self.best_response(sigma, OOP) + self.best_response(sigma, IP)
        return (best - self.pot) / 2 / self.pot, filled

    def checks(self, nodes: Mapping[str, Mapping]) -> Dict:
        """What checks.river_checks gives for a river spot, for any spot: the answer's
        exploitability, each player's value, and bounds on the spot's true value for OOP
        (pot - IP's best response <= true value <= OOP's best response)."""
        sigma, filled = self.strategy_arrays(nodes)
        best = (self.best_response(sigma, OOP), self.best_response(sigma, IP))
        value = self.evaluate(nodes).value
        r = lambda x: round(float(x), 6)  # noqa: E731
        return {"exploitability_pot": round((best[OOP] + best[IP] - self.pot) / 2 / self.pot, 8),
                "filled_rows": filled, "values": {"oop": r(value[OOP]), "ip": r(value[IP])},
                "oop_value_bounds": [r(self.pot - best[IP]), r(best[OOP])]}
