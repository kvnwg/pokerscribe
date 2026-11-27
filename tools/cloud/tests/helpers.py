"""Shared pieces for the tools/cloud tests: settings without a file, and a fake Compute Engine
that answers the gcloud commands the tools send (in memory, nothing leaves the computer)."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time

from tools.cloud import local_test, settings

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE_GCLOUD = os.path.join(HERE, "fake_gcloud.py")

BASE_ENV = {
    "PROJECT": "test-project",
    "BUCKET": "test-bucket",
    "RUN_NAME": "hu-test",
    "SPOT_PRICE_PER_HOUR": "2.0461",
    "STANDARD_PRICE_PER_HOUR": "3.7722",
    "BUDGET_USD": "40",
    "TRAINER_MODE": "copy",
}


def make_settings(tmp_path, **over) -> settings.Settings:
    """Settings from PSCLOUD_* variables only; a trainer and its config are made in tmp_path."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    trainer = tmp_path / "trainer.py"
    if not trainer.exists():
        trainer.write_text("#!/usr/bin/env python3\nprint('hi')\n")
    cfg = tmp_path / "train.json"
    if not cfg.exists():
        cfg.write_text('{"iterations": 10}\n')
    env = dict(BASE_ENV, TRAINER_PATH=str(trainer), TRAINER_CONFIG=str(cfg))
    env.update({k: str(v) for k, v in over.items()})
    environ = {settings.ENV_PREFIX + k: v for k, v in env.items()}
    return settings.load(str(tmp_path / "no-such-settings.env"), environ=environ)


def iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000-00:00", time.gmtime(t))


class FakeCompute:
    """Answers gcloud compute (and a few storage bucket) commands from memory.

    ``fail`` maps a command word (create, start) to a list of stderr texts; each call of that
    command pops one and fails with it. With ``supervisors`` (a bucket folder), creating or
    starting a machine runs the real supervisor and the fake trainer on a folder standing in
    for the machine's disk, and the machine stops when the supervisor exits.
    """

    def __init__(self, store_dir: str | None = None, root: str | None = None,
                 fake_cfg: str | None = None):
        self.calls: list[list[str]] = []
        self.instances: dict[str, dict] = {}
        self.operations: list[dict] = []
        self.fail: dict[str, list[str]] = {}
        self.buckets: dict[str, dict] = {}
        self.metadata: dict[str, dict] = {}
        self.store_dir = store_dir
        self.root = root
        self.fake_cfg = fake_cfg
        self.procs: dict[str, subprocess.Popen] = {}
        self.disks: dict[str, str] = {}
        self.disk_count = 0

    # --- the machines ---

    def add(self, name, zone="us-central1-a", status="RUNNING", started=None):
        self.instances[name] = {
            "name": name, "zone": f"https://compute/projects/p/zones/{zone}", "status": status,
            "machineType": f"https://compute/zones/{zone}/machineTypes/c4a-highmem-64",
            "scheduling": {"provisioningModel": "SPOT"},
            "creationTimestamp": iso(started or time.time()),
            "lastStartTimestamp": iso(started or time.time()),
            "labels": {"pscloud-run": "hu-test"}, "id": "1"}

    def status(self, name):
        self.poll()
        return self.instances[name]["status"] if name in self.instances else None

    def poll(self):
        for name, p in list(self.procs.items()):
            if p.poll() is not None:
                del self.procs[name]
                if name in self.instances:
                    self.instances[name]["status"] = "TERMINATED"
                    self.instances[name]["lastStopTimestamp"] = iso(time.time())

    def _boot(self, name):
        if self.store_dir is None:
            return
        disk = self.disks[name]
        run_json = local_test.run_config(self.root, disk, self.store_dir, self.fake_cfg,
                                         instance=name)
        log = os.path.join(self.root, f"{disk}.supervisor.out")
        self.procs[name] = local_test.start_supervisor(run_json, log)

    def preempt(self, name, timeout=60):
        """Google takes the machine back: SIGTERM to everything, then it is stopped."""
        p = self.procs.get(name)
        if p is not None:
            os.killpg(p.pid, signal.SIGTERM)
            p.wait(timeout=timeout)
        self.poll()
        inst = self.instances[name]
        inst["status"] = "TERMINATED"
        self.operations.append({"operationType": "compute.instances.preempted",
                                "targetLink": f"https://compute/zones/x/instances/{name}",
                                "insertTime": iso(time.time())})

    def wait_stopped(self, name, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            if self.status(name) in ("TERMINATED", None):
                return
            time.sleep(0.05)
        raise TimeoutError(f"{name} did not stop")

    def kill_all(self):
        for p in self.procs.values():
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass

    # --- gcloud ---

    def __call__(self, args, stdin=None):
        self.calls.append(list(args))
        self.poll()
        a = [x for x in args if x != "beta"]
        flags = {}
        for x in a:
            if x.startswith("--") and "=" in x:
                k, v = x[2:].split("=", 1)
                flags[k] = v
        if a[:3] == ["compute", "instances", "list"]:
            want = flags.get("filter", "").replace("name=", "")
            rows = [i for n, i in self.instances.items() if not want or n == want]
            return 0, json.dumps(rows), ""
        if a[:2] == ["compute", "instances"]:
            verb, name = a[2], a[3]
            if self.fail.get(verb):
                return 1, "", self.fail[verb].pop(0)
            if verb == "create":
                zone = flags["zone"]
                self.add(name, zone=zone)
                self.metadata[name] = dict(kv.split("=", 1) for kv in flags["metadata"].split(","))
                self.disk_count += 1
                self.disks[name] = f"disk-{self.disk_count}"
                self._boot(name)
                return 0, "[]", ""
            if name not in self.instances:
                return 1, "", f"ERROR: The resource 'projects/p/zones/z/instances/{name}' was not found"
            inst = self.instances[name]
            if verb == "start":
                inst["status"] = "RUNNING"
                inst["lastStartTimestamp"] = iso(time.time())
                self._boot(name)
            elif verb == "stop":
                p = self.procs.get(name)
                if p is not None:
                    os.killpg(p.pid, signal.SIGTERM)
                    p.wait(timeout=60)
                    self.poll()
                inst["status"] = "TERMINATED"
            elif verb == "delete":
                del self.instances[name]
                self.disks.pop(name, None)
            elif verb == "add-metadata":
                self.metadata.setdefault(name, {}).update(
                    dict(kv.split("=", 1) for kv in flags["metadata"].split(",")))
            elif verb == "set-scheduling":
                inst["scheduling"]["maxRunDuration"] = flags.get("max-run-duration")
            return 0, "", ""
        if a[:3] == ["compute", "operations", "list"]:
            return 0, json.dumps(self.operations), ""
        if a[:3] == ["storage", "buckets", "describe"]:
            b = self.buckets.get(a[3])
            return (0, json.dumps(b), "") if b else (1, "", "ERROR: 404 bucket not found")
        if a[:3] == ["storage", "buckets", "create"]:
            self.buckets[a[3]] = {"name": a[3], "location": flags.get("location", "").upper()}
            return 0, "", ""
        if a[:2] == ["compute", "disks"] or a[:2] == ["compute", "addresses"] or \
                a[:2] == ["compute", "snapshots"] or a[:2] == ["compute", "images"] or \
                a[:2] == ["compute", "machine-images"] or a[:3] == ["storage", "buckets", "list"]:
            return 0, "[]", ""
        return 1, "", f"FakeCompute: not implemented: {' '.join(args)}"

    def verbs(self):
        """The compute instances verbs called, in order."""
        out = []
        for c in self.calls:
            a = [x for x in c if x != "beta"]
            if a[:2] == ["compute", "instances"] and a[2] != "list":
                out.append(a[2])
        return out


def python():
    return sys.executable
