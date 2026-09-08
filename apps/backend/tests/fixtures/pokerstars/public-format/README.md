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

The file is a public format sample and P1b evidence-preparation input. It is
not a representative-corpus case, proof of current-client behavior, or proof
that a missing marker identifies a player-selected action. Its exact current
parser expectation is the structured `no_hand_headers` rejection: it retains
the observed legacy `PokerStars Game #` header and has no dealt-to-hero line.
Do not edit it into an accepted history or use it to introduce unrelated header
or hero inference. The associated evidence packet is
[`docs/process/pokerstars-p1b-action-origin-evidence.md`](../../../../../../docs/process/pokerstars-p1b-action-origin-evidence.md).
