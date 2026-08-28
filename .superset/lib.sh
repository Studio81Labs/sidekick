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

# nvm_bin_dirs <major> <executable>: the bin directories of nvm-managed Node
# installs (at least <major>) that contain <executable>, best first: installs
# of exactly that major (the .nvmrc choice) newest first, then compatible
# higher majors newest first.
nvm_bin_dirs() {
  for dir in "${NVM_DIR:-$HOME/.nvm}"/versions/node/v*/bin; do
    [ -x "$dir/$2" ] || continue
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
  done | sort -k1,1nr -k2,2nr | cut -d' ' -f3-
}

# nvm_bin_dir <major> <executable>: the best of the above, or nothing.
nvm_bin_dir() {
  nvm_bin_dirs "$1" "$2" | head -n 1
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
    nvm_bin=$(nvm_bin_dir "$WANTED_NODE" node)
    [ -n "$nvm_bin" ] && PATH="$nvm_bin:$PATH"
  fi
  export PATH
  node_ok "$WANTED_NODE"
}

# wanted_pnpm_major <root>: the pnpm major from package.json's packageManager
# field (engines says pnpm >=11), defaulting to 11.
wanted_pnpm_major() {
  major=$(sed -n 's/^[[:space:]]*"packageManager":[[:space:]]*"pnpm@\([0-9][0-9]*\).*/\1/p' "$1/package.json" 2>/dev/null)
  echo "${major:-11}"
}

# pnpm_version_ok <executable> <major>: succeeds when that pnpm is at least
# that major.
pnpm_version_ok() {
  have=$("$1" --version 2>/dev/null | sed -n 's/^\([0-9][0-9]*\).*/\1/p')
  [ "${have:-0}" -ge "$2" ] 2>/dev/null
}

# ensure_pnpm <root>: sets PNPM to a pnpm executable of at least the major
# from package.json: the one on PATH when it is recent enough, otherwise one
# installed beside an nvm-managed Node (global install or corepack shim),
# preferring installs compatible with WANTED_NODE. PATH is left alone, so an
# older pnpm ahead on PATH is simply bypassed and no other node gets in front
# of the one already chosen. Fails when none qualifies.
# shellcheck disable=SC2034  # PNPM is consumed by the sourcing script
ensure_pnpm() {
  WANTED_PNPM=$(wanted_pnpm_major "$1")
  PNPM=""
  if command -v pnpm >/dev/null 2>&1 && pnpm_version_ok pnpm "$WANTED_PNPM"; then
    PNPM=$(command -v pnpm)
    return 0
  fi
  candidates=$(nvm_bin_dirs "${WANTED_NODE:-0}" pnpm; nvm_bin_dirs 0 pnpm)
  while IFS= read -r dir; do
    [ -n "$dir" ] || continue
    if pnpm_version_ok "$dir/pnpm" "$WANTED_PNPM"; then
      PNPM="$dir/pnpm"
      return 0
    fi
  done <<EOF
$candidates
EOF
  return 1
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
