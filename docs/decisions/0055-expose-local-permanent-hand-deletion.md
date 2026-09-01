# ADR 0055: Expose Local Permanent Hand Deletion

Status: accepted

Date: 2026-09-01

## Context

The local player runtime can inspect imported-hand audit records and deactivate
an active approval, but a player cannot yet remove retained hand evidence. The
domain lifecycle already defines the required ordering: first publish a
`deletion_pending` successor that removes the active canonical pointer and
learning eligibility, then purge hand-linked evidence and publish a
receipt-only tombstone for the same deletion generation. The store also uses
that tombstone generation to prevent an older backup from silently
resurrecting purged evidence.

A local HTTP mutation needs to preserve that ordering across stale browser
state, multiple runtime processes, concurrent backup/restore work, lost
responses, and interrupted cascade publication. It must not expose raw source
content, accept client-authored canonical state, or make the hosted V1 API a
player-data path.

## Decision

The loopback-only player API exposes authenticated
`POST /api/player/hands/{record_key}/delete`. The request carries:

- an opaque UUID generated for that deletion attempt;
- a non-empty player reason;
- an opaque SHA-256 version of the complete retained record;
- the loaded lifecycle status, active revision, deletion generation, and
  lifecycle timestamp.

The record version covers raw source and audit fields even though the player
projection never returns their contents. A request therefore cannot erase
retained evidence appended after the audit detail was loaded. Active records
require the active canonical revision; inactive records require a null active
revision. Every mismatch fails without writing.

Under the same stable thread stripe, process-shared `flock` stripe, and shared
data-volume hold used by approval deactivation, the runtime publishes two
ordered lifecycle cascades:

1. Unless the record is already `deletion_pending`, request deletion through
   the domain lifecycle service. This advances the deletion generation,
   removes the active canonical pointer, and makes the record ineligible for
   learning while retaining its audit for retry.
2. Purge that pending generation through the same service. This replaces the
   record with a tombstone and deletes every exact retained decision-artifact
   filename in one durable cascade.

The server supplies both transition times and advances each strictly beyond the
stored lifecycle marker. The tombstone retains only deletion generation and a
deletion receipt. Its receipt ID is the request UUID. Its checksum binds the
record key, request UUID and reason, exact retained-record version, source and
target generations, source lifecycle status, and server deletion time. The
reason and prior record version are not themselves retained in the tombstone.
An exact retry against the completed tombstone reconstructs this binding and
returns the existing sanitized detail; a different request receives a
conflict.

A failure before purge has durable intent leaves the complete
`deletion_pending` record inactive. The player rereads it, retains the original
reason, and offers cleanup retry using the refreshed version and the same
generation. A failure after purge intent is durable returns recovery required;
the affected detail remains unavailable until startup recovery rolls the
tombstone and remaining artifact deletions forward. Lost responses are reported
as committed only when the refreshed tombstone has both the expected generation
and exact request receipt ID. Any other refreshed state is shown without being
attributed to the failed request.

The PWA requires a reason and an explicit irreversible confirmation. It states
which hand-linked audit is removed, that only receipt evidence remains, and
that restoring an older backup cannot undo the deletion. The mutation uses the
existing local session, Host/Origin, CSRF, restore gate, and lock boundaries.

## Consequences

Players can permanently remove any retained hand, including unapproved and
already-inactive records, without risking a window where canonical evidence is
gone but learning artifacts remain active. Stale audit views cannot erase newer
retained evidence. Cleanup failures remain visible and retryable, while durable
partial publication requires startup recovery instead of presenting a
pre-replay state as final. Tombstones continue to dominate older backups by
deletion generation.

The opaque version is intentionally a transport precondition, not a public
content checksum or replacement for the domain aggregate validation. This
advances issues #415 and #432 but does not add import, correction,
approval/reapproval, conflict resolution, or authorized reimport. The route is
local-runtime only, so it does not change the hosted OpenAPI document or
generated client.
