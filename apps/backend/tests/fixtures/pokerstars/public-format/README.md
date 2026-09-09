# Public PokerStars format specimens

This directory contains sanitized derivatives of bounded public PokerStars
format specimens. Each upstream source is licensed under MIT; its complete
attribution and license text are retained beside its derivative.

Each specimen is a **public format sample**, not a representative corpus case
or proof of current PokerStars semantics. It must not support a Phase 0
clean-rate, action-origin, commercial-rights, or grading-coverage claim.

## Pokerregion tournament HAND2 sanitation

Before committing, the fixture replaced the upstream hand and tournament/table
identifiers with invented values and mapped every player name one-to-one to
`Player01` through `Player09`. It retains the observed tournament-header,
timestamp, ante, blind, all-in, side-pot, showdown, summary, and tournament
placement syntax for parser investigation. It contains no original player name,
hand identifier, tournament identifier, table identifier, account identifier,
or local source path. The sanitized fixture is 2,121 bytes with SHA-256
`844d23d2e5085e02082a85f873ba9cd5637ed300545846877c520a8b444a11e4`.

## HAND2 current expectation

The P1a regression maps this specimen only against the independently reviewed
[HAND2 source labels](../../../../../../docs/process/pokerstars-hand2-source-labels.md).
It preserves unresolved normalized chronology, retains the printed timestamps
as source evidence, and keeps finish places ancillary. This does not establish
general tournament support, current PokerStars semantics, or corpus evidence.

## HHSmithy cash `Limit1`

[`hhsmithy-cash-limit1.txt`](./hhsmithy-cash-limit1.txt) is a sanitized
derivative of
[`Limit1.txt`](https://github.com/HHSmithy/PokerHandHistoryParser/blob/91600818d95e23f154073735c1258e92c4f55f97/HandHistories.Parser.UnitTests/SampleHandHistories/PokerStars/CashGame/Limits/Limit1.txt)
from `HHSmithy/PokerHandHistoryParser` at commit
`91600818d95e23f154073735c1258e92c4f55f97`. Its upstream MIT license is
retained in
[`LICENSE.hhsmithy-pokerhandhistoryparser-MIT.txt`](./LICENSE.hhsmithy-pokerhandhistoryparser-MIT.txt).

The fixture maps every original player, observer and table-join name to an
invented role identifier and replaces the upstream hand/table identifiers. It
preserves the source's header family, timestamp text, monetary/card/action
syntax, line order, and timeout/disconnect/table-notification markers. No
original player, hand identifier, table identifier, account identifier, or
local source path remains.

The file is a public format sample and bounded P1b regression input. It is not
a representative-corpus case, proof of current-client behavior, or proof that
a missing marker identifies a player-selected action. The adapter maps only its
independently reviewed `pokerstars-text/v4` header/body form: explicit `USD`, a
one-digit-hour legacy header, an unknown hero, the three initial dealt-in
seats, source results, inert notifications, and the five qualified marker
bindings. Do not use it to introduce unrelated header, hero, reconnect, or
player-selected inference. The associated source labels and evidence packet are
[`docs/process/pokerstars-p1b-hhsmithy-source-labels.md`](../../../../../../docs/process/pokerstars-p1b-hhsmithy-source-labels.md)
and
[`docs/process/pokerstars-p1b-action-origin-evidence.md`](../../../../../../docs/process/pokerstars-p1b-action-origin-evidence.md).

## wizardwerdna/pokerstats legacy timeout-to-fold

[`wizardwerdna-pokerstats-timeout-fold.txt`](./wizardwerdna-pokerstats-timeout-fold.txt)
is a sanitized derivative of lines 194–246 of
[`spec/file_many_hands.txt`](https://github.com/wizardwerdna/pokerstats/blob/315a4db29630c586fb080d084fa17dcad9494a84/spec/file_many_hands.txt#L194-L246)
from `wizardwerdna/pokerstats` at commit
`315a4db29630c586fb080d084fa17dcad9494a84`. Its upstream MIT license is
retained in
[`LICENSE.wizardwerdna-pokerstats-MIT.txt`](./LICENSE.wizardwerdna-pokerstats-MIT.txt).

The fixture maps each original player name to `Player01` through `Player09`,
replaces the hand/table identifiers, and normalizes trailing whitespace only.
It retains the legacy header, timestamp/dollar text, stacks, cards, amounts,
action/summary order, immediate timeout-to-fold pair, and following sit-out
notification. No original player, hand, table, account identifier, or local
path remains.

This public format sample is P1b source-label input, not a representative
corpus case or current-client proof. The reviewed adapter maps only its exact
legacy header/body grammar. The labels preserve `currency=None` because dollar
notation supplies no ISO code; unmarked actions remain unknown. Do not rewrite
it to a modern header or broaden the reviewed parser support. See the
[legacy timeout labels](../../../../../../docs/process/pokerstars-p1b-game-timeout-source-labels.md).
