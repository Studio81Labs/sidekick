# ADR 0074: Persist Revalidated Grades as Audit Evidence

Status: accepted

Date: 2026-09-05

## Context

ADR 0073 can prove that a retained `ReferenceActivatedGrade` matches the
current approved hand, reference-activation catalog, and learning-content
catalog under one coherent read scope. Returning that result and saving it in a
later operation would create a time-of-check/time-of-use gap: the hand or either
catalog could change before persistence.

Grades are player-derived data that must survive portable backup and disappear
with permanent hand deletion. They are not current authority. Persisting a grade
must not create a mastery sample, update an aggregate, schedule a drill, or turn
the grade's `requires_current_catalog_hand_and_content` marker into a consumable
eligibility claim.

## Decision

Add one concrete player-workspace operation that reloads and revalidates the
grade, then commits it before releasing the same authority scope. It acquires
locks in the established order: the hand's in-process stripe, the hand's
exclusive interprocess stripe, and the shared data-volume lock. The exclusive
hand stripe excludes lifecycle changes to that hand; the shared volume lock
excludes reference-activation and learning-content catalog publication. The
imported-hand cascade remains the innermost leaf lock.

Persist each grade beneath its hand record as an immutable artifact. Its storage
identity binds canonical revision, deletion generation, decision index, catalog
digest, coverage band, activation ID, and mastery-series ID. Repeating the exact
write is idempotent. Different serialized evidence resolving to that same
identity is rejected rather than replacing or duplicating audit history.
Before commit, the serialized artifact must fit the portable player's fixed
per-artifact backup limit; persistence cannot create data that blocks the
mandatory export-before-uninstall path.

The artifact stores the complete `ReferenceActivatedGrade`, including reference,
policy, economics, utility model, EV unit, content, review, catalog, and hand
provenance. Its learning-eligibility literal remains
`requires_current_catalog_hand_and_content`. There is no active-grade reader and
no mastery or drill mutation in this decision; a future consumer must revalidate
again inside its own mutation scope.

Grades participate in the imported-hand lifecycle. Reapproval and withdrawal
leave prior grades as historical evidence distinguished by their immutable hand
binding. Permanent purge and authorized reimport enumerate exact stored grade
filenames and remove them in the same cascade as the hand transition.

Player backup schema v2 enumerates and checksums grade artifacts. Restore accepts
legacy schema v1 archives with no grade field, conflict-checks same-name retained
bytes, and restores grades only as player audit data. It never restores the
install-local reference-activation or learning-content catalogs as current
authority. Storage and restore also rebuild the named retained canonical
revision and require the indexed canonical decision to equal the grade's
snapshot. Matching only hand identity and revision number is insufficient. The
workspace layout version does not change because `grades/` is an optional child
owned by the already-versioned imported-hand store.

## Consequences

Revalidated solved-grade evidence can now be retained without a race between
validation and persistence, overwritten history, backup loss, or deletion
leakage. A later mastery implementation has durable provenance to inspect, but
cannot treat presence on disk as current eligibility.

The packaged catalogs remain empty and there is still no HTTP or PWA grading
workflow, production solved-reference publication, mastery calculation,
aggregate mixing analysis, or drill scheduling. Those remain gated by issues
#412, #414, #416, #418, and #420.
