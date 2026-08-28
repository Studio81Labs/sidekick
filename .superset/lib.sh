#!/bin/sh
# Shared helpers for the Superset lifecycle scripts in this directory.
# Sourced by setup.sh and run.sh; not meant to be executed.

# wanted_node_major <root>: the Node major required by <root>/.nvmrc
# (package.json engines: node >=24), defaulting to 24.
wanted_node_major() {
  major=$(sed -n '1s/^v\{0,1\}\([0-9][0-9]*\).*/\1/p' "$1/.nvmrc" 2>/dev/null)
  echo "${major:-24}"
}

# node_ok <major>: succeeds when the node on PATH is at least that major.
node_ok() {
  command -v node >/dev/null 2>&1 || return 1
  have=$(node --version 2>/dev/null | sed -n 's/^v\([0-9][0-9]*\).*/\1/p')
  [ "${have:-0}" -ge "$1" ] 2>/dev/null
}

# node_found: the node version on PATH, or "none", for error messages.
node_found() {
  node --version 2>/dev/null || echo none
}

# nvm_node_bin <major>: the bin directory of the best nvm-managed Node that
# satisfies "at least <major>": the newest install of exactly that major (the
# .nvmrc choice) when there is one, else the newest compatible higher major.
nvm_node_bin() {
  for dir in "${NVM_DIR:-$HOME/.nvm}"/versions/node/v*/bin; do
    [ -x "$dir/node" ] || continue
    ver=${dir%/bin}
    ver=${ver##*/v}
    major=${ver%%.*}
    rest=${ver#*.}
    minor=${rest%%.*}
    patch=${rest#*.}
    patch=${patch%%[!0-9]*}
    case "$major$minor$patch" in *[!0-9]* | '') continue ;; esac
    [ "$major" -ge "$1" ] || continue
    if [ "$major" -eq "$1" ]; then rank=1; else rank=0; fi
    printf '%d %d %s\n' "$rank" "$((major * 1000000 + minor * 1000 + patch))" "$dir"
  done | sort -k1,1nr -k2,2nr | head -n 1 | cut -d' ' -f3-
}

# ensure_node <root>: Superset's setup and Run processes may not load the
# interactive shell rc, so make the usual per-user tool locations (pnpm
# standalone, rustup) reachable — appended, so they never shadow a suitable
# tool already on PATH — and, when node is missing or too old, prepend the
# best compatible nvm install. Exports PATH and sets WANTED_NODE; fails when
# node is still unsuitable.
ensure_node() {
  WANTED_NODE=$(wanted_node_major "$1")
  PATH="$PATH:$HOME/.local/bin:$HOME/.cargo/bin"
  if ! node_ok "$WANTED_NODE"; then
    nvm_bin=$(nvm_node_bin "$WANTED_NODE")
    [ -n "$nvm_bin" ] && PATH="$nvm_bin:$PATH"
  fi
  export PATH
  node_ok "$WANTED_NODE"
}

# solver_fallback_enabled <backend dir> <venv python>: prints "yes" or "no",
# read through the backend's own settings loader (environment plus the .env
# file in the backend dir), so it reflects what the backend will actually do.
# When the settings cannot be loaded — the backend would fail to start the
# same way — prints "error: <diagnostic>" and fails.
solver_fallback_enabled() {
  (cd "$1" && "$2" - <<'PY'
import sys
try:
    from app.config import get_settings
    print("yes" if get_settings().postflop_solver_fallback_enabled else "no")
except Exception as exc:  # validation error, import error, ...
    detail = " ".join(line.strip() for line in str(exc).splitlines() if line.strip())
    print("error: " + (detail or type(exc).__name__)[:400])
    sys.exit(1)
PY
  )
}
