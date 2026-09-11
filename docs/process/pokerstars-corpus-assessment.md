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

## Run the review MVP acceptance profile

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
  --minimum-tag-count tournament=1 \
  --minimum-tag-count automatic_action=1 \
  --minimum-tag-count timeout=1 \
  --minimum-tag-count disconnect=1 \
  --minimum-tag-count forced_system_action=1 \
  --minimum-tag-count unknown_action=1 \
  --minimum-labeled-tag-count incomplete_hand=1 \
  --json > /absolute/private/pokerstars-assessment.json
```

The command above supplies the mechanical gates for the **`review-mvp/v1`**
profile approved by [ADR 0082](../decisions/0082-deliver-a-review-first-local-mvp.md).
The manifest/report schemas remain v1. Before evaluating, freeze a representative
sampling plan with independent review: public source URLs/revisions/hashes,
rights/custodian, supported-format/date/economic distribution, exclusions and
reasons, independently authored full labels and named reviewers. Record an
immutable evidence index binding `profile: review-mvp/v1` to that plan, the exact
command, adapter/format/code revisions, report digest and corpus fingerprint.
`=1` floors prove scenario presence, not representative composition. Do not
change the sampling plan or labels to conceal failed cases after seeing results.

For this review-only profile, `player_selected_action` is not a mandatory parsed
tag. Positive preselection/reconnect/absence semantics are deferred, not guessed
or treated as passed. Reconnect and absence are not CLI tags. All existing
supported automatic timeout/disconnect, forced and unknown coverage floors
remain. Unknown origins must match independent labels and remain unknown in the
UI; #411 still requires affirmative evidence for any future voluntary learning
decision. A returned-status line proves no reconnect semantics.

At least 1,000 distinct authorized real hands from free public downloads are
required; no owner-supplied personal history or paid source is a prerequisite.
Source rights, labels, reviewers and the representative study remain unresolved.
An exit-zero run without those artifacts is an instrument/checkpoint result,
not #409 completion. Historical reports retain their original profile and claims.

After recording the first reviewed report, pin its printed digest on repeat
runs:

```bash
pnpm backend:pokerstars-corpus /absolute/private/manifest.json \
  --corpus-root /absolute/private/pokerstars-corpus \
  --expected-corpus-fingerprint <64-lowercase-hex-digest> \
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
  --minimum-tag-count tournament=1 \
  --minimum-tag-count automatic_action=1 \
  --minimum-tag-count timeout=1 \
  --minimum-tag-count disconnect=1 \
  --minimum-tag-count forced_system_action=1 \
  --minimum-tag-count unknown_action=1 \
  --minimum-labeled-tag-count incomplete_hand=1 \
  --json
```

Exit status `0` means every case matched its labels and all requested gates
passed. Status `1` means a ground-truth, count, rate, tag, or fingerprint gate
failed. Status `2` means the manifest or corpus could not be assessed safely.
The repeat command retains every review-profile count, rate and composition
gate together with the fingerprint; it is not a fingerprint-only check. Future
learning qualification must explicitly define any additional positive-origin
coverage and implement it only from independently reviewed source semantics.
Do not retroactively label this review report as a passed learning-origin gate.

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

A synthetic run validates the instrument only. A full `review-mvp/v1` acceptance
claim requires the real representative corpus, rights/custody, independent labels
and review, all frozen composition/count/rate gates and a passing fingerprint-
pinned run. No qualifying full corpus has yet been certified. This profile does
not certify comprehensive PokerStars syntax, positive voluntary/reconnect
semantics, showdown ranking, solved grading or learning eligibility.
