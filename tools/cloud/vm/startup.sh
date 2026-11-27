#!/bin/bash
# PokerScribe training machine: setup, run by Google as root at every boot (startup-script).
#
# The first boot downloads the bundle from the bucket (the supervisor, run.json, the trainer's
# config, and the trainer, or the engine's source to build it), installs the systemd service
# pscloud-trainer and starts it. Later boots find the same bundle installed and only make sure
# the service runs (it is enabled, so systemd starts it at boot anyway).
#
# If the setup fails, the log goes to the bucket (logs/startup-*.log), the run is marked failed
# (state.json) and the machine powers off, so a broken machine doesn't sit there billing.
#
# Everything it needs comes from the instance metadata set by `python -m tools.cloud launch`:
# pscloud-store (gs://<bucket>/runs/<run>) and pscloud-bundle-version.
#
# The tests run it in a sandbox: PSCLOUD_ROOT prefixes every path it writes, PSCLOUD_METADATA_URL
# replaces the metadata server (a file:// folder works), PSCLOUD_POWEROFF the power-off command,
# PSCLOUD_RETRY_WAIT the first retry delay, and stub commands come first on PATH.
# It keeps to bash 3.2 so the test also runs on macOS.
set -euo pipefail

ROOT="${PSCLOUD_ROOT:-}"
META="${PSCLOUD_METADATA_URL:-http://metadata.google.internal/computeMetadata/v1/instance/attributes/}"
POWEROFF="${PSCLOUD_POWEROFF:-systemctl poweroff}"
OPT=/opt/pscloud
BUNDLE=$OPT/bundle
VAR=/var/lib/pscloud
UNITS=/etc/systemd/system
export CLOUDSDK_CORE_DISABLE_PROMPTS=1

mkdir -p "$ROOT$BUNDLE/config" "$ROOT$VAR/checkpoints" "$ROOT$UNITS"
LOG="$ROOT$VAR/startup.log"
STORE=""

log() {
  printf '%s pscloud startup: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG" >&2
}

fail() {
  trap - ERR
  log "FAILED: $1"
  if [ -n "$STORE" ] && command -v gcloud >/dev/null 2>&1; then
    gcloud storage cp "$LOG" \
      "$STORE/logs/startup-$(hostname)-$(date -u +%Y%m%dT%H%M%SZ).log" >/dev/null 2>&1 || true
    python3 -c 'import json, sys, time
print(json.dumps({"state": "failed", "at": time.time(), "session": None,
                  "detail": "machine setup failed: " + sys.argv[1]}))' "$1" \
      | gcloud storage cp - "$STORE/state.json" >/dev/null 2>&1 || true
  fi
  log "powering off"
  $POWEROFF || true
  exit 1
}
trap 'fail "line $LINENO: $BASH_COMMAND"' ERR

attr() {
  curl -sf --max-time 10 -H "Metadata-Flavor: Google" "$META$1" || true
}

retry() {  # retry <attempts> <command...>
  local attempts=$1 i=1 wait="${PSCLOUD_RETRY_WAIT:-5}"
  shift
  until "$@"; do
    if [ "$i" -ge "$attempts" ]; then
      return 1
    fi
    log "retrying in ${wait} s ($i of $attempts failed): $*"
    sleep "$wait"
    i=$((i + 1))
    wait=$((wait * 2))
    if [ "$wait" -gt 60 ]; then wait=60; fi
  done
}

apt_install() {
  DEBIAN_FRONTEND=noninteractive apt-get update -q
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q "$@"
}

install_gcloud() {
  log "gcloud is missing: installing google-cloud-cli from Google's apt repository"
  apt_install apt-transport-https ca-certificates gnupg curl
  curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | gpg --dearmor --yes -o /usr/share/keyrings/cloud.google.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    > /etc/apt/sources.list.d/google-cloud-sdk.list
  apt_install google-cloud-cli
}

fetch() {  # fetch <name in bundle/>: download to the same name under $BUNDLE
  local dest="$ROOT$BUNDLE/$1"
  mkdir -p "$(dirname "$dest")"
  retry 6 gcloud storage cp "$STORE/bundle/$1" "$dest.part"
  mv -f "$dest.part" "$dest"
}

mget() {  # mget <key>: a value from the bundle's manifest.json
  python3 -c 'import json, sys
v = json.load(open(sys.argv[1])).get(sys.argv[2], "")
print("true" if v is True else "false" if v is False else v)' "$ROOT$BUNDLE/manifest.json" "$1"
}

build_trainer() {
  local version=$1 src="$ROOT$OPT/src" bin pkg feat tool
  bin="$(mget cargo_bin)"
  pkg="$(mget cargo_package)"
  feat="$(mget cargo_features)"
  tool="$(mget rust_toolchain)"
  fetch engine-src.tar.gz
  rm -rf "$src"
  mkdir -p "$src"
  tar -xzf "$ROOT$BUNDLE/engine-src.tar.gz" -C "$src"
  if ! command -v cc >/dev/null 2>&1; then
    retry 3 apt_install build-essential
  fi
  export RUSTUP_HOME="$ROOT$OPT/rust/rustup" CARGO_HOME="$ROOT$OPT/rust/cargo"
  export PATH="$PATH:$CARGO_HOME/bin"
  if ! command -v cargo >/dev/null 2>&1; then
    log "installing Rust ($tool) with rustup"
    retry 3 sh -c "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
      | sh -s -- -y --profile minimal --no-modify-path --default-toolchain $tool"
  fi
  local args
  args=(build --release --bin "$bin")
  if [ -n "$pkg" ]; then args=("${args[@]}" -p "$pkg"); fi
  if [ -n "$feat" ]; then args=("${args[@]}" --features "$feat"); fi
  if [ "$(mget has_lock)" = "true" ]; then args=("${args[@]}" --locked); fi
  log "building the trainer: cargo ${args[*]}"
  (cd "$src/engine" && cargo "${args[@]}") >>"$LOG" 2>&1
  cp "$src/engine/target/release/$bin" "$ROOT$BUNDLE/trainer"
  # The next machine of this run downloads this instead of building again.
  retry 3 gcloud storage cp "$ROOT$BUNDLE/trainer" "$STORE/bundle/trainer-built-$version"
  log "built $bin and saved it to the bucket"
}

write_units() {
  local timeout
  timeout="$(mget stop_timeout_seconds)"
  cat > "$ROOT$UNITS/pscloud-trainer.service" <<EOF
[Unit]
Description=PokerScribe training run (tools/cloud supervisor)
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=3600
StartLimitBurst=5
OnFailure=pscloud-on-failure.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 $BUNDLE/supervisor.py --run-config $BUNDLE/run.json
WorkingDirectory=$VAR
Restart=on-failure
RestartSec=30
# Every process in the service gets SIGTERM at a stop: the trainer saves, the supervisor
# uploads what it saved. Both then have this long before SIGKILL (a Spot preemption cuts it
# to about 30 seconds, or 2 minutes plus 30 seconds with the notice).
KillMode=control-group
TimeoutStopSec=$timeout
LimitNOFILE=1048576
Environment=PYTHONUNBUFFERED=1
Environment=CLOUDSDK_CORE_DISABLE_PROMPTS=1

[Install]
WantedBy=multi-user.target
EOF
  cat > "$ROOT$UNITS/pscloud-on-failure.service" <<EOF
[Unit]
Description=PokerScribe training run: save the log and power off after the supervisor failed

[Service]
Type=oneshot
ExecStart=/bin/bash $OPT/on-failure.sh
EOF
  cat > "$ROOT$OPT/on-failure.sh" <<EOF
#!/bin/bash
# systemd runs this when pscloud-trainer failed 5 times within an hour: the supervisor's log
# goes to the bucket, the run is marked failed, and the machine powers off.
export CLOUDSDK_CORE_DISABLE_PROMPTS=1
STORE=$(printf '%q' "$STORE")
boot=\$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || date +%s)
journalctl -u pscloud-trainer.service -n 2000 --no-pager \\
  | gcloud storage cp - "\$STORE/logs/\$boot-supervisor-failed.log" || true
python3 -c 'import json, time
print(json.dumps({"state": "failed", "at": time.time(), "session": None,
                  "detail": "the supervisor kept failing: see logs/*-supervisor-failed.log"}))' \\
  | gcloud storage cp - "\$STORE/state.json" || true
$POWEROFF
EOF
  chmod 755 "$ROOT$OPT/on-failure.sh"
}

# --- main ---

command -v curl >/dev/null 2>&1 || retry 3 apt_install curl
STORE="$(attr pscloud-store)"
VERSION="$(attr pscloud-bundle-version)"
[ -n "$STORE" ] || fail "no pscloud-store in the instance metadata"
[ -n "$VERSION" ] || fail "no pscloud-bundle-version in the instance metadata"
log "run bucket $STORE, bundle $VERSION"
command -v python3 >/dev/null 2>&1 || retry 3 apt_install python3
command -v gcloud >/dev/null 2>&1 || retry 3 install_gcloud

installed="$(cat "$ROOT$OPT/installed-version" 2>/dev/null || true)"
if [ "$installed" != "$VERSION" ]; then
  log "installing bundle $VERSION"
  fetch manifest.json
  got="$(mget version)"
  [ "$got" = "$VERSION" ] || fail "the bucket has bundle $got, the metadata says $VERSION: launch again"
  fetch supervisor.py
  fetch run.json
  fetch "config/$(mget config_name)"
  if [ "$(mget mode)" = "copy" ]; then
    fetch trainer
  elif gcloud storage ls "$STORE/bundle/trainer-built-$VERSION" >/dev/null 2>&1; then
    log "a machine of this run already built the trainer: downloading it"
    fetch "trainer-built-$VERSION"
    mv -f "$ROOT$BUNDLE/trainer-built-$VERSION" "$ROOT$BUNDLE/trainer"
  else
    build_trainer "$VERSION"
  fi
  chmod 755 "$ROOT$BUNDLE/trainer"
  write_units
  echo "$VERSION" > "$ROOT$OPT/installed-version"
  log "bundle $VERSION installed"
fi

systemctl daemon-reload
systemctl enable pscloud-trainer.service
systemctl start --no-block pscloud-trainer.service
log "pscloud-trainer is running (journalctl -u pscloud-trainer -f)"
