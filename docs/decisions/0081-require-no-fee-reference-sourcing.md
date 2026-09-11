# ADR 0081: Require No-Fee Reference Sourcing

Status: accepted for sourcing and budget; no solver or policy is qualified

Date: 2026-09-11

Execution update: [ADR 0082](0082-deliver-a-review-first-local-mvp.md) supersedes
this ADR's immediate R0a/R0/R1–R4 sequence after the bounded screen exhausted its
candidates. Source qualification is deferred; review-only implementation may
proceed. The zero mandatory fee decision below remains binding.

## Context

The owner rejects HRC costs before paying customers exist. Epic #405 and issue
#412 previously preferred HRC Pro exports and waited for a licensed operator.
A temporary trial does not establish an affordable way to reproduce, expand or
maintain the reference library. The owner also requires free public hand-history
acquisition rather than a personally supplied 1,000-hand corpus.

The native grading domain already accepts independently qualified static
references without naming HRC. `ReferenceRightsEvidence` supports owned or
licensed results; it does not require a paid license. `grade_decision` rejects
unqualified, mismatched and non-local references. No runtime or persisted-schema
change is needed to change the acquisition route.

## Decision

Keep the offline-generated, immutable static preflop reference architecture.
Require zero mandatory solver-license, dataset, subscription and external
solve-service fees for acquisition, regeneration, updates and player use.
HRC and other paid-source workflows are excluded from the current plan. A trial,
refund window or expected future revenue is not an exception. Reopening paid
sourcing requires a new explicit owner decision; revenue does not enable it
automatically.

Candidate routes are freely obtainable, appropriately licensed complete solved
artifacts, or reproducible offline generation using existing free/open-source
software. No supplier is selected. A public download or source-code license alone
does not establish rights to a dataset or the correctness of its strategies.
Review code, dependencies, output/data rights and actual distribution obligations
separately. No paid vendor benchmark is required: independent source inspection,
poker review and a suitable free verification method may supply the evidence,
but the same integrity, convergence and useful-coverage gates still apply.

Use existing hardware for bounded qualification; record CPU/RAM/disk, elapsed
time, energy assumptions and available unpaid operator/reviewer capacity. Zero
vendor fees does not mean unlimited or costless computation and review. No cloud
spend, new hardware, paid reviewer or source purchase is authorized. Freeze a
feasible resource/update plan before bulk generation.

Refine #412 in place with **R0a no-fee feasibility screening** before its existing
R0 contract freeze. The [source assessment](../reference/v2-grading-reference-assessment.md#no-fee-source-screen)
records the initial pinned candidates and exact next steps. R0a must produce a
candidate decision or a concrete scope/budget conflict, not an endless search or
new speculative adapter. One eligible complete artifact permits early mapping;
final R0 still needs #409-based economics/coverage and independent review. Then
retain R1 normalizer, R2 native static lookup, R3 certification, R4 evidence and
#414 final validation/decision in serial order.

Only a source-specific, supported export or documented open format is an R0
input. `Hand: Export Strategies` JSON is no longer the mandated format. Freeze
the actual field/unit/convergence mapping before implementation. No new solver
engine, legacy provider restoration, player-side solving, remote service,
qualification bypass or catalog activation is authorized by this decision.

## Product boundary and unresolved feasibility

The zero-fee constraint supersedes the HRC-first acquisition assumption, not the
preflop-first teaching goal. Complete mixed policies, exact input/economics,
rights, native convergence, independent validation and the existing 80% overall /
60% priority-route useful-coverage thresholds remain. Unknown or unsupported
situations stay ungraded and never become mastery or corrective-drill evidence.

No complete free source has yet passed these gates. A heads-up push/fold or
check-down model cannot silently replace ordinary six-max/full-ring play. If
free sources cannot meet the required coverage, return the measured shortfall
and a concrete narrower product proposal to #405/#414. Changing the target user,
legal action set, economics, grade authority, thresholds or replacing the
teaching loop with review-only functionality requires an explicit product and
architecture decision before dependent implementation. Missing evidence alone
is not a final stop or reshape verdict.

## Consequences and validation

#409 uses free public acquisition with provenance and independent labels; it
still owns the real corpus/action-origin gate. #412 no longer waits for an HRC
file, a paid budget or a trial activation. #414 verifies compliance with this
zero-fee ceiling alongside real evidence and exact-candidate lifecycle/security,
including the outstanding application-file update procedure. Existing scope
fits #409/#412/#414; no duplicate implementation issue is needed.

There are no new APIs, events, persistence formats, migrations, UI flows or
runtime dependencies. ADRs 0067 and 0079 remain authoritative. This decision
unblocks bounded source feasibility work, not source-specific production code
or Phase 1. Implementation remains SERIAL with at most one writer/merge-bound
PR. Documentation validation covers source links, consistency and formatting;
no solver run or source certification is claimed by this decision.
