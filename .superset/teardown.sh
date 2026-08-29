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

# Exact argument boundaries matter: a process is matched only when a whole
# argument is a worktree script path, never when an argument merely contains
# it (after a space, a newline, ...). The exact argv is read and classified
# in one Python helper — NUL-separated /proc/<pid>/cmdline on Linux,
# sysctl(KERN_PROCARGS2) on macOS — using the backend venv's interpreter,
# else python3. Only when no Python exists at all does the space-joined `ps`
# output serve as a last resort.
CLASSIFY_PYTHON="$ROOT_DIR/apps/backend/.venv/bin/python"
[ -x "$CLASSIFY_PYTHON" ] || CLASSIFY_PYTHON=$(command -v python3 2>/dev/null || true)

# classify_pid <pid>: prints "path" (an executable or node script living in
# this worktree), "cwd" (python running uvicorn or one of its multiprocessing
# workers; the working directory still has to be checked) or nothing.
classify_pid() {
  if [ -n "$CLASSIFY_PYTHON" ]; then
    "$CLASSIFY_PYTHON" - "$1" "$ROOT_DIR" <<'PY'
import ctypes, ctypes.util, re, struct, sys


def read_argv(pid):
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as fh:
            raw = fh.read()
    except OSError:
        raw = b""
    if raw:
        parts = raw.split(b"\0")
        if parts and parts[-1] == b"":
            parts.pop()
        return parts
    if sys.platform != "darwin":
        return []
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
    size = ctypes.c_size_t(0)
    if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
        return []
    buf = ctypes.create_string_buffer(size.value)
    if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
        return []
    raw = buf.raw[: size.value]
    argc = struct.unpack("=i", raw[:4])[0]
    rest = raw[4:]
    cut = rest.find(b"\0")  # the executable path comes first, NUL-padded
    rest = rest[cut:].lstrip(b"\0") if cut >= 0 else b""
    return rest.split(b"\0")[:argc]


def classify(argv, root):
    if not argv:
        return ""
    argv = [a.decode("utf-8", "replace") for a in argv]
    argv0, rest = argv[0], argv[1:]
    base = argv0.rsplit("/", 1)[-1]
    worktree = (root + "/apps/backend/.venv/", root + "/node_modules/",
                root + "/apps/pwa/node_modules/", root + "/solver-plugins/")
    scripts = (root + "/node_modules/", root + "/apps/pwa/node_modules/")
    if argv0.startswith(worktree):
        return "path"
    if base == "node" and any(a.startswith(scripts) for a in rest):
        return "path"
    if re.fullmatch(r"[Pp]ython[0-9.]*", base) and (
        rest[:2] == ["-m", "uvicorn"]
        or (len(rest) > 1 and rest[0] == "-c" and rest[1].startswith("from multiprocessing."))
    ):
        return "cwd"
    return ""


if sys.argv[1] == "--stdin":  # test hook: NUL-separated argv on stdin
    print(classify(sys.stdin.buffer.read().split(b"\0"), sys.argv[2]))
else:
    print(classify(read_argv(int(sys.argv[1])), sys.argv[2]))
PY
  else
    classify_pid_ps "$1"
  fi
}

# classify_pid_ps <pid>: the lossy last resort without Python — `ps` joins
# arguments with spaces, so a script path is required to start an argument
# as far as that output can tell.
classify_pid_ps() {
  argv0=$(ps -o comm= -p "$1" 2>/dev/null) || return 0
  args=$(ps -o command= -p "$1" 2>/dev/null)
  args=${args#"$argv0"}
  args=${args# }
  case $argv0 in
    "$ROOT_DIR/apps/backend/.venv/"* | "$ROOT_DIR/node_modules/"* \
      | "$ROOT_DIR/apps/pwa/node_modules/"* | "$ROOT_DIR/solver-plugins/"*)
      echo path ;;
    node | */node)
      case " $args" in
        *" $ROOT_DIR/node_modules/"* | *" $ROOT_DIR/apps/pwa/node_modules/"*) echo path ;;
      esac ;;
    python | python[0-9]* | */python | */python[0-9]* | Python | */Python)
      case $args in
        "-m uvicorn" | "-m uvicorn "* | "-c from multiprocessing."*) echo cwd ;;
      esac ;;
  esac
}

# Snapshot first so the filtering below cannot match its own processes, then
# prefilter cheaply on the full command line; exact classification follows.
snapshot=$(ps -axo pid=,command= 2>/dev/null) || exit 0
candidates=$(printf '%s\n' "$snapshot" | awk -v root="$ROOT_DIR" -v self="$$" '
  $1 != self && (index($0, root) || index($0, "uvicorn") || index($0, "multiprocessing.")) { print $1 }')

pids=""
for pid in $candidates; do
  case "$(classify_pid "$pid")" in
    path) pids="$pids $pid" ;;
    cwd)
      case "$(cwd_of "$pid")" in
        "$ROOT_DIR" | "$ROOT_DIR"/*) pids="$pids $pid" ;;
      esac ;;
  esac
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
