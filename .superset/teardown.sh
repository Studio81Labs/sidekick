#!/bin/sh
# Superset workspace teardown for Poker Hero.
#
# Setup starts no services and installs everything inside the worktree (which
# Superset deletes), so the only thing to undo is dev servers still running
# from this workspace: left alone they would keep their ports and serve code
# from a deleted directory. Best-effort; never fails the workspace delete.
#
# Dev servers are recognised by what they *are*, never by text that merely
# mentions the workspace (an agent prompt, an editor argument):
#   - executables living inside this worktree (venv python, esbuild, ...)
#   - `node` running a script from this worktree (vite)
#   - `python -m uvicorn` and its multiprocessing workers whose working
#     directory is inside this worktree (macOS framework Python rewrites
#     argv[0], so the venv path never shows up in `ps` for these)
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

# Snapshot first so the filtering below cannot match its own processes.
snapshot=$(ps -axo pid=,command= 2>/dev/null) || exit 0

# One "<kind>:<pid>" per candidate; kind "cwd" still needs the directory check.
candidates=$(printf '%s\n' "$snapshot" | awk -v root="$ROOT_DIR" -v self="$$" '
  $1 == self { next }
  {
    argv0 = $2
    if (index(argv0, root "/apps/backend/.venv/") == 1 \
        || index(argv0, root "/node_modules/") == 1 \
        || index(argv0, root "/apps/pwa/node_modules/") == 1) {
      print "path:" $1; next
    }
    if (argv0 ~ /(^|\/)node$/ \
        && (index($0, root "/node_modules/") || index($0, root "/apps/pwa/node_modules/"))) {
      print "path:" $1; next
    }
    if (argv0 ~ /(^|\/)[Pp]ython[0-9.]*$/ \
        && (($3 == "-m" && $4 == "uvicorn") \
            || ($3 == "-c" && $4 == "from" && $5 ~ /^multiprocessing\./))) {
      print "cwd:" $1; next
    }
  }')

pids=""
for entry in $candidates; do
  pid=${entry#*:}
  case $entry in
    path:*) pids="$pids $pid" ;;
    cwd:*)
      case "$(cwd_of "$pid")" in
        "$ROOT_DIR" | "$ROOT_DIR"/*) pids="$pids $pid" ;;
      esac ;;
  esac
done

if [ -z "$pids" ]; then
  echo "No dev-server processes running from this workspace."
  exit 0
fi

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
