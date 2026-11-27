"""Settings for the cloud tools: a KEY=value file kept outside the repo, plus PSCLOUD_* variables.

Where the file is, first match wins:

1. ``--settings <file>`` on the command line;
2. the ``PSCLOUD_SETTINGS`` environment variable;
3. ``~/.config/pokerscribe/cloud.env``.

Every setting can also be given as an environment variable with a ``PSCLOUD_`` prefix, which
overrides the file: ``PSCLOUD_PROJECT=my-project``. The project, the bucket and any service
account live only there, never in the repo. ``settings.example.env`` lists everything.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess

ENV_PREFIX = "PSCLOUD_"
SETTINGS_ENV = "PSCLOUD_SETTINGS"
DEFAULT_PATH = os.path.join("~", ".config", "pokerscribe", "cloud.env")
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TRUE = {"1", "true", "yes", "on"}
FALSE = {"0", "false", "no", "off", ""}

# name: (kind, default, what it is). A default of None means "no default".
SPEC = {
    # where
    "PROJECT": ("str", None, "Google Cloud project ID"),
    "BUCKET": ("str", None, "Cloud Storage bucket name, without gs://"),
    "RUN_NAME": ("str", None, "name of this training run (lowercase, digits, dashes)"),
    "REGION": ("str", "us-central1", "region of the machine and the bucket"),
    "ZONE": ("str", "us-central1-a", "zone the machine is created in"),
    "ZONES": ("list", None, "zones to try, in order, when a new machine is needed "
                            "(default: ZONE only)"),
    "INSTANCE_NAME": ("str", None, "machine name (default: ps-<RUN_NAME>)"),
    # the machine
    "MACHINE_TYPE": ("str", "c4a-highcpu-64", "machine type (c4a-highcpu-64: 64 cores, 128 "
                                              "GB; or c4a-highmem-64: the same cores, 512 GB)"),
    "PROVISIONING": ("str", "SPOT", "SPOT or STANDARD (on-demand)"),
    "PREEMPTION_NOTICE_SECONDS": ("int", 120, "Spot only: 120 asks Google for 2 minutes' notice "
                                              "before the 30-second stop (uses gcloud beta); "
                                              "0 for no notice"),
    "DISK_SIZE_GB": ("int", 200, "boot disk size; at least 4 checkpoints plus 30 GB"),
    "DISK_TYPE": ("str", "hyperdisk-balanced", "boot disk type (C4A takes Hyperdisk only)"),
    "DISK_IOPS": ("int", None, "provisioned IOPS for the boot disk (optional)"),
    "DISK_THROUGHPUT_MBPS": ("int", None, "provisioned throughput in MiB/s (optional)"),
    "IMAGE_FAMILY": ("str", "debian-12-arm64", "OS image family (must be Arm64 for C4A)"),
    "IMAGE_PROJECT": ("str", "debian-cloud", "project of the OS image"),
    "SERVICE_ACCOUNT": ("str", None, "service account for the machine (default: the "
                                     "project's default compute account)"),
    "NETWORK": ("str", None, "VPC network (default: default)"),
    "SUBNET": ("str", None, "subnet (optional)"),
    "EXTERNAL_IP": ("bool", True, "give the machine an external IP (needed to download Rust "
                                  "and crates, unless the subnet has Cloud NAT)"),
    # prices and the cap
    "SPOT_PRICE_PER_HOUR": ("float", None, "machine price per hour, Spot, USD"),
    "STANDARD_PRICE_PER_HOUR": ("float", None, "machine price per hour, on-demand, USD"),
    "IP_PRICE_PER_HOUR": ("float", 0.005, "external IPv4 address of an on-demand machine, per "
                                          "hour while running"),
    "SPOT_IP_PRICE_PER_HOUR": ("float", 0.0025, "external IPv4 address of a Spot machine, per "
                                                "hour while running"),
    "DISK_PRICE_PER_GB_MONTH": ("float", 0.08, "boot disk, per GB per month (billed while "
                                               "the disk exists, stopped or not)"),
    "DISK_IOPS_PRICE_PER_MONTH": ("float", 0.005, "Hyperdisk Balanced: each provisioned IOPS "
                                                  "above the free 3,000, per month"),
    "DISK_THROUGHPUT_PRICE_PER_MONTH": ("float", 0.04, "Hyperdisk Balanced: each provisioned "
                                                       "MiB/s above the free 140, per month"),
    "BUDGET_USD": ("float", None, "hard cap: the machine stops when the estimated cost "
                                  "reaches this"),
    "BUDGET_MARGIN_MINUTES": ("float", 15.0, "the supervisor stops the trainer this many "
                                             "minutes of running cost before the cap"),
    # recovery
    "MAX_RESTARTS": ("int", 10, "most times the recovery loop starts or recreates the machine"),
    "RECREATE_AFTER_FAILED_STARTS": ("int", 3, "failed starts (no capacity) in a row before "
                                               "a new machine is made in the next zone"),
    "RESTART_ANY_STOP": ("bool", False, "also restart after a stop that wasn't a preemption"),
    "RECOVER_POLL_SECONDS": ("int", 60, "how often the recovery loop looks"),
    "SILENT_STOP_MINUTES": ("int", 30, "the recovery loop stops a running machine that has "
                                       "sent no report this long after it started (its setup "
                                       "is stuck); 0: never"),
    # the trainer
    "TRAINER_MODE": ("str", "build", "build (cargo on the machine, from ENGINE_DIR) or copy "
                                     "(TRAINER_PATH, already built for aarch64 Linux)"),
    "TRAINER_PATH": ("str", None, "copy mode: the trainer file (aarch64 Linux binary or a "
                                  "script with #!)"),
    "TRAINER_CARGO_BIN": ("str", None, "build mode: the binary's name (cargo --bin)"),
    "TRAINER_CARGO_PACKAGE": ("str", None, "build mode: its crate (cargo -p, optional)"),
    "TRAINER_CARGO_FEATURES": ("str", None, "build mode: cargo --features (optional)"),
    "RUST_TOOLCHAIN": ("str", "stable", "build mode: rustup toolchain"),
    "ENGINE_DIR": ("str", os.path.join(REPO, "engine"), "build mode: the Cargo workspace"),
    "TRAINER_CONFIG": ("str", None, "the trainer's --config file (a local path)"),
    "TRAINER_ARGS": ("str", "", "extra trainer arguments, shell-quoted (optional)"),
    "TRAINER_FILES": ("list", None, "local files or folders the trainer needs (bucket tables, "
                                    "say), put in the bundle and installed on the machine at "
                                    "/opt/pscloud/bundle/files/<name> (optional)"),
    "CHECKPOINT_PATTERN": ("str", "*.ckpt", "file names the trainer gives its checkpoints"),
    "KEEP_CHECKPOINTS": ("int", 3, "checkpoints kept in the bucket"),
    "ARTIFACT_PATTERNS": ("list", ["*.bps", "*.jsonl"],
                          "other files the trainer writes in its folder (strategy files, logs) "
                          "that go to artifacts/ in the bucket and are all kept; none to turn "
                          "it off"),
    "TRAINER_MEMORY_GB": ("float", None, "the trainer's peak memory, measured (optional: check "
                                         "and launch then refuse a machine it doesn't fit)"),
    "CHECKPOINT_GB": ("float", None, "one checkpoint's size (optional: the disk is then "
                                     "checked to hold 4 of them, the artifacts and 30 GB)"),
    "ARTIFACTS_GB": ("float", None, "all the artifacts of the run together (optional, with "
                                    "CHECKPOINT_GB)"),
    "STATUS_SECONDS": ("int", 60, "how often the machine writes status.json"),
    "STOP_GRACE_SECONDS": ("int", 600, "time the trainer gets to save after SIGTERM on a stop "
                                       "we ask for (budget, stop command)"),
    "FINAL_UPLOAD_SECONDS": ("int", 600, "time for the last upload when the trainer exits"),
    "MAX_TRAINER_CRASHES": ("int", 3, "trainer crashes restarted (with --resume) before the "
                                      "run counts as failed"),
    "POWER_OFF_WHEN_DONE": ("bool", True, "power the machine off when training finishes"),
}

# Machine types whose size is known without asking Google: (vCPUs, memory in GB). C4A comes
# with 2 GB a vCPU (highcpu), 4 (standard) or 8 (highmem). `check` asks Google for any type.
# Hyperdisk Balanced's baseline, included in the price per GB.
FREE_IOPS = 3000
FREE_MBPS = 140
# Hyperdisk Balanced's limits (Google's docs, 27 Nov 2026): IOPS from 3,000 to 500 a GB, at
# most 160,000; throughput from MAX(140, IOPS/256) to MIN(2,400, IOPS/4) MiB/s.
MAX_IOPS_PER_GB = 500
MAX_IOPS = 160_000
MAX_MBPS = 2400

KNOWN_MACHINES = {f"c4a-{kind}-{n}": (n, n * per) for kind, per in
                  (("highcpu", 2), ("standard", 4), ("highmem", 8))
                  for n in (1, 2, 4, 8, 16, 32, 48, 64, 72)}

# Where TRAINER_FILES are installed on the machine (control.VM_BUNDLE + "/files").
VM_FILES = "/opt/pscloud/bundle/files"
# Room on the disk besides the checkpoints and artifacts: the system, Rust and the build.
DISK_SPARE_GB = 30

_NAME = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
_RUN = re.compile(r"^[a-z][a-z0-9-]{0,38}[a-z0-9]$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")


class SettingsError(Exception):
    pass


def parse_env_file(text: str) -> dict:
    """KEY=value lines. # starts a comment line; values may be quoted; `export ` is allowed."""
    out = {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            raise SettingsError(f"line {n}: expected KEY=value, got {raw!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in ("'", '"'):
            try:
                parts = shlex.split(value)
            except ValueError as e:
                raise SettingsError(f"line {n}: {e}") from e
            value = parts[0] if parts else ""
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        out[key] = value
    return out


def convert(name: str, kind: str, raw: str):
    try:
        if kind == "str":
            return raw if raw != "" else None
        if kind == "int":
            return int(raw) if raw != "" else None
        if kind == "float":
            return float(raw) if raw != "" else None
        if kind == "bool":
            v = raw.strip().lower()
            if v in TRUE:
                return True
            if v in FALSE:
                return False
            raise ValueError(raw)
        if kind == "list":
            items = [x.strip() for x in raw.replace(" ", ",").split(",") if x.strip()]
            return items or None
    except ValueError:
        raise SettingsError(f"{name}: {raw!r} is not a valid {kind}") from None
    raise AssertionError(kind)


class Settings:
    def __init__(self, values: dict, source: str | None = None):
        self.values = values
        self.source = source

    def __getattr__(self, name):
        if name.isupper() and name in self.values:
            return self.values[name]
        raise AttributeError(name)

    def get(self, name, default=None):
        v = self.values.get(name)
        return default if v is None else v

    # --- derived ---

    @property
    def instance_name(self) -> str:
        return self.values.get("INSTANCE_NAME") or f"ps-{self.values['RUN_NAME']}"

    @property
    def zones(self) -> list[str]:
        zones = list(self.values.get("ZONES") or [])
        zone = self.values["ZONE"]
        return [zone] + [z for z in zones if z != zone]

    @property
    def spot(self) -> bool:
        return (self.values.get("PROVISIONING") or "").upper() == "SPOT"

    @property
    def machine_price(self) -> float:
        return float(self.values["SPOT_PRICE_PER_HOUR" if self.spot
                                  else "STANDARD_PRICE_PER_HOUR"])

    @property
    def ip_price(self) -> float:
        if not self.values["EXTERNAL_IP"]:
            return 0.0
        return float(self.values["SPOT_IP_PRICE_PER_HOUR" if self.spot
                                 else "IP_PRICE_PER_HOUR"] or 0)

    @property
    def disk_performance(self) -> tuple[int | None, int | None]:
        """The boot disk's provisioned (IOPS, MiB/s) as sent to Google. Hyperdisk Balanced
        needs both once either is given, so an unset one is sent as the free baseline (3,000
        IOPS, 140 MiB/s). Both are sent even when neither is set: left to Google, an 80 GB disk
        gets 3,480 IOPS and 260 MiB/s, which cost more than the estimate counts. Other disk
        types: as set."""
        iops, mbps = self.values.get("DISK_IOPS"), self.values.get("DISK_THROUGHPUT_MBPS")
        if (self.values.get("DISK_TYPE") or "") == "hyperdisk-balanced":
            return int(iops or FREE_IOPS), int(mbps or FREE_MBPS)
        return (int(iops) if iops else None), (int(mbps) if mbps else None)

    def disk_month_price(self, size_gb: float, disk_type: str | None, iops: int | None = None,
                         mbps: int | None = None) -> float:
        """A disk's price a month: its size, and on Hyperdisk Balanced the IOPS and throughput
        provisioned above the free baseline (3,000 IOPS, 140 MiB/s). For this run's boot disk
        and for any disk `leftovers` lists, from that disk's own size and performance."""
        month = float(size_gb or 0) * float(self.values["DISK_PRICE_PER_GB_MONTH"] or 0)
        if (disk_type or "") == "hyperdisk-balanced":
            month += max(0, int(iops or FREE_IOPS) - FREE_IOPS) * float(
                self.values["DISK_IOPS_PRICE_PER_MONTH"] or 0)
            month += max(0, int(mbps or FREE_MBPS) - FREE_MBPS) * float(
                self.values["DISK_THROUGHPUT_PRICE_PER_MONTH"] or 0)
        return month

    @property
    def disk_price_per_hour(self) -> float:
        """The boot disk's size, and on Hyperdisk Balanced the IOPS and throughput provisioned
        above the free baseline (3,000 IOPS, 140 MiB/s), by the hour."""
        iops, mbps = self.disk_performance
        return self.disk_month_price(float(self.values["DISK_SIZE_GB"]),
                                     self.values.get("DISK_TYPE"), iops, mbps) / 730.0

    @property
    def price_per_hour(self) -> float:
        """Everything billed by the hour while the machine runs."""
        return self.machine_price + self.ip_price + self.disk_price_per_hour

    @property
    def store_url(self) -> str:
        return f"gs://{self.values['BUCKET']}/runs/{self.values['RUN_NAME']}"

    @property
    def trainer_args(self) -> list[str]:
        return shlex.split(self.values.get("TRAINER_ARGS") or "")

    def vcpus(self) -> int | None:
        m = re.search(r"-(\d+)(?:-lssd)?$", self.values.get("MACHINE_TYPE") or "")
        return int(m.group(1)) if m else None

    def machine_memory_gb(self) -> float | None:
        """The machine type's memory, if it is one of KNOWN_MACHINES."""
        mt = re.sub(r"-lssd$", "", self.values.get("MACHINE_TYPE") or "")
        known = KNOWN_MACHINES.get(mt)
        return float(known[1]) if known else None

    def disk_needed_gb(self) -> float | None:
        """Disk the run needs (4 checkpoints, the artifacts, DISK_SPARE_GB), if CHECKPOINT_GB
        is set."""
        ck = self.values.get("CHECKPOINT_GB")
        if ck is None:
            return None
        return 4 * float(ck) + float(self.values.get("ARTIFACTS_GB") or 0) + DISK_SPARE_GB

    @property
    def artifact_patterns(self) -> list[str]:
        pats = list(self.values.get("ARTIFACT_PATTERNS") or [])
        return [] if [p.lower() for p in pats] == ["none"] else pats

    def trainer_files(self) -> list[str]:
        return [os.path.expanduser(p) for p in (self.values.get("TRAINER_FILES") or [])]

    def problems(self, for_launch: bool = True) -> list[str]:
        """Everything wrong with the settings, as plain sentences."""
        v = self.values
        out = []
        for key in ("PROJECT", "BUCKET", "RUN_NAME"):
            if not v.get(key):
                out.append(f"{key} is not set")
        if v.get("RUN_NAME") and not _RUN.match(v["RUN_NAME"]):
            out.append("RUN_NAME: 2 to 40 characters, lowercase letters, digits and dashes, "
                       "starting with a letter")
        if v.get("RUN_NAME") and not _NAME.match(self.instance_name):
            out.append(f"INSTANCE_NAME {self.instance_name!r} is not a valid machine name")
        if v.get("BUCKET") and (v["BUCKET"].startswith("gs://") or not _BUCKET.match(v["BUCKET"])):
            out.append("BUCKET: the bucket's name only, without gs://")
        prov = (v.get("PROVISIONING") or "").upper()
        if prov not in ("SPOT", "STANDARD"):
            out.append("PROVISIONING must be SPOT or STANDARD")
        else:
            key = "SPOT_PRICE_PER_HOUR" if prov == "SPOT" else "STANDARD_PRICE_PER_HOUR"
            if v.get(key) is None or v[key] <= 0:
                out.append(f"{key} is not set (needed for the cost estimate and the cap)")
        if v.get("PREEMPTION_NOTICE_SECONDS") not in (0, 120):
            out.append("PREEMPTION_NOTICE_SECONDS must be 0 or 120")
        if v.get("BUDGET_USD") is None or v["BUDGET_USD"] <= 0:
            out.append("BUDGET_USD is not set (the hard cap is required)")
        for key in ("MAX_RESTARTS", "RECREATE_AFTER_FAILED_STARTS", "MAX_TRAINER_CRASHES",
                    "SILENT_STOP_MINUTES"):
            if v.get(key) is None or v[key] < 0:
                out.append(f"{key} must be 0 or more")
        if (v.get("KEEP_CHECKPOINTS") or 0) < 1:
            out.append("KEEP_CHECKPOINTS must be at least 1")
        if (v.get("DISK_SIZE_GB") or 0) < 20:
            out.append("DISK_SIZE_GB must be at least 20")
        if (v.get("STATUS_SECONDS") or 0) < 10:
            out.append("STATUS_SECONDS must be at least 10")
        for z in self.zones if v.get("ZONE") else []:
            if not z.startswith((v.get("REGION") or "") + "-"):
                out.append(f"zone {z} is not in REGION {v.get('REGION')}")
        mt = v.get("MACHINE_TYPE") or ""
        if mt.startswith(("c4a-", "t2a-")) and "arm64" not in (v.get("IMAGE_FAMILY") or ""):
            out.append(f"{mt} is an Arm machine: IMAGE_FAMILY must be an arm64 image")
        if mt.startswith("c4a-") and (v.get("DISK_TYPE") or "").startswith("pd-"):
            out.append("C4A machines don't take Persistent Disk: use hyperdisk-balanced")
        if (v.get("DISK_TYPE") or "") == "hyperdisk-balanced":
            iops, mbps = self.disk_performance
            top = min(MAX_IOPS_PER_GB * int(v.get("DISK_SIZE_GB") or 0), MAX_IOPS)
            if not FREE_IOPS <= iops <= top:
                out.append(f"DISK_IOPS {iops}: Hyperdisk Balanced of {v.get('DISK_SIZE_GB')} GB "
                           f"takes {FREE_IOPS} to {top}")
            low, high = max(FREE_MBPS, iops / 256), min(MAX_MBPS, iops / 4)
            if not low <= mbps <= high:
                out.append(f"DISK_THROUGHPUT_MBPS {mbps}: with {iops} IOPS Hyperdisk Balanced "
                           f"takes {low:g} to {high:g} MiB/s")
        mem = self.machine_memory_gb()
        need = v.get("TRAINER_MEMORY_GB")
        if mem is not None and need is not None and float(need) > 0.9 * mem:
            out.append(f"TRAINER_MEMORY_GB {float(need):g} does not fit {mt} ({mem:g} GB) with "
                       f"10% to spare: pick a machine with more memory")
        disk = self.disk_needed_gb()
        if disk is not None and (v.get("DISK_SIZE_GB") or 0) < disk:
            out.append(f"DISK_SIZE_GB {v.get('DISK_SIZE_GB')} is too small: 4 checkpoints of "
                       f"{float(v['CHECKPOINT_GB']):g} GB, {float(v.get('ARTIFACTS_GB') or 0):g} "
                       f"GB of artifacts and {DISK_SPARE_GB} GB for the system need "
                       f"{disk:g} GB")
        if for_launch:
            out += self._trainer_problems()
        return out

    def _trainer_problems(self) -> list[str]:
        v = self.values
        out = []
        mode = v.get("TRAINER_MODE")
        if mode == "copy":
            path = v.get("TRAINER_PATH")
            if not path:
                out.append("TRAINER_PATH is not set (copy mode)")
            elif not os.path.isfile(os.path.expanduser(path)):
                out.append(f"TRAINER_PATH {path} does not exist")
            else:
                kind = executable_kind(os.path.expanduser(path))
                if kind not in ("elf-aarch64", "script"):
                    out.append(f"TRAINER_PATH {path} is {kind}, not an aarch64 Linux "
                               f"program or a script: build it for aarch64-unknown-linux-gnu, "
                               f"or use TRAINER_MODE=build")
        elif mode == "build":
            if not v.get("TRAINER_CARGO_BIN"):
                out.append("TRAINER_CARGO_BIN is not set (build mode)")
            eng = os.path.expanduser(v.get("ENGINE_DIR") or "")
            if not os.path.isfile(os.path.join(eng, "Cargo.toml")):
                out.append(f"ENGINE_DIR {eng} has no Cargo.toml")
        else:
            out.append("TRAINER_MODE must be build or copy")
        names = set()
        for path in self.trainer_files():
            name = os.path.basename(path.rstrip(os.sep))
            if not os.path.exists(path):
                out.append(f"TRAINER_FILES: {path} does not exist")
            elif name in names:
                out.append(f"TRAINER_FILES: two entries are called {name}")
            names.add(name)
        cfg = v.get("TRAINER_CONFIG")
        if not cfg:
            out.append("TRAINER_CONFIG is not set")
        elif not os.path.isfile(os.path.expanduser(cfg)):
            out.append(f"TRAINER_CONFIG {cfg} does not exist")
        else:
            # A config that names a path under VM_FILES needs that file in TRAINER_FILES, or the
            # trainer fails on the machine, after the machine has started billing.
            for ref in bundle_file_refs(os.path.expanduser(cfg)):
                first = ref[len(VM_FILES) + 1:].split("/", 1)[0]
                if first not in names:
                    out.append(f"TRAINER_CONFIG names {ref}, but no entry of TRAINER_FILES is "
                               f"called {first}")
        return out


def bundle_file_refs(config_path: str) -> list[str]:
    """Strings in a JSON config that are paths under VM_FILES (none if it isn't JSON)."""
    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    found = []

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and x.startswith(VM_FILES + "/"):
            found.append(x.rstrip("/"))
    walk(data)
    return sorted(set(found))


def executable_kind(path: str) -> str:
    """What kind of program ``path`` is: 'elf-aarch64' (what the machine runs), 'script'
    (starts with #!), or something else, described."""
    with open(path, "rb") as f:
        head = f.read(64)
    if head.startswith(b"#!"):
        return "script"
    if head[:4] == b"\x7fELF" and len(head) >= 20:
        little = head[5] == 1
        machine = int.from_bytes(head[18:20], "little" if little else "big")
        return {183: "elf-aarch64", 62: "elf-x86_64"}.get(machine, f"elf-{machine}")
    if head[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xcf"):
        return "a macOS (Mach-O) program"
    return "unknown"


def settings_path(explicit: str | None = None, environ=None) -> str:
    env = os.environ if environ is None else environ
    return os.path.expanduser(explicit or env.get(SETTINGS_ENV) or DEFAULT_PATH)


def load(path: str | None = None, environ=None, require_file: bool = False) -> Settings:
    env = os.environ if environ is None else environ
    path = settings_path(path, env)
    raw = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            raw = parse_env_file(f.read())
    elif require_file:
        raise SettingsError(f"no settings file at {path} (copy tools/cloud/settings.example.env "
                            f"there and fill it in)")
    unknown = sorted(set(raw) - set(SPEC))
    if unknown:
        raise SettingsError(f"{path}: unknown settings {', '.join(unknown)}")
    for key in SPEC:
        if ENV_PREFIX + key in env:
            raw[key] = env[ENV_PREFIX + key]
    values = {}
    for key, (kind, default, _what) in SPEC.items():
        values[key] = convert(key, kind, raw[key]) if key in raw else default
        if values[key] is None:
            values[key] = default
    if values.get("PROVISIONING"):
        values["PROVISIONING"] = values["PROVISIONING"].upper()
    return Settings(values, source=path if os.path.exists(path) else None)


def tracked_by_git(path: str) -> bool:
    """True if ``path`` is inside this repo and git would commit it (not ignored)."""
    path = os.path.abspath(path)
    if not path.startswith(REPO + os.sep):
        return False
    try:
        p = subprocess.run(["git", "-C", REPO, "check-ignore", "-q", path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    return p.returncode == 1          # 0: ignored; 1: not ignored
