# Phase 0 Public Specimen Inventory

This inventory records the bounded public-source preparation permitted by
issues [#409](https://github.com/Studio81Labs/sidekick/issues/409) and
[#412](https://github.com/Studio81Labs/sidekick/issues/412). It distinguishes
format investigation from representative-corpus, rights, and qualification
evidence required by the Phase 0 gate.

Status: preparation only; Phase 1 remains **NO-GO**.

## Evidence boundary

Each entry records a pinned source, retrieval date, byte digest, known use, and
what it cannot establish. A public source is never promoted to a representative
PokerStars corpus case or a qualified solved source solely because it is
downloadable. Private exports, player histories, vendor correspondence, and
license dossiers remain outside this repository.

The current adapter accepts only its documented English no-limit cash subset.
Observed tournament syntax and a viewer save are retained here so later work can
be evidence-led, but neither changes that supported surface or parser provenance.

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
| Independent label review  | Full parsed-state label review is pending P1a; the P0 test independently expects only the documented current `unsupported_header` outcome                                                                                                                     |

The specimen demonstrates a tournament header with buy-in/fee, level and blind
text, `CET` plus bracketed `ET` timestamps, antes, all-in actions, side-pot
summary wording, and tournament placements. It does **not** establish which
source timestamp is canonical, full tournament-economic/ICM inputs, current
client-version behavior, automatic/timeout/disconnect semantics, or a 1,000-hand
representative distribution.

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
  Its P1a0 model/serialization and workspace v5/backup v3 compatibility work must
  merge before P1a parser changes. The entry pair maps to optional
  `entry_buy_in`/`entry_fee` in explicit currency and `blind_level="XI"`;
  `stage` remains unknown. Full source labels for tournament identity/type,
  absolute-chip stacks, summaries and source-time/zone interpretation are still
  required; this decision does not make the fixture parseable.
- Tournament economics: no payout, remaining-field, bounty, ICM, or rake
  schedule may be inferred from the specimen.
- Summary variants: main/side-pot totals, placements, and showdown wording need
  field-by-field labels before they become detected state.
- Action origin: an all-in marker is not evidence that a choice was voluntary,
  automatic, timeout-driven, or disconnect-driven. Missing markers remain
  `unknown` unless versioned source semantics prove otherwise.
- Corpus evidence: this single sample is not a representative case, has no
  independent full-state label review, and contributes nothing to the ≥99%
  parser gate or its composition thresholds.
- Solved-reference evidence: no supported HRC strategy export, selected-delivery
  rights, route/economics matrix, unit/utility mapping, convergence artifact,
  poker review, benchmark, coverage result, or budget is available.

## Next evidence required

After P1a0 compatibility work, P1a can replace the fixture's rejection assertion
with complete independently reviewed labels only for syntax established by a
pinned source. P2 still needs a
private authorized representative corpus and independent labels. R0 remains
blocked on an actual supported strategy export and rights evidence; no
source-specific normalizer, lookup, certification, production catalog, or
network transport is authorized by this inventory.
