# ADR 0078: Preserve Unresolved Historical Source Time

Status: accepted; parser implementation pending under issue #409

Date: 2026-09-08

Resolves the source-label checkpoint in
[#409 comment 5585636988](https://github.com/Studio81Labs/sidekick/issues/409#issuecomment-5585636988).
ADR 0077's compatibility prerequisite is implemented in PR #500. This decision
adds no model fields, migrations, production code or implementation PR.

## Context

The pinned public HAND2 specimen prints both `2013/10/04 23:22:20 CET` and
`2013/10/04 17:22:20 ET`. A six-hour wall-clock difference does not distinguish
fixed CET/EST offsets from seasonal Central-European/Eastern offsets: those
interpretations can agree internally yet differ by an hour in UTC. The sample
does not establish which historical client semantics apply. The current cash
adapter's DST-derived ET conversion is an existing behavior, not independent
proof for this new dual-zone format.

PokerStars' current [time-zone help](https://www.pokerstars.com/help/articles/time-zone-setting/32057/)
identifies ET as the default and lists selectable zones, but does not specify
this 2013 export's offset or precedence. On 2026-09-08 the indexed article was
available in search; direct retrieval redirected to a page-not-found response.
This is a research lead, not a certified historical format contract.

`SourceChronology` already permits `played_at=None` and `source_timezone=None`;
it deliberately rejects a non-null timezone without a timestamp. Raw hand text
and `DetectedFieldEvidence` retain source lines, warnings and confidence. The
private corpus expectation model also permits the two nulls. Product invariants
require uncertainty to remain visible, rather than requiring every source fact
to be converted into an unjustifiably precise canonical value.

## Decision

### Represent uncertainty without discarding the hand

The evidenced historical tournament header form with leading `CET` and
bracketed `ET` is eligible for bounded parsing with **unresolved normalized
chronology**. Set both `played_at` and `source_timezone` to `None` in raw and
detected chronology. Preserve `source_file_id`, hand ordinal and ordinary import
provenance; leave unproved session identity unknown. Preserve both complete
printed timestamps and zone labels verbatim in retained raw text and header-line
source evidence. Do not substitute import time, strip one timestamp, choose a
zone based on token position, or manufacture an offset from their difference.

Attach header evidence to `/chronology/played_at` and
`/chronology/source_timezone` with confidence zero and this field warning:

> Source time is unresolved: historical dual-zone timestamp semantics are unverified.

Include the same warning in detection warnings. Confidence zero describes the
unresolved normalized value, not doubt that the raw line contains two strings.
Local audit/review continues using existing sanitized evidence pointers and
warning projections; private excerpts remain governed by the current boundary.

This rule is limited to the explicitly recognized historical tournament syntax.
Validate both calendar/wall-clock strings and the complete header structure
before applying it. Invalid dates/times and malformed/truncated/unknown header
forms retain per-hand rejection; do not convert arbitrary parser errors to
unknown time. Existing cash single-zone parsing, supported UTC/GMT/ET behavior,
and rejection of ambiguous/nonexistent ET times remain unchanged.

Unknown chronology is a valid label and a reviewable state. It establishes no
recency/session/proof eligibility, chronology coverage or source-format accuracy
claim. Existing economics, origin, approval and downstream readiness gates still
apply. A parsed hand with matching pot totals can be `clean` in the existing
amount-reconciliation sense while having unresolved chronology and origins;
that disposition is not an assertion of complete source correctness.

Later evidence can justify a separately reviewed format revision. Reimport then
uses ordinary changed-meaning conflicts and explicit approval. Never revise
retained raw/detected/canonical chronology, repair old hashes, or auto-enrich an
approved hand. Keep hand schemas, workspace v5, backup v3 and lifecycle locks
unchanged. A new structured wall-time/candidate-zone model is not required for
this bounded work; it would need a separate evidenced architectural decision.

### Complete the specimen's result labels

The [HAND2 source-label sheet](../process/pokerstars-hand2-source-labels.md)
defines the hand, source evidence, all ordered actions, positions, unknowns,
showdowns, awards and summary comparisons independently of adapter output.
Implement against that sheet rather than generating a golden state from the
parser. It is a public format regression, not the independently qualified
representative corpus or external poker-review evidence.

The main/side summary supplies gross pots in main-first order. Preserve award
source order separately; the side award appears before the main award. Validate
summary cards, seat/position tags and collections against the corresponding
observed hand events, without synthesizing duplicate actions or awards. Keep
summary total/component evidence independent from reconstructed contributions.

The two `finished the tournament in ... place` lines are **ancillary tournament
result statements**. Validate their complete recognized wording, declared actor,
positive ordinal and absence of duplicate actor statements. Retain the lines
as raw/source evidence; do not put finish places into `PlayerResult`, payouts,
stage, `players_remaining`, starting stacks or action history. In particular,
80th/81st place cannot prove the decision-time field size or paid places.

Expose this retained but unmodeled information as `/results` field evidence,
with confidence `None`, the two line references, and the following warning in
both that field and detection warnings:

> Tournament finish positions are retained as source evidence only; field size and payouts remain unknown.

Other result evidence remains at its specific showdown/award/stated-pot
pointers. No new canonical placement schema is approved. Unknown lines still
reject; this is not permission to ignore arbitrary tournament text. If a newly
observed line affects a pot, payout, bounty, stack or origin, stop the dependent
extension and determine its meaning before accepting it.

### Execution and validation

Maintain SERIAL execution, one implementation writer/merge-bound PR. After this
decision and the label sheet land, P1a may begin using the complete HAND2 mapping
with explicit uncertainty. Neither private files nor a timezone guess is a
prerequisite. P1b's source-origin evidence and the empirical P2/R0 gates remain
separate; this does not authorize inventing those labels.

P1a must verify the whole expected state, the two null chronology fields in raw
and detected records, both source strings, zero-confidence evidence, stable
warning order, existing metadata/lineage, and an unchanged raw fixture digest.
Include malformed-date/bracket and unknown-line cases, summary total/component,
card/position/collection contradictions, placement duplicate/actor errors,
mixed-file isolation, review/reimport/backup round-trip and existing cash/DST
regressions. Do not remove uncertain fields from corpus comparison or reclassify
public examples as empirical evidence. Run the relevant repository parser,
corpus, imported-hand and local import/hand suites; PWA tests/build if UI changes.

The implementation orchestrator may author tests and supported syntax from this
mapping and resolve ordinary implementation details. Escalate any requirement
to choose an unproved timestamp/offset, reinterpret source facts, discard
evidence, change domain/backup/API/security/lifecycle semantics, or weaken a gate.
The lack of an exact UTC label is not itself a new blocker after this explicit
unknown-time decision.

## Consequences

The hand remains fully reviewable at the existing level of source certainty.
The orchestrator can implement the evidenced tournament format without another
model migration or an invented timestamp. Exact historical time remains an
open evidence question, with no fabricated answer or human review sign-off.
Phase 1 remains NO-GO and the full Epic remains dependent on its external gates.
