# V2 Grading Reference Source Assessment

Status: Phase 0 research checkpoint; source gate open

Initial assessment: 2026-08-27; HRC evidence/cutover checkpoint: 2026-09-10

Tracking issue:
[#412](https://github.com/Studio81Labs/poker-hero/issues/412)

This report records the locally actionable research for the V2 grading spike.
It is not a source approval, legal opinion, completed benchmark, or Phase 0 gate
decision. A reference becomes mastery-eligible only after the unresolved evidence
and all gates below pass.

## Recommendation

Proceed with a controlled validation of a **static, locally shipped preflop
policy derived from authorized HRC Pro exports**. Do not enable a remote solved
feed in Phase 1. Defer postflop mastery unless a separately sourced policy proves
its exact root inputs, independent benchmark quality, delivery rights, and
economics.

This recommendation is conditional. HRC is the strongest public candidate, but
Poker Hero does not yet have:

- a reviewed dossier binding applicable written terms to the actual exported
  results, generating licensee/key and chosen static delivery/update model;
- a representative HRC export proving that all required actions, exact sizes,
  mixed frequencies, EVs, EV units, utility model, configuration, and convergence
  evidence are available;
- a normalized policy revision or an independently reviewed benchmark corpus;
- a benchmark run or a real-hand coverage study; or
- an agreed acquisition, compute, review, and update budget.

Until those items exist, no native grading route is qualified or
mastery-eligible. The V1 preflop chart and postflop routes were removed under
ADR 0079. This preserves the
[V2 trustworthiness gate](../specs/poker-hero-product-spec.md#52-the-trustworthiness-gate-non-negotiable)
and [ADR 0046](../decisions/0046-adopt-import-first-learning-boundary.md).

## Evidence method

The report uses three evidence classes deliberately:

- **Verified public fact**: a statement supported by a linked vendor document,
  vendor terms, or upstream repository.
- **Repository fact**: behavior visible in Poker Hero source or an accepted ADR.
- **Assessment**: a Poker Hero-specific conclusion drawn from those facts. An
  assessment is not a vendor promise or legal conclusion.

Public pages and prices were checked on 2026-08-27. Vendor terms, products, and
prices can change; the eventual rights dossier must preserve dated copies and
checksums of the terms actually reviewed. Rights findings below identify product
risk and require qualified review where appropriate; they are not legal advice.

## Current repository baseline

The current components deliberately do not provide a V2 solved reference:

- ADR 0079 removes the V1 preflop chart, postflop solver, generic HTTP adapter,
  and screenshot recommendation benchmark. They cannot be restored as a source
  qualification shortcut.
- The current remote-reference consent and dispatch contracts are fail-closed
  infrastructure, not a configured reference feed or policy evaluator.
- A future native certification implementation must carry immutable
  reference/policy/tolerance revisions; source, configuration, and normalized
  policy digests; declared coverage; economic and utility provenance; an EV
  unit; delivery-specific rights evidence; and passing convergence evidence.
  Declarations alone do not prove source ownership, input completeness,
  delivery rights or that an artifact implements its declared model.

Consequently, a corpus generated from the removed chart/solver cannot satisfy
issue #412 by being relabeled. The independent reference must exist first; the
benchmark measures the adapter against it.

## Candidate inventory

### HoldemResources Calculator (HRC)

**Verified public facts**

- HRC Pro describes itself as capable of tournament and cash-game calculations
  at any stack depth. Its cash-game documentation supports rake configuration
  and says cash calculations use ChipEV. See
  [HRC pricing](https://www.holdemresources.net/hrc/pricing) and
  [cash-game configuration](https://www.holdemresources.net/docs/cashgame/).
- The documented `Export Strategies` function emits strategies and EVs in JSON.
  HRC also documents postflop abstraction as part of its preflop model. See the
  [HRC v3 release notes](https://www.holdemresources.net/blog/2023-hrc-v3-release/).
- The HRC 4 EULA permits commercial distribution and open sharing of results of
  authorized calculations. It prohibits automated scraping, backend access for
  other users, and use outside the launcher, and requires results to use the
  supported export/save functions. Additional key-specific terms may apply. See
  the [HRC 4 EULA](https://www.holdemresources.net/legal/eula/hrc_v4).
- Public list pricing on the review date was USD 49.99 monthly or USD 359.90
  yearly for HRC Pro. A license is for one user and two installations.

**Assessment**

HRC has the best apparent fit for the Phase 1 preflop floor: it can model the
required cash or tournament economics, construct multi-player preflop trees,
and export machine-readable strategies and EVs. A human operator can generate a
bounded dataset through supported product functions, then Poker Hero can ship a
normalized static lookup with no player-data egress or runtime network
dependency.

The [HRC 4 EULA](https://www.holdemresources.net/legal/eula/hrc_v4), rechecked on
2026-09-10, is written rights evidence, not an absence of published permission.
Assess it against the actual source/build, generating licensee, applicable
key-specific terms and proposed delivery. Do not make a bespoke vendor letter
an unconditional prerequisite: seek additional confirmation only where that
review identifies a material uncovered or ambiguous use. No actual export or
project/key-specific authorization has been established by this checkpoint.

The rights dossier must still address:

- embedding normalized or transformed exports in an open-source and/or
  commercially distributed local application;
- redistributing the complete mixed policy rather than isolated screenshots or
  reports;
- publishing replacement policy revisions and migration artifacts; and
- the intended attribution, repository visibility, and any key-specific terms.

HRC is therefore **preferred for validation, not yet cleared for shipping**.
Acquisition price appears bounded; solve-generation time, hardware, human
review, coverage breadth, and recurring update cost are still unknown.

### PioSOLVER

**Verified public facts**

- PioSOLVER Pro and Edge solve heads-up flop, turn, and river spots; only Edge
  advertises a preflop solver, and that preflop solver is heads-up. Public prices
  on the review date were EUR 450 for Pro and EUR 800 for Edge. See
  [PioSOLVER products](https://piosolver.com/products/).
- The personal terms permit sharing results, saves, observations, and coaching
  material but forbid turning the personal product into an on-demand result
  service. Software integration must require a licensed PioSOLVER. See
  [PioSOLVER terms](https://piosolver.com/docs/licensing/).
- PioSOLVER publicly offers a high-volume business license for on-the-fly
  computing, API access, and cloud products at EUR 5,000 per month for 100
  computers. See its [business FAQ](https://piosolver.com/docs/faq/business/).
- The standalone application runs offline but periodically contacts its license
  server.

**Assessment**

PioSOLVER cannot supply the required six-max or other multi-player preflop floor.
It could be an independent source for a bounded heads-up postflop corpus, but
only after complete prior-street ranges, action history, effective stack,
position, board, economics, tree abstraction, and convergence are pinned.

The personal terms do not explicitly settle redistribution of a complete
embedded policy dataset, and they forbid an on-demand result service. Written
static-embedding permission or a suitable commercial agreement is required.
The published server license is a material recurring cost and would create a
network dependency and remote-provider privacy work. PioSOLVER is therefore a
**possible independent heads-up postflop checker, not the Phase 1 preflop
source**.

### MonkerSolver

**Verified public facts**

- MonkerSolver advertises Hold'em and Omaha solving from any street with any
  number of players, customizable betting trees, and abstraction controls. Its
  public price on the review date was EUR 499. See the
  [MonkerSolver product page](https://www.monkerware.com/solver.html).
- The official getting-started guide says tree size and solve time depend on RAM
  and CPU and that large preflop trees may take several days to converge. See the
  [MonkerSolver guide](https://monkerware.com/guide.html).
- MonkerViewer can open locally exported ranges and exposes mixed-strategy
  views. See the [MonkerViewer page](https://monkerware.com/viewer.html).
- The public [terms of service](https://monkerware.com/tos.html) describe a
  personal, non-transferable account and service limitations, but do not grant
  explicit commercial embedding, redistribution, update, or server-serving
  rights for solver outputs.

**Assessment**

MonkerSolver is technically plausible for multi-player preflop and possibly
multiway postflop, but public evidence is weaker than HRC for an auditable,
machine-readable export pipeline and much weaker for the selected delivery
rights. Large-tree compute and reproducibility costs may also be substantial.
It remains a **fallback candidate only after written commercial output and
embedding rights plus a real export inspection**.

### GTO Wizard public benchmarking API

**Verified public facts**

- The public API is an agent-performance benchmark, currently heads-up no-limit
  at 200 BB. GTO Wizard says it permits playing hands and observing results but
  does not expose solver capabilities. See the
  [benchmark page](https://gtowizard.com/benchmark).
- Its terms restrict use to benchmarking an agent, prohibit systematic strategy
  extraction and model distillation, allow publication and improvement use of
  submitted hand histories and decision logs, and make access revocable. See the
  [benchmark API terms](https://gtowizard.com/benchmark/terms).

**Assessment**

This API is **rejected for grading-reference sourcing**. It supplies neither a
complete policy nor redistribution or derived-output rights, and its authorized
purpose and anti-extraction terms conflict directly with building a static
lookup. It is network-dependent and its public-data terms are also incompatible
with Poker Hero's minimized, private optional-feed boundary. A distinct future
commercial GTO Wizard agreement would be a new candidate and must be assessed
from scratch; the public benchmark key is not such an agreement.

### Previously bundled `b-inary/postflop-solver`

**Verified public facts**

- The upstream project is a Rust postflop solver using Discounted CFR and is
  licensed AGPL-3.0. The maintainer suspended open-source development in
  October 2023 and warns that breaking changes may occur without version
  changes. See the
  [`b-inary/postflop-solver` repository](https://github.com/b-inary/postflop-solver).
- Before #520, Poker Hero pinned upstream commit
  `9d1509fe5077d019825f833eed04b16d342dfda1` and exposed it through a separate
  stdin/stdout process. That removed adapter accepted heads-up postflop states
  only, derived or configured ranges, built a constrained tree, and recorded
  assumptions, candidate frequencies, EVs, and exploitability.

**Assessment**

The component has no license fee or runtime network dependency and the pinned
commit improves reproducibility. It is not preflop, is not independent of the
removed provider being evaluated, and its assumed/derived root ranges do not
meet V2's exact-input gate. Its AGPL distribution obligations also require a
release-compliance review.

ADR 0079 and merged #520 supersede the earlier recommendation to retain this
component. The solver and its exclusive runtime consumers are removed. Its own
output cannot substitute for an independent reference, and it must not be
restored as a fallback while #412 is blocked.

## Comparison matrix

| Candidate                | Potential coverage                                    | Delivery fit                                                | Public rights evidence                                                                                       | Cost evidence                                                       | Network and continuity risk                                                                                 | Phase 0 disposition                                      |
| ------------------------ | ----------------------------------------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| HRC Pro                  | Multi-player preflop; cash and tournament models      | Operator-generated static export fits local-first           | Published distribution grant for authorized results; actual source/key/delivery applicability review pending | USD 49.99/month or 359.90/year, plus unknown compute/review cost    | No player runtime network for a static lookup; generation depends on licensed product and vendor continuity | Preferred conditional preflop validation                 |
| PioSOLVER                | Heads-up postflop; heads-up preflop in Edge           | Static HU corpus is possible; remote compute is undesirable | Personal result sharing allowed, on-demand service forbidden; complete dataset embedding unclear             | EUR 450 Pro, EUR 800 Edge; published server license EUR 5,000/month | Periodic license check; a server feed adds runtime network and privacy dependency                           | Reserve for independent HU postflop evidence             |
| MonkerSolver             | Any street/player count advertised                    | Static exports may fit, but pipeline is unproven            | No explicit public commercial embedding/update grant found                                                   | EUR 499 plus potentially large hardware/time cost                   | Static lookup avoids player runtime network; vendor/account and long-solve continuity remain                | Fallback only after written rights and export inspection |
| GTO Wizard benchmark API | 200-BB heads-up agent games, not solver policy access | Does not supply a lookup policy                             | Benchmark-only; extraction/distillation forbidden                                                            | Public benchmark access, not a licensable grading dataset           | Mandatory network, revocable access, public benchmarking data                                               | Reject                                                   |
| Removed b-inary solver   | Historical heads-up postflop trees only               | Removed in #520                                             | AGPL-3.0; distribution compliance required                                                                   | No license fee; local compute cost                                  | No runtime network; upstream development suspended                                                          | Removed under ADR 0079; no fallback retention            |

## Proposed Phase 1 coverage and delivery boundary

The source-validation run must choose its coverage from the dominant format in a
versioned corpus of approximately 1,000 real target-user hands. Do not generate
a broad chart before that corpus identifies table size, stakes or tournament
type, stack distribution, rake/economic model, and recurring action routes.

The first policy revision should contain only the bounded combinations explicitly
solved and benchmarked. Its manifest must enumerate:

- game type, blind/ante structure, dealt-in count, and structural positions;
- cash rake mode, percentage, cap, and currency/blind conversion, or tournament
  chip-EV/ICM/bounty model and every required tournament input;
- effective-stack values or closed intervals whose policy equivalence was
  independently demonstrated;
- the full action tree through RFI, calls, versus-RFI, three-bet, four-bet,
  blind-defense, squeeze, cold-call, limp, and short-stack branches actually
  included;
- every allowed action and exact total sizing at every node;
- unsupported routes, including any economics, table count, structural
  position, stack, sizing, or action sequence not represented exactly; and
- the immutable policy, normalization, support-tolerance, and schema revisions.

A request outside that manifest returns an explicit unsupported result. It is
never coerced to the nearest position, stack, size, or economic model.

The delivery artifact is a versioned static lookup installed with the local
application. Policy generation may use a licensed desktop solver, but neither
the solver binary nor license key is shipped. Phase 1 makes no solved-data
request at runtime and therefore adds no player-data egress. A remote feed may
be reconsidered only in a later decision with explicit commercial serving
rights, a field allowlist, consent and revocation UX, encrypted transport,
retention/training/logging terms, auditable request/response provenance, and a
usable local-only mode.

If that later decision is opened, its maximum outbound allowlist is the
pseudonymous route state needed for one lookup: game/economic model, table size
and structural positions, effective stack and exact sizing, prior actions, board
and hole-card values or documented abstractions, and exact conditioned ranges.
It must exclude raw hand histories, site/hand/session identity, player names,
source timestamps, screenshots, import/canonical record identifiers, and all
mastery, profile, lesson, and drill data. Provider failure or revoked consent
must make remote-only coverage visibly unavailable, never trigger an
undisclosed provider or heuristic-to-solved fallback.

Postflop remains `heuristic` and ungraded for mastery unless a separate source
passes the same gates. In particular, even heads-up output is not solved-grade
eligible when stack, relative position, pot/action history, board, ranges, prior
street conditioning, economics, or policy revision is assumed or incomplete.
Multiway postflop is deferred rather than approximated as solved.

## Required evidence artifacts

The following files or equivalent immutable records are mandatory before a
`go` recommendation. Artifact names below are proposed so the gate can be
audited consistently.

1. `coverage-manifest.json`: the complete inclusion and exclusion matrix above,
   plus a stable node-key specification.
2. `rights-dossier/`: dated applicable terms snapshots and checksums,
   purchase/key-specific conditions, source ownership/licensee evidence,
   attribution requirements, and reviewer approval mapping granted rights to
   the actual embedding, redistribution, commercial-use, and update mode.
   Include vendor correspondence only when needed to resolve a material
   uncovered or ambiguous use; sufficient applicable published terms do not
   require a separate letter.
3. `source-build.json`: solver product/tier, exact version/build, license owner,
   export path, generation host, hardware, date, and operator.
4. `solve-configs/`: one immutable input configuration per tree, covering the
   full bet tree, stack/table/position map, card and postflop abstraction,
   rake/equity/utility model, convergence target, seed or sampling controls, and
   expected EV/cost unit.
5. `raw-exports/`: unmodified supported-function exports with SHA-256 checksums.
   A representative sample must be reviewed before bulk generation.
6. `normalization-spec.md` and a versioned normalizer: exact mappings for node,
   position, action, sizing, hand class, frequency, EV, unit, and utility-model
   fields, with rejection rules for missing or ambiguous values.
7. `policy-revision.json`: normalized complete positive-frequency action support,
   exact sizings, frequencies, candidate EVs, EV/cost unit, utility provenance,
   economic assumptions, source/build/config hashes, normalizer revision, policy
   revision, and artifact checksum for every covered node.
8. `convergence-report.json`: source convergence evidence plus duplicate-run
   stability results for a predeclared stratified node sample.
9. `reference-corpus.json`: independently reviewed, stratified benchmark cases
   that were not produced by the provider implementation being evaluated. It
   includes negative cases immediately outside every coverage boundary.
10. `benchmark-baseline.json`: full machine-readable results, dataset
    fingerprint, provider revision, all thresholds, per-case output, and human
    reviewer sign-off.
11. `real-hand-coverage.json`: coverage and rejection rates over the fixed target
    corpus, broken down by table size, position, stack, action route, sizing, and
    economics. Unsupported decisions remain visible but ungraded.
12. `cost-and-update-plan.md`: license, hardware, operator/reviewer time, artifact
    size, update cadence, vendor/version drift triggers, and an approved budget.
13. `migration-plan.md`: staged activation rehearsal in an explicitly labelled
    disposable local test authority, compatibility test, rollback, and atomic
    regrade/rebuild or separate-series behavior for grades, mastery, drills,
    principles, and proof metrics. It records the test authority identity and
    artifact/catalog/content digests. It is not production publication or
    activation: production catalogs remain empty until #414 records the final
    decision, after which #416 is the only production-activation path.
14. `phase-0-grading-gate.md`: signed `go`, `reshape`, or `stop` recommendation
    linking every artifact and listing residual risk.

The retired screenshot benchmark's schema-v5 envelope is historical evidence
only. A future native certification contract must independently retain immutable
revisions and artifact digests, declared coverage, economic and utility
provenance, an EV unit, delivery-specific rights evidence, and convergence
evidence. Declarations alone do not make a source trustworthy.

Further V2 certification work must match native decisions to the declared
economics, positions, stacks, action route, and complete policy; it must add
negative expected-unsupported cases and connect eligibility to the production
mastery gate. Remote consent/privacy enforcement and real evidence/results
remain separate requirements.

## Proposed benchmark gates

These thresholds are requirements for the HRC-derived lookup validation, not
claims about a benchmark that has already run.

### Artifact and route integrity

- 100% of covered cases match the pinned source, build, solve configuration,
  economic/utility model, table size, structural positions, effective stack,
  action history, sizing tree, policy revision, normalization revision, and EV
  unit.
- 100% of covered cases return a complete valid distribution containing every
  positive-frequency source action and no invented action.
- 100% line coverage and 100% action/sizing identity agreement after documented
  normalization. Sizing tolerance is at most 0.01 BB and never wider than half
  the source export's sizing resolution.
- 100% policy and EV coverage. Mean total-variation policy distance is at most
  0.005 and no case exceeds 0.01 after accounting for documented export
  rounding. Maximum selected-line EV loss is 0.01 of the declared EV unit; a
  larger EV-equivalence tolerance requires separate poker-review approval.
- 0% fallback, assumed-input, policy-incomplete, unknown-provenance, or remote
  routing among covered cases.
- 100% of negative boundary cases are rejected as unsupported, including the
  nearest unsupported table size, position, stack, action size, action sequence,
  and economic model. No nearest-neighbor coercion is allowed.
- Identical normalized artifact checksums and benchmark results across three
  clean lookup builds from the same raw exports.

### Source quality and useful coverage

- Duplicate independent solver runs over a predeclared stratified sample have
  mean policy total-variation distance at most 0.02 and 99th percentile at most
  0.05. The source's native convergence/error measure must also meet a threshold
  documented and frozen before bulk solving; absence of an auditable native
  measure is a `reshape` or `stop`, not a waived check.
- A poker-qualified reviewer verifies 100% of solve configurations and a
  stratified sample of at least 100 exported nodes. Any material tree,
  economics, unit, position, or action-mapping error fails the gate and requires
  regeneration.
- The fixed approximately 1,000-hand target corpus parses and reconciles first.
  The policy must exactly cover at least 80% of its voluntary preflop decision
  points overall and at least 60% in every declared high-priority route. The
  lookup must still be 100% correct within its declared coverage. Coverage below
  the floor may `reshape` to a narrower explicitly useful product only with
  poker-player approval; it may never be hidden by coercion.
- License, generation, review, storage, and update costs fit a written budget
  approved before bulk generation. A public sticker price alone does not pass
  this test.

The removed screenshot benchmark's example thresholds are historical V1
regression defaults, not the native V2 source-certification gates. The stricter
gates reflect that a deterministic static lookup has no reason to lose provenance, omit
policy mass, fall back, or approximate an in-matrix node.

## Go, reshape, and stop decision rules

### Go

Recommend `go` for preflop-first Phase 1 only when all required artifacts exist,
the actual delivery mode has explicit written rights, every benchmark and
coverage threshold passes, and cost is approved. Before that decision,
update/migration and immutable-revision compatibility are rehearsed only in an
explicitly labelled disposable local test authority, with exact authority and
artifact/catalog/content digests plus rollback results retained as evidence.
That rehearsal is not production publication or activation: production
reference/content catalogs remain empty until #414 records the final decision,
and #416 is the only production-activation path after a supported decision.
Postflop may still remain deferred under a preflop `go`.

### Reshape

Recommend `reshape` when trustworthy preflop grading is possible only after a
bounded change that preserves an independently useful teaching loop, for
example:

- written rights or benchmark quality cover a narrower table size, economic
  model, stack band, or action tree than planned;
- real-hand coverage misses the proposed floor but a clearly named route such as
  one cash-game table/rake/stack band remains frequent enough to validate
  learning; or
- postflop rights, roots, or benchmark quality fail while the preflop floor
  passes.

The reshaped matrix and success criteria must be approved before implementation;
unsupported cases remain heuristic/ungraded.

### Stop

Recommend `stop` for the V2 mastery loop when no independently solved preflop
source provides complete mixed-policy and EV/unit evidence under rights matching
the shipped delivery mode, or when the real benchmark cannot meet integrity,
quality, useful-coverage, reproducibility, or approved-cost gates. Also stop a
remote-only proposal that cannot preserve explicit consent, minimization,
retention/use bounds, revocation, auditability, and a usable local-only mode.

Do not substitute the removed V1 chart/solver output, configured ranges,
or an unauthorized/public benchmark API when a gate fails.

## Outstanding external work

Issue #412 and the Phase 0 grading gate remain open. The next evidence-producing
steps are:

1. Assign an evidence custodian/generating operator and review the applicable
   terms for the exact static delivery, source ownership, key, attribution and
   update plan. Retain dated terms/checksums and any needed clarification.
2. Obtain one complete, authorized `Export Strategies` JSON from a licensed
   operator, with its actual version/build, setup and convergence metadata.
   One tree starts export inspection; it does not complete representative
   coverage. No qualifying downloadable complete export has been verified in
   the recorded investigation. Configuration-only JSON or a viewer save does
   not substitute.
3. Inspect the raw JSON for complete strategies, exact sizes, frequencies, EVs,
   unit/utility provenance, configuration identity, and convergence evidence.
4. Select the initial economic and route matrix from the real target-user corpus,
   then freeze the coverage manifest and solver-quality threshold.
5. Build the normalizer and V2 benchmark schema, have a poker-qualified reviewer
   validate configurations, and run the real source, stability, negative-boundary,
   lookup, and real-hand coverage benchmarks.
6. Record actual acquisition, compute, review, artifact-size, and update costs,
   then publish the Phase 0 `go`, `reshape`, or `stop` recommendation.

PioSOLVER or MonkerSolver outreach should begin only if HRC permission, exports,
or benchmark quality fail, or if independently sourced heads-up postflop coverage
is pursued. No vendor has been selected by this report.
