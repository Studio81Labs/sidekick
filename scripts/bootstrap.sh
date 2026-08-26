#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
BACKEND_DIR="$ROOT_DIR/apps/backend"
POSTFLOP_SOLVER_DIR="$ROOT_DIR/solver-plugins/postflop"
POSTFLOP_SOLVER_BIN="$POSTFLOP_SOLVER_DIR/target/release/poker-postflop-solver"

command -v node >/dev/null 2>&1 || { echo "Node.js 24+ is required" >&2; exit 1; }
command -v pnpm >/dev/null 2>&1 || { echo "pnpm 11+ is required" >&2; exit 1; }
command -v cargo >/dev/null 2>&1 || { echo "Rust 1.85+ with Cargo is required" >&2; exit 1; }

PYTHON_BIN=""
check_python_candidate() {
  candidate_name=$1
  if command -v "$candidate_name" >/dev/null 2>&1 \
    && "$candidate_name" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' \
      >/dev/null 2>&1; then
    PYTHON_BIN=$(command -v "$candidate_name")
  fi
}

for candidate in python3 python; do
  check_python_candidate "$candidate"
  [ -n "$PYTHON_BIN" ] && break
done

python_minor=30
while [ -z "$PYTHON_BIN" ] && [ "$python_minor" -ge 11 ]; do
  check_python_candidate "python3.$python_minor"
  python_minor=$((python_minor - 1))
done

if [ -z "$PYTHON_BIN" ]; then
  echo "Python 3.11+ is required" >&2
  exit 1
fi

pnpm install --frozen-lockfile

if [ ! -d "$BACKEND_DIR/.venv" ]; then
  "$PYTHON_BIN" -m venv "$BACKEND_DIR/.venv"
fi

"$BACKEND_DIR/.venv/bin/python" -m pip install \
  --require-hashes \
  -r "$BACKEND_DIR/requirements-dev.txt"
"$BACKEND_DIR/.venv/bin/python" -m pip install \
  --no-deps \
  --no-build-isolation \
  "$BACKEND_DIR"
"$BACKEND_DIR/.venv/bin/python" -m pip check

cargo build --locked --release --manifest-path "$POSTFLOP_SOLVER_DIR/Cargo.toml"
if [ ! -x "$POSTFLOP_SOLVER_BIN" ]; then
  echo "Postflop solver build did not produce $POSTFLOP_SOLVER_BIN" >&2
  exit 1
fi

if [ ! -f "$BACKEND_DIR/.env" ]; then
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
fi

echo "Poker Hero is ready."
echo "Run 'pnpm backend:dev' and 'pnpm pwa:dev' in separate terminals."
