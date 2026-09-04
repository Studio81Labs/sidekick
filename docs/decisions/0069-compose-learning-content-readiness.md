# ADR 0069: Compose Learning-Content Readiness Evidence

Status: accepted

Date: 2026-09-04

## Context

The grading domain can produce an independently qualified, complete solved-policy
comparison for one active canonical decision, but intentionally marks it
`requires_content_activation`. The learning-content domain can map that decision
to zero or one revision-pinned primary concept and prove that every concept
reachable from a mapping has at least one compatible human-approved principle.
Those contracts were separate, so the application layer could not yet prove that
a grade had compatible reviewed teaching content without trusting
caller-assembled tags or activation snapshots. A principle's policy-revision
label alone also cannot distinguish two otherwise different qualified reference
identities if an identifier is incorrectly reused.

Issue #416 requires heuristic and policy-incomplete decisions to remain outside
mastery and drills. It also forbids mixing reference revisions within a concept
and coverage band. The repository does not yet have the authoritative activation
catalog, coverage-band identity, or mastery-series migration boundary needed to
grant that eligibility safely. A per-decision composition therefore cannot label
an artifact learning-eligible.

## Decision

Add a persistence-free application composition boundary that produces immutable
`LearningContentReadyGrade` evidence. The service accepts the complete canonical
decision, grade, taxonomy revision, mapping revision, and principle records. It
defensively validates those inputs and then recomputes the grade,
primary-concept tagging, and content activation itself. Each immutable principle
revision embeds a structurally identical learning-content copy of the complete
`ReferencePolicyQualificationBinding`. That binding participates in the
principle semantic digest before human approval; only records bound to the
grade's complete qualified reference participate in coverage.

The boundary fails closed unless:

- the grade is an independently qualified, gradeable solved-policy comparison
  that still requires content activation;
- the full decision binding and grading-context digest match the supplied
  canonical decision;
- recomputing the grade from that exact decision, reference, and source
  qualification reproduces the retained grade, including the selected action;
- the source qualification binds the exact resolved reference, including its
  reference, policy, tolerance, coverage, route, engine, economic, utility, EV,
  threshold, and immutable artifact identities;
- the supplied taxonomy and mapping produce exactly one supported primary
  concept for the decision;
- every concept reachable from the mapping has compatible approved content
  bound to that exact qualified reference; and
- the retained approved principle records reproduce the exact eligible bindings,
  including semantic digests.

The output retains the full decision, grade, taxonomy, mapping, recomputed tag,
recomputed activation check, exact qualification binding, and complete approved
principle records with their immutable reference bindings. Keeping the records
preserves the append-only human reviewer, timestamp, and review-basis provenance
that a reduced binding would lose. Activation checks, principle reveals, and
principle cache keys also retain that full learning-content reference binding so
two different references cannot alias merely because they share a policy label.

The result is labeled `content_ready` and explicitly remains
`requires_reference_activation`. It is not learning eligibility. Only a future
authoritative catalog can pin one reference to a concept and coverage band and
issue evidence that later mastery or drill consumers may accept.

`LearningContentActivationCheck` also validates its set semantics. Affected and
missing concept IDs and eligible principle bindings must be sorted and unique,
eligible bindings may target only affected concepts, and the missing set must
exactly equal affected concepts without eligible principles. These invariants
make malformed snapshots invalid, while application composition still
recomputes the snapshot rather than trusting it.

## Consequences

Later reference activation has a narrow, provenance-complete input instead of
reconstructing grading and content compatibility. An absent tag, heuristic or
incomplete grade, selected-action mismatch, uncovered concept, stale mapping,
changed reference identity, forged qualification binding, invented tag
provenance, or unapproved principle fails closed before content-ready evidence
exists.

This decision does not persist grades or learning evidence. It does not publish
or activate a catalog revision, define coverage-band identity, migrate or rebuild
a mastery series, calculate aggregate mixing deviations, update mastery, expose
player APIs, or schedule drills. No production composition creates this evidence
yet; authoritative activation and downstream learning remain later checkpoints
under issues #416, #418, and #420.
