"""The supervisor with the fake trainer, a local folder as the bucket: crashes, the budget cap,
stop requests, the Spot preemption notice, which checkpoint a start resumes from, and uploads
that are never torn. Also the fake trainer's own contract."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest

from tools.cloud import fake_trainer, local_test
from tools.cloud import supervisor as sup
from tools.cloud.supervisor import (LocalStore, STATE, STATUS, STOP_MARKER, read_json,
                                    remote_checkpoints, write_json)

FAKE = local_test.FAKE


def fake_config(tmp_path, **over):
    cfg = {"iterations": 300, "iteration_seconds": 0.01, "checkpoint_seconds": 0.2,
           "checkpoint_bytes": 8192}
    cfg.update(over)
    path = tmp_path / f"fake-{len(list(tmp_path.glob('fake-*.json')))}.json"
    path.write_text(json.dumps(cfg))
    return str(path)


def make_run(tmp_path, machine="m1", fake=None, **over):
    store_dir = str(tmp_path / "bucket" / "runs" / "r")
    fake = fake or fake_config(tmp_path)
    run_json = local_test.run_config(str(tmp_path), machine, store_dir, fake, **over)
    return run_json, LocalStore(store_dir), tmp_path / machine


def run_supervisor(run_json, timeout=90):
    p = subprocess.run([sys.executable, local_test.SUPERVISOR, "--run-config", run_json],
                       capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stderr


def events(mdir):
    return local_test.trainer_events(str(mdir))


def ckpt_iteration(path):
    with open(path, "rb") as f:
        return fake_trainer.decode(f.read())["iteration"]


# --- the fake trainer ----------------------------------------------------------------------------

def test_fake_trainer_contract(tmp_path):
    cfg = fake_config(tmp_path, iterations=40, iteration_seconds=0.001)
    ck = tmp_path / "ck"

    def run(*extra):
        return subprocess.run([sys.executable, FAKE, "--config", cfg, "--checkpoint-dir",
                               str(ck), *extra], capture_output=True, text=True, timeout=60)

    assert run("--resume").returncode == 2                     # nothing to resume
    p = run()
    assert p.returncode == 0
    done = json.loads(p.stdout.strip().splitlines()[-1])
    assert done["digest"] == fake_trainer.expected_digest(40)
    assert run().returncode == 2                               # a checkpoint, no --resume
    assert run("--resume").returncode == 0                     # already done
    (ck / "fake.ckpt").write_bytes(b"PSFAKE1\n{}\nbad\n")
    assert run("--resume").returncode == 2                     # damaged
    with pytest.raises(ValueError):
        fake_trainer.decode(b"nope")


def test_fake_trainer_saves_on_sigterm(tmp_path):
    cfg = fake_config(tmp_path, iterations=100000, checkpoint_seconds=1000)
    ck = tmp_path / "ck"
    p = subprocess.Popen([sys.executable, FAKE, "--config", cfg, "--checkpoint-dir", str(ck)],
                         stdout=subprocess.PIPE, text=True)
    time.sleep(0.5)
    p.terminate()
    out, _ = p.communicate(timeout=30)
    assert p.returncode == 75
    saved = [json.loads(x) for x in out.splitlines() if "saved on SIGTERM" in x]
    assert saved and ckpt_iteration(ck / "fake.ckpt") == saved[0]["iterations"] > 0


def test_fake_trainer_holds_until_sigterm(tmp_path):
    # While the hold file exists the trainer waits at hold_at, with a checkpoint saved there,
    # until SIGTERM. Resumed from there, or started without the file, it never holds.
    hold = tmp_path / "hold"
    hold.write_text("")
    cfg = fake_config(tmp_path, iterations=40, iteration_seconds=0.001, checkpoint_seconds=1000,
                      hold_at=20, hold_file=str(hold))
    ck = tmp_path / "ck"
    p = subprocess.Popen([sys.executable, FAKE, "--config", cfg, "--checkpoint-dir", str(ck)],
                         stdout=subprocess.PIPE, text=True)
    holding = None
    for line in p.stdout:
        if '"holding"' in line:
            holding = json.loads(line)
            break
    assert holding and holding["iterations"] == 20
    assert ckpt_iteration(ck / "fake.ckpt") == 20
    time.sleep(0.3)
    assert p.poll() is None                                    # still waiting
    p.terminate()
    out, _ = p.communicate(timeout=30)
    assert p.returncode == 75
    saved = [json.loads(x) for x in out.splitlines() if "saved on SIGTERM" in x]
    assert [s["iterations"] for s in saved] == [20] and ckpt_iteration(ck / "fake.ckpt") == 20

    def run(ckdir, *extra):
        return subprocess.run([sys.executable, FAKE, "--config", cfg, "--checkpoint-dir",
                               str(ckdir), *extra], capture_output=True, text=True, timeout=60)

    r = run(ck, "--resume")                                    # the file is still there
    assert r.returncode == 0 and '"holding"' not in r.stdout
    assert json.loads(r.stdout.strip().splitlines()[-1])["digest"] == \
        fake_trainer.expected_digest(40)
    hold.unlink()
    r = run(tmp_path / "ck2")                                  # fresh, no file: no hold
    assert r.returncode == 0 and '"holding"' not in r.stdout


# --- crashes -------------------------------------------------------------------------------------

def test_crash_is_restarted_with_resume(tmp_path):
    fake = fake_config(tmp_path, crash_at=100, checkpoint_seconds=0.1)
    run_json, store, mdir = make_run(tmp_path, fake=fake)
    rc, err = run_supervisor(run_json)
    assert rc == 0, err
    assert read_json(store, STATE)["state"] == "done"
    ev = events(mdir)
    assert [e["event"] for e in ev if e.get("event") in ("started", "resumed", "done")] == \
        ["started", "resumed", "done"]
    st = read_json(store, STATUS)
    assert st["trainer"]["crashes"] == 1 and st["trainer"]["runs"] == 2
    assert [e for e in ev if e.get("event") == "done"][0]["digest"] == \
        fake_trainer.expected_digest(300)


def test_repeated_crashes_end_the_run(tmp_path):
    fake = fake_config(tmp_path, crash_at=0)                   # before any checkpoint
    run_json, store, mdir = make_run(tmp_path, fake=fake, max_trainer_crashes=2)
    rc, err = run_supervisor(run_json)
    assert rc == 0, err
    state = read_json(store, STATE)
    assert state["state"] == "failed" and "crashed 3 times" in state["detail"]
    assert (mdir / "powered-off").exists()
    assert read_json(store, STATUS)["trainer"]["runs"] == 3


def test_a_missing_trainer_counts_as_a_crash(tmp_path):
    run_json, store, mdir = make_run(tmp_path, trainer=[str(tmp_path / "no-such-trainer")],
                                  max_trainer_crashes=0)
    rc, err = run_supervisor(run_json)
    assert rc == 0, err
    assert read_json(store, STATE)["state"] == "failed"


# --- the budget ----------------------------------------------------------------------------------

def test_budget_cap_stops_the_trainer(tmp_path):
    # $10 a second, $25 cap, no margin: the cap is reached after about 2.5 seconds.
    fake = fake_config(tmp_path, iterations=10**6)
    run_json, store, mdir = make_run(tmp_path, fake=fake, machine_per_hour=36000.0, ip_per_hour=0,
                                  disk_per_hour=0, budget_usd=25.0, budget_margin_seconds=0)
    t0 = time.time()
    rc, err = run_supervisor(run_json)
    assert rc == 0, err
    assert time.time() - t0 < 30
    state = read_json(store, STATE)
    assert state["state"] == "budget", state
    saved = [e for e in events(mdir) if e.get("event") == "saved on SIGTERM"]
    assert saved, "the trainer was not asked to save"
    newest = remote_checkpoints(store)[-1]
    assert ckpt_iteration(store.url(newest.object)) == saved[-1]["iterations"]
    assert (mdir / "powered-off").exists()
    cost = read_json(store, STATUS)["cost"]
    assert cost["total_usd"] >= 25.0 and cost["budget_usd"] == 25.0


def test_budget_spent_before_the_trainer_starts(tmp_path):
    run_json, store, mdir = make_run(tmp_path, budget_usd=5.0)
    write_json(store, "sessions/old.json", {"session": "old", "started_at": 0.0,
                                            "last_seen_at": 3 * 3600.0, "machine_per_hour": 2.0})
    rc, err = run_supervisor(run_json)
    assert rc == 0, err
    assert read_json(store, STATE)["state"] == "budget"
    assert events(mdir) == []                                  # never started
    assert (mdir / "powered-off").exists()


# --- stop requests -------------------------------------------------------------------------------

def test_stop_marker_during_the_run(tmp_path):
    fake = fake_config(tmp_path, iterations=10**6)
    run_json, store, mdir = make_run(tmp_path, fake=fake)
    p = local_test.start_supervisor(run_json, str(tmp_path / "out"))
    local_test.wait_for(lambda: (read_json(store, STATUS) or {}).get("progress", {})
                        .get("iterations"), 30, "progress")
    write_json(store, STOP_MARKER, {"requested_at": time.time()})
    assert p.wait(timeout=60) == 0
    assert read_json(store, STATE)["state"] == "stopped"
    saved = [e for e in events(mdir) if e.get("event") == "saved on SIGTERM"]
    assert saved and ckpt_iteration(store.url(remote_checkpoints(store)[-1].object)) == \
        saved[-1]["iterations"]
    assert (mdir / "powered-off").exists()


def test_stop_marker_at_start(tmp_path):
    run_json, store, mdir = make_run(tmp_path)
    write_json(store, STOP_MARKER, {"requested_at": 1.0})
    rc, err = run_supervisor(run_json)
    assert rc == 0, err
    assert read_json(store, STATE)["state"] == "stopped" and events(mdir) == []


# --- Spot preemption with notice -----------------------------------------------------------------

class FakeMetadata:
    """The metadata server: says "preempted" once ``after`` seconds have passed."""

    def __init__(self, after: float):
        self.t0 = time.time()
        self.after = after

    def attributes(self):
        return {"pscloud-budget-usd": "55", "pscloud-machine-per-hour": "1.5"}

    def instance_info(self):
        return {"instance": "ps-hu-test", "zone": "us-central1-a", "machine_type": "c4a-highmem-64"}

    def preempted(self):
        return time.time() - self.t0 > self.after


def test_preemption_notice_saves_uploads_and_powers_off(tmp_path):
    fake = fake_config(tmp_path, iterations=10**6)
    run_json, store, mdir = make_run(tmp_path, fake=fake, instance=None)
    cfg = sup.load_run_config(run_json)
    s = sup.Supervisor(cfg, metadata=FakeMetadata(after=1.5))
    assert s.cfg["budget_usd"] == 55.0 and s.cfg["machine_per_hour"] == 1.5
    assert s.cfg["instance"] == "ps-hu-test"
    assert s.run(install_signals=False) == 0
    assert s.stop_reason == "preempted"
    assert read_json(store, STATE) is None                     # not a final state
    st = read_json(store, STATUS)
    assert st["stop_reason"] == "preempted" and st["instance"] == "ps-hu-test"
    saved = [e for e in events(mdir) if e.get("event") == "saved on SIGTERM"]
    assert saved and ckpt_iteration(store.url(remote_checkpoints(store)[-1].object)) == \
        saved[-1]["iterations"]
    assert (mdir / "powered-off").exists()


def test_sigterm_mid_run_is_not_a_final_state(tmp_path):
    fake = fake_config(tmp_path, iterations=10**6)
    run_json, store, mdir = make_run(tmp_path, fake=fake)
    cfg = sup.load_run_config(run_json)
    s = sup.Supervisor(cfg)
    threading.Timer(1.5, lambda: s.request_stop("shutdown")).start()
    assert s.run(install_signals=False) == 0
    assert read_json(store, STATE) is None
    assert read_json(store, STATUS)["stop_reason"] == "shutdown"
    assert not (mdir / "powered-off").exists()                 # the system is going down anyway


# --- which checkpoint a start resumes from -------------------------------------------------------

def put_checkpoint(path, iteration, mtime):
    data = fake_trainer.encode(iteration, fake_trainer.expected_digest(iteration), 150, 1024)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))


def test_a_newer_checkpoint_on_the_disk_wins_and_is_uploaded(tmp_path):
    # The machine was stopped after its last save but before the upload finished.
    fake = fake_config(tmp_path, iterations=150)
    run_json, store, mdir = make_run(tmp_path, fake=fake)
    old = tmp_path / "old.ckpt"
    put_checkpoint(old, 40, time.time() - 3600)
    store.put_file(sup.checkpoint_object(1, time.time() - 3600, "fake.ckpt"), str(old))
    put_checkpoint(mdir / "checkpoints" / "fake.ckpt", 100, time.time() - 60)
    rc, err = run_supervisor(run_json)
    assert rc == 0, err
    resumed = [e for e in events(mdir) if e.get("event") == "resumed"]
    assert resumed[0]["iterations"] == 100
    assert read_json(store, STATUS)["checkpoints"]["restored_from"] is None
    seqs = [c.seq for c in remote_checkpoints(store)]
    assert seqs[-1] > 1                                         # new uploads after the old one
    assert read_json(store, STATE)["state"] == "done"


def test_a_newer_checkpoint_in_the_bucket_is_downloaded(tmp_path):
    fake = fake_config(tmp_path, iterations=150)
    run_json, store, mdir = make_run(tmp_path, fake=fake)
    put_checkpoint(mdir / "checkpoints" / "fake.ckpt", 10, time.time() - 7200)
    newer = tmp_path / "newer.ckpt"
    t = time.time() - 600
    put_checkpoint(newer, 100, t)
    obj = sup.checkpoint_object(7, t, "fake.ckpt")
    store.put_file(obj, str(newer))
    rc, err = run_supervisor(run_json)
    assert rc == 0, err
    assert [e for e in events(mdir) if e.get("event") == "resumed"][0]["iterations"] == 100
    assert read_json(store, STATUS)["checkpoints"]["restored_from"] == obj
    assert remote_checkpoints(store)[-1].seq > 7               # numbering continues


def test_uploads_are_never_torn(tmp_path):
    # Saves every 50 ms, each taking 20 ms half-written: every uploaded object must be whole.
    fake = fake_config(tmp_path, iterations=200, checkpoint_seconds=0.05, save_seconds=0.02,
                       checkpoint_bytes=256 * 1024)
    run_json, store, mdir = make_run(tmp_path, fake=fake, keep_checkpoints=1000,
                                  settle_seconds=0.0)
    rc, err = run_supervisor(run_json)
    assert rc == 0, err
    objs = remote_checkpoints(store)
    assert len(objs) >= 3
    for c in objs:
        ckpt_iteration(store.url(c.object))                      # raises if torn
    assert [c.seq for c in objs] == list(range(1, len(objs) + 1))


# --- artifacts: the trainer's other results ------------------------------------------------------

def test_artifacts_are_uploaded_kept_and_put_back_on_a_new_machine(tmp_path):
    # Machine 1 writes stage files and a stages log, then Google takes it. Machine 2 starts
    # with an empty disk: the supervisor puts the stage files back before the trainer starts,
    # so the trainer finds the stage before each new one, and every stage stays in the bucket.
    # Trainer 1 holds at iteration 150 until it is stopped, so the stop always comes halfway,
    # however fast the machine (without the hold a fast one could finish first).
    hold = tmp_path / "hold"
    hold.write_text("")
    fake = fake_config(tmp_path, iterations=400, stage_every=50, checkpoint_seconds=0.2,
                       hold_at=150, hold_file=str(hold))
    over = dict(artifact_patterns=["*.bps", "*.jsonl"], keep_checkpoints=2)
    run1, store, m1 = make_run(tmp_path, "m1", fake=fake, **over)
    cfg = sup.load_run_config(run1)
    s1 = sup.Supervisor(cfg)

    def halfway():
        names = [n for n, _ in store.list(sup.ARTIFACTS)]
        return sup.ARTIFACTS + "stage-150.bps" in names and remote_checkpoints(store)

    t = threading.Thread(target=lambda: s1.run(install_signals=False))
    t.start()
    local_test.wait_for(halfway, 60, "three stages in the bucket")
    s1.request_stop("shutdown")
    t.join(60)
    assert not t.is_alive()
    hold.unlink()                                                 # machine 2 runs to the end
    assert read_json(store, STATE) is None
    saved = [e for e in events(m1) if e.get("event") == "saved on SIGTERM"]
    assert [e["iterations"] for e in saved] == [150]
    st1 = read_json(store, STATUS)["artifacts"]
    assert st1["uploads"] >= 4 and st1["upload_failures"] == 0

    run2, _, m2 = make_run(tmp_path, "m2", fake=fake, **over)
    rc, err = run_supervisor(run2)
    assert rc == 0, err
    assert read_json(store, STATE)["state"] == "done"
    st2 = read_json(store, STATUS)["artifacts"]
    assert st2["restored"] >= 4                                   # stages and the log
    names = sorted(n[len(sup.ARTIFACTS):] for n, _ in store.list(sup.ARTIFACTS))
    assert names == sorted([f"stage-{i}.bps" for i in range(50, 401, 50)] + ["stages.jsonl"])
    assert len(remote_checkpoints(store)) == 2                    # checkpoints are still pruned
    # The log in the bucket is the whole log, both machines' lines, and after the resume each
    # stage found the one before on the disk.
    log = [json.loads(x) for x in (store.get_bytes(sup.ARTIFACTS + "stages.jsonl") or b"")
           .decode().splitlines()]
    assert [x["iterations"] for x in log][-1] == 400
    assert all(x["previous_on_disk"] in (True, None) for x in log), log
    assert (m2 / "checkpoints" / "stages.jsonl").read_bytes() == \
        store.get_bytes(sup.ARTIFACTS + "stages.jsonl")


def test_artifacts_off_by_default_and_never_checkpoints(tmp_path):
    fake = fake_config(tmp_path, iterations=100, stage_every=50)
    run_json, store, mdir = make_run(tmp_path, fake=fake)
    rc, err = run_supervisor(run_json)
    assert rc == 0, err
    assert store.list(sup.ARTIFACTS) == []
    assert (mdir / "checkpoints" / "stage-100.bps").exists()
    local = sup.local_artifacts(str(mdir / "checkpoints"), ["*"], "*.ckpt")
    assert "fake.ckpt" not in [n for n, _ in local]
