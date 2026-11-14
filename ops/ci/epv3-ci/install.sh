#!/bin/bash
# Idempotent installer. Copies epv3-ci only. Does not touch /opt/epv3 or Live services.
set -euo pipefail
umask 077

PREFIX=/usr/local
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
CLI_SRC="$SRC_DIR/epv3-ci"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --prefix)
      PREFIX="${2:-}"
      shift 2
      ;;
    *)
      echo "usage: install.sh [--prefix DIR]" >&2
      exit 2
      ;;
  esac
done

[[ -n "$PREFIX" && "$PREFIX" != "/" ]] || { echo "STOP: refusing prefix" >&2; exit 2; }
case "$PREFIX" in
  /opt/epv3|/opt/epv3/*)
    echo "STOP: refusing to install under /opt/epv3" >&2
    exit 2
    ;;
esac
if [[ -d "$PREFIX" ]]; then
  PREFIX="$(readlink -f "$PREFIX")"
fi
case "$PREFIX" in
  /opt/epv3|/opt/epv3/*)
    echo "STOP: refusing to install under /opt/epv3" >&2
    exit 2
    ;;
esac
[[ -f "$CLI_SRC" ]] || { echo "STOP: epv3-ci source is missing" >&2; exit 2; }

mkdir -p "$PREFIX/bin"
dest="$PREFIX/bin/epv3-ci"
if [[ -e "$dest" && ! -f "$dest" ]]; then
  echo "STOP: $dest exists and is not a file" >&2
  exit 2
fi
tmp="$(mktemp "$PREFIX/bin/.epv3-ci.XXXXXX")"
cp "$CLI_SRC" "$tmp"
chmod 0755 "$tmp"
mv -f "$tmp" "$dest"
echo "INSTALLED=$dest"
if [[ -f "$dest" ]] && cmp -s "$CLI_SRC" "$dest"; then
  echo "IDEMPOTENT=yes"
fi
