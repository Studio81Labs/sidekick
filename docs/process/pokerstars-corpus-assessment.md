# PokerStars Corpus Assessment

Use the offline assessment command to measure the bounded PokerStars adapter
against independently labeled histories for issue #409. The command reads local
files only and does not open the player workspace or import any hand.

## Corpus custody

- Use only histories the project is authorized to inspect and assess.
- Sanitize any fixture or report before committing it. Do not commit production
  hand IDs, player names, account identifiers, or local source paths.
- Keep private source files and the working manifest outside the repository.
- Give cases opaque local IDs. IDs and source paths are consumed for validation
  and the corpus fingerprint but are not emitted in the report.
- Author expectations independently from the parser output. Copying parser
  output into the manifest would measure serialization consistency, not
  correctness.

## Manifest contract

The root schema is `pokerstars-corpus-manifest/v1`. Cases must be unique and
sorted by `source_path`, then `hand_ordinal`; every source must label contiguous
ordinals starting at one. Paths are relative POSIX paths beneath the selected
corpus root. Source bytes and non-null source hand IDs must be unique across the
corpus.

Every case includes sorted coverage `tags` and one expectation:

- `parsed`: expected reconciliation disposition, source hand ID, played time and
  source zone, game/blind/economic context, button, every seat and exact
  structural position, hero cards, ordered streets and board cards, every action
  and actor seat, action-origin classification/confidence, action and origin
  evidence line numbers, stated pot, showdown evidence, awards, player results,
  and complete parser warnings;
- `rejected`: the expected nullable source hand ID and structured parser
  diagnostic code.

Inferable tags such as `cash`, `tournament`, `heads_up`, `six_max`, `full_ring`,
`sit_out`, `ante`, `uncalled_bet`, `automatic_action`, `timeout`, `disconnect`,
`player_selected_action`, `forced_system_action`, `unknown_action`, `rake`,
`showdown`, and `side_pot` must exactly match the parsed expectation.
`incomplete_hand` remains an explicit corpus label because it needs source-level
review. All tags on a rejected case also require independent source review
because there is no parsed projection from which to infer them.

The Pydantic models in
`apps/backend/app/pokerstars_corpus_assessment.py` are the authoritative field
contract. Invalid, duplicate, incomplete, unsorted, or path-escaping manifests
are rejected before a result can be treated as evidence.

## Run the current adapter checkpoint

From the repository root, gate the format and scenarios the current bounded
adapter can produce as matching parses:

```bash
pnpm backend:pokerstars-corpus /absolute/private/manifest.json \
  --corpus-root /absolute/private/pokerstars-corpus \
  --minimum-cases 1000 \
  --minimum-clean-parse-rate 0.99 \
  --minimum-tag-count cash=1 \
  --minimum-tag-count heads_up=1 \
  --minimum-tag-count six_max=1 \
  --minimum-tag-count full_ring=1 \
  --minimum-tag-count sit_out=1 \
  --minimum-tag-count ante=1 \
  --minimum-tag-count uncalled_bet=1 \
  --minimum-tag-count rake=1 \
  --minimum-tag-count side_pot=1 \
  --minimum-tag-count showdown=1 \
  --minimum-tag-count forced_system_action=1 \
  --minimum-tag-count unknown_action=1 \
  --minimum-labeled-tag-count incomplete_hand=1 \
  --json > /absolute/private/pokerstars-assessment.json
```

This is a regression checkpoint for the adapter's current supported surface,
not the complete Phase 0 acceptance gate. The current format revision maps one
reviewed tournament form and two reviewed, versioned automatic-action cash
forms, while ordinary unmarked decisions remain `unknown`. It can therefore
produce matching parsed cases tagged `tournament`, `automatic_action`,
`timeout`, or `disconnect` only where a separately reviewed source label
supports them. It cannot yet produce `player_selected_action`, reconnect, or
absence-derived origin cases. Do not add impossible verified-parse gates merely
to make the command look complete.

Those categories remain Phase 0 blockers, not waived requirements. Before
closing #409, implement their parser semantics, add each category to the command
above as a `--minimum-tag-count`, and obtain matching parsed examples in the
representative corpus. Until then, exit status `0` proves only the current
adapter checkpoint and must not be reported as Phase 0 acceptance.

After recording the first reviewed report, pin its printed digest on repeat
runs:

```bash
pnpm backend:pokerstars-corpus /absolute/private/manifest.json \
  --corpus-root /absolute/private/pokerstars-corpus \
  --expected-corpus-fingerprint <64-lowercase-hex-digest> \
  --minimum-cases 1000 \
  --minimum-clean-parse-rate 0.99 \
  --json
```

Exit status `0` means every case matched its labels and all requested gates
passed. Status `1` means a ground-truth, count, rate, tag, or fingerprint gate
failed. Status `2` means the manifest or corpus could not be assessed safely.
The clean-parse rate always divides clean matching parses by every labeled hand,
including expected rejections; unsupported cases cannot be removed from the 99%
denominator by changing their expected outcome. A `--minimum-tag-count` gate
uses only ground-truth-matching parsed cases. Labeled rejected cases remain in
the report's composition counts but cannot satisfy a parsed-coverage gate. The
separate `--minimum-labeled-tag-count` gate accepts only `incomplete_hand`; it
allows independently reviewed incomplete cases to count whether their safe
expected result is a parse or a structured rejection.

The report intentionally contains only aggregate counts, adapter/format
revisions, the corpus fingerprint, and ordinal-only failure categories. It
separates labeled composition tags from verified parsed coverage tags. Use the
private manifest to map a failing ordinal back to source material. Do not weaken
redaction to make a report self-contained.

## Evidence boundary

A passing synthetic run validates the assessment instrument only. A passing
current-adapter checkpoint validates only its listed supported surface. Do not
claim the #409 representative-corpus requirement, 99% Phase 0 gate, complete
format/action-origin coverage, or issue completion until the unsupported
categories above are implemented and gated and the legally obtained or
sanitized real corpus has the required composition, independent labels, and a
passing pinned run.
