"""The river betting tree of a spot.

Each node is keyed by the actions so far, separated by spaces: "" is the start of the
river (out of position to act), "x" a check, "b50" a bet of 50, "r150" a raise to 150,
"c" a call, "f" a fold. Amounts are what that player has put in on the river so far
("bet 50", "raise to 150"), in the spot's chips, so "x b50 r150 c" reads: check, bet 50,
raise to 150, call.

Bets are shares of the pot; raises are shares of the pot after calling; sizes at or over
the effective stack become all in, and equal amounts are offered once. A raise is at
least the size of the bet or raise it answers, unless it is all in. Where all in is added
as a choice of its own is the sizes' business (BetSizes.adds_allin).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

from .spot import IP, OOP, RiverSpot

FOLD, SHOWDOWN = "fold", "showdown"


def fmt_amount(x: float) -> str:
    r = round(x, 2)
    if abs(r - round(r)) < 1e-9:
        return str(int(round(r)))
    return f"{r:.2f}".rstrip("0").rstrip(".")


@dataclass(frozen=True)
class Node:
    key: str
    player: int  # who acts: OOP or IP; -1 at a terminal node
    actions: Tuple[str, ...]  # action tokens, in order
    children: Tuple[str, ...]  # the key each action leads to
    put_in: Tuple[float, float]  # chips each player has put in on the river so far
    terminal: str = ""  # "", "fold" or "showdown"
    folder: int = -1  # who folded, at a fold node

    @property
    def is_terminal(self) -> bool:
        return bool(self.terminal)

    def child(self, action: str) -> str:
        return self.children[self.actions.index(action)]


def action_amount(token: str) -> Optional[float]:
    """The amount in a bet or raise token ("b50" -> 50.0), None for x, c and f."""
    return float(token[1:]) if token[:1] in ("b", "r") else None


def describe_action(token: str) -> str:
    kind = token[:1]
    if kind == "x":
        return "check"
    if kind == "c":
        return "call"
    if kind == "f":
        return "fold"
    if kind == "b":
        return f"bet {token[1:]}"
    if kind == "r":
        return f"raise to {token[1:]}"
    raise ValueError(f"Unknown action token: {token!r}")


class GameTree:
    def __init__(self, spot: RiverSpot):
        self.spot = spot
        self.nodes: Dict[str, Node] = {}
        self._build("", OOP, (0.0, 0.0), raises=0, checked=False)

    @property
    def root(self) -> Node:
        return self.nodes[""]

    def __getitem__(self, key: str) -> Node:
        return self.nodes[key]

    def __contains__(self, key: str) -> bool:
        return key in self.nodes

    def __len__(self) -> int:
        return len(self.nodes)

    def decision_nodes(self, player: Optional[int] = None) -> Iterator[Node]:
        for n in self.nodes.values():
            if not n.is_terminal and (player is None or n.player == player):
                yield n

    def terminals(self) -> Iterator[Node]:
        return (n for n in self.nodes.values() if n.is_terminal)

    def path(self, key: str) -> List[Tuple[Node, str]]:
        """(node, action taken there) from the root down to the node with this key."""
        out, node = [], self.root
        for token in key.split():
            out.append((node, token))
            node = self.nodes[node.child(token)]
        return out

    # ---------------------------------------------------------------- build
    def _add(self, node: Node) -> None:
        self.nodes[node.key] = node

    def _build(self, key: str, player: int, put: Tuple[float, float], raises: int, checked: bool) -> None:
        spot = self.spot
        stack = spot.effective_stack
        other = 1 - player
        mine, theirs = put[player], put[other]
        sizes = spot.sizes(player)
        actions: List[str] = []
        children: List[str] = []

        def go(token: str) -> str:
            k = f"{key} {token}".strip()
            actions.append(token)
            children.append(k)
            return k

        if theirs <= mine + 1e-9:  # no bet to answer: check or bet
            k = go("x")
            if checked or player == IP:
                self._add(Node(k, -1, (), (), put, SHOWDOWN))
            else:
                self._build(k, other, put, raises, checked=True)
            allin = sizes.adds_allin("bets", stack / spot.pot)
            for amount in _amounts([f * spot.pot for f in sizes.bets], stack, allin, floor=0.0):
                new = list(put)
                new[player] = amount
                k = go("b" + fmt_amount(amount))
                self._build(k, other, (new[0], new[1]), raises, checked)
        else:  # facing a bet or raise: fold, call or raise
            k = go("f")
            self._add(Node(k, -1, (), (), put, FOLD, folder=player))
            k = go("c")
            called = list(put)
            called[player] = theirs
            self._add(Node(k, -1, (), (), (called[0], called[1]), SHOWDOWN))
            if raises < spot.max_raises and theirs < stack - 1e-9:
                after_call = spot.pot + 2 * theirs
                least = theirs + (theirs - mine)  # a raise is at least the bet it answers
                wanted = [max(least, theirs + f * after_call) for f in sizes.raise_sizes(raises)]
                allin = sizes.adds_allin(sizes.raise_list(raises), (stack - theirs) / after_call)
                for amount in _amounts(wanted, stack, allin, floor=theirs):
                    new = list(put)
                    new[player] = amount
                    k = go("r" + fmt_amount(amount))
                    self._build(k, other, (new[0], new[1]), raises + 1, checked)
        self._add(Node(key, player, tuple(actions), tuple(children), put))


def _amounts(wanted: List[float], stack: float, allin: bool, floor: float) -> List[float]:
    """Bet or raise-to amounts: capped at the stack, above `floor`, each offered once."""
    out = []
    for x in list(wanted) + ([stack] if allin else []):
        x = round(min(x, stack), 2)
        if x > floor + 1e-9 and x not in out:
            out.append(x)
    return sorted(out)


def build_tree(spot: RiverSpot) -> GameTree:
    return GameTree(spot)
