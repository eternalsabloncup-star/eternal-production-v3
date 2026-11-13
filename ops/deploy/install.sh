#!/usr/bin/env bash
# Installs the V3 deploy runner under PREFIX (default /opt/epv3/deploy).
# FAIL-CLOSED: requires a prepared, valid live config (--config FILE, or an existing $PREFIX/deploy.conf.json).
# The example config is never used as live config. DRY-RUN unless --apply.
# Never touches systemd, nginx, sudoers, secrets, deploy keys, services or app dirs.
set -euo pipefail

PREFIX="${EPV3_DEPLOY_PREFIX:-/opt/epv3/deploy}"
APPLY=0
CFG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --config) CFG="${2:?--config needs a file}"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

run() { if [[ $APPLY == 1 ]]; then "$@"; else echo "DRY-RUN: $*"; fi; }

[[ "$PREFIX" == /opt/epv3/* || -n "${EPV3_DEPLOY_ALLOW_PREFIX:-}" ]] || { echo "refusing prefix $PREFIX" >&2; exit 2; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "python >= 3.10 required" >&2; exit 2; }

if [[ -z "$CFG" ]]; then
  CFG="$PREFIX/deploy.conf.json"
  [[ -f "$CFG" ]] || { echo "REFUSED: no live config. Prepare one and pass --config FILE (see deploy.conf.example.json)" >&2; exit 2; }
fi
[[ -f "$CFG" ]] || { echo "REFUSED: config not found: $CFG" >&2; exit 2; }
python3 "$HERE/epv3_deploy.py" --config "$CFG" validate-config || { echo "REFUSED: config invalid; nothing installed" >&2; exit 2; }

for d in bin state source artifacts approvals; do run install -d -m 750 "$PREFIX/$d"; done
run install -m 755 "$HERE/epv3_deploy.py" "$PREFIX/bin/epv3-deploy"
if [[ -e "$PREFIX/deploy.conf.json" ]]; then
  echo "keeping existing $PREFIX/deploy.conf.json"
else
  run install -m 640 "$CFG" "$PREFIX/deploy.conf.json"
fi
echo "installed (apply=$APPLY) -> $PREFIX/bin/epv3-deploy (no baseline recorded, no service touched)"
