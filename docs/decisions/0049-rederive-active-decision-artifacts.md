# ADR 0049: Re-Derive Active Decision Artifacts

Status: accepted

Date: 2026-08-31

## Context

`HandDecisionExtraction` is persisted beside its canonical imported-hand record.
Its Pydantic validators reject malformed shapes and many internally contradictory
chip states, while the filename binds the artifact to a canonical revision and
deletion generation. Those checks cannot prove that an otherwise valid payload
was actually derived from the record stored beside it. A changed action amount,
action type, betting increment, or foreign-but-self-consistent betting line can
therefore pass schema validation.

The aggregate already owns the complete extraction walk and can deterministically
rebuild the active artifact. Reimplementing betting rules inside either the
persisted contract or the store would create a second authority. Trusting the
store as the only writer is also insufficient: restore, manual repair, disk
corruption, and future migrations all cross a rehydration boundary.

One self-validation gap can be closed without replay. Whether a short all-in
reopened betting depends on the wager and full-increment yardstick at the hero's
prior action. The aggregate already holds both values, but the persisted decision
previously dropped them.

The persisted shape also duplicates source chronology and import provenance on
the extraction envelope and each decision point. The aggregate validation walk
and the extraction walk express the short-big-blind nominal bring-in with two
proven-equivalent forms, and `HeroDecisionState.validate_action_history` runs
ordered sub-checks whose later checks rely on earlier structural checks.

## Decision

The freshly validated `ImportedHandRecord` is the sole trust authority for active
decision state. `FileImportedHandStore.active_decisions` continues to select by
active revision and deletion generation, then re-runs
`extract_hero_decision_points` and requires the stored and derived extractions to
be completely equal. A mismatch raises `DecisionArtifactIntegrityError`. The
read does not repair or overwrite the artifact, because retained bytes are audit
evidence and replacement would violate artifact-retention guarantees.

`get_decisions` remains a historical audit primitive. It schema-validates the
requested artifact but does not claim semantic derivation from an inactive
canonical revision; historical artifacts are never eligible for grading,
mastery, or drills. A future historical-verification feature would need an
explicit revision-targeted extractor rather than borrowing the active extractor.

`HeroActionContext` and `HeroDecisionState` now publish `acted_wager` and
`reopen_increment`, copied directly from the extraction walk. Rehydration calls
the aggregate-owned `_raise_is_reopened` helper with those scalars and combines
that verdict with hero affordability and opponent actionability. It does not
replay `action_history`.

Chronology and provenance remain duplicated intentionally. The envelope needs
them for valid no-decision hands, while a decision point is the atomic unit sent
to grading and remains self-contained when inspected or audited independently.
Envelope validation keeps both copies equal.

The two nominal-bring-in expressions remain. They are implementation details at
different walks, have been verified equivalent for valid states, and are not a
persisted contract ambiguity. The ordered action-history sub-checks also remain
inside one explicit model validator; their dependency order is visible and
covered as one validation boundary. Neither structural note justifies a new
public contract or a broader betting-engine refactor.

## Consequences

Corruption-only contradictions in action deltas, hero action type, and the
current full-wager increment cannot enter active learning merely because each
field is locally legal: re-derivation detects the complete artifact mismatch.
The stored contract additionally proves the short-all-in reopening verdict from
its own published inputs.

An active artifact mismatch is a loud integrity failure rather than an empty
result or an automatic rebuild. The caller can preserve the evidence, report the
record as unavailable for learning, and invoke an explicit rebuild/repair path
when one exists. Unrelated hands remain readable and process independently.

The two added fields change the internal persisted decision shape. No V2 route,
production lifecycle writer, or player runtime consumer exists yet, so there is
no deployed compatibility surface to migrate. Any pre-boundary development
artifact that lacks the fields fails validation and must be rebuilt from its
canonical record; it is never guessed into validity.
