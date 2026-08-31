# ADR 0051: Isolate the Local Player Store Composition

Status: accepted

Date: 2026-08-31

## Context

ADR 0050 established a separate authenticated loopback application but left its
readiness shell disconnected from persistence. The imported-hand aggregate,
crash-safe file store, and lifecycle cascade already exist. The hosted
`WorkspaceCoordinator`, however, also opens legacy screenshot-job and benchmark
stores. Reusing it in the player runtime would make an unfinished player route
one dependency away from administrative V1 data and would blur the local player
system-of-record boundary.

Persisted hand histories also require a stronger local-filesystem assumption
than the installation credential alone. An owner-only key inside a shared data
directory would authenticate the API while leaving future player records
readable by other local users.

## Decision

The local runtime opens a dedicated `PlayerWorkspace` containing only the
imported-hand repository. It never constructs the V1 job or benchmark stores.
The configured player data directory and imported-hand store must be
current-user-owned directories with no group or world permissions; Darwin
extended ACL entries are also rejected because they can grant access that mode
bits do not show. Startup fails explicitly instead of weakening those
requirements or changing existing permissions silently.

Before the listener starts, the player workspace runs the imported-hand
journal's existing fail-closed recovery under the exclusive data lock when
interrupted writes exist, then waits for any legitimate exclusive volume work
to drain under the bounded shared startup lock. The configured recovery,
startup, and request-write lock budgets remain independent.

An authenticated read-only `/api/player/storage` endpoint reports the resolved
player-controlled data location, imported-hand record count, and the exact
completed, quarantined, and failed recovery identifiers. Quarantined or failed
recovery yields `attention_required`; completed recovery alone remains ready.
The readiness shell displays this status and path. No import, record read,
lifecycle mutation, backup, grading, or learning route is added.

## Consequences

Future player-only application services have an explicit local repository to
receive without inheriting hosted V1 persistence. Startup recovery is now part
of the real player process, and the player can verify where data will live
before import is enabled. Recovery evidence remains distinguishable rather than
being collapsed into a generic healthy or failed flag.

Existing shared or incorrectly owned directories must be corrected by their
owner or replaced with a private directory before the player runtime starts.
The runtime still serves a foundation shell, so issue #432 and the Phase 1 gate
remain open pending the dedicated PWA, import/lifecycle APIs, backups, migration,
uninstall/export behavior, optional remote-provider boundary, and complete
network evidence.
