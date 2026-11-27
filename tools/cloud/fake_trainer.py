#!/usr/bin/env python3
"""A fake trainer for testing the cloud tooling without a real run (and without spending money).

It follows the trainer contract exactly (README.md, "The trainer"):

    fake_trainer.py --config <file> --checkpoint-dir <dir> [--resume]

- Each "iteration" sleeps a little and moves a hash chain one step, so the final hash says
  whether a run that was stopped and resumed did the same work as one that never stopped.
- It writes ``checkpoint_name`` every ``checkpoint_seconds``: to ``<name>.tmp`` first, flushed
  to the disk, then renamed, as the CFR library does. The file has a checksum.
- On SIGTERM it finishes the current iteration, saves, and exits with ``stop_exit_code`` (75).
- It exits 0 only when all iterations are done.
- It prints progress lines on stdout: ``{"iterations": 120, "target_iterations": 400}``.
- ``--resume`` without a checkpoint, a damaged checkpoint, or a checkpoint present without
  ``--resume``: exit 2. The supervisor has to get the flag right.

The config is JSON; every field is optional:

    {"iterations": 400, "iteration_seconds": 0.01, "checkpoint_seconds": 0.5,
     "checkpoint_name": "fake.ckpt", "checkpoint_bytes": 4096, "save_seconds": 0.0,
     "progress_every": 10, "crash_at": null, "stop_exit_code": 75}

``crash_at`` makes a fresh (not resumed) run exit 3 at that iteration, to test crash restarts.
``stage_every`` (off by default) writes a result at every multiple of that many iterations,
as the blueprint trainer writes its strategy files: ``stage-<i>.bps`` (written whole, then
renamed) and a line appended to ``stages.jsonl``, which says whether the stage before is on
the disk (on a new machine it is only there if the supervisor put it back).

``hold_at`` with ``hold_file`` (off by default) makes a test's "halfway" happen before the run
can finish, however fast the machine: at iteration ``hold_at`` (after its progress line and
stage), if ``hold_file`` exists, the trainer saves a checkpoint, prints
``{"event": "holding", ...}`` and waits while the file is there, until SIGTERM (then it saves
and exits as usual). A run resumed at ``hold_at`` or later never reaches it again, so never
holds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time

MAGIC = b"PSFAKE1\n"
SEED = b"pokerscribe fake trainer"

DEFAULTS = {
    "iterations": 400,
    "iteration_seconds": 0.01,
    "checkpoint_seconds": 0.5,
    "checkpoint_name": "fake.ckpt",
    "checkpoint_bytes": 4096,
    "save_seconds": 0.0,
    "progress_every": 10,
    "crash_at": None,
    "stop_exit_code": 75,
    "stage_every": None,
    "hold_at": None,
    "hold_file": None,
}


def start_digest() -> str:
    return hashlib.sha256(SEED).hexdigest()


def step(digest: str, i: int) -> str:
    return hashlib.sha256(f"{digest}:{i}".encode()).hexdigest()


def expected_digest(iterations: int) -> str:
    """The hash after ``iterations`` iterations of an uninterrupted run."""
    d = start_digest()
    for i in range(iterations):
        d = step(d, i)
    return d


def encode(iteration: int, digest: str, target: int, pad_to: int) -> bytes:
    payload = json.dumps({"iteration": iteration, "digest": digest, "target": target},
                         sort_keys=True).encode()
    body = MAGIC + payload + b"\n" + hashlib.sha256(payload).hexdigest().encode() + b"\n"
    return body + b"\0" * max(0, pad_to - len(body))


def decode(data: bytes) -> dict:
    if not data.startswith(MAGIC):
        raise ValueError("not a fake checkpoint")
    lines = data[len(MAGIC):].split(b"\n", 2)
    if len(lines) < 2:
        raise ValueError("checkpoint cut short")
    payload, check = lines[0], lines[1]
    if hashlib.sha256(payload).hexdigest().encode() != check:
        raise ValueError("checkpoint checksum does not match")
    return json.loads(payload)


def save(path: str, data: bytes, save_seconds: float) -> None:
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        half = len(data) // 2
        f.write(data[:half])
        if save_seconds:
            time.sleep(save_seconds)        # a slow save, to test the in-between states
        f.write(data[half:])
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def stage(ckdir: str, i: int, every: int, digest: str) -> None:
    """A stage result: a file of its own and a line in stages.jsonl."""
    save(os.path.join(ckdir, f"stage-{i}.bps"), f"{i} {digest}\n".encode(), 0.0)
    before = os.path.exists(os.path.join(ckdir, f"stage-{i - every}.bps")) if i > every else None
    with open(os.path.join(ckdir, "stages.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"iterations": i, "previous_on_disk": before}) + "\n")


def say(obj: dict) -> None:
    print(json.dumps(obj, sort_keys=True), flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="fake trainer for tools/cloud tests")
    ap.add_argument("--config", required=True)
    ap.add_argument("--checkpoint-dir", required=True)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args(argv)
    with open(args.config, encoding="utf-8") as f:
        cfg = dict(DEFAULTS, **json.load(f))
    target = int(cfg["iterations"])
    path = os.path.join(args.checkpoint_dir, cfg["checkpoint_name"])
    os.makedirs(args.checkpoint_dir, exist_ok=True)

    stop = {"flag": False}

    def on_term(_signum, _frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, on_term)

    if args.resume:
        if not os.path.exists(path):
            print(f"--resume given but there is no checkpoint at {path}", file=sys.stderr)
            return 2
        try:
            with open(path, "rb") as f:
                state = decode(f.read())
        except (OSError, ValueError) as e:
            print(f"damaged checkpoint {path}: {e}", file=sys.stderr)
            return 2
        i, digest = int(state["iteration"]), state["digest"]
        say({"event": "resumed", "iterations": i, "target_iterations": target})
    else:
        if os.path.exists(path):
            print(f"a checkpoint exists at {path} but --resume was not given", file=sys.stderr)
            return 2
        i, digest = 0, start_digest()
        say({"event": "started", "iterations": 0, "target_iterations": target})

    last_save = time.monotonic()
    while i < target:
        if not args.resume and cfg["crash_at"] is not None and i == int(cfg["crash_at"]):
            print(f"crashing at iteration {i} (crash_at)", file=sys.stderr, flush=True)
            return 3
        time.sleep(float(cfg["iteration_seconds"]))
        digest = step(digest, i)
        i += 1
        if i % int(cfg["progress_every"]) == 0:
            say({"iterations": i, "target_iterations": target})
        if cfg["stage_every"] and i % int(cfg["stage_every"]) == 0:
            stage(args.checkpoint_dir, i, int(cfg["stage_every"]), digest)
        hold = cfg["hold_file"]
        if cfg["hold_at"] is not None and i == int(cfg["hold_at"]) and hold and \
                os.path.exists(hold):
            save(path, encode(i, digest, target, int(cfg["checkpoint_bytes"])),
                 float(cfg["save_seconds"]))
            last_save = time.monotonic()
            say({"event": "holding", "iterations": i, "target_iterations": target})
            while os.path.exists(hold) and not stop["flag"]:
                time.sleep(0.01)
        if stop["flag"]:
            save(path, encode(i, digest, target, int(cfg["checkpoint_bytes"])),
                 float(cfg["save_seconds"]))
            say({"event": "saved on SIGTERM", "iterations": i, "target_iterations": target})
            return int(cfg["stop_exit_code"])
        if time.monotonic() - last_save >= float(cfg["checkpoint_seconds"]):
            save(path, encode(i, digest, target, int(cfg["checkpoint_bytes"])),
                 float(cfg["save_seconds"]))
            last_save = time.monotonic()
    save(path, encode(i, digest, target, int(cfg["checkpoint_bytes"])), 0.0)
    say({"event": "done", "iterations": i, "target_iterations": target, "digest": digest})
    return 0


if __name__ == "__main__":
    sys.exit(main())
