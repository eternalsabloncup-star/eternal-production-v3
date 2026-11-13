#!/usr/bin/env bash
# Installs the V3 deploy runner under PREFIX (default /opt/epv3/deploy).
# DRY-RUN unless --apply. Never touches systemd, nginx, sudoers, secrets, services or app dirs.
# Needs Owner approval before running with --apply on the VPS.
set -euo pipefail

PREFIX="${EPV3_DEPLOY_PREFIX:-/opt/epv3/deploy}"
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

run() { if [[ $APPLY == 1 ]]; then "$@"; else echo "DRY-RUN: $*"; fi; }

[[ "$PREFIX" == /opt/epv3/* || -n "${EPV3_DEPLOY_ALLOW_PREFIX:-}" ]] || { echo "refusing prefix $PREFIX"; exit 2; }
python3 - <<'EOF' || { echo "python >= 3.10 required"; exit 2; }
import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)
EOF

for d in bin state source artifacts approvals keys; do run install -d -m 750 "$PREFIX/$d"; done
run install -m 755 "$HERE/epv3_deploy.py" "$PREFIX/bin/epv3-deploy"
if [[ -e "$PREFIX/deploy.conf.json" ]]; then
  echo "keeping existing $PREFIX/deploy.conf.json"
else
  run install -m 640 "$HERE/deploy.conf.example.json" "$PREFIX/deploy.conf.json"
fi
echo "installed (apply=$APPLY) -> $PREFIX/bin/epv3-deploy"
