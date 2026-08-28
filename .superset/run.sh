#!/bin/sh
# Superset "Run" command for Poker Hero: starts the FastAPI backend (uvicorn
# with --reload) and the Vite PWA dev server together in one pane, using the
# same commands as `pnpm backend:dev` and `pnpm pwa:dev`.
#
# Every workspace gets its own ports so several workspaces can run at once. The
# defaults (API 8000, PWA 5173) are used when free; otherwise the next free ports
# are taken. Ports are claimed under a lock in a per-user directory so workspaces
# started at the same moment cannot collide, and CORS plus the PWA's API URL are
# wired to the chosen ports automatically, and the backend is pointed at this
# worktree's solver binary explicitly (a custom POKER_CORS_ORIGINS or
# POKER_POSTFLOP_SOLVER_COMMAND in apps/backend/.env is not used here; run
# `pnpm backend:dev` for those).
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
# It is verified to be a private directory owned by this user before use.
PORT_CLAIMS="${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/poker-hero-dev-ports-$(id -u)"

[ -x "$VENV_PY" ] || { echo "Backend virtualenv missing; run ./.superset/setup.sh first" >&2; exit 1; }
[ -x "$VITE_BIN" ] || { echo "PWA dependencies missing; run ./.superset/setup.sh first" >&2; exit 1; }

# The Run pane may not load the interactive shell rc either, and the vite
# launcher resolves `node` from PATH, so pick Node the same way setup does.
# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$ROOT_DIR/.superset/lib.sh"
ensure_node "$ROOT_DIR" \
  || { echo "Node.js $WANTED_NODE+ is required, found $(node_found) (see .nvmrc)" >&2; exit 1; }

# Load the backend settings once, exactly as the backend will: this also
# catches an invalid apps/backend/.env before anything is launched.
SOLVER_FALLBACK=$(solver_fallback_enabled "$BACKEND_DIR" "$VENV_PY") \
  || { echo "Backend configuration does not load (check apps/backend/.env): ${SOLVER_FALLBACK#error: }" >&2; exit 1; }

# pick_ports <preferred>...: prints one free port per argument (the preferred
# one, or the next free above it). Each port is recorded in $PORT_CLAIMS as a
# file named after the port holding this script's PID; claims of dead processes
# are reclaimed. Checking and claiming happen under an advisory lock that the
# kernel releases if its holder dies, so concurrent Run commands never pick the
# same port, even while reclaiming a stale claim.
pick_ports() {
  "$VENV_PY" - "$PORT_CLAIMS" "$$" "$@" <<'PY'
import errno, fcntl, os, socket, stat, sys

claims_dir, owner_pid, preferred = sys.argv[1], sys.argv[2], sys.argv[3:]

# The directory must be ours and private: a pre-created or shared directory
# (possible for the /tmp fallback on multi-user hosts) could carry planted
# entries, so refuse anything that is not a 0700 directory owned by this user.
os.makedirs(claims_dir, mode=0o700, exist_ok=True)
info = os.lstat(claims_dir)
if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
    sys.exit(
        f"refusing to use {claims_dir}: it must be a directory owned by you with "
        "mode 0700 (remove it, or point XDG_RUNTIME_DIR or TMPDIR at a private directory)"
    )
NOFOLLOW = os.O_NOFOLLOW | os.O_CLOEXEC


def is_free(port):
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.bind((host, port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                return False
            if exc.errno in (errno.EADDRNOTAVAIL, errno.EAFNOSUPPORT):
                continue  # this address family is not available here
            if exc.errno in (errno.EACCES, errno.EPERM):
                sys.exit(f"port {port} is not permitted for this user ({exc.strerror}); "
                         "choose another with POKER_BACKEND_PORT / POKER_PWA_PORT")
            sys.exit(f"cannot test port {port} on {host}: {exc}")
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
        entry = os.lstat(path)
    except FileNotFoundError:
        entry = None
    if entry is not None and not stat.S_ISREG(entry.st_mode):
        os.unlink(path)  # links and other non-files are never followed or trusted
        entry = None
    holder = 0
    if entry is not None:
        with os.fdopen(os.open(path, os.O_RDONLY | NOFOLLOW)) as fh:
            try:
                holder = int(fh.read().strip() or 0)
            except ValueError:
                holder = 0  # garbage: no live process can rely on it
    if holder and holder != int(owner_pid) and is_alive(holder):
        return False
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | NOFOLLOW, 0o600), "w") as fh:
        fh.write(owner_pid + "\n")
    return True


chosen = []
try:
    lock_fd = os.open(os.path.join(claims_dir, ".lock"), os.O_RDWR | os.O_CREAT | NOFOLLOW, 0o600)
except OSError as exc:
    sys.exit(f"refusing to use the port lock in {claims_dir}: {exc}")
try:
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    for wanted in preferred:
        port = int(wanted)
        while port in chosen or not (is_free(port) and claim(port)):
            port += 1
        chosen.append(port)
finally:
    os.close(lock_fd)
print(" ".join(map(str, chosen)))
PY
}

ports=$(pick_ports "${POKER_BACKEND_PORT:-8000}" "${POKER_PWA_PORT:-5173}")
BACKEND_PORT=${ports%% *}
PWA_PORT=${ports##* }
BACKEND_URL="http://localhost:$BACKEND_PORT"
PWA_URL="http://localhost:$PWA_PORT"

# Solver selection. The backend is told exactly which solver to run, as an
# absolute path rather than a PATH lookup: this worktree's binary when it is
# current, otherwise a path that cannot exist (a child of /dev/null) so the
# backend's fallback engine runs and the reason shows up in its responses. A
# binary is current
# when setup stamped it with the tree hash of a clean tree that is still
# checked out (and the binary has not been rebuilt since the stamp), or when
# nothing under solver-plugins/postflop (directories included, so deletions
# count; target/ excluded) is newer than it.
SOLVER_BIN="$SOLVER_BIN_DIR/poker-postflop-solver"
SOLVER_SRC="$ROOT_DIR/solver-plugins/postflop"
SOLVER_STAMP="$SOLVER_BIN_DIR/.poker-hero-solver-tree"
solver_status() {
  [ -x "$SOLVER_BIN" ] || { echo missing; return; }
  tree=$(git -C "$ROOT_DIR" rev-parse "HEAD:solver-plugins/postflop" 2>/dev/null || true)
  if [ -n "$tree" ] && [ "$(cat "$SOLVER_STAMP" 2>/dev/null)" = "$tree" ] \
    && [ -z "$(find "$SOLVER_BIN" -newer "$SOLVER_STAMP" 2>/dev/null)" ] \
    && [ -z "$(git -C "$ROOT_DIR" status --porcelain -- solver-plugins/postflop)" ]; then
    echo ok
  elif [ -z "$(find "$SOLVER_SRC" -name target -prune -o -newer "$SOLVER_BIN" -print 2>/dev/null \
        | head -n 1)" ]; then
    echo ok
  else
    echo stale
  fi
}
SOLVER_STATUS=$(solver_status)
if [ "$SOLVER_STATUS" = ok ]; then
  SOLVER_COMMAND=$SOLVER_BIN
else
  # Unforgeable: nothing can be created below /dev/null, so this always fails
  # to launch (ENOTDIR) and the status is still readable in the error.
  SOLVER_COMMAND="/dev/null/poker-postflop-solver.$SOLVER_STATUS"
fi
# The setting is parsed with shlex, so single-quote it (paths may contain spaces).
# shellcheck disable=SC2089  # the quotes are meant literally, for shlex
SOLVER_COMMAND_QUOTED="'$(printf '%s' "$SOLVER_COMMAND" | sed "s/'/'\\\\''/g")'"

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

# Backend, as in `pnpm backend:dev` (run from apps/backend so .env and the
# data/ directory resolve); CORS follows the PWA port and the solver command
# is pinned as decided above.
(
  cd "$BACKEND_DIR" || exit 1
  POKER_CORS_ORIGINS=$(printf '["http://localhost:%s","http://127.0.0.1:%s"]' "$PWA_PORT" "$PWA_PORT")
  POKER_POSTFLOP_SOLVER_COMMAND=$SOLVER_COMMAND_QUOTED
  # shellcheck disable=SC2090  # see SOLVER_COMMAND_QUOTED
  export POKER_CORS_ORIGINS POKER_POSTFLOP_SOLVER_COMMAND
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
if [ "$SOLVER_STATUS" != ok ]; then
  if [ "$SOLVER_FALLBACK" = yes ]; then
    outcome="using the recommendation fallback"
  else
    outcome="POKER_POSTFLOP_SOLVER_FALLBACK_ENABLED is false, so postflop recommendations will fail"
  fi
  case $SOLVER_STATUS in
    missing) printf '  note: postflop solver binary not built; %s\n' "$outcome"
             printf '        (build it with ./.superset/setup.sh once Rust is installed)\n' ;;
    stale) printf '  note: postflop solver binary is older than its sources; %s\n' "$outcome"
           printf '        (rebuild with ./.superset/setup.sh, or cargo build --release in solver-plugins/postflop)\n' ;;
  esac
fi
printf 'Ctrl-C stops both.\n\n'

# Wait for either server to exit; the trap then stops the other one.
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$PWA_PID" 2>/dev/null; do
  sleep 1
done
echo "A dev server exited; stopping the other." >&2
exit 1
