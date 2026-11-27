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
