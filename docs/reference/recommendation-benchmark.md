# Recommendation Benchmark Format

The offline recommendation benchmark compares any configured recommendation
provider with a reviewed reference policy. Reference data should come from a
trusted solver export or an independently reviewed strategy source. Do not
generate the reference with the same provider being evaluated.

## Run A Corpus

```bash
pnpm backend:recommendation-benchmark ./recommendation-benchmark.json \
  --provider local_solver \
  --require-reference-source \
  --require-grading-reference \
  --minimum-action-accuracy 0.90 \
  --minimum-line-accuracy 0.80 \
  --minimum-line-coverage 0.90 \
  --minimum-policy-coverage 0.90 \
  --minimum-ev-coverage 0.90 \
  --minimum-conditioning-accuracy 1.00 \
  --minimum-conditioning-coverage 1.00 \
  --minimum-range-source-accuracy 1.00 \
  --minimum-range-source-coverage 1.00 \
  --maximum-policy-distance 0.15 \
  --maximum-ev-loss 0.05 \
  --maximum-fallback-rate 0.20
```

Add `--json` for the complete machine-readable report. The command exits with
status `1` when a provider case fails or a configured threshold is missed, and
status `2` when the corpus or provider configuration is invalid.

## Regression Baselines

Capture a trusted report with `--json`, then compare a later run of the same
provider and normalized corpus:

```bash
pnpm backend:recommendation-benchmark ./recommendation-benchmark.json \
  --provider local_solver \
  --json > ./local-solver-baseline.json

pnpm backend:recommendation-benchmark ./recommendation-benchmark.json \
  --provider local_solver \
  --baseline-report ./local-solver-baseline.json \
  --maximum-metric-regression action_accuracy=0.01 \
  --maximum-metric-regression line_accuracy=0.01 \
  --maximum-metric-regression average_policy_distance=0.02 \
  --maximum-metric-regression average_ev_loss=0.05 \
  --maximum-metric-regression fallback_rate=0 \
  --maximum-street-metric-regression river:average_ev_loss=0.02 \
  --maximum-tag-metric-regression facing-bet:action_accuracy=0.01 \
  --maximum-case-metric-regression action_accuracy=0
```

The dataset fingerprint covers normalized scoring inputs, thresholds, tags,
and reference provenance while ignoring case order, tag order, reference-line
order, and case descriptions. A changed state, policy, EV label, or other
scoring input requires an explicitly reviewed replacement baseline. Reports
without a fingerprint remain readable but cannot be used as a baseline.

Repeat `--maximum-metric-regression METRIC=DELTA` with any of these keys:

- `action_accuracy`, `line_accuracy`, `line_coverage`, `policy_coverage`,
  `ev_coverage`, `conditioning_accuracy`, `conditioning_coverage`,
  `range_source_accuracy`, and `range_source_coverage`: fail on excessive drops.
- `average_policy_distance`, `average_ev_loss`, `maximum_ev_loss`, and
  `fallback_rate`: fail on excessive increases.

Ratio deltas use `0.01` for one percentage point. EV-loss deltas use BB. Human
output shows all comparable aggregate changes. JSON mode emits only the current
report on stdout so it remains reusable, with failures written to stderr.

Use repeatable
`--maximum-street-metric-regression STREET:METRIC=DELTA` and
`--maximum-tag-metric-regression TAG:METRIC=DELTA` declarations to protect one
existing report breakdown from regressions hidden by the aggregate. They accept
the same metric keys and direction rules. A repeated scope/metric pair or a
scope absent from the benchmark corpus is a configuration error.

Use repeatable `--maximum-case-metric-regression METRIC=DELTA` declarations to
apply a threshold independently to every case. This catches a regression in one
trusted hand even when a recovery elsewhere leaves aggregate, street, and tag
metrics unchanged. The case gate accepts the same metric keys. A metric that was
not evaluated for a baseline case is skipped for that case; if baseline evidence
was evaluated and disappears from the current run, the case fails explicitly.

## Corpus Schema

```json
{
  "schema": "poker-hero-recommendation-benchmark",
  "schema_version": 5,
  "name": "Reviewed heads-up turn sample",
  "reference_source": {
    "name": "Independent solver export",
    "version": "2026.08",
    "configuration": "Heads-up cash, 100 BB, no rake"
  },
  "grading_reference": {
    "reference_revision": "reference-example-2026.08",
    "policy_revision": "policy-example-2026.08.1",
    "tolerance_revision": "tolerance-example-1",
    "source_artifact_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
    "source_configuration_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
    "policy_artifact_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
    "coverage": {
      "table_configurations": [
        {
          "dealt_in_count": 2,
          "structural_positions": [
            {
              "action_index": 0,
              "button_distance": 0,
              "display_label": "BTN/SB"
            },
            {
              "action_index": 1,
              "button_distance": 1,
              "display_label": "BB"
            }
          ]
        }
      ],
      "effective_stack_depths_bb": [97.5],
      "streets": ["turn"]
    },
    "economic_model": {
      "kind": "cash",
      "name": "heads-up-no-rake-example",
      "revision": "economics-example-1",
      "configuration_sha256": "4444444444444444444444444444444444444444444444444444444444444444"
    },
    "utility_model": {
      "name": "cash-expected-value-example",
      "revision": "utility-example-1",
      "configuration_sha256": "5555555555555555555555555555555555555555555555555555555555555555"
    },
    "ev_unit": "bb",
    "rights_evidence": {
      "basis": "licensed",
      "delivery_mode": "shipped_static_lookup",
      "grants": ["commercial_use", "embedding", "redistribution", "updates"],
      "evidence_pointer": "example-only:not-license-evidence",
      "evidence_sha256": "6666666666666666666666666666666666666666666666666666666666666666"
    },
    "convergence_evidence": [
      {
        "metric": "exploitability",
        "unit": "bb_per_100",
        "comparison": "at_most",
        "threshold": 0.02,
        "observed": 0.01,
        "iterations": 250000,
        "evidence_pointer": "example-only:not-convergence-evidence",
        "evidence_sha256": "7777777777777777777777777777777777777777777777777777777777777777"
      }
    ]
  },
  "sizing_tolerance_bb": 0.01,
  "minimum_policy_frequency": 0.05,
  "cases": [
    {
      "id": "btn-vs-bb-turn-001",
      "description": "Button checks or bets half pot after a checked flop",
      "tags": [
        "single-raised-pot",
        "in-position",
        "range-conditioning",
        "range-source"
      ],
      "expected_range_conditioning": "applied",
      "expected_range_source": "preflop_chart_single_raised_pot",
      "state": {
        "hero_cards": [
          { "rank": "A", "suit": "hearts" },
          { "rank": "K", "suit": "diamonds" }
        ],
        "board_cards": [
          { "rank": "Q", "suit": "spades" },
          { "rank": "7", "suit": "clubs" },
          { "rank": "2", "suit": "hearts" },
          { "rank": "4", "suit": "diamonds" }
        ],
        "pot_size": 5.5,
        "current_bet": 0.0,
        "hero_stack": 97.5,
        "opponent_stack": 97.5,
        "effective_stack": 97.5,
        "players_in_hand": 2,
        "hero_structural_position": {
          "dealt_in_player_count": 2,
          "action_index": 0,
          "button_distance": 0,
          "display_label": "BTN/SB"
        },
        "hero_position": "button",
        "opponent_position": "big_blind",
        "preflop_opener_position": "button",
        "preflop_open_size": 2.5,
        "preflop_action_history": [
          { "actor": "button", "action": "raise", "amount": 2.5 },
          { "actor": "big_blind", "action": "call", "amount": 2.5 }
        ],
        "street": "turn",
        "facing_action": null,
        "completed_postflop_streets": [
          {
            "street": "flop",
            "actions": [
              { "actor": "oop", "action": "check", "amount": null },
              { "actor": "ip", "action": "check", "amount": null }
            ]
          }
        ],
        "action_context": "Checked to hero",
        "user_approved": true
      },
      "reference_lines": [
        {
          "action": "check",
          "sizing": null,
          "frequency": 0.4,
          "ev_bb": 4.8
        },
        {
          "action": "bet",
          "sizing": 5.0,
          "frequency": 0.6,
          "ev_bb": 4.9
        }
      ]
    }
  ]
}
```

All values above illustrate the file shape only. The repeated digests, evidence
pointers, rights grants, convergence measurements, and policy values are not
real evidence, license conclusions, benchmark results, or strategy claims.

## Evaluation Rules

- Reference frequencies are strict finite JSON numbers and sum to `1.0` per case.
- `reference_source` records the independent solver or reviewed strategy source.
  Version-1 corpora without provenance or tags and version-2 corpora without
  range-conditioning expectations remain readable. Version-3 corpora without
  range-source expectations and version-4 corpora without grading-reference
  evidence also remain readable; new Phase-0 corpora use version 5. Use
  `--require-reference-source` and `--require-grading-reference` for trusted
  grading-reference runs.
- Schema version 5 requires `grading_reference`. Its reference, policy, and
  tolerance revisions are immutable identities. The SHA-256 fields pin the raw
  source export, the complete source configuration, the normalized policy, the
  economic and utility configurations, the rights evidence, and each
  convergence artifact. All hashes and evidence pointers must refer to retained,
  reviewable artifacts; recording a claim in this file does not establish it.
- Coverage declares every supported dealt-in count and structural position,
  exact effective-stack depth, and street. Each table configuration covers every
  action index and button distance exactly once and enforces its table-size
  display label, including the heads-up button/small-blind special case. Every
  version-5 case supplies its exact `hero_structural_position`; its street,
  decision-time `effective_stack`, dealt-in count, and position must fall inside
  the declared envelope. `players_in_hand` is the number of current survivors,
  so it may be lower than the dealt-in count but cannot exceed it. A populated
  `hero_stack` or `opponent_stack` cannot be below `effective_stack`. When
  `players_in_hand` is exactly 2 and both visible stacks are populated,
  `effective_stack` must equal their exact minimum. Missing visible stacks and
  multiway cases remain valid without an equality inference because the exact
  opponent minimum is not then determined by these two fields. The listed table
  configurations, stacks, and streets define the declared Cartesian coverage
  boundary. Until recommendation providers consume structural position directly,
  the legacy `hero_position` route must agree exactly: `BTN/SB` and
  `BTN` route as `button`, `SB` as `small_blind`, `BB` as `big_blind`, `UTG` as
  `utg`, `HJ` as `hijack`, and `CO` as `cutoff`. Table-specific full-ring labels
  such as `UTG+1`, `LJ`, and combined `*/LJ` labels have no exact legacy route;
  version-5 corpora are rejected instead of coercing them into a nearby policy.
  Versions 1 through 4 retain their legacy behavior. Canonical nine-handed
  positions are `BTN`, `SB`, `BB`, `UTG`, `UTG+1`, `UTG+2`, `LJ`, `HJ`, and
  `CO`; ten-handed adds the distinct `UTG+3` seat before `LJ`. The economic and
  utility models are separately named,
  revisioned, and configuration-digested. `ev_unit` is one of `bb`, `chips`,
  `currency`, or `utility`.
- The current EV scorer consumes only `ev_bb`. A version-5 corpus with a non-BB
  `ev_unit` must omit all `ev_bb` labels; the loader rejects the corpus instead
  of implying a chip, currency, or utility conversion. Extending the scorer to
  generic EV units is separate work.
- Rights evidence selects `shipped_static_lookup` or `server_side_feed`. A
  shipped lookup requires explicit commercial-use, embedding, redistribution,
  and update grants. A server-side feed requires commercial-use, commercial-
  serving, and derived-output grants. Evidence has a retained pointer and
  digest. These declarations cover reference delivery rights only; they do not
  implement remote-provider consent or privacy controls.
- Every convergence entry records a metric, unit, pass direction, threshold,
  observed value, iteration count, and retained evidence pointer/digest. A
  measurement that misses its declared threshold is rejected.
- Lowercase case tags classify scenarios such as `single-raised-pot` and
  `facing-bet`. Reports include deterministic street and tag breakdowns; a case
  may contribute to more than one tag.
- Lines at or above `minimum_policy_frequency` count as supported strategy.
- Action agreement ignores sizing; line agreement uses `sizing_tolerance_bb`.
- The sizing boundary is strict: a difference exactly equal to the tolerance
  is not a match.
- A bet or raise may omit reference sizing for action-only evaluation. Such a
  case is excluded from line accuracy.
- If one line has `ev_bb`, every line in that case must have it. EV loss is the
  best reference EV minus the selected reference line EV.
- Policy distance is total-variation distance and is available only when the
  provider returns a complete valid `raw.candidates` frequency distribution.
  Four-decimal provider frequencies are normalized when their total differs
  from one only by bounded rounding error. Zero-frequency candidates do not
  require sizing because they contribute no policy mass.
- A provider exception or missing required canonical field fails only that case.
- A non-empty `raw.fallback_reason` counts toward fallback rate;
  `routing_reason` does not.
- Turn and river cases may declare `expected_range_conditioning` as `applied` or
  `skipped`. The benchmark compares it with
  `raw.range_conditioning.status`; an absent or malformed status lowers evidence
  coverage, while a recognized wrong status lowers agreement. The conditioning
  accuracy and coverage thresholds make both regressions fail explicitly.
- Flop, turn, and river cases may declare `expected_range_source` as
  `configured` or one of the `preflop_chart_*_pot` sources emitted by the local
  postflop solver. The benchmark compares the exact value with
  `raw.range_source`. A missing, malformed, or unknown source lowers evidence
  coverage; a recognized but incorrect source lowers agreement. Use
  `--minimum-range-source-accuracy` and `--minimum-range-source-coverage` to
  make either regression fail the run.
- Line, policy, and EV coverage report how many completed cases supplied enough
  evidence for each optional metric. Their minimum thresholds prevent missing
  sizes, frequencies, or EV labels from making a partial result look healthy.

The corpus is limited to 1,000 cases and 4 MiB. Unknown fields, coerced schema
versions, duplicate IDs or line identities, partial EV labels, and ambiguous
wager sizes are rejected before the provider is called.
