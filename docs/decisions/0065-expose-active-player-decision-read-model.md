# ADR 0065: Expose the Active Player Decision Read Model

Status: accepted

Date: 2026-09-04

## Context

Canonical hand approval already publishes a revision- and deletion-generation-
bound `HandDecisionExtraction` in the local player store. Lifecycle changes
retain older artifacts for audit while `FileImportedHandStore.active_decisions`
refuses to treat them as current learning evidence. The local player API can
inspect a hand's review record, but it has no boundary through which a later
player workflow can read the current extraction without reaching around the
workspace composition or accidentally selecting a historical artifact.

The product specification makes an approved, current decision point the atomic
input to grading, mastery, and drills. It also requires the active artifact to
be re-derived from fresh canonical state before it is served. Exposing every
retained artifact, trusting its filename alone, or falling back to a prior
revision would violate that boundary.

## Decision

The authenticated local player runtime exposes
`GET /api/player/hands/{record_key}/decisions`. The route runs under the
existing restore-exclusion gate and stable per-hand thread, process, and
data-volume read locks. It reads the current canonical record, re-derives the
expected extraction, and delegates final artifact selection and equality
checking to `FileImportedHandStore.active_decisions`.

The read succeeds only for an active canonical hand whose exact
revision- and deletion-generation-bound artifact is present and equal to the
fresh derivation. A valid no-decision hand remains a successful explicit
`no_decision` result. A current `not_extractable` artifact is also served with
its rejection reason and no decision points, so the fail-closed verdict stays
reviewable and cannot enter grading. Pending, withdrawn, rejected,
deletion-pending, deleted, and unresolved-conflict hands return an unavailable
response and never expose retained historical decisions. A missing current
artifact or a schema-valid artifact that differs from canonical state is an
integrity failure, not an empty result or a fallback.

The response carries the opaque complete-record version and a JSON projection
of the current extraction. It preserves the canonical identity, chronology,
import provenance, revision, deletion generation, ordered decision state,
player-selected table action and origin, and excluded-action reasons. Raw hand
history and source-evidence excerpts are removed recursively; source IDs, line
ranges, markers, confidence, and versioned origin semantics remain reviewable.
The response inherits loopback, Host/Origin, session, no-store, recovery, and
workspace-version controls. As a `GET`, it does not require CSRF and cannot
mutate approval or learning state.

This local-only route is not added to the hosted OpenAPI document or generated
hosted client. It performs no grading, provider selection, remote request,
mastery update, or drill scheduling.

## Consequences

Later grading and player review work has one explicit read boundary for current
decision evidence and cannot silently consume a superseded artifact. Expected
lifecycle ineligibility, an explicit extraction rejection, and storage
integrity failure remain distinguishable, while all failures remain
fail-closed.

This advances the decision-persistence and local player workflow criteria of
#432 and provides a prerequisite for #416. It does not supply a trustworthy
solved reference, persist grades, mastery, drills, or proof metrics, authorize a
remote provider, close either issue, or open the Phase 1 gate.
