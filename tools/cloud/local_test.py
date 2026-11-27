"""A whole run on this computer, with no cloud and no cost: `python -m tools.cloud local-test`.

The real supervisor runs the fake trainer, with a local folder standing in for the bucket:

1. Machine 1 starts from nothing and trains. Halfway through, every process on it gets
   SIGTERM at once, as systemd does when Google stops a Spot machine. The trainer saves; the
   supervisor uploads that checkpoint and exits, leaving the run open (not a final state).
2. Machine 2 starts with an empty disk, as a new machine would. Its supervisor downloads the
   newest checkpoint from the bucket and starts the trainer with --resume. The run finishes.
3. Checks: the second trainer resumed where the first one saved, the final hash equals that
   of a run that never stopped, the bucket keeps exactly the last 3 checkpoints, both
   sessions were recorded for the cost, the run's state is "done", and the power-off command
   ran.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time

from . import fake_trainer
from .supervisor import (CHECKPOINTS, SESSIONS, STATE, STATUS, LocalStore, read_json,
                         remote_checkpoints)

HERE = os.path.dirname(os.path.abspath(__file__))
SUPERVISOR = os.path.join(HERE, "supervisor.py")
FAKE = os.path.join(HERE, "fake_trainer.py")


def run_config(root: str, machine: str, store_dir: str, fake_cfg: str, **over) -> str:
    """Write a run.json for one simulated machine and return its path."""
    mdir = os.path.join(root, machine)
    os.makedirs(mdir, exist_ok=True)
    cfg = {
        "run": "local-test",
        "store": store_dir,
        "trainer": [sys.executable, FAKE],
        "config": fake_cfg,
        "checkpoint_dir": os.path.join(mdir, "checkpoints"),
        "work_dir": mdir,
        "checkpoint_pattern": "*.ckpt",
        "keep_checkpoints": 3,
        "settle_seconds": 0.2,
        "scan_seconds": 0.1,
        "status_seconds": 0.3,
        "control_seconds": 0.3,
        "budget_usd": 100.0,
        "machine_per_hour": 2.0461,
        "ip_per_hour": 0.005,
        "disk_per_hour": 0.02,
        "crash_backoff_seconds": 0.2,
        "stop_grace_seconds": 30.0,
        "final_upload_seconds": 30.0,
        "power_off": [sys.executable, "-c",
                      "import sys; open(sys.argv[1], 'a').write('off\\n')",
                      os.path.join(mdir, "powered-off")],
        "instance": machine,
        "zone": "local",
        "machine_type": "fake",
        "provisioning": "SPOT",
    }
    cfg.update(over)
    path = os.path.join(mdir, "run.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)
    return path


def start_supervisor(run_json: str, log_path: str) -> subprocess.Popen:
    log = open(log_path, "ab")
    # A session of its own, so one killpg reaches the supervisor and the trainer together,
    # like systemd's control-group kill.
    return subprocess.Popen([sys.executable, SUPERVISOR, "--run-config", run_json],
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


def wait_for(cond, timeout: float, what: str, poll: float = 0.05):
    end = time.time() + timeout
    while time.time() < end:
        v = cond()
        if v:
            return v
        time.sleep(poll)
    raise TimeoutError(f"timed out waiting for {what}")


def trainer_events(machine_dir: str) -> list[dict]:
    events = []
    logs = os.path.join(machine_dir, "logs")
    for fn in sorted(os.listdir(logs)) if os.path.isdir(logs) else []:
        if fn.startswith("trainer-"):
            with open(os.path.join(logs, fn), encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            events.append(json.loads(line))
                        except ValueError:
                            pass
    return events


def checkpoint_iteration(store: LocalStore, obj: str) -> int:
    with open(store.url(obj), "rb") as f:
        return int(fake_trainer.decode(f.read())["iteration"])


def run(root: str, iterations: int = 400, say=print) -> dict:
    """Run the scenario in ``root`` and return what was checked. Raises AssertionError if a
    check fails."""
    store_dir = os.path.join(root, "bucket", "runs", "local-test")
    store = LocalStore(store_dir)
    fake_cfg = os.path.join(root, "fake.json")
    with open(fake_cfg, "w", encoding="utf-8") as f:
        json.dump({"iterations": iterations, "iteration_seconds": 0.01,
                   "checkpoint_seconds": 0.3, "checkpoint_bytes": 64 * 1024,
                   "save_seconds": 0.05}, f)
    half = iterations // 2
    out = {}

    say("machine 1: fresh start")
    m1 = os.path.join(root, "machine-1")
    p1 = start_supervisor(run_config(root, "machine-1", store_dir, fake_cfg),
                          os.path.join(root, "machine-1.supervisor.out"))

    def halfway():
        st = read_json(store, STATUS)
        it = st and st["progress"].get("iterations")
        return it is not None and it >= half and remote_checkpoints(store)

    wait_for(halfway, 60, "machine 1 to get halfway with a checkpoint in the bucket")
    say(f"machine 1: at iteration {read_json(store, STATUS)['progress']['iterations']}, "
        f"sending SIGTERM to every process (Google stops the machine)")
    os.killpg(p1.pid, signal.SIGTERM)
    rc1 = p1.wait(timeout=60)
    assert rc1 == 0, f"supervisor 1 exited with {rc1}"
    assert read_json(store, STATE) is None, "a stopped machine must not end the run"
    st1 = read_json(store, STATUS)
    assert st1["stop_reason"] == "shutdown", st1["stop_reason"]
    saved = [e for e in trainer_events(m1) if e.get("event") == "saved on SIGTERM"]
    assert saved, "trainer 1 did not save on SIGTERM"
    saved_at = int(saved[-1]["iterations"])
    remote = remote_checkpoints(store)
    newest = max(remote, key=lambda c: c.seq)
    in_bucket = checkpoint_iteration(store, newest.object)
    assert in_bucket == saved_at, (
        f"the bucket's newest checkpoint is at iteration {in_bucket}, the SIGTERM save at "
        f"{saved_at}: the last save was not uploaded")
    assert 1 <= len(remote) <= 3, f"{len(remote)} checkpoints in the bucket"
    assert not os.path.exists(os.path.join(m1, "powered-off")), \
        "machine 1 powered itself off on a plain shutdown"
    say(f"machine 1: trainer saved at iteration {saved_at}, uploaded as {newest.object}; "
        f"{len(remote)} checkpoint(s) in the bucket")
    out["stopped_at"] = saved_at

    say("machine 2: new machine, empty disk")
    m2 = os.path.join(root, "machine-2")
    p2 = start_supervisor(run_config(root, "machine-2", store_dir, fake_cfg),
                          os.path.join(root, "machine-2.supervisor.out"))
    rc2 = p2.wait(timeout=120)
    assert rc2 == 0, f"supervisor 2 exited with {rc2}"
    events = trainer_events(m2)
    resumed = [e for e in events if e.get("event") == "resumed"]
    assert resumed, "trainer 2 did not resume (it started fresh)"
    assert int(resumed[0]["iterations"]) == saved_at, (
        f"trainer 2 resumed at {resumed[0]['iterations']}, not at {saved_at}")
    done = [e for e in events if e.get("event") == "done"]
    assert done, "trainer 2 did not finish"
    want = fake_trainer.expected_digest(iterations)
    assert done[-1]["digest"] == want, "the resumed run did different work from an " \
                                       "uninterrupted one"
    state = read_json(store, STATE)
    assert state and state["state"] == "done", state
    remote = remote_checkpoints(store)
    assert len(remote) == 3, f"{len(remote)} checkpoints kept, not 3"
    assert checkpoint_iteration(store, max(remote, key=lambda c: c.seq).object) == iterations
    sessions = store.list(SESSIONS)
    assert len(sessions) == 2, f"{len(sessions)} sessions recorded"
    assert os.path.exists(os.path.join(m2, "powered-off")), "machine 2 did not power off"
    st2 = read_json(store, STATUS)
    say(f"machine 2: resumed at iteration {saved_at}, finished at {iterations}; the hash "
        f"matches an uninterrupted run")
    say(f"bucket: {len(remote)} checkpoints kept "
        f"({', '.join(c.object[len(CHECKPOINTS):] for c in remote)})")
    say(f"cost recorded over {st2['cost']['sessions']} sessions: "
        f"${st2['cost']['total_usd']:.6f} (seconds at Spot prices)")
    say("state: done; machine 2 powered off")
    out.update(resumed_at=int(resumed[0]["iterations"]), digest=done[-1]["digest"],
               kept=[c.object for c in remote], sessions=len(sessions), state=state["state"],
               cost=st2["cost"])
    return out


def main(keep: str | None = None) -> int:
    if keep:
        os.makedirs(keep, exist_ok=True)
        root = keep
        run(root)
        print(f"files kept in {root}")
        return 0
    with tempfile.TemporaryDirectory(prefix="pscloud-local-test-") as root:
        run(root)
    print("local test passed")
    return 0
