#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BACKEND_DIR="$ROOT_DIR/apps/backend"
PLAYER_E2E_DATA_DIR=$(mktemp -d "${TMPDIR:-/tmp}/poker-hero-player-e2e.XXXXXX")
PLAYER_E2E_LAUNCH_FILE="$ROOT_DIR/apps/pwa/.player-e2e-launch-url"
PLAYER_E2E_SERVER_PID=""

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ -n "$PLAYER_E2E_SERVER_PID" ]; then
    kill "$PLAYER_E2E_SERVER_PID" >/dev/null 2>&1 || true
    wait "$PLAYER_E2E_SERVER_PID" >/dev/null 2>&1 || true
  fi
  rm -f -- "$PLAYER_E2E_LAUNCH_FILE"
  rm -rf -- "$PLAYER_E2E_DATA_DIR"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ -n "${POKER_E2E_PYTHON:-}" ]; then
  if command -v "$POKER_E2E_PYTHON" >/dev/null 2>&1; then
    PLAYER_E2E_PYTHON_BIN=$(command -v "$POKER_E2E_PYTHON")
  else
    echo "POKER_E2E_PYTHON must name an executable Python interpreter" >&2
    exit 1
  fi
elif [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  PLAYER_E2E_PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PLAYER_E2E_PYTHON_BIN=$(command -v python3)
elif command -v python >/dev/null 2>&1; then
  PLAYER_E2E_PYTHON_BIN=$(command -v python)
else
  echo "Python 3.11+ with Poker Hero backend dependencies is required" >&2
  exit 1
fi

rm -f -- "$PLAYER_E2E_LAUNCH_FILE"
cd "$PLAYER_E2E_DATA_DIR"
env -i \
  HOME="${HOME:-$PLAYER_E2E_DATA_DIR}" \
  PATH="${PATH:-}" \
  TMPDIR="${TMPDIR:-/tmp}" \
  PYTHONPATH="$BACKEND_DIR" \
  "$PLAYER_E2E_PYTHON_BIN" "$ROOT_DIR/scripts/player_e2e_server.py" \
    --data-dir "$PLAYER_E2E_DATA_DIR" \
    --launch-file "$PLAYER_E2E_LAUNCH_FILE" &
PLAYER_E2E_SERVER_PID=$!
wait "$PLAYER_E2E_SERVER_PID"
