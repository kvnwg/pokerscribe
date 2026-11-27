"""Compute Engine through the gcloud CLI: the commands, and what their output means.

Every command is built as a list by a plain function (so the tests can check them and
``--dry-run`` can print them) and run by a ``Gcloud`` object, which the tests replace.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shlex
import subprocess
import sys

RUNNING_STATES = {"PROVISIONING", "STAGING", "RUNNING", "STOPPING", "SUSPENDING", "REPAIRING",
                  "PENDING"}
STOPPED_STATES = {"TERMINATED", "STOPPED"}

LABEL = "pscloud-run"

_STOCKOUT = re.compile(r"ZONE_RESOURCE_POOL_EXHAUSTED|resource_pool_exhausted|"
                       r"does not have enough resources|STOCKOUT|not enough resources available",
                       re.IGNORECASE)
_QUOTA = re.compile(r"QUOTA_EXCEEDED|Quota '[^']+' exceeded", re.IGNORECASE)
_NOT_FOUND = re.compile(r"was not found|notFound|not found", re.IGNORECASE)


class GcloudError(Exception):
    def __init__(self, args, rc, stderr):
        self.args_ = args
        self.rc = rc
        self.stderr = stderr
        super().__init__(f"gcloud {' '.join(args[:4])} ... failed ({rc}): {stderr.strip()[-800:]}")

    @property
    def stockout(self) -> bool:
        return bool(_STOCKOUT.search(self.stderr))

    @property
    def quota(self) -> bool:
        return bool(_QUOTA.search(self.stderr))

    @property
    def not_found(self) -> bool:
        return bool(_NOT_FOUND.search(self.stderr))


def subprocess_runner(args: list[str], stdin: bytes | None = None):
    env = dict(os.environ, CLOUDSDK_CORE_DISABLE_PROMPTS="1")
    p = subprocess.run(["gcloud"] + args, input=stdin, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=env)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


class Gcloud:
    """Runs gcloud. With ``dry_run``, commands that change something are printed, not run,
    and read-only ones return "nothing there"."""

    def __init__(self, project: str, runner=None, dry_run: bool = False, echo=None):
        self.project = project
        self.runner = runner or subprocess_runner
        self.dry_run = dry_run
        self.echo = echo or (lambda s: print(s, file=sys.stderr))
        self.history: list[list[str]] = []

    def __call__(self, args: list[str], json_out: bool = False, mutating: bool = True,
                 check: bool = True, stdin: bytes | None = None):
        args = list(args)
        if "--project" not in args and not args[0] == "config" and self.project:
            args += ["--project", self.project]
        if json_out:
            args += ["--format", "json"]
        self.history.append(args)
        if self.dry_run:
            if mutating:
                self.echo("would run: gcloud " + " ".join(shlex.quote(a) for a in args))
            return ([] if json_out else "")
        rc, out, err = self.runner(args, stdin) if stdin is not None else self.runner(args)
        if rc and check:
            raise GcloudError(args, rc, err)
        if rc:
            return None
        if json_out:
            try:
                return json.loads(out or "null")
            except ValueError as e:
                raise GcloudError(args, 0, f"not JSON: {e}: {out[:200]}") from e
        return out


# --- times ---------------------------------------------------------------------------------------

def parse_time(s: str | None) -> float | None:
    """GCE timestamps: 2026-11-26T15:30:00.123-08:00 (or Z)."""
    if not s:
        return None
    s = s.strip().replace("Z", "+00:00")
    m = re.match(r"^(.*T\d\d:\d\d:\d\d)(\.\d+)?([+-]\d\d:\d\d)$", s)
    if m:
        frac = (m.group(2) or ".0")[1:7].ljust(6, "0")
        s = f"{m.group(1)}.{frac}{m.group(3)}"
    try:
        return datetime.datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def duration(seconds: int) -> str:
    """gcloud's duration format: 1d2h3m4s."""
    seconds = int(seconds)
    d, rest = divmod(seconds, 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    out = "".join(f"{v}{u}" for v, u in ((d, "d"), (h, "h"), (m, "m"), (s, "s")) if v)
    return out or "0s"


# --- instances -----------------------------------------------------------------------------------

def last_part(url: str | None) -> str | None:
    return url.rsplit("/", 1)[-1] if url else None


def summarize_instance(raw: dict) -> dict:
    sched = raw.get("scheduling") or {}
    return {
        "name": raw.get("name"),
        "zone": last_part(raw.get("zone")),
        "status": raw.get("status"),
        "machine_type": last_part(raw.get("machineType")),
        "provisioning": sched.get("provisioningModel") or "STANDARD",
        "created_at": parse_time(raw.get("creationTimestamp")),
        "last_start_at": parse_time(raw.get("lastStartTimestamp")),
        "last_stop_at": parse_time(raw.get("lastStopTimestamp")),
        "termination_at": parse_time(sched.get("terminationTime")),
        "labels": raw.get("labels") or {},
        "id": raw.get("id"),
    }


def find_instance(gcloud: Gcloud, name: str) -> dict | None:
    """The machine called ``name`` in any zone of the project, or None."""
    rows = gcloud(["compute", "instances", "list", f"--filter=name={name}"], json_out=True,
                  mutating=False) or []
    rows = [r for r in rows if r.get("name") == name]
    if not rows:
        return None
    if len(rows) > 1:
        zones = ", ".join(last_part(r.get("zone")) or "?" for r in rows)
        raise GcloudError(["compute", "instances", "list"], 0,
                          f"{len(rows)} machines are called {name} (zones {zones}): delete "
                          f"the extra ones by hand")
    return summarize_instance(rows[0])


def metadata_arg(values: dict) -> str:
    for k, v in values.items():
        if "," in str(v) or "=" in str(k):
            raise ValueError(f"metadata {k}={v}: commas are not allowed")
    return ",".join(f"{k}={v}" for k, v in values.items())


def create_command(s, zone: str, max_run_seconds: int, metadata: dict,
                   startup_script: str) -> list[str]:
    """``gcloud compute instances create`` for the settings ``s`` (tools.cloud.settings)."""
    beta = s.spot and int(s.PREEMPTION_NOTICE_SECONDS or 0) > 0
    cmd = (["beta"] if beta else []) + [
        "compute", "instances", "create", s.instance_name,
        f"--zone={zone}",
        f"--machine-type={s.MACHINE_TYPE}",
        f"--provisioning-model={'SPOT' if s.spot else 'STANDARD'}",
        # STOP keeps the disk, so a restart finds the last checkpoint even if its upload was
        # cut off. It is also what happens at the budget backstop below.
        "--instance-termination-action=STOP",
        f"--max-run-duration={duration(max_run_seconds)}",
        f"--image-family={s.IMAGE_FAMILY}",
        f"--image-project={s.IMAGE_PROJECT}",
        f"--boot-disk-size={int(s.DISK_SIZE_GB)}GB",
        f"--boot-disk-type={s.DISK_TYPE}",
        "--scopes=storage-rw",
        f"--labels={LABEL}={s.RUN_NAME}",
        f"--metadata={metadata_arg(metadata)}",
        f"--metadata-from-file=startup-script={startup_script}",
    ]
    if beta:
        cmd.append(f"--preemption-notice-duration={int(s.PREEMPTION_NOTICE_SECONDS)}s")
    if s.DISK_IOPS:
        cmd.append(f"--boot-disk-provisioned-iops={int(s.DISK_IOPS)}")
    if s.DISK_THROUGHPUT_MBPS:
        cmd.append(f"--boot-disk-provisioned-throughput={int(s.DISK_THROUGHPUT_MBPS)}")
    if s.SERVICE_ACCOUNT:
        cmd.append(f"--service-account={s.SERVICE_ACCOUNT}")
    if s.NETWORK:
        cmd.append(f"--network={s.NETWORK}")
    if s.SUBNET:
        cmd.append(f"--subnet={s.SUBNET}")
    if not s.EXTERNAL_IP:
        cmd.append("--no-address")
    return cmd


def set_max_run_command(name: str, zone: str, seconds: int) -> list[str]:
    return ["compute", "instances", "set-scheduling", name, f"--zone={zone}",
            f"--max-run-duration={duration(seconds)}", "--instance-termination-action=STOP"]


def add_metadata_command(name: str, zone: str, values: dict) -> list[str]:
    return ["compute", "instances", "add-metadata", name, f"--zone={zone}",
            f"--metadata={metadata_arg(values)}"]


def start_command(name: str, zone: str) -> list[str]:
    return ["compute", "instances", "start", name, f"--zone={zone}"]


def stop_command(name: str, zone: str) -> list[str]:
    return ["compute", "instances", "stop", name, f"--zone={zone}"]


def delete_command(name: str, zone: str) -> list[str]:
    return ["compute", "instances", "delete", name, f"--zone={zone}", "--delete-disks=all",
            "--quiet"]


def preempted_since(gcloud: Gcloud, name: str, zone: str, since: float | None) -> float | None:
    """The time of the latest preemption of this machine after ``since``, or None."""
    rows = gcloud(["compute", "operations", "list", f"--zones={zone}",
                   "--filter=operationType=compute.instances.preempted"],
                  json_out=True, mutating=False, check=False) or []
    latest = None
    for r in rows:
        if not str(r.get("targetLink", "")).endswith(f"/instances/{name}"):
            continue
        t = parse_time(r.get("insertTime") or r.get("startTime"))
        if t is None or (since is not None and t < since - 60):
            continue
        latest = t if latest is None else max(latest, t)
    return latest


# --- what is still costing money ----------------------------------------------------------------

def leftovers(gcloud: Gcloud, bucket: str | None, disk_per_gb_month: float,
              instance_name: str | None = None) -> list[dict]:
    """Everything in the project that bills while it exists. Each row: kind, name, where,
    detail, ours (made by these tools), monthly (rough USD a month, or None)."""
    rows = []

    def q(args):
        return gcloud(args, json_out=True, mutating=False, check=False) or []

    for r in q(["compute", "instances", "list"]):
        s = summarize_instance(r)
        rows.append({"kind": "machine", "name": s["name"], "where": s["zone"],
                     "detail": f"{s['status']}, {s['machine_type']}, {s['provisioning']}"
                               + (" (billed by the hour)" if s["status"] in RUNNING_STATES
                                  else " (stopped: its disks still bill)"),
                     "ours": LABEL in s["labels"], "monthly": None})
    for r in q(["compute", "disks", "list"]):
        size = float(r.get("sizeGb") or 0)
        users = [last_part(u) for u in r.get("users") or []]
        rows.append({"kind": "disk", "name": r.get("name"), "where": last_part(r.get("zone")),
                     "detail": f"{int(size)} GB {last_part(r.get('type'))}, "
                               + (f"used by {', '.join(users)}" if users else "attached to nothing"),
                     "ours": LABEL in (r.get("labels") or {}) or bool(
                         instance_name and instance_name in users),
                     "monthly": size * disk_per_gb_month})
    for r in q(["compute", "addresses", "list"]):
        rows.append({"kind": "static IP", "name": r.get("name"),
                     "where": last_part(r.get("region")) or "global",
                     "detail": r.get("status") or "", "ours": False, "monthly": None})
    for r in q(["compute", "snapshots", "list"]):
        gb = float(r.get("storageBytes") or 0) / 1e9
        rows.append({"kind": "snapshot", "name": r.get("name"), "where": "global",
                     "detail": f"{gb:.1f} GB", "ours": False, "monthly": None})
    for r in q(["compute", "images", "list", "--no-standard-images"]):
        rows.append({"kind": "image", "name": r.get("name"), "where": "global",
                     "detail": f"{r.get('diskSizeGb', '?')} GB", "ours": False, "monthly": None})
    for r in q(["compute", "machine-images", "list"]):
        rows.append({"kind": "machine image", "name": r.get("name"), "where": "global",
                     "detail": "", "ours": False, "monthly": None})
    for r in q(["storage", "buckets", "list"]):
        name = r.get("name") or last_part(r.get("storage_url", "").rstrip("/"))
        detail = r.get("location") or ""
        monthly = None
        if bucket and name == bucket:
            out = gcloud(["storage", "du", "--summarize", f"gs://{bucket}"], mutating=False,
                         check=False)
            if out:
                try:
                    gb = int(out.split()[0]) / 1e9
                    detail += f", {gb:.2f} GB stored"
                    monthly = gb * 0.02
                except (ValueError, IndexError):
                    pass
        rows.append({"kind": "bucket", "name": name, "where": detail, "detail": "",
                     "ours": bool(bucket and name == bucket), "monthly": monthly})
    return rows


# The C4A quota as the console shows it: "CPUs per VM family", vm_family C4A, per region.
VM_FAMILY_METRIC = "compute.googleapis.com/cpus_per_vm_family"
VM_FAMILY_QUOTA_ID = "CPUS-PER-VM-FAMILY-per-project-region"


def parse_vm_family_quota(info, region: str, family: str) -> dict | None:
    """The limit of the CPUs-per-VM-family quota for ``family`` in ``region``, from the Cloud
    Quotas API's QuotaInfo (``gcloud beta quotas info describe`` gives one, ``... list`` a
    list of them). Each QuotaInfo has ``metric``, ``quotaId`` and ``dimensionsInfos``: a list
    of ``{"dimensions": {"region": ..., "vm_family": ...}, "details": {"value": "64"}}``,
    where an entry with fewer dimensions is the default for the rest. The most specific entry
    that matches wins; a value of -1 means no limit. None when nothing matches or the format
    is not the one expected: the caller then says it couldn't read the quota."""
    infos = info if isinstance(info, list) else [info]
    best = None
    for q in infos:
        if not isinstance(q, dict):
            continue
        if q.get("metric") != VM_FAMILY_METRIC and \
                str(q.get("quotaId", "")).upper() != VM_FAMILY_QUOTA_ID.upper():
            continue
        for d in q.get("dimensionsInfos") or []:
            if not isinstance(d, dict):
                continue
            dims = d.get("dimensions") or {}
            if not isinstance(dims, dict):
                continue
            if "region" in dims and str(dims["region"]).lower() != region.lower():
                continue
            if "vm_family" in dims and str(dims["vm_family"]).upper() != family.upper():
                continue
            try:
                value = float((d.get("details") or {}).get("value"))
            except (TypeError, ValueError):
                continue
            rank = ("region" in dims) + 2 * ("vm_family" in dims)
            if best is None or rank > best[0]:
                best = (rank, {"limit": float("inf") if value < 0 else value,
                               "dimensions": dims, "quota_id": q.get("quotaId")})
    return best[1] if best else None


def vm_family_quota(gcloud: Gcloud, region: str, family: str) -> dict | None:
    """The CPUs-per-VM-family quota's limit through the Cloud Quotas API (needs
    cloudquotas.googleapis.com and gcloud beta), or None. Usage is not part of that API."""
    for args in (["beta", "quotas", "info", "describe", VM_FAMILY_QUOTA_ID,
                  "--service=compute.googleapis.com"],
                 ["beta", "quotas", "info", "list", "--service=compute.googleapis.com"]):
        try:
            info = gcloud(args, json_out=True, mutating=False, check=False)
        except GcloudError:      # not JSON
            continue
        if info:
            q = parse_vm_family_quota(info, region, family)
            if q is not None:
                return q
    return None


def quotas(gcloud: Gcloud, region: str) -> list[dict]:
    """The region's and the project's CPU quotas (metric, limit, usage)."""
    out = []
    reg = gcloud(["compute", "regions", "describe", region], json_out=True, mutating=False,
                 check=False) or {}
    for q in reg.get("quotas") or []:
        if "CPU" in q.get("metric", ""):
            out.append({"scope": region, **q})
    proj = gcloud(["compute", "project-info", "describe"], json_out=True, mutating=False,
                  check=False) or {}
    for q in proj.get("quotas") or []:
        if "CPU" in q.get("metric", ""):
            out.append({"scope": "project", **q})
    return out
