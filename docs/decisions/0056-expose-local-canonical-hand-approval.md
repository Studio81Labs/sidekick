# ADR 0056: Expose Local Canonical Hand Approval

Status: accepted

Date: 2026-09-01

## Context

The local player runtime can inspect retained parser proposals, deactivate an
approval, and permanently delete a hand, but it cannot yet publish the player's
reviewed state as canonical ground truth. The imported-hand lifecycle already
supports approval and reapproval through the atomic cascade that publishes the
canonical record and its derived decision artifacts together. The missing
boundary is a stale-safe, auditable local transport that keeps parser output
separate from player-approved state.

The audit projection deliberately removes raw source text and evidence excerpts.
A player must be able to round-trip that sanitized state without erasing private
evidence from the retained canonical record. The client also cannot be trusted
to author detected values, correction pointers, correction timestamps, revision
numbers, or approval timestamps. Lost HTTP responses need exact attribution so
the UI never mistakes a concurrent approval for its own.

## Decision

The loopback-only player API exposes authenticated
`POST /api/player/hands/{record_key}/approve` for first approval and reapproval.
The request carries:

- a UUID identifying the exact approval attempt;
- one retained detection ID and a complete reviewed state document;
- an optional correction reason, required when the reviewed state differs from
  the detection;
- the opaque complete-record version; and
- the loaded lifecycle status, active revision, canonical revision count,
  deletion generation, and lifecycle timestamp.

Only pending-review, active, withdrawn, and rejected records are eligible. Every
precondition must still describe the retained aggregate under the stable thread
stripe, process-shared record stripe, and shared data-volume hold established by
the preceding lifecycle ADRs. Deletion-pending and deleted records cannot be
approved. The server selects the next monotonic revision, advances the approval
time strictly beyond the lifecycle marker, and calls the existing lifecycle
approval or reapproval cascade. Unresolved source lineage and other aggregate
invariants continue to fail closed in domain validation.

The server builds the canonical revision from the immutable detection and the
reviewed document. It restores source-evidence `excerpt` fields removed by the
sanitized player projection before validating the complete hand state. List
elements carrying private excerpts are matched through their visible provenance
identity, including street, player, pot, and source-location fields; an
ambiguous structural edit is rejected instead of attaching an excerpt to the
wrong element. The server then derives the smallest non-overlapping JSON-pointer
corrections. Detected values, approved values, correction timestamps, approval
timestamp, and revision number are server-owned. An unchanged review records no
corrections. A changed review without a reason is rejected without writing, and
validation responses never include private evidence values.

Canonical revisions gain an optional `approval_id`. Existing stored revisions
remain valid with a null value, while every non-null ID must be unique within an
aggregate. An exact retry whose ID belongs to the latest active revision
reconstructs the expected revision using its stored approval time and returns
the current sanitized detail only when every field matches. Reusing an ID for a
different request, an older revision, or an inactive revision is a conflict.

The player PWA selects a retained detection, seeds the editor from the latest
matching canonical revision or that detection, and requires explicit
confirmation before publishing. It validates that the reviewed value is a JSON
object and requires a reason for a visible JSON difference. On an error or
interrupted response it reloads the audit detail and reports success only when
the latest active revision carries the attempted UUID. When no exact commit is
found, a still-applicable reviewed draft remains in the editor against the
refreshed preconditions. A durable ready cascade returns recovery-required; the
PWA clears its projections and credentials and requires runtime restart before
retrying.

## Consequences

Players can correct parser output and explicitly approve or supersede canonical
ground truth without allowing parser proposals to overwrite prior approvals.
Canonical state, derived decision artifacts, correction provenance, and private
source evidence remain coherent through one lifecycle cascade. Stale browser
views cannot overwrite newer retained evidence, and concurrent or lost-response
approvals cannot be misattributed.

This advances issue #415 but does not add the PokerStars import adapter, player
hand-history upload, source-conflict resolution, authorized reimport, or the V2
learning surfaces. The route is local-runtime only, so it does not change the
hosted OpenAPI document or generated client.
