# ADR 0058: Ingest Parsed Hand Candidates Before Enabling Upload

Status: accepted

Date: 2026-09-01

## Context

Issue #415 needs a player-facing hand-history import workflow, but the
corpus-backed PokerStars adapter gate in issue #409 is not complete. Exposing a
local upload route before a production adapter exists would either accept no
real input or encourage a partial parser to look production-ready. The local
store already has strict raw, detected, canonical, conflict, lifecycle,
decision-artifact, and backup contracts; what is missing below the future
transport is one serialized application operation that safely appends an
adapter-produced candidate to those contracts.

Exact and overlapping reimports also need durable audit provenance without
copying identical raw text or detected learning data. Conversely, the same
stable identity can acquire materially different bytes or a new semantic
interpretation of identical bytes. Those cases must remain reviewable conflicts
and must never overwrite approved state.

## Decision

`ImportedHandIngestionService` accepts one already-parsed candidate consisting
of an immutable `RawHandHistory` and its `DetectedImportedHand`. It revalidates
both complete graphs and requires their stable identity, raw-source identity,
and source chronology to agree. Adapter candidates cannot pre-author retained
reimport audit.

The service applies one of four append-only outcomes:

- A new identity becomes a pending-review aggregate with no canonical revision.
- Identical bytes with the same detected meaning append a `RawHandReimport`
  occurrence to the retained raw source. The occurrence keeps the later source
  ID, chronology, filename, adapter/version, import ID, and import time, while
  raw text, detection, canonical revisions, and derived learning data remain
  single-copy. The initial occurrence and every reimport bind their import ID to
  a semantic fingerprint, so a retry cannot change meaning after other detected
  interpretations have also been retained.
- Materially different bytes retain the new raw source and detection under an
  unresolved `ImportConflict`.
- A different detected meaning for identical bytes appends the source
  occurrence, retains the new detection against the existing immutable raw
  bytes, and creates a single-source/multiple-detection unresolved conflict.

An exact retry of one import ID is a no-op only when its source evidence and
detected meaning still agree. Reusing the ID for different provenance, bytes,
or meaning fails explicitly. A new occurrence cannot precede the latest import
time anywhere in the aggregate; an exact retry remains a no-op even after later
imports. Source occurrence IDs and import IDs are unique across the aggregate.
They participate in lifecycle chronology, deletion ordering, backup/restore,
and monotonic restore comparison.

The ingestion service preserves a retained lifecycle and active pointer when a
conflict is appended. The unresolved conflict still makes decision extraction
fail closed, so no conflicting candidate enters learning. A deleted or
deletion-pending record cannot be resurrected through this operation; a future
authorized reimport lifecycle operation must handle its generation explicitly.

`PlayerWorkspace.ingest_detected_hand` composes the service under the existing
stable in-process stripe, process-shared record stripe, and shared data-volume
lock. The application service deliberately relies on this identity-exclusive
serialization across its complete resolve/find/save transaction; direct
concurrent service use is not a supported production composition. The
persistence port owns reimport classification and opaque key resolution,
keeping filesystem identity out of the application service.

## Consequences

The future PokerStars adapter and multipart player route have a complete,
conflict-safe local transaction to call. Valid siblings can be processed
independently by a later batch coordinator, while one malformed or conflicting
candidate cannot overwrite another hand.

This change does not add a PokerStars parser, corpus claim, player upload route,
PWA control, batch coordinator, conflict-resolution mutation, or authorized
tombstone reimport. It progresses #415 but does not close it, and it does not
claim any #409 acceptance criterion. The hosted Worker and V1 FastAPI surfaces
remain unchanged and continue denying the player namespace.
