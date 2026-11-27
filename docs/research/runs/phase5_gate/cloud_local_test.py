"""tools/cloud's local test with the real blueprint trainer in place of the fake one.

    python docs/research/runs/phase5_gate/cloud_local_test.py \
        --trainer engine/target/release/blueprint --tables ~/abstraction/k10

The real supervisor (tools/cloud/supervisor.py) runs `blueprint --config ... --checkpoint-dir
... [--resume]` with a local folder as the bucket. Machine 1 starts fresh; once a checkpoint
is in the bucket, every process gets SIGTERM (as when Google stops a Spot machine). Machine 2
starts with an empty disk, downloads the newest checkpoint and resumes; the run finishes.
Checks: the trainer saved on SIGTERM and exited with 75, that save was uploaded, machine 2
resumed at exactly that iteration and finished, and the run's state is "done".
"""
import argparse
import json
import os
import signal
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))
sys.path.insert(0, ROOT)

from tools.cloud.local_test import run_config, start_supervisor, trainer_events, wait_for  # noqa: E402
from tools.cloud.supervisor import STATE, STATUS, LocalStore, read_json, remote_checkpoints  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trainer", required=True)
    ap.add_argument("--tables", required=True)
    ap.add_argument("--until", type=int, default=20_000_000)
    ap.add_argument("--keep", help="keep the run's files in this folder")
    a = ap.parse_args()
    root = a.keep or tempfile.mkdtemp(prefix="blueprint-cloud-")
    os.makedirs(root, exist_ok=True)
    store_dir = os.path.join(root, "bucket", "runs", "local-test")
    store = LocalStore(store_dir)
    config = os.path.join(root, "trainer.json")
    spec = {"stack_bb": 10, "menu": "minimal", "abstraction": os.path.expanduser(a.tables),
            "training": {"seed": 1, "threads": 2, "compact_scale": 100.0, "regret_floor": -3.1e6,
                         "linear": None, "pruning": None}}
    with open(config, "w") as f:
        json.dump({"spec": spec, "until": a.until, "every_minutes": 0.05}, f)
    trainer = [os.path.abspath(a.trainer)]
    over = dict(trainer=trainer, machine_type="local", stop_grace_seconds=60.0)

    print("machine 1: fresh start")
    p1 = start_supervisor(run_config(root, "machine-1", store_dir, config, **over),
                          os.path.join(root, "machine-1.supervisor.out"))

    def checkpoint_and_progress():
        st = read_json(store, STATUS)
        it = st and st["progress"].get("iterations")
        return it and it >= 2_000_000 and remote_checkpoints(store)

    wait_for(checkpoint_and_progress, 300, "machine 1 to save and upload a checkpoint", poll=0.5)
    print(f"machine 1: at iteration {read_json(store, STATUS)['progress']['iterations']}, SIGTERM to every process")
    os.killpg(p1.pid, signal.SIGTERM)
    assert p1.wait(timeout=120) == 0
    assert read_json(store, STATE) is None, "a stopped machine must not end the run"
    m1 = os.path.join(root, "machine-1")
    saved = [e for e in trainer_events(m1) if e.get("event") == "saved on SIGTERM"]
    assert saved, "trainer 1 did not save on SIGTERM"
    saved_at = int(saved[-1]["iterations"])
    print(f"machine 1: trainer saved at iteration {saved_at}; {len(remote_checkpoints(store))} checkpoint(s) in the bucket")

    print("machine 2: new machine, empty disk")
    p2 = start_supervisor(run_config(root, "machine-2", store_dir, config, **over),
                          os.path.join(root, "machine-2.supervisor.out"))
    assert p2.wait(timeout=1800) == 0
    events = trainer_events(os.path.join(root, "machine-2"))
    resumed = [e for e in events if e.get("event") == "resumed"]
    assert resumed and int(resumed[0]["iterations"]) == saved_at, resumed
    done = [e for e in events if e.get("event") == "done"]
    assert done and done[-1]["iterations"] == a.until, done
    state = read_json(store, STATE)
    assert state and state["state"] == "done", state
    st = read_json(store, STATUS)
    print(f"machine 2: resumed at iteration {saved_at}, finished at {a.until}; state {state['state']}")
    print(f"trainer memory at the last report: {st.get('memory')}")
    print("all checks passed")


if __name__ == "__main__":
    t = time.time()
    main()
    print(f"{time.time() - t:.0f} s")
