# PokerStars P1b Return-Status Source Labels

Status: source-authored P1b development labels under #409. This packet records
one observed historical status line and the complete surrounding detected state
before any parser extension. It is not a passing assessment case,
representative-corpus evidence, current-client assertion, network-reconnect
claim, player-selected-origin claim, or external poker-expert certification.

Date: 2026-09-09. Baseline: `63cec315ffa06ac1c54130d0c2d5536080d6c3dd`.

## Evidence, custody, and sanitation

The source is lines 302–351 of
[`wizardwerdna/pokerstats` `spec/file_many_hands.txt`](https://github.com/wizardwerdna/pokerstats/blob/315a4db29630c586fb080d084fa17dcad9494a84/spec/file_many_hands.txt#L302-L351),
pinned to `315a4db29630c586fb080d084fa17dcad9494a84`. The original full file is
17,391 bytes with SHA-256
`d242a58da28908a409c795afd8c1634a958541eb953cf4b0808d3eb46a37e36c`; its Git
blob is `a56c722a13aee935eb1700073c10dfda91da3ae1`. The 50 selected original
lines are 1,563 bytes with SHA-256
`8bda1b9b15c63b9b0f21eb2c318f55efe96c46b222392d451cef6d0b322e2511`.

The upstream [MIT license](https://github.com/wizardwerdna/pokerstats/blob/315a4db29630c586fb080d084fa17dcad9494a84/LICENSE)
has SHA-256
`e1b18163db18a3b5f81c427d4013da49c744a0bacd5f06e859cf650b261bf84b` and is
already retained at
[`LICENSE.wizardwerdna-pokerstats-MIT.txt`](../../apps/backend/tests/fixtures/pokerstars/public-format/LICENSE.wizardwerdna-pokerstats-MIT.txt).
The sanitized 50-line, 1,506-byte derivative is
[`wizardwerdna-pokerstats-return-status.txt`](../../apps/backend/tests/fixtures/pokerstars/public-format/wizardwerdna-pokerstats-return-status.txt),
SHA-256 `b1e4f6ef89fbe9125b7a4efcdfb9363fd539a310379f87d6a571779e050523fa`.
It maps player, hand, and table identifiers one-to-one to invented values and
normalizes trailing whitespace only. Header family, timestamp/dollar notation,
eight declared seats, cards, amounts, event order, and line numbers remain.

The original selected bytes contain trailing spaces on seat/action/summary
lines. At current `main`, those bytes first fail with `missing_seats`; applying
only the explicit trailing-whitespace normalization above exposes the
`unsupported_line` at sanitized line 22. Neither observation is a successful
parse or evidence to silently normalize unrelated inputs.

Export channel, PokerStars client/build, locale provenance, and current-client
applicability are unknown. These labels were authored from the pinned source,
the existing dealt-in position calculator, and independently checked amount
arithmetic, not from changed parser output. The separate legacy timeout packet
already establishes the immediate 2008 timeout-to-fold binding; this source
does not widen that source family.

## Current parser boundary

The sanitized fixture has the already reviewed two-digit-hour legacy cash
header, an immediate `has timed out` → same-actor fold pair, and immediate
`is sitting out` line. The current adapter accepts those existing pieces but
returns one `unsupported_line` diagnostic at line 22 for:

```text
Player07 has returned
```

It returns no candidate. That checksum-guarded rejection is required until a
separate parser PR follows independent review of this packet. Do not remove the
line, infer a network reconnection, turn the player back into a new seat,
change participation, or infer a player-selected/preselected action to obtain
a parse.

The line is observed source text only. It does not establish its transport
meaning, a causal scope for later actions, a reconnect event model, or a
general `<name> has returned` grammar. The same upstream collection also has a
return status for an undeclared name at original line 542; that occurrence is
not a labeled fixture and forbids generalizing this one dealt-in case.

## Complete source-authored target state

The state below is the independently authored complete expected detected state
if a later, separately reviewed mapping admits this exact status as inert raw
text. It is not emitted by the current parser and does not authorize that
mapping. Runtime import identifiers, source-file identity, import timestamp,
detector revision, and raw/detected hashes use the existing constructors and
deterministic test context.

- Identity: `site="pokerstars"`, `source_hand_id="900000000022"`, ordinal 1
  (line 1).
- Chronology: `played_at="2008-10-31T17:21:34-04:00"`,
  `source_timezone="ET"`, `source_session_id=None` (line 1). Retain the
  printed header as source evidence; the existing bounded cash ET rule gives
  the observed daylight offset on this date.
- Game: `variant="texas_holdem"`, `betting_limit="no_limit"`,
  `table_size=9`, button seat 8 (lines 1–2). Small blind 0.25, big blind 0.50,
  ante 0 with `ante_mode="unknown"`, and `straddle=None`.
- Economics: `kind="cash"`, `currency=None`, `rake=None` (line 1). Dollar
  symbols do not supply ISO currency or a cash-rake schedule. The stated rake
  is a result fact only.
- Hero: `hero_player_id="seat-8"`, `hero_cards=[9h, 6s]` (line 14).

### Seats and structural positions

All eight declared players are `participation="dealt_in"`. The absence of
seat 2 and the line-21 sit-out/line-22 return status do not alter this initial
ring. The values use the existing eight-handed position calculator, not a
second position model.

| Seat | Line | Player ID | Display name | Stack | Position | Button distance | Action index |
| ---- | ---- | --------- | ------------ | ----- | -------- | --------------- | ------------ |
| 1    | 3    | `seat-1`  | Player01     | 34.90 | BB       | 2               | 7            |
| 3    | 4    | `seat-3`  | Player03     | 99.10 | UTG      | 3               | 0            |
| 4    | 5    | `seat-4`  | Player04     | 44    | UTG+1    | 4               | 1            |
| 5    | 6    | `seat-5`  | Player05     | 45.60 | LJ       | 5               | 2            |
| 6    | 7    | `seat-6`  | Player06     | 18.80 | HJ       | 6               | 3            |
| 7    | 8    | `seat-7`  | Player07     | 31.95 | CO       | 7               | 4            |
| 8    | 9    | `seat-8`  | Player08     | 59.30 | BTN      | 0               | 5            |
| 9    | 10   | `seat-9`  | Player09     | 50.25 | SB       | 1               | 6            |

### Ordered actions and origins

`amount` is the incremental contribution or returned amount, and
`total_committed` is the actor's current-street commitment after the action.
Street commitments reset at each street marker. Every action has its own line
as action evidence.

Forced blind posts and the uncalled return are `forced_system` /
`explicit_marker`, confidence `1`, with their own action/origin evidence and
no semantics revision or automatic reason. The 16 unmarked ordinary actions
are `unknown` / `unresolved`, with no confidence/revision/reason; missing
markers, the hero identity, source status lines, and clean reconciliation do
not make them player-selected.

Only preflop sequence 6 is `client_automatic` / `explicit_marker`, confidence
`1`, `semantics_revision="pokerstars-cash-2008-timeout-v1"`, and
`automatic_reason="timeout"`. Its origin evidence is exactly marker line 19
and action line 20; its action evidence is line 20. The existing marker rule
binds one immediate same-actor fold and then consumes the marker. Line 21 is
an already reviewed inert sit-out source line. Line 22 is separately observed
raw status text, not automatic-action evidence.

| Street  | Seq. | Line | Actor    | Action           | Amount | Total committed | Expected origin          |
| ------- | ---- | ---- | -------- | ---------------- | ------ | --------------- | ------------------------ |
| preflop | 0    | 11   | `seat-9` | post_small_blind | 0.25   | 0.25            | forced_system            |
| preflop | 1    | 12   | `seat-1` | post_big_blind   | 0.50   | 0.50            | forced_system            |
| preflop | 2    | 15   | `seat-3` | call             | 0.50   | 0.50            | unknown                  |
| preflop | 3    | 16   | `seat-4` | fold             | None   | 0               | unknown                  |
| preflop | 4    | 17   | `seat-5` | fold             | None   | 0               | unknown                  |
| preflop | 5    | 18   | `seat-6` | call             | 0.50   | 0.50            | unknown                  |
| preflop | 6    | 20   | `seat-7` | fold             | None   | 0               | client_automatic timeout |
| preflop | 7    | 23   | `seat-8` | fold             | None   | 0               | unknown                  |
| preflop | 8    | 24   | `seat-9` | fold             | None   | 0.25            | unknown                  |
| preflop | 9    | 25   | `seat-1` | check            | None   | 0.50            | unknown                  |
| flop    | 0    | 27   | `seat-1` | check            | None   | 0               | unknown                  |
| flop    | 1    | 28   | `seat-3` | check            | None   | 0               | unknown                  |
| flop    | 2    | 29   | `seat-6` | check            | None   | 0               | unknown                  |
| turn    | 0    | 31   | `seat-1` | check            | None   | 0               | unknown                  |
| turn    | 1    | 32   | `seat-3` | check            | None   | 0               | unknown                  |
| turn    | 2    | 33   | `seat-6` | check            | None   | 0               | unknown                  |
| river   | 0    | 35   | `seat-1` | bet              | 1      | 1               | unknown                  |
| river   | 1    | 36   | `seat-3` | fold             | None   | 0               | unknown                  |
| river   | 2    | 37   | `seat-6` | fold             | None   | 0               | unknown                  |
| river   | 3    | 38   | `seat-1` | uncalled_return  | 1      | 0               | forced_system            |

### Streets, results, and arithmetic

Boards are preflop `[]`, flop `[Ac, 2h, Qd]` (26), turn
`[Ac, 2h, Qd, 6h]` (30), and river `[Ac, 2h, Qd, 6h, 7c]` (34). The summary
board at line 42 must agree.

- `results.stated_pot`: gross 1.75, rake 0.05, net 1.70, and
  `gross_pots=[]` (line 41).
- `results.showdown=[]`. No shown cards, rank, winner proof, or player-result
  vector is inferred.
- The only award is `seat-1` collecting 1.70 from `pot` (line 39), with no
  `pot_index`.
- Summary rows 43–50 must agree with actor, structural-position, fold-street,
  and collection facts but add no actions or player-result entries.

Independent contribution arithmetic is seat 1 = 0.50, seat 3 = 0.50, seat 6
= 0.50, seat 9 = 0.25, and zero for every other dealt-in seat. The line-38
uncalled return removes the river bet. Gross 1.75 and net 1.70 reconcile to
zero discrepancy under the existing amount-only result boundary. This does not
infer a winner, a voluntary action, an approved state, or a decision point.

Expected warning, in exact order:

1. `Action origin is unresolved for 16 player decision(s); review is required.`

## Unsupported meaning and review gate

This packet does not establish a network reconnection, reconnection duration,
re-entered/dealt-in participation, a new player/seat, preselection, ordinary
action voluntariness, or player-selected absence semantics. It does not add a
`reconnect` corpus tag; no such current `CorpusTag` exists. Parser output must
not emit `user_confirmed`.

An independent review must compare this packet with the pinned original bytes,
reconstruct the eight-seat ring, 20 actions, timeout binding, raw status lines,
boards, summary and 1.75 / 0.05 / 1.70 arithmetic, and verify the current
normalized-fixture rejection. Only then may a separate focused parser PR decide
whether an exact inert raw-status mapping is safe. No schema, API, persistence,
approval, extraction, backup, corpus-gate, reconnect, or player-selected
behavior is authorized by these labels.
