# ADR 0077: Retain Tournament Entry and Blind-Level Source Facts

Status: accepted; P1a0 compatibility implementation in PR #500; P1a parser mapping pending under issue #409

The V1 retention and pre-release compatibility requirements below are superseded
by [ADR 0079](0079-adopt-an-unreleased-current-only-cutover.md). Domain, current
V2 provenance/lifecycle and security requirements remain in force. Earlier
implementation details are retained as decision history.

Date: 2026-09-08

Resolves the architectural decision in issue #498 under Epic #405. PR #500
implements the P1a0 compatibility precursor below. Tournament parser mapping,
source-label work, and the remaining P1a work are still pending under #409.

## Context

PR #497 retained a sanitized, attributed PokerStars tournament specimen. Its
header contains `Tournament #800000000, $3.19+$0.31 USD` and
`Level XI (400/800)`. The Epic requires these supplied facts to remain distinct
and reviewable. Before P1a0, `TournamentEconomics` had no entry-cost fields,
and its `stage` field was part of the route-critical tournament context. Raw
header retention alone did not satisfy the distinct detected-field requirement.

The same economics model appears in detected and approved hands, extracted
decisions, retained grade snapshots, and offline recommendation economic models.
Its serialized values participate in content, semantic and economic hashes.
Adding ordinary nullable defaults would insert new null keys into old payloads,
potentially invalidating retained checksums, snapshot restoration and reimports.
The P1a0 compatibility precursor advances the player workspace from layout v4
to v5 and portable backup output from v2 to v3 before new fields can be
persisted. It intentionally does not add tournament parser behavior.

## Decision

### Domain and units

Extend `TournamentEconomics`, without changing its `kind` discriminator, with
these three optional source facts:

| Field          | Python type                   | Meaning                                                                                                                         |
| -------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `entry_buy_in` | Optional `NonNegativeDecimal` | Site-reported base entry amount, in the denomination identified by the existing `currency`; not an inferred prize contribution. |
| `entry_fee`    | Optional `NonNegativeDecimal` | Separately reported entry fee in that same denomination; not cash-hand rake or a rake schedule.                                 |
| `blind_level`  | Optional `NonEmptyText`       | Source level label, such as `XI`; preserve its spelling without converting it into a tournament stage or ordinal.               |

All three default to `None`. Monetary arithmetic uses the existing finite,
nonnegative Decimal contract; JSON uses decimal strings. Zero is a supplied
value, distinct from unknown. The amounts are independent optional facts; do
not infer a missing partner, currency, total, bounty allocation or payout.
An explicit `USD` token supplies currency; a bare dollar sign alone does not
prove USD. Non-currency tournament-entry denominations require a further
evidenced contract rather than being mislabeled as currency.

For the pinned two-component header, the target detection contains
`entry_buy_in="3.19"`, `entry_fee="0.31"`, `currency="USD"`, and
`blind_level="XI"`. `game.blinds.small_blind=400` and `big_blind=800` remain
absolute tournament chips. Ante amounts and poster mode come from evidenced
posting semantics. Never convert entry costs into chips or include them in
stacks, pot reconstruction, hand rake, payouts, or ICM completeness.

`stage` retains tournament progression/strategic context, such as a separately
established bubble or final-table stage. A level number or Roman numeral does
not establish it; this header leaves `stage=None`. Do not reinterpret legacy
non-null stage values or make a new stage taxonomy in this change. New fields
are not added to extraction or economic-completeness prerequisites. Existing
payout, field, stack, bounty, stage and ICM gates still apply independently.

This approves only the evidenced entry pair and level representation. It does
not approve splitting arbitrary multi-component/PKO headers, assigning bounty
economics, interpreting the specimen's competing timestamps, labeling action
origin, or filling the remaining full-hand labels. Unproved syntax keeps the
existing per-hand diagnostic boundary; unrelated hands still proceed.

### Evidence, review and contracts

The parser records existing `DetectedFieldEvidence` at these JSON pointers:

- `/game/economics/entry_buy_in`
- `/game/economics/entry_fee`
- `/game/economics/blind_level`

Retain currency and blind evidence at their existing pointers. Each supplied
fact points to its retained header line and existing confidence/warning
metadata. Raw source text and adapter/version provenance remain immutable.
Missing values have no invented source evidence.

The dedicated local hand-detail and approval APIs continue carrying generic
state JSON. Known values appear through the existing detected/canonical audit
projection and JSON review UI. Verify explicit null/removal, invalid values,
and correction reasons through those boundaries. Existing correction-diff
behavior may record the enclosing economics pointer when keys are added or
removed; its before/after values must preserve a complete review audit. Do not
redesign correction granularity just for these fields.

No route, event, hosted OpenAPI contract, local access boundary or remote
transport is added. Local JSON consumers must tolerate absent optional keys.
If implementation exposes these native models through any additional typed
contract, align and validate that actual consumer rather than hand-editing
generated artifacts. Keep the remote reference boundary unchanged.

### Serialization, hashes and reimport

Give only these three new fields `Field(default=None,
exclude_if=lambda value: value is None)`, using the existing Pydantic pattern in
`RecommendationEconomicBlindLevel.ante_mode`. Apply the exclusion to normal
Python and JSON serialization, not only a hand-hash helper. An explicit null
normalizes to absence. Do not globally enable `exclude_none` or `exclude_unset`,
drop pre-existing null keys, weaken aggregate revalidation, or discard known
values from a hash to make old expectations pass.

For legacy records without these facts, content and semantic fingerprints,
canonical serialization, record-version hashes, economic-configuration hashes,
decision snapshots and grade restoration must remain unchanged. Known new
values must be included wherever the containing state/economics is serialized
and hashed, including the existing economic-configuration hash. Exact reference
matching therefore remains fail-closed if the retained facts differ; this
decision does not introduce metadata-insensitive matching or relax qualification.

Keep the imported-hand raw/detected/canonical/aggregate `v1` schema tags: their
extension is optional, with unchanged legacy serialization. Use the explicit
workspace and backup capability versions below to exclude older player readers.
Do not regenerate old detections, approved revisions, decision/grade artifacts,
policy artifacts, or digests during upgrade.

Identity and record keys are unchanged. A parser version that discovers new
facts uses normal ingestion and its retained provenance. A materially changed
detection for the same raw bytes creates the existing conflict; it cannot
overwrite or silently enrich approved state. Null and omission of these new
fields have the same meaning. Distinct known values have distinct semantic
fingerprints. Existing deletion, reapproval and stale-request behavior remains.

### Workspace and backup compatibility

Advance the player workspace capability marker to layout **v5** before a writer
can persist populated new fields. Implement an explicit v4-to-v5 migration under
the existing exclusive data-volume hold, with a manifest recheck, validation of
the existing private imported-hand directory and consent/reference/content
stores, then durable same-directory manifest replacement. Reuse the existing
locking, ownership, no-symlink, atomic replacement and retry rules from ADR 0059.
This migration changes only the marker, not retained payloads, catalog contents
or journal bytes. Preserve legacy adoption and v1/v2/v3 upgrade support. Future
versions and attempts to downgrade fail closed. A running v4 process must reject
subsequent operations after observing v5 through its existing manifest check.

Advance portable player backup output to schema **v3**, retaining the current
archive layout and artifact checksums. New readers accept v1, v2 and v3: v1 must
omit `grade_artifacts`; both v2 and v3 must explicitly declare it. Keep the v2
rule explicit when changing the current-version constant. Older readers reject
v3 at manifest validation, before restore mutation. New readers restore legacy
archives without relabeling their records or recomputing historical hashes.
Whole-archive preflight, size/path limits, conflict checks and atomic restore
remain unchanged. Catalogs and consent remain excluded from portable backup.

This is forward upgrade/read compatibility, not permission for an old binary to
read new known facts. Rollback uses a pre-upgrade backup in a separate compatible
workspace. Never lower a marker in place, strip fields, rewrite audit history,
or silently export a lossy legacy archive to facilitate downgrade. Existing
offline files containing populated fields also require the upgraded reader;
unsupported strict-model validation remains explicit.

### Implementation boundary and validation

Serial execution under #496 landed this documentation decision first. PR #500
implements the completed P1a0 precursor; P1a remains separate:

1. **P1a0, #409 (PR #500):** domain fields and serialization; workspace v5/backup v3
   compatibility; local audit/review contract coverage; upgrade, retained-hash
   and artifact regression tests. No tournament parser behavior yet.
2. **P1a, #409:** evidenced tournament parser mapping, source labels, header and
   summary tests, and adapter provenance. Remaining source semantics must still
   be established before corresponding parser behavior.

Keep completed issues #410 and #432 closed; this is an evidenced extension under
#409, not a reopening of their completed acceptance criteria. #498 tracks the
architectural decision, not implementation completion.

P1a0 uses retained fixtures made by the pre-change models, including a
legacy tournament with an approved revision, extracted decision and grade audit.
Check their original bytes/digests rather than regenerating all expectations
with the new models. Required validation includes:

- Exact legacy content/semantic/economic/record-version hashes; decision and
  grade snapshot restore and re-derivation; unchanged absent/null serialization.
- New known values round-trip through model, record, decision, grade and backup;
  differing values change relevant hashes; negative/non-finite amounts and empty
  labels reject, while zero and incomplete context remain reviewable.
- Null/missing/known corrections, reapproval and reimport conflict behavior;
  no automatic approval, extraction-readiness promotion or pot changes.
- Layout v4-to-v5 and older upgrades, repeated/interrupted publication, ownership
  and lock checks, future-version rejection and old-process fencing; compare
  retained payload and recovery evidence bytes before/after migration.
- Backup v1/v2 read and v3 round-trip, required grade-list semantics, checksum
  tampering, preflight failure/no partial restore, and explicit old-reader
  rejection of v3. Exercise existing export-before-remove behavior with v3.
- Local detected/canonical JSON and correction API contracts; PWA review of known
  and absent keys; existing recommendation economics and reference qualification
  regressions because the model is shared.

PR #500 runs the relevant repository backend suites and local player UI tests,
and builds the player UI where it changes. It updates current
architecture/operational version claims for P1a0. A failure to preserve retained
hashes/artifacts, maintain reader fencing, or avoid changing route economics in
future P1a work requires escalation before continuing; it is not permission for
data repair or broader hash/normalization redesign.

## Consequences

The P1a0 compatibility precursor gives the orchestrator an exact contract for
the real source gap without needing a private solved export. Parser work can
resume after the remaining source-label checks. Legacy facts stay readable; new
facts stay independently reviewable and cannot become invented ICM inputs. The
cost is one focused compatibility PR and an explicit reader-version boundary.

The representative authorized corpus, supported solved-reference export and
delivery rights, independent poker review, budget evidence and Phase 0 gate
remain separate prerequisites. Neither this decision nor the public specimen
makes the full Epic ready or changes Phase 1's NO-GO status.
