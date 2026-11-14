#!/bin/bash
# Test doubles for epv3-ci. Does not contact Live PostgreSQL or /opt/epv3.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLI="$ROOT_DIR/epv3-ci"
PASS=0
FAIL=0

ok() { PASS=$((PASS + 1)); printf 'PASS %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s\n' "$1" >&2; }

assert() {
  local name="$1"
  shift
  if "$@"; then
    ok "$name"
  else
    bad "$name"
  fi
}

new_repo() {
  WORK="$(mktemp -d)"
  ROOT="$WORK/ci"
  SRC="$ROOT/src"
  mkdir -p "$SRC/backend" "$SRC/frontend" "$SRC/accurate-gateway" "$ROOT/home"
  printf 'backend\n' > "$SRC/backend/requirements.txt"
  printf 'gateway\n' > "$SRC/accurate-gateway/requirements.txt"
  printf '{}\n' > "$SRC/frontend/package-lock.json"
  git -C "$SRC" init -q -b main
  git -C "$SRC" add .
  git -C "$SRC" -c user.email=ci@example.com -c user.name=ci commit -q -m fixture
  TARGET_SHA="$(git -C "$SRC" rev-parse HEAD)"
  PGPASS_SRC="$ROOT/ci-runner.pgpass"
  PGPASS="$ROOT/ci.pgpass"
  ENV_FILE="$ROOT/ci.env"
  VENV="$ROOT/venv"
  VENV_GW="$ROOT/venv-gateway"
  HOME_CI="$ROOT/home"
  MANIFEST_DIR="$ROOT/manifests/$TARGET_SHA"
  MANIFEST="$MANIFEST_DIR/prepare.manifest"
  REPORT_DIR="$ROOT/reports/$TARGET_SHA"
  REPORT="$REPORT_DIR/REPORT.txt"
  STATE_CI_DATA="$ROOT/pgdata"
  mkdir -p "$STATE_CI_DATA"
  SECRET='p@ss/word:secret'
  printf '%s\n' "127.0.0.1:5433:${DB}:${ROLE}:${SECRET}" > "$PGPASS_SRC"
  chmod 600 "$PGPASS_SRC"
  PEER_LOG="$WORK/peer.log"
  : > "$PEER_LOG"
}

seams() {
  require_root() { :; }
  require_run_user() { :; }
  user_can_write() { [[ -w "$1" ]]; }
  list_listening_postmasters() {
    printf 'ci 101 postgres 5433 %s 0::/epv3-ci.slice/postgres.service\n' "$STATE_CI_DATA"
    printf 'live 202 postgres 5432 /var/lib/postgresql/16/main 0::/system.slice/postgresql.service\n'
  }
  sql_identity() {
    local created=f
    if [[ -f "$PEER_LOG" ]] && grep -q 'ALTER ROLE' "$PEER_LOG"; then
      created=t
    fi
    if [[ "${FORCE_SUPER:-}" == "1" ]]; then
      created=t
      printf '%s\n' "${ROLE}|5433|${STATE_CI_DATA}|127.0.0.1|t|${created}|127.0.0.1"
      return 0
    fi
    printf '%s\n' "${ROLE}|5433|${STATE_CI_DATA}|127.0.0.1|f|${created}|127.0.0.1"
  }
  psql_peer() {
    printf '%s %s\n' "$1" "$2" >> "$PEER_LOG"
    if [[ "$2" == "SHOW data_directory" ]]; then
      printf '%s\n' "$STATE_CI_DATA"
    fi
  }
  systemctl_value() {
    case "$1:$2" in
      epv3-ci.slice:MemoryMax) printf '2147483648\n' ;;
      epv3-ci.slice:CPUQuotaPerSecUSec) printf '1.5s\n' ;;
      epv3-api:LoadState|epv3-accurate-gateway:LoadState) printf 'loaded\n' ;;
      epv3-api:Slice|epv3-accurate-gateway:Slice) printf 'system.slice\n' ;;
      *) printf '\n' ;;
    esac
  }
  mem_avail_kb() { printf '3000000\n'; }
  disk_avail_bytes() { printf '20000000000\n'; }
  find_node() { NODE_BIN="/usr/bin/node"; NODE_MAJOR=24; }
  have_cmd() { return 0; }
  prepare_python() { printf 'prepare-python-limited\n' >> "$WORK/actions"; }
  prove_port_block() { printf 'port-block\n' >> "$WORK/actions"; }
  run_limited() {
    local name="$1"
    printf 'leak %s\n3 passed in 0.01s\n' "$SECRET"
    mkdir -p "$REPORT_DIR"
    printf '%s 0\n' "$name" >> "$REPORT_DIR/jobs.tsv"
  }
}

source_cli() {
  # shellcheck disable=SC1090
  source "$CLI"
  DB=epv3_ci_05befb16_test
  ROLE=epv3_ci_runner
  PGHOST_CI=127.0.0.1
  PGPORT_CI=5433
  SLICE=epv3-ci.slice
  RUN_USER=epv3-ci-test
  LIVE_PORT=5432
}

run_case() {
  local name="$1"
  shift
  set +e
  ( set -euo pipefail; "$@" )
  local rc=$?
  set -e
  if [[ "$rc" -eq 0 ]]; then
    ok "$name"
  else
    bad "$name"
  fi
}

check_passes() {
  source_cli
  new_repo
  seams
  local out
  out="$(cmd_check)"
  [[ "$out" == *"CHECK=PASS"* ]]
  [[ "$out" == *"CREATEDB=f"* ]]
  [[ "$out" == *"NODE_GITHUB_EQUIVALENT=no"* ]]
  [[ "$out" != *"$SECRET"* ]]
  [[ ! -e "$MANIFEST" && ! -e "$ENV_FILE" ]]
}

prepare_then_run() {
  source_cli
  new_repo
  seams
  local out
  out="$(cmd_prepare)"
  [[ "$out" == *"PREPARE=PASS"* ]]
  [[ "$out" != *"$SECRET"* ]]
  [[ "$(awk -F= '$1=="SHA"{print $2}' "$MANIFEST")" == "$TARGET_SHA" ]]
  [[ "$(awk -F= '$1=="CREATEDB"{print $2}' "$MANIFEST")" == "t" ]]
  [[ "$(awk -F= '$1=="SUPERUSER"{print $2}' "$MANIFEST")" == "f" ]]
  [[ "$(grep -c 'ALTER ROLE' "$PEER_LOG")" -eq 1 ]]
  [[ "$(grep -c 5432 "$PEER_LOG")" -eq 0 ]]
  out="$(cmd_prepare)"
  [[ "$(grep -c 'ALTER ROLE' "$PEER_LOG")" -eq 1 ]]
  out="$(cmd_run)"
  [[ "$out" == *"INDEPENDENT_CI=PASS"* ]]
  [[ "$out" == *"E2E=NOT_RUN"* && "$out" == *"E2E_IS_PASS=no"* ]]
  [[ "$out" == *"GITHUB_CI_EQUIVALENT=no"* ]]
  [[ "$out" != *"$SECRET"* ]]
  ! grep -q "$SECRET" "$REPORT" "$REPORT_DIR/backend.log"
  grep -q port-block "$WORK/actions"
}

skipped_is_fail() {
  source_cli
  new_repo
  seams
  cmd_prepare >/dev/null
  run_limited() {
    local name="$1"
    printf '1 passed, 1 skipped in 0.01s\n'
    mkdir -p "$REPORT_DIR"
    printf '%s 0\n' "$name" >> "$REPORT_DIR/jobs.tsv"
  }
  set +e
  cmd_run >/dev/null
  local rc=$?
  set -e
  [[ "$rc" -eq 1 ]]
  [[ "$(awk -F= '$1=="INDEPENDENT_CI"{print $2}' "$REPORT")" == "FAIL" ]]
  [[ "$(awk -F= '$1=="E2E_IS_PASS"{print $2}' "$REPORT")" == "no" ]]
}

backend_fail() {
  source_cli
  new_repo
  seams
  cmd_prepare >/dev/null
  run_limited() {
    local name="$1"
    mkdir -p "$REPORT_DIR"
    if [[ "$name" == "backend" ]]; then
      printf '1 failed, 2 passed in 0.01s\n'
      printf '%s 1\n' "$name" >> "$REPORT_DIR/jobs.tsv"
      return 1
    fi
    printf '3 passed in 0.01s\n'
    printf '%s 0\n' "$name" >> "$REPORT_DIR/jobs.tsv"
  }
  set +e
  cmd_run >/dev/null
  local rc=$?
  set -e
  [[ "$rc" -eq 1 ]]
  [[ "$(awk -F= '$1=="BACKEND_RESULT"{print $2}' "$REPORT")" == "FAIL" ]]
  [[ "$(awk -F= '$1=="INDEPENDENT_CI"{print $2}' "$REPORT")" == "FAIL" ]]
}

run_without_prepare() {
  source_cli
  new_repo
  seams
  set +e
  local out
  out="$(cmd_run 2>&1)"
  local rc=$?
  set -e
  [[ "$rc" -eq 2 ]]
  [[ "$out" == *"prepare manifest is missing"* ]]
}

superuser_stops() {
  source_cli
  new_repo
  seams
  FORCE_SUPER=1
  set +e
  local out
  out="$(cmd_check 2>&1)"
  local rc=$?
  set -e
  [[ "$rc" -eq 2 && "$out" == *"superuser"* ]]
  [[ ! -e "$MANIFEST" ]]
}

decide_gates() {
  source_cli
  new_repo
  seams
  load_state
  local reason
  reason="$(decide)"
  [[ -z "$reason" ]]
  STATE_HEAD=deadbeef
  set +e
  reason="$(decide)"
  local rc=$?
  set -e
  [[ "$rc" -eq 1 && "$reason" == *"HEAD"* ]]
  load_state
  STATE_LIVE_DATA="$ROOT/pgdata-live"
  set +e
  reason="$(decide)"
  rc=$?
  set -e
  [[ "$rc" -eq 1 && "$reason" == *"Live data directory"* ]]
  load_state
  STATE_SLICE_MEM=infinity
  set +e
  reason="$(decide)"
  rc=$?
  set -e
  [[ "$rc" -eq 1 && "$reason" == *"MemoryMax"* ]]
  load_state
  STATE_API_SLICE="$SLICE"
  set +e
  reason="$(decide)"
  rc=$?
  set -e
  [[ "$rc" -eq 1 && "$reason" == *"Live service"* ]]
  load_state
  STATE_NODE_MAJOR=23
  set +e
  reason="$(decide)"
  rc=$?
  set -e
  [[ "$rc" -eq 1 && "$reason" == *"Node"* ]]
}

dirty_tree_stops() {
  source_cli
  new_repo
  seams
  printf 'x\n' >> "$SRC/backend/requirements.txt"
  set +e
  local out
  out="$(cmd_check 2>&1)"
  local rc=$?
  set -e
  [[ "$rc" -eq 2 && "$out" == *"dirty"* ]]
}

binary_fail_closed() {
  local marker
  marker="$(mktemp)"
  rm -f "$marker"
  set +e
  local out
  out="$(EPV3_CI_ROOT=/tmp/evil PATH="/tmp/does-not-exist:$PATH" bash "$CLI" check 2>&1)"
  local rc=$?
  set -e
  [[ "$rc" -eq 2 && "$out" == *"run as root"* && "$out" != *"/tmp/evil"* ]]
  [[ ! -d /var/lib/epv3-ci-test ]]
  set +e
  out="$(bash "$CLI" bootstrap 2>&1)"
  rc=$?
  set -e
  [[ "$rc" -eq 2 && "$out" == *"epv3-ci check"* && "$out" == *"epv3-ci prepare"* && "$out" == *"epv3-ci run"* ]]
}

installer_cases() {
  local dest
  dest="$(mktemp -d)"
  bash "$ROOT_DIR/install.sh" --prefix "$dest" >/dev/null
  bash "$ROOT_DIR/install.sh" --prefix "$dest" >/dev/null
  cmp -s "$CLI" "$dest/bin/epv3-ci"
  [[ -x "$dest/bin/epv3-ci" ]]
  set +e
  local out rc
  out="$(bash "$ROOT_DIR/install.sh" --prefix /opt/epv3/ci-tool 2>&1)"
  rc=$?
  set -e
  [[ "$rc" -eq 2 && "$out" == *"/opt/epv3"* ]]
  [[ ! -e /opt/epv3/ci-tool ]]
}

run_case "check is read-only and reports Node 24" check_passes
run_case "prepare grants CREATEDB once and run writes PASS" prepare_then_run
run_case "skipped result is FAIL" skipped_is_fail
run_case "backend failure is FAIL" backend_fail
run_case "run without prepare stops" run_without_prepare
run_case "superuser stops" superuser_stops
run_case "decide rejects unsafe states" decide_gates
run_case "dirty tree stops" dirty_tree_stops
run_case "executable ignores override env and stays closed" binary_fail_closed
run_case "installer is idempotent and refuses /opt/epv3" installer_cases

printf 'TEST_PASS=%s\nTEST_FAIL=%s\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
