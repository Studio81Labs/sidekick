# ADR 0082: Deliver a Review-First Local MVP

Status: accepted; implementation and release evidence outstanding

Date: 2026-09-11

## Context

The owner approved the review-first proposal in escalation #525 after the
bounded R0a screen found no eligible no-fee ordinary-preflop reference. The
screen did not run solvers or qualify a policy. ADR 0081 excludes mandatory
solver, data and external-service fees, including regeneration and updates.
Continuing to require solved grading before any player validation would block
all delivery. Building another solver or promoting heuristics would change the
cost or trust boundary rather than resolve that dependency.

The current local runtime already imports, retains, corrects and explicitly
approves canonical hands. Its primary correction interface is a JSON textarea.
The native domain can retain unknown origins and partial economic facts without
asserting a usable learning decision. Current V2 storage and lifecycle
foundations are useful independently of solved grading. Application-file updates
remain unqualified despite working browser-worker update fencing.

## Decision

Reshape Epic #405 into a **local hand-review MVP**: import real PokerStars text,
read the recorded hand, correct it through structured controls, explicitly
approve the reviewed record, and retain/export/restore/delete it locally. This
is a post-hand review utility; do not market its release as a proven teaching
loop or claim that human review identifies optimal play.

Defer #412 and the remaining learning work under #406, including automated
mistake/EV grading, leak ranking, mastery, principle-based teaching, drills,
repetition and learning proof. They are neither completed nor automatically
unblocked by #405's review-release decision. Future learning must pass its own
source, rights, convergence, mixed-policy, input, content and coverage gates.
Keep current V2 domain/audit foundations and their fail-closed semantics; do not
restore the retired V1 chart, solver adapters, application or compatibility.
No runtime solver, remote feed or mandatory external fee is authorized.

The GitHub [Epic's Technical Implementation Plan](https://github.com/Studio81Labs/sidekick/issues/405#technical-implementation-plan)
is the persistent detailed plan. [#496](https://github.com/Studio81Labs/sidekick/issues/496)
is the execution handoff. New children [#527](https://github.com/Studio81Labs/sidekick/issues/527)
and [#528](https://github.com/Studio81Labs/sidekick/issues/528) own structured
review and application-file lifecycle respectively. Execution is **SERIAL**, one
implementation writer and merge-bound PR at a time.

### Review and contracts

Render detected or approved `ImportedHandState` directly, with every recorded
street/action, exact Decimal amounts and units, cards, warnings, safe provenance
and explicit unknowns. Do not require a Hero or extractable voluntary learning
decision to display a hand. Source-reported awards remain source claims under
ADR 0078; no new evaluator or poker advice is implied.

Replace the JSON correction workflow with typed structured controls and a
separate preview/change summary and explicit approval. Preserve canonical
validation, evidence binding, server-owned corrections/timestamps and the
current conflict/lifecycle behavior. Technical identity, parser confidence and
source attestations are not editable poker facts. Any explicit user-origin
confirmation retains the existing evidence-bound `user_confirmed` semantics;
it is not a parser rule or reference qualification.

Add only an authenticated, bounded, no-store local
`POST /api/player/hands/{record_key}/review-preview` endpoint. It shares pure
canonical preparation/validation with approval and uses the existing Python
structural-position helper for fully known dealt-in rings. It leaves partial or
dead-button cases unresolved and fills no other unknown fields. The precise
versioned request/response/error contract is in #405. Preview has no persistence,
idempotency, audit, decision or grade writes and grants no approval authority.
Approval rechecks the existing expected-state tuple and all domain invariants.
Private error responses expose safe field pointers/codes, not source excerpts.

Keep drafts transient and fence responses by hand/version/detection/draft
revision. Add preview to the existing operation and browser-update coordination.
No local-storage hand drafts, automatic approval, hosted player API or new event
is introduced. Workspace layout 6 and backup schema 4 remain unchanged; no
migration, legacy fallback or new learning store is needed.

### Review-specific import qualification

Use the explicitly named `review-mvp/v1` acceptance profile in #409. Retain
manifest/report v1 and historical reports; bind the profile in the evidence
index to exact CLI flags, corpus fingerprint and code revisions. Do not relabel
an old checkpoint as a new completed gate.

Require at least 1,000 distinct real freely downloadable, authorized and
independently labelled hands, a frozen representative sampling/composition plan,
all expected cases matching, and at least 99% clean parses across the whole
labelled denominator, including rejected cases. Retain full non-pot, chronology,
position, origin, warning and pot-reconciliation verification. Presence floors
are not by themselves proof of representativeness. A public code license alone
does not establish rights to third-party hand data. Source custody/rights,
independent labels/review and the passing report remain outstanding.

For this review profile, positive parsed player-selected/preselection,
reconnect and absence semantics are **not mandatory coverage prerequisites**.
Unknown remains a valid and visibly unknown result. Keep all current documented
composition floors for supported cash/tournament, table sizes, sit-outs, antes,
uncalled returns, rake, side pots, showdown, incomplete hands, automatic timeout/
disconnect, forced and unknown actions. No new reconnect CLI tag or invented
voluntariness rule is permitted. ADR 0075 measurement integrity and #411's
positive-evidence requirement for learning decisions are unchanged. Broader
parser semantics require new reviewed sources when separately pursued.

### Delivery and release gate

The first delivery target is a **controlled local macOS arm64 pilot** on the
existing host, with exact OS/browser versions recorded during #528/#414. The
current unsigned host-platform archive is suitable only for this controlled
repository-build channel. Integrity hashes do not authenticate a publisher.
This decision does not authorize a public signed installer, automatic updater,
other-platform support claim, new trust channel or paid signing service.

#528 must qualify a manual side-by-side application-file update: verify the
candidate outside the data directory, finish operations, create and rehearse a
verified current-format backup, stop the old runtime, enforce its existing
exclusive lease, and launch the new application against the same explicit data
root with fresh sessions and a safe shell handoff. Test two distinct current
bundles, failed/interrupted staging/startup, corrupt artifacts, concurrent
processes, recovery, application removal, export-before-data removal and stale
restore. Preserve data on failure; do not downgrade, migrate or silently reset.

#414 becomes the exact-candidate **review-pilot** gate: #409 import evidence,
#527 usable correction/approval, #528 application-file lifecycle, existing local
privacy/security/admin isolation, and named recorded-fact/usability reviewers.
No solver evidence is required for this gate. A `go` authorizes only the review
pilot, not the future teaching loop. Missing representative evidence, a failed
security/lifecycle check or unusable correction workflow still blocks release.

## Alternatives rejected

- Paid HRC or trial-based sourcing violates the approved recurring-cost boundary.
- More unbounded source searching has no evidenced finish condition after R0a.
- Building a new solver is a separate major product/engineering project.
- A narrow research game or heuristic chart does not meet the approved teaching
  trust requirements and must not be presented as an equivalent grading floor.
- Shipping the current JSON-only editor is not the approved consumer workflow.
- Removing independent corpus and lifecycle validation would conceal unresolved
  correctness and data-safety risks rather than make review release-ready.

## Consequences and supersession

This decision supersedes ADR 0081's immediate R0a/R0/R1–R4 execution instruction,
not its zero-fee policy. It supersedes the original shared review-plus-learning
entry dependency in ADR 0046 and specification §9 only for the review MVP.
Learning invariants in ADR 0067 and later grading/content/audit ADRs remain
binding for future learning. ADRs 0078–0080 remain in force.

Implementers may decide naming, layout and test organization within the plan.
Escalate architecture, domain/evidence, API, persistence, security, lifecycle,
compatibility, core scope, corpus acceptance or cost changes before proceeding.
The owner has approved the product reshape; actual corpus/reviewer availability
and candidate release validation remain unresolved evidence, not assumed facts.
