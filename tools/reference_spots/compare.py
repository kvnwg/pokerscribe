"""Check another solver's answer to a reference spot against the saved answer.

A spot can have many equilibria, so strategies are not compared hand by hand. What every
equilibrium shares is the value of the game, so the checks are (data/SPOT_FORMAT.md,
"Comparing a solver to a key"):

1. the answer is close to an equilibrium by our own exact best response
   (app/solver/exploitability.py), whatever the other solver says about itself;
2. its value is close to the reference value;
3. its bounds on the true value meet the reference's (if they don't, one of the two
   answers is wrong or the two solvers are solving different games);
4. it passes the spot's expected checks and, where the value is known, has that value.

The known bluff and call shares of the polar games are a fifth check, off unless asked for
(`share_tol`): shares move far more than the value does. An answer 0.3% of the pot from an
equilibrium can have a call share 7 points off (measured on py05), so ask for them only
of a tight solve (0.01% of the pot or better, where they are within half a point).
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Tuple

from tools.answer_keys.checks import check_expected, river_checks

from .known import known_failures

MAX_EXPLOITABILITY = 0.005  # share of the pot: the Phase 4 gate for a river answer
VALUE_TOL = 0.005  # share of the pot: the Phase 4 gate "within 0.5% pot EV"


def check_answer(spot: Mapping, nodes: Mapping[str, Mapping], reference_checks: Mapping, *,
                 max_exploitability: float = MAX_EXPLOITABILITY, value_tol: float = VALUE_TOL,
                 share_tol: Optional[float] = None) -> Tuple[Dict, List[str]]:
    """(numbers, problems) for one answer: `nodes` are the node records of the other
    solver's RESULT, `reference_checks` the "checks" of the reference RESULT's header."""
    pot = spot["pot"]
    checks = river_checks(spot, nodes)
    ref_value = reference_checks["values"]["oop"]
    low = max(checks["oop_value_bounds"][0], reference_checks["oop_value_bounds"][0])
    high = min(checks["oop_value_bounds"][1], reference_checks["oop_value_bounds"][1])
    numbers = {"exploitability_pot": checks["exploitability_pot"], "oop_value": checks["values"]["oop"],
               "difference": checks["values"]["oop"] - ref_value, "bounds_meet": low <= high + 1e-6,
               "filled_rows": checks["filled_rows"]}
    problems = []
    if checks["exploitability_pot"] > max_exploitability:
        problems.append(f"{100 * checks['exploitability_pot']:.3f}% of the pot from an equilibrium "
                        f"(limit {100 * max_exploitability:g}%)")
    if abs(numbers["difference"]) > value_tol * pot:
        problems.append(f"OOP value {numbers['oop_value']:.3f}, reference {ref_value:.3f} "
                        f"(limit {100 * value_tol:g}% of the pot)")
    if not numbers["bounds_meet"]:
        problems.append(f"its bounds on the true value {checks['oop_value_bounds']} don't meet the "
                        f"reference's {list(reference_checks['oop_value_bounds'])}")
    problems += check_expected(spot, nodes)
    problems += known_failures(spot, nodes, checks, tol_value=value_tol * pot, tol_share=share_tol)
    return numbers, problems
