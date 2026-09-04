# ADR 0073: Revalidate Current Learning Evidence Under One Authority Scope

Status: accepted

Date: 2026-09-04

## Context

ADR 0070 deliberately made `ReferenceActivatedGrade` point-in-time evidence,
not mastery or drill authority. ADRs 0071 and 0072 then gave the local player
workspace durable current reference-activation and learning-content catalogs.
The remaining check also needs the current approved canonical hand.

Reading those three authorities through their independent public readers would
permit a catalog publication or hand lifecycle transition between reads. A
shared volume lock alone is insufficient because ordinary hand writers also
hold it shared while relying on the per-hand thread and process locks for
serialization.

## Decision

Add a pure application revalidation operation that defensively reconstructs
all inputs and fails closed unless:

- the retained grade's complete reference catalog and semantic digest exactly
  equal the persisted current reference authority;
- the current active hand artifact contains the exact retained decision,
  including its identity, canonical revision, deletion generation, index, and
  complete grading state;
- the current learning-content catalog has a current taxonomy and mapping and
  reproduces the retained grade, concept tag, activation check, and exact
  eligible approved principle records; and
- the selected active reference activation still retains those exact approved
  principle records and the same activation and mastery-series identities.

Any reference-catalog change invalidates the retained evidence, including an
append for another concept or coverage band. This preserves the complete
catalog-digest contract accepted in ADR 0070. An unrelated learning-content
append may pass only when recomputation produces the exact same relevant
readiness evidence; retirement, supersession, replacement, taxonomy drift, or
mapping drift affecting that evidence fails closed.

Compose the operation in `PlayerWorkspace` under the established lock order:
the hand's in-process stripe, its shared interprocess stripe, and then the
shared volume lock. While all three are held, load the integrity-checked active
decision artifact and both catalog stores directly, then perform only bounded
local validation and recomputation. Do not invoke network work, callbacks, or
durable mutation inside this read scope.

Return a freshly canonicalized `ReferenceActivatedGrade`. It deliberately
retains `requires_current_catalog_hand_and_content`: after the locks are
released, the evidence may immediately become stale. This checkpoint does not
create a consumable eligibility type.

## Consequences

Application code can now prove that retained solved-grade evidence matched all
three current authorities at one instant without trusting caller-supplied
historical catalog or hand snapshots. Catalog publication and same-hand
lifecycle mutation cannot cross the workspace check.

A future operation that persists a grade, updates mastery, or schedules a drill
must repeat this revalidation and commit its mutation before releasing the same
authority or transaction scope. The packaged catalogs remain empty, and this
decision adds no API, catalog publication workflow, grade persistence, mastery
calculation, aggregate mixing analysis, or drill scheduling.
