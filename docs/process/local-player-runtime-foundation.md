# Local Player Runtime Foundation

The local player command starts the isolated security substrate defined by
[ADR 0050](../decisions/0050-establish-local-player-runtime-security-substrate.md).
It is a development checkpoint for the V2 runtime boundary, not the completed
V2 player product.

## Prerequisites

Bootstrap the repository so `apps/backend/.venv` and the pinned dependencies
exist:

```bash
pnpm bootstrap
```

`POKER_DATA_DIR` selects the player-controlled local data directory. If it is
not set, the backend default is `apps/backend/data` when the workspace command
is used. The runtime creates `.player-runtime-key` there with owner-only file
permissions. Do not copy this file into browser storage, a URL, logs, or a
hosted deployment.

## Start and stop

Run:

```bash
pnpm player:start
```

The command binds only to `127.0.0.1:8765`, starts with proxy-header handling
disabled, and opens the default browser with a short-lived ticket in the URL
fragment. The page removes the fragment, creates a process-local authenticated
session, and reports whether the boundary is ready. Stop the service with
`Ctrl-C`; all browser sessions expire when the process exits.

There is intentionally no player-runtime host or port flag. A non-loopback
operator development service would be a different runtime and would require
TLS plus its own server-enforced authorization design.

## Current limit

This foundation exposes only authenticated session lifecycle and health under
`/api/player`. It has no hand-history import, approval, learning, persistence,
backup, restore, migration, remote lookup, or player workflow. The hosted
Worker and V1 FastAPI deployment deny the namespace. Do not use this command as
evidence that the Phase 1 gate or issue #432 is complete.
