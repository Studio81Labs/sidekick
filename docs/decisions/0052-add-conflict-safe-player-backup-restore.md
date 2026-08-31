# ADR 0052: Add Conflict-Safe Player Backup and Restore

Status: accepted

Date: 2026-08-31

## Context

The V2 player store is now isolated from hosted V1 persistence, but a local
data directory without a portable, verified backup cannot satisfy the Phase 1
durability boundary. The existing application-backup format contains V1
screenshot jobs, source images, and parser benchmark reports. Extending that
format would mix administrative test data with player records and make the
hosted application contract an accidental dependency of the local runtime.

Imported-hand records also cannot be restored by copying files over the live
store. A stale archive may predate a deletion generation, a matching-generation
live record may attempt to reactivate a tombstone, and record plus decision
artifacts must remain one crash-recoverable unit.

## Decision

The local runtime owns a separate `poker-hero-player-backup` version 1 ZIP
format. It contains only V2 imported-hand `record.json` files and every exact
retained decision-artifact filename. The manifest is strict, sorted, and
checksums and sizes every member. Export schema validation preserves the exact
stored bytes rather than regenerating historical audit artifacts. V1 jobs,
images, benchmark reports, and configuration are never included.

Export holds the player data-volume lock exclusively while it validates the
store and builds the complete archive. Restore first bounds, parses, validates,
and checksum-verifies the whole ZIP without a lock. It then takes the exclusive
volume lock, rereads current records, and applies `classify_restore` to every
candidate. Older record or deletion generations are reported as skipped. Any
divergent lineage, same-name artifact replacement, merge requirement, or
tombstone reactivation requirement rejects the entire request before a live
file changes; ordinary restore never supplies user-authorized reimport. Because
a tombstone deliberately retains no identity, it may replace a retained live
record only when that record is deletion-pending at the same generation. A
newer but otherwise unbound tombstone requires explicit conflict resolution
rather than treating its archive path as deletion authority.

Accepted records and missing retained artifacts are published together through
one multi-record `restore` cascade. Existing audit artifacts absent from the
archive are preserved and identical ones are reused. The sole deletion path is
a bound tombstone: it removes every exact locally retained artifact in the same
cascade as the tombstone, matching lifecycle purge semantics. The cascade
intentionally bypasses the store's ordinary shared write-lock wrapper because
restore already owns the exclusive volume lock; its journal remains the inner,
crash-recoverable lock.

An active record is accepted only with its canonical active artifact. Restore
re-derives that artifact from the freshly validated record and requires exact
equality before writing; checksums alone prove byte integrity, not agreement
with canonical poker state.

Authenticated `GET /api/player/backups/export` and CSRF-protected
`POST /api/player/backups/restore` expose this contract only from the loopback
player application. They inherit the exact Host, Origin, session, response,
and hosted-namespace denial policies from ADR 0050. They are intentionally not
added to the hosted V1 OpenAPI document or generated client.

## Consequences

The imported-hand portion of player-local state can be exported, verified, and
restored without allowing an older backup to resurrect deleted evidence. A
multi-record restore either has no durable intent or is recoverable as one
journaled unit, and a retry reuses identical data.

This first player format does not yet contain future grade, mastery, drill, or
proof stores because those stores do not exist. Adding them requires a new
schema version and the same conflict-safe, deletion-aware treatment; it must not
silently reinterpret version 1. The current readiness shell also has no backup
controls, so the packaged player PWA and its user-facing workflow remain open
work under issue #432.
