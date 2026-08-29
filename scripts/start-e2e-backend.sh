#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BACKEND_DIR="$ROOT_DIR/apps/backend"
DATA_DIR=$(mktemp -d "${TMPDIR:-/tmp}/poker-hero-e2e.XXXXXX")
SERVER_PID=""
PROVIDER_PID=""
PROVIDER_READY_FILE="$DATA_DIR/provider-ready"

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "$PROVIDER_PID" ]; then
    kill "$PROVIDER_PID" >/dev/null 2>&1 || true
    wait "$PROVIDER_PID" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$DATA_DIR"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

if [ -n "${POKER_E2E_PYTHON:-}" ]; then
  if command -v "$POKER_E2E_PYTHON" >/dev/null 2>&1; then
    PYTHON_BIN=$(command -v "$POKER_E2E_PYTHON")
  else
    echo "POKER_E2E_PYTHON must name an executable Python interpreter" >&2
    exit 1
  fi
elif [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=$(command -v python3)
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN=$(command -v python)
else
  echo "Python 3.11+ with Poker Hero backend dependencies is required" >&2
  exit 1
fi

"$PYTHON_BIN" "$ROOT_DIR/scripts/e2e_provider_stub.py" \
  --host 127.0.0.1 \
  --port 8011 \
  --data-dir "$DATA_DIR" \
  --ready-file "$PROVIDER_READY_FILE" &
PROVIDER_PID=$!

ready_attempt=0
while [ ! -f "$PROVIDER_READY_FILE" ]; do
  if ! kill -0 "$PROVIDER_PID" >/dev/null 2>&1; then
    echo "E2E parser and recommendation provider failed to start" >&2
    wait "$PROVIDER_PID"
    exit 1
  fi
  ready_attempt=$((ready_attempt + 1))
  if [ "$ready_attempt" -ge 100 ]; then
    echo "Timed out waiting for E2E parser and recommendation provider" >&2
    exit 1
  fi
  sleep 0.05
done

cd "$DATA_DIR"
# The suite exports, imports and restores archives back to back within seconds,
# so the production per-minute data-transfer budget (covered by the backend unit
# tests) is raised here instead of pacing the browser scenarios.
env -i \
  HOME="${HOME:-$DATA_DIR}" \
  PATH="${PATH:-}" \
  TMPDIR="${TMPDIR:-/tmp}" \
  PYTHONPATH="$BACKEND_DIR" \
  POKER_DATA_DIR="$DATA_DIR" \
  POKER_PARSER_PROVIDER=llm_vision \
  POKER_EXTERNAL_PARSER_URL=http://127.0.0.1:8011/parse \
  POKER_RECOMMENDATION_PROVIDER=external_solver \
  POKER_EXTERNAL_PROVIDER_URL=http://127.0.0.1:8011/recommend \
  POKER_EXTERNAL_REQUEST_TIMEOUT_SECONDS=40 \
  POKER_ADMIN_OCR_TEST_ENABLED=true \
  POKER_ADMIN_OCR_TEST_TOKEN=e2e-administrative-ocr-test-token-0123456789 \
  POKER_API_RATE_LIMIT_DATA_TRANSFERS_PER_MINUTE=60 \
  POKER_CORS_ORIGINS='["http://127.0.0.1:4174"]' \
  "$PYTHON_BIN" -m uvicorn app.main:app \
    --host 127.0.0.1 \
    --port 8010 &
SERVER_PID=$!
wait "$SERVER_PID"
