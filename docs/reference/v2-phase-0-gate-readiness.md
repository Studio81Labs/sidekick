# V2 Phase 0 Gate-Readiness Ledger

Status: Phase 1 **NO-GO**; final Phase 0 decision pending

Historical ledger review: 2026-09-05; cutover checkpoint: 2026-09-10

Historical evidence baseline: `ad93d12b7eb2a1aa36fadc92d616d83fcd08d5ca`
([`feat(backend): expose retained grade audit evidence (#492)`](https://github.com/Studio81Labs/sidekick/pull/492))

Tracking: [epic #405](https://github.com/Studio81Labs/sidekick/issues/405),
[gate report #414](https://github.com/Studio81Labs/sidekick/issues/414), and
[readiness checkpoint #493](https://github.com/Studio81Labs/sidekick/issues/493)

## Post-cutover checkpoint — 2026-09-10

C1 #519, C2 #520 and C3 #521 are merged; #517 is complete. The inspected cutover
commit is `ad3be0184b2606e4b8d6e04ad05cdb777db77ed6`. Its PR checks passed and
review threads are resolved. This records implementation completion, not a new
full empirical or release-candidate validation run.

[ADR 0079](../decisions/0079-adopt-an-unreleased-current-only-cutover.md)
supersedes pre-release compatibility: workspace 6 and backup 4 are current-only,
old recommendation execution is removed, and hosted OCR is an explicit
administrator surface. The product specification’s application-upgrade gate
still applies; rejecting retired data formats does not satisfy it. [ADR 0080](../decisions/0080-retire-mcp-data-and-write-principal-operations.md)
restricts MCP to environment status and rejects retired principal scopes.

No further production implementation is currently evidence-qualified under
#409/#412. [ADR 0081](../decisions/0081-require-no-fee-reference-sourcing.md)
replaces HRC-first sourcing with zero mandatory source/license/service fees.
Resume bounded [R0a no-fee source screening](./v2-grading-reference-assessment.md#r0a-execution-and-exit)
under #412 and free public-source qualification under #409. Do not wait for the
owner's personal corpus, HRC purchase or trial. Independent labels, real source
artifacts, rights, review and useful coverage remain required; source-specific
code and Phase 1 remain blocked. The historical ledger baseline does not
override these current decisions.

## Purpose and authority

This ledger records whether the evidence needed by the
[V2 Phase 0 plan](../specs/poker-hero-product-spec.md#9-phased-build-plan-gated)
exists at the pinned baseline. It separates implemented safeguards and
assessment tools from the empirical, commercial, and reviewer evidence that
must still be obtained.

This is not the final `go`, `reshape`, or `stop` report required by issue #414.
Missing evidence cannot prove that a narrower trustworthy product is viable,
so it is not a `reshape` decision. It also cannot prove that no compliant
preflop source can work, so it is not a `stop` decision. Until the import and
grading viability spikes both produce their required evidence, Phase 1 remains
blocked.

[ADR 0046](../decisions/0046-adopt-import-first-learning-boundary.md) remains
the controlling product, security, migration, and rollback boundary. This
readiness inventory does not change architecture, so it creates no new ADR.

## Status vocabulary

- `implemented` — the repository contains the scoped contract, runtime,
  control, assessment tool, or test evidence. This does not substitute for a
  real corpus, source rights, or production benchmark.
- `blocked on external evidence` — completion requires authorized material,
  vendor or rights evidence, qualified review, real target-user evidence, or a
  commercial decision that is not present in the repository.
- `not started` — the production behavior or proof does not exist and must not
  be inferred from contracts, synthetic fixtures, empty catalogs, or retained
  historical records.

## Shared-gate ledger

| Gate criterion                                                                                                                                                                                                                                                                                       | Status                         | Evidence at the baseline                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | Missing evidence or work                                                                                                                                                                                                                                                                | Accountable owner                                                                                              |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Site-agnostic raw, detected, corrected, approved, and lifecycle contracts remain separate; user approval is the only canonical authority.                                                                                                                                                            | `implemented`                  | [ADR 0046](../decisions/0046-adopt-import-first-learning-boundary.md), [canonical imported-hand model #410](https://github.com/Studio81Labs/sidekick/issues/410), and decision/lifecycle suites in [`test_imported_hand_models.py`](../../apps/backend/tests/test_imported_hand_models.py), [`test_imported_hand_lifecycle.py`](../../apps/backend/tests/test_imported_hand_lifecycle.py), and [`test_imported_hand_decisions.py`](../../apps/backend/tests/test_imported_hand_decisions.py).                                                                                                                                                                                  | None for the contract boundary. Each adapter still needs independent source evidence before its detected values can be trusted.                                                                                                                                                         | Import-domain maintainer                                                                                       |
| The PokerStars adapter and assessment instrument preserve chronology, economics, exact position, reconciliation, diagnostics, and queue independence for the currently supported English no-limit cash subset, reviewed automatic subsets, and the single reviewed historical HAND2 tournament form. | `implemented`                  | [PokerStars corpus procedure](../process/pokerstars-corpus-assessment.md), [ADR 0075](../decisions/0075-assess-pokerstars-corpus-offline.md), [ADR 0078](../decisions/0078-preserve-unresolved-historical-source-time.md), and the [HAND2 source labels](../process/pokerstars-hand2-source-labels.md).                                                                                                                                                                                                                                                                                                                                                                        | This engineering checkpoint is not representative-corpus proof; HAND2 chronology and ordinary action origins remain explicitly unknown.                                                                                                                                                 | Parser maintainer / #409                                                                                       |
| Tournament variants beyond the reviewed historical HAND2 form, plus player-selected/preselection, reconnect, and absence action-origin semantics are supported from documented source behavior.                                                                                                      | `in progress`                  | HAND2 has independently authored labels and maps its supplied tournament facts without invented chronology or origins. Reviewed historical cash subsets support only exact timeout bindings; the return status is raw-only and non-semantic.                                                                                                                                                                                                                                                                                                                                                                                                                                   | Implement only from reviewed, versioned real examples; then add verified parsed-coverage gates. Do not guess syntax or origin semantics from synthetic fixtures.                                                                                                                        | Parser maintainer / #409                                                                                       |
| Approximately 1,000 authorized or sanitized, independently labeled representative PokerStars hands pass the complete ≥99% clean-parse and coverage gate.                                                                                                                                             | `blocked on external evidence` | The offline tool can produce a deterministic redacted report without writing player data.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Authorized corpus custody, independent labels, required composition, a pinned fingerprint, complete coverage gates, and a passing sanitized report.                                                                                                                                     | Corpus custodian and independent label reviewer / [#409](https://github.com/Studio81Labs/sidekick/issues/409)  |
| Grading contracts fail closed unless solved policy, route inputs, economics, EV unit, source qualification, rights, benchmark, and immutable revisions agree.                                                                                                                                        | `implemented`                  | [grading source assessment](./v2-grading-reference-assessment.md), [source qualification ADR 0067](../decisions/0067-require-independent-reference-source-qualification.md), [remote dispatch ADR 0068](../decisions/0068-guard-remote-reference-dispatch.md), and native grading tests in [`test_grading.py`](../../apps/backend/tests/test_grading.py); the old recommendation benchmark was removed in #520.                                                                                                                                                                                                                                                                | These contracts prove rejection behavior only; they do not qualify a real policy.                                                                                                                                                                                                       | Grading-domain maintainer / #412                                                                               |
| An independently solved preflop source has complete mixed-policy and EV/unit evidence plus written rights for the selected delivery mode.                                                                                                                                                            | `blocked on external evidence` | ADR 0081 excludes paid-source workflows. The [source assessment](./v2-grading-reference-assessment.md#no-fee-source-screen) records the bounded no-fee R0a screen; no source is approved.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Written embedding, redistribution, commercial-use, update, repository-visibility, and attribution terms for static delivery, or commercial-serving and derived-output rights for a server-only feed; representative exports; exact policy/economics/utility evidence; qualified review. | Reference acquisition and legal/commercial owner / [#412](https://github.com/Studio81Labs/sidekick/issues/412) |
| The selected source passes a frozen independent benchmark, real-hand coverage study, reproducibility check, and approved acquisition/compute/review/update cost gate.                                                                                                                                | `blocked on external evidence` | `ReferenceBenchmarkEvidence` and `ReferenceSourceQualification` retain fail-closed evidence bindings. The native benchmark manifest/schema and runner remain unimplemented under #412; real results are absent.                                                                                                                                                                                                                                                                                                                                                                                                                                                                | Normalized immutable policy artifact, independently authored benchmark corpus, poker-qualified reviewer sign-off, stability/negative-boundary/lookup/coverage results, zero mandatory external fees and feasible local compute/review capacity.                                         | Benchmark owner, poker-qualified reviewer, and local resource-capacity owner / #412                            |
| Multiway postflop is explicitly selected as precompute, license, or defer for the Phase 1 scope.                                                                                                                                                                                                     | `blocked on external evidence` | The product spec and source assessment keep multiway output heuristic and mastery-ineligible.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Record the choice from actual source rights, quality, coverage, and cost evidence in the final #414 report.                                                                                                                                                                             | Product and reference owners / #412 and #414                                                                   |
| Remote-reference consent and minimized-request preflight contracts are exact, revocable, failure-safe, and local-only by default.                                                                                                                                                                    | `implemented`                  | Install-local consent, closed outbound DTOs, exact preflight binding, revocation, and negative fields are covered by [ADR 0066](../decisions/0066-persist-install-local-remote-reference-consent.md), [ADR 0068](../decisions/0068-guard-remote-reference-dispatch.md), [`test_remote_references.py`](../../apps/backend/tests/test_remote_references.py), and [`test_remote_reference_dispatch.py`](../../apps/backend/tests/test_remote_reference_dispatch.py).                                                                                                                                                                                                              | These contracts perform no network request and qualify no provider.                                                                                                                                                                                                                     | Provider/privacy owner / #412                                                                                  |
| An actual optional remote provider has approved privacy/use terms, encrypted transport, request/response provenance, revocation, failure behavior, and verified local-only fallback.                                                                                                                 | `blocked on external evidence` | No provider policy or transport is configured, so no player request can leave the local runtime.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | If a remote source is proposed, retain its real retention, training, logging, privacy, TLS, provenance, failure, revocation, and local-only results.                                                                                                                                    | Provider/privacy owner / #412                                                                                  |
| Screenshot upload and live capture are absent from the player capability and retained only in the disabled-by-default, server-authorized administrative OCR test boundary.                                                                                                                           | `implemented`                  | [administrative isolation #413](https://github.com/Studio81Labs/sidekick/issues/413), [PR #436](https://github.com/Studio81Labs/sidekick/pull/436), [ADR 0046](../decisions/0046-adopt-import-first-learning-boundary.md), [`test_admin_ocr_test_access.py`](../../apps/backend/tests/test_admin_ocr_test_access.py), [`test_admin_ocr_test_api.py`](../../apps/backend/tests/test_admin_ocr_test_api.py), and the [PWA administrative-capture integration suite](../../apps/pwa/src/pages/analyzer/__tests__/administrative-capture.integration.test.tsx).                                                                                                                    | Re-run the direct bypass and transition-denial checks on the final release candidate; rollback must never restore a player capture path.                                                                                                                                                | Safety owner / #414                                                                                            |
| The co-located player PWA/API/store is loopback-only, authenticated, Host/Origin/CSRF constrained, private, current-format backup/restore capable, and denied by the hosted Worker/API path.                                                                                                         | `implemented`                  | [local runtime #432](https://github.com/Studio81Labs/sidekick/issues/432), [local runtime procedure](../process/local-player-runtime-foundation.md), ADRs [0050](../decisions/0050-establish-local-player-runtime-security-substrate.md), [0052](../decisions/0052-add-conflict-safe-player-backup-restore.md), [0059](../decisions/0059-version-the-local-player-workspace-layout.md), and [0061](../decisions/0061-build-platform-scoped-player-runtime-bundles.md), plus [`test_player_runtime.py`](../../apps/backend/tests/test_player_runtime.py), [`test_player_backup.py`](../../apps/backend/tests/test_player_backup.py), and the direct-network player E2E command. | Release bundles remain unsigned and are not end-user installers or an update channel. That release-engineering gap does not permit Phase 1 while the two viability spikes are blocked.                                                                                                  | Local-delivery owner / #414                                                                                    |
| Reapproval, withdrawal, rejection, deletion-pending, purge, and stale restore cannot leave active existing decision or grade artifacts.                                                                                                                                                              | `implemented`                  | [ADR 0048](../decisions/0048-roll-back-unpublished-reapprovals.md), ADRs [0054](../decisions/0054-expose-local-approval-deactivation.md) and [0055](../decisions/0055-expose-local-permanent-hand-deletion.md), [`test_imported_hand_lifecycle.py`](../../apps/backend/tests/test_imported_hand_lifecycle.py), and [`test_player_backup.py`](../../apps/backend/tests/test_player_backup.py).                                                                                                                                                                                                                                                                                  | Re-run the complete lifecycle matrix on the final release candidate.                                                                                                                                                                                                                    | Persistence owner / #414                                                                                       |
| Lifecycle rebuild/deactivation is integrated with mastery, drill, and proof-of-learning stores.                                                                                                                                                                                                      | `not started`                  | No mastery, drill, or proof store exists, so no current contribution can survive a hand transition.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | After the shared gate clears, every new derived store must join the same atomic lifecycle cascade and add failure, pending, purge, and stale-restore evidence before Phase 1 validation.                                                                                                | Learning persistence owner / #418, #420, and #421                                                              |
| Current reference/content authority contains production solved policy and compatible approved teaching principles.                                                                                                                                                                                   | `not started`                  | The stores and activation/revalidation contracts exist, but the packaged reference and learning-content catalogs are empty. See the [backend architecture](./architecture.md#backend).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | A source that passed #412, compatible human-reviewed principles, a reviewed activation proposal, and the final #414 decision.                                                                                                                                                           | Reference/content owners / #412, #416, and #414                                                                |
| A current-authority consumer revalidates retained grades and commits a mastery or drill mutation inside the same authority scope.                                                                                                                                                                    | `not started`                  | [ADR 0074](../decisions/0074-persist-revalidated-grade-audit-evidence.md) and [ADR 0076](../decisions/0076-expose-retained-grade-audit-evidence.md) preserve immutable, redacted historical evidence only. Every artifact remains `requires_current_catalog_hand_and_content`.                                                                                                                                                                                                                                                                                                                                                                                                 | A later consumer may exist only after the gate clears and must revalidate current hand, reference, content, and lifecycle authority inside its mutation scope.                                                                                                                          | Grading/learning owner / #416 and #418                                                                         |
| A written Phase 0 report verifies all evidence and records one final `go`, `reshape`, or `stop` decision.                                                                                                                                                                                            | `not started`                  | This ledger makes the current no-go state auditable but deliberately is not the final decision.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | Complete #409 and #412 evidence, verify the release-candidate safety/local-delivery/lifecycle matrix, resolve material ADR drift, and obtain the named decision and owners in #414.                                                                                                     | Product gate owner / [#414](https://github.com/Studio81Labs/sidekick/issues/414)                               |

## Evidence that must not be overstated

- Synthetic parser fixtures and a passing current-subset assessment validate
  contracts and tooling, not the representative corpus or 99% import gate.
- The V1 preflop chart, postflop providers, and screenshot benchmark were
  removed under ADR 0079. Their removal neither qualifies a native source nor
  permits mastery or drill generation.
- A future native certification harness must prove its own fail-closed
  validation behavior; it cannot reuse the retired screenshot schema as source
  evidence.
- Empty install-local reference and learning-content catalogs prove safe default
  behavior, not production readiness.
- A retained `ReferenceActivatedGrade` and the player grade-audit response are
  historical evidence. Neither is current learning authority.
- Closing implementation issues #413 and #432 records their repository scopes;
  it does not override the shared gate or clear the two viability spikes.
- No private corpus, vendor correspondence, license document, source export, or
  player-identifying data is committed or implied by this ledger.

## Re-entry checklist

### Import evidence — issue #409

1. Acquire free public source histories, qualify their provenance/permission
   and representative composition, and author labels independently of parser
   output. Personal histories from the owner are not a prerequisite; retain
   sensitive originals outside Git even when publicly downloadable.
2. Preserve the completed bounded tournament/automatic/status mappings;
   implement remaining required tournament variants and missing action-origin
   semantics only from new reviewed, versioned sources.
3. Add verified coverage gates for every currently unsupported required
   category.
4. Run the complete assessment with approximately 1,000 cases, the 99% floor,
   required composition, and a pinned corpus fingerprint.
5. Retain a sanitized aggregate report and independent review record; retain no
   private source or identity data in the repository.

### Grading evidence — issue #412

1. Complete the bounded R0a no-fee source screen and decision in the
   [source assessment](./v2-grading-reference-assessment.md#r0a-execution-and-exit).
   HRC, paid alternative suppliers and trials are not prerequisites.
2. Obtain an eligible complete artifact and inspect actions, sizes, frequencies,
   EVs/units, utility, settings, convergence and applicable code/data/output
   rights. Record any material gap; public code alone is not a license.
3. Freeze final R0 economics/coverage from #409, the independent review method
   and feasible existing-hardware/operator capacity, then execute R1–R4 serially.
4. Retain all existing benchmark, stability, negative-boundary and useful-coverage
   evidence. Zero external fees is the owner-set ceiling, not a waived quality
   gate or a promise that compute and review take no resources.
5. If no eligible free source exists in the bounded pass, report the exact
   shortfall and escalate a concrete product-scope proposal; do not treat a
   narrow research game as a successful current preflop gate.

### Final gate — issue #414

1. Verify the two completed evidence packages against the product spec and ADR
   0046 without weakening any threshold.
2. Re-run and attach the release-candidate safety, direct-network,
   local-delivery, current-format backup/restore, unsupported-version rejection,
   application-upgrade procedure, and lifecycle evidence. The application
   upgrade must preserve current player data and security and verify the safe
   browser-shell handoff on the accepted validation platform. The [runtime
   procedure](../process/local-player-runtime-foundation.md#browser-shell-updates)
   currently implements only the browser-shell handoff; the application-file
   update lifecycle remains unimplemented/unvalidated. Record the accepted
   release procedure and actual upgrade evidence before `go`; an unsigned
   bundle or unsupported-schema rejection alone cannot pass this prerequisite.
   This does not restore old-format readers, V1 fallback or a downgrade path.
   A new installer/update channel still requires the explicit release decision.
3. Choose exactly one supported outcome: `go`; a narrower, evidence-backed
   `reshape`; or `stop` based on demonstrated source failure.
4. Name owners, rollback, unresolved risk, and entry criteria for the chosen
   outcome. Update or supersede ADR 0046 only if the boundary changes.

## Work prohibited while blocked

Until #414 records a supported final decision, do not:

- activate a production reference or teaching-content catalog;
- expose retained audit grades as authoritative current player grades;
- consume grade evidence for mastery, aggregate mixing, leak ranking, proof, or
  drill scheduling;
- begin Phase 1 player/dogfooding validation;
- claim directional learning or transfer;
- begin Phase 2 site breadth or Phase 3 hosted hardening; or
- enable a remote provider request without its qualified source, exact consent,
  minimized disclosure, and transport evidence.

The safe next work is evidence production under #409 and #412, followed by the
single final decision in #414.
