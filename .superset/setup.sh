#!/bin/sh
# Superset workspace setup for Poker Hero.
#
# Runs once for every new workspace (a fresh git worktree). It mirrors
# scripts/bootstrap.sh but is tuned for worktrees:
#   - workspaces with identical solver sources share one Cargo build cache
#     (keyed by the solver's git tree hash), so the solver compiles once per
#     source version rather than once per workspace
#   - local env files are carried over from the main checkout when present
#   - the Rust solver build is best-effort: without cargo the workspace still
#     comes up and the backend uses its built-in recommendation fallback
#
# Superset sets SUPERSET_ROOT_PATH (main checkout) and SUPERSET_WORKSPACE_PATH;
# both are derived from git when the script is run by hand.
# Optional: POKER_PYTHON=/path/to/python3.x to pin the interpreter.
set -eu

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
BACKEND_DIR="$ROOT_DIR/apps/backend"
SOLVER_DIR="$ROOT_DIR/solver-plugins/postflop"
SOLVER_BIN_NAME="poker-postflop-solver"
SOLVER_BIN="$SOLVER_DIR/target/release/$SOLVER_BIN_NAME"

step() { printf '\n==> %s\n' "$*"; }
warn() { printf '!!  %s\n' "$*" >&2; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

# Main checkout: source of local env files.
MAIN_DIR="${SUPERSET_ROOT_PATH:-}"
if [ -z "$MAIN_DIR" ]; then
  common_dir=$(git -C "$ROOT_DIR" rev-parse --git-common-dir 2>/dev/null || echo .git)
  MAIN_DIR=$(CDPATH='' cd -- "$ROOT_DIR" && cd -- "$(dirname -- "$common_dir")" && pwd -P)
fi
MAIN_DIR=$(CDPATH='' cd -- "$MAIN_DIR" && pwd -P)

# --- Toolchain ---------------------------------------------------------------
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$ROOT_DIR/.superset/lib.sh"
ensure_node "$ROOT_DIR" \
  || fail "Node.js $WANTED_NODE+ is required, found $(node_found) (see .nvmrc)"
command -v pnpm >/dev/null 2>&1 || fail "pnpm 11+ is required"

PYTHON_BIN="${POKER_PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
  for candidate in python3 python python3.14 python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
      PYTHON_BIN=$(command -v "$candidate")
      break
    fi
  done
fi
[ -n "$PYTHON_BIN" ] || fail "Python 3.11+ is required (set POKER_PYTHON to pick one)"

step "Workspace: $ROOT_DIR"
echo "main checkout: $MAIN_DIR"
echo "node $(node --version), pnpm $(pnpm --version), $("$PYTHON_BIN" --version 2>&1)"

# --- JavaScript ---------------------------------------------------------------
step "Installing JavaScript dependencies"
(cd "$ROOT_DIR" && pnpm install --frozen-lockfile)

# --- Python -------------------------------------------------------------------
step "Preparing backend virtualenv"
[ -d "$BACKEND_DIR/.venv" ] || "$PYTHON_BIN" -m venv "$BACKEND_DIR/.venv"
VENV_PY="$BACKEND_DIR/.venv/bin/python"
"$VENV_PY" -m pip install --disable-pip-version-check \
  --require-hashes -r "$BACKEND_DIR/requirements-dev.txt"
"$VENV_PY" -m pip install --disable-pip-version-check \
  --no-deps --no-build-isolation "$BACKEND_DIR"
"$VENV_PY" -m pip check

# --- Local env files ----------------------------------------------------------
step "Preparing local env files"
# copy_local <relative path> [example relative path]
# Keeps an existing file, else copies the main checkout's copy, else the example.
copy_local() {
  rel=$1
  example=${2:-}
  if [ -e "$ROOT_DIR/$rel" ]; then
    echo "keeping   $rel"
  elif [ "$MAIN_DIR" != "$ROOT_DIR" ] && [ -f "$MAIN_DIR/$rel" ]; then
    cp "$MAIN_DIR/$rel" "$ROOT_DIR/$rel"
    echo "copied    $rel (from main checkout)"
  elif [ -n "$example" ] && [ -f "$ROOT_DIR/$example" ]; then
    cp "$ROOT_DIR/$example" "$ROOT_DIR/$rel"
    echo "created   $rel (from $example)"
  fi
}
copy_local apps/backend/.env apps/backend/.env.example
copy_local apps/backend/.mcp.env
copy_local apps/pwa/.env.local
copy_local apps/pwa/.dev.vars

# --- Backend configuration ----------------------------------------------------
# Load the settings exactly as the backend will (environment plus the .env
# just put in place); an invalid value would stop uvicorn from starting.
step "Checking backend configuration"
SOLVER_FALLBACK=$(solver_fallback_enabled "$BACKEND_DIR" "$VENV_PY") \
  || fail "backend configuration does not load (check apps/backend/.env): ${SOLVER_FALLBACK#error: }"
echo "settings load; postflop solver fallback enabled: $SOLVER_FALLBACK"

# --- Rust solver (best-effort) -----------------------------------------------
step "Building the postflop solver"
SOLVER_STAMP="$SOLVER_DIR/target/release/.poker-hero-solver-tree"
# The solver's git tree hash identifies its sources; "clean" means the worktree
# has no local changes under solver-plugins/postflop.
solver_tree=$(git -C "$ROOT_DIR" rev-parse "HEAD:solver-plugins/postflop" 2>/dev/null || true)
solver_clean=no
if [ -n "$solver_tree" ] \
  && [ -z "$(git -C "$ROOT_DIR" status --porcelain -- solver-plugins/postflop)" ]; then
  solver_clean=yes
fi
if command -v cargo >/dev/null 2>&1; then
  # Workspaces whose solver sources are identical (same tree hash, clean) share
  # one Cargo target dir under the user's cache, so the common case is a no-op
  # build plus a copy of the binary into this worktree (the path
  # `pnpm backend:dev` expects). Any other state builds privately in the
  # worktree. Different sources never share a target dir, so cargo's
  # mtime-based freshness and the post-build copy cannot mix up workspaces.
  # The cache (~/.cache/poker-hero/solver-target) is safe to delete anytime.
  if [ "$solver_clean" = yes ]; then
    target_dir="${XDG_CACHE_HOME:-$HOME/.cache}/poker-hero/solver-target/$solver_tree"
  else
    target_dir="$SOLVER_DIR/target"
  fi
  CARGO_TARGET_DIR="$target_dir" \
    cargo build --locked --release --manifest-path "$SOLVER_DIR/Cargo.toml"
  if [ "$target_dir" != "$SOLVER_DIR/target" ]; then
    mkdir -p "$SOLVER_DIR/target/release"
    cp -f "$target_dir/release/$SOLVER_BIN_NAME" "$SOLVER_BIN"
  fi
  [ -x "$SOLVER_BIN" ] || fail "solver build did not produce $SOLVER_BIN"
  # Record which sources the binary came from, so a later run without cargo
  # can tell whether it is still valid. The stamp is written after the binary
  # on purpose: a binary rebuilt later (newer than the stamp) invalidates it.
  if [ "$solver_clean" = yes ]; then
    printf '%s\n' "$solver_tree" > "$SOLVER_STAMP"
  else
    rm -f "$SOLVER_STAMP"
  fi
else
  if [ -x "$SOLVER_BIN" ]; then
    if [ "$solver_clean" = yes ] && [ "$(cat "$SOLVER_STAMP" 2>/dev/null)" = "$solver_tree" ] \
      && [ -z "$(find "$SOLVER_BIN" -newer "$SOLVER_STAMP" 2>/dev/null)" ]; then
      warn "cargo not found; keeping the solver binary previously built from these exact sources."
    else
      rm -f "$SOLVER_BIN" "$SOLVER_STAMP"
      warn "cargo not found: removed a solver binary that no longer matches this worktree's sources."
    fi
  fi
  if [ ! -x "$SOLVER_BIN" ]; then
    warn "cargo not found: skipping the postflop solver build."
    if [ "$SOLVER_FALLBACK" = yes ]; then
      warn "The backend still runs; recommendations use the built-in fallback"
      warn "(POKER_POSTFLOP_SOLVER_FALLBACK_ENABLED=true)."
    else
      warn "POKER_POSTFLOP_SOLVER_FALLBACK_ENABLED is false, so postflop"
      warn "recommendations will fail until the solver is built."
    fi
    warn "Install Rust 1.85+ (https://rustup.rs) and re-run ./.superset/setup.sh to enable it."
  fi
fi

step "Workspace ready"
echo "Use the Run button (./.superset/run.sh) to start the API and PWA together;"
echo "it uses the postflop solver binary only while it matches the current sources."
echo "The manual 'pnpm backend:dev' puts whatever is in solver-plugins/postflop/target/release"
echo "on PATH unconditionally, so re-run ./.superset/setup.sh after changing the solver"
echo "before using it ('pnpm pwa:dev' is unaffected)."
