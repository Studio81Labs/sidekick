#!/bin/sh
# Superset workspace teardown for Poker Hero.
#
# Setup starts no services and installs everything inside the worktree (which
# Superset deletes), so the only thing to undo is dev servers still running
# from this workspace: left alone they would keep their ports and serve code
# from a deleted directory. Best-effort; never fails the workspace delete.
#
# Dev servers are recognised by what they *are* (argv[0] and arguments), never
# by text that merely mentions the workspace (an agent prompt, an editor arg):
#   - executables living inside this worktree (venv python, esbuild, the
#     postflop solver, ...)
#   - `node` running a script from this worktree (vite)
#   - `python -m uvicorn` and its multiprocessing workers whose working
#     directory is inside this worktree (macOS framework Python rewrites
#     argv[0], so the venv path never shows up in `ps` for these)
# plus everything those processes spawned (solver runs, esbuild, ...).
set -u

ROOT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")/.." 2>/dev/null && pwd -P) \
  || ROOT_DIR="${SUPERSET_WORKSPACE_PATH:-}"
[ -n "$ROOT_DIR" ] || exit 0

# cwd_of <pid>: the process's working directory (Linux /proc, else lsof).
cwd_of() {
  if [ -r "/proc/$1/cwd" ]; then
    readlink "/proc/$1/cwd" 2>/dev/null
  elif command -v lsof >/dev/null 2>&1; then
    lsof -a -d cwd -p "$1" -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1
  fi
}

# argv_of <pid>: sets ARGV0 (argv[0] verbatim, spaces included) and ARGS (the
# remaining arguments, space-joined). Linux reads /proc; on macOS `ps -o comm`
# is argv[0] verbatim and `ps -o command` is argv[0] followed by the arguments.
argv_of() {
  if [ -r "/proc/$1/cmdline" ]; then
    ARGV0=$(tr '\0' '\n' < "/proc/$1/cmdline" | head -n 1)
    ARGS=$(tr '\0' ' ' < "/proc/$1/cmdline")
  else
    ARGV0=$(ps -o comm= -p "$1" 2>/dev/null) || return 1
    ARGS=$(ps -o command= -p "$1" 2>/dev/null)
  fi
  [ -n "$ARGV0" ] || return 1
  ARGS=${ARGS#"$ARGV0"}
  ARGS=${ARGS# }
}

# Snapshot first so the filtering below cannot match its own processes, then
# prefilter cheaply on the full command line; exact classification follows.
snapshot=$(ps -axo pid=,command= 2>/dev/null) || exit 0
candidates=$(printf '%s\n' "$snapshot" | awk -v root="$ROOT_DIR" -v self="$$" '
  $1 != self && (index($0, root) || index($0, "uvicorn") || index($0, "multiprocessing.")) { print $1 }')

pids=""
for pid in $candidates; do
  argv_of "$pid" || continue
  kind=""
  case $ARGV0 in
    "$ROOT_DIR/apps/backend/.venv/"* | "$ROOT_DIR/node_modules/"* \
      | "$ROOT_DIR/apps/pwa/node_modules/"* | "$ROOT_DIR/solver-plugins/"*)
      kind=path ;;
    node | */node)
      case $ARGS in
        *"$ROOT_DIR/node_modules/"* | *"$ROOT_DIR/apps/pwa/node_modules/"*) kind=path ;;
      esac ;;
    python | python[0-9]* | */python | */python[0-9]* | Python | */Python)
      case $ARGS in
        "-m uvicorn" | "-m uvicorn "* | "-c from multiprocessing."*)
          case "$(cwd_of "$pid")" in
            "$ROOT_DIR" | "$ROOT_DIR"/*) kind=cwd ;;
          esac ;;
      esac ;;
  esac
  [ -n "$kind" ] && pids="$pids $pid"
done

if [ -z "$pids" ]; then
  echo "No dev-server processes running from this workspace."
  exit 0
fi

# Add everything the matched processes spawned, recursively (an in-flight
# solver run, esbuild, OCR helpers), so no part of the tree is left behind.
pids=$(ps -axo pid=,ppid= 2>/dev/null | awk -v seeds="$pids" -v self="$$" '
  BEGIN { n = split(seeds, a, " "); for (i = 1; i <= n; i++) if (a[i] != "") want[a[i]] = 1 }
  { parent[$1] = $2 }
  END {
    changed = 1
    while (changed) {
      changed = 0
      for (p in parent)
        if (!(p in want) && (parent[p] in want) && p != self) { want[p] = 1; changed = 1 }
    }
    for (p in want) printf "%s ", p
  }')

echo "Stopping dev-server processes still running from this workspace:"
printf '%s\n' "$snapshot" | awk -v list="$pids" '
  BEGIN { n = split(list, a, " "); for (i = 1; i <= n; i++) if (a[i] != "") want[a[i]] = 1 }
  ($1 in want) { print "  " substr($0, 1, 160) }'

# shellcheck disable=SC2086
kill $pids 2>/dev/null || true
alive=""
for _ in 1 2 3 4 5; do
  alive=""
  for pid in $pids; do
    kill -0 "$pid" 2>/dev/null && alive="$alive $pid"
  done
  [ -z "$alive" ] && break
  sleep 1
done
if [ -n "$alive" ]; then
  # shellcheck disable=SC2086
  kill -9 $alive 2>/dev/null || true
fi
exit 0
