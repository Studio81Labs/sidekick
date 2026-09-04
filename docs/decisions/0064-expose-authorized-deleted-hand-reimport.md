# ADR 0064: Expose Authorized Deleted-Hand Reimport

Status: accepted

Date: 2026-09-04

## Context

Ordinary imported-hand ingestion deliberately refuses `deleted` and
`deletion_pending` records. A permanent tombstone no longer retains the stable
identity or hand-linked evidence, but its identity-derived record key and
deletion generation remain authoritative. Treating the next matching upload as
a new identity would silently bypass deletion-generation protection. Restoring
an older backup is likewise not permission to resurrect purged evidence.

The product specification permits resurrection only through an explicit
user-authorized reimport. That operation must remain distinct from ordinary
overlapping imports, preserve parser uncertainty, create no canonical truth or
learning data, and safely recover when the browser loses a mutation response.

## Decision

The authenticated local player runtime exposes
`POST /api/player/hands/{record_key}/reimport` as a bounded multipart mutation.
The request supplies one UUID authorization-attempt ID, one PokerStars `.txt`
file, and exact record-version, lifecycle-status, deletion-generation, and
lifecycle-time preconditions from the sanitized hand detail. The source file
may contain other hands, but it must contain exactly one successfully parsed
hand whose stable identity derives the selected record key. No sibling hand is
ingested by this targeted operation.

The operation accepts only `deleted` or `deletion_pending`. It builds a fresh
`pending_review` aggregate from only the newly parsed raw source and detection,
advances the deletion generation by one, and advances lifecycle time strictly.
It retains parser confidence, warnings, field evidence, source provenance, and
pot-reconciliation warnings from the new candidate. It retains no prior raw
source, detection, conflict, correction, canonical revision, deletion request,
deletion receipt, or derived decision artifact. Reimporting a
`deletion_pending` record is the explicit cancellation of that pending deletion;
the prior incarnation's retained audit is removed rather than carried into the
new generation.

Publication uses one `authorized_reimport` cascade. The new record and deletion
of every exact decision-artifact filename still retained for the old
incarnation commit as one roll-forward unit under the existing stable thread,
process, data-volume, and journal locks. Failure before durable intent leaves
the deleted incarnation unchanged. Failure after durable intent requires
startup recovery and the hand remains unavailable until replay finishes.

The parser provenance derived from the authorization request ID, target record
key, and hand ordinal is the durable retry binding. An exact retry compares the
complete source, recognition, confidence, warning, evidence, detector, and
provenance payload while preserving the first server timestamps. It returns the
already-published pending record without another generation advance. Reusing
the request identity with changed evidence fails explicitly. Another request,
another identity, a stale precondition, a non-deletion lifecycle, or an
unresolved cascade writes nothing.

The PWA exposes the action only on deleted or deletion-pending detail, requires
one local file and an irreversible confirmation, and explains that prior audit
and approval do not return. A filename-and-content fingerprint retains only the
non-sensitive request ID needed to reuse an interrupted attempt; neither the
filename nor hand-history content enters browser storage. One ambiguous
transport response is retried automatically with the exact request. A still
ambiguous attempt remains available for the player to retry safely.

The route inherits loopback, Host/Origin, session, CSRF, no-store,
restore-exclusion, workspace-version, multipart-size, and recovery boundaries.
Its response is a sanitized audit projection and never contains raw
hand-history text or evidence excerpts. The hosted OpenAPI and generated client
remain unchanged because this is a local-player-only surface.

## Consequences

Players can deliberately recreate a deleted hand as new, unapproved evidence
without weakening ordinary import or backup resurrection guards. Every earlier
backup and decision artifact is stale relative to the advanced deletion
generation, and the reimport cannot grade, change mastery, generate drills, or
serve learning decisions until a separate explicit canonical approval.

This advances the lifecycle-safe local persistence criteria of #432. It does
not add grading, mastery, drill, proof, or representative-corpus behavior, close
the Phase 1 gate, or make the unsigned runtime bundle a supported installer.
