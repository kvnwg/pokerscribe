"""Unit tests for tools/cloud: settings, checkpoint names and retention, the restore decision,
the cost estimate, the bucket stores (a folder, and gcloud through a fake), the gcloud
commands, the recovery decision table, the bundle, and the watch output."""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tarfile
import io
import gzip

import pytest

from tools.cloud import control, gce, settings, supervisor as sup
from tools.cloud.supervisor import (GcsStore, LocalStore, RemoteCheckpoint, checkpoint_object,
                                    parse_checkpoint_object, plan_restore, retention, run_cost)

from .helpers import FAKE_GCLOUD, make_settings


# --- settings ------------------------------------------------------------------------------------

def test_env_file_format():
    text = """
# a comment
PROJECT=my-proj
export BUCKET = "my bucket"
RUN_NAME='hu-1'
BUDGET_USD=40  # inline comment
ZONES=us-central1-a, us-central1-b
"""
    got = settings.parse_env_file(text)
    assert got == {"PROJECT": "my-proj", "BUCKET": "my bucket", "RUN_NAME": "hu-1",
                   "BUDGET_USD": "40", "ZONES": "us-central1-a, us-central1-b"}
    with pytest.raises(settings.SettingsError):
        settings.parse_env_file("no equals sign here")


def test_load_file_then_environment(tmp_path):
    f = tmp_path / "cloud.env"
    f.write_text("PROJECT=from-file\nBUCKET=b-file\nRUN_NAME=hu-1\nBUDGET_USD=12.5\n"
                 "EXTERNAL_IP=no\nZONES=us-central1-b us-central1-c\n")
    s = settings.load(str(f), environ={"PSCLOUD_PROJECT": "from-env"})
    assert s.PROJECT == "from-env" and s.BUCKET == "b-file" and s.BUDGET_USD == 12.5
    assert s.EXTERNAL_IP is False and s.ip_price == 0.0
    assert s.zones == ["us-central1-a", "us-central1-b", "us-central1-c"]
    assert s.instance_name == "ps-hu-1"
    assert s.store_url == "gs://b-file/runs/hu-1"
    assert s.source == str(f)
    # the file is found through PSCLOUD_SETTINGS too
    s2 = settings.load(None, environ={"PSCLOUD_SETTINGS": str(f)})
    assert s2.PROJECT == "from-file"


def test_unknown_and_bad_settings(tmp_path):
    f = tmp_path / "cloud.env"
    f.write_text("PROJCET=typo\n")
    with pytest.raises(settings.SettingsError, match="PROJCET"):
        settings.load(str(f), environ={})
    with pytest.raises(settings.SettingsError, match="BUDGET_USD"):
        settings.load(str(tmp_path / "none"), environ={"PSCLOUD_BUDGET_USD": "lots"})
    with pytest.raises(settings.SettingsError, match="EXTERNAL_IP"):
        settings.load(str(tmp_path / "none"), environ={"PSCLOUD_EXTERNAL_IP": "maybe"})


def test_problems_name_what_is_missing(tmp_path):
    s = settings.load(str(tmp_path / "none"), environ={})
    probs = " | ".join(s.problems())
    for needed in ("PROJECT", "BUCKET", "RUN_NAME", "SPOT_PRICE_PER_HOUR", "BUDGET_USD",
                   "TRAINER_CARGO_BIN", "TRAINER_CONFIG"):
        assert needed in probs
    ok = make_settings(tmp_path)
    assert ok.problems() == []
    assert any("arm64" in p for p in make_settings(tmp_path, IMAGE_FAMILY="debian-12").problems())
    assert any("Persistent Disk" in p
               for p in make_settings(tmp_path, DISK_TYPE="pd-balanced").problems())
    assert any("not in REGION" in p
               for p in make_settings(tmp_path, ZONES="europe-west4-a").problems())
    assert any("gs://" in p for p in make_settings(tmp_path, BUCKET="gs://x").problems())
    assert any("RUN_NAME" in p for p in make_settings(tmp_path, RUN_NAME="Bad_Name").problems())
    assert any("STANDARD_PRICE" in p for p in make_settings(
        tmp_path, PROVISIONING="standard", STANDARD_PRICE_PER_HOUR="").problems())


def test_prices(tmp_path):
    s = make_settings(tmp_path, DISK_SIZE_GB=365, DISK_PRICE_PER_GB_MONTH=0.10)
    assert s.machine_price == 2.0461
    assert s.disk_price_per_hour == pytest.approx(365 * 0.10 / 730)
    assert s.price_per_hour == pytest.approx(2.0461 + 0.005 + 0.05)
    std = make_settings(tmp_path, PROVISIONING="standard")
    assert std.PROVISIONING == "STANDARD" and std.machine_price == 3.7722
    assert s.vcpus() == 64 and make_settings(tmp_path, MACHINE_TYPE="c4a-highmem-64-lssd").vcpus() == 64


def elf_header(machine: int) -> bytes:
    return b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8 + struct.pack("<HH", 2, machine) + \
        b"\0" * 40


def test_executable_kind(tmp_path):
    cases = {"arm.bin": (elf_header(183), "elf-aarch64"),
             "x86.bin": (elf_header(62), "elf-x86_64"),
             "script": (b"#!/bin/sh\necho\n", "script"),
             "mac.bin": (b"\xcf\xfa\xed\xfe" + b"\0" * 60, "a macOS (Mach-O) program"),
             "junk": (b"hello", "unknown")}
    for name, (data, kind) in cases.items():
        (tmp_path / name).write_bytes(data)
        assert settings.executable_kind(str(tmp_path / name)) == kind
    s = make_settings(tmp_path, TRAINER_PATH=str(tmp_path / "x86.bin"))
    assert any("aarch64" in p for p in s.problems())
    assert make_settings(tmp_path, TRAINER_PATH=str(tmp_path / "arm.bin")).problems() == []


def test_settings_file_in_repo_is_flagged():
    assert not settings.tracked_by_git("/tmp/somewhere/cloud.env")
    example = os.path.join(settings.REPO, "tools", "cloud", "settings.example.env")
    assert settings.tracked_by_git(example)           # a file git would commit
    ignored = os.path.join(settings.REPO, "tools", "cloud", "settings.env")
    assert not settings.tracked_by_git(ignored)       # .gitignore keeps this name out


def test_example_settings_file_loads_and_has_no_secrets():
    path = os.path.join(os.path.dirname(settings.__file__), "settings.example.env")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert set(settings.parse_env_file(text)) <= set(settings.SPEC)
    for key in settings.SPEC:
        assert key in text, f"{key} is not documented in settings.example.env"
    assert "@" not in text.replace("@example", "")    # no email addresses


# --- checkpoint names, restore, retention --------------------------------------------------------

def test_checkpoint_object_round_trip():
    obj = checkpoint_object(42, 1795738515.9, "blue-print.v2.ckpt")
    assert obj == "checkpoints/00000042-20261127T001515Z-blue-print.v2.ckpt"
    c = parse_checkpoint_object(obj, 7)
    assert c.seq == 42 and c.name == "blue-print.v2.ckpt" and c.size == 7
    assert c.written_at == 1795738515.0
    assert parse_checkpoint_object("checkpoints/junk") is None
    assert parse_checkpoint_object("logs/00000001-20261127T001515Z-x") is None


def rc(seq, t, name="b.ckpt"):
    return RemoteCheckpoint(checkpoint_object(seq, t, name), seq, float(int(t)), name, 10)


def test_plan_restore():
    remote = [rc(1, 1000), rc(2, 2000), rc(3, 3000)]
    assert plan_restore([], []) is None
    assert plan_restore([], remote).seq == 3                     # new machine: newest
    assert plan_restore([("b.ckpt", 2500.7)], remote).seq == 3   # the bucket is newer
    assert plan_restore([("b.ckpt", 3000.9)], remote) is None    # the same save
    assert plan_restore([("b.ckpt", 3600.0)], remote) is None    # the disk is newer: keep it
    assert plan_restore([("b.ckpt", 10.0)], []) is None


def test_retention_keeps_the_newest():
    remote = [rc(i, 1000 * i) for i in (5, 1, 3, 4, 2)]
    assert [c.seq for c in retention(remote, 3)] == [2, 1]
    assert retention(remote[:2], 3) == []
    assert [c.seq for c in retention(remote, 0)] == [4, 3, 2, 1]   # never keeps fewer than 1


def test_local_checkpoints_skip_temporary_files(tmp_path):
    for name in ("a.ckpt", "a.ckpt.tmp", ".hidden.ckpt", "b.ckpt", "notes.txt", "c.ckpt.part"):
        (tmp_path / name).write_text("x")
    os.mkdir(tmp_path / "dir.ckpt")
    assert [n for n, _ in sup.local_checkpoints(str(tmp_path), "*.ckpt")] in (
        ["a.ckpt", "b.ckpt"], ["b.ckpt", "a.ckpt"])
    assert sup.local_checkpoints(str(tmp_path / "missing"), "*") == []


# --- cost ----------------------------------------------------------------------------------------

def test_run_cost():
    sessions = [
        {"session": "a", "started_at": 0.0, "last_seen_at": 3600.0, "machine_per_hour": 2.0,
         "ip_per_hour": 0.01},
        {"session": "b", "started_at": 7200.0, "last_seen_at": 7300.0, "machine_per_hour": 2.0,
         "ip_per_hour": 0.01},
    ]
    # a: closed, 1 h + 120 s tail; b: live, until now = 10800 (1 h)
    c = run_cost(sessions, now=10800.0, live_id="b", tail=120.0, disk_per_hour=0.1)
    assert c["machine_hours"] == pytest.approx(1 + 120 / 3600 + 1)
    assert c["machine_usd"] == pytest.approx(2.0 * c["machine_hours"])
    assert c["disk_usd"] == pytest.approx(0.1 * 3)            # the disk exists from 0 to now
    assert c["total_usd"] == pytest.approx(c["machine_usd"] + c["ip_usd"] + c["disk_usd"])
    assert run_cost([], now=5.0)["total_usd"] == 0.0


def test_estimate_cost_adds_time_since_the_last_report(tmp_path):
    s = make_settings(tmp_path)
    status = {"updated_at": 1000.0, "cost": {"total_usd": 5.0}}
    running = {"status": "RUNNING", "last_start_at": 500.0}
    assert control.estimate_cost(status, running, 1000.0 + 3600, s) == \
        pytest.approx(5.0 + s.price_per_hour)
    # a new boot that has not reported yet: from its start
    rebooted = {"status": "RUNNING", "last_start_at": 2000.0}
    assert control.estimate_cost(status, rebooted, 2000.0 + 1800, s) == \
        pytest.approx(5.0 + s.price_per_hour / 2)
    stopped = {"status": "TERMINATED", "last_start_at": 500.0}
    assert control.estimate_cost(status, stopped, 1000.0 + 3600, s) == \
        pytest.approx(5.0 + s.disk_price_per_hour)
    assert control.estimate_cost(None, None, 99.0, s) == 0.0
    assert control.run_seconds_left(0.0, s) == int(40 / s.price_per_hour * 3600)
    assert control.run_seconds_left(41.0, s) == 0


# --- progress ------------------------------------------------------------------------------------

def test_parse_progress_and_rate():
    assert sup.parse_progress('{"iterations": 5, "x": 1}') == {"iterations": 5, "x": 1}
    for line in ("iterations=5", '{"iterations": "5"}', '{"iterations": true}', "{bad json}",
                 '["iterations"]', ""):
        assert sup.parse_progress(line) is None
    r = sup.Rate(window=100)
    assert r.per_second() is None
    for t in range(0, 300, 10):
        r.add(float(t), t * 50.0)
    assert r.per_second() == pytest.approx(50.0)
    assert r.samples[0][0] >= 190 - 10
    r.add(400.0, 10.0)                       # resumed from an older checkpoint
    assert r.per_second() is None


# --- stores --------------------------------------------------------------------------------------

def test_parse_ls_long():
    text = """      2276224  2026-11-26T19:25:17Z  gs://b/runs/r/checkpoints/00000001-20261126T192517Z-x.ckpt
                                 gs://b/runs/r/checkpoints/sub/
           12  2026-11-26T19:25:18Z  gs://b/runs/r/checkpoints/00000002-20261126T192518Z-x.ckpt
TOTAL: 2 objects, 2276236 bytes (2.17MiB)
"""
    assert sup.parse_ls_long(text, "gs://b/runs/r/") == [
        ("checkpoints/00000001-20261126T192517Z-x.ckpt", 2276224),
        ("checkpoints/00000002-20261126T192518Z-x.ckpt", 12)]


def exercise_store(store, tmp_path):
    assert store.get_bytes("status.json") is None
    assert store.list("checkpoints/") == []
    store.put_bytes("status.json", b'{"a": 1}')
    assert sup.read_json(store, "status.json") == {"a": 1}
    f = tmp_path / "data.bin"
    f.write_bytes(b"x" * 1000)
    store.put_file("checkpoints/00000001-20261126T192517Z-x.ckpt", str(f))
    store.put_file("checkpoints/00000002-20261126T192518Z-x.ckpt", str(f))
    assert store.list("checkpoints/") == [
        ("checkpoints/00000001-20261126T192517Z-x.ckpt", 1000),
        ("checkpoints/00000002-20261126T192518Z-x.ckpt", 1000)]
    out = tmp_path / "back.bin"
    store.get_file("checkpoints/00000002-20261126T192518Z-x.ckpt", str(out))
    assert out.read_bytes() == b"x" * 1000
    store.delete("checkpoints/00000001-20261126T192517Z-x.ckpt")
    store.delete("checkpoints/never-there")          # no error
    assert [n for n, _ in store.list("checkpoints/")] == [
        "checkpoints/00000002-20261126T192518Z-x.ckpt"]
    with pytest.raises(sup.StoreError):
        store.get_file("checkpoints/missing", str(tmp_path / "nope"))


def test_local_store(tmp_path):
    exercise_store(LocalStore(str(tmp_path / "bucket")), tmp_path)


def test_gcs_store_through_fake_gcloud(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_GCS_ROOT", str(tmp_path / "gcs"))
    os.makedirs(tmp_path / "gcs")
    store = GcsStore("gs://test-bucket/runs/r", gcloud=[sys.executable, FAKE_GCLOUD])
    exercise_store(store, tmp_path)
    assert (tmp_path / "gcs" / "test-bucket" / "runs" / "r" / "status.json").exists()
    calls = (tmp_path / "gcs" / "calls.log").read_text().splitlines()
    assert "storage cp - gs://test-bucket/runs/r/status.json" in calls


def test_gcs_store_reports_real_errors(tmp_path):
    bad = tmp_path / "gcloud"
    bad.write_text("#!/bin/sh\necho 'ERROR: (gcloud.storage) 403 permission denied' >&2\nexit 1\n")
    bad.chmod(0o755)
    store = GcsStore("gs://b/runs/r", gcloud=[str(bad)])
    with pytest.raises(sup.StoreError, match="403"):
        store.get_bytes("status.json")
    with pytest.raises(sup.StoreError, match="403"):
        store.list("checkpoints/")
    with pytest.raises(ValueError):
        GcsStore("/not/a/bucket")


# --- gcloud commands -----------------------------------------------------------------------------

def test_duration_and_times():
    assert gce.duration(0) == "0s"
    assert gce.duration(59) == "59s"
    assert gce.duration(3600 * 26 + 61) == "1d2h1m1s"
    assert gce.parse_time("2026-11-26T15:30:00.123-08:00") == pytest.approx(1795735800.123)
    assert gce.parse_time("2026-11-26T23:30:00Z") == pytest.approx(1795735800.0)
    assert gce.parse_time(None) is None and gce.parse_time("garbage") is None


def test_create_command_spot(tmp_path):
    s = make_settings(tmp_path)
    md = control.instance_metadata(s, "abc123")
    cmd = gce.create_command(s, "us-central1-b", 7200, md, "/x/startup.sh")
    assert cmd[:5] == ["beta", "compute", "instances", "create", "ps-hu-test"]
    for flag in ("--zone=us-central1-b", "--machine-type=c4a-highmem-64",
                 "--provisioning-model=SPOT", "--instance-termination-action=STOP",
                 "--max-run-duration=2h", "--image-family=debian-12-arm64",
                 "--image-project=debian-cloud", "--boot-disk-size=200GB",
                 "--boot-disk-type=hyperdisk-balanced", "--scopes=storage-rw",
                 "--labels=pscloud-run=hu-test", "--preemption-notice-duration=120s",
                 "--metadata-from-file=startup-script=/x/startup.sh"):
        assert flag in cmd, flag
    meta = next(c for c in cmd if c.startswith("--metadata="))
    assert "pscloud-store=gs://test-bucket/runs/hu-test" in meta
    assert "pscloud-bundle-version=abc123" in meta
    assert "pscloud-budget-usd=40.00" in meta
    assert not any(c.startswith("--service-account") for c in cmd)
    assert "--no-address" not in cmd


def test_create_command_standard_and_options(tmp_path):
    s = make_settings(tmp_path, PROVISIONING="STANDARD", SERVICE_ACCOUNT="trainer-sa-name",
                      EXTERNAL_IP="false", DISK_IOPS=6000, DISK_THROUGHPUT_MBPS=600,
                      SUBNET="sub-1")
    cmd = gce.create_command(s, "us-central1-a", 90, {"k": "v"}, "/s.sh")
    assert cmd[0] == "compute"                              # no beta without Spot notice
    assert "--provisioning-model=STANDARD" in cmd
    assert "--max-run-duration=1m30s" in cmd
    assert "--instance-termination-action=STOP" in cmd      # needed by --max-run-duration
    assert not any(c.startswith("--preemption-notice") for c in cmd)
    for flag in ("--service-account=trainer-sa-name", "--no-address",
                 "--boot-disk-provisioned-iops=6000", "--boot-disk-provisioned-throughput=600",
                 "--subnet=sub-1"):
        assert flag in cmd
    s0 = make_settings(tmp_path, PREEMPTION_NOTICE_SECONDS=0)
    assert gce.create_command(s0, "us-central1-a", 90, {}, "/s.sh")[0] == "compute"
    with pytest.raises(ValueError):
        gce.metadata_arg({"k": "a,b"})


def test_gcloud_adds_project_and_dry_run_prints():
    seen = []
    g = gce.Gcloud("p1", runner=lambda args: (seen.append(args) or (0, '{"a": 1}', "")))
    assert g(["compute", "instances", "list"], json_out=True) == {"a": 1}
    assert seen[0] == ["compute", "instances", "list", "--project", "p1", "--format", "json"]
    printed = []
    d = gce.Gcloud("p1", dry_run=True, echo=printed.append,
                   runner=lambda a: pytest.fail("a dry run ran gcloud"))
    assert d(["compute", "instances", "list"], json_out=True, mutating=False) == []
    d(["compute", "instances", "delete", "x", "--quiet"])
    assert printed == ["would run: gcloud compute instances delete x --quiet --project p1"]
    err = gce.Gcloud("p", runner=lambda a: (1, "", "ZONE_RESOURCE_POOL_EXHAUSTED: no room"))
    with pytest.raises(gce.GcloudError) as e:
        err(["compute", "instances", "start", "x"])
    assert e.value.stockout and not e.value.quota


def test_preempted_since():
    ops = [{"operationType": "compute.instances.preempted",
            "targetLink": "https://x/zones/z/instances/ps-hu-test", "insertTime": "2026-11-26T10:00:00Z"},
           {"operationType": "compute.instances.preempted",
            "targetLink": "https://x/zones/z/instances/other", "insertTime": "2026-11-26T12:00:00Z"}]
    g = gce.Gcloud("p", runner=lambda a: (0, json.dumps(ops), ""))
    t = gce.parse_time("2026-11-26T10:00:00Z")
    assert gce.preempted_since(g, "ps-hu-test", "z", t - 3600) == t
    assert gce.preempted_since(g, "ps-hu-test", "z", t + 3600) is None   # before the last start
    assert gce.preempted_since(g, "nobody", "z", None) is None


# --- the recovery decision -----------------------------------------------------------------------

def snap(**over):
    base = {"now": 10000.0, "instance": {"name": "ps-hu-test", "zone": "us-central1-a",
                                         "status": "TERMINATED", "last_start_at": 5000.0},
            "status": None, "state": None, "stop_requested": False,
            "restarts": {"events": []}, "checkpoints": [], "preempted_at": 9000.0, "cost": 1.0}
    base.update(over)
    return base


def test_decide(tmp_path):
    s = make_settings(tmp_path, ZONES="us-central1-a,us-central1-b", MAX_RESTARTS=2)
    running = {"name": "x", "zone": "us-central1-a", "status": "RUNNING"}
    table = [
        (snap(), "start"),
        (snap(instance=running), "wait"),
        (snap(instance=dict(running, status="STOPPING")), "wait"),
        (snap(state={"state": "done", "detail": "finished"}), "finished"),
        (snap(state={"state": "failed", "detail": "x"}, instance=running), "finished"),
        (snap(stop_requested=True), "finished"),
        (snap(cost=39.9), "give-up"),                        # inside the margin
        (snap(restarts={"events": [{"counted": True}, {"counted": True}]}), "give-up"),
        (snap(restarts={"events": [{"counted": False}] * 5}), "start"),   # resumes don't count
        (snap(instance=None), "create"),
        (snap(preempted_at=None), "give-up"),                # stopped by something else
        (snap(instance=dict(running, status="SUSPENDED")), "give-up"),
    ]
    for sn, want in table:
        assert control.decide(sn, s)[0] == want, (sn, control.decide(sn, s))
    assert control.decide(snap(), s, failed_starts=3)[0] == "recreate"
    one_zone = make_settings(tmp_path)
    assert control.decide(snap(), one_zone, failed_starts=9)[0] == "start"
    anystop = make_settings(tmp_path, RESTART_ANY_STOP="true")
    assert control.decide(snap(preempted_at=None), anystop)[0] == "start"


# --- the bundle ----------------------------------------------------------------------------------

def test_bundle_copy_mode(tmp_path):
    s = make_settings(tmp_path, TRAINER_ARGS="--threads 64 --name 'a b'")
    a, b = tmp_path / "a", tmp_path / "b"
    m1 = control.build_bundle(s, str(a))
    m2 = control.build_bundle(s, str(b))
    assert m1["version"] == m2["version"] and len(m1["version"]) == 16
    assert sorted(m1["files"]) == ["config/train.json", "run.json", "supervisor.py", "trainer"]
    run = json.loads((a / "run.json").read_text())
    assert run["trainer"] == ["/opt/pscloud/bundle/trainer"]
    assert run["config"] == "/opt/pscloud/bundle/config/train.json"
    assert run["trainer_args"] == ["--threads", "64", "--name", "a b"]
    assert run["store"] == "gs://test-bucket/runs/hu-test"
    assert run["budget_usd"] == 40.0 and run["machine_per_hour"] == 2.0461
    assert run["power_off"] == ["systemctl", "poweroff"] and run["gce_metadata"]
    sup.check_run_config(run)
    assert set(run) - {"format"} <= set(sup.DEFAULTS)
    (tmp_path / "train.json").write_text('{"iterations": 11}\n')
    assert control.build_bundle(s, str(tmp_path / "c"))["version"] != m1["version"]


def test_bundle_build_mode(tmp_path):
    eng = tmp_path / "engine"
    (eng / "crates" / "x" / "src").mkdir(parents=True)
    (eng / "Cargo.toml").write_text("[workspace]\n")
    (eng / "crates" / "x" / "src" / "main.rs").write_text("fn main() {}\n")
    (eng / "target" / "release").mkdir(parents=True)
    (eng / "target" / "release" / "big").write_bytes(b"x" * 1000)
    s = make_settings(tmp_path, TRAINER_MODE="build", TRAINER_CARGO_BIN="blueprint",
                      ENGINE_DIR=str(eng))
    assert s.problems() == []
    m = control.build_bundle(s, str(tmp_path / "bundle"))
    assert m["mode"] == "build" and m["cargo_bin"] == "blueprint" and m["has_lock"] is False
    data = (tmp_path / "bundle" / "engine-src.tar.gz").read_bytes()
    names = tarfile.open(fileobj=io.BytesIO(gzip.decompress(data))).getnames()
    assert sorted(names) == ["engine/Cargo.toml", "engine/crates/x/src/main.rs"]
    assert control.engine_tarball(str(eng)) == data            # the same bytes every time
    assert m["version"] == control.build_bundle(s, str(tmp_path / "again"))["version"]


# --- watch ---------------------------------------------------------------------------------------

def test_format_watch(tmp_path):
    s = make_settings(tmp_path)
    now = 100000.0
    status = {
        "updated_at": now - 25, "stop_reason": None,
        "trainer": {"state": "running", "started_at": now - 7800, "resumed": True, "crashes": 0},
        "progress": {"iterations": 1_234_567_000, "target_iterations": 10_000_000_000,
                     "iterations_per_second": 152_000.0, "updated_at": now - 30},
        "memory": {"trainer_rss_bytes": 41.2e9, "trainer_peak_bytes": 42e9,
                   "total_bytes": 503.8e9, "available_bytes": 458.8e9},
        "checkpoints": {"last_written_at": now - 240, "last_written_name": "blueprint.ckpt",
                        "last_written_bytes": 5.5e9, "last_uploaded_at": now - 180,
                        "upload_failures": 0},
        "cost": {"total_usd": 8.41, "machine_usd": 8.2, "ip_usd": 0.06, "disk_usd": 0.15},
    }
    inst = {"name": "ps-hu-test", "zone": "us-central1-a", "status": "RUNNING",
            "machine_type": "c4a-highmem-64", "provisioning": "SPOT", "last_start_at": now - 8000}
    sn = {"now": now, "instance": inst, "status": status, "state": None, "stop_requested": False,
          "restarts": {"events": [{"at": now - 9000, "action": "start", "zone": "us-central1-a",
                                   "why": "preempted", "counted": True}]},
          "checkpoints": [rc(1, 1), rc(2, 2), rc(3, 3)], "preempted_at": None,
          "cost": control.estimate_cost(status, inst, now, s)}
    text = "\n".join(control.format_watch(sn, s))
    for want in ("RUNNING for 2 h 13 min", "running (resumed)", "1,234,567,000 iterations",
                 "12.3%", "152,000 per second", "about 16 h", "trainer 41.2 GB (peak 42.0 GB)",
                 "machine 45.0 of 503.8 GB", "written 4 min ago", "uploaded 3 min ago",
                 "3 in the bucket", "cap $40.00", "restarts    1 of 10", "report      25 s ago"):
        assert want in text, (want, text)
    assert "WARNING" not in text
    quiet = dict(sn, status=dict(status, updated_at=now - 3600))
    assert "WARNING" in "\n".join(control.format_watch(quiet, s))
    empty = {"now": now, "instance": None, "status": None, "state": None,
             "stop_requested": False, "restarts": {"events": []}, "checkpoints": [],
             "preempted_at": None, "cost": 0.0}
    assert "none" in "\n".join(control.format_watch(empty, s))


def test_cli_help_runs():
    p = subprocess.run([sys.executable, "-m", "tools.cloud", "--help"], capture_output=True,
                       text=True, cwd=settings.REPO)
    assert p.returncode == 0 and "local-test" in p.stdout


# --- trainer files, memory and disk --------------------------------------------------------------

def test_known_machines_memory_and_disk_rules(tmp_path):
    s = make_settings(tmp_path, MACHINE_TYPE="c4a-highcpu-64")
    assert s.vcpus() == 64 and s.machine_memory_gb() == 128.0
    assert make_settings(tmp_path).machine_memory_gb() == 512.0        # c4a-highmem-64
    assert make_settings(tmp_path, MACHINE_TYPE="n2-custom-8-1024").machine_memory_gb() is None
    # The Phase 6 trainer (7.4 GB at its peak) fits; 120 GB does not leave 10% spare.
    assert make_settings(tmp_path, MACHINE_TYPE="c4a-highcpu-64",
                         TRAINER_MEMORY_GB="7.4").problems() == []
    big = make_settings(tmp_path, MACHINE_TYPE="c4a-highcpu-64", TRAINER_MEMORY_GB="120")
    assert any("does not fit c4a-highcpu-64 (128 GB)" in p for p in big.problems())
    # The disk holds 4 checkpoints, the artifacts and 30 GB for the system.
    disk = make_settings(tmp_path, CHECKPOINT_GB="4.9", ARTIFACTS_GB="7", DISK_SIZE_GB="50")
    assert disk.disk_needed_gb() == pytest.approx(56.6)
    assert any("DISK_SIZE_GB 50 is too small" in p and "56.6 GB" in p for p in disk.problems())
    assert make_settings(tmp_path, CHECKPOINT_GB="4.9", ARTIFACTS_GB="7",
                         DISK_SIZE_GB="80").problems() == []
    assert make_settings(tmp_path).disk_needed_gb() is None


def test_trainer_files_must_exist_and_cover_the_config(tmp_path):
    tables = tmp_path / "k200"
    tables.mkdir()
    (tables / "river.abs").write_bytes(b"r" * 100)
    cfg = tmp_path / "phase6.json"
    cfg.write_text(json.dumps({"spec": {"abstraction": "/opt/pscloud/bundle/files/k200",
                                        "stack_bb": 200}}))
    none = make_settings(tmp_path, TRAINER_CONFIG=str(cfg))
    assert any("names /opt/pscloud/bundle/files/k200" in p and "called k200" in p
               for p in none.problems())
    good = make_settings(tmp_path, TRAINER_CONFIG=str(cfg), TRAINER_FILES=str(tables))
    assert good.problems() == [] and good.trainer_files() == [str(tables)]
    missing = make_settings(tmp_path, TRAINER_FILES=str(tmp_path / "nope"))
    assert any("does not exist" in p for p in missing.problems())
    other = tmp_path / "other" / "k200"
    other.mkdir(parents=True)
    twice = make_settings(tmp_path, TRAINER_FILES=f"{tables},{other}")
    assert any("two entries are called k200" in p for p in twice.problems())


def test_bundle_with_trainer_files(tmp_path):
    tables = tmp_path / "k200"
    tables.mkdir()
    (tables / "river.abs").write_bytes(b"r" * 1000)
    (tables / "flop.abs").write_bytes(b"f" * 10)
    (tables / ".DS_Store").write_bytes(b"x")
    s = make_settings(tmp_path, TRAINER_FILES=str(tables))
    m = control.build_bundle(s, str(tmp_path / "a"))
    assert m["extra_files"] == ["files/k200/flop.abs", "files/k200/river.abs"]
    assert set(m["extra_files"]) <= set(m["files"])
    assert (tmp_path / "a" / "files" / "k200" / "river.abs").read_bytes() == b"r" * 1000
    assert m["bytes"] >= 1010
    run = json.loads((tmp_path / "a" / "run.json").read_text())
    assert run["artifact_patterns"] == ["*.bps", "*.jsonl"]
    sup.check_run_config(run)
    assert control.build_bundle(s, str(tmp_path / "b"))["version"] == m["version"]
    (tables / "river.abs").write_bytes(b"R" * 1000)           # other tables: another bundle
    assert control.build_bundle(s, str(tmp_path / "c"))["version"] != m["version"]
    plain = control.build_bundle(make_settings(tmp_path), str(tmp_path / "d"))
    assert plain["extra_files"] == []
    off = make_settings(tmp_path, ARTIFACT_PATTERNS="none")
    assert control.run_config(off)["artifact_patterns"] == []


def test_format_watch_artifacts_and_memory_warning(tmp_path):
    s = make_settings(tmp_path, MACHINE_TYPE="c4a-highcpu-64")
    now = 100000.0
    status = {"updated_at": now - 20,
              "memory": {"trainer_rss_bytes": 7.3e9, "trainer_peak_bytes": 7.4e9,
                         "total_bytes": 135e9, "available_bytes": 126e9},
              "artifacts": {"uploads": 3, "in_bucket": 4, "restored": 1,
                            "last_uploaded_name": "strategy-4000000.bps",
                            "last_uploaded_at": now - 60, "upload_failures": 0}}
    inst = {"name": "ps-hu-test", "zone": "us-central1-a", "status": "RUNNING",
            "machine_type": "c4a-highcpu-64", "provisioning": "SPOT", "last_start_at": now - 900}
    sn = {"now": now, "instance": inst, "status": status, "state": None, "stop_requested": False,
          "restarts": {"events": []}, "checkpoints": [], "preempted_at": None, "cost": 1.0}
    text = "\n".join(control.format_watch(sn, s))
    assert "artifacts   4 in the bucket; last strategy-4000000.bps 60 s ago; 1 put back" in text
    assert "WARNING" not in text
    full = dict(status, memory=dict(status["memory"], trainer_peak_bytes=125e9))
    text = "\n".join(control.format_watch(dict(sn, status=full), s))
    assert "WARNING     memory reached 93% of the machine" in text
