"""vm/startup.sh, run for real in a sandbox: every path under a temporary root, a folder for the
metadata server, the fake gcloud for the bucket, and stubs for systemctl, apt-get and cargo
that write down how they were called."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from tools.cloud import control

from .helpers import FAKE_GCLOUD, make_settings

STARTUP = control.STARTUP_SCRIPT


def stub(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


class Sandbox:
    def __init__(self, tmp_path, s, machine="root"):
        self.tmp = tmp_path
        self.s = s
        self.root = tmp_path / machine
        self.gcs = tmp_path / "gcs"
        self.meta = tmp_path / "meta"
        self.bin = tmp_path / "bin"
        for d in (self.gcs, self.meta, self.bin):
            d.mkdir(exist_ok=True)
        stub(self.bin / "gcloud", f'exec "{sys.executable}" "{FAKE_GCLOUD}" "$@"\n')
        stub(self.bin / "systemctl", f'echo "$@" >> "{tmp_path}/systemctl.log"\n')
        stub(self.bin / "apt-get", f'echo "$@" >> "{tmp_path}/apt.log"\n')
        stub(self.bin / "cargo", f'''echo "$PWD $@" >> "{tmp_path}/cargo.log"
bin=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--bin" ]; then bin="$2"; fi
  shift
done
mkdir -p target/release
printf '#!/bin/sh\\necho built trainer\\n' > "target/release/$bin"
chmod +x "target/release/$bin"
''')
        self.bucket = self.gcs / "test-bucket" / "runs" / s.RUN_NAME

    def publish(self, version=None):
        """Build the bundle and put it where launch would: the bucket and the metadata."""
        folder = self.tmp / "bundle-src"
        if folder.exists():
            shutil.rmtree(folder)
        m = control.build_bundle(self.s, str(folder))
        dest = self.bucket / "bundle"
        dest.mkdir(parents=True, exist_ok=True)
        for f in m["files"] + ["manifest.json"]:
            (dest / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(folder / f, dest / f)
        (self.meta / "pscloud-store").write_text(self.s.store_url)
        (self.meta / "pscloud-bundle-version").write_text(version or m["version"])
        return m

    def run(self):
        env = dict(os.environ, PSCLOUD_ROOT=str(self.root),
                   PSCLOUD_METADATA_URL=f"file://{self.meta}/",
                   PSCLOUD_POWEROFF="systemctl poweroff", PSCLOUD_RETRY_WAIT="0",
                   FAKE_GCS_ROOT=str(self.gcs), PATH=f"{self.bin}:{os.environ['PATH']}")
        return subprocess.run(["bash", STARTUP], env=env, capture_output=True, text=True,
                              timeout=120)

    def log(self, name):
        p = self.tmp / name
        return p.read_text().splitlines() if p.exists() else []

    def gcloud_calls(self):
        return self.log("gcs/calls.log")


def test_startup_script_parses():
    assert subprocess.run(["bash", "-n", STARTUP]).returncode == 0


def test_first_and_second_boot_copy_mode(tmp_path):
    s = make_settings(tmp_path)
    box = Sandbox(tmp_path, s)
    m = box.publish()
    p = box.run()
    assert p.returncode == 0, p.stderr
    opt = box.root / "opt" / "pscloud"
    for f in ("supervisor.py", "run.json", "config/train.json", "trainer"):
        assert (opt / "bundle" / f).is_file(), f
    assert os.access(opt / "bundle" / "trainer", os.X_OK)
    assert (opt / "installed-version").read_text().strip() == m["version"]
    assert json.loads((opt / "bundle" / "run.json").read_text())["run"] == "hu-test"
    unit = (box.root / "etc" / "systemd" / "system" / "pscloud-trainer.service").read_text()
    assert ("ExecStart=/usr/bin/python3 /opt/pscloud/bundle/supervisor.py --run-config "
            "/opt/pscloud/bundle/run.json") in unit
    assert "KillMode=control-group" in unit and "Restart=on-failure" in unit
    assert f"TimeoutStopSec={m['stop_timeout_seconds']}" in unit
    assert "OnFailure=pscloud-on-failure.service" in unit and "WantedBy=multi-user.target" in unit
    assert (box.root / "etc" / "systemd" / "system" / "pscloud-on-failure.service").exists()
    onfail = (opt / "on-failure.sh").read_text()
    assert "STORE=gs://test-bucket/runs/hu-test" in onfail and "systemctl poweroff" in onfail
    assert subprocess.run(["bash", "-n", str(opt / "on-failure.sh")]).returncode == 0
    assert box.log("systemctl.log") == ["daemon-reload", "enable pscloud-trainer.service",
                                        "start --no-block pscloud-trainer.service"]
    # A second boot of the same machine: nothing is downloaded again.
    downloads = len(box.gcloud_calls())
    p = box.run()
    assert p.returncode == 0, p.stderr
    assert len(box.gcloud_calls()) == downloads
    assert box.log("systemctl.log")[-1] == "start --no-block pscloud-trainer.service"


def test_trainer_files_are_installed_under_bundle_files(tmp_path):
    tables = tmp_path / "k200"
    tables.mkdir()
    (tables / "river.abs").write_bytes(b"r" * 5000)
    (tables / "turn.abs").write_bytes(b"t" * 50)
    s = make_settings(tmp_path, TRAINER_FILES=str(tables))
    box = Sandbox(tmp_path, s)
    m = box.publish()
    assert m["extra_files"] == ["files/k200/river.abs", "files/k200/turn.abs"]
    p = box.run()
    assert p.returncode == 0, p.stderr
    got = box.root / "opt" / "pscloud" / "bundle" / "files" / "k200"
    assert (got / "river.abs").read_bytes() == b"r" * 5000
    assert (got / "turn.abs").read_bytes() == b"t" * 50
    assert not list(got.glob("*.part"))
    assert "installed 2 trainer file(s)" in p.stderr


def test_build_mode_builds_once_per_run(tmp_path):
    eng = tmp_path / "engine"
    (eng / "crates" / "trainer" / "src").mkdir(parents=True)
    (eng / "Cargo.toml").write_text("[workspace]\nmembers = [\"crates/*\"]\n")
    (eng / "crates" / "trainer" / "src" / "main.rs").write_text("fn main() {}\n")
    s = make_settings(tmp_path, TRAINER_MODE="build", TRAINER_CARGO_BIN="blueprint-train",
                      TRAINER_CARGO_PACKAGE="trainer", ENGINE_DIR=str(eng))
    box = Sandbox(tmp_path, s, machine="machine-1")
    m = box.publish()
    p = box.run()
    assert p.returncode == 0, p.stderr
    cargo = box.log("cargo.log")
    assert len(cargo) == 1 and cargo[0].endswith(
        "engine build --release --bin blueprint-train -p trainer")
    trainer = box.root / "opt" / "pscloud" / "bundle" / "trainer"
    assert "built trainer" in trainer.read_text()
    built = box.bucket / "bundle" / f"trainer-built-{m['version']}"
    assert built.read_text() == trainer.read_text()            # saved for the next machine
    # A new machine of the same run downloads the build instead of building.
    box2 = Sandbox(tmp_path, s, machine="machine-2")
    p = box2.run()
    assert p.returncode == 0, p.stderr
    assert len(box2.log("cargo.log")) == 1
    assert "built trainer" in (box2.root / "opt" / "pscloud" / "bundle" / "trainer").read_text()


def test_failed_setup_marks_the_run_and_powers_off(tmp_path):
    s = make_settings(tmp_path)
    box = Sandbox(tmp_path, s)
    box.publish(version="0123456789abcdef")         # the metadata names a bundle not there
    p = box.run()
    assert p.returncode == 1
    state = json.loads((box.bucket / "state.json").read_text())
    assert state["state"] == "failed" and "launch again" in state["detail"]
    assert box.log("systemctl.log")[-1] == "poweroff"
    assert list((box.bucket / "logs").glob("startup-*.log"))
    assert not (box.root / "opt" / "pscloud" / "installed-version").exists()


def test_missing_metadata_fails_cleanly(tmp_path):
    s = make_settings(tmp_path)
    box = Sandbox(tmp_path, s)
    p = box.run()                                   # no metadata at all
    assert p.returncode == 1 and "no pscloud-store" in p.stderr
    assert box.log("systemctl.log") == ["poweroff"]
