# PokerStars P1b HHSmithy Cash Source Labels

Status: independently reviewed P1b source mapping under #409. The source-label
review completed without findings on merged PR #513; the reviewed adapter
extension maps the complete expected detected state and narrowly observed input
grammar below. This is not a passing assessment case, representative-corpus
evidence, a current-client assertion, or an external poker-expert certification.

Date: 2026-09-09. Baseline: `0b5837142dfb32bb10943f1a0ae132610cbc1889`.

## Evidence, custody, and authoring boundary

The source is
[`HHSmithy/PokerHandHistoryParser` `Limit1.txt`](https://github.com/HHSmithy/PokerHandHistoryParser/blob/91600818d95e23f154073735c1258e92c4f55f97/HandHistories.Parser.UnitTests/SampleHandHistories/PokerStars/CashGame/Limits/Limit1.txt),
pinned to `91600818d95e23f154073735c1258e92c4f55f97`. The original is 1,410
bytes with SHA-256
`9eb7e08c0bd57cd69ef5983102d813b56e138ad25d814d6881932fd4623e96cb`.
The upstream README's MIT license has SHA-256
`c9421183ce179d09f85510fefac722c76a01b0f92edb208b34b8237fce2d5a9c` and is
retained beside the sanitized derivative.

The repository's 45-line sanitized fixture is
[`hhsmithy-cash-limit1.txt`](../../apps/backend/tests/fixtures/pokerstars/public-format/hhsmithy-cash-limit1.txt),
1,378 bytes with SHA-256
`481c9ac5af9e20bc0fa6f55adf606d52733387993ef8aec2696193cadfde2ae0`.
It maps original player, observer, joiner, hand, and table identifiers
one-to-one to invented identifiers while retaining source syntax, cards,
amounts, timestamp text, event order, and line numbers. The original-byte
digest was rechecked against the pinned GitHub blob while preparing this
packet. Line references below are to the sanitized bytes.

Export channel, PokerStars client/build, locale provenance, and current-client
applicability are unknown. These labels were authored from the source text and
independent cash arithmetic, not from a changed adapter's output. The
[action-origin evidence packet](pokerstars-p1b-action-origin-evidence.md)
records the vendor context and candidate-origin scope that this full state
uses. It does not establish reconnect, preselection, or player-selected
absence semantics.

## Current parser boundary

The reviewed adapter accepts the exact sanitized bytes as one detected,
pending-review candidate under `pokerstars-text/v5`. It maps the source's
explicit `USD`, one-digit-hour `PokerStars Game #` header, unknown hero, five
qualified marker bindings, inert notifications, results, and source evidence.
Do not add a hero, rewrite the header, replace explicit `USD` with the older
unknown-currency dollar grammar, or derive the labels from parser output.

## Reviewed target grammar

This is a narrow source grammar, not a general `PokerStars Game #` family. The
reviewed adapter accepts only the following source form:

```text
PokerStars Game #<decimal>:  Hold'em No Limit ($<positive decimal>/$<positive decimal> USD) - <YYYY>/<MM>/<DD> <H>:<MM>:<SS> ET
```

The observed header has exactly two spaces after the colon, explicit `USD`, and
a one-digit hour (`3`). The qualified form keeps that one-digit-hour boundary;
it is not a second path for a two-digit hour, another currency token, omitted
ISO currency, another zone, another limit, or another header spelling. Header
date/time values must still be valid under the existing bounded cash ET time
rule, including its daylight-saving rejection boundary. The source labels
`USD` as supplied currency; the earlier 2008 dollar-only family remains
separate and has `currency=None`.

The source body being qualified has all of the following bounded features:

- a `9-max` table declaration with the button at seat 5 (line 2), followed by
  exactly the three initial seat declarations at lines 3–5;
- normal small-blind/big-blind posts, `HOLE CARDS`, calls, checks, one bet,
  one fold, and one call in the recorded order;
- no `Dealt to` line. This is valid for a detected cash state with an unknown
  hero, but it remains unavailable for decision extraction;
- three plain timeout-to-check candidates and two combined
  timeout/disconnect-to-check-or-fold candidates, each immediately bound to the
  same actor on the same street as specified below;
- observed `is disconnected` and `joins the table at seat #<n>` notifications
  retained only in existing raw text, plus the shown/mucked/collection and
  summary wording recorded below.

The observed notification grammar is inert. A joiner or observer does not
create a seat, change the three-player dealt-in ring, become a hero, create an
action, or carry a disconnect cause to a later action. The bare Player02
disconnect at line 24 is additional raw context only; the combined marker on
line 25 is self-contained. This packet does not qualify a reconnect marker,
an unbound disconnect, a duplicate/stale/cross-actor/cross-street/cross-hand
marker, or arbitrary ancillary event syntax. Those inputs must remain rejected
or unresolved according to a separately reviewed rule.

The ranked show and summary form is limited to this source description:
`two pair, Eights and Threes` on lines 37 and 44. It is retained source prose,
validated for repeat/card/collection consistency, not computed winner proof.
No hand evaluator, new result field, or generalized rank-description grammar
is authorized by this label.

## Expected detected state

Runtime import identifiers, source-file identity, import timestamp, detector
revision, and raw/detected hashes use the existing constructors and deterministic
test context. All other values below are emitted by the reviewed adapter for
this exact grammar.

- Identity: `site="pokerstars"`, `source_hand_id="900000000020"`, ordinal 1
  (line 1).
- Chronology: `played_at="2014-01-06T03:56:02-05:00"`,
  `source_timezone="ET"`, `source_session_id=None` (line 1). January is
  standard eastern time under the existing bounded cash rule; preserve the
  complete printed header as evidence.
- Game: `variant="texas_holdem"`, `betting_limit="no_limit"`,
  `table_size=9`, and button seat 5 (lines 1–2). Small blind is 0.05, big blind
  is 0.10, ante is 0 with `ante_mode="unknown"`, and `straddle=None`.
- Economics: `kind="cash"`, `currency="USD"`, `rake=None`. The stated hand
  rake is a result fact, not a cash-rake schedule; no jurisdiction, percentage,
  cap, drop, or session identity is supplied.
- Hero: `hero_player_id=None`, `hero_cards=[]`. There is no hero field evidence
  because the source supplies no dealt-to line. Do not manufacture confidence
  or evidence for either absence, infer a hero from the button or action order,
  or weaken the existing `incomplete_hand_state` extraction guard.

### Seats and structural positions

All three declared initial seats are `participation="dealt_in"` and form the
entire dealt-in ring. Later join notices do not add seats 3, 7, 8, or 9. The
position values come from the existing three-handed structural-position
calculator; they are not a second position model.

| Seat | Line | Player ID | Display name | Stack | Position | Button distance | Action index |
| ---- | ---- | --------- | ------------ | ----- | -------- | --------------- | ------------ |
| 2    | 3    | `seat-2`  | Player02     | 7.85  | SB       | 1               | 1            |
| 4    | 4    | `seat-4`  | Player04     | 8     | BB       | 2               | 2            |
| 5    | 5    | `seat-5`  | Player05     | 6.04  | BTN      | 0               | 0            |

### Ordered actions and origins

`amount` is the incremental contribution and `total_committed` is the actor's
commitment on that street after the action. Street commitments reset at each
street marker. Every action has its own source line as action evidence.

Forced blind posts have `forced_system` / `explicit_marker`, confidence `1`,
own-line origin evidence, and no semantics revision or automatic reason. The
eight unmarked ordinary actions have `unknown` / `unresolved`, no confidence,
semantics revision, or automatic reason, and own-line origin evidence. Missing
markers never imply a player-selected action.

The five candidate automatic rows are all `client_automatic` /
`explicit_marker`, confidence `1`, and
`semantics_revision="pokerstars-cash-2014-timeout-disconnect-v1"`. Their
origin evidence contains exactly the marker line followed by the action line;
the action evidence remains its action line. Plain markers use
`automatic_reason="timeout"`. Combined `while disconnected` markers use the
single, more-specific `automatic_reason="disconnect"`; do not emit two causes
or two automatic actions for one combined marker.

| Street  | Seq. | Line | Actor    | Action           | Amount | Total committed | Expected origin                     |
| ------- | ---- | ---- | -------- | ---------------- | ------ | --------------- | ----------------------------------- |
| preflop | 0    | 6    | `seat-2` | post_small_blind | 0.05   | 0.05            | forced_system                       |
| preflop | 1    | 7    | `seat-4` | post_big_blind   | 0.10   | 0.10            | forced_system                       |
| preflop | 2    | 9    | `seat-5` | call             | 0.10   | 0.10            | unknown                             |
| preflop | 3    | 10   | `seat-2` | call             | 0.05   | 0.10            | unknown                             |
| preflop | 4    | 15   | `seat-4` | check            | None   | 0.10            | client_automatic timeout (14–15)    |
| flop    | 0    | 17   | `seat-2` | check            | None   | 0               | unknown                             |
| flop    | 1    | 21   | `seat-4` | check            | None   | 0               | client_automatic timeout (20–21)    |
| flop    | 2    | 22   | `seat-5` | check            | None   | 0               | unknown                             |
| turn    | 0    | 26   | `seat-2` | check            | None   | 0               | client_automatic disconnect (25–26) |
| turn    | 1    | 28   | `seat-4` | check            | None   | 0               | client_automatic timeout (27–28)    |
| turn    | 2    | 29   | `seat-5` | bet              | 0.30   | 0.30            | unknown                             |
| turn    | 3    | 31   | `seat-2` | fold             | None   | 0               | client_automatic disconnect (30–31) |
| turn    | 4    | 32   | `seat-4` | call             | 0.30   | 0.30            | unknown                             |
| river   | 0    | 34   | `seat-4` | check            | None   | 0               | unknown                             |
| river   | 1    | 35   | `seat-5` | check            | None   | 0               | unknown                             |

Each candidate binds exactly one immediate same-actor ordinary action on the
current street and is then consumed. Another actionable actor, street boundary,
hand boundary, file boundary, malformed binding, duplicate, or conflicting
marker ends that scope. The raw observer/join/bare-disconnect lines do not
alter this rule. The combined marker at line 25 may classify only line 26; its
prior bare disconnect at line 24 cannot classify line 31, which has its own
combined marker at line 30.

### Streets, results, and arithmetic

Boards are preflop `[]`, flop `[2c, 4c, 8d]` (16), turn
`[2c, 4c, 8d, 7d]` (23), and river `[2c, 4c, 8d, 7d, 8h]` (33). The summary
board at line 42 must agree.

- `results.stated_pot`: gross 0.90, rake 0.04, net 0.86, and
  `gross_pots=[]` (line 41). The summary supplies the independent stated
  comparator; neither the award nor reconstruction replaces its evidence.
- `results.showdown`, in source order: `seat-4` shows `[3s, 3c]` (37), then
  `seat-5` mucks with no cards (38). The rank prose remains raw source
  description only.
- `results.awards`: `seat-4` collects 0.86 from `pot` (39), with
  `pot_index=None`. `results.players=[]`; no net-result vector is stated.
- Summary rows 43–45 must agree with the previously observed fold street,
  position labels, shown/mucked dispositions, cards, and collection. They add
  no actions, duplicate showdown entry, award, player result, hero, or winner
  calculation.

Independent action arithmetic gives contributions of 0.10 from `seat-2`, 0.40
from `seat-4`, and 0.40 from `seat-5`. Their 0.90 total matches the stated
gross pot; gross minus 0.04 rake equals the 0.86 net and reported collection.
These labels expect a zero-discrepancy, amount-only `pass` reconciliation. They
do not calculate best-five ranks, certify a winner, establish a rake schedule,
or make the hand extractable while its hero is unknown.

## Evidence, warnings, and negative cases

Use exact field evidence for the header (line 1), table/button (2), seats and
positions (2–5), forced/action lines, board lines, and direct result lines.
The five origin evidence lists are `[14,15]`, `[20,21]`, `[25,26]`, `[27,28]`,
and `[30,31]` respectively. Retain lines 11–14, 18–20, 24–25, 27, and 30 in
raw source as applicable; only the five explicit marker/action pairs are
origin evidence. No structured event store is added.

The expected detection warning, in exact order, is:

1. `Action origin is unresolved for 8 player decision(s); review is required.`

Unknown hero fields and absence of a cash rake schedule are explicit state
unknowns, not fabricated zero-confidence facts. The state remains reviewable,
but decision extraction is `incomplete_hand_state` before any origin-based
decision selection.

The adapter preserves the established 2008 unqualified-dollar family while
rejecting malformed or changed **explicit-USD one-digit-hour** headers, other
new currencies/zones/limits, invalid source time, unbound or cross-scope
markers, reconnect text, player-selected/preselection inference,
joiner-as-seat behavior, and rank-derived winner claims outside this qualified
surface. A bare disconnect remains accepted only as inert raw text and cannot
classify a later action.

## Independent review and implementation gate

The independent review on PR #513 compared the pinned original bytes with the
three-seat ring, all 15 actions, five marker bindings, boards, supplied unknown
hero, source results, and 0.90 / 0.04 / 0.86 arithmetic. It found no issues.
The implementation retains the fixture digest and adds full-state,
unknown-hero, malformed/negative, raw-retention, and reimport regressions. No
schema, API, workspace, backup, approval, or corpus-gate change is authorized
by this source mapping.
