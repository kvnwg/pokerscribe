"""Benchmark a bot against GTO Wizard AI through the GTO Wizard Benchmark API.

    export GTOWIZARD_API_KEY=...          (see README.md; the key is never passed on the command line)
    python -m tools.gtowizard play --hands 1000 --log docs/research/runs/gtowizard/run.jsonl \\
                                   --bot checkcall --accept-terms [--resume]
    python -m tools.gtowizard results docs/research/runs/gtowizard/run.jsonl
    python -m tools.gtowizard stats docs/research/runs/gtowizard/run.jsonl
    python -m tools.gtowizard limits
    python -m tools.gtowizard mock --port 8765      (a local stand-in, to try all of this without a key)

Benchmarking only. The hands must NEVER be used to train, tune or calibrate anything. No human
help during hands. Results are public from the first hand. ``play`` refuses to start without
``--accept-terms``.

``--hands`` is the total for the log: with ``--resume`` the session continues until the log holds
that many finished hands. Hands left open on the server by an earlier run are always finished
first. The daily, weekly and monthly caps are never exceeded: the session stops before the hand
that would.
"""
from __future__ import annotations

import argparse
import sys

from ..slumbot.bots import BOTS, make_bot
from .client import API_URL, KEY_ENV, MIN_INTERVAL_FLOOR, GTOWizardClient, GTOWizardError
from .limits import (PUBLISHED, WINDOWS, Caps, HandBudget, Ledger, default_ledger_path, next_resets,
                     use_server_counts, utcnow)
from .session import TERMS, format_summary, read_log, run_session, save_results, summary


def _add_api(p: argparse.ArgumentParser) -> None:
    p.add_argument("--url", default=API_URL,
                   help="API address (default: the real one; http://127.0.0.1:PORT for the mock)")


def _add_caps(p: argparse.ArgumentParser) -> None:
    p.add_argument("--ledger", help="file counting the hands started with this key "
                                    "(default: gtowizard_ledger.jsonl in PokerScribe's data folder)")
    for w in WINDOWS:
        p.add_argument(f"--{w}-cap", type=int, default=PUBLISHED[w],
                       help=f"hands allowed per {w} (default and most: {PUBLISHED[w]:,})")


def _budget(args) -> HandBudget:
    try:
        caps = Caps(**{w: getattr(args, f"{w}_cap") for w in WINDOWS})
    except ValueError as e:
        raise SystemExit(str(e))
    return HandBudget(Ledger(args.ledger or default_ledger_path()), caps)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.gtowizard", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("play", help="play hands against GTO Wizard AI")
    p.add_argument("--hands", type=int, required=True, help="total finished hands wanted in the log")
    p.add_argument("--log", required=True, help="JSONL hand log")
    p.add_argument("--bot", required=True, choices=sorted(BOTS))
    p.add_argument("--accept-terms", action="store_true",
                   help="you have read the terms: benchmark only, never training data, no human "
                        "help during hands, public results")
    p.add_argument("--resume", action="store_true", help="continue an existing log")
    p.add_argument("--min-interval", type=float, default=0.5,
                   help=f"seconds between requests (default 0.5, floor {MIN_INTERVAL_FLOOR})")
    p.add_argument("--quiet", action="store_true")
    _add_api(p)
    _add_caps(p)

    r = sub.add_parser("results", help="fetch GTO Wizard's luck-adjusted results and save them with the log")
    r.add_argument("log")
    _add_api(r)

    s = sub.add_parser("stats", help="summarise a hand log (no network)")
    s.add_argument("log")

    c = sub.add_parser("limits", help="show the hand caps, what is used and what is left")
    c.add_argument("--offline", action="store_true", help="use the local ledger only, no request")
    _add_api(c)
    _add_caps(c)

    m = sub.add_parser("mock", help="run the local mock server (not GTO Wizard AI; see mock_server.py)")
    m.add_argument("--port", type=int, default=8765)
    m.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    try:
        return _run(ap, args)
    except GTOWizardError as e:  # messages are built without the key (client.scrub)
        print(f"error: {e}", file=sys.stderr)
        return 1


def _run(ap: argparse.ArgumentParser, args) -> int:
    if args.cmd == "stats":
        print(format_summary(summary(read_log(args.log))))
        return 0

    if args.cmd == "mock":
        from .mock_server import MockBenchmark, MockServer
        server = MockServer(MockBenchmark(seed=args.seed), port=args.port)
        print(f"Mock benchmark at {server.url} (a random opponent and made-up AIVAT numbers, "
              "not GTO Wizard AI).", flush=True)
        print(f"Try it:  {KEY_ENV}=any-text python -m tools.gtowizard play --url {server.url} "
              "--hands 20 --log /tmp/mock.jsonl --ledger /tmp/mock_ledger.jsonl --bot checkcall "
              "--accept-terms", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0

    if args.cmd == "limits":
        budget = _budget(args)
        now = utcnow()
        ledger_only = args.offline
        if not args.offline:
            client = GTOWizardClient(url=args.url)
            uncounted = use_server_counts(budget, client, now, open_hands=len(client.in_progress()))
            if uncounted:
                print("note: " + uncounted)
                ledger_only = True
        used, left, resets = budget.used(now), budget.left(now), next_resets(now)
        print("counted from " + ("the local ledger only" if ledger_only
                                 else "the local ledger and the server (the larger number)"))
        for w in WINDOWS:
            print(f"  this {w + ':':7} {used[w]:>6,} used of {budget.caps.of(w):>6,}, "
                  f"{left[w]:>6,} left, resets {resets[w]:%Y-%m-%d %H:%M} UTC")
        return 0

    if args.cmd == "results":
        snap = save_results(GTOWizardClient(url=args.url), args.log)
        print(format_summary(summary(read_log(args.log))))
        return 0 if snap.get("all_time") else 1

    # play
    if args.hands <= 0:
        ap.error("--hands must be positive")
    if not args.accept_terms:
        print(TERMS + "\nPass --accept-terms to play.", file=sys.stderr)
        return 2
    bot = make_bot(args.bot)
    client = GTOWizardClient(url=args.url, min_interval=args.min_interval)
    echo = (lambda _m: None) if args.quiet else (lambda msg: print(msg, flush=True))
    result = run_session(client, bot, args.log, args.hands, accept_terms=True, resume=args.resume,
                         budget=_budget(args), echo=echo)
    print(format_summary(result))
    print(f"{client.requests} requests")
    return 0 if result["stopped"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
