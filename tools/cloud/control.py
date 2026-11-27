"""The commands run from Kevin's computer: launch, watch, recover, stop, resume, cleanup,
leftovers, check, logs, artifacts. ``__main__.py`` parses the command line and calls these.

Everything goes through a ``Ctx``: the settings, a ``gce.Gcloud`` and the run's bucket prefix
(a ``supervisor.GcsStore``, or a local folder in the tests).
"""
from __future__ import annotations

import fnmatch
import gzip
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import time

from . import gce
from .gce import GcloudError
from .settings import VM_FILES, Settings, executable_kind, tracked_by_git
from .supervisor import (ARTIFACTS, BUNDLE, FINAL_STATES, LAUNCH, LOGS, RESTARTS, STATE, STATUS,
                         STOP_MARKER, GcsStore, StoreError, read_json, remote_checkpoints,
                         write_json)

HERE = os.path.dirname(os.path.abspath(__file__))
STARTUP_SCRIPT = os.path.join(HERE, "vm", "startup.sh")
SUPERVISOR = os.path.join(HERE, "supervisor.py")

VM_BUNDLE = "/opt/pscloud/bundle"
VM_WORK = "/var/lib/pscloud"
VM_CHECKPOINTS = "/var/lib/pscloud/checkpoints"

MIN_RUN_SECONDS = 600          # don't start a machine for less than 10 minutes of budget
STALE_FACTOR = 5               # no report for 5 status intervals: something is wrong


class Ctx:
    def __init__(self, s: Settings, gcloud: gce.Gcloud, store, out=print, clock=time.time,
                 sleep=time.sleep):
        self.s = s
        self.gcloud = gcloud
        self.store = store
        self.out = out
        self.clock = clock
        self.sleep = sleep


class DryStore:
    """For --dry-run: prints the uploads and reads nothing (a fresh bucket)."""

    def __init__(self, url: str, out=print):
        self.base = url
        self.out = out

    def put_bytes(self, name, data):
        self.out(f"would upload {len(data)} bytes to {self.base}/{name}")

    def put_file(self, name, path):
        self.out(f"would upload {path} ({os.path.getsize(path)} bytes) to {self.base}/{name}")

    def get_bytes(self, name):
        return None

    def get_file(self, name, dest):
        raise StoreError("dry run")

    def list(self, prefix):
        return []

    def delete(self, name):
        self.out(f"would delete {self.base}/{name}")


def make_ctx(s: Settings, dry_run: bool = False, out=print) -> Ctx:
    g = gce.Gcloud(s.PROJECT, dry_run=dry_run, echo=out)
    store = DryStore(s.store_url, out) if dry_run else GcsStore(s.store_url)
    return Ctx(s, g, store, out=out)


# --- formatting ----------------------------------------------------------------------------------

def done(ctx: Ctx, verb: str) -> str:
    """'created', or 'would have created' in a dry run."""
    return f"(dry run) would have {verb}" if ctx.gcloud.dry_run else verb


def age(seconds: float | None) -> str:
    if seconds is None:
        return "never"
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds} s"
    m = seconds // 60
    if m < 90:
        return f"{m} min"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h} h {m:02d} min"
    d, h = divmod(h, 24)
    return f"{d} d {h} h"


def gb(n: float | None) -> str:
    return "?" if n is None else f"{n / 1e9:.1f} GB"


def count(n) -> str:
    return "?" if n is None else f"{int(n):,}"


def utc(t: float | None) -> str:
    return "?" if t is None else time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))


# --- cost ----------------------------------------------------------------------------------------

def estimate_cost(status: dict | None, inst: dict | None, now: float, s: Settings) -> float:
    """Cost so far: the machine's last report, plus the time since then at the current price
    if the machine is running (or the disk alone if it is stopped)."""
    total = float(((status or {}).get("cost") or {}).get("total_usd") or 0.0)
    since = (status or {}).get("updated_at")
    if inst is None:
        return total
    if inst["status"] in gce.RUNNING_STATES:
        start = inst.get("last_start_at") or inst.get("created_at") or now
        begin = max(float(since), start) if since else start
        total += max(0.0, now - begin) / 3600.0 * s.price_per_hour
    elif since:
        total += max(0.0, now - float(since)) / 3600.0 * s.disk_price_per_hour
    return total


def run_seconds_left(cost: float, s: Settings) -> int:
    """How long the machine may run before the cap: GCE stops it then (--max-run-duration)."""
    left = float(s.BUDGET_USD) - cost
    return max(0, int(left / s.price_per_hour * 3600)) if s.price_per_hour > 0 else 0


# --- a picture of the run ------------------------------------------------------------------------

def snapshot(ctx: Ctx) -> dict:
    s = ctx.s
    now = ctx.clock()
    inst = gce.find_instance(ctx.gcloud, s.instance_name)
    status = read_json(ctx.store, STATUS)
    state = read_json(ctx.store, STATE)
    stop = ctx.store.get_bytes(STOP_MARKER) is not None
    restarts = read_json(ctx.store, RESTARTS) or {"events": []}
    ckpts = remote_checkpoints(ctx.store)
    preempted_at = None
    if inst and inst["status"] in gce.STOPPED_STATES:
        if status and status.get("stop_reason") == "preempted" and \
                float(status.get("updated_at") or 0) >= (inst.get("last_start_at") or 0):
            preempted_at = float(status["updated_at"])
        else:
            preempted_at = gce.preempted_since(ctx.gcloud, inst["name"], inst["zone"],
                                               inst.get("last_start_at"))
    return {"now": now, "instance": inst, "status": status, "state": state,
            "stop_requested": stop, "restarts": restarts, "checkpoints": ckpts,
            "preempted_at": preempted_at, "cost": estimate_cost(status, inst, now, s)}


def restarts_used(snap: dict) -> int:
    return sum(1 for e in snap["restarts"].get("events", []) if e.get("counted", True))


def decide(snap: dict, s: Settings, failed_starts: int = 0) -> tuple[str, str]:
    """What the recovery loop does next: (action, why). Actions: wait, finished, give-up,
    start, recreate, create."""
    state = (snap.get("state") or {}).get("state")
    inst = snap.get("instance")
    if state in FINAL_STATES:
        return "finished", f"the run is {state}: {(snap['state'] or {}).get('detail', '')}"
    if snap.get("stop_requested"):
        return "finished", "a stop was requested (python -m tools.cloud resume clears it)"
    if inst is not None and inst["status"] in gce.RUNNING_STATES:
        return "wait", f"machine {inst['status']}"
    if inst is not None and inst["status"] == "SUSPENDED":
        return "give-up", "the machine is suspended, which these tools never do: look at it"
    margin = float(s.BUDGET_MARGIN_MINUTES) / 60.0 * s.price_per_hour
    if snap["cost"] >= float(s.BUDGET_USD) - margin \
            or run_seconds_left(snap["cost"], s) < MIN_RUN_SECONDS:
        return "give-up", (f"the budget is spent: about ${snap['cost']:.2f} of "
                           f"${float(s.BUDGET_USD):.2f}")
    if restarts_used(snap) >= int(s.MAX_RESTARTS):
        return "give-up", f"{restarts_used(snap)} restarts used, the most MAX_RESTARTS allows"
    if inst is None:
        return "create", "the machine is gone: making a new one (the bucket has the checkpoints)"
    if inst["status"] in gce.STOPPED_STATES:
        if snap.get("preempted_at") is None and not s.RESTART_ANY_STOP:
            return "give-up", ("the machine stopped, but not by a Spot preemption and not by "
                               "these tools: not restarting it (python -m tools.cloud resume "
                               "starts it; RESTART_ANY_STOP=true restarts any stop)")
        if failed_starts >= int(s.RECREATE_AFTER_FAILED_STARTS) and len(s.zones) > 1:
            return "recreate", (f"{failed_starts} starts failed for lack of capacity: a new "
                                f"machine in another zone")
        return "start", ("preempted at " + utc(snap["preempted_at"]) if snap.get("preempted_at")
                         else "stopped")
    return "wait", f"machine {inst['status']}"


# --- the bundle ----------------------------------------------------------------------------------

def engine_tarball(engine_dir: str) -> bytes:
    """The Cargo workspace without target/: the same bytes for the same sources."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for dirpath, dirs, files in os.walk(engine_dir):
                dirs[:] = sorted(d for d in dirs if d not in ("target", ".git"))
                for fn in sorted(files):
                    if fn == ".DS_Store":
                        continue
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, engine_dir).replace(os.sep, "/")
                    info = tarfile.TarInfo("engine/" + rel)
                    info.size = os.path.getsize(full)
                    info.mode = 0o755 if os.access(full, os.X_OK) else 0o644
                    info.mtime = 0
                    with open(full, "rb") as f:
                        tar.addfile(info, f)
    return buf.getvalue()


def run_config(s: Settings) -> dict:
    """run.json for the supervisor on the machine."""
    return {
        "format": 1,
        "run": s.RUN_NAME,
        "store": s.store_url,
        "gcloud": ["gcloud"],
        "trainer": [f"{VM_BUNDLE}/trainer"],
        "trainer_args": s.trainer_args,
        "config": f"{VM_BUNDLE}/config/{os.path.basename(s.TRAINER_CONFIG)}",
        "checkpoint_dir": VM_CHECKPOINTS,
        "work_dir": VM_WORK,
        "checkpoint_pattern": s.CHECKPOINT_PATTERN,
        "keep_checkpoints": int(s.KEEP_CHECKPOINTS),
        "artifact_patterns": s.artifact_patterns,
        "status_seconds": float(s.STATUS_SECONDS),
        "control_seconds": 15.0,
        "budget_usd": float(s.BUDGET_USD),
        "budget_margin_seconds": float(s.BUDGET_MARGIN_MINUTES) * 60.0,
        "machine_per_hour": s.machine_price,
        "ip_per_hour": s.ip_price,
        "disk_per_hour": s.disk_price_per_hour,
        "max_trainer_crashes": int(s.MAX_TRAINER_CRASHES),
        "stop_grace_seconds": float(s.STOP_GRACE_SECONDS),
        "final_upload_seconds": float(s.FINAL_UPLOAD_SECONDS),
        "power_off": ["systemctl", "poweroff"],
        "power_off_when_done": bool(s.POWER_OFF_WHEN_DONE),
        "gce_metadata": True,
        "session_from_boot": True,
        "provisioning": s.PROVISIONING,
    }


def trainer_file_list(s: Settings) -> list[tuple[str, str]]:
    """(name in the bundle, local path) for every file of TRAINER_FILES: a file goes to
    files/<its name>, a folder's files to files/<folder name>/<path inside it>."""
    out = []
    for path in s.trainer_files():
        base = os.path.basename(path.rstrip(os.sep))
        if os.path.isdir(path):
            for dirpath, dirs, names in os.walk(path):
                dirs.sort()
                for fn in sorted(names):
                    if fn.startswith("."):
                        continue
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, path).replace(os.sep, "/")
                    out.append((f"files/{base}/{rel}", full))
        else:
            out.append((f"files/{base}", path))
    return out


def build_bundle(s: Settings, folder: str) -> dict:
    """Write the files the machine downloads at its first boot into ``folder``; return the
    manifest (with the bundle's version, a hash of everything in it)."""
    files = {}
    os.makedirs(os.path.join(folder, "config"), exist_ok=True)
    shutil.copyfile(SUPERVISOR, os.path.join(folder, "supervisor.py"))
    files["supervisor.py"] = "supervisor.py"
    with open(os.path.join(folder, "run.json"), "w", encoding="utf-8") as f:
        json.dump(run_config(s), f, indent=1, sort_keys=True)
    files["run.json"] = "run.json"
    cfg_name = os.path.basename(s.TRAINER_CONFIG)
    shutil.copyfile(os.path.expanduser(s.TRAINER_CONFIG), os.path.join(folder, "config", cfg_name))
    files[f"config/{cfg_name}"] = f"config/{cfg_name}"
    manifest = {"format": 1, "mode": s.TRAINER_MODE, "config_name": cfg_name,
                "stop_timeout_seconds": int(s.STOP_GRACE_SECONDS) + int(s.FINAL_UPLOAD_SECONDS)
                + 120}
    if s.TRAINER_MODE == "copy":
        shutil.copyfile(os.path.expanduser(s.TRAINER_PATH), os.path.join(folder, "trainer"))
        files["trainer"] = "trainer"
        manifest["trainer_kind"] = executable_kind(os.path.expanduser(s.TRAINER_PATH))
    else:
        eng = os.path.expanduser(s.ENGINE_DIR)
        with open(os.path.join(folder, "engine-src.tar.gz"), "wb") as f:
            f.write(engine_tarball(eng))
        files["engine-src.tar.gz"] = "engine-src.tar.gz"
        manifest.update(cargo_bin=s.TRAINER_CARGO_BIN, cargo_package=s.TRAINER_CARGO_PACKAGE or "",
                        cargo_features=s.TRAINER_CARGO_FEATURES or "",
                        rust_toolchain=s.RUST_TOOLCHAIN,
                        has_lock=os.path.exists(os.path.join(eng, "Cargo.lock")))
    extra = []
    for name, src in trainer_file_list(s):
        dest = os.path.join(folder, name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            os.link(src, dest)          # the bucket tables are 138 MB: no need to copy them
        except OSError:
            shutil.copyfile(src, dest)
        files[name] = name
        extra.append(name)
    manifest["extra_files"] = extra
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode() + b"\0")
        with open(os.path.join(folder, files[name]), "rb") as f:
            h.update(hashlib.sha256(f.read()).digest())
    h.update(json.dumps(manifest, sort_keys=True).encode())
    manifest["version"] = h.hexdigest()[:16]
    manifest["files"] = sorted(files)
    manifest["bytes"] = sum(os.path.getsize(os.path.join(folder, n)) for n in files)
    with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    return manifest


def upload_bundle(ctx: Ctx, folder: str, manifest: dict) -> None:
    for name in manifest["files"]:
        ctx.store.put_file(BUNDLE + name, os.path.join(folder, name))
    ctx.store.put_file(BUNDLE + "manifest.json", os.path.join(folder, "manifest.json"))


def instance_metadata(s: Settings, version: str) -> dict:
    return {"pscloud-run": s.RUN_NAME, "pscloud-store": s.store_url,
            "pscloud-bundle-version": version, "pscloud-budget-usd": f"{float(s.BUDGET_USD):.2f}",
            "pscloud-machine-per-hour": f"{s.machine_price:.6f}",
            "pscloud-ip-per-hour": f"{s.ip_price:.6f}",
            "pscloud-disk-per-hour": f"{s.disk_price_per_hour:.6f}",
            "pscloud-provisioning": s.PROVISIONING}


# --- making and starting machines ----------------------------------------------------------------

def record_restart(ctx: Ctx, action: str, zone: str, why: str, counted: bool = True) -> None:
    data = read_json(ctx.store, RESTARTS) or {"events": []}
    data["events"].append({"at": ctx.clock(), "action": action, "zone": zone, "why": why,
                           "counted": counted})
    write_json(ctx.store, RESTARTS, data)


def bundle_version(ctx: Ctx) -> str:
    m = read_json(ctx.store, BUNDLE + "manifest.json")
    if not m or not m.get("version"):
        raise StoreError(f"no bundle in {ctx.s.store_url}/{BUNDLE}: run launch first")
    return m["version"]


def create_machine(ctx: Ctx, cost: float, version: str, zones=None) -> str:
    """Create the machine in the first zone that has room. Returns the zone."""
    s = ctx.s
    seconds = run_seconds_left(cost, s)
    if seconds < MIN_RUN_SECONDS:
        raise RuntimeError(f"the budget left (${float(s.BUDGET_USD) - cost:.2f}) buys under "
                           f"{MIN_RUN_SECONDS // 60} minutes: raise BUDGET_USD")
    last = None
    for zone in zones or s.zones:
        cmd = gce.create_command(s, zone, seconds, instance_metadata(s, version), STARTUP_SCRIPT)
        try:
            ctx.gcloud(cmd)
            ctx.out(f"{done(ctx, 'created')} {s.instance_name} in {zone} ({s.MACHINE_TYPE}, "
                    f"{s.PROVISIONING}); GCE stops it after {gce.duration(seconds)} of running "
                    f"(the budget)")
            return zone
        except GcloudError as e:
            last = e
            if e.stockout:
                ctx.out(f"{zone}: no capacity for {s.MACHINE_TYPE} right now")
                continue
            if e.quota:
                raise RuntimeError(f"quota: {e.stderr.strip()[-400:]}\nRequest more "
                                   f"(tools/cloud/README.md, Setup step 4).") from e
            raise
    raise RuntimeError(f"no zone had capacity: {last}")


def start_machine(ctx: Ctx, inst: dict, cost: float) -> None:
    """Start a stopped machine, first giving it the current budget and its remaining run time."""
    s = ctx.s
    seconds = run_seconds_left(cost, s)
    if seconds < MIN_RUN_SECONDS:
        raise RuntimeError("the budget is spent")
    name, zone = inst["name"], inst["zone"]
    ctx.gcloud(gce.add_metadata_command(name, zone, {
        "pscloud-budget-usd": f"{float(s.BUDGET_USD):.2f}"}))
    ctx.gcloud(gce.set_max_run_command(name, zone, seconds))
    ctx.gcloud(gce.start_command(name, zone))
    ctx.out(f"{done(ctx, 'started')} {name} in {zone}; GCE stops it after "
            f"{gce.duration(seconds)} of running")


def watch_hint(s: Settings, zone: str | None = None) -> list[str]:
    z = zone or s.ZONE
    return [
        "Watch it:",
        "  python -m tools.cloud watch --every 60       # progress, speed, memory, cost",
        "  caffeinate -i python -m tools.cloud recover  # keeps it going after Spot stops",
        "  python -m tools.cloud logs                    # the trainer's output",
        "On the machine itself:",
        f"  gcloud compute instances get-serial-port-output {s.instance_name} --zone {z} "
        f"--project {s.PROJECT}",
        f"  gcloud compute ssh {s.instance_name} --zone {z} --project {s.PROJECT} -- "
        f"sudo journalctl -u pscloud-trainer -f",
        "Stop it:",
        "  python -m tools.cloud stop       # saves, keeps the disk and the bucket",
        "  python -m tools.cloud cleanup    # also deletes the machine and its disk",
    ]


# --- launch --------------------------------------------------------------------------------------

def ensure_bucket(ctx: Ctx) -> None:
    s = ctx.s
    url = f"gs://{s.BUCKET}"
    info = ctx.gcloud(["storage", "buckets", "describe", url], json_out=True, mutating=False,
                      check=False)
    if not info:
        ctx.gcloud(["storage", "buckets", "create", url, f"--location={s.REGION}",
                    "--uniform-bucket-level-access", "--public-access-prevention",
                    "--soft-delete-duration=0"])
        ctx.out(f"{done(ctx, 'created')} bucket {url} in {s.REGION} (soft delete off: deleted "
                f"checkpoints are not kept and billed for 7 days)")
        return
    loc = str(info.get("location") or "").lower()
    if loc and loc != s.REGION.lower():
        ctx.out(f"warning: bucket {url} is in {loc}, the machine in {s.REGION}: uploads are "
                f"slower and may cost network fees")
    soft = soft_delete_seconds(info)
    if soft:
        ctx.out(f"warning: bucket {url} keeps deleted objects for {soft // 86400} days (soft "
                f"delete); every replaced checkpoint stays billed that long. Turn it off: "
                f"gcloud storage buckets update {url} --clear-soft-delete")


def soft_delete_seconds(info: dict) -> int:
    for key, val in info.items():
        if "soft_delete" in key.lower() and isinstance(val, dict):
            for k, v in val.items():
                if "duration" in k.lower():
                    try:
                        return int(v)
                    except (TypeError, ValueError):
                        return 0
    return 0


def launch(ctx: Ctx, force: bool = False) -> int:
    s = ctx.s
    problems = s.problems(for_launch=True)
    if s.source and tracked_by_git(s.source):
        problems.append(f"the settings file {s.source} is inside the repo and not ignored by "
                        f"git: move it to ~/.config/pokerscribe/cloud.env")
    if problems:
        ctx.out("Fix the settings first:")
        for p in problems:
            ctx.out(f"  - {p}")
        return 2
    inst = gce.find_instance(ctx.gcloud, s.instance_name)
    if inst is not None:
        ctx.out(f"{s.instance_name} already exists ({inst['status']} in {inst['zone']}). "
                f"Use resume, recover, or cleanup.")
        return 2
    state = read_json(ctx.store, STATE)
    if state and state.get("state") == "done" and not force:
        ctx.out(f"run {s.RUN_NAME} is already done. Pick a new RUN_NAME, or --force to start a "
                f"machine on it again.")
        return 2
    status = read_json(ctx.store, STATUS)
    cost = estimate_cost(status, None, ctx.clock(), s)
    if run_seconds_left(cost, s) < MIN_RUN_SECONDS:
        ctx.out(f"run {s.RUN_NAME} has cost about ${cost:.2f} already; BUDGET_USD "
                f"${float(s.BUDGET_USD):.2f} leaves too little. Raise BUDGET_USD.")
        return 2
    ckpts = remote_checkpoints(ctx.store)
    if ckpts:
        ctx.out(f"the bucket has {len(ckpts)} checkpoint(s) for run {s.RUN_NAME}: the machine "
                f"will resume from {ckpts[-1].object}")
    if state:
        ctx.out(f"clearing the run's earlier state ({state.get('state')})")
        ctx.store.delete(STATE)
    if ctx.store.get_bytes(STOP_MARKER) is not None:
        ctx.store.delete(STOP_MARKER)
    ensure_bucket(ctx)
    with tempfile.TemporaryDirectory(prefix="pscloud-bundle-") as folder:
        manifest = build_bundle(s, folder)
        shown = [n for n in manifest["files"] if n not in manifest["extra_files"]]
        if manifest["extra_files"]:
            shown.append(f"{len(manifest['extra_files'])} trainer file(s) under files/")
        ctx.out(f"bundle {manifest['version']} ({manifest['mode']} mode, "
                f"{manifest['bytes'] / 1e6:.0f} MB): {', '.join(shown)}")
        upload_bundle(ctx, folder, manifest)
    hours = run_seconds_left(cost, s) / 3600
    ctx.out(f"price ${s.price_per_hour:.4f}/h (machine ${s.machine_price:.4f}, IP "
            f"${s.ip_price:.4f}, disk ${s.disk_price_per_hour:.4f}); cap ${float(s.BUDGET_USD):.2f} "
            f"buys about {hours:.1f} h")
    zone = create_machine(ctx, cost, manifest["version"])
    write_json(ctx.store, LAUNCH, {"at": ctx.clock(), "instance": s.instance_name, "zone": zone,
                                   "machine_type": s.MACHINE_TYPE, "provisioning": s.PROVISIONING,
                                   "price_per_hour": s.price_per_hour,
                                   "budget_usd": float(s.BUDGET_USD),
                                   "bundle": manifest["version"]})
    for line in watch_hint(s, zone):
        ctx.out(line)
    return 0


# --- watch ---------------------------------------------------------------------------------------

def format_watch(snap: dict, s: Settings) -> list[str]:
    now = snap["now"]
    inst = snap["instance"]
    st = snap["status"] or {}
    lines = [f"run         {s.RUN_NAME}   bucket {s.store_url}"]
    if inst is None:
        lines.append(f"machine     {s.instance_name}: none")
    else:
        since = inst.get("last_start_at") if inst["status"] in gce.RUNNING_STATES \
            else inst.get("last_stop_at")
        lines.append(f"machine     {inst['name']}  {inst['zone']}  {inst['machine_type']}  "
                     f"{inst['provisioning']}  {inst['status']}"
                     + (f" for {age(now - since)}" if since else ""))
    tr = st.get("trainer") or {}
    if tr:
        up = age(now - tr["started_at"]) if tr.get("started_at") else "?"
        how = "resumed" if tr.get("resumed") else "fresh start"
        if tr.get("state") == "running":
            lines.append(f"trainer     running ({how}), up {up}, crashes {tr.get('crashes', 0)}")
        else:
            lines.append(f"trainer     {tr.get('state')}, exit code {tr.get('exit_code')}, "
                         f"crashes {tr.get('crashes', 0)}")
    pr = st.get("progress") or {}
    if pr.get("iterations") is not None:
        it, target, rate = pr["iterations"], pr.get("target_iterations"), \
            pr.get("iterations_per_second")
        text = f"{count(it)} iterations"
        if target:
            text += f" of {count(target)} ({100.0 * it / target:.1f}%)"
        if rate:
            text += f", {count(rate)} per second"
            if target and target > it:
                text += f", about {age((target - it) / rate)} left"
        text += f" (reported {age(now - pr['updated_at'])} ago)" if pr.get("updated_at") else ""
        lines.append(f"progress    {text}")
    mem = st.get("memory") or {}
    tight = None
    if mem.get("total_bytes"):
        used = mem["total_bytes"] - (mem.get("available_bytes") or 0)
        t = f"machine {used / 1e9:.1f} of {gb(mem['total_bytes'])} used"
        if mem.get("trainer_rss_bytes"):
            t = f"trainer {gb(mem['trainer_rss_bytes'])} (peak {gb(mem.get('trainer_peak_bytes'))}), " + t
        lines.append(f"memory      {t}")
        peak = max(float(mem.get("trainer_peak_bytes") or 0), float(used))
        if not mem.get("trainer_rss_bytes") and mem.get("session_trainer_peak_bytes"):
            lines[-1] += f"; the trainer's peak this session {gb(mem['session_trainer_peak_bytes'])}"
        if peak > 0.9 * float(mem["total_bytes"]):
            tight = peak / float(mem["total_bytes"])
    ck = st.get("checkpoints") or {}
    remote = snap["checkpoints"]
    if ck.get("last_written_at") or remote:
        t = []
        if ck.get("last_written_at"):
            t.append(f"written {age(now - ck['last_written_at'])} ago "
                     f"({ck.get('last_written_name')}, {gb(ck.get('last_written_bytes'))})")
        if ck.get("last_uploaded_at"):
            t.append(f"uploaded {age(now - ck['last_uploaded_at'])} ago")
        t.append(f"{len(remote)} in the bucket")
        lines.append("checkpoint  " + "; ".join(t))
        if ck.get("upload_failures"):
            lines.append(f"            {ck['upload_failures']} failed upload(s), last: "
                         f"{(ck.get('last_error') or '')[:200]}")
    elif inst is not None:
        lines.append("checkpoint  none yet")
    art = st.get("artifacts") or {}
    if art.get("uploads") or art.get("in_bucket") or art.get("restored"):
        t = [f"{art.get('in_bucket', 0)} in the bucket"]
        if art.get("last_uploaded_name"):
            t.append(f"last {art['last_uploaded_name']} "
                     f"{age(now - art['last_uploaded_at'])} ago")
        if art.get("restored"):
            t.append(f"{art['restored']} put back on this machine")
        lines.append("artifacts   " + "; ".join(t)
                     + "  (python -m tools.cloud artifacts --download DIR)")
        if art.get("upload_failures"):
            lines.append(f"            {art['upload_failures']} failed upload(s), last: "
                         f"{(art.get('last_error') or '')[:200]}")
    cost = snap["cost"]
    budget = float(s.BUDGET_USD)
    c = st.get("cost") or {}
    parts = ""
    if c:
        parts = (f" (at the last report: machine ${c.get('machine_usd', 0):.2f}, IP "
                 f"${c.get('ip_usd', 0):.2f}, disk ${c.get('disk_usd', 0):.2f})")
    line = f"cost        about ${cost:.2f} so far{parts}; cap ${budget:.2f} " \
           f"({100.0 * cost / budget:.0f}%)"
    if inst is not None and inst["status"] in gce.RUNNING_STATES and s.price_per_hour > 0:
        line += f"; at ${s.price_per_hour:.2f}/h the cap is reached in " \
                f"{age((budget - cost) / s.price_per_hour * 3600)}"
    lines.append(line)
    ev = snap["restarts"].get("events", [])
    used = restarts_used(snap)
    t = f"{used} of {s.MAX_RESTARTS}"
    if ev:
        t += f" (last: {ev[-1]['action']} at {utc(ev[-1]['at'])}, {ev[-1]['why']})"
    lines.append(f"restarts    {t}")
    if snap.get("preempted_at"):
        lines.append(f"preempted   at {utc(snap['preempted_at'])}")
    if st.get("updated_at"):
        lines.append(f"report      {age(now - st['updated_at'])} ago"
                     + (f", stop reason: {st['stop_reason']}" if st.get("stop_reason") else ""))
    state = snap.get("state")
    if state:
        lines.append(f"state       {state.get('state')}: {state.get('detail')} "
                     f"({utc(state.get('at'))})")
    elif snap.get("stop_requested"):
        lines.append("state       stop requested")
    # warnings
    if tight is not None:
        lines.append(f"WARNING     memory reached {100 * tight:.0f}% of the machine: the trainer "
                     f"may be killed for lack of memory. Set TRAINER_MEMORY_GB to the trainer's "
                     f"peak and pick a machine with more (c4a-highmem-64).")
    if inst is not None and inst["status"] == "RUNNING":
        start = inst.get("last_start_at") or now
        last = st.get("updated_at")
        quiet = now - max(float(last or 0), start)
        if quiet > STALE_FACTOR * float(s.STATUS_SECONDS) + (900 if not last or last < start else 0):
            lines.append(f"WARNING     no report from the machine for {age(quiet)} while it runs "
                         f"(and bills). Look at its startup output: gcloud compute instances "
                         f"get-serial-port-output {inst['name']} --zone {inst['zone']} "
                         f"--project {s.PROJECT}; or stop it.")
    return lines


def watch(ctx: Ctx, every: float | None = None) -> int:
    while True:
        try:
            snap = snapshot(ctx)
            lines = format_watch(snap, ctx.s)
        except (GcloudError, StoreError) as e:
            lines = [f"could not read the run: {e}"]
        ctx.out("\n".join(lines))
        if not every:
            return 0
        ctx.out("")
        ctx.sleep(every)


# --- recover -------------------------------------------------------------------------------------

def recover(ctx: Ctx, once: bool = False) -> int:
    """Keep the run going: restart the machine (or make a new one) after Google stops it,
    until the run is finished, the budget is spent, or MAX_RESTARTS is used up."""
    s = ctx.s
    failed_starts = 0
    zone_index = 0
    last_line = None
    while True:
        try:
            snap = snapshot(ctx)
            action, why = decide(snap, s, failed_starts)
        except (GcloudError, StoreError) as e:
            ctx.out(f"{utc(ctx.clock())}  could not read the run (retrying): {e}")
            if once:
                return 1
            ctx.sleep(float(s.RECOVER_POLL_SECONDS))
            continue
        st = snap["status"] or {}
        pr = (st.get("progress") or {})
        line = (f"{utc(snap['now'])}  {action}: {why}; "
                f"{count(pr.get('iterations'))} iterations; ${snap['cost']:.2f} of "
                f"${float(s.BUDGET_USD):.2f}; restarts {restarts_used(snap)}/{s.MAX_RESTARTS}")
        if line != last_line or action != "wait":
            ctx.out(line)
            last_line = line
        try:
            if action == "finished":
                return 0
            if action == "give-up":
                return 1
            if action == "start":
                try:
                    start_machine(ctx, snap["instance"], snap["cost"])
                    record_restart(ctx, "start", snap["instance"]["zone"], why)
                    failed_starts = 0
                except GcloudError as e:
                    if not e.stockout:
                        raise
                    failed_starts += 1
                    ctx.out(f"  no capacity in {snap['instance']['zone']} "
                            f"({failed_starts} in a row)")
            elif action in ("recreate", "create"):
                version = bundle_version(ctx)
                if snap["instance"] is not None:
                    old = snap["instance"]
                    zone_index = (s.zones.index(old["zone"]) + 1) if old["zone"] in s.zones else 0
                    ctx.gcloud(gce.delete_command(old["name"], old["zone"]))
                    ctx.out(f"  deleted {old['name']} in {old['zone']} (its disk too)")
                zones = s.zones[zone_index:] + s.zones[:zone_index]
                zone = create_machine(ctx, snap["cost"], version, zones=zones)
                record_restart(ctx, action, zone, why)
                failed_starts = 0
        except (GcloudError, StoreError, RuntimeError) as e:
            ctx.out(f"  {action} failed: {e}")
            if once:
                return 1
        if once:
            return 0
        ctx.sleep(float(s.RECOVER_POLL_SECONDS))


# --- stop, resume, cleanup -----------------------------------------------------------------------

def stop(ctx: Ctx, timeout: float | None = None, poll: float = 10.0) -> int:
    """Ask the machine to stop: the supervisor sees the marker, the trainer saves, the last
    checkpoint is uploaded, and the machine powers itself off. Falls back to a plain GCE stop
    (which still sends SIGTERM through an ACPI shutdown) if that takes too long."""
    s = ctx.s
    write_json(ctx.store, STOP_MARKER, {"requested_at": ctx.clock()})
    ctx.out("stop requested (the recovery loop will not restart the machine)")
    inst = gce.find_instance(ctx.gcloud, s.instance_name)
    if inst is None or inst["status"] in gce.STOPPED_STATES:
        ctx.out(f"{s.instance_name}: " + ("none" if inst is None else inst["status"]))
        return print_leftovers(ctx)
    status = read_json(ctx.store, STATUS) or {}
    now = ctx.clock()
    alive = status.get("updated_at") and now - float(status["updated_at"]) < \
        3 * float(s.STATUS_SECONDS) and float(status["updated_at"]) >= (inst.get("last_start_at") or 0)
    limit = timeout if timeout is not None else (
        float(s.STOP_GRACE_SECONDS) + float(s.FINAL_UPLOAD_SECONDS) + 300 if alive else 0)
    end = ctx.clock() + limit
    if alive:
        ctx.out(f"waiting up to {age(limit)} for the trainer to save and the machine to power off")
    while ctx.clock() < end:
        inst = gce.find_instance(ctx.gcloud, s.instance_name)
        if inst is None or inst["status"] in gce.STOPPED_STATES:
            break
        ctx.sleep(poll)
    inst = gce.find_instance(ctx.gcloud, s.instance_name)
    if inst is not None and inst["status"] not in gce.STOPPED_STATES:
        ctx.out("the machine is still up: stopping it through GCE (the trainer still gets "
                "SIGTERM from the shutdown)")
        ctx.gcloud(gce.stop_command(inst["name"], inst["zone"]))
    state = read_json(ctx.store, STATE)
    ckpts = remote_checkpoints(ctx.store)
    ctx.out(f"stopped. Run state: {(state or {}).get('state', 'open')}; "
            f"{len(ckpts)} checkpoint(s) in the bucket"
            + (f", newest {ckpts[-1].object}" if ckpts else ""))
    return print_leftovers(ctx)


def resume(ctx: Ctx) -> int:
    """Clear a stop (or a spent budget, if BUDGET_USD was raised) and start the machine again,
    or make a new one if it is gone."""
    s = ctx.s
    problems = s.problems(for_launch=False)
    if problems:
        for p in problems:
            ctx.out(f"  - {p}")
        return 2
    state = read_json(ctx.store, STATE)
    if state and state.get("state") == "done":
        ctx.out("the run is done; nothing to resume")
        return 2
    ctx.store.delete(STOP_MARKER)
    if state and state.get("state") in ("stopped", "budget", "failed"):
        ctx.out(f"clearing state {state['state']}")
        ctx.store.delete(STATE)
    snap = snapshot(ctx)
    inst = snap["instance"]
    if inst is not None and inst["status"] in gce.RUNNING_STATES:
        ctx.out(f"{inst['name']} is already {inst['status']}")
        return 0
    try:
        if inst is None:
            zone = create_machine(ctx, snap["cost"], bundle_version(ctx))
            record_restart(ctx, "create", zone, "resume", counted=False)
        else:
            start_machine(ctx, inst, snap["cost"])
            zone = inst["zone"]
            record_restart(ctx, "start", zone, "resume", counted=False)
    except (GcloudError, RuntimeError, StoreError) as e:
        ctx.out(f"resume failed: {e}")
        return 1
    for line in watch_hint(s, zone):
        ctx.out(line)
    return 0


def cleanup(ctx: Ctx, yes: bool = False, ask=input) -> int:
    """Stop the run, delete the machine and its disk, keep the bucket, list what is left."""
    s = ctx.s
    inst = gce.find_instance(ctx.gcloud, s.instance_name)
    if inst is not None:
        if not yes:
            a = ask(f"Delete machine {inst['name']} ({inst['zone']}) and its disk? The bucket "
                    f"and its checkpoints are kept. [y/N] ")
            if a.strip().lower() not in ("y", "yes"):
                ctx.out("nothing deleted")
                return 1
        if inst["status"] not in gce.STOPPED_STATES:
            stop(ctx)
        else:
            write_json(ctx.store, STOP_MARKER, {"requested_at": ctx.clock()})
        ctx.gcloud(gce.delete_command(inst["name"], inst["zone"]))
        ctx.out(f"deleted {inst['name']} and its disk; kept {s.store_url}")
    else:
        ctx.out(f"{s.instance_name}: no machine")
    return print_leftovers(ctx)


def print_leftovers(ctx: Ctx) -> int:
    s = ctx.s
    rows = gce.leftovers(ctx.gcloud, s.BUCKET, float(s.DISK_PRICE_PER_GB_MONTH or 0),
                         instance_name=s.instance_name)
    if not rows:
        ctx.out(f"Nothing in project {s.PROJECT} is costing money (machines, disks, IPs, "
                f"snapshots, images, buckets).")
        return 0
    ctx.out(f"Still in project {s.PROJECT} (these cost money while they exist):")
    for r in rows:
        money = f"  about ${r['monthly']:.2f}/month" if r.get("monthly") is not None else ""
        mark = "  (this run)" if r["ours"] else ""
        ctx.out(f"  {r['kind']:<13} {r['name']:<30} {r['where'] or '':<16} {r['detail']}"
                f"{money}{mark}")
    return 0


# --- check ---------------------------------------------------------------------------------------

def check(ctx: Ctx) -> int:
    """Everything that can be checked before a paid run without spending money."""
    s = ctx.s
    bad = 0

    def ok(flag: bool, text: str, fix: str = ""):
        nonlocal bad
        if not flag:
            bad += 1
        ctx.out(("  ok    " if flag else "  FIX   ") + text + (f"\n        {fix}" if fix and
                                                              not flag else ""))

    ctx.out(f"settings: {s.source or 'no file, environment variables only'}")
    problems = s.problems(for_launch=True)
    for p in problems:
        ok(False, p)
    if not problems:
        ok(True, "settings complete")
    if s.source:
        ok(not tracked_by_git(s.source), "settings file kept out of git",
           "move it to ~/.config/pokerscribe/cloud.env")
    out = ctx.gcloud(["config", "get-value", "account"], mutating=False, check=False)
    ok(bool(out and out.strip()), "gcloud is logged in", "run: gcloud auth login")
    proj = ctx.gcloud(["projects", "describe", s.PROJECT], json_out=True, mutating=False,
                      check=False)
    ok(bool(proj), f"project {s.PROJECT} is reachable",
       "check PROJECT, and that billing is enabled for it")
    services = ctx.gcloud(["services", "list", "--enabled"], json_out=True, mutating=False,
                          check=False) or []
    names = {(x.get("config") or {}).get("name") or x.get("name", "").rsplit("/", 1)[-1]
             for x in services}
    for api in ("compute.googleapis.com", "storage.googleapis.com"):
        ok(api in names, f"{api} is enabled", f"gcloud services enable {api} --project "
                                              f"{s.PROJECT}")
    need_mem = s.TRAINER_MEMORY_GB
    for zone in s.zones:
        mt = ctx.gcloud(["compute", "machine-types", "describe", s.MACHINE_TYPE,
                         f"--zone={zone}"], json_out=True, mutating=False, check=False)
        ok(bool(mt), f"{s.MACHINE_TYPE} exists in {zone}"
           + (f" ({mt.get('guestCpus')} vCPUs, {int(mt.get('memoryMb', 0)) // 1024} GB)" if mt
              else ""), "pick another zone (ZONE, ZONES)")
        if mt and need_mem is not None and mt.get("memoryMb"):
            have = int(mt["memoryMb"]) / 1024
            ok(float(need_mem) <= 0.9 * have,
               f"the trainer's {float(need_mem):g} GB fits {s.MACHINE_TYPE}'s {have:g} GB in "
               f"{zone} with 10% to spare", "pick a machine with more memory")
    if need_mem is None:
        ctx.out("  note  TRAINER_MEMORY_GB is not set: the trainer's memory is not checked "
                "against the machine")
    disk = s.disk_needed_gb()
    if disk is not None and int(s.DISK_SIZE_GB or 0) >= disk:
        ok(True, f"disk {s.DISK_SIZE_GB} GB holds 4 checkpoints of {float(s.CHECKPOINT_GB):g} "
                 f"GB, {float(s.ARTIFACTS_GB or 0):g} GB of artifacts and the system "
                 f"({disk:g} GB)")
    files = trainer_file_list(s) if not any("TRAINER_FILES" in p for p in problems) else []
    if files:
        size = sum(os.path.getsize(p) for _, p in files)
        ctx.out(f"  note  TRAINER_FILES: {len(files)} file(s), {size / 1e6:.0f} MB, installed "
                f"under {VM_FILES}")
    need = s.vcpus() or 0
    family = (s.MACHINE_TYPE or "").split("-")[0].upper()
    qs = gce.quotas(ctx.gcloud, s.REGION)
    fam = [q for q in qs if q["metric"].startswith(family + "_")]
    for q in qs:
        if q["metric"] in ("CPUS", "CPUS_ALL_REGIONS", "PREEMPTIBLE_CPUS") or q in fam:
            ctx.out(f"        quota {q['scope']} {q['metric']}: {q.get('usage', 0):g} used of "
                    f"{q.get('limit', 0):g}")
    if fam:
        lim = max(float(q.get("limit", 0)) - float(q.get("usage", 0)) for q in fam)
        ok(lim >= need, f"{family} CPU quota in {s.REGION} has room for {need} vCPUs",
           "request it: tools/cloud/README.md, Setup step 4")
    else:
        # Google lists this quota as "CPUs per VM family" (vm_family C4A), which `regions
        # describe` may not show. The Cloud Quotas API has its limit, not its usage.
        vq = gce.vm_family_quota(ctx.gcloud, s.REGION, family)
        if vq is not None:
            ok(vq["limit"] >= need, f"{family} CPU quota (CPUs per VM family) in {s.REGION} is "
                                    f"{vq['limit']:g}, room for {need} vCPUs if no other "
                                    f"{family} machine runs (usage not read)",
               "request it: tools/cloud/README.md, Setup step 4")
        else:
            ctx.out(f"  ?     couldn't read the {family} CPU quota: on the Quotas page it is "
                    f"\"CPUs per VM family\", vm_family {family}, region {s.REGION} "
                    f"({gce.VM_FAMILY_METRIC}); it needs room for {need} (README, Setup "
                    f"step 4)")
    allreg = [q for q in qs if q["metric"] == "CPUS_ALL_REGIONS"]
    if allreg:
        q = allreg[0]
        ok(float(q.get("limit", 0)) - float(q.get("usage", 0)) >= need,
           f"CPUS_ALL_REGIONS has room for {need} vCPUs", "request it: README, Setup step 4")
    if s.spot and int(s.PREEMPTION_NOTICE_SECONDS or 0) > 0:
        out = ctx.gcloud(["beta", "compute", "instances", "create", "--help"], mutating=False,
                         check=False)
        ok(bool(out) and "preemption-notice-duration" in out,
           "gcloud beta has --preemption-notice-duration",
           "gcloud components install beta (or PREEMPTION_NOTICE_SECONDS=0)")
    info = ctx.gcloud(["storage", "buckets", "describe", f"gs://{s.BUCKET}"], json_out=True,
                      mutating=False, check=False)
    if info:
        ok(str(info.get("location", "")).lower() == s.REGION.lower(),
           f"bucket gs://{s.BUCKET} is in {s.REGION}", "use a bucket in the machine's region")
        ok(not soft_delete_seconds(info), "bucket soft delete is off",
           f"gcloud storage buckets update gs://{s.BUCKET} --clear-soft-delete")
    else:
        ctx.out(f"  note  bucket gs://{s.BUCKET} does not exist yet: launch creates it")
    if not s.problems(for_launch=False) and s.price_per_hour > 0:
        hours = float(s.BUDGET_USD) / s.price_per_hour
        ctx.out(f"  note  ${s.price_per_hour:.4f}/h: the cap ${float(s.BUDGET_USD):.2f} buys "
                f"about {hours:.1f} h of running")
    ctx.out("all checks passed" if not bad else f"{bad} thing(s) to fix")
    return 0 if not bad else 1


# --- artifacts -----------------------------------------------------------------------------------

def artifacts(ctx: Ctx, download: str | None = None, only: str | None = None) -> int:
    """List the run's artifacts in the bucket (strategy files, stages.jsonl); with ``download``,
    copy the ones not already there (same size) into that folder."""
    found = [(n[len(ARTIFACTS):], size) for n, size in ctx.store.list(ARTIFACTS)
             if not n.endswith("/")]
    if only:
        found = [(n, size) for n, size in found if fnmatch.fnmatch(n, only)]
    if not found:
        ctx.out(f"no artifacts in {ctx.s.store_url}/{ARTIFACTS}"
                + (f" matching {only}" if only else ""))
        return 1
    total = sum(size for _, size in found)
    ctx.out(f"{len(found)} artifact(s) in {ctx.s.store_url}/{ARTIFACTS}, {gb(total)}:")
    for name, size in found:
        ctx.out(f"  {name:40s} {size / 1e6:10.1f} MB")
    if not download:
        return 0
    os.makedirs(download, exist_ok=True)
    got = 0
    for name, size in found:
        dest = os.path.join(download, name)
        if os.path.exists(dest) and os.path.getsize(dest) == size and not name.endswith(".jsonl"):
            continue                # stages.jsonl grows, so it is always fetched again
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        ctx.store.get_file(ARTIFACTS + name, dest + ".part")
        os.replace(dest + ".part", dest)
        got += 1
    ctx.out(f"downloaded {got} to {download} ({len(found) - got} were there already)")
    return 0


# --- logs ----------------------------------------------------------------------------------------

def logs(ctx: Ctx, which: str = "trainer", lines: int = 60) -> int:
    st = read_json(ctx.store, STATUS) or {}
    sid = st.get("session")
    names = [n for n, _ in ctx.store.list(LOGS) if n.endswith(f"-{which}.log")]
    if not names:
        ctx.out("no logs in the bucket yet")
        return 1
    name = next((n for n in names if sid and n == f"{LOGS}{sid}-{which}.log"), names[-1])
    data = ctx.store.get_bytes(name) or b""
    ctx.out(f"== {ctx.s.store_url}/{name} (last {lines} lines)")
    for line in data.decode("utf-8", "replace").splitlines()[-lines:]:
        ctx.out(line)
    return 0
