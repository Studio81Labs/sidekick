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

# ensure_node <root>: Superset's setup and Run processes may not load the
# interactive shell rc, so expose the usual per-user tool locations (pnpm
# standalone, rustup) and, when node is missing or too old, prepend the nvm
# install matching .nvmrc. Exports PATH and sets WANTED_NODE; fails when node
# is still unsuitable.
ensure_node() {
  WANTED_NODE=$(wanted_node_major "$1")
  PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if ! node_ok "$WANTED_NODE"; then
    for candidate in "${NVM_DIR:-$HOME/.nvm}"/versions/node/v"$WANTED_NODE".*/bin; do
      [ -x "$candidate/node" ] && PATH="$candidate:$PATH"
    done
  fi
  export PATH
  node_ok "$WANTED_NODE"
}
