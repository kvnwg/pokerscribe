"""tools/cloud's local test with the leaf table job (`search --config ...`) as the trainer.

    python docs/research/runs/phase7/leaf_rehearsal.py --search engine/target/release/search \
        --strategy <strategy file> --tables ~/abstraction/k200 [--deals N] [--part-nodes K]

The real supervisor (tools/cloud/supervisor.py) runs the job with a local folder as the
bucket, as on the rented machine, with the settings of `cloud.env.example` (the checkpoint
`leaf.ckpt`; the artifacts `*.leafpart`, `*.leaf` and `*.jsonl`) and the config of
`leaf.json` (its paths under /opt/pscloud/bundle/files pointed at the local copies):

1. Machine 1 starts fresh. Once 2 parts are in the bucket, every process gets SIGTERM (as
   when Google stops a Spot machine): the job gives up the part it was building, exits 75,
   and the supervisor uploads the checkpoint and the parts.
2. Machine 2 starts with an empty disk: the supervisor puts back the checkpoint and every
   part, the job resumes with those parts done, builds the rest and writes the table file,
   and the supervisor uploads it and ends the run "done".
3. Checks: the job exited 75 on SIGTERM; machine 2 resumed with every part the bucket had;
   every part and the table file are in the bucket; the run is "done"; both sessions were
   recorded for the cost; and the table file's values are those of `search leaf` (a build on
   this computer, without the supervisor) bit for bit.

Measured: the time to stop after SIGTERM, to resume, the parts' time, the job's memory.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
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

PATTERNS = ["*.leafpart", "*.leaf", "*.jsonl"]


def values(path):
    """The values of a leaf table file (everything after its header)."""
    with open(path, "rb") as f:
        assert f.read(8) == b"PSLEAF1\n", path
        n = int.from_bytes(f.read(8), "little")
        header = json.loads(f.read(n))
        return header, f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--search", required=True, help="the search binary")
    ap.add_argument("--strategy", required=True, help="a strategy file (any blueprint)")
    ap.add_argument("--tables", required=True, help="its bucket tables")
    ap.add_argument("--deals", type=int, default=20_000)
    ap.add_argument("--part-nodes", type=int, default=16)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--keep", help="keep the run's files in this folder")
    a = ap.parse_args()
    t0 = time.time()
    root = a.keep or tempfile.mkdtemp(prefix="leaf-rehearsal-")
    os.makedirs(root, exist_ok=True)
    store_dir = os.path.join(root, "bucket", "runs", "local-test")
    store = LocalStore(store_dir)
    strategy = os.path.abspath(os.path.expanduser(a.strategy))
    tables = os.path.abspath(os.path.expanduser(a.tables)).rstrip(os.sep)
    # The config as the machine sees it, then pointed at the local copies.
    vm = "/opt/pscloud/bundle/files"
    job = {"strategy": f"{vm}/{os.path.basename(strategy)}",
           "tables": f"{vm}/{os.path.basename(tables)}",
           "deals": a.deals, "seed": 7, "part_nodes": a.part_nodes}
    machine_cfg = os.path.join(root, "leaf.json")
    with open(machine_cfg, "w") as f:
        json.dump(job, f)
    config, changed = local_config(machine_cfg, [strategy, tables],
                                   os.path.join(root, "config", "leaf.json"))
    for c in changed:
        print(f"config: {c}")
    over = dict(trainer=[os.path.abspath(a.search)], trainer_args=["--threads", str(a.threads)],
                artifact_patterns=PATTERNS, machine_type="local", status_seconds=2.0,
                control_seconds=1.0, settle_seconds=1.0, scan_seconds=0.5,
                stop_grace_seconds=120.0, final_upload_seconds=600.0)
    out = {}

    def parts_in_bucket():
        return sorted(n[len(ARTIFACTS):] for n, _ in store.list(ARTIFACTS)
                      if n.endswith(".leafpart"))

    print("machine 1: fresh start")
    m1 = os.path.join(root, "machine-1")
    p1 = start_supervisor(run_config(root, "machine-1", store_dir, config, **over),
                          os.path.join(root, "machine-1.supervisor.out"))
    try:
        started = wait_for(lambda: [e for e in trainer_events(m1) if e.get("event") == "started"],
                           600, "the job to start", poll=0.5)[0]
        parts = int(started["parts"])
        assert parts >= 4, f"{parts} parts: too few for the rehearsal (lower --part-nodes)"
        print(f"machine 1: {parts} parts of {a.part_nodes} turn starts, {a.deals:,} deals")
        wait_for(lambda: len(parts_in_bucket()) >= 2, 3600, "2 parts in the bucket", poll=0.5)
    except BaseException:
        os.killpg(p1.pid, signal.SIGKILL)
        raise
    print(f"machine 1: {len(parts_in_bucket())} part(s) in the bucket; SIGTERM to every "
          f"process (Google stops the machine)")
    sig_at = time.time()
    os.killpg(p1.pid, signal.SIGTERM)
    assert p1.wait(timeout=600) == 0
    out["stop_seconds"] = round(time.time() - sig_at, 1)
    assert read_json(store, STATE) is None, "a stopped machine must not end the run"
    st1 = read_json(store, STATUS)
    assert st1["stop_reason"] == "shutdown", st1["stop_reason"]
    assert (st1["trainer"] or {}).get("exit_code") == 75, st1["trainer"]
    saved = [e for e in trainer_events(m1) if e.get("event") == "saved on SIGTERM"]
    assert saved, "the job did not stop on SIGTERM"
    in_bucket = parts_in_bucket()
    assert remote_checkpoints(store), "no checkpoint in the bucket"
    print(f"machine 1: the job exited 75, {out['stop_seconds']} s after SIGTERM, with "
          f"{saved[-1]['parts_done']} part(s) done; {len(in_bucket)} in the bucket")

    print("machine 2: new machine, empty disk")
    m2 = os.path.join(root, "machine-2")
    t2 = time.time()
    p2 = start_supervisor(run_config(root, "machine-2", store_dir, config, **over),
                          os.path.join(root, "machine-2.supervisor.out"))
    try:
        resumed = wait_for(lambda: [e for e in trainer_events(m2) if e.get("event") == "resumed"],
                           600, "the job to resume", poll=0.5)[0]
        out["resume_seconds"] = round(time.time() - t2, 1)
        assert resumed["parts_done"] == len(in_bucket), (resumed, in_bucket)
        print(f"machine 2: checkpoint and {len(in_bucket)} part(s) put back; the job resumed "
              f"with them done after {out['resume_seconds']} s")
        assert p2.wait(timeout=7200) == 0
    except BaseException:
        os.killpg(p2.pid, signal.SIGKILL)
        raise
    state = read_json(store, STATE)
    assert state and state["state"] == "done", state
    events = trainer_events(m2)
    done = [e for e in events if e.get("event") == "done"]
    assert done, "the job did not finish"
    leaf_name = os.path.basename(strategy) + ".leaf"
    names = sorted(n[len(ARTIFACTS):] for n, _ in store.list(ARTIFACTS))
    assert leaf_name in names, names
    assert len([n for n in names if n.endswith(".leafpart")]) == parts, names
    assert len(store.list(SESSIONS)) == 2, "both sessions recorded"
    st2 = read_json(store, STATUS)
    part_seconds = [e["part_seconds"] for e in trainer_events(m1) + events if "part_seconds" in e]
    rates = [e["node_deals_per_second"] for e in trainer_events(m1) + events
             if "node_deals_per_second" in e]
    peaks = [(m or {}).get("session_trainer_peak_bytes") for m in (st1.get("memory"),
                                                                   st2.get("memory"))]
    out.update(parts=parts, part_seconds=part_seconds, node_deals_per_second=rates,
               trainer_peak_bytes=max([p for p in peaks if p] or [0]) or None,
               cost=st2.get("cost"))
    print(f"machine 2: done; the table file and all {parts} parts are in the bucket; state done")

    # The same tables built on this computer, without the supervisor.
    local = os.path.join(root, "local")
    os.makedirs(local, exist_ok=True)
    copy = os.path.join(local, os.path.basename(strategy))
    shutil.copy(strategy, copy)
    r = subprocess.run([os.path.abspath(a.search), "leaf", "--strategy", copy, "--tables", tables,
                        "--deals", str(a.deals), "--seed", "7", "--part-nodes",
                        str(a.part_nodes), "--threads", str(a.threads)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    h1, v1 = values(store.url(ARTIFACTS + leaf_name))
    h2, v2 = values(copy + ".leaf")
    assert v1 == v2, "the cloud job's tables differ from search leaf's"
    assert h1["strategy_hash"] == h2["strategy_hash"] and h1["nodes"] == h2["nodes"]
    print(f"the table file's values are search leaf's, bit for bit ({len(v1):,} bytes)")
    if out["trainer_peak_bytes"]:
        print(f"job memory: peak {out['trainer_peak_bytes'] / 1e9:.2f} GB")
    out["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(out))
    print("all checks passed")
    if not a.keep:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
