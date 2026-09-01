#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
VENV_PYTHON="$ROOT_DIR/apps/backend/.venv/bin/python"
SCRIPT=${1:?Python script path is required}
shift
if [ "${1:-}" = "--" ]; then
  shift
fi

if [ -x "$VENV_PYTHON" ]; then
  exec "$VENV_PYTHON" "$SCRIPT" "$@"
fi
exec python3 "$SCRIPT" "$@"
