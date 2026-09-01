# Local Player Runtime and Recovery PWA

The local player command starts the isolated security substrate defined by
[ADR 0050](../decisions/0050-establish-local-player-runtime-security-substrate.md).
The dedicated local player PWA delivery is defined by
[ADR 0053](../decisions/0053-serve-a-dedicated-local-player-pwa.md). It remains
a development checkpoint for the V2 runtime boundary, not the completed V2
player product.

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

The command first builds and verifies the dedicated player PWA, then binds only
to `127.0.0.1:8765`, starts with proxy-header handling disabled, and opens the
default browser with a short-lived ticket in the URL fragment. Use
`pnpm player:build` when only the player assets need rebuilding. The PWA removes
the fragment before exchanging it, creates a process-local authenticated
session, and reports whether the boundary and player store are ready. The
authenticated page displays the resolved data location. Stop the service with
`Ctrl-C`; all browser sessions expire when the process exits.

Before listening, the runtime recovers interrupted imported-hand cascades under
the data-volume lock. The authenticated `/api/player/storage` status preserves
completed, quarantined, and failed recovery identifiers separately. A
quarantined or failed recovery is shown as requiring attention; completed
roll-forward recovery alone remains ready.

## Imported-hand backup and restore

The authenticated player API can export the current V2 imported-hand store as a
checksummed `poker-hero-player-backup` ZIP from
`GET /api/player/backups/export`. Restore accepts that ZIP at
`POST /api/player/backups/restore`; like every player mutation, it requires the
exact local Origin, the process-local bearer session, and its matching CSRF
token. The local recovery PWA exposes both controls. **Download backup** streams
the archive to the browser. **Restore backup** sends the selected ZIP only to
the same-origin loopback API, blocks page unload while the non-replayable request
is active, and refreshes storage status after success. A lost or incomplete
response is potentially committed: the PWA clears the selected archive, blocks
an immediate retry, and refreshes only after the runtime finishes the in-flight
restore. Storage status takes the shared data-volume lock; if that bounded wait
cannot produce a stable snapshot, the UI keeps the restore outcome explicitly
unresolved, hides stale totals and backup controls, and requires restart before
export or retry. Status waits behind the restore asynchronously before it uses
the shared worker pool, so queued refreshes cannot prevent restore completion. A
`503` restore storage failure is also unresolved because journal
intent or some files may already be durable. The PWA hides the pre-restore
status and requires a local runtime restart so startup recovery finishes before
export or another restore attempt.

Export includes each record and every retained decision artifact, including
inactive audit history. Restore validates the complete archive before writing,
skips stale record and deletion generations, and rejects conflicts, an attempt
to reactivate a tombstone, or an unbound tombstone targeting a live record. An
active record must carry the exact decision artifact re-derived from its
canonical state. Accepted changes are published through one recoverable
multi-record cascade; a tombstone bound to the same deletion-pending generation
removes retained decision artifacts in that unit. The format deliberately
excludes V1 screenshot jobs, parser benchmarks, and any hosted data.

There is intentionally no player-runtime host or port flag. A non-loopback
operator development service would be a different runtime and would require
TLS plus its own server-enforced authorization design.

## Boundary verification

Run the direct-network browser checkpoint with:

```bash
pnpm player:test:e2e
```

The command builds both PWA entries, starts the production Uvicorn player
application on `127.0.0.1:8765`, and consumes a one-use launch URL through an
owner-readable test handoff file. It verifies the authenticated same-origin
storage and backup/restore flow, service-worker control, static-shell-only
caches, and a failed offline storage read. The same suite starts the production
Worker under local Wrangler with a recording backend. Direct and repeatedly
encoded player API POSTs must return `404` with `Cache-Control: no-store`, and
the recording backend must receive neither a request nor its sentinel body.
The backend transport test also connects through a discovered non-loopback
IPv4 address and requires connection refusal; Linux CI fails when it cannot
produce that LAN-side evidence instead of silently skipping it.

The browser harness uses only test-side launch and recording processes. It does
not add a ticket endpoint, configurable player bind address, hosted player
route, or production credential transport.

## Current limit

The local runtime now exposes authenticated session lifecycle, health, store
status, conflict-safe backup/restore, sanitized imported-hand audit reads,
approval/reapproval, withdrawal/rejection, and permanent deletion under
`/api/player`, with an installable player PWA. The local workspace also composes
the conflict-safe transaction for an already-parsed hand-history candidate, but
there is still no player hand-history upload route or corpus-backed PokerStars
adapter. Learning, migration, remote lookup, operating-system
installer/uninstaller, and the complete player workflow remain absent. Future
grade, mastery, drill, and proof stores do not yet exist, so they are not part
of the version 1 archive. The hosted Worker and V1 FastAPI deployment deny the
namespace, and the direct-network checkpoint verifies that denial without
proxying a request body. Do not use the runtime or its test command as evidence
that the Phase 1 gate or issue #432 is complete.
