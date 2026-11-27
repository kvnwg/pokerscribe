"""The commands run from Kevin's computer, against a fake Compute Engine (tests/helpers.py) and
a local folder as the bucket: launch (and --dry-run), recover, stop, resume, cleanup, check,
leftovers. The last two tests are whole simulated runs: real supervisors and the fake trainer
on folders standing in for machine disks, a Spot preemption halfway, and the recovery loop
restarting the same machine, or making a new one when Google deleted it."""
from __future__ import annotations

import json
import os
import time

import pytest

from tools.cloud import control, fake_trainer, gce, local_test
from tools.cloud.supervisor import (BUNDLE, LAUNCH, RESTARTS, STATE, STATUS, STOP_MARKER,
                                    LocalStore, read_json, remote_checkpoints, write_json)

from .helpers import FakeCompute, iso, make_settings

STOCKOUT = ("ERROR: (gcloud.compute.instances.start) The zone 'us-central1-a' does not have "
            "enough resources available to fulfill the request. ZONE_RESOURCE_POOL_EXHAUSTED")


class Done(Exception):
    pass


def make_ctx(tmp_path, fake=None, sleeps=None, **over):
    s = make_settings(tmp_path, **over)
    fake = fake or FakeCompute()
    out = []
    store = LocalStore(str(tmp_path / "bucket" / "runs" / s.RUN_NAME))

    def sleep(_seconds):
        if sleeps is not None:
            sleeps.append(_seconds)
            if len(sleeps) > 20:
                raise Done()

    ctx = control.Ctx(s, gce.Gcloud(s.PROJECT, runner=fake, echo=out.append), store,
                      out=out.append, sleep=sleep)
    return ctx, fake, out


# --- launch --------------------------------------------------------------------------------------

def test_launch_dry_run_runs_nothing(tmp_path):
    s = make_settings(tmp_path)
    out = []

    def no_gcloud(args):
        raise AssertionError(f"a dry run ran gcloud {args}")

    ctx = control.Ctx(s, gce.Gcloud(s.PROJECT, runner=no_gcloud, dry_run=True, echo=out.append),
                      control.DryStore(s.store_url, out.append), out=out.append)
    assert control.launch(ctx) == 0
    text = "\n".join(out)
    assert "would run: gcloud storage buckets create gs://test-bucket --location=us-central1" in text
    assert "--soft-delete-duration=0" in text
    assert "would run: gcloud beta compute instances create ps-hu-test" in text
    assert "--provisioning-model=SPOT" in text and "--max-run-duration=" in text
    for f in ("supervisor.py", "run.json", "config/train.json", "trainer", "manifest.json"):
        assert f"to gs://test-bucket/runs/hu-test/bundle/{f}" in text, f
    assert "python -m tools.cloud watch" in text


def test_launch_creates_bucket_bundle_and_machine(tmp_path):
    ctx, fake, out = make_ctx(tmp_path)
    assert control.launch(ctx) == 0, out
    assert "test-bucket" in str(fake.buckets) or "gs://test-bucket" in fake.buckets
    create = next(c for c in fake.calls if "create" in c and "instances" in c)
    manifest = read_json(ctx.store, BUNDLE + "manifest.json")
    assert f"pscloud-bundle-version={manifest['version']}" in " ".join(create)
    for f in manifest["files"]:
        assert os.path.exists(ctx.store.url(BUNDLE + f)), f
    run = json.loads(open(ctx.store.url(BUNDLE + "run.json")).read())
    assert run["store"] == "gs://test-bucket/runs/hu-test"
    launch = read_json(ctx.store, LAUNCH)
    assert launch["zone"] == "us-central1-a" and launch["bundle"] == manifest["version"]
    hours = control.run_seconds_left(0.0, ctx.s)
    assert f"--max-run-duration={gce.duration(hours)}" in create
    assert fake.instances["ps-hu-test"]["status"] == "RUNNING"


def test_launch_refusals(tmp_path):
    ctx, fake, out = make_ctx(tmp_path)
    fake.add("ps-hu-test")
    assert control.launch(ctx) == 2 and "already exists" in out[-1]
    ctx, fake, out = make_ctx(tmp_path / "b")
    write_json(ctx.store, STATE, {"state": "done", "detail": "x"})
    assert control.launch(ctx) == 2 and "already done" in out[-1]
    ctx, fake, out = make_ctx(tmp_path / "c")
    write_json(ctx.store, STATUS, {"updated_at": 1.0, "cost": {"total_usd": 39.95}})
    assert control.launch(ctx) == 2 and "Raise BUDGET_USD" in out[-1]
    ctx, fake, out = make_ctx(tmp_path / "d", BUDGET_USD="")
    assert control.launch(ctx) == 2 and any("BUDGET_USD" in x for x in out)
    assert not any("create" in c for c in fake.calls)


def test_launch_clears_an_earlier_failure_and_resumes_from_the_bucket(tmp_path):
    ctx, fake, out = make_ctx(tmp_path)
    write_json(ctx.store, STATE, {"state": "failed", "detail": "x"})
    write_json(ctx.store, STOP_MARKER, {})
    ck = tmp_path / "x.ckpt"
    ck.write_bytes(b"x")
    ctx.store.put_file("checkpoints/00000003-20261126T120000Z-x.ckpt", str(ck))
    assert control.launch(ctx) == 0
    assert read_json(ctx.store, STATE) is None and read_json(ctx.store, STOP_MARKER) is None
    assert any("resume from checkpoints/00000003" in x for x in out)


def test_launch_moves_on_when_a_zone_is_full(tmp_path):
    ctx, fake, out = make_ctx(tmp_path, ZONES="us-central1-a,us-central1-c")
    fake.fail["create"] = [STOCKOUT]
    assert control.launch(ctx) == 0
    assert read_json(ctx.store, LAUNCH)["zone"] == "us-central1-c"
    assert fake.instances["ps-hu-test"]["zone"].endswith("us-central1-c")


def test_launch_explains_quota(tmp_path):
    ctx, fake, out = make_ctx(tmp_path)
    fake.fail["create"] = ["ERROR: Quota 'C4A_CPUS' exceeded. Limit: 0.0 in region us-central1."]
    with pytest.raises(RuntimeError, match="Setup step 4"):
        control.launch(ctx)


def test_existing_bucket_with_soft_delete_is_warned_about(tmp_path):
    ctx, fake, out = make_ctx(tmp_path)
    fake.buckets["gs://test-bucket"] = {"location": "US-CENTRAL1", "soft_delete_policy": {
        "retentionDurationSeconds": "604800"}}
    control.ensure_bucket(ctx)
    assert any("soft delete" in x and "7 days" in x for x in out)
    assert not any(c[:3] == ["storage", "buckets", "create"] for c in fake.calls)


# --- recover -------------------------------------------------------------------------------------

def preempted_machine(fake, name="ps-hu-test", zone="us-central1-a"):
    fake.add(name, zone=zone, status="TERMINATED", started=time.time() - 3600)
    fake.operations.append({"operationType": "compute.instances.preempted",
                            "targetLink": f"https://x/zones/{zone}/instances/{name}",
                            "insertTime": iso(time.time() - 60)})


def test_recover_restarts_a_preempted_machine(tmp_path):
    ctx, fake, out = make_ctx(tmp_path, BUDGET_USD="30")
    preempted_machine(fake)
    write_json(ctx.store, STATUS, {"updated_at": time.time() - 120, "stop_reason": "shutdown",
                                   "cost": {"total_usd": 10.0}})
    assert control.recover(ctx, once=True) == 0
    assert fake.verbs() == ["add-metadata", "set-scheduling", "start"]
    assert fake.metadata["ps-hu-test"]["pscloud-budget-usd"] == "30.00"
    left = control.run_seconds_left(
        control.estimate_cost(read_json(ctx.store, STATUS),
                              {"status": "TERMINATED"}, time.time(), ctx.s), ctx.s)
    got = fake.instances["ps-hu-test"]["scheduling"]["maxRunDuration"]
    assert abs(_seconds(got) - left) < 30
    ev = read_json(ctx.store, RESTARTS)["events"]
    assert len(ev) == 1 and ev[0]["action"] == "start" and ev[0]["counted"]


def _seconds(d):
    total, num = 0, ""
    for ch in d:
        if ch.isdigit():
            num += ch
        else:
            total += int(num) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[ch]
            num = ""
    return total


def test_recover_makes_a_new_machine_after_repeated_stockouts(tmp_path):
    sleeps = []
    ctx, fake, out = make_ctx(tmp_path, sleeps=sleeps, ZONES="us-central1-a,us-central1-b")
    write_json(ctx.store, BUNDLE + "manifest.json", {"version": "v1"})
    preempted_machine(fake)
    fake.fail["start"] = [STOCKOUT] * 3
    with pytest.raises(Done):
        control.recover(ctx)
    verbs = fake.verbs()
    assert verbs.count("start") == 3 and "delete" in verbs and verbs[-1] == "create"
    assert fake.instances["ps-hu-test"]["zone"].endswith("us-central1-b")
    ev = read_json(ctx.store, RESTARTS)["events"]
    assert [e["action"] for e in ev] == ["recreate"] and ev[0]["zone"] == "us-central1-b"


@pytest.mark.parametrize("setup,want_rc,words", [
    (lambda ctx, fake: write_json(ctx.store, STATE, {"state": "done", "detail": "finished"}),
     0, "the run is done"),
    (lambda ctx, fake: write_json(ctx.store, STOP_MARKER, {}), 0, "stop was requested"),
    (lambda ctx, fake: write_json(ctx.store, STATUS, {"updated_at": time.time(),
                                                      "cost": {"total_usd": 39.9}}),
     1, "budget is spent"),
    (lambda ctx, fake: write_json(ctx.store, RESTARTS, {"events": [{"counted": True}] * 10}),
     1, "10 restarts used"),
    (lambda ctx, fake: fake.operations.clear(), 1, "not by a Spot preemption"),
])
def test_recover_knows_when_to_stop(tmp_path, setup, want_rc, words):
    ctx, fake, out = make_ctx(tmp_path)
    preempted_machine(fake)
    setup(ctx, fake)
    assert control.recover(ctx, once=True) == want_rc
    assert words in out[-1], out
    assert "start" not in fake.verbs()


def test_recover_waits_while_running(tmp_path):
    ctx, fake, out = make_ctx(tmp_path)
    fake.add("ps-hu-test")
    assert control.recover(ctx, once=True) == 0
    assert fake.verbs() == [] and "wait" in out[-1]


# --- stop, resume, cleanup, leftovers ------------------------------------------------------------

def test_stop_without_a_live_supervisor_falls_back_to_gce(tmp_path):
    ctx, fake, out = make_ctx(tmp_path)
    fake.add("ps-hu-test")
    assert control.stop(ctx) == 0
    assert read_json(ctx.store, STOP_MARKER) is not None
    assert fake.verbs() == ["stop"]
    assert fake.instances["ps-hu-test"]["status"] == "TERMINATED"
    assert any("Still in project" in x or "Nothing in project" in x for x in out)


def test_resume_clears_the_stop_and_starts(tmp_path):
    ctx, fake, out = make_ctx(tmp_path)
    fake.add("ps-hu-test", status="TERMINATED")
    write_json(ctx.store, STOP_MARKER, {})
    write_json(ctx.store, STATE, {"state": "stopped"})
    assert control.resume(ctx) == 0
    assert read_json(ctx.store, STOP_MARKER) is None and read_json(ctx.store, STATE) is None
    assert fake.verbs()[-1] == "start"
    assert read_json(ctx.store, RESTARTS)["events"][0]["counted"] is False


def test_cleanup_deletes_the_machine_and_keeps_the_bucket(tmp_path):
    ctx, fake, out = make_ctx(tmp_path)
    fake.add("ps-hu-test", status="TERMINATED")
    write_json(ctx.store, STATUS, {"x": 1})
    assert control.cleanup(ctx, ask=lambda q: "n") == 1
    assert "ps-hu-test" in fake.instances
    assert control.cleanup(ctx, yes=True) == 0
    assert "ps-hu-test" not in fake.instances
    delete = next(c for c in fake.calls if "delete" in c)
    assert "--delete-disks=all" in delete
    assert read_json(ctx.store, STATUS) == {"x": 1}            # the bucket is untouched


def test_leftovers_lists_what_costs_money(tmp_path):
    s = make_settings(tmp_path)
    rows = {
        ("compute", "instances", "list"): [{"name": "ps-hu-test", "zone": "z/us-central1-a",
                                            "status": "TERMINATED", "labels": {"pscloud-run": "x"},
                                            "machineType": "m/c4a-highmem-64"}],
        ("compute", "disks", "list"): [{"name": "ps-hu-test", "zone": "z/us-central1-a",
                                        "sizeGb": "200", "type": "t/hyperdisk-balanced",
                                        "users": ["u/instances/ps-hu-test"]},
                                       {"name": "old", "zone": "z/us-central1-b", "sizeGb": "10",
                                        "type": "t/pd-standard"}],
        ("compute", "addresses", "list"): [{"name": "ip1", "region": "r/us-central1",
                                            "status": "RESERVED"}],
        ("storage", "buckets", "list"): [{"name": "test-bucket", "location": "US-CENTRAL1"}],
    }

    def runner(args):
        if args[:3] == ["storage", "du", "--summarize"]:
            return 0, "5000000000  gs://test-bucket\n", ""
        return 0, json.dumps(rows.get(tuple(args[:3]), [])), ""

    out = []
    ctx = control.Ctx(s, gce.Gcloud(s.PROJECT, runner=runner), None, out=out.append)
    control.print_leftovers(ctx)
    text = "\n".join(out)
    assert "stopped: its disks still bill" in text and "attached to nothing" in text
    assert "about $16.00/month" in text                         # 200 GB at $0.08
    assert "static IP" in text and "5.00 GB stored" in text
    assert text.count("(this run)") == 3                        # machine, disk, bucket


def test_check_points_at_what_to_fix(tmp_path):
    s = make_settings(tmp_path)
    answers = {
        ("config", "get-value", "account"): (0, "someone\n"),
        ("projects", "describe", "test-project"): (0, '{"projectId": "test-project"}'),
        ("services", "list", "--enabled"): (0, json.dumps(
            [{"config": {"name": "compute.googleapis.com"}}])),
        ("compute", "machine-types", "describe"): (0, '{"guestCpus": 64, "memoryMb": 524288}'),
        ("compute", "regions", "describe"): (0, json.dumps({"quotas": [
            {"metric": "C4A_CPUS", "limit": 24.0, "usage": 0.0},
            {"metric": "CPUS", "limit": 100.0, "usage": 0.0}]})),
        ("compute", "project-info", "describe"): (0, json.dumps({"quotas": [
            {"metric": "CPUS_ALL_REGIONS", "limit": 32.0, "usage": 0.0}]})),
        ("beta", "compute", "instances"): (0, "... --preemption-notice-duration ..."),
        ("storage", "buckets", "describe"): (0, json.dumps(
            {"location": "US-CENTRAL1", "soft_delete_policy": {"retentionDurationSeconds": "0"}})),
    }

    def runner(args):
        for k, (rc, text) in answers.items():
            if tuple(args[:len(k)]) == k:
                return rc, text, ""
        return 1, "", "not found"

    out = []
    ctx = control.Ctx(s, gce.Gcloud(s.PROJECT, runner=runner), None, out=out.append)
    assert control.check(ctx) == 1
    text = "\n".join(out)
    assert "FIX   storage.googleapis.com is enabled" in text
    assert "FIX   C4A CPU quota in us-central1 has room for 64 vCPUs" in text
    assert "FIX   CPUS_ALL_REGIONS has room for 64 vCPUs" in text
    assert "ok    compute.googleapis.com is enabled" in text
    assert "ok    bucket soft delete is off" in text
    assert "3 thing(s) to fix" in text


def check_answers(memory_mb):
    return {
        ("config", "get-value", "account"): (0, "someone\n"),
        ("projects", "describe", "test-project"): (0, '{"projectId": "test-project"}'),
        ("services", "list", "--enabled"): (0, json.dumps(
            [{"config": {"name": "compute.googleapis.com"}},
             {"config": {"name": "storage.googleapis.com"}}])),
        ("compute", "machine-types", "describe"): (
            0, json.dumps({"guestCpus": 64, "memoryMb": memory_mb})),
        ("compute", "regions", "describe"): (0, json.dumps({"quotas": [
            {"metric": "C4A_CPUS", "limit": 72.0, "usage": 0.0},
            {"metric": "CPUS", "limit": 100.0, "usage": 0.0}]})),
        ("compute", "project-info", "describe"): (0, json.dumps({"quotas": [
            {"metric": "CPUS_ALL_REGIONS", "limit": 72.0, "usage": 0.0}]})),
        ("beta", "compute", "instances"): (0, "... --preemption-notice-duration ..."),
        ("storage", "buckets", "describe"): (0, json.dumps(
            {"location": "US-CENTRAL1", "soft_delete_policy": {"retentionDurationSeconds": "0"}})),
    }


def run_check(s, answers):
    def runner(args):
        for k, (rc, text) in answers.items():
            if tuple(args[:len(k)]) == k:
                return rc, text, ""
        return 1, "", "not found"

    out = []
    ctx = control.Ctx(s, gce.Gcloud(s.PROJECT, runner=runner), None, out=out.append)
    return control.check(ctx), "\n".join(out)


def test_check_on_c4a_highcpu_64_with_the_phase6_sizes(tmp_path):
    tables = tmp_path / "k200"
    tables.mkdir()
    (tables / "river.abs").write_bytes(b"r" * 2_000_000)
    s = make_settings(tmp_path, MACHINE_TYPE="c4a-highcpu-64", SPOT_PRICE_PER_HOUR="1.3146",
                      STANDARD_PRICE_PER_HOUR="2.4243", TRAINER_MEMORY_GB="7.4",
                      CHECKPOINT_GB="4.9", ARTIFACTS_GB="7", DISK_SIZE_GB="80",
                      TRAINER_FILES=str(tables))
    rc, text = run_check(s, check_answers(131072))
    assert rc == 0, text
    assert "c4a-highcpu-64 exists in us-central1-a (64 vCPUs, 128 GB)" in text
    assert "ok    the trainer's 7.4 GB fits c4a-highcpu-64's 128 GB in us-central1-a" in text
    assert "ok    disk 80 GB holds 4 checkpoints of 4.9 GB, 7 GB of artifacts" in text
    assert "TRAINER_FILES: 1 file(s), 2 MB" in text
    assert "$1.3" in text and "all checks passed" in text
    # A trainer too big for the machine Google describes is a thing to fix.
    big = make_settings(tmp_path, MACHINE_TYPE="c4a-highcpu-64", TRAINER_MEMORY_GB="120")
    rc, text = run_check(big, check_answers(131072))
    assert rc == 1 and "does not fit c4a-highcpu-64 (128 GB)" in text
    assert "FIX   the trainer's 120 GB fits c4a-highcpu-64's 128 GB" in text


def test_check_reads_the_c4a_quota_as_cpus_per_vm_family(tmp_path):
    s = make_settings(tmp_path, MACHINE_TYPE="c4a-highcpu-64")
    answers = check_answers(131072)
    # As on Kevin's project: no C4A_CPUS in regions describe, only the plain CPU quotas.
    answers[("compute", "regions", "describe")] = (0, json.dumps({"quotas": [
        {"metric": "CPUS", "limit": 100.0, "usage": 0.0}]}))
    quota = {"quotaId": "CPUS-PER-VM-FAMILY-per-project-region",
             "metric": "compute.googleapis.com/cpus_per_vm_family",
             "dimensionsInfos": [{"dimensions": {"region": "us-central1", "vm_family": "C4A"},
                                  "details": {"value": "64"}}]}
    answers[("beta", "quotas", "info", "describe")] = (0, json.dumps(quota))
    rc, text = run_check(s, answers)
    assert rc == 0, text
    assert "ok    C4A CPU quota (CPUs per VM family) in us-central1 is 64, room for 64" in text
    # Too small is a thing to fix.
    quota["dimensionsInfos"][0]["details"]["value"] = "32"
    answers[("beta", "quotas", "info", "describe")] = (0, json.dumps(quota))
    rc, text = run_check(s, answers)
    assert rc == 1 and "FIX   C4A CPU quota (CPUs per VM family) in us-central1 is 32" in text
    # describe fails, list has it.
    del answers[("beta", "quotas", "info", "describe")]
    quota["dimensionsInfos"][0]["details"]["value"] = "72"
    answers[("beta", "quotas", "info", "list")] = (0, json.dumps([quota]))
    rc, text = run_check(s, answers)
    assert rc == 0 and "is 72, room for 64" in text
    # The API off or another format: the "?" line naming the quota, and no failure.
    answers[("beta", "quotas", "info", "list")] = (1, "")
    rc, text = run_check(s, answers)
    assert rc == 0, text
    assert '?     couldn\'t read the C4A CPU quota: on the Quotas page it is "CPUs per VM ' \
           'family", vm_family C4A, region us-central1' in text
    answers[("beta", "quotas", "info", "list")] = (0, "not json")
    rc, text = run_check(s, answers)
    assert rc == 0 and "couldn't read the C4A CPU quota" in text


def test_artifacts_lists_and_downloads(tmp_path):
    ctx, _fake, out = make_ctx(tmp_path)
    assert control.artifacts(ctx) == 1 and "no artifacts" in out[-1]
    ctx.store.put_bytes("artifacts/strategy-1000000.bps", b"a" * 3000)
    ctx.store.put_bytes("artifacts/strategy-2000000.bps", b"b" * 3000)
    ctx.store.put_bytes("artifacts/stages.jsonl", b'{"iterations": 1000000}\n')
    out.clear()
    assert control.artifacts(ctx) == 0
    assert "3 artifact(s)" in out[0] and any("strategy-2000000.bps" in x for x in out)
    dest = tmp_path / "got"
    assert control.artifacts(ctx, download=str(dest), only="strategy-*") == 0
    assert sorted(os.listdir(dest)) == ["strategy-1000000.bps", "strategy-2000000.bps"]
    assert "downloaded 2" in out[-1]
    ctx.store.put_bytes("artifacts/strategy-4000000.bps", b"c" * 3000)
    ctx.store.put_bytes("artifacts/stages.jsonl", b'{"iterations": 1000000}\n{"x": 1}\n')
    assert control.artifacts(ctx, download=str(dest)) == 0
    assert "downloaded 2" in out[-1] and "(2 were there already)" in out[-1]
    assert (dest / "stages.jsonl").read_text().count("\n") == 2
    assert not [n for n in os.listdir(dest) if n.endswith(".part")]


# --- whole simulated runs ------------------------------------------------------------------------

def simulation(tmp_path, iterations=400):
    """The trainer holds halfway while tmp_path/hold exists (fake_trainer.py, hold_at), so a
    test's preemption always comes halfway, however fast the machine. preempt_halfway()
    removes the file once the first machine has stopped."""
    store_dir = str(tmp_path / "bucket" / "runs" / "hu-test")
    fake_cfg = str(tmp_path / "fake.json")
    hold = tmp_path / "hold"
    hold.write_text("")
    with open(fake_cfg, "w") as f:
        json.dump({"iterations": iterations, "iteration_seconds": 0.01,
                   "checkpoint_seconds": 0.3, "checkpoint_bytes": 16384,
                   "hold_at": iterations // 2, "hold_file": str(hold)}, f)
    fake = FakeCompute(store_dir=store_dir, root=str(tmp_path), fake_cfg=fake_cfg)
    ctx, fake, out = make_ctx(tmp_path, fake=fake, BUDGET_USD="100")
    write_json(ctx.store, BUNDLE + "manifest.json", {"version": "v1"})
    return ctx, fake, out


def preempt_halfway(ctx, fake, tmp_path, iterations, name="ps-hu-test"):
    """Waits until the trainer is halfway with a checkpoint in the bucket, then Google takes
    the machine (preempt waits for its processes to exit) and the hold is lifted."""
    local_test.wait_for(
        lambda: ((read_json(ctx.store, STATUS) or {}).get("progress", {}).get("iterations") or 0)
        >= iterations // 2 and remote_checkpoints(ctx.store), 60, "halfway")
    fake.preempt(name)
    (tmp_path / "hold").unlink()


def check_finished(ctx, disk_dirs, iterations):
    events = []
    for d in disk_dirs:
        events += local_test.trainer_events(d)
    saved = [e for e in events if e.get("event") == "saved on SIGTERM"]
    resumed = [e for e in events if e.get("event") == "resumed"]
    done = [e for e in events if e.get("event") == "done"]
    assert saved and resumed and done
    assert resumed[0]["iterations"] == saved[0]["iterations"]
    assert done[-1]["digest"] == fake_trainer.expected_digest(iterations)
    assert read_json(ctx.store, STATE)["state"] == "done"
    assert len(remote_checkpoints(ctx.store)) == 3


def test_simulated_preemption_restarts_the_same_machine(tmp_path):
    ctx, fake, out = simulation(tmp_path)
    try:
        control.create_machine(ctx, 0.0, "v1")
        preempt_halfway(ctx, fake, tmp_path, 400)
        assert control.recover(ctx, once=True) == 0, out      # sees the preemption, starts
        assert fake.verbs()[-1] == "start"
        fake.wait_stopped("ps-hu-test")                       # the run finishes, powers off
        assert control.recover(ctx, once=True) == 0           # finished: nothing to do
        assert "finished" in out[-1]
        check_finished(ctx, [str(tmp_path / "disk-1")], 400)
        ev = read_json(ctx.store, RESTARTS)["events"]
        assert [e["action"] for e in ev] == ["start"]
    finally:
        fake.kill_all()


def test_simulated_preemption_with_the_machine_deleted_makes_a_new_one(tmp_path):
    ctx, fake, out = simulation(tmp_path)
    try:
        control.create_machine(ctx, 0.0, "v1")
        preempt_halfway(ctx, fake, tmp_path, 400)
        del fake.instances["ps-hu-test"]                      # termination action DELETE
        assert control.recover(ctx, once=True) == 0, out
        assert fake.verbs()[-1] == "create"
        assert fake.disks["ps-hu-test"] == "disk-2"           # an empty disk
        fake.wait_stopped("ps-hu-test")
        check_finished(ctx, [str(tmp_path / "disk-1"), str(tmp_path / "disk-2")], 400)
        st = read_json(ctx.store, STATUS)
        assert st["checkpoints"]["restored_from"]             # it came from the bucket
        assert st["cost"]["sessions"] == 2
    finally:
        fake.kill_all()
