"""Reading the answers with known solutions out of a RESULT: who bets, what share of the
bets are bluffs, how often the bluff catcher calls (the polar games py01 to py08)."""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional

from app.solver.spot import parse_combo

from .defs import KNOWN


def _is_nuts(combo: str) -> bool:
    a, b = parse_combo(combo)
    return a[0] == b[0]  # in the polar games every pair in the bettor's range is a set


def polar_shares(spot: Mapping, nodes: Mapping[str, Mapping]) -> Dict[str, float]:
    """{"bluffs": share of the bets (by weight) made with air, "calls": how often the bluff
    catcher calls the bet, "nuts_bet": how often the nuts bet} for one of the polar games."""
    known = KNOWN[spot["id"]]
    bettor = known["bettor"]
    caller = "oop" if bettor == "ip" else "ip"
    bet_node = nodes["x" if bettor == "ip" else ""]
    (bet,) = [a for a in bet_node["actions"] if a.startswith("b")]
    weights = spot["ranges"][bettor]
    total = air = nuts = nuts_weight = 0.0
    for combo, row in bet_node["strategy"].items():
        w = weights[combo]
        total += w * row[bet]
        if _is_nuts(combo):
            nuts += w * row[bet]
            nuts_weight += w
        else:
            air += w * row[bet]
    call_node = nodes[("x " if bettor == "ip" else "") + bet]
    cw = spot["ranges"][caller]
    calls = sum(cw[c] * row["c"] for c, row in call_node["strategy"].items()) / sum(cw.values())
    return {"bluffs": air / total if total else 0.0, "calls": calls, "nuts_bet": nuts / nuts_weight}


def known_failures(spot: Mapping, nodes: Mapping[str, Mapping], checks: Mapping, tol_value: float = 0.02,
                   tol_share: Optional[float] = 0.005) -> List[str]:
    """Where an answer misses a known answer: the value within tol_value chips (of a pot of
    100), and in the polar games the bluff and call shares within tol_share (None: the
    shares aren't checked). `checks` is river_checks(spot, nodes). The defaults are for the
    reference answers themselves."""
    want = KNOWN.get(spot["id"])
    if not want:
        return []
    out = []
    if abs(checks["values"]["oop"] - float(want["oop_value"])) > tol_value:
        out.append(f"OOP value {checks['values']['oop']:.4f}, known {float(want['oop_value']):.4f}")
    if "bettor" in want and tol_share is not None:
        got = polar_shares(spot, nodes)
        for name in ("bluffs", "calls"):
            if abs(got[name] - float(want[name])) > tol_share:
                out.append(f"{name} {got[name]:.4f}, known {float(want[name]):.4f}")
        if got["nuts_bet"] < 1 - tol_share:
            out.append(f"the nuts bet only {got['nuts_bet']:.4f} of the time")
    return out
