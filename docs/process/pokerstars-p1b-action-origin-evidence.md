# PokerStars P1b Action-Origin Evidence Preparation

Status: P1b source-evidence preparation under #409. This packet is not a
parser implementation, a passing corpus case, representative-corpus evidence,
or an external poker-expert certification. It must receive an independent
source-review pass before any rule below is implemented.

## Scope, custody, and sanitation

| Field                    | Recorded value                                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Evidence level           | `public format sample`                                                                                                                                                                                                                                                                                                                                                                                     |
| Upstream source          | [`HHSmithy/PokerHandHistoryParser` `Limit1.txt`](https://github.com/HHSmithy/PokerHandHistoryParser/blob/91600818d95e23f154073735c1258e92c4f55f97/HandHistories.Parser.UnitTests/SampleHandHistories/PokerStars/CashGame/Limits/Limit1.txt), pinned to `91600818d95e23f154073735c1258e92c4f55f97`                                                                                                          |
| Retrieved                | 2026-09-08                                                                                                                                                                                                                                                                                                                                                                                                 |
| Original bytes           | 1,410 bytes; SHA-256 `9eb7e08c0bd57cd69ef5983102d813b56e138ad25d814d6881932fd4623e96cb`                                                                                                                                                                                                                                                                                                                    |
| License evidence         | [upstream README MIT license](https://github.com/HHSmithy/PokerHandHistoryParser/blob/91600818d95e23f154073735c1258e92c4f55f97/README.md#license), SHA-256 `c9421183ce179d09f85510fefac722c76a01b0f92edb208b34b8237fce2d5a9c`; retained at [`LICENSE.hhsmithy-pokerhandhistoryparser-MIT.txt`](../../apps/backend/tests/fixtures/pokerstars/public-format/LICENSE.hhsmithy-pokerhandhistoryparser-MIT.txt) |
| Sanitized derivative     | [`hhsmithy-cash-limit1.txt`](../../apps/backend/tests/fixtures/pokerstars/public-format/hhsmithy-cash-limit1.txt), 1,378 bytes, SHA-256 `481c9ac5af9e20bc0fa6f55adf606d52733387993ef8aec2696193cadfde2ae0`                                                                                                                                                                                                 |
| Source family            | English PokerStars cash no-limit history, with a legacy `PokerStars Game #` header and observed 2014 timestamp text                                                                                                                                                                                                                                                                                        |
| Channel/version metadata | Export channel, PokerStars client/build, locale provenance, and current-client applicability are unknown                                                                                                                                                                                                                                                                                                   |
| Sanitation               | Original player/observer/joiner names map one-to-one to invented role identifiers; the hand/table identifiers are invented. Textual syntax, cards, amounts, timestamps, event order, and line numbers are retained.                                                                                                                                                                                        |

The upstream repository's MIT terms permit this attributed derivative. Its
public availability does not establish that it is a current PokerStars export,
a representative customer history, or an exhaustive description of client
automatic behavior.

## Current parser boundary and independently authored expectation

The sanitized source has 45 lines. It is an explicitly labelled negative
integration fixture for the current adapter:

| Input                 | Expected result                                                     | Evidence                                                                                                                                   |
| --------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Exact sanitized bytes | No parsed candidates; one `unsupported_header` diagnostic at line 1 | The adapter detects a `PokerStars Game #` hand boundary, then rejects this one-digit-hour/explicit-ISO header outside the bounded grammar. |

The fixture has no `Dealt to` line. It cannot be transformed into a positive
parser case by adding a hero, changing its header, or treating a known actor as
the hero. Its present expectation remains rejection until a separately reviewed
extension supplies full-state labels and implements the evidenced grammar.
That expectation is a current parser boundary, not a permanent prohibition on
qualifying this source.

`ImportedHandState` already permits `hero_player_id=None` and `hero_cards=[]`.
A complete detected-state expectation must explicitly label these unknowns;
it need not invent an extractable hero. Ordinary cash parsing has no universal
hero requirement. Decision extraction still returns `incomplete_hand_state`
when the hero is unknown, even after explicit approval. The separate reviewed
HAND2 tournament form's required dealt-to line remains unchanged.

For this source, full-state label preparation and bounded grammar qualification
are remaining work, not a requirement to obtain another external file solely
to supply hero cards or match an already supported header. The header has both
a one-digit hour and an explicit `USD` token, unlike the supported 2008 legacy
cash family. Labels must preserve that supplied currency, the three initial
dealt-in seats, all actions/boards/results, and every unproved field. Keep the
original bytes and sanitation mapping unchanged.

## Evidence reviewed for marker candidates

The raw source is the only evidence of this historical text grammar and event
ordering. PokerStars' [cash time-bank help](https://www.pokerstars.com/help/articles/ring-time-ma/220419/)
states that a time bank activates when ordinary decision time expires, that a
disconnected player receives reconnect time instead, and that expiration folds
the hand. Its [tournament mechanics](https://www.pokerstars.com/help/articles/rules-table-master/)
also states that a sit-out player automatically folds while still posting blinds
and antes.

Those vendor statements establish that timeout and disconnect automation exist;
they do not specify this historical export grammar, its complete marker set,
the action-binding algorithm, reconnect ordering, or absence semantics.

## Proposed rule and source-label ledger

Line numbers refer to the exact sanitized fixture. The proposed semantics
revision is `pokerstars-cash-2014-timeout-disconnect-v1`; it is deliberately
versioned to this observed source family and must not be applied to another
channel, locale, or client version without its own reviewed evidence.

| Source marker and required binding                                                                                          | Labeled action                                                      | Proposed origin                                                                                                  | Cause/evidence                                                                                                                 | Scope and reset                                                                                                                                                                                      | Status                            |
| --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| `Player04 has timed out` immediately followed by `Player04: checks` (14–15, 20–21, 27–28)                                   | Same actor's immediately following check on the current street      | `client_automatic`, `explicit_marker`, confidence `1`, semantics revision above, `automatic_reason="timeout"`    | Retain both the marker and action lines.                                                                                       | One action only; consume the marker after that action. A new street, another actionable actor line, hand boundary, malformed binding, duplicate, or conflicting marker leaves the action unresolved. | Candidate for independent review. |
| `Player02 has timed out while disconnected` immediately followed by `Player02: checks` (25–26) or `Player02: folds` (30–31) | Same actor's immediately following check/fold on the current street | `client_automatic`, `explicit_marker`, confidence `1`, semantics revision above, `automatic_reason="disconnect"` | Retain the combined marker and bound action. Line 24 is additional actor-specific disconnect context for the first occurrence. | One action only; consume the marker after that action. The combined marker is self-contained; a prior bare disconnect notice is never enough.                                                        | Candidate for independent review. |
| `Observer01 is disconnected` (11)                                                                                           | None                                                                | No action-origin label                                                                                           | Retain as raw source text; it is not action evidence.                                                                          | It must not carry across actors, streets, hands, or files.                                                                                                                                           | Negative case.                    |
| Unmarked ordinary calls/checks/bets/folds, including lines 9, 10, 17, 22, 29, 32, 34, and 35                                | Their own action only                                               | `unknown`, `unresolved`, no confidence/revision/reason                                                           | Action line only.                                                                                                              | No inference from legality, all-in status, a clean pot, a prior timeout, or an absent marker.                                                                                                        | Required negative case.           |

The combined `while disconnected` text names both timeout and disconnect. The
existing single `automatic_reason` contract encodes it as `disconnect`, the
more specific cause, while retaining the complete marker text as evidence.
Plain timeout cases independently supply the `timeout` tag; a combined case
must not be counted twice merely because its source wording includes both
words.

## Explicit unsupported and negative cases

- A bare `is disconnected` message does not classify a subsequent action,
  including every later action in a hand or session.
- This source contains no reconnect marker, preselected-action marker, client
  version, export-channel declaration, or evidence that a marker's absence
  establishes a player-selected action. Those semantics remain unsupported.
- Duplicate, stale, cross-actor, cross-street, cross-hand, and conflicting
  timeout markers have no positive label in this packet. The parser must retain
  the affected action as unresolved or reject malformed syntax according to a
  separately reviewed rule; it must not bind a convenient later action.
- Parser output must never emit `user_confirmed`. Individual canonical review
  may separately record that origin under the existing audited approval
  contract, but that does not make this parser evidence or satisfy a corpus
  gate.

## Required independent review before implementation

The parser PR may implement only rows whose historical grammar, actor/action
binding, confidence, combined-cause encoding, and reset behavior receive a
separate source review against the pinned original bytes and cited vendor
material. It must also include a compatible, complete, independently labelled
input. Here, compatible means representable by existing domain contracts and
the explicitly reviewed target grammar; it does not mean already accepted by
the current parser or ready for hero-decision extraction. This fixture remains
a structured rejection today because its grammar and complete expected state
have not been implemented and reviewed as a positive case. The review must
verify that labels were authored from the source and this ledger before parser
output, not copied from the changed adapter.

The preparation must account for observer/join/disconnect notifications and the
show/summary rank prose as well as the header and five candidate marker/action
bindings. Existing retained raw text can preserve inert notifications without
a new structured event model. Any future accepted wording must be explicitly
bounded and validated: joiners must not be added to the initial dealt-in ring,
and a bare disconnect must not become a causal marker. Rank prose remains
source description under ADR 0078; do not derive a winner or repair source
awards. Unknown or materially unmodeled behavior still rejects or escalates.

First prepare complete source-authored labels and obtain independent review;
then implement only qualified rows in a separate parser PR. No parser change
or positive corpus qualification is conferred by this clarification. Missing
reconnect, preselection and player-selected/absence semantics remain separate
evidence gaps; they do not prevent preparation of this bounded source mapping.

Any attempt to infer player-selected origins from missing markers, expand this
legacy header into general PokerStars support, change `ActionOrigin` or corpus
tag contracts, or rely on a hand-global disconnected state is outside this
packet and requires the existing Epic escalation process.
