# ADR 0054: Expose Local Approval Deactivation

Status: accepted

Date: 2026-09-01

## Context

The local player runtime can inspect retained imported-hand records, but it
cannot yet act on an approval. The imported-hand lifecycle service already
withdraws or rejects an active canonical revision through the atomic cascade
that deactivates derived learning evidence while retaining audit history. That
service deliberately does not own transport concurrency. Its compare-and-swap
closes races inside one process, but two local-runtime processes could otherwise
publish successors built from the same stored record.

The first player lifecycle write must not also invent correction, approval,
reapproval, deletion, or import contracts. It must preserve the parser proposal,
canonical revision, corrections, and provenance already exposed by the audit
projection, and it must remain unreachable through the hosted Worker or V1 API.

## Decision

The loopback-only player API exposes two authenticated actions:

- `POST /api/player/hands/{record_key}/withdraw`
- `POST /api/player/hands/{record_key}/reject`

Each request carries a non-empty player reason and the active canonical
revision, deletion generation, and lifecycle timestamp from the loaded audit
detail. The server accepts the transition only when those values still describe
an active record. It supplies the transition time, calls the existing lifecycle
cascade, and returns the same sanitized detail projection used by the read
route. A retry returns the already-current inactive record only when the target
status, reason, canonical revision, and deletion generation still match; other
stale requests fail without writing. The supplied lifecycle time is strictly
later than the stored marker: if wall time is equal or behind because restored
data came from a faster clock, the server advances the marker by one microsecond
so the inactive successor remains orderable against its active predecessor.

The player workspace serializes each transition in this order:

1. a stable in-process record stripe;
2. the matching named process-shared `flock` stripe;
3. a shared data-volume hold spanning the request precondition read and
   lifecycle transition;
4. the store's nested shared data-volume hold; and
5. the cascade journal's leaf lock.

The stable stripe is derived from the identity-based record key, so separate
local-runtime processes use the same lock. The outer shared volume hold prevents
a restore in another process from replacing the record after the precondition
check but before the lifecycle service rereads it. The named lock is separate
from the data-volume lock: nesting the store's shared volume hold under an
exclusive hold of that same file would deadlock. An asynchronous shared/exclusive
restore gate remains outside this sequence: ordinary status, hand, lifecycle,
and export requests share the gate and may proceed concurrently, while restore
owns it exclusively from upload through publication. A waiting restore blocks
new ordinary entrants so a steady stream of hand work cannot starve it.

The player PWA shows the actions only for an active detail, requires a reason
and explicit confirmation, sends the stored precondition with session and CSRF
credentials, and replaces both list summary and detail with the returned audit.
After an error or interrupted response it rereads the detail and requires the
requested status, reason, canonical revision, and deletion generation before
reporting that the inactive state committed. If a storage failure leaves a
durable ready cascade, both the mutation and detail read return recovery
required instead of exposing the pre-replay record as final. Collection pages
report that affected key as unavailable rather than projecting its pre-replay
lifecycle summary. The PWA discards its stale hand projections and session,
keeps the lifecycle outcome unresolved, and requires a local-runtime restart
before the hand can be loaded or retried.
Volume-wide storage status, backup export, and backup restore take an exclusive
volume snapshot and return recovery required while any durable ready cascade
remains. The gate is not global to hand work: unrelated record keys remain
readable and writable through their own stripes while the affected key stays
closed.

## Consequences

Players can immediately remove a previously approved hand from learning or mark
it incorrect without destroying source, detection, correction, canonical, or
derived audit evidence. Concurrent or stale requests cannot silently overwrite
a newer lifecycle state. Ambiguous browser responses are reconciled against a
final local record; a record with pending roll-forward work is deliberately not
available for reconciliation until startup recovery completes it. A backup
cannot capture a pre-replay lifecycle state that could later reactivate an
approval when restored elsewhere.

This advances issue #415 but does not complete it. Hand-history import,
correction, approval/reapproval, conflict resolution, deletion/purge, and the
learning surfaces remain separate future slices. The routes are local-runtime
only, so they do not change the hosted OpenAPI document or generated client.
