# PokerStars P1b Legacy Game Timeout Source Labels

Status: source-authored P1b development labels under #409. This is not a
passing assessment case, representative-corpus evidence, current-client
assertion, or external poker-expert certification. The separate independent
development-fixture review completed on PR #510 before this bounded parser work.

Date: 2026-09-09. Baseline: `094bda29054c2309d16b8c7445daeffb727921ac`.

## Evidence, custody, and authoring boundary

The source is lines 194–246 of
[`wizardwerdna/pokerstats` `spec/file_many_hands.txt`](https://github.com/wizardwerdna/pokerstats/blob/315a4db29630c586fb080d084fa17dcad9494a84/spec/file_many_hands.txt#L194-L246),
pinned to `315a4db29630c586fb080d084fa17dcad9494a84`. The original full file is
17,391 bytes with SHA-256
`d242a58da28908a409c795afd8c1634a958541eb953cf4b0808d3eb46a37e36c`; its Git
blob is `a56c722a13aee935eb1700073c10dfda91da3ae1`. The selected original hand
is 1,708 bytes with SHA-256
`84324369fc66a424f7aa105b7661995bf7ceac0c4161e84c164cdfa00eca0329`.

The upstream [MIT license](https://github.com/wizardwerdna/pokerstats/blob/315a4db29630c586fb080d084fa17dcad9494a84/LICENSE)
has SHA-256
`e1b18163db18a3b5f81c427d4013da49c744a0bacd5f06e859cf650b261bf84b` and is
retained at
[`LICENSE.wizardwerdna-pokerstats-MIT.txt`](../../apps/backend/tests/fixtures/pokerstars/public-format/LICENSE.wizardwerdna-pokerstats-MIT.txt).
The sanitized 53-line, 1,653-byte derivative is
[`wizardwerdna-pokerstats-timeout-fold.txt`](../../apps/backend/tests/fixtures/pokerstars/public-format/wizardwerdna-pokerstats-timeout-fold.txt),
SHA-256 `51b9add6944ebef6f6205076a29aad2f12c09aec536d7298ed93e55f607b338a`.
It replaces player names and hand/table identifiers with invented values and
normalizes trailing whitespace only. Header family, timestamp/dollar notation,
stacks, cards, amounts, action/summary order, and timeout/sit-out text remain.

Export channel, PokerStars client/build, locale provenance, and current-client
applicability are unknown. The labels below were authored from the pinned
source, source syntax, and auditable cash arithmetic before this branch changes
parser code. They are not copied from changed-parser output. The independent
Codex PR review on #510 completed with no findings or review threads at
`a5eb3a2f2107fbb19d98c8b1fc3d1f54fd85f8fd`. No external or human source
review is claimed.

PokerStars' [cash time-bank help](https://www.pokerstars.com/help/articles/ring-time-ma/220419/)
states that time-bank expiration folds a hand and distinguishes reconnect time
for disconnected players. That establishes general automatic-timeout behavior;
this source establishes only the observed historical `has timed out` marker and
line order. Neither establishes absence/manual-action semantics, preselection,
reconnect ordering, or current-client grammar.

## Current parser boundary

The reviewed parser maps this one legacy `PokerStars Game #` source family. It
must not rewrite the fixture, infer a hero, turn `$` into `USD`, or generalize
the family beyond the labels below. The earlier HHSmithy fixture is retained as
an `unsupported_header` rejection: the adapter detects its legacy hand boundary
but its one-digit-hour/explicit-ISO header does not match this reviewed grammar.

## Expected detected state

All references are to exact sanitized lines. Runtime import identifiers,
source-file identity, import timestamp, detector revision, and raw/detected
hashes use the existing constructors and test context.

- Identity: `site="pokerstars"`, `source_hand_id="900000000021"`, ordinal 1
  (line 1).
- Chronology: `played_at="2008-10-31T17:17:57-04:00"`,
  `source_timezone="ET"`, `source_session_id=None` (line 1). The existing cash
  ET chronology rule yields the observed eastern daylight offset on this date;
  retain the printed timestamp/timezone as evidence.
- Game: `variant="texas_holdem"`, `betting_limit="no_limit"`, `table_size=9`,
  button seat 6 (lines 1–2). Small blind 0.25, big blind 0.50, no ante and no
  straddle (lines 1, 12–13).
- Economics: `kind="cash"`, `currency=None`, `rake=None` (line 1). Dollar
  symbols without an ISO code or independently reviewable jurisdiction do not
  establish USD; retain raw notation without manufacturing currency evidence.
- Hero: `hero_player_id="seat-8"`, `hero_cards=[7d, Jd]` (line 15).

Each seat is `participation="dealt_in"`. The line-20 sit-out notice follows
Player02's fold; retain it in raw text but do not remove Player02 from the
dealt-in ring or use it as automatic-action evidence.

| Seat | Line | Display name | Stack  | Position | Button distance | Action index |
| ---- | ---- | ------------ | ------ | -------- | --------------- | ------------ |
| 1    | 3    | Player01     | 34.90  | UTG+1    | 4               | 1            |
| 2    | 4    | Player02     | 50     | UTG+2    | 5               | 2            |
| 3    | 5    | Player03     | 100.10 | LJ       | 6               | 3            |
| 4    | 6    | Player04     | 44     | HJ       | 7               | 4            |
| 5    | 7    | Player05     | 52.10  | CO       | 8               | 5            |
| 6    | 8    | Player06     | 20.30  | BTN      | 0               | 6            |
| 7    | 9    | Player07     | 32.40  | SB       | 1               | 7            |
| 8    | 10   | Player08     | 50.90  | BB       | 2               | 8            |
| 9    | 11   | Player09     | 50.75  | UTG      | 3               | 0            |

`dealt_in_player_count=9`; structural labels bind the button and complete
dealt-in ring using the existing position calculator.

## Ordered actions and origins

`amount` is the incremental contribution or returned amount;
`total_committed` is the actor's current-street commitment after the action.
Street commitments reset at each street marker. Thus line 25 contributes 0.75
after the blind; the line-30 and line-38 raises contribute 3 and 16.50.

Forced posts and uncalled return have `forced_system` / `explicit_marker`,
confidence `1`, own-line action/origin evidence, and no semantics revision or
automatic reason. Every unmarked non-forced action has `unknown` / `unresolved`,
no confidence/revision/reason, and own-line action/origin evidence.

Only action 4 has the proposed qualified origin `client_automatic` /
`explicit_marker`, confidence `1`,
`semantics_revision="pokerstars-cash-2008-timeout-v1"`, and
`automatic_reason="timeout"`. Its action evidence is line 19; origin evidence
is the actor-specific line-18 marker plus line 19. It binds one immediately
following same-actor action on that street, then is consumed. A source-event,
action by another actor, street/hand/file boundary, duplicate/stale marker, or
malformed binding ends scope. Line 20 is not a marker.

| Seq. | Street  | Line | Actor  | Action           | Amount | Total committed | Origin                   |
| ---- | ------- | ---- | ------ | ---------------- | ------ | --------------- | ------------------------ |
| 0    | preflop | 12   | seat-7 | post_small_blind | 0.25   | 0.25            | forced_system            |
| 1    | preflop | 13   | seat-8 | post_big_blind   | 0.50   | 0.50            | forced_system            |
| 2    | preflop | 16   | seat-9 | fold             | None   | 0               | unknown                  |
| 3    | preflop | 17   | seat-1 | fold             | None   | 0               | unknown                  |
| 4    | preflop | 19   | seat-2 | fold             | None   | 0               | client_automatic timeout |
| 5    | preflop | 21   | seat-3 | call             | 0.50   | 0.50            | unknown                  |
| 6    | preflop | 22   | seat-4 | fold             | None   | 0               | unknown                  |
| 7    | preflop | 23   | seat-5 | fold             | None   | 0               | unknown                  |
| 8    | preflop | 24   | seat-6 | fold             | None   | 0               | unknown                  |
| 9    | preflop | 25   | seat-7 | raise            | 0.75   | 1               | unknown                  |
| 10   | preflop | 26   | seat-8 | call             | 0.50   | 1               | unknown                  |
| 11   | preflop | 27   | seat-3 | call             | 0.50   | 1               | unknown                  |
| 12   | flop    | 29   | seat-7 | bet              | 1      | 1               | unknown                  |
| 13   | flop    | 30   | seat-8 | raise            | 3      | 3               | unknown                  |
| 14   | flop    | 31   | seat-3 | fold             | None   | 0               | unknown                  |
| 15   | flop    | 32   | seat-7 | call             | 2      | 3               | unknown                  |
| 16   | turn    | 34   | seat-7 | check            | None   | 0               | unknown                  |
| 17   | turn    | 35   | seat-8 | check            | None   | 0               | unknown                  |
| 18   | river   | 37   | seat-7 | bet              | 4.50   | 4.50            | unknown                  |
| 19   | river   | 38   | seat-8 | raise            | 16.50  | 16.50           | unknown                  |
| 20   | river   | 39   | seat-7 | fold             | None   | 4.50            | unknown                  |
| 21   | river   | 40   | seat-8 | uncalled_return  | 12     | 4.50            | forced_system            |

The parser never emits `user_confirmed`; ordinary actions do not become
player-selected from their legality, missing marker, hero identity, sit-out
status, later board/result evidence, or clean pot arithmetic.

## Streets, results, and arithmetic

Boards are preflop `[]`, flop `[Td, 3h, 7c]` (28), turn
`[Td, 3h, 7c, 6c]` (33), river `[Td, 3h, 7c, 6c, 7s]` (36); summary board line
44 agrees. There is no showdown. Source-stated pot is gross 18, rake 0.85,
net 17.15 and `gross_pots=[]` (43). The only award is seat-8 collecting 17.15
from `pot` (41); no winner, rank, or result vector is inferred. Summary rows
45–53 must agree with actors, positions, fold streets, and award, but add no
actions.

Independent action arithmetic gives contributions seat-7 8.50, seat-8 8.50,
and seat-3 1. The 12 river return reduces seat-8's 16.50 commitment. Gross 18
and net 17.15 reconcile to zero discrepancy under the existing amount-only
result boundary. This neither infers unshown cards/winner nor voluntary origin
or an approved/extractable decision.

## Evidence, warning, and required review

Use exact-field evidence for observed header, table, seats, hero/cards,
actions, boards, stated pot, award, and summary comparisons. Action 4 adds only
line 18 to its line-19 origin evidence. Retain line 20 in raw source; the
current detected-state contract has no typed source-event field.

Expected warning, in exact order:

1. `Action origin is unresolved for 18 player decision(s); review is required.`

The completed review supports only this legacy header, currency-null dollar
notation, immediate same-actor timeout-to-fold binding, and inert source-event
handling. Regressions prove that unmarked actions remain unknown, timeout does
not cross actor, street, hand, or file, and a bare sit-out is not a marker. This
packet still does not establish disconnect, reconnect, combined-cause,
preselection, or player-selected semantics. Any wider scope, ISO inference,
source-event model, origin-contract change, or absence semantics requires the
Epic escalation path.
