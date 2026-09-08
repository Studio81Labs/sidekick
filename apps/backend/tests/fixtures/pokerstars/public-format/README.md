# Public PokerStars format specimens

This directory contains a sanitized derivative of `HAND2` from
[`pokerregion/poker`](https://github.com/pokerregion/poker/blob/0a47855301c1dd571368039353b9aa6ce65c30fd/tests/handhistory/stars_hands.py)
at commit `0a47855301c1dd571368039353b9aa6ce65c30fd`. The upstream source is
licensed under MIT; its complete attribution and license text are retained in
[`LICENSE.pokerregion-poker-MIT.txt`](./LICENSE.pokerregion-poker-MIT.txt).

The fixture is a **public format sample**, not a representative corpus case or
proof of current PokerStars semantics. It must not support a Phase 0 clean-rate,
action-origin, commercial-rights, or grading-coverage claim.

## Sanitization

Before committing, the fixture replaced the upstream hand and tournament/table
identifiers with invented values and mapped every player name one-to-one to
`Player01` through `Player09`. It retains the observed tournament-header,
timestamp, ante, blind, all-in, side-pot, showdown, summary, and tournament
placement syntax for parser investigation. It contains no original player name,
hand identifier, tournament identifier, table identifier, account identifier,
or local source path. The sanitized fixture is 2,121 bytes with SHA-256
`844d23d2e5085e02082a85f873ba9cd5637ed300545846877c520a8b444a11e4`.

## Current expectation

The P0 regression deliberately expects the current cash-only adapter to reject
this specimen with `unsupported_header` at line 1. That expectation was written
from the fixture and the documented cash-only contract, not copied from a
successful parser result. P1a may replace it only with independently reviewed
full-state labels when the tournament-header and summary semantics are
implemented.
