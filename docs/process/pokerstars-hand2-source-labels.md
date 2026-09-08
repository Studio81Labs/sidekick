# PokerStars HAND2 Source Labels

Status: architecture-owned source mapping for P1a under #409; implementation
pending. This is not a passing parser report, a representative-corpus case, or
an external poker-expert certification.

Date: 2026-09-08. Baseline: `3682328da0a9a534b43a192d21739775904baf76`.
Decision: [ADR 0078](../decisions/0078-preserve-unresolved-historical-source-time.md).

## Evidence and independent preparation

Source: the sanitized [HAND2 fixture](../../apps/backend/tests/fixtures/pokerstars/public-format/pokerregion-tournament-hand2.txt)
from PR #497, with SHA-256
`844d23d2e5085e02082a85f873ba9cd5637ed300545846877c520a8b444a11e4`.
It contains 57 lines. Attribution, MIT license and pinned upstream revision are
in the [public specimen inventory](v2-phase-0-public-specimen-inventory.md).
Line numbers below refer to these exact sanitized bytes, not the upstream file.

The architecture agent authored this mapping from source text and explicit chip
arithmetic. A separate read-only source investigator (`hand2_source_audit`,
GPT-6 Astra/high) independently derived the ledger, positions, pot split and
uncertainties without reading adapter output or generated expectations. The
architecture agent verified the consequential findings against the source and
current contracts, including an independent integer-arithmetic check of total
contributions and chip conservation. This is agent-assisted independent
preparation of a development regression; no human or corpus-owner sign-off is
claimed. The implementation must not generate its expected labels by running
the parser being tested.

A follow-up independent document/source review found no mismatches in the
specified mapping. The architecture agent then manually constructed this state
in a temporary read-only validation script against the existing baseline
models: hand/detection validation and JSON round-trip passed, including null
chronology and ancillary result evidence. The existing pot oracle agreed with
the already-authored main 4740, side 21570 and zero discrepancy. No adapter was
run to obtain these labels, and this does not claim parser or integration tests
passed. The implementation must retain the equivalent regressions in its PR.

## Hand and economic fields

All chip amounts below are exact Decimal-compatible values in absolute
tournament chips. Entry amounts are separately denominated in USD.

- Identity: `site="pokerstars"`, `source_hand_id="900000000010"` (line 1).
- Chronology: `played_at=None`, `source_timezone=None`, `source_session_id=None`.
  Preserve line 1's exact `2013/10/04 23:22:20 CET` and bracketed
  `2013/10/04 17:22:20 ET` in raw/header evidence. Use the existing raw-source
  identity for `source_file_id`, hand ordinal 1, and the test's supplied import
  context/provenance; import time is not play time. Do not alter the fixture to
  substitute UTC or remove a zone.
- Game: `variant="texas_holdem"`, `betting_limit="no_limit"`, `table_size=9`;
  button seat 2 (lines 1–2).
- Blinds: small 400, big 800, ante 75, `ante_mode="per_player"`,
  `straddle=None` (lines 1, 12–23). All nine ante posts are explicit.
- Economics: `kind="tournament"`, `tournament_id="800000000"`,
  `entry_buy_in="3.19"`, `entry_fee="0.31"`, `currency="USD"`,
  `blind_level="XI"` (line 1). `tournament_type`, `stage`, `paid_places`,
  `players_remaining` and `bounty_format` remain `None`; `payouts=[]`,
  `bounties=[]`, `icm_inputs_complete=False`.
- `remaining_stacks`: retain only the nine known on-table hand-start stacks
  from lines 3–11, keyed by the existing `seat-N` player IDs in seat order.
  These are a partial field snapshot, not proof that only nine players remain;
  do not fill off-table entries or ICM completeness. Each matches the seat's
  `starting_stack` exactly.
- Hero: `hero_player_id="seat-2"`, `hero_cards=[Jd, Js]` (line 24).

## Seats and structural positions

Each seat has `player_id="seat-N"`, `display_name="Player0N"`,
`participation="dealt_in"`, and `dealt_in_player_count=9`. Seat evidence is the
listed line; position evidence also binds the button/dealt-in ring. Positions
below follow the existing structural model; do not create a second calculator.

| Seat | Source line | Starting stack | Position | Button distance | Action index |
| ---- | ----------- | -------------- | -------- | --------------- | ------------ |
| 1    | 3           | 12910          | CO       | 8               | 5            |
| 2    | 4           | 11815          | BTN      | 0               | 6            |
| 3    | 5           | 7395           | SB       | 1               | 7            |
| 4    | 6           | 7765           | BB       | 2               | 8            |
| 5    | 7           | 10080          | UTG      | 3               | 0            |
| 6    | 8           | 1030           | UTG+1    | 4               | 1            |
| 7    | 9           | 13175          | UTG+2    | 5               | 2            |
| 8    | 10          | 2415           | LJ       | 6               | 3            |
| 9    | 11          | 13070          | HJ       | 7               | 4            |

## Ordered actions and origin

There are 21 preflop actions, numbered 0–20. The action and its origin each
retain their exact source line. Forced posts/return have
`kind="forced_system"`, `basis="explicit_marker"`, confidence 1; ordinary
folds/raises/call have `kind="unknown"`, `basis="unresolved"`, confidence
`None`. All have `semantics_revision=None`, `automatic_reason=None`. All-in
markers establish stack commitment, not player-selected origin.

`amount` is the incremental chip amount, or the returned amount for a return.
`total_committed` is the actor's street commitment after the action, including
the ante. The source's raise increment is not the action's incremental amount.

| Sequence | Line  | Actor seat       | Action           | Amount  | Total committed | All-in |
| -------- | ----- | ---------------- | ---------------- | ------- | --------------- | ------ |
| 0–8      | 12–20 | 1–9 respectively | post_ante        | 75 each | 75 each         | false  |
| 9        | 21    | 3                | post_small_blind | 400     | 475             | false  |
| 10       | 22    | 4                | post_big_blind   | 800     | 875             | false  |
| 11       | 25    | 5                | fold             | None    | 75              | false  |
| 12       | 26    | 6                | raise            | 955     | 1030            | true   |
| 13       | 27    | 7                | fold             | None    | 75              | false  |
| 14       | 28    | 8                | fold             | None    | 75              | false  |
| 15       | 29    | 9                | raise            | 12995   | 13070           | true   |
| 16       | 30    | 1                | fold             | None    | 75              | false  |
| 17       | 31    | 2                | call             | 11740   | 11815           | true   |
| 18       | 32    | 3                | fold             | None    | 475             | false  |
| 19       | 33    | 4                | fold             | None    | 875             | false  |
| 20       | 34    | 9                | uncalled_return  | 1255    | 11815           | false  |

Preflop board is empty. Subsequent streets have empty action lists, with
cumulative boards: flop `[3c,6s,9d]` (35), turn `[3c,6s,9d,8d]` (36), river
`[3c,6s,9d,8d,Ks]` (37). Summary board line 48 must match that river board.

## Results, summary and placements

- `stated_pot`: gross 26310, rake 0, net 26310, `gross_pots=[4740,21570]` in
  main/side order. Source evidence is line 47, independent of the action-ledger
  calculation. Component sum must equal gross. Zero hand rake does not prove a
  tournament entry-fee schedule or any ICM input.
- `showdown`, in source order: seat 9 `[Kd,Ac]` shown (39); seat 2 `[Jd,Js]`
  shown (40); seat 6 `[9c,Qd]` shown (42). Preserve cards and evidence; summary
  repetition does not add duplicate showdown entries.
- `awards`, in source order: seat 9 receives 21570 with `pot_index=1` (41), then
  4740 with `pot_index=0` (43). A return is not an award. Raw line references
  preserve interleaving of shows and awards despite their separate model lists.
- `results.players=[]`, matching the existing adapter boundary: there is no
  explicit net-result vector in the text. The arithmetic below is an independent
  oracle, not permission to introduce a new result/ending-stack representation.
- Lines 49/53/55/56 repeat preflop folds for seats 1/5/7/8; line 51 repeats the
  SB fold for seat 3, line 52 the BB fold for seat 4. Their seat identities,
  position tags and fold street must match the hand. “Didn't bet” does not erase
  antes and creates no additional action.
- Lines 50/54 repeat shown losing cards for seats 2/6; line 57 repeats seat 9's
  cards and total collected 26310. Match the actual shown cards and collections,
  including zero awards for a stated loser. Hand-rank prose is retained source
  description, not a new canonical field or action-origin signal.
- Lines 44/45 state seat 2 finished 80th and seat 6 finished 81st. Retain them
  under ADR 0078's ancillary-source rule; no placement field is added. Validate
  declared actors, positive ordinals, full wording and no duplicate actor
  statement. Do not infer field size 81, paid places, payouts, stage or a player
  action. Keep these lines in `/results` evidence with confidence `None` and the
  explicit unmodeled-placement warning.

## Independent chip and decision-context oracle

Antes total 675; after blinds the pot is 1875. The subsequent chip additions
produce `1875 + 955 + 12995 + 11740 - 1255 = 26310`.
Net contributions by seat 1–9 are
`[75,11815,475,875,75,1030,75,75,11815]`.

The main pot is `3×1030 + 475 + 875 + 4×75 = 4740`, eligible to seats 2/6/9.
The side pot is `2×(11815-1030) = 21570`, eligible to seats 2/9. All nine
contribute to the main pot; only seats 2/9 contribute to the side. No third pot
is left after the 1255 return. These labels predict zero reconciliation
discrepancy and the existing `clean` amount disposition; they do not claim an
executed production parser pass or an extractable approved decision.

For arithmetic auditing only, ending stacks are
`[12835,0,6920,6890,10005,0,13100,2340,27565]`; both starting and ending chip
totals are 79655. Seat 9's net is `26310-11815=14495`; others lose their net
contributions. Do not persist calculated values as source-supplied facts.

Immediately before hero action 17: pot 15825; hero stack 11740; ante-inclusive
street/hand commitment 75, live commitment 0; outstanding live wager 12995;
last full raise increment 12040. The first raise's 155 increment is a short
all-in relative to the 800 big blind. Hero's stack cannot cover the full wager:
the actual call is 11740 and no raise is available. This is one observed hero
action, still origin-unknown. Future blind folds, return, runout and results are
not decision-time observations. Incomplete economics/origin and lack of
approval continue to block consumable learning evidence.

## Detection evidence and exact warnings

Use existing exact-field evidence for directly observed identities, game facts,
seats, header economics and derived structural facts, with the source lines
above. Header economic pointers include ADR 0077's three new fields. Attach
partial `remaining_stacks` entries to their matching seat lines. Preserve
existing action, board, showdown and award evidence; the independent stated-pot
pointer must bind line 47, not the awards alone.

For the two chronology pointers use line 1, confidence 0 and the second warning
below. For `/results` ancillary evidence use lines 44–45, confidence `None`
and the third warning. Detection warnings, in exact order:

1. `Action origin is unresolved for 9 player decision(s); review is required.`
2. `Source time is unresolved: historical dual-zone timestamp semantics are unverified.`
3. `Tournament finish positions are retained as source evidence only; field size and payouts remain unknown.`

Runtime-supplied identifiers/import timestamps, detector revisions and hashes
follow existing constructors. Freeze deterministic test inputs; do not use
adapter-generated output to author semantic expectations. No absent economic
field receives invented exact confidence or evidence. These labels are complete
at the existing domain's level of certainty, including nulls and retained-only
statements. Public development coverage remains separate from the empirical
1,000-hand, origin/chronology and solved-reference gates.
