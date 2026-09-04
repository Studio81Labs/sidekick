# ADR 0070: Isolate Reference Activation by Concept and Coverage Band

Status: accepted

Date: 2026-09-04

## Context

ADR 0069 established immutable, per-decision evidence that a solved grade has
compatible human-reviewed teaching content. That evidence deliberately remains
`requires_reference_activation`. Issue #416 and the product specification also
require active mastery for one concept and coverage band to use one pinned
reference series. An upgrade must atomically rebuild downstream state or start a
clearly separate mastery series; old and new classifications must never mix.

There is not yet persisted mastery, drill, or proof state to rebuild. There is
also no runtime reference catalog or trustworthy remote-response promotion path.
The next safe boundary is therefore a pure catalog transition that selects the
separate-series upgrade strategy and produces provenance that later lifecycle
and mastery composition can verify.

## Decision

Add a persistence-free application contract under
`app/application/reference_activation.py`.

`CoverageBand` gives each comparable band a stable ID, embeds a deterministic
selector over canonical decision state, and pins the selector digest plus the
exact revision, pointer, and SHA-256 of its reviewed definition. It also pins the
coverage-manifest revision and digest from the qualified reference. Activation
and later grade binding recompute selector membership from the retained canonical
decision. Multiple active bands matching one decision fail closed as ambiguous;
a caller cannot assign an arbitrary band ID. The stable ID is the catalog key
across upgrades, while definition and coverage changes remain visible on the
activation event.

`ReferenceSeriesBinding` identifies the fields that must remain comparable for
one concept/band mastery series: reference, policy, tolerance, source evidence,
policy artifact, coverage, engine/configuration, economics, utility, EV unit,
support threshold, equivalent-EV threshold, and sizing tolerance. Exact route,
decision-context, and policy-content hashes remain per-decision evidence. They
are intentionally excluded from the broader series key because multiple exact
routes and solved policy payloads can belong to one reviewed coverage band.
Every grade must still retain and revalidate those exact fields.

`ReferenceActivationCatalog` is an immutable append-only snapshot. Each
`ReferenceActivation` records:

- the concept and coverage-band key;
- taxonomy series/revision, mapping revision, concept-definition revision, and
  exact taxonomy and mapping content digests;
- the broad reference-series binding and the exact binding used to approve the
  activation;
- the complete qualified local source, rights, benchmark, and coverage evidence;
- canonical compatible human-approved principle records and their full review
  provenance;
- activation identity/time; and
- a distinct mastery-series ID.

The catalog validates contiguous history, monotonic activation times, unique
activation identities, unique mastery-series identities, distinct active
selectors per concept, and exactly one latest active activation for every
concept/band key. Every activation binds its canonical content digest and the
previous activation digest, so a reused object graph cannot silently rewrite
append-only history. Replacing an active key always appends a new activation
with a new mastery-series ID. The transition is atomic as an immutable value:
success returns one complete successor snapshot, while any validation failure
returns nothing and leaves the prior catalog active and unchanged.

The deterministic digest chain is a consistency and audit mechanism, not a
signature or independent source of authority. A caller controlling a complete
snapshot can also recompute its digests. Future persistence and runtime
composition must therefore own the trusted current catalog revision and digest;
downstream code must reload that authority instead of trusting the snapshot
nested in a grade.

Activation accepts only a freshly revalidated `LearningContentReadyGrade`. The
coverage band must match its exact qualified coverage evidence, and the catalog
event retains only that readiness artifact's compatible approved principle
records. It does not retain the activating hand or grade in catalog history.

`ReferenceActivatedGrade` binds later per-decision readiness evidence to the
latest matching catalog entry and the SHA-256 of the complete catalog snapshot.
It requires exact taxonomy/mapping/definition pins, exact taxonomy and mapping
content digests, and the same broad reference series. Revision-label reuse with
different content therefore fails closed. The grade's route, context, policy
content, and teaching-principle compatibility remain exact and
decision-specific through the nested readiness evidence.

Reference activation is a point-in-time catalog claim, not current catalog or
current-hand authorization. The resulting artifact is marked
`requires_current_catalog_hand_and_content`, not generally learning-eligible. A
future mastery or drill boundary must reload the current catalog, current
principle records, and current approved canonical hand, then verify the catalog
digest, content lifecycle, canonical revision, and deletion generation before
accepting this evidence.

## Consequences

One catalog snapshot cannot mix reference or taxonomy classifications for a
concept/band, and every upgrade is visibly isolated in a new mastery series.
Historical activation events and reviewer provenance remain available for
audit. Distinct bands can coexist, and different exact routes can use the same
active broad series only when each decision independently passes the full
grading and content-readiness gates.

This decision does not persist or publish the catalog, configure a production
reference, retag imported decisions, calculate mastery or aggregate mixing,
schedule drills, recheck current hand lifecycle state, expose an API/PWA surface,
or decode/promote remote provider responses. Those remain separate composition
and downstream checkpoints under #416, #418, and #420.
