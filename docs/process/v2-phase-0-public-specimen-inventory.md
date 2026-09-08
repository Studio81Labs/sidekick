# Phase 0 Public Specimen Inventory

This inventory records the bounded public-source preparation permitted by
issues [#409](https://github.com/Studio81Labs/sidekick/issues/409) and
[#412](https://github.com/Studio81Labs/sidekick/issues/412). It distinguishes
format investigation from representative-corpus, rights, and qualification
evidence required by the Phase 0 gate.

Status: P1a0 compatibility merged in #500; the P1a implementation maps the
reviewed HAND2 form defined in [the label sheet](pokerstars-hand2-source-labels.md)
and [ADR 0078](../decisions/0078-preserve-unresolved-historical-source-time.md).
Phase 1 remains **NO-GO**.

## Evidence boundary

Each entry records a pinned source, retrieval date, byte digest, known use, and
what it cannot establish. A public source is never promoted to a representative
PokerStars corpus case or a qualified solved source solely because it is
downloadable. Private exports, player histories, vendor correspondence, and
license dossiers remain outside this repository.

The current adapter accepts its documented English no-limit cash subset and the
single reviewed historical HAND2 tournament form. Other tournament syntax and a
viewer save remain evidence-led investigation, not expanded support or corpus
evidence.

## PokerStars tournament format specimen

| Field                     | Recorded value                                                                                                                                                                                                                                                |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Evidence level            | `public format sample`                                                                                                                                                                                                                                        |
| Source                    | [`pokerregion/poker` `stars_hands.py`](https://github.com/pokerregion/poker/blob/0a47855301c1dd571368039353b9aa6ce65c30fd/tests/handhistory/stars_hands.py), pinned to `0a47855301c1dd571368039353b9aa6ce65c30fd`                                             |
| Retrieved                 | 2026-09-08                                                                                                                                                                                                                                                    |
| Source SHA-256            | `76abb12360b114eaf3a7ccd12ed5e5237f4d83817215ff326969978e86b2efda`                                                                                                                                                                                            |
| License evidence          | [upstream MIT license](https://github.com/pokerregion/poker/blob/0a47855301c1dd571368039353b9aa6ce65c30fd/LICENSE), SHA-256 `0a8b15334228a8dc8c034eb548fcf6c67bf36033039fa8a7ffa4c6ab17f254c4`                                                                |
| Repository material       | Sanitized `HAND2` derivative at [`apps/backend/tests/fixtures/pokerstars/public-format/pokerregion-tournament-hand2.txt`](../../apps/backend/tests/fixtures/pokerstars/public-format/pokerregion-tournament-hand2.txt), with retained attribution and license |
| Sanitized fixture SHA-256 | `844d23d2e5085e02082a85f873ba9cd5637ed300545846877c520a8b444a11e4`                                                                                                                                                                                            |
| Sanitation                | Replaced all player names and hand/tournament/table identifiers; preserved observed textual syntax, poker amounts, cards, and action order; no local path is retained                                                                                         |
| Permitted use             | Regression and source-format investigation under the retained MIT attribution; no claim about current PokerStars behavior beyond the observed text                                                                                                            |
| Independent label review  | [Source mapping](pokerstars-hand2-source-labels.md) authored and checked independently of adapter output, with a separate agent source audit; no human/corpus certification claimed. The P1a regression maps only the labelled HAND2 form.                    |

The specimen demonstrates a tournament header with buy-in/fee, level and blind
text, `CET` plus bracketed `ET` timestamps, antes, all-in actions, side-pot
summary wording, and tournament placements. It does **not** establish which
source timestamp is canonical, full tournament-economic/ICM inputs, current
client-version behavior, automatic/timeout/disconnect semantics, or a 1,000-hand
representative distribution.

## PokerStars cash action-origin specimen

| Field                     | Recorded value                                                                                                                                                                                                                                                                                    |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Evidence level            | `public format sample`                                                                                                                                                                                                                                                                            |
| Source                    | [`HHSmithy/PokerHandHistoryParser` `Limit1.txt`](https://github.com/HHSmithy/PokerHandHistoryParser/blob/91600818d95e23f154073735c1258e92c4f55f97/HandHistories.Parser.UnitTests/SampleHandHistories/PokerStars/CashGame/Limits/Limit1.txt), pinned to `91600818d95e23f154073735c1258e92c4f55f97` |
| Retrieved                 | 2026-09-08                                                                                                                                                                                                                                                                                        |
| Source SHA-256            | `9eb7e08c0bd57cd69ef5983102d813b56e138ad25d814d6881932fd4623e96cb` (1,410 bytes)                                                                                                                                                                                                                  |
| License evidence          | [upstream README MIT license](https://github.com/HHSmithy/PokerHandHistoryParser/blob/91600818d95e23f154073735c1258e92c4f55f97/README.md#license), SHA-256 `c9421183ce179d09f85510fefac722c76a01b0f92edb208b34b8237fce2d5a9c`                                                                     |
| Repository material       | Sanitized source-only derivative at [`apps/backend/tests/fixtures/pokerstars/public-format/hhsmithy-cash-limit1.txt`](../../apps/backend/tests/fixtures/pokerstars/public-format/hhsmithy-cash-limit1.txt), attribution/license retained beside it                                                |
| Sanitized fixture SHA-256 | `481c9ac5af9e20bc0fa6f55adf606d52733387993ef8aec2696193cadfde2ae0` (1,378 bytes)                                                                                                                                                                                                                  |
| Sanitation                | Replaced player, observer, joiner, hand and table identifiers; retained source syntax, cards, amounts, timestamps, event order and line positions.                                                                                                                                                |
| Independent labels        | P1b evidence ledger and independently authored current rejection expectation in [the action-origin packet](pokerstars-p1b-action-origin-evidence.md); independent source review is required before parser implementation.                                                                         |

This specimen records plain `has timed out`, `has timed out while disconnected`,
and unrelated table/disconnect notifications. The current adapter rejects it at
the legacy `PokerStars Game #` header, and it lacks a dealt-to-hero line. It is
therefore not a supported parser input, a proof of current-client behavior, or
a complete action-origin rule. The bounded candidate labels, combined-cause
encoding, evidence lines, scope/reset conditions, and explicit negative cases
are recorded separately; missing markers continue to mean `unknown`.

## HRC viewer example

| Field                    | Recorded value                                                                                                                                                           |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Evidence level           | `public format sample`                                                                                                                                                   |
| Source                   | [HRC First Steps](https://www.holdemresources.net/docs/first-steps/) → [example viewer file](https://www.holdemresources.net/misc/examples/icm_25bb_classic_viewer.hrcv) |
| Retrieved                | 2026-09-08                                                                                                                                                               |
| Byte length              | `3620892`                                                                                                                                                                |
| SHA-256                  | `b649880e9de9ce4018dc37a564fea816b5ca26aa74d8c341d4e7b1277f46a7c8`                                                                                                       |
| Observed archive entries | `settings.json`, `state.json`, `gametree.dat`, `nodedata.dat`, `idx.dat`                                                                                                 |
| Permitted use            | Documentation and viewer-format inspection only; no file is committed                                                                                                    |
| Rights/export status     | No distribution, normalized-artifact, or strategy-export right is established by this entry                                                                              |

The [HRC release notes](https://www.holdemresources.net/blog/2023-hrc-v3-release/)
describe a viewer save as a partial save containing hand settings and preflop
results, and `Hand: Export Strategies` as the JSON format containing strategies
and EVs. This `.hrcv` sample is therefore not a supported strategy JSON export,
must not be decoded or normalized, and cannot satisfy R0's source, rights, unit,
convergence, or coverage requirements.

## Exact unsupported inventory

The next parser implementation may proceed only after a reviewed source label
defines the corresponding meaning. This inventory leaves the following explicit
blockers in place:

- Tournament header mapping: #498's model gap is resolved by
  [ADR 0077](../decisions/0077-retain-tournament-entry-and-level-source-facts.md).
  Its P1a0 model/serialization and workspace v5/backup v3 compatibility work
  merged in #500. The entry pair maps to optional
  `entry_buy_in`/`entry_fee` in explicit currency and `blind_level="XI"`;
  `stage` remains unknown. The [HAND2 labels](pokerstars-hand2-source-labels.md)
  now specify the complete bounded mapping, including unknown tournament type
  and normalized chronology. Both printed timestamps remain raw/source evidence
  under ADR 0078. An exact historical offset remains an evidence question, not a
  prerequisite to implementing these explicitly uncertain labels. The adapter
  maps only this reviewed form; other tournament headers remain unsupported.
- Tournament economics: no payout, remaining-field, bounty, ICM, or rake
  schedule may be inferred from the specimen.
- Summary variants: HAND2 main/side-pot totals, showdown/collection comparisons
  and source-only finish places are mapped in the label sheet. Additional
  unreviewed variants still require their own labels before acceptance.
- Action origin: an all-in marker is not evidence that a choice was voluntary,
  automatic, timeout-driven, or disconnect-driven. Missing markers remain
  `unknown` unless versioned source semantics prove otherwise.
- Corpus evidence: this single sample's agent-reviewed development mapping is
  not representative-corpus or external poker-review qualification. It
  contributes nothing to the ≥99% parser gate or its composition thresholds.
- Solved-reference evidence: no supported HRC strategy export, selected-delivery
  rights, route/economics matrix, unit/utility mapping, convergence artifact,
  poker review, benchmark, coverage result, or budget is available.

## Next evidence required

The P1a implementation uses the linked HAND2 mapping and source-authored
full-state expectations, including unknowns, warnings and retained evidence.
It does not derive expected labels from its own parser output. P2 still needs a
private authorized representative corpus and independent labels. R0 remains
blocked on an actual supported strategy export and rights evidence; no
source-specific normalizer, lookup, certification, production catalog, or
network transport is authorized by this inventory.
