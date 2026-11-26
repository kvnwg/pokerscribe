"""Play Slumbot heads-up through its public API, or summarise a hand log.

    python -m tools.slumbot play --hands 200 --log runs/slumbot/checkcall.jsonl [--bot checkcall]
                                 [--resume] [--login] [--min-interval 1.0]
    python -m tools.slumbot stats runs/slumbot/checkcall.jsonl

``--hands`` is the total for the log: with ``--resume`` the session continues until the log holds
that many finished hands. ``--login`` reads SLUMBOT_USERNAME and SLUMBOT_PASSWORD (or asks); the
password is never written anywhere. Logging in only matters for Slumbot's leaderboards.
Play an even number of hands so each seat is played equally often.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from .bots import BOTS, make_bot
from .client import MIN_INTERVAL_FLOOR, SlumbotClient
from .session import format_summary, hands_in, read_log, run_session, summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.slumbot", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("play", help="play hands against Slumbot")
    p.add_argument("--hands", type=int, required=True, help="total finished hands wanted in the log")
    p.add_argument("--log", required=True, help="JSONL hand log (a .state.json is kept next to it)")
    p.add_argument("--bot", default="checkcall", choices=sorted(BOTS))
    p.add_argument("--resume", action="store_true", help="continue an existing log")
    p.add_argument("--login", action="store_true", help="log in (SLUMBOT_USERNAME / SLUMBOT_PASSWORD)")
    p.add_argument("--min-interval", type=float, default=1.0,
                   help=f"seconds between requests (default 1.0, floor {MIN_INTERVAL_FLOOR})")
    p.add_argument("--quiet", action="store_true")
    s = sub.add_parser("stats", help="summarise a hand log")
    s.add_argument("log")
    args = ap.parse_args(argv)

    if args.cmd == "stats":
        print(format_summary(summary(hands_in(read_log(args.log)))))
        return 0

    if args.hands <= 0:
        ap.error("--hands must be positive")
    bot = make_bot(args.bot)
    client = SlumbotClient(min_interval=args.min_interval)
    if args.login:
        user = os.environ.get("SLUMBOT_USERNAME") or input("Slumbot username: ")
        pw = os.environ.get("SLUMBOT_PASSWORD") or getpass.getpass("Slumbot password: ")
        client.login(user, pw)
    echo = (lambda _m: None) if args.quiet else (lambda m: print(m, flush=True))
    result = run_session(client, bot, args.log, args.hands, resume=args.resume,
                         logged_in=args.login, echo=echo)
    print(format_summary(result))
    print(f"{client.requests} requests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
