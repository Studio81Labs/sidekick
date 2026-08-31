# Local Player Runtime and Store Foundation

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
is used. The directory must be owned by the current user and have no group or
world permissions (mode `0700` on Unix-like systems). A newly created directory
uses that mode; an existing shared directory is rejected rather than changed
silently. On macOS, extended ACL entries are also rejected because they can
grant access not represented by the mode bits.

The runtime creates `.player-runtime-key` there with owner-only file
permissions and opens only the V2 imported-hand store under `imported-hands/`.
That store directory must satisfy the same ownership, mode, and macOS ACL
checks. The runtime does not open the V1 screenshot-job or benchmark stores. Do
not copy the key into browser storage, a URL, logs, or a hosted deployment.

## Start and stop

Run:

```bash
pnpm player:start
```

The command binds only to `127.0.0.1:8765`, starts with proxy-header handling
disabled, and opens the default browser with a short-lived ticket in the URL
fragment. The page removes the fragment, creates a process-local authenticated
session, and reports whether the boundary and player store are ready. The
authenticated page displays the resolved data location. Stop the service with
`Ctrl-C`; all browser sessions expire when the process exits.

Before listening, the runtime recovers interrupted imported-hand cascades under
the data-volume lock. The authenticated `/api/player/storage` status preserves
completed, quarantined, and failed recovery identifiers separately. A
quarantined or failed recovery is shown as requiring attention; completed
roll-forward recovery alone remains ready.

There is intentionally no player-runtime host or port flag. A non-loopback
operator development service would be a different runtime and would require
TLS plus its own server-enforced authorization design.

## Current limit

This foundation exposes authenticated session lifecycle, health, and read-only
store status under `/api/player`. The imported-hand store is opened and
recovered, but there is no hand-history import, record read, approval, learning,
backup, restore, migration, remote lookup, or player workflow. The hosted
Worker and V1 FastAPI deployment deny the namespace. Do not use this command as
evidence that the Phase 1 gate or issue #432 is complete.
