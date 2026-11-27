#!/usr/bin/env python3
"""The supervisor: runs the trainer on the cloud machine and keeps its checkpoints safe.

systemd starts it at every boot (see vm/startup.sh). It:

1. records this boot as a session in the bucket (start time, prices), for the cost estimate;
2. stops at once if the budget is spent or a stop was requested;
3. downloads the newest checkpoint from the bucket if it is newer than anything on the disk;
4. runs ``<trainer> --config <file> --checkpoint-dir <dir> [--resume]``, with ``--resume``
   whenever a checkpoint is on the disk;
5. copies every new checkpoint to the bucket as soon as it is written, and keeps the last 3 there;
6. writes ``status.json`` to the bucket every minute: progress, iterations per second, memory,
   checkpoints, cost so far;
7. stops the trainer with SIGTERM (it saves, then exits) when Google gives notice of preemption,
   when the budget is reached, or when ``python -m tools.cloud stop`` asks for it;
8. restarts the trainer with ``--resume`` if it crashes, up to a limit;
9. writes the run's final state (done, failed, budget, stopped) and powers the machine off.

Standard library only, Python 3.9 or later: this one file is copied to the machine as it is.
The bucket is reached through the gcloud CLI, or is a local folder in the tests.

    python3 supervisor.py --run-config run.json

The trainer contract (README.md, "The trainer"): exit 0 only when training is finished; on
SIGTERM, save a checkpoint and exit; write checkpoints atomically (a temporary name, then a
rename) as files matching ``checkpoint_pattern``; optionally print progress lines on stdout,
each a JSON object with an ``iterations`` field.
"""
from __future__ import annotations

import argparse
import collections
import fnmatch
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

FORMAT = 1

# Object names under the run's prefix in the bucket (gs://<bucket>/runs/<run>/...).
STATUS = "status.json"
STATE = "state.json"
STOP_MARKER = "control/stop"
RESTARTS = "restarts.json"
LAUNCH = "launch.json"
SESSIONS = "sessions/"
CHECKPOINTS = "checkpoints/"
LOGS = "logs/"
BUNDLE = "bundle/"

FINAL_STATES = ("done", "failed", "budget", "stopped")

DEFAULTS = {
    "run": None,
    "store": None,
    "gcloud": ["gcloud"],
    "trainer": None,
    "trainer_args": [],
    "config": None,
    "checkpoint_dir": None,
    "work_dir": None,
    "staging_dir": None,
    "checkpoint_pattern": "*.ckpt",
    "keep_checkpoints": 3,
    "settle_seconds": 2.0,
    "scan_seconds": 1.0,
    "status_seconds": 60.0,
    "control_seconds": 15.0,
    "preempt_poll_seconds": 2.0,
    "budget_usd": None,
    "budget_margin_seconds": 900.0,
    "machine_per_hour": None,
    "ip_per_hour": 0.0,
    "disk_per_hour": 0.0,
    "session_tail_seconds": None,
    "max_trainer_crashes": 3,
    "crash_backoff_seconds": 30.0,
    "stop_grace_seconds": 600.0,
    "final_upload_seconds": 600.0,
    "power_off": [],
    "power_off_when_done": True,
    "power_off_on_failure": True,
    "power_off_on_budget": True,
    "power_off_on_stop": True,
    "power_off_after_preemption": True,
    "gce_metadata": False,
    "session_from_boot": False,
    "log_tail_bytes": 1_000_000,
    "rate_window_seconds": 600.0,
    "instance": None,
    "zone": None,
    "machine_type": None,
    "provisioning": None,
}

# Instance metadata attributes set by `python -m tools.cloud launch` (they override run.json, so
# a restarted or recreated machine carries its own prices, and `resume` can raise the budget).
METADATA_OVERRIDES = {
    "pscloud-budget-usd": "budget_usd",
    "pscloud-machine-per-hour": "machine_per_hour",
    "pscloud-ip-per-hour": "ip_per_hour",
    "pscloud-disk-per-hour": "disk_per_hour",
    "pscloud-provisioning": "provisioning",
}


# --- time --------------------------------------------------------------------------------------

def utc_stamp(t: float) -> str:
    """20261126T153000Z: whole seconds, sortable, no dashes (checkpoint object names)."""
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(int(t)))


def parse_stamp(s: str) -> float:
    import calendar
    return float(calendar.timegm(time.strptime(s, "%Y%m%dT%H%M%SZ")))


def iso(t: float | None) -> str | None:
    if t is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


# --- the bucket ----------------------------------------------------------------------------------

class StoreError(Exception):
    pass


class LocalStore:
    """A local folder standing in for the bucket (tests, `python -m tools.cloud local-test`)."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def __repr__(self):
        return f"LocalStore({self.root})"

    def url(self, name: str) -> str:
        return os.path.join(self.root, *name.split("/"))

    def _atomic_write(self, name: str, writer) -> None:
        path = self.url(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            writer(tmp)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def put_bytes(self, name: str, data: bytes) -> None:
        def w(tmp):
            with open(tmp, "wb") as f:
                f.write(data)
        self._atomic_write(name, w)

    def put_file(self, name: str, path: str) -> None:
        self._atomic_write(name, lambda tmp: shutil.copyfile(path, tmp))

    def get_bytes(self, name: str) -> bytes | None:
        try:
            with open(self.url(name), "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def get_file(self, name: str, dest: str) -> None:
        src = self.url(name)
        if not os.path.isfile(src):
            raise StoreError(f"not in the bucket: {name}")
        shutil.copyfile(src, dest)

    def list(self, prefix: str) -> list[tuple[str, int]]:
        """Objects whose name starts with ``prefix`` (a folder ending in /), with sizes."""
        base = self.url(prefix.rstrip("/"))
        out = []
        if not os.path.isdir(base):
            return out
        for dirpath, _dirs, files in os.walk(base):
            for fn in files:
                if fn.endswith(".tmp"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, self.root).replace(os.sep, "/")
                try:
                    out.append((rel, os.path.getsize(full)))
                except FileNotFoundError:
                    pass
        return sorted(out)

    def delete(self, name: str) -> None:
        try:
            os.unlink(self.url(name))
        except FileNotFoundError:
            pass


_NOT_FOUND = re.compile(r"matched no objects|no urls matched|not found|404|does not exist",
                        re.IGNORECASE)


class GcsStore:
    """A Cloud Storage prefix (gs://bucket/runs/<run>) through the gcloud CLI."""

    def __init__(self, base_url: str, gcloud=("gcloud",), timeout: float = 3600.0):
        if not base_url.startswith("gs://"):
            raise ValueError(f"not a gs:// URL: {base_url}")
        self.base = base_url.rstrip("/")
        self.gcloud = list(gcloud)
        self.timeout = timeout

    def __repr__(self):
        return f"GcsStore({self.base})"

    def url(self, name: str) -> str:
        return f"{self.base}/{name}"

    def _run(self, args, data: bytes | None = None, timeout: float | None = None):
        env = dict(os.environ, CLOUDSDK_CORE_DISABLE_PROMPTS="1")
        try:
            return subprocess.run(self.gcloud + ["storage"] + list(args), input=data,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                  timeout=timeout or self.timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise StoreError(f"gcloud storage {args[0]}: {e}") from e

    @staticmethod
    def _err(p) -> str:
        return (p.stderr or b"").decode("utf-8", "replace").strip()

    def put_bytes(self, name: str, data: bytes) -> None:
        p = self._run(["cp", "-", self.url(name)], data=data, timeout=300)
        if p.returncode:
            raise StoreError(f"upload {name}: {self._err(p)}")

    def put_file(self, name: str, path: str) -> None:
        size = os.path.getsize(path)
        p = self._run(["cp", path, self.url(name)])
        if p.returncode:
            raise StoreError(f"upload {name}: {self._err(p)}")
        # gcloud checks the hash of every upload; the size check catches a wrong object name.
        listed = dict(self.list(name))
        if listed.get(name) != size:
            raise StoreError(f"upload {name}: the bucket has {listed.get(name)} bytes, "
                             f"the file {size}")

    def get_bytes(self, name: str) -> bytes | None:
        p = self._run(["cat", self.url(name)], timeout=300)
        if p.returncode:
            if _NOT_FOUND.search(self._err(p)):
                return None
            raise StoreError(f"read {name}: {self._err(p)}")
        return p.stdout

    def get_file(self, name: str, dest: str) -> None:
        p = self._run(["cp", self.url(name), dest])
        if p.returncode:
            raise StoreError(f"download {name}: {self._err(p)}")

    def list(self, prefix: str) -> list[tuple[str, int]]:
        p = self._run(["ls", "-l", self.url(prefix)], timeout=300)
        if p.returncode:
            if _NOT_FOUND.search(self._err(p)):
                return []
            raise StoreError(f"list {prefix}: {self._err(p)}")
        return parse_ls_long(p.stdout.decode("utf-8", "replace"), self.base + "/")

    def delete(self, name: str) -> None:
        p = self._run(["rm", self.url(name)], timeout=300)
        if p.returncode and not _NOT_FOUND.search(self._err(p)):
            raise StoreError(f"delete {name}: {self._err(p)}")


def parse_ls_long(text: str, base: str) -> list[tuple[str, int]]:
    """Parse ``gcloud storage ls -l`` output: "  <size>  <time>  gs://...". Folders and the
    TOTAL line are skipped. Names are returned relative to ``base``."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit() and parts[-1].startswith("gs://"):
            url = parts[-1]
            if url.startswith(base) and not url.endswith("/"):
                out.append((url[len(base):], int(parts[0])))
    return sorted(out)


def make_store(url: str, gcloud=("gcloud",)):
    if url.startswith("gs://"):
        return GcsStore(url, gcloud=gcloud)
    return LocalStore(url)


def read_json(store, name: str):
    data = store.get_bytes(name)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def write_json(store, name: str, obj) -> None:
    store.put_bytes(name, (json.dumps(obj, indent=1, sort_keys=True) + "\n").encode("utf-8"))


# --- checkpoints -------------------------------------------------------------------------------

_CKPT = re.compile(r"^(\d{8})-(\d{8}T\d{6}Z)-(.+)$")


def checkpoint_object(seq: int, mtime: float, name: str) -> str:
    """checkpoints/00000042-20261126T153000Z-blueprint.ckpt: a sequence number (newest is
    highest, across restarts), the file's modification time, and its name on the disk."""
    return f"{CHECKPOINTS}{seq:08d}-{utc_stamp(mtime)}-{name}"


class RemoteCheckpoint(collections.namedtuple("RemoteCheckpoint",
                                              "object seq written_at name size")):
    pass


def parse_checkpoint_object(obj: str, size: int = 0) -> RemoteCheckpoint | None:
    if not obj.startswith(CHECKPOINTS):
        return None
    m = _CKPT.match(obj[len(CHECKPOINTS):])
    if not m:
        return None
    try:
        written = parse_stamp(m.group(2))
    except ValueError:
        return None
    return RemoteCheckpoint(obj, int(m.group(1)), written, m.group(3), size)


def remote_checkpoints(store) -> list[RemoteCheckpoint]:
    out = []
    for obj, size in store.list(CHECKPOINTS):
        c = parse_checkpoint_object(obj, size)
        if c is not None:
            out.append(c)
    return sorted(out, key=lambda c: c.seq)


def is_temporary(name: str) -> bool:
    return name.startswith(".") or name.endswith((".tmp", ".part", ".partial", ".download"))


def local_checkpoints(ckdir: str, pattern: str) -> list[tuple[str, os.stat_result]]:
    """Finished checkpoint files in the trainer's folder: matching ``pattern``, not temporary."""
    out = []
    try:
        entries = list(os.scandir(ckdir))
    except FileNotFoundError:
        return out
    for e in entries:
        if is_temporary(e.name) or not fnmatch.fnmatch(e.name, pattern):
            continue
        try:
            if e.is_file(follow_symlinks=False):
                out.append((e.name, e.stat(follow_symlinks=False)))
        except FileNotFoundError:
            pass
    return sorted(out, key=lambda x: (x[1].st_mtime, x[0]))


def plan_restore(local: list[tuple[str, float]], remote: list[RemoteCheckpoint]):
    """The bucket checkpoint to download before the trainer starts, or None.

    ``local`` is (name, mtime) of the checkpoints on the disk. The newest one in the bucket is
    downloaded only if it is newer (by whole seconds) than every checkpoint on the disk. A disk
    checkpoint that is newer than the bucket's (a save the 30-second window cut off) stays and is
    uploaded as soon as the supervisor runs.
    """
    if not remote:
        return None
    newest = max(remote, key=lambda c: c.seq)
    newest_local = max((int(m) for _n, m in local), default=None)
    if newest_local is None or int(newest.written_at) > newest_local:
        return newest
    return None


def retention(remote: list[RemoteCheckpoint], keep: int) -> list[RemoteCheckpoint]:
    """The bucket checkpoints to delete: all but the newest ``keep``."""
    ordered = sorted(remote, key=lambda c: c.seq, reverse=True)
    return ordered[max(1, keep):]


# --- cost ----------------------------------------------------------------------------------------

def session_rate(s: dict) -> float:
    return float(s.get("machine_per_hour") or 0.0) + float(s.get("ip_per_hour") or 0.0)


def session_end(s: dict, now: float | None, tail: float) -> float:
    """A live session runs to ``now``; a closed one to its last report plus ``tail`` (the minute
    or so between the last report and the power-off that no report covers)."""
    if now is not None:
        return now
    return float(s["last_seen_at"]) + tail


def run_cost(sessions: list[dict], now: float, live_id: str | None = None,
             tail: float = 120.0, disk_per_hour: float = 0.0, disk_to_now: bool = True) -> dict:
    """Estimated cost of a run: each session's hours times its machine and IP prices, plus the
    disk from the first session's start (it exists while the machine is stopped too)."""
    machine = ip = hours = 0.0
    first = None
    last_end = None
    for s in sessions:
        start = float(s["started_at"])
        end = session_end(s, now if s.get("session") == live_id else None, tail)
        h = max(0.0, end - start) / 3600.0
        hours += h
        machine += h * float(s.get("machine_per_hour") or 0.0)
        ip += h * float(s.get("ip_per_hour") or 0.0)
        first = start if first is None else min(first, start)
        last_end = end if last_end is None else max(last_end, end)
    disk = 0.0
    if first is not None and disk_per_hour:
        disk_end = now if disk_to_now else last_end
        disk = max(0.0, disk_end - first) / 3600.0 * disk_per_hour
    return {"machine_usd": machine, "ip_usd": ip, "disk_usd": disk,
            "total_usd": machine + ip + disk, "machine_hours": hours,
            "sessions": len(sessions)}


# --- the machine ---------------------------------------------------------------------------------

class GceMetadata:
    """The metadata server (only reachable on the cloud machine)."""

    BASE = "http://metadata.google.internal/computeMetadata/v1/"

    def __init__(self, base: str | None = None):
        self.base = base or self.BASE

    def get(self, path: str, timeout: float = 2.0) -> str | None:
        req = urllib.request.Request(self.base + path, headers={"Metadata-Flavor": "Google"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def attributes(self) -> dict:
        raw = self.get("instance/attributes/?recursive=true")
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    def preempted(self) -> bool:
        return (self.get("instance/preempted", timeout=1.0) or "").strip().upper() == "TRUE"

    def instance_info(self) -> dict:
        def last(v):
            return v.rsplit("/", 1)[-1] if v else None
        return {"instance": self.get("instance/name"),
                "zone": last(self.get("instance/zone")),
                "machine_type": last(self.get("instance/machine-type"))}


def boot_session() -> tuple[str | None, float | None]:
    """(boot id, boot time) on Linux, so a supervisor restarted within one boot continues the
    same session and the minutes before it started are counted."""
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            boot_id = f.read().strip()
        with open("/proc/uptime") as f:
            uptime = float(f.read().split()[0])
        return boot_id, time.time() - uptime
    except (OSError, ValueError, IndexError):
        return None, None


def memory_info(pid: int | None) -> dict:
    """Memory of the trainer (resident and peak) and of the machine, from /proc (Linux)."""
    out = {"trainer_rss_bytes": None, "trainer_peak_bytes": None,
           "total_bytes": None, "available_bytes": None}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                if k == "MemTotal":
                    out["total_bytes"] = int(v.split()[0]) * 1024
                elif k == "MemAvailable":
                    out["available_bytes"] = int(v.split()[0]) * 1024
    except (OSError, ValueError):
        pass
    if pid:
        try:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        out["trainer_rss_bytes"] = int(line.split()[1]) * 1024
                    elif line.startswith("VmHWM:"):
                        out["trainer_peak_bytes"] = int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            pass
    return out


# --- progress ------------------------------------------------------------------------------------

def parse_progress(line: str) -> dict | None:
    """A trainer progress line: a JSON object with a numeric ``iterations`` field."""
    line = line.strip()
    if not (line.startswith("{") and line.endswith("}")):
        return None
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    if isinstance(obj, dict) and isinstance(obj.get("iterations"), (int, float)) \
            and not isinstance(obj.get("iterations"), bool):
        return obj
    return None


class Rate:
    """Iterations per second over the last ``window`` seconds."""

    def __init__(self, window: float):
        self.window = window
        self.samples: collections.deque = collections.deque()

    def add(self, t: float, iterations: float) -> None:
        if self.samples and iterations < self.samples[-1][1]:
            self.samples.clear()            # a restart from an older checkpoint
        self.samples.append((t, iterations))
        while len(self.samples) > 2 and self.samples[1][0] < t - self.window:
            self.samples.popleft()

    def per_second(self) -> float | None:
        if len(self.samples) < 2:
            return None
        (t0, i0), (t1, i1) = self.samples[0], self.samples[-1]
        return (i1 - i0) / (t1 - t0) if t1 > t0 else None


# --- configuration -------------------------------------------------------------------------------

def load_run_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    unknown = set(raw) - set(DEFAULTS) - {"format"}
    if unknown:
        raise ValueError(f"{path}: unknown settings {sorted(unknown)}")
    cfg = dict(DEFAULTS)
    cfg.update(raw)
    return cfg


def check_run_config(cfg: dict) -> None:
    for key in ("run", "store", "trainer", "checkpoint_dir", "work_dir"):
        if not cfg.get(key):
            raise ValueError(f"run config: {key} is missing")
    if not isinstance(cfg["trainer"], list):
        raise ValueError("run config: trainer must be a list (the command)")
    budget = cfg.get("budget_usd")
    if budget is None or float(budget) <= 0:
        raise ValueError("run config: budget_usd must be above 0 (the hard cap)")
    if cfg.get("machine_per_hour") is None or float(cfg["machine_per_hour"]) < 0:
        raise ValueError("run config: machine_per_hour is missing")
    if int(cfg["keep_checkpoints"]) < 1:
        raise ValueError("run config: keep_checkpoints must be at least 1")


# --- the supervisor ------------------------------------------------------------------------------

class Supervisor:
    def __init__(self, cfg: dict, store=None, metadata: GceMetadata | None = None,
                 clock=time.time):
        self.cfg = dict(cfg)
        self.clock = clock
        self.metadata = metadata
        if self.metadata is None and self.cfg.get("gce_metadata"):
            self.metadata = GceMetadata()
        if self.metadata is not None:
            self._apply_metadata()
        check_run_config(self.cfg)
        self.store = store or make_store(self.cfg["store"], gcloud=self.cfg["gcloud"])
        self.ckdir = os.path.abspath(self.cfg["checkpoint_dir"])
        self.work = os.path.abspath(self.cfg["work_dir"])
        self.staging = os.path.abspath(self.cfg.get("staging_dir") or os.path.join(
            os.path.dirname(self.ckdir.rstrip(os.sep)), ".pscloud-staging"))
        self.logdir = os.path.join(self.work, "logs")
        for d in (self.ckdir, self.work, self.staging, self.logdir):
            os.makedirs(d, exist_ok=True)
        self.tail = float(self.cfg["session_tail_seconds"]
                          if self.cfg["session_tail_seconds"] is not None
                          else float(self.cfg["status_seconds"]) + 60.0)
        self.lock = threading.RLock()
        self.stop_reason: str | None = None      # shutdown, preempted, budget, stopped
        self.user_stop = False
        self.preempted = False
        self.proc: subprocess.Popen | None = None
        self.trainer = {"state": "starting", "pid": None, "started_at": None, "resumed": None,
                        "exit_code": None, "crashes": 0, "runs": 0}
        self.progress: dict = {}
        self.progress_at: float | None = None
        self.rate = Rate(float(self.cfg["rate_window_seconds"]))
        self.ckpt = {"last_written_at": None, "last_written_name": None,
                     "last_written_bytes": None, "last_uploaded_at": None,
                     "last_uploaded_object": None, "uploads": 0, "upload_failures": 0,
                     "last_error": None, "restored_from": None, "in_bucket": None}
        self.closed_sessions: list[dict] = []
        self.session: dict = {}
        self.outcome: str | None = None
        self.detail: str | None = None
        self._quit = threading.Event()
        self._uploaded: dict[str, tuple] = {}
        self._next_seq = 1
        self.upload_lock = threading.Lock()
        self._next_preempt_poll = 0.0
        self.sup_log_path = os.path.join(self.logdir, "supervisor.log")
        self.trainer_log_path = None

    # --- small helpers ---

    def log(self, msg: str) -> None:
        line = f"{iso(self.clock())} {msg}"
        print(line, file=sys.stderr, flush=True)
        try:
            with open(self.sup_log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def _apply_metadata(self) -> None:
        attrs = self.metadata.attributes()
        for attr, key in METADATA_OVERRIDES.items():
            if attr in attrs and attrs[attr] != "":
                v = attrs[attr]
                self.cfg[key] = v if key == "provisioning" else float(v)
        info = self.metadata.instance_info()
        for k, v in info.items():
            if v and not self.cfg.get(k):
                self.cfg[k] = v

    def _rates(self) -> float:
        return float(self.cfg["machine_per_hour"]) + float(self.cfg["ip_per_hour"] or 0) \
            + float(self.cfg["disk_per_hour"] or 0)

    def cost(self, now: float | None = None) -> dict:
        now = self.clock() if now is None else now
        sessions = self.closed_sessions + ([self.session] if self.session else [])
        c = run_cost(sessions, now, live_id=self.session.get("session"), tail=self.tail,
                     disk_per_hour=float(self.cfg["disk_per_hour"] or 0))
        c["budget_usd"] = float(self.cfg["budget_usd"])
        c["price_per_hour"] = self._rates()
        return c

    def budget_reached(self, now: float | None = None) -> bool:
        margin = self._rates() * float(self.cfg["budget_margin_seconds"]) / 3600.0
        return self.cost(now)["total_usd"] >= float(self.cfg["budget_usd"]) - margin

    def request_stop(self, reason: str) -> None:
        with self.lock:
            if self.stop_reason is None:
                self.stop_reason = reason
                self.log(f"stop requested: {reason}")
            elif self.stop_reason == "shutdown" and reason == "preempted":
                self.stop_reason = "preempted"
            proc = self.proc
        if proc is not None and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGTERM)
            except OSError:
                pass

    def _on_signal(self, signum, _frame) -> None:
        # SIGTERM from systemd (shutdown, preemption, `systemctl stop`) or Ctrl-C.
        self.request_stop("shutdown")

    # --- sessions ---

    def _load_sessions(self) -> None:
        boot_id, boot_time = (boot_session() if self.cfg.get("session_from_boot")
                              else (None, None))
        sid = self.session.get("session") or boot_id or uuid.uuid4().hex
        own = None
        self.closed_sessions = []
        for obj, _size in self.store.list(SESSIONS):
            s = read_json(self.store, obj)
            if not isinstance(s, dict) or "started_at" not in s:
                continue
            if s.get("session") == sid:
                own = s
            else:
                self.closed_sessions.append(s)
        now = self.clock()
        if own is None:
            own = {"session": sid, "run": self.cfg["run"], "started_at": boot_time or now,
                   "instance": self.cfg.get("instance") or socket.gethostname(),
                   "zone": self.cfg.get("zone"), "machine_type": self.cfg.get("machine_type"),
                   "provisioning": self.cfg.get("provisioning")}
        own.update({"last_seen_at": now,
                    "machine_per_hour": float(self.cfg["machine_per_hour"]),
                    "ip_per_hour": float(self.cfg["ip_per_hour"] or 0)})
        self.session = own
        self.log(f"session {sid}: {len(self.closed_sessions)} earlier session(s) in the bucket")

    def _write_session(self) -> None:
        with self.lock:
            self.session["last_seen_at"] = self.clock()
            s = dict(self.session)
        write_json(self.store, f"{SESSIONS}{s['session']}.json", s)

    # --- status ---

    def status(self) -> dict:
        now = self.clock()
        with self.lock:
            prog = dict(self.progress)
            st = {
                "format": FORMAT,
                "run": self.cfg["run"],
                "session": self.session.get("session"),
                "instance": self.session.get("instance"),
                "zone": self.session.get("zone"),
                "machine_type": self.session.get("machine_type"),
                "provisioning": self.session.get("provisioning"),
                "updated_at": now,
                "session_started_at": self.session.get("started_at"),
                "supervisor_pid": os.getpid(),
                "trainer": dict(self.trainer),
                "progress": {
                    "iterations": prog.get("iterations"),
                    "target_iterations": prog.get("target_iterations"),
                    "iterations_per_second": self.rate.per_second(),
                    "updated_at": self.progress_at,
                    "line": prog,
                },
                "memory": memory_info(self.trainer.get("pid")
                                      if self.trainer.get("state") == "running" else None),
                "checkpoints": dict(self.ckpt),
                "cost": self.cost(now),
                "stop_reason": self.stop_reason,
                "outcome": self.outcome,
            }
        return st

    def write_status(self) -> None:
        try:
            write_json(self.store, STATUS, self.status())
            self._write_session()
        except StoreError as e:
            self.log(f"status not written: {e}")

    def upload_logs(self) -> None:
        sid = self.session.get("session")
        for path, suffix in ((self.trainer_log_path, "trainer"),
                             (self.sup_log_path, "supervisor")):
            if not path or not os.path.exists(path):
                continue
            try:
                size = os.path.getsize(path)
                with open(path, "rb") as f:
                    f.seek(max(0, size - int(self.cfg["log_tail_bytes"])))
                    data = f.read()
                self.store.put_bytes(f"{LOGS}{sid}-{suffix}.log", data)
            except (OSError, StoreError) as e:
                self.log(f"log not uploaded: {e}")

    def write_state(self, state: str, detail: str) -> None:
        obj = {"state": state, "at": self.clock(), "detail": detail,
               "session": self.session.get("session")}
        try:
            write_json(self.store, STATE, obj)
        except StoreError as e:
            self.log(f"state not written: {e}")

    # --- checkpoints ---

    def _init_checkpoints(self) -> None:
        """Restore the newest bucket checkpoint if it is newer than the disk's, and note which
        disk files are already in the bucket."""
        remote = remote_checkpoints(self.store)
        self._next_seq = (max(c.seq for c in remote) + 1) if remote else 1
        local = local_checkpoints(self.ckdir, self.cfg["checkpoint_pattern"])
        pick = plan_restore([(n, st.st_mtime) for n, st in local], remote)
        if pick is not None:
            dest = os.path.join(self.ckdir, pick.name)
            tmp = os.path.join(self.ckdir, f".{pick.name}.download")
            self.log(f"restoring {pick.object} ({pick.size} bytes) from the bucket")
            self.store.get_file(pick.object, tmp)
            if pick.size and os.path.getsize(tmp) != pick.size:
                os.unlink(tmp)
                raise StoreError(f"download of {pick.object} has the wrong size")
            os.utime(tmp, (pick.written_at, pick.written_at))
            os.replace(tmp, dest)
            self.ckpt["restored_from"] = pick.object
            local = local_checkpoints(self.ckdir, self.cfg["checkpoint_pattern"])
        elif local:
            self.log(f"the disk has the newest checkpoint ({local[-1][0]})")
        for name, st in local:
            if any(c.name == name and int(c.written_at) == int(st.st_mtime) for c in remote):
                self._uploaded[name] = (st.st_ino, st.st_mtime_ns, st.st_size)
        if local:
            name, st = local[-1]
            self.ckpt.update(last_written_at=st.st_mtime, last_written_name=name,
                             last_written_bytes=st.st_size)
        self.ckpt["in_bucket"] = len(remote)
        for f in os.listdir(self.staging):
            try:
                os.unlink(os.path.join(self.staging, f))
            except OSError:
                pass

    def has_local_checkpoint(self) -> bool:
        return bool(local_checkpoints(self.ckdir, self.cfg["checkpoint_pattern"]))

    def pending_checkpoints(self, settle: bool = True) -> list[tuple[str, os.stat_result]]:
        now = time.time()
        out = []
        for name, st in local_checkpoints(self.ckdir, self.cfg["checkpoint_pattern"]):
            if self._uploaded.get(name) == (st.st_ino, st.st_mtime_ns, st.st_size):
                continue
            if settle and now - st.st_mtime < float(self.cfg["settle_seconds"]):
                continue
            out.append((name, st))
        return out

    def upload_one(self, name: str, st: os.stat_result) -> bool:
        """Upload one version of a checkpoint file, then delete all but the newest few."""
        with self.upload_lock:
            return self._upload_one(name, st)

    def _upload_one(self, name: str, st: os.stat_result) -> bool:
        src = os.path.join(self.ckdir, name)
        staged = os.path.join(self.staging, f"{name}.{os.getpid()}")
        try:
            if os.path.exists(staged):
                os.unlink(staged)
            before = os.stat(src)
            try:
                os.link(src, staged)       # pins this version: the trainer may rename over src
                linked = True
            except OSError:
                shutil.copy2(src, staged)  # another file system: copy, then check src held still
                linked = False
            sst = os.stat(staged)
            if linked:
                key = (sst.st_ino, sst.st_mtime_ns, sst.st_size)
            else:
                after = os.stat(src)
                same = (before.st_ino, before.st_mtime_ns, before.st_size) == \
                    (after.st_ino, after.st_mtime_ns, after.st_size)
                key = (after.st_ino, after.st_mtime_ns, after.st_size) if same else None
        except FileNotFoundError:
            return False
        try:
            obj = checkpoint_object(self._next_seq, sst.st_mtime, name)
            t0 = time.time()
            self.store.put_file(obj, staged)
            self._next_seq += 1
            if key is not None:
                self._uploaded[name] = key
            with self.lock:
                self.ckpt.update(last_uploaded_at=self.clock(), last_uploaded_object=obj,
                                 uploads=self.ckpt["uploads"] + 1, last_error=None)
            self.log(f"uploaded {obj} ({sst.st_size} bytes, {time.time() - t0:.1f} s)")
        except (StoreError, OSError) as e:
            with self.lock:
                self.ckpt["upload_failures"] += 1
                self.ckpt["last_error"] = str(e)[-500:]
            self.log(f"upload of {name} failed: {e}")
            return False
        finally:
            try:
                os.unlink(staged)
            except OSError:
                pass
        self.prune()
        return True

    def prune(self) -> None:
        """Delete all but the newest ``keep_checkpoints`` in the bucket (after an upload, so the
        bucket never holds fewer). A failure here is retried after the next upload."""
        try:
            remote = remote_checkpoints(self.store)
            for c in retention(remote, int(self.cfg["keep_checkpoints"])):
                self.store.delete(c.object)
            with self.lock:
                self.ckpt["in_bucket"] = min(len(remote), int(self.cfg["keep_checkpoints"]))
        except StoreError as e:
            self.log(f"old checkpoints not deleted yet: {e}")

    def note_written(self) -> None:
        local = local_checkpoints(self.ckdir, self.cfg["checkpoint_pattern"])
        if local:
            name, st = local[-1]
            with self.lock:
                self.ckpt.update(last_written_at=st.st_mtime, last_written_name=name,
                                 last_written_bytes=st.st_size)

    def _uploader(self) -> None:
        backoff = 0.0
        while not self._quit.is_set():
            self.note_written()
            pending = self.pending_checkpoints()
            if pending:
                name, st = pending[0]
                if self.upload_one(name, st):
                    backoff = 0.0
                    continue
                backoff = min(60.0, max(5.0, backoff * 2))
                self._quit.wait(backoff)
                continue
            self._quit.wait(float(self.cfg["scan_seconds"]))

    def flush_checkpoints(self, deadline: float) -> None:
        """After the trainer exits: upload whatever is new, retrying until the deadline."""
        attempt = 0
        while time.time() < deadline:
            self.note_written()
            pending = self.pending_checkpoints(settle=False)
            if not pending:
                return
            name, st = pending[0]
            if not self.upload_one(name, st):
                attempt += 1
                time.sleep(min(10.0, 1.0 * attempt))
        if self.pending_checkpoints(settle=False):
            self.log("final upload not finished before the deadline; the disk keeps it")

    # --- the reporter thread ---

    def _reporter(self) -> None:
        now = time.time()
        next_status = now
        next_control = now
        while not self._quit.is_set():
            now = time.time()
            if now >= next_status:
                self.write_status()
                self.upload_logs()
                next_status = now + float(self.cfg["status_seconds"])
            if now >= next_control:
                try:
                    if self.store.get_bytes(STOP_MARKER) is not None:
                        self.user_stop = True
                except StoreError as e:
                    self.log(f"stop marker not read: {e}")
                next_control = now + float(self.cfg["control_seconds"])
            self._quit.wait(0.5)

    # --- the trainer ---

    def trainer_command(self, resume: bool) -> list[str]:
        cmd = list(self.cfg["trainer"])
        if self.cfg.get("config"):
            cmd += ["--config", self.cfg["config"]]
        cmd += ["--checkpoint-dir", self.ckdir]
        if resume:
            cmd.append("--resume")
        return cmd + list(self.cfg.get("trainer_args") or [])

    def _read_output(self, proc, log_path: str) -> None:
        with open(log_path, "ab") as log:
            for raw in iter(proc.stdout.readline, b""):
                log.write(raw)
                log.flush()
                p = parse_progress(raw.decode("utf-8", "replace"))
                if p is not None:
                    t = self.clock()
                    with self.lock:
                        self.progress = p
                        self.progress_at = t
                        self.rate.add(t, float(p["iterations"]))

    def _check_triggers(self) -> None:
        if self.stop_reason is not None:
            return
        # The preemption notice is polled here, not in the reporter thread, whose bucket
        # writes can take seconds. The metadata server is local and answers in milliseconds.
        now = time.time()
        if self.metadata is not None and now >= self._next_preempt_poll:
            self._next_preempt_poll = now + float(self.cfg["preempt_poll_seconds"])
            if self.metadata.preempted():
                self.preempted = True
        if self.preempted:
            self.request_stop("preempted")
        elif self.user_stop:
            self.request_stop("stopped")
        elif self.budget_reached():
            self.request_stop("budget")

    def run_trainer(self, resume: bool) -> int:
        cmd = self.trainer_command(resume)
        self.trainer_log_path = os.path.join(self.logdir,
                                             f"trainer-{self.session['session']}.log")
        self.log(f"starting the trainer: {' '.join(cmd)}")
        env = dict(os.environ, PYTHONUNBUFFERED="1", PSCLOUD_RUN=str(self.cfg["run"]),
                   PSCLOUD_SESSION=str(self.session["session"]))
        with self.lock:
            if self.stop_reason is not None:
                return -1
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                             cwd=self.work, env=env)
            except OSError as e:
                self.log(f"the trainer did not start: {e}")
                self.trainer.update(state="exited", exit_code=127)
                return 127
            self.trainer.update(state="running", pid=self.proc.pid, started_at=self.clock(),
                                resumed=resume, exit_code=None,
                                runs=self.trainer["runs"] + 1)
        reader = threading.Thread(target=self._read_output, args=(self.proc, self.trainer_log_path),
                                  daemon=True)
        reader.start()
        signalled_at = None
        while True:
            rc = self.proc.poll()
            if rc is not None:
                break
            self._check_triggers()
            if self.stop_reason is not None:
                if signalled_at is None:
                    signalled_at = time.time()
                    try:
                        self.proc.send_signal(signal.SIGTERM)
                    except OSError:
                        pass
                elif time.time() - signalled_at > float(self.cfg["stop_grace_seconds"]):
                    self.log("the trainer did not stop in time: killing it")
                    self.proc.kill()
            time.sleep(0.2)
        reader.join(timeout=10)
        with self.lock:
            self.trainer.update(state="exited", exit_code=rc)
            self.proc = None
        self.log(f"the trainer exited with code {rc}")
        return rc

    # --- the whole run ---

    def _retry(self, fn, what: str, seconds: float = 600.0) -> None:
        """Bucket calls at boot: the network can take a moment. Give up after ``seconds``
        (the supervisor then exits with an error and systemd restarts it)."""
        end = time.time() + seconds
        wait = 2.0
        while True:
            try:
                return fn()
            except StoreError as e:
                if time.time() + wait > end or self.stop_reason is not None:
                    raise
                self.log(f"could not {what}, retrying in {wait:.0f} s: {e}")
                time.sleep(wait)
                wait = min(60.0, wait * 2)

    def power_off(self, why: str) -> None:
        cmd = self.cfg.get("power_off") or []
        if not cmd:
            self.log(f"not powering off ({why}): no power_off command set")
            return
        self.log(f"powering off: {why}")
        try:
            subprocess.run(cmd, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.log(f"power off failed: {e}")

    def run(self, install_signals: bool = True) -> int:
        if install_signals:
            signal.signal(signal.SIGTERM, self._on_signal)
            signal.signal(signal.SIGINT, self._on_signal)
        self.log(f"supervisor for run {self.cfg['run']}, bucket {self.store}")
        self._retry(self._load_sessions, "read the sessions")
        self.write_status()
        if self.budget_reached():
            c = self.cost()
            return self._finish("budget", f"budget spent before the trainer started "
                                          f"(${c['total_usd']:.2f} of ${c['budget_usd']:.2f})")
        if self.store.get_bytes(STOP_MARKER) is not None:
            return self._finish("stopped", "a stop was requested (python -m tools.cloud resume "
                                           "clears it)")
        self._retry(self._init_checkpoints, "check the checkpoints")
        threads = [threading.Thread(target=self._uploader, daemon=True),
                   threading.Thread(target=self._reporter, daemon=True)]
        for t in threads:
            t.start()
        crashes = 0
        outcome = None
        detail = None
        while self.stop_reason is None:
            rc = self.run_trainer(self.has_local_checkpoint())
            if self.stop_reason is not None:
                break
            if rc == 0:
                outcome, detail = "done", "the trainer finished"
                break
            crashes += 1
            with self.lock:
                self.trainer["crashes"] = crashes
            if crashes > int(self.cfg["max_trainer_crashes"]):
                outcome = "failed"
                detail = f"the trainer crashed {crashes} times (last exit code {rc})"
                break
            self.log(f"trainer crash {crashes} of at most {self.cfg['max_trainer_crashes']}: "
                     f"restarting in {self.cfg['crash_backoff_seconds']} s")
            end = time.time() + float(self.cfg["crash_backoff_seconds"])
            while time.time() < end and self.stop_reason is None:
                self._check_triggers()
                time.sleep(0.2)
        # Stop the threads, then upload what is new. The status goes first: it says why the
        # machine stopped, which the recovery loop needs, and it is small.
        self._quit.set()
        for t in threads:
            t.join(timeout=float(self.cfg["final_upload_seconds"]))
        if self.stop_reason == "shutdown" and self.metadata is not None \
                and self.metadata.preempted():
            self.stop_reason = "preempted"
        self.outcome = outcome
        self.write_status()
        self.flush_checkpoints(time.time() + float(self.cfg["final_upload_seconds"]))
        if outcome is not None:
            return self._finish(outcome, detail)
        reason = self.stop_reason
        if reason == "budget":
            c = self.cost()
            return self._finish("budget", f"estimated cost ${c['total_usd']:.2f} reached the "
                                          f"cap ${c['budget_usd']:.2f}")
        if reason == "stopped":
            return self._finish("stopped", "stop requested")
        # shutdown or preempted: not a final state. The next start resumes.
        self._close()
        if reason == "preempted" and self.cfg.get("power_off_after_preemption"):
            self.power_off("preempted: saved, powering off before Google does")
        return 0

    def _close(self) -> None:
        self.write_status()
        self.upload_logs()

    def _finish(self, state: str, detail: str) -> int:
        self.outcome = state
        self.detail = detail
        self.log(f"run {state}: {detail}")
        self.write_state(state, detail)
        self._close()
        flag = {"done": "power_off_when_done", "failed": "power_off_on_failure",
                "budget": "power_off_on_budget", "stopped": "power_off_on_stop"}[state]
        if self.cfg.get(flag):
            self.power_off(f"run {state}")
        return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-config", required=True, help="run.json written by launch")
    args = ap.parse_args(argv)
    cfg = load_run_config(args.run_config)
    return Supervisor(cfg).run()


if __name__ == "__main__":
    sys.exit(main())
