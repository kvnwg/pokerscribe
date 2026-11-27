"""Training runs on a rented Google Cloud machine. Run from the repo root on your own computer.

    python -m tools.cloud check                 # everything checkable without spending money
    python -m tools.cloud launch [--dry-run]    # bucket, bundle, machine; prints how to watch
    python -m tools.cloud watch [--every 60]    # progress, it/s, memory, cost, last checkpoint
    python -m tools.cloud recover [--once]      # restarts the machine after Spot stops it
    python -m tools.cloud logs [--supervisor]   # the trainer's (or supervisor's) output
    python -m tools.cloud artifacts [--download DIR]   # strategy files and other results
    python -m tools.cloud stop                  # saves, powers off; keeps the disk and bucket
    python -m tools.cloud resume                # starts it again after a stop
    python -m tools.cloud cleanup [--yes]       # stop, delete the machine and disk; keep bucket
    python -m tools.cloud leftovers             # everything in the project still costing money
    python -m tools.cloud local-test            # the whole cycle on this computer, no cloud
    python -m tools.cloud local-test --trainer T --config C   # the same with a real trainer

Settings come from ~/.config/pokerscribe/cloud.env (or --settings, or PSCLOUD_SETTINGS) and
PSCLOUD_* environment variables. See tools/cloud/README.md and settings.example.env.
"""
from __future__ import annotations

import argparse
import sys

from . import control, local_test
from .gce import GcloudError
from .settings import SettingsError, load
from .supervisor import StoreError


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.cloud", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--settings", help="settings file (default ~/.config/pokerscribe/cloud.env)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="check settings, login, APIs, quota, bucket (no cost)")
    p = sub.add_parser("launch", help="create the bucket, upload the bundle, create the machine")
    p.add_argument("--dry-run", action="store_true",
                   help="print every command and upload, run nothing (assumes a fresh run)")
    p.add_argument("--force", action="store_true", help="launch even if the run is done")
    p = sub.add_parser("watch", help="show the run's progress and cost")
    p.add_argument("--every", type=float, help="refresh every N seconds")
    p = sub.add_parser("recover", help="keep the run going through Spot preemptions")
    p.add_argument("--once", action="store_true", help="look once, act once, exit")
    p = sub.add_parser("logs", help="print the last lines of the trainer's output")
    p.add_argument("--supervisor", action="store_true", help="the supervisor's log instead")
    p.add_argument("-n", "--lines", type=int, default=60)
    p = sub.add_parser("artifacts", help="list (or download) the run's artifacts in the bucket")
    p.add_argument("--download", metavar="DIR", help="copy the ones DIR does not have yet")
    p.add_argument("--only", metavar="GLOB", help="only names matching GLOB, e.g. 'strategy-*'")
    sub.add_parser("stop", help="stop the machine (it saves first); keep disk and bucket")
    sub.add_parser("resume", help="start the machine again after a stop")
    p = sub.add_parser("cleanup", help="stop, delete the machine and its disk, keep the bucket")
    p.add_argument("--yes", action="store_true", help="don't ask")
    sub.add_parser("leftovers", help="list everything in the project still costing money")
    p = sub.add_parser("local-test", help="fake trainer, local folder as bucket, SIGTERM, resume")
    p.add_argument("--keep", metavar="DIR", help="run in DIR and keep the files")
    p.add_argument("--trainer", help="a real trainer instead of the fake one (a dress rehearsal)")
    p.add_argument("--config", help="the trainer's config, with --trainer")
    p.add_argument("--files", default="", help="local copies of TRAINER_FILES, comma-separated")
    p.add_argument("--trainer-args", default="", help="e.g. '--threads 4'")
    p.add_argument("--sigterm-after", type=int, default=2, help="stages before the SIGTERM")
    p.add_argument("--stop-after", type=int, default=4, help="stages before the stop")
    p.add_argument("--timeout-minutes", type=float, default=60.0)
    p.add_argument("--report", help="write what was measured to this JSON file")
    args = ap.parse_args(argv)

    if args.cmd == "local-test":
        return local_test.main(args.keep, trainer=args.trainer, config=args.config,
                               files=[f for f in args.files.split(",") if f.strip()],
                               trainer_args=args.trainer_args, sigterm_after=args.sigterm_after,
                               stop_after=args.stop_after, timeout_minutes=args.timeout_minutes,
                               report=args.report)
    try:
        s = load(args.settings)
        if args.cmd != "check" and not s.PROJECT:
            print("PROJECT is not set: copy tools/cloud/settings.example.env to "
                  "~/.config/pokerscribe/cloud.env and fill it in", file=sys.stderr)
            return 2
        ctx = control.make_ctx(s, dry_run=getattr(args, "dry_run", False))
        if args.cmd == "check":
            return control.check(ctx)
        if args.cmd == "launch":
            return control.launch(ctx, force=args.force)
        if args.cmd == "watch":
            return control.watch(ctx, every=args.every)
        if args.cmd == "recover":
            return control.recover(ctx, once=args.once)
        if args.cmd == "logs":
            return control.logs(ctx, "supervisor" if args.supervisor else "trainer", args.lines)
        if args.cmd == "artifacts":
            return control.artifacts(ctx, download=args.download, only=args.only)
        if args.cmd == "stop":
            return control.stop(ctx)
        if args.cmd == "resume":
            return control.resume(ctx)
        if args.cmd == "cleanup":
            return control.cleanup(ctx, yes=args.yes)
        if args.cmd == "leftovers":
            return control.print_leftovers(ctx)
    except (SettingsError, GcloudError, StoreError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 2


if __name__ == "__main__":
    sys.exit(main())
