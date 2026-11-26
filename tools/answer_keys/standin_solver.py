"""A stand-in for the Rust subgame-solve binary: the same command line, answered by the
Python solvers (app/solver for a river spot, turn_solver.py for a turn spot). It is here to
test the harness (python -m tools.answer_keys run) before the Rust binary exists, and to
time the Python solvers the way the Rust one will be timed.

    python tools/answer_keys/standin_solver.py <spot.json> [--out result.json]
        [--target-exploitability 0.3] [--max-iterations N] [--time-ms N] [--threads N]

It writes the spot's RESULT (data/SPOT_FORMAT.md: JSON Lines, the header then one line per
decision node) to --out, or to standard output without it. The header's "solver" block has
the solve time (elapsed_s), the iterations and the exploitability (exploitability_pot, a
share of the pot).

--target-exploitability is in percent of the pot, like TexasSolver's accuracy. --threads
is accepted and ignored. A turn spot takes seconds where a river spot takes milliseconds.

    python -m tools.answer_keys run --solver tools/answer_keys/standin_solver.py --spots river --out /tmp/standin
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.answer_keys.python_solver import solve_spot  # noqa: E402
from tools.answer_keys.result import encode  # noqa: E402
from tools.answer_keys.spots import SpotError, load_spot  # noqa: E402

DEFAULT_TARGET_PCT = 0.3


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="standin_solver.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("spot", help="a spot file (data/answer_keys/spots/<id>.json)")
    p.add_argument("--out", help="where to write the RESULT (default: standard output)")
    p.add_argument("--target-exploitability", type=float, default=DEFAULT_TARGET_PCT, help="percent of the pot")
    p.add_argument("--max-iterations", type=int)
    p.add_argument("--time-ms", type=float)
    p.add_argument("--threads", type=int, help="accepted and ignored")
    args = p.parse_args(argv)
    try:
        spot = load_spot(args.spot)
        # without a limit of its own a run still ends: solve_spot's safety stop on iterations
        header, nodes = solve_spot(spot, args.target_exploitability, args.max_iterations, args.time_ms)
    except (SpotError, OSError, ValueError) as e:
        print(f"standin_solver: {e}", file=sys.stderr)
        return 2
    data = encode(header, nodes)
    if args.out:
        with open(args.out, "wb") as f:
            f.write(data)
    else:
        sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
