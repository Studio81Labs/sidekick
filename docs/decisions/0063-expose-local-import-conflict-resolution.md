# ADR 0063: Expose Local Import Conflict Resolution

Status: accepted

Date: 2026-09-02

## Context

The imported-hand aggregate already retains materially different source and
detection evidence as unresolved conflicts, and its canonical-source lineage
requires an explicit `resolved_use_source` choice before a different source can
become active. The local player API and PWA expose that audit, but provide no
way to make the choice. A player can reapprove the preserved source while a
conflict remains open, but cannot switch to a competing source through the
supported workflow.

Resolving a conflict can also change whether an already-approved hand is safe
to serve. Keeping the preserved source should restore its existing active
decision artifact. Selecting another source cannot silently reinterpret the
old canonical revision as belonging to that source, and parser output still
cannot become ground truth without a separate explicit review and approval.

## Decision

The authenticated local player runtime exposes
`POST /api/player/hands/{record_key}/conflicts/{conflict_id}/resolve`. The body
selects either `keep_active` or `use_source`, names one raw source retained by
the conflict, and carries the complete record and lifecycle preconditions from
the sanitized audit detail. The operation is serialized by the same stable
thread, process, data-volume, and journal locks as approval and deletion.

`keep_active` is valid only when the conflict recorded a preserved canonical
revision and the selected source is that revision's source. The lifecycle
status and canonical pointer are retained. If the record is active, the atomic
cascade republishes the decisions derived from the now-resolved aggregate; an
identical retained artifact is reused rather than replaced. When another
conflict remains unresolved, the cascade advances only the record and leaves
the earlier artifact retained but unservable; resolving the final conflict
republishes the exact eligible extraction.

`use_source` records the selected source but does not create a canonical
revision. An active record becomes `pending_review`, loses its active pointer,
and immediately stops serving learning decisions. An already inactive record
keeps its lifecycle status and reason. The player must next use the existing
review-and-approval route with an eligible retained detection from the selected
source. This also supports a single-source/multiple-detection conflict: the
source choice moves the hand back to review, and the later approval chooses the
specific detected meaning.

Both resolutions retain every raw source, detection, prior canonical revision,
and conflict entry. The conflict gains its immutable status, selected source,
and server resolution timestamp, while lifecycle freshness advances strictly.
An exact retry of the same immutable conflict choice returns current sanitized
detail; a different choice, missing conflict, stale snapshot, invalid source,
or deletion state fails without writing. Interrupted durable publication
requires normal startup recovery.

The PWA offers the preserved-state action only when a preserved revision can be
identified. It offers source-review actions only for sources with a retained
approval-eligible detection, confirms the consequence before mutation, and
seeds the existing approval editor from the selected source after a successful
resolution. It reloads detail after an ambiguous response and reports success
only when the retained conflict has the exact requested status and source.

The route inherits loopback, session, Host/Origin, CSRF, no-store,
restore-exclusion, workspace-version, and recovery boundaries. Responses remain
sanitized and never include raw hand-history text or evidence excerpts.

## Consequences

Players can close retained import conflicts without overwriting parser or
canonical evidence. Keeping the preserved state can make its existing approved
decision usable again; choosing a source always requires a separate explicit
approval before learning resumes.

The cascade journal adds `resolve_conflict` as a diagnostic operation label; it
does not change the stored imported-hand or backup schema. The hosted API and
generated OpenAPI client are unaffected because this is a local-player-only
route.

This advances the conflict-resolution workflow in #432. It does not authorize
reimport over a deletion tombstone, add grade/mastery/drill/proof stores, satisfy
the #409 representative-corpus gate, or make the unsigned runtime bundle a
supported installer.
