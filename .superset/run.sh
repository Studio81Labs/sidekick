#!/bin/sh
# Superset "Run" command for Poker Hero: starts the FastAPI backend (uvicorn
# with --reload) and the Vite PWA dev server together in one pane, using the
# same commands as `pnpm backend:dev` and `pnpm pwa:dev`.
#
# Every workspace gets its own ports so several workspaces can run at once. The
# defaults (API 8000, PWA 5173) are used when free; otherwise the next free ports
# are taken. Ports are claimed under a lock in a per-user directory so workspaces
# started at the same moment cannot collide, and CORS plus the PWA's API URL are
# wired to the chosen ports automatically (a custom POKER_CORS_ORIGINS in
# apps/backend/.env is not used here; run `pnpm backend:dev` for that).
# Preferred ports can be overridden with POKER_BACKEND_PORT / POKER_PWA_PORT.
set -eu

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
BACKEND_DIR="$ROOT_DIR/apps/backend"
PWA_DIR="$ROOT_DIR/apps/pwa"
VENV_PY="$BACKEND_DIR/.venv/bin/python"
VITE_BIN="$PWA_DIR/node_modules/.bin/vite"
SOLVER_BIN_DIR="$ROOT_DIR/solver-plugins/postflop/target/release"
# Per-user claims directory: the XDG runtime dir when available, else a
# uid-suffixed temp dir (TMPDIR is per-user on macOS but often unset on Linux).
PORT_CLAIMS="${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/poker-hero-dev-ports-$(id -u)"

[ -x "$VENV_PY" ] || { echo "Backend virtualenv missing; run ./.superset/setup.sh first" >&2; exit 1; }
[ -x "$VITE_BIN" ] || { echo "PWA dependencies missing; run ./.superset/setup.sh first" >&2; exit 1; }

# pick_ports <preferred>...: prints one free port per argument (the preferred
# one, or the next free above it). Each port is recorded in $PORT_CLAIMS as a
# file named after the port holding this script's PID; claims of dead processes
# are reclaimed. Checking and claiming happen under an advisory lock that the
# kernel releases if its holder dies, so concurrent Run commands never pick the
# same port, even while reclaiming a stale claim.
pick_ports() {
  "$VENV_PY" - "$PORT_CLAIMS" "$$" "$@" <<'PY'
import errno, fcntl, os, socket, sys

claims_dir, owner_pid, preferred = sys.argv[1], sys.argv[2], sys.argv[3:]
os.makedirs(claims_dir, mode=0o700, exist_ok=True)


def is_free(port):
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.bind((host, port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                return False
    return True


def is_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def claim(port):
    path = os.path.join(claims_dir, str(port))
    try:
        with open(path) as fh:
            holder = int(fh.read().strip() or 0)
    except FileNotFoundError:
        holder = 0
    except (OSError, ValueError):
        holder = 0  # unreadable or garbage: no live process can rely on it
    if holder and holder != int(owner_pid) and is_alive(holder):
        return False
    with open(path, "w") as fh:
        fh.write(owner_pid + "\n")
    return True


chosen = []
with open(os.path.join(claims_dir, ".lock"), "a+") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    for wanted in preferred:
        port = int(wanted)
        while port in chosen or not (is_free(port) and claim(port)):
            port += 1
        chosen.append(port)
print(" ".join(map(str, chosen)))
PY
}

ports=$(pick_ports "${POKER_BACKEND_PORT:-8000}" "${POKER_PWA_PORT:-5173}")
BACKEND_PORT=${ports%% *}
PWA_PORT=${ports##* }
BACKEND_URL="http://localhost:$BACKEND_PORT"
PWA_URL="http://localhost:$PWA_PORT"

BACKEND_PID=""
PWA_PID=""
# shellcheck disable=SC2329  # invoked via trap
cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  for pid in $BACKEND_PID $PWA_PID; do
    kill "$pid" >/dev/null 2>&1 || true
  done
  for pid in $BACKEND_PID $PWA_PID; do
    wait "$pid" >/dev/null 2>&1 || true
  done
  rm -f "$PORT_CLAIMS/$BACKEND_PORT" "$PORT_CLAIMS/$PWA_PORT"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

# Backend, as in `pnpm backend:dev` (solver on PATH, run from apps/backend so
# .env and the data/ directory resolve). CORS follows the PWA port.
(
  cd "$BACKEND_DIR" || exit 1
  PATH="$SOLVER_BIN_DIR:$PATH"
  POKER_CORS_ORIGINS=$(printf '["http://localhost:%s","http://127.0.0.1:%s"]' "$PWA_PORT" "$PWA_PORT")
  export PATH POKER_CORS_ORIGINS
  exec "$VENV_PY" -m uvicorn app.main:app --reload --host localhost --port "$BACKEND_PORT"
) &
BACKEND_PID=$!

# PWA, as in `pnpm pwa:dev`, pointed at this workspace's backend.
(
  cd "$PWA_DIR" || exit 1
  VITE_API_BASE_URL="$BACKEND_URL"
  export VITE_API_BASE_URL
  exec "$VITE_BIN" --host localhost --port "$PWA_PORT" --strictPort
) &
PWA_PID=$!

printf '\nPoker Hero dev servers  [%s]\n' "$(basename "$ROOT_DIR")"
printf '  PWA  %s\n' "$PWA_URL"
printf '  API  %s   (OpenAPI docs: %s/docs)\n' "$BACKEND_URL" "$BACKEND_URL"
[ -x "$SOLVER_BIN_DIR/poker-postflop-solver" ] \
  || printf '  note: postflop solver binary not built; using recommendation fallback\n'
printf 'Ctrl-C stops both.\n\n'

# Wait for either server to exit; the trap then stops the other one.
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$PWA_PID" 2>/dev/null; do
  sleep 1
done
echo "A dev server exited; stopping the other." >&2
exit 1
