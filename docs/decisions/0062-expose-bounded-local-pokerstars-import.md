# ADR 0062: Expose Bounded Local PokerStars Import

Status: accepted

Local source-read amendment: [ADR 0083](0083-bind-reviewed-rows-to-retained-source-evidence.md)
authorizes an optional bounded authenticated source-lines view for the owner to
bind canonical corrections to entirely omitted lines. Import responses and all
other existing projections remain redacted; source text stays local and
canonical excerpts stay server-owned. This is planned under #533/#527.

Date: 2026-09-02

## Context

The local player runtime already owns the authenticated loopback boundary, the
private imported-hand store, a bounded PokerStars text adapter, and a
conflict-safe per-candidate ingestion transaction. Players still cannot submit
hand-history exports through that runtime, so the only retained examples come
from tests or direct store composition.

The current adapter is deliberately narrower than issue #409's representative
corpus and 99% clean-parse gate. Exposing it therefore must make the supported
subset and every rejection visible without presenting parser output as approved
truth. A multi-file request also cannot become one transaction: valid sibling
hands must survive malformed input, conflicts, or storage contention elsewhere
in the batch.

Browser transport can fail after one or more per-hand writes commit. Retrying
with a new import identity would incorrectly append another source occurrence;
reconstructing the same request with a new server clock value previously caused
the strict import-provenance comparison to reject the replay.

## Decision

The local player application exposes authenticated
`POST /api/player/imports` as multipart form data. It accepts a client-generated
UUID request ID and one to twenty bounded UTF-8 `.txt` files. Each multipart
file derives a stable adapter context from that request ID, its ordered slot,
and its SHA-256 digest. The server supplies the import and detection timestamps;
source chronology remains the chronology parsed from the hand history.

The coordinator parses every file and ingests every successful candidate
independently through `PlayerWorkspace.ingest_detected_hand`. Its response
contains sanitized per-file statuses, per-hand record keys, ingestion and
reconciliation dispositions, warning counts, and structured diagnostics. It
never returns raw hand-history text or evidence excerpts. New hands remain
`pending_review`; import cannot author a canonical revision, resolve a
conflict, resurrect a deletion tombstone, or feed learning.

An exact request replay compares all retained source provenance and detection
audit except the newly observed server timestamps. When those deterministic
fields still match, the first durable server timestamps remain authoritative
and the candidate returns `duplicate_request`. Reusing the same derived
occurrence identity for different filename metadata, chronology, adapter
metadata, detected meaning, confidence, warnings, or evidence fails explicitly.
A retry can therefore confirm already committed hands and continue uncommitted
siblings without a batch journal or a new backup member. A genuinely new import
uses a new UUID and appends normal exact-reimport or conflict audit provenance.
Changed bytes are not an exact retry: their digest derives different
source/import/detection IDs, so they cannot alias the earlier occurrence and,
when they retain the same stable hand identity, follow the ordinary explicit
reimport/conflict rules.

The route inherits the player session, Host/Origin, CSRF, loopback, no-store,
restore-exclusion, workspace-version, and recovery-attention boundaries. The
hosted Worker and V1 FastAPI application continue denying the complete player
namespace. A raw-body middleware bounds the complete multipart request before
the form parser can spool file parts, and the explicitly configured Starlette
form parser applies the lower file-count limit before the route reads any file.

The dedicated player PWA owns the multipart transport, validates that every
ordered file slot received an outcome, and retains the same UUID and selected
files after an ambiguous response or retryable storage diagnostic. Before
submission it persists the outstanding UUID with ordered SHA-256 filename and
content fingerprints, but no filename or hand-history text. After a runtime or
page restart, reselecting the exact ordered files restores that UUID; renamed,
reordered, or changed files use a new UUID. Confirmed terminal outcomes erase
the persisted retry identity, clear stale record detail, and refresh the stable
storage count. Selection or active import is unsafe for service-worker
activation.

The UI labels this as the bounded English no-limit cash subset plus the single
ADR 0078-reviewed historical tournament header form. Diagnostics and
failed/indeterminate reconciliation remain visible. Parser proposals stay
unapproved, and any canonical use still requires explicit player review and
approval from an eligible retained detection.

## Consequences

Players can import one or many currently supported PokerStars text exports
without moving their payloads through the hosted application. Malformed files,
unsupported hands, retained conflicts, and storage failures do not discard
successful siblings. Exact request retries do not add audit occurrences, while
a new request preserves an exact or overlapping reimport as a distinct source
occurrence.

No persistent batch receipt is added. Recovery is the same idempotent replay of
the original ordered files and request UUID; the first stored timestamps remain
the audit authority. Reordering or changing a request requires a new UUID.

This advances the local import and API-security criteria of #432. It does not
satisfy the representative corpus and 99% clean-parse evidence in #409, add
conflict-resolution or authorized tombstone-reimport routes, enable the V2
learning loop, close the Phase 1 gate, or make the unsigned runtime bundle a
supported installer.
