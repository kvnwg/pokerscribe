"""tools/cloud's local test with the Phase 7 plan job (`search --config phase7.json ...`) as
the trainer, on a small blueprint and with the plan's sizes cut down.

    python docs/research/runs/phase7/plan_rehearsal.py --search engine/target/release/search \
        --strategy <strategy file> --tables ~/abstraction/k200 [--keep DIR]

The real supervisor (tools/cloud/supervisor.py) runs the job with a local folder as the
bucket, as on the rented machine, with the settings of `cloud.env.example` (the checkpoint
`plan.ckpt`; the artifacts `*.leafpart`, `*.json`, `*.deals` and `*.jsonl`) and the plan of
`phase7.json` (its paths under /opt/pscloud/bundle/files pointed at the local copies, and the
sizes below):

1. Machine 1 starts fresh. Once the gate's first chunk is in the bucket, every process gets
   SIGTERM (as when Google stops a Spot machine): the job gives up the chunk it is playing,
   exits 75 at once, and the supervisor uploads the checkpoint and the results.
2. Machine 2 starts with an empty disk: the supervisor puts back the checkpoint, the leaf
   table parts and every result. The job resumes, puts the table file together from the
   parts (no part is built again), skips the results there, plays the rest, and the run
   ends "done".
3. Checks: exit 75 within seconds of SIGTERM; machine 2 built no part and did not play the
   bench, the pilot or the first chunk again; every result is in the bucket, `end.json` says
   every step was played; the table file is not in the bucket; both sessions were recorded.
"""
import argparse
import json
import os
import shutil
import signal
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, ROOT)

from tools.cloud.local_test import (local_config, run_config, start_supervisor,  # noqa: E402
                                    trainer_events, wait_for)
from tools.cloud.supervisor import (ARTIFACTS, SESSIONS, STATE, STATUS, LocalStore,  # noqa: E402
                                    read_json, remote_checkpoints)

PATTERNS = ["*.leafpart", "*.json", "*.deals", "*.jsonl"]

# The plan's sizes for the rehearsal; every other setting is phase7.json's.
SMALL = {
    "leaf": {"deals": 20000, "part_nodes": 2},
    "agent": {"flop_iterations": 40, "turn_iterations": 16, "river_iterations": 60},
    "bench": {"hands": 4},
    "pilot": {"deals": 32},
    "size": {"step": 32, "min": 64, "max": 64},
    "gate": {"chunk": 32},
    "variants": {"chunks": 1, "agent": {"flop_iterations": 40, "turn_iterations": 16,
                                        "river_iterations": 60}},
    "lbr": {"hands": 8, "chunks": 1},
}


def small_plan():
    with open(os.path.join(HERE, "phase7.json"), encoding="utf-8") as f:
        plan = json.load(f)
    for key, over in SMALL.items():
        if key == "variants":
            for v in plan["variants"]:
                v["chunks"] = over["chunks"]
                v["agent"].update(over["agent"])
        else:
            plan[key].update(over)
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--search", required=True, help="the search binary")
    ap.add_argument("--strategy", required=True, help="a strategy file (any blueprint)")
    ap.add_argument("--tables", required=True, help="its bucket tables")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--keep", help="keep the run's files in this folder")
    a = ap.parse_args()
    t0 = time.time()
    root = a.keep or tempfile.mkdtemp(prefix="plan-rehearsal-")
    os.makedirs(root, exist_ok=True)
    store_dir = os.path.join(root, "bucket", "runs", "local-test")
    store = LocalStore(store_dir)
    strategy = os.path.abspath(os.path.expanduser(a.strategy))
    tables = os.path.abspath(os.path.expanduser(a.tables)).rstrip(os.sep)
    vm = "/opt/pscloud/bundle/files"
    plan = small_plan()
    plan["strategy"] = f"{vm}/{os.path.basename(strategy)}"
    plan["tables"] = f"{vm}/{os.path.basename(tables)}"
    machine_cfg = os.path.join(root, "phase7.json")
    with open(machine_cfg, "w") as f:
        json.dump(plan, f)
    config, changed = local_config(machine_cfg, [strategy, tables],
                                   os.path.join(root, "config", "phase7.json"))
    for c in changed:
        print(f"config: {c}")
    over = dict(trainer=[os.path.abspath(a.search)], trainer_args=["--threads", str(a.threads)],
                artifact_patterns=PATTERNS, machine_type="local", status_seconds=2.0,
                control_seconds=1.0, settle_seconds=1.0, scan_seconds=0.5,
                stop_grace_seconds=120.0, final_upload_seconds=600.0)
    out = {}

    def in_bucket():
        return sorted(n[len(ARTIFACTS):] for n, _ in store.list(ARTIFACTS))

    print("machine 1: fresh start")
    m1 = os.path.join(root, "machine-1")
    p1 = start_supervisor(run_config(root, "machine-1", store_dir, config, **over),
                          os.path.join(root, "machine-1.supervisor.out"))
    try:
        wait_for(lambda: "match-01.json" in in_bucket(), 3600, "the first gate chunk", poll=0.5)
    except BaseException:
        os.killpg(p1.pid, signal.SIGKILL)
        raise
    print(f"machine 1: {len(in_bucket())} result(s) in the bucket; SIGTERM to every process "
          f"(Google stops the machine)")
    sig_at = time.time()
    os.killpg(p1.pid, signal.SIGTERM)
    assert p1.wait(timeout=600) == 0
    out["supervisor_stop_seconds"] = round(time.time() - sig_at, 1)
    assert read_json(store, STATE) is None, "a stopped machine must not end the run"
    st1 = read_json(store, STATUS)
    assert st1["stop_reason"] == "shutdown", st1["stop_reason"]
    assert (st1["trainer"] or {}).get("exit_code") == 75, st1["trainer"]
    saved = [e for e in trainer_events(m1) if e.get("event") == "saved on SIGTERM"]
    assert saved, "the job did not stop on SIGTERM"
    assert remote_checkpoints(store), "no checkpoint in the bucket"
    before = in_bucket()
    parts = [n for n in before if n.endswith(".leafpart")]
    with open(store.url(ARTIFACTS + "match-01.json"), "rb") as f:
        first_chunk = f.read()
    print(f"machine 1: the job exited 75 at step {saved[-1].get('step')}; the supervisor was "
          f"done {out['supervisor_stop_seconds']} s after SIGTERM; {len(parts)} parts and "
          f"{len(before) - len(parts)} other results in the bucket")

    print("machine 2: new machine, empty disk")
    m2 = os.path.join(root, "machine-2")
    t2 = time.time()
    p2 = start_supervisor(run_config(root, "machine-2", store_dir, config, **over),
                          os.path.join(root, "machine-2.supervisor.out"))
    try:
        wait_for(lambda: [e for e in trainer_events(m2) if e.get("event") == "resumed"],
                 600, "the job to resume", poll=0.5)
        out["resume_seconds"] = round(time.time() - t2, 1)
        assert p2.wait(timeout=7200) == 0
    except BaseException:
        os.killpg(p2.pid, signal.SIGKILL)
        raise
    state = read_json(store, STATE)
    assert state and state["state"] == "done", state
    events = trainer_events(m2)
    assert not [e for e in events if "part_seconds" in e], "machine 2 built a part again"
    assert not [e for e in events if e.get("event") == "bench"], "the bench was played again"
    done = [e for e in events if e.get("event") == "done" and "end" in e]
    assert done and done[-1]["end"] == "every step is played", done
    names = in_bucket()
    for f in ["bench.json", "bounds.json", "pilot.json", "size.json", "match-01.json",
              "match-02.json", "gate.json", "variant-modicum.json", "variant-final.json",
              "lbr-search-fcpa14-1.json", "lbr-blueprint-b56_14-1.deals",
              "compare-b56_14-1.json", "end.json"]:
        assert f in names, (f, names)
    assert not [n for n in names if n.endswith(".leaf")], "the table file is not an artifact"
    with open(store.url(ARTIFACTS + "match-01.json"), "rb") as f:
        assert f.read() == first_chunk, "the first chunk was played again"
    assert len(store.list(SESSIONS)) == 2, "both sessions recorded"
    st2 = read_json(store, STATUS)
    peaks = [(m or {}).get("session_trainer_peak_bytes") for m in (st1.get("memory"),
                                                                   st2.get("memory"))]
    with open(store.url(ARTIFACTS + "gate.json"), encoding="utf-8") as f:
        gate = json.load(f)
    out.update(parts=len(parts), results=len(names), gate_z=gate["z"],
               trainer_peak_bytes=max([p for p in peaks if p] or [0]) or None,
               cost=st2.get("cost"), seconds=round(time.time() - t0, 1))
    print(f"machine 2: resumed after {out['resume_seconds']} s, built no part, played the "
          f"rest; {len(names)} results in the bucket; state done")
    print(json.dumps(out))
    print("all checks passed")
    if not a.keep:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
