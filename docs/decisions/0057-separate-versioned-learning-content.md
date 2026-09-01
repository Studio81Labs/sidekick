# ADR 0057: Separate Versioned Learning Content From Canonical Decisions

Status: accepted

Date: 2026-09-01

## Context

The imported-hand boundary now produces canonical, revision-bound hero decision
points. Issue #417 needs a versioned concept taxonomy and human-reviewed
principle library, but attaching the current taxonomy directly to
`HandDecisionExtraction` would make canonical decision integrity depend on
mutable learning content. A taxonomy migration could then make an otherwise
valid retained decision artifact compare unequal to its canonical hand.

The later grading, mastery, drill, and proof-metric issues have not yet created
their persisted artifacts or a cross-artifact transaction. Pretending those
participants exist would either couple taxonomy code to speculative models or
claim an atomic migration boundary that cannot yet be exercised.

## Decision

Versioned learning content lives under `app/domain/learning_content`, separate
from imported-hand extraction and persistence.

- A taxonomy revision is an immutable hierarchy of stable concept IDs and
  immutable concept-definition revisions.
- A mapping revision targets exactly one taxonomy revision. Rules are
  versioned data over canonical decision-state fields. Every selector is
  explicit; catch-all rules are invalid.
- Tagging returns either no tag with an explicit reason or exactly one primary
  tag. A present tag binds the decision identity, canonical revision, deletion
  generation, decision index, taxonomy revision, mapping revision,
  concept-definition revision, and matched rule. Overlapping rules fail rather
  than selecting one by order.
- A principle revision pins one concept, taxonomy, definition, and grading
  reference-policy revision. Its status history is append-only. Every revision
  begins as a draft, including LLM-authored text, and approval requires a human
  actor plus review provenance.
- Activation derives affected concepts from the mapping and succeeds only when
  each has at least one exactly compatible approved principle. Draft,
  superseded, retired, and differently pinned principles do not satisfy the
  gate.
- Principle reveals retain the exact decision, taxonomy, mapping, definition,
  reference, and principle versions. Reusable cache keys retain the exact
  semantic taxonomy, mapping, definition, reference, and principle versions.
  Reveal text is structurally prefixed as conditional educational reference
  guidance.

The package is a pure domain boundary in this change. It does not mutate
`HeroDecisionPoint`, publish tags, activate a taxonomy, schedule a drill, or
persist learning content.

## Consequences

Canonical imported-hand artifacts remain byte-stable when learning content
changes. Unsupported decisions remain visibly untagged, ambiguous mappings fail
closed, and no LLM draft can become revealable or activation-eligible without a
human review event. Later consumers receive explicit compatibility gates and
version-complete cache/reveal contracts instead of reconstructing provenance.

Issue #417 remains open for the persisted catalog, staged taxonomy migration,
atomic publication with tags and future mastery/drill/proof artifacts, backup
and restore, and application composition. Those pieces will use the contracts
defined here once their real storage participants exist; this ADR does not
invent a transaction over absent consumers.
