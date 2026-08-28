import json
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.domain.imported_hands import (
    CashEconomics,
    TournamentEconomics,
    structural_position_labels,
)
from app.domain.poker import Card, PreflopAction
from app.domain.recommendations import RecommendationRequest, RecommendationResult
from app.providers.base import ProviderConfigurationError
from app.providers.registry import build_provider
from app.recommendation_benchmark import (
    MAX_RECOMMENDATION_BENCHMARK_BYTES,
    MAX_RECOMMENDATION_BENCHMARK_REPORT_BYTES,
    RECOMMENDATION_BENCHMARK_SCHEMA,
    RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
    RecommendationBenchmarkCase,
    RecommendationBenchmarkDataset,
    RecommendationBenchmarkError,
    RecommendationBenchmarkReport,
    RecommendationBenchmarkState,
    RecommendationReferenceLine,
    benchmark_recommendation_file,
    format_recommendation_benchmark_report,
    load_recommendation_benchmark_dataset,
    load_recommendation_benchmark_report,
    main,
    recommendation_dataset_fingerprint,
    recommendation_economic_configuration_sha256,
    recommendation_utility_configuration_sha256,
    run_recommendation_benchmark,
    validate_comparable_recommendation_baseline,
)


class SequenceProvider:
    name = "test_solver"
    required_fields = ["hero_cards", "street"]

    def __init__(self, outcomes: list[RecommendationResult | Exception]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[RecommendationRequest] = []

    def required_fields_for(
        self,
        state: RecommendationBenchmarkState,
    ) -> list[str]:
        return self.required_fields

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def benchmark_state(**overrides: object) -> RecommendationBenchmarkState:
    values = {
        "hero_cards": [Card.from_code("Ah"), Card.from_code("Kd")],
        "board_cards": [
            Card.from_code("Qs"),
            Card.from_code("Jc"),
            Card.from_code("2h"),
        ],
        "street": "flop",
        "pot_size": 10.0,
        "current_bet": 0.0,
        "hero_stack": 100.0,
        "effective_stack": 100.0,
        "players_in_hand": 2,
        "hero_position": "button",
        "utility_model": case_utility_model_evidence(),
    }
    values.update(overrides)
    return RecommendationBenchmarkState.model_validate(values)


def reference_line(
    action: str,
    *,
    sizing: float | None = None,
    frequency: float = 1.0,
    ev_bb: float | None = None,
) -> RecommendationReferenceLine:
    return RecommendationReferenceLine.model_validate(
        {
            "action": action,
            "sizing": sizing,
            "frequency": frequency,
            "ev_bb": ev_bb,
        }
    )


def benchmark_case(
    case_id: str,
    lines: list[RecommendationReferenceLine],
    *,
    tags: list[str] | None = None,
    expected_range_conditioning: Literal["applied", "skipped"] | None = None,
    expected_range_source: str | None = None,
    **state_overrides: object,
) -> RecommendationBenchmarkCase:
    return RecommendationBenchmarkCase(
        id=case_id,
        description=f"Reference case {case_id}",
        tags=tags or [],
        state=benchmark_state(**state_overrides),
        expected_range_conditioning=expected_range_conditioning,
        expected_range_source=expected_range_source,
        reference_lines=lines,
    )


def benchmark_dataset(
    cases: list[RecommendationBenchmarkCase],
    **overrides: object,
) -> RecommendationBenchmarkDataset:
    values = {
        "schema": RECOMMENDATION_BENCHMARK_SCHEMA,
        # Most scoring tests exercise the still-supported v4 contract. Focused
        # tests below opt into the evidence-complete v5 contract explicitly.
        "schema_version": 4,
        "name": "Trusted solver sample",
        "sizing_tolerance_bb": 0.01,
        "minimum_policy_frequency": 0.05,
        "cases": cases,
    }
    values.update(overrides)
    return RecommendationBenchmarkDataset.model_validate(values)


def covered_preflop_case(
    case_id: str = "covered-preflop",
) -> RecommendationBenchmarkCase:
    return benchmark_case(
        case_id,
        [reference_line("check", ev_bb=0.4)],
        street="preflop",
        board_cards=[],
        effective_stack=100.0,
        players_in_hand=2,
        economic_model=case_economic_model_evidence(),
        hero_structural_position={
            "dealt_in_player_count": 2,
            "action_index": 0,
            "button_distance": 0,
            "display_label": "BTN/SB",
        },
    )


def covered_heads_up_postflop_case(
    case_id: str = "covered-heads-up-postflop",
    **state_overrides: object,
) -> RecommendationBenchmarkCase:
    values: dict[str, object] = {
        "opponent_position": "big_blind",
        "economic_model": case_economic_model_evidence(),
        "hero_structural_position": {
            "dealt_in_player_count": 2,
            "action_index": 0,
            "button_distance": 0,
            "display_label": "BTN/SB",
        },
    }
    values.update(state_overrides)
    return benchmark_case(case_id, [reference_line("check")], **values)


def cash_economic_configuration(
    *,
    currency: str = "USD",
    rake_percentage: str = "0",
    rake_cap: str = "0",
    fixed_drop: str = "0",
) -> CashEconomics:
    return CashEconomics.model_validate(
        {
            "kind": "cash",
            "currency": currency,
            "rake": {
                "percentage": Decimal(rake_percentage),
                "cap": Decimal(rake_cap),
                "fixed_drop": Decimal(fixed_drop),
            },
        }
    )


def tournament_economic_configuration(
    *,
    no_bounties: bool = False,
) -> TournamentEconomics:
    bounty_format = "none" if no_bounties else "progressive"
    hero_bounty = Decimal("0") if no_bounties else Decimal("25")
    villain_bounty = Decimal("0") if no_bounties else Decimal("40")
    return TournamentEconomics.model_validate(
        {
            "kind": "tournament",
            "tournament_id": "tournament-42",
            "tournament_type": "progressive-knockout",
            "stage": "heads-up-final-table",
            "currency": "USD",
            "paid_places": 2,
            "players_remaining": 2,
            "payouts": [
                {
                    "place_from": 1,
                    "place_to": 1,
                    "amount": Decimal("100"),
                },
                {
                    "place_from": 2,
                    "place_to": 2,
                    "amount": Decimal("50"),
                },
            ],
            "remaining_stacks": [
                {"player_id": "hero", "stack": Decimal("5000")},
                {"player_id": "villain", "stack": Decimal("3000")},
            ],
            "bounty_format": bounty_format,
            "bounties": [
                {"player_id": "hero", "value": hero_bounty},
                {"player_id": "villain", "value": villain_bounty},
            ],
            "icm_inputs_complete": True,
        }
    )


def case_economic_model_evidence(
    *,
    name: str = "heads-up-no-rake",
    revision: str = "economics-1",
    configuration: CashEconomics | TournamentEconomics | None = None,
    configuration_sha256: str | None = None,
) -> dict[str, object]:
    economic_configuration = configuration or cash_economic_configuration()
    return {
        "kind": economic_configuration.kind,
        "name": name,
        "revision": revision,
        "configuration_sha256": configuration_sha256
        or recommendation_economic_configuration_sha256(economic_configuration),
        "configuration": economic_configuration,
    }


def case_utility_model_evidence(
    *,
    name: str = "cash-expected-value",
    revision: str = "utility-1",
    configuration: dict[str, Any] | None = None,
    configuration_sha256: str | None = None,
) -> dict[str, object]:
    utility_configuration = configuration or {
        "objective": "cash_expected_value"
    }
    return {
        "name": name,
        "revision": revision,
        "configuration_sha256": configuration_sha256
        or recommendation_utility_configuration_sha256(utility_configuration),
        "configuration": utility_configuration,
    }


def grading_reference_evidence(
    *,
    ev_unit: str = "bb",
    delivery_mode: str = "shipped_static_lookup",
) -> dict[str, Any]:
    grants = (
        ["commercial_use", "embedding", "redistribution", "updates"]
        if delivery_mode == "shipped_static_lookup"
        else ["commercial_use", "commercial_serving", "derived_outputs"]
    )
    return {
        "reference_revision": "reference-2026.08",
        "policy_revision": "policy-2026.08.1",
        "tolerance_revision": "tolerance-1",
        "source_artifact_sha256": "1" * 64,
        "source_configuration_sha256": "2" * 64,
        "policy_artifact_sha256": "3" * 64,
        "coverage": {
            "table_configurations": [
                {
                    "dealt_in_count": 2,
                    "structural_positions": [
                        {
                            "action_index": 0,
                            "button_distance": 0,
                            "display_label": "BTN/SB",
                        },
                        {
                            "action_index": 1,
                            "button_distance": 1,
                            "display_label": "BB",
                        },
                    ],
                }
            ],
            "effective_stack_depths_bb": [50.0, 100.0],
            "streets": ["preflop"],
        },
        "economic_model": case_economic_model_evidence(),
        "utility_model": case_utility_model_evidence(),
        "ev_unit": ev_unit,
        "rights_evidence": {
            "basis": "licensed",
            "delivery_mode": delivery_mode,
            "grants": grants,
            "evidence_pointer": "evidence/reference-rights-review.md",
            "evidence_sha256": "6" * 64,
        },
        "convergence_evidence": [
            {
                "metric": "exploitability",
                "unit": "bb_per_100",
                "comparison": "at_most",
                "threshold": 0.02,
                "observed": 0.01,
                "iterations": 250000,
                "evidence_pointer": "evidence/convergence-report.json",
                "evidence_sha256": "7" * 64,
            }
        ],
    }


def reference_table_configuration(dealt_in_count: int) -> dict[str, object]:
    action_order_distances = (
        [0, 1]
        if dealt_in_count == 2
        else [*range(3, dealt_in_count), 0, 1, 2]
    )
    action_index_by_distance = {
        distance: index for index, distance in enumerate(action_order_distances)
    }
    return {
        "dealt_in_count": dealt_in_count,
        "structural_positions": [
            {
                "action_index": action_index_by_distance[button_distance],
                "button_distance": button_distance,
                "display_label": display_label,
            }
            for button_distance, display_label in enumerate(
                structural_position_labels(dealt_in_count)
            )
        ],
    }


def grading_reference_for_table_counts(*dealt_in_counts: int) -> dict[str, Any]:
    evidence = grading_reference_evidence()
    evidence["coverage"]["table_configurations"] = [
        reference_table_configuration(count) for count in dealt_in_counts
    ]
    return evidence


def postflop_grading_reference_for_table_counts(
    *dealt_in_counts: int,
) -> dict[str, Any]:
    evidence = grading_reference_for_table_counts(*dealt_in_counts)
    evidence["coverage"]["streets"] = ["flop", "turn", "river"]
    return evidence


def tournament_benchmark_dataset(
    configuration: TournamentEconomics,
) -> RecommendationBenchmarkDataset:
    economic_model = case_economic_model_evidence(
        configuration=configuration,
        name="final-table-icm-with-bounties",
        revision="tournament-economics-7",
    )
    case = covered_preflop_case().model_copy(deep=True)
    state_payload = case.state.model_dump()
    state_payload["economic_model"] = economic_model
    case.state = RecommendationBenchmarkState.model_validate(state_payload)
    case.reference_lines[0].ev_bb = None
    reference = grading_reference_evidence(ev_unit="utility")
    reference["economic_model"] = economic_model
    return benchmark_dataset(
        [case],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=reference,
    )


def recommendation(
    action: str,
    *,
    sizing: float | None = None,
    candidates: list[dict[str, object]] | None = None,
    fallback_reason: str | None = None,
    range_conditioning: object | None = None,
    range_source: object | None = None,
) -> RecommendationResult:
    raw: dict[str, object] = {"engine": "reference_test_v1"}
    if candidates is not None:
        raw["candidates"] = candidates
    if fallback_reason is not None:
        raw["fallback_reason"] = fallback_reason
    if range_conditioning is not None:
        raw["range_conditioning"] = range_conditioning
    if range_source is not None:
        raw["range_source"] = range_source
    return RecommendationResult.model_validate(
        {
            "action": action,
            "sizing": sizing,
            "confidence": 0.8,
            "explanation": "Test recommendation.",
            "raw": raw,
        }
    )


def write_dataset(path: Path, dataset: RecommendationBenchmarkDataset) -> Path:
    path.write_text(dataset.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    return path


def write_report(path: Path, report: RecommendationBenchmarkReport) -> Path:
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def test_recommendation_dataset_fingerprint_tracks_scoring_inputs() -> None:
    first = benchmark_case(
        "first",
        [
            reference_line("check", frequency=0.4),
            reference_line("bet", sizing=5.0, frequency=0.6),
        ],
        tags=["single-raised-pot", "flop"],
    )
    second = benchmark_case("second", [reference_line("fold")])
    dataset = benchmark_dataset([first, second])
    baseline = recommendation_dataset_fingerprint(dataset)

    reordered = dataset.model_copy(deep=True)
    reordered.cases.reverse()
    reordered.cases[1].tags.reverse()
    reordered.cases[1].reference_lines.reverse()
    reordered.cases[1].description = "Updated review note"
    reordered.name = "Updated display name"
    changed = dataset.model_copy(deep=True)
    changed.cases[0].state.pot_size = 11.0

    assert recommendation_dataset_fingerprint(reordered) == baseline
    assert recommendation_dataset_fingerprint(changed) != baseline


def test_schema_five_propagates_grading_reference_and_fingerprints_evidence() -> None:
    dataset = benchmark_dataset(
        [covered_preflop_case("preflop-check")],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={
            "name": "Independent solver export",
            "version": "2026.08",
            "configuration": "Heads-up cash, no rake",
        },
        grading_reference=grading_reference_evidence(),
    )
    baseline_fingerprint = recommendation_dataset_fingerprint(dataset)
    reordered = dataset.model_copy(deep=True)
    assert reordered.grading_reference is not None
    reordered.grading_reference.coverage.effective_stack_depths_bb.reverse()
    reordered.grading_reference.coverage.table_configurations[0].structural_positions.reverse()
    reordered.grading_reference.rights_evidence.grants.reverse()
    changed = dataset.model_copy(deep=True)
    assert changed.grading_reference is not None
    changed.grading_reference.source_configuration_sha256 = "8" * 64
    changed_source = dataset.model_copy(deep=True)
    assert changed_source.grading_reference is not None
    changed_source.grading_reference.source_artifact_sha256 = "9" * 64
    changed_rights = dataset.model_copy(deep=True)
    assert changed_rights.grading_reference is not None
    changed_rights.grading_reference.rights_evidence.evidence_sha256 = "a" * 64
    changed_case_economics = dataset.model_copy(deep=True)
    assert changed_case_economics.cases[0].state.economic_model is not None
    assert changed_case_economics.cases[0].state.economic_model.kind == "cash"
    changed_case_economics.cases[0].state.economic_model.configuration_sha256 = (
        "b" * 64
    )

    report = run_recommendation_benchmark(
        dataset,
        SequenceProvider([recommendation("check")]),
    )

    assert recommendation_dataset_fingerprint(reordered) == baseline_fingerprint
    assert recommendation_dataset_fingerprint(changed) != baseline_fingerprint
    assert (
        recommendation_dataset_fingerprint(changed_source) != baseline_fingerprint
    )
    assert (
        recommendation_dataset_fingerprint(changed_rights) != baseline_fingerprint
    )
    assert (
        recommendation_dataset_fingerprint(changed_case_economics)
        != baseline_fingerprint
    )
    assert report.grading_reference == dataset.grading_reference
    formatted = format_recommendation_benchmark_report(report)
    assert "policy=policy-2026.08.1" in formatted
    assert f"configuration={'2' * 64}" in formatted
    assert (
        "Table coverage: 2-handed (BTN/SB[action=0,button-distance=0], "
        "BB[action=1,button-distance=1])" in formatted
    )
    assert "EV unit=bb" in formatted
    assert "licensed/shipped_static_lookup" in formatted
    assert "exploitability 0.01 bb_per_100 <= 0.02" in formatted


@pytest.mark.parametrize(
    ("utility_model", "message"),
    [
        (None, "requires a utility_model"),
        (
            case_utility_model_evidence(name="tournament-icm"),
            "utility_model.name 'tournament-icm'.*declared.*'cash-expected-value'",
        ),
        (
            case_utility_model_evidence(revision="utility-2"),
            "utility_model.revision 'utility-2'.*declared.*'utility-1'",
        ),
        (
            case_utility_model_evidence(
                configuration={"objective": "tournament_icm"}
            ),
            "utility_model.configuration_sha256.*does not match declared",
        ),
    ],
)
def test_schema_five_requires_each_case_to_match_the_declared_utility_model(
    utility_model: dict[str, object] | None,
    message: str,
) -> None:
    case = covered_preflop_case().model_copy(deep=True)
    state_payload = case.state.model_dump()
    state_payload["utility_model"] = utility_model
    case.state = RecommendationBenchmarkState.model_validate(state_payload)

    with pytest.raises(ValidationError, match=message):
        benchmark_dataset(
            [case],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=grading_reference_evidence(),
        )


def test_utility_model_rejects_material_config_mutation_with_stale_digest() -> None:
    payload = case_utility_model_evidence()
    configuration = payload["configuration"]
    assert isinstance(configuration, dict)
    configuration["risk_adjustment"] = "icm"

    with pytest.raises(
        ValidationError,
        match="configuration_sha256 must match its normalized route-critical",
    ):
        RecommendationBenchmarkState.model_validate({"utility_model": payload})


def test_utility_configuration_hash_normalizes_json_object_and_number_forms(
) -> None:
    concise = {
        "objective": "cash_expected_value",
        "parameters": {"weight": 1, "offset": 0},
    }
    reordered = {
        "parameters": {"offset": -0.0, "weight": 1.0},
        "objective": "cash_expected_value",
    }

    assert recommendation_utility_configuration_sha256(
        concise
    ) == recommendation_utility_configuration_sha256(reordered)


def test_schema_five_routes_exact_utility_context_to_the_provider() -> None:
    dataset = benchmark_dataset(
        [covered_preflop_case()],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=grading_reference_evidence(),
    )
    provider = SequenceProvider([recommendation("check")])

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    request_state = provider.requests[0].model_dump(mode="json")["state"]
    assert request_state["utility_model"] == (
        dataset.cases[0].state.utility_model.model_dump(mode="json")
    )
    assert request_state["economic_model"] is not None
    assert request_state["hero_structural_position"] is not None


def test_schema_five_revalidates_utility_binding_before_provider_execution() -> None:
    dataset = benchmark_dataset(
        [covered_preflop_case()],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=grading_reference_evidence(),
    )
    utility_model = dataset.cases[0].state.utility_model
    assert utility_model is not None
    utility_model.name = "mutated-after-load"
    provider = SequenceProvider([recommendation("check")])

    report = run_recommendation_benchmark(dataset, provider)

    assert report.failed_cases == 1
    assert report.cases[0].error is not None
    assert "utility_model.name" in report.cases[0].error
    assert provider.requests == []
    assert len(provider.outcomes) == 1


def test_schema_five_utility_mismatch_fails_before_file_provider_execution(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [covered_preflop_case()],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=grading_reference_evidence(),
    )
    payload = dataset.model_dump(mode="json", by_alias=True)
    payload["cases"][0]["state"]["utility_model"]["configuration"][
        "objective"
    ] = "tournament_icm"
    path = tmp_path / "mismatched-utility-model.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    provider = SequenceProvider([recommendation("check")])

    with pytest.raises(RecommendationBenchmarkError, match="utility_model"):
        benchmark_recommendation_file(
            path,
            Settings(data_dir=tmp_path / "unused"),
            provider,
        )

    assert provider.requests == []
    assert len(provider.outcomes) == 1


def test_utility_binding_is_fingerprinted_and_order_normalized() -> None:
    baseline = benchmark_dataset(
        [covered_preflop_case()],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=grading_reference_evidence(),
    )
    reordered = baseline.model_copy(deep=True)
    changed = baseline.model_copy(deep=True)
    assert reordered.grading_reference is not None
    reordered_models = (
        reordered.grading_reference.utility_model,
        reordered.cases[0].state.utility_model,
    )
    for model in reordered_models:
        assert model is not None
        model.configuration = dict(reversed(model.configuration.items()))

    assert changed.grading_reference is not None
    changed_models = (
        changed.grading_reference.utility_model,
        changed.cases[0].state.utility_model,
    )
    for model in changed_models:
        assert model is not None
        model.configuration["risk_adjustment"] = "none"
        model.configuration_sha256 = recommendation_utility_configuration_sha256(
            model.configuration
        )

    assert recommendation_dataset_fingerprint(
        reordered
    ) == recommendation_dataset_fingerprint(baseline)
    assert recommendation_dataset_fingerprint(
        changed
    ) != recommendation_dataset_fingerprint(baseline)
    baseline_report = run_recommendation_benchmark(
        baseline,
        SequenceProvider([recommendation("check")]),
    )
    changed_report = run_recommendation_benchmark(
        changed,
        SequenceProvider([recommendation("check")]),
    )
    with pytest.raises(
        RecommendationBenchmarkError,
        match="baseline corpus does not match",
    ):
        validate_comparable_recommendation_baseline(
            changed_report,
            baseline_report,
        )


@pytest.mark.parametrize(
    ("economic_model", "message"),
    [
        (None, "requires an economic_model"),
        (
            {"kind": "unknown", "reason": "source omitted tournament context"},
            "economic_model is unknown",
        ),
        (
            case_economic_model_evidence(
                configuration=tournament_economic_configuration(),
                name="final-table-icm-with-bounties",
                revision="tournament-economics-7",
            ),
            "economic_model.kind 'tournament'.*declared.*'cash'",
        ),
        (
            case_economic_model_evidence(name="different-rake-model"),
            "economic_model.name 'different-rake-model'.*declared.*'heads-up-no-rake'",
        ),
        (
            case_economic_model_evidence(revision="economics-2"),
            "economic_model.revision 'economics-2'.*declared.*'economics-1'",
        ),
        (
            case_economic_model_evidence(
                configuration=cash_economic_configuration(
                    currency="EUR",
                    rake_percentage="0.05",
                    rake_cap="4",
                    fixed_drop="1",
                )
            ),
            "economic_model.configuration_sha256.*does not match declared",
        ),
    ],
)
def test_schema_five_requires_each_case_to_match_the_declared_economic_model(
    economic_model: dict[str, object] | None,
    message: str,
) -> None:
    case = covered_preflop_case().model_copy(deep=True)
    state_payload = case.state.model_dump()
    state_payload["economic_model"] = economic_model
    case.state = RecommendationBenchmarkState.model_validate(state_payload)

    with pytest.raises(ValidationError, match=message):
        benchmark_dataset(
            [case],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=grading_reference_evidence(),
        )


def test_schema_five_accepts_an_exact_tournament_economic_model_binding() -> None:
    tournament_model = case_economic_model_evidence(
        configuration=tournament_economic_configuration(),
        name="final-table-icm-with-bounties",
        revision="tournament-economics-7",
    )
    case = covered_preflop_case().model_copy(deep=True)
    state_payload = case.state.model_dump()
    state_payload["economic_model"] = tournament_model
    case.state = RecommendationBenchmarkState.model_validate(state_payload)
    case.reference_lines[0].ev_bb = None
    reference = grading_reference_evidence(ev_unit="utility")
    reference["economic_model"] = tournament_model

    dataset = benchmark_dataset(
        [case],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=reference,
    )

    assert dataset.cases[0].state.economic_model is not None
    assert dataset.cases[0].state.economic_model.kind == "tournament"


def test_economic_model_rejects_material_config_mutation_with_stale_digest() -> None:
    payload = case_economic_model_evidence()
    configuration = payload["configuration"]
    assert isinstance(configuration, CashEconomics)
    assert configuration.rake is not None
    configuration.rake.cap = Decimal("4")

    with pytest.raises(
        ValidationError,
        match="configuration_sha256 must match its normalized route-critical",
    ):
        RecommendationBenchmarkState.model_validate({"economic_model": payload})


def test_economic_model_digest_normalizes_equivalent_decimal_representations() -> None:
    baseline = cash_economic_configuration()
    equivalent = cash_economic_configuration(
        rake_percentage="-0.000",
        rake_cap="0.00",
        fixed_drop="0E+3",
    )

    assert recommendation_economic_configuration_sha256(
        equivalent
    ) == recommendation_economic_configuration_sha256(baseline)


def test_economic_model_rejects_incomplete_route_critical_configuration() -> None:
    missing_cash_value = cash_economic_configuration()
    assert missing_cash_value.rake is not None
    missing_cash_value.rake.fixed_drop = None
    incomplete_icm = tournament_economic_configuration()
    incomplete_icm.icm_inputs_complete = False

    for configuration, missing_field in (
        (missing_cash_value, "rake.fixed_drop"),
        (incomplete_icm, "icm_inputs_complete"),
    ):
        with pytest.raises(ValidationError, match=missing_field):
            RecommendationBenchmarkState.model_validate(
                {
                    "economic_model": case_economic_model_evidence(
                        configuration=configuration
                    )
                }
            )


def test_schema_five_rejects_distinct_valid_case_and_reference_economics() -> None:
    case = covered_preflop_case().model_copy(deep=True)
    state_payload = case.state.model_dump()
    state_payload["economic_model"] = case_economic_model_evidence(
        configuration=cash_economic_configuration(
            currency="EUR",
            rake_percentage="0.05",
            rake_cap="4",
            fixed_drop="1",
        )
    )
    case.state = RecommendationBenchmarkState.model_validate(state_payload)

    with pytest.raises(
        ValidationError,
        match="economic_model.configuration_sha256.*does not match declared",
    ):
        benchmark_dataset(
            [case],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=grading_reference_evidence(),
        )


def test_schema_five_normalizes_tournament_economic_collection_order() -> None:
    reference_configuration = tournament_economic_configuration()
    case_configuration = reference_configuration.model_copy(deep=True)
    case_configuration.payouts.reverse()
    case_configuration.remaining_stacks.reverse()
    case_configuration.bounties.reverse()
    assert recommendation_economic_configuration_sha256(
        case_configuration
    ) == recommendation_economic_configuration_sha256(reference_configuration)
    model_values = {
        "name": "final-table-icm-with-bounties",
        "revision": "tournament-economics-7",
    }
    case = covered_preflop_case().model_copy(deep=True)
    state_payload = case.state.model_dump()
    state_payload["economic_model"] = case_economic_model_evidence(
        configuration=case_configuration,
        **model_values,
    )
    case.state = RecommendationBenchmarkState.model_validate(state_payload)
    case.reference_lines[0].ev_bb = None
    reference = grading_reference_evidence(ev_unit="utility")
    reference["economic_model"] = case_economic_model_evidence(
        configuration=reference_configuration,
        **model_values,
    )

    dataset = benchmark_dataset(
        [case],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=reference,
    )

    assert dataset.cases[0].state.economic_model is not None


def test_fingerprint_normalizes_case_and_reference_tournament_collection_order(
) -> None:
    baseline = tournament_benchmark_dataset(tournament_economic_configuration())
    reordered = baseline.model_copy(deep=True)
    assert reordered.grading_reference is not None
    reordered_reference = reordered.grading_reference.economic_model.configuration
    reordered_case_model = reordered.cases[0].state.economic_model
    assert isinstance(reordered_reference, TournamentEconomics)
    assert (
        reordered_case_model is not None
        and reordered_case_model.kind == "tournament"
    )
    assert isinstance(reordered_case_model.configuration, TournamentEconomics)
    for configuration in (
        reordered_reference,
        reordered_case_model.configuration,
    ):
        configuration.payouts.reverse()
        configuration.remaining_stacks.reverse()
        configuration.bounties.reverse()

    assert recommendation_dataset_fingerprint(
        reordered
    ) == recommendation_dataset_fingerprint(baseline)
    baseline_report = run_recommendation_benchmark(
        baseline,
        SequenceProvider([recommendation("check")]),
    )
    reordered_report = run_recommendation_benchmark(
        reordered,
        SequenceProvider([recommendation("check")]),
    )
    validate_comparable_recommendation_baseline(reordered_report, baseline_report)


def test_fingerprint_and_comparability_track_material_tournament_economic_changes(
) -> None:
    baseline = tournament_benchmark_dataset(tournament_economic_configuration())
    changed_configuration = tournament_economic_configuration()
    changed_configuration.bounties[0].value = Decimal("26")
    changed = tournament_benchmark_dataset(changed_configuration)

    assert recommendation_dataset_fingerprint(
        changed
    ) != recommendation_dataset_fingerprint(baseline)
    baseline_report = run_recommendation_benchmark(
        baseline,
        SequenceProvider([recommendation("check")]),
    )
    changed_report = run_recommendation_benchmark(
        changed,
        SequenceProvider([recommendation("check")]),
    )
    with pytest.raises(
        RecommendationBenchmarkError,
        match="baseline corpus does not match",
    ):
        validate_comparable_recommendation_baseline(changed_report, baseline_report)


def test_economic_configuration_hash_normalizes_decimal_representation() -> None:
    concise = cash_economic_configuration(
        rake_percentage="0.05",
        rake_cap="4",
        fixed_drop="1",
    )
    padded = cash_economic_configuration(
        rake_percentage="0.0500",
        rake_cap="4.000",
        fixed_drop="1.00",
    )

    assert recommendation_economic_configuration_sha256(
        concise
    ) == recommendation_economic_configuration_sha256(padded)


def test_schema_five_accepts_explicit_no_bounty_tournament_economics() -> None:
    configuration = tournament_economic_configuration(no_bounties=True)
    tournament_model = case_economic_model_evidence(
        configuration=configuration,
        name="final-table-icm-no-bounties",
        revision="tournament-economics-8",
    )
    case = covered_preflop_case().model_copy(deep=True)
    state_payload = case.state.model_dump()
    state_payload["economic_model"] = tournament_model
    case.state = RecommendationBenchmarkState.model_validate(state_payload)
    case.reference_lines[0].ev_bb = None
    reference = grading_reference_evidence(ev_unit="utility")
    reference["economic_model"] = tournament_model

    dataset = benchmark_dataset(
        [case],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=reference,
    )

    economic_model = dataset.cases[0].state.economic_model
    assert economic_model is not None and economic_model.kind == "tournament"
    assert isinstance(economic_model.configuration, TournamentEconomics)
    assert economic_model.configuration.bounty_format == "none"
    assert {bounty.value for bounty in economic_model.configuration.bounties} == {
        Decimal("0")
    }


def test_economic_model_rejects_nonzero_no_bounty_values() -> None:
    configuration = tournament_economic_configuration(no_bounties=True)
    configuration.bounties[0].value = Decimal("1")

    with pytest.raises(ValidationError, match="requires explicit zero bounty values"):
        RecommendationBenchmarkState.model_validate(
            {
                "economic_model": case_economic_model_evidence(
                    configuration=configuration,
                    name="invalid-no-bounty-model",
                )
            }
        )


def test_schema_five_economic_model_mismatch_fails_before_provider_execution(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [covered_preflop_case()],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=grading_reference_evidence(),
    )
    payload = dataset.model_dump(mode="json", by_alias=True)
    payload["cases"][0]["state"]["economic_model"]["configuration"]["rake"][
        "cap"
    ] = 4
    path = tmp_path / "mismatched-economic-model.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    provider = SequenceProvider([recommendation("check")])

    with pytest.raises(RecommendationBenchmarkError, match="economic_model"):
        benchmark_recommendation_file(
            path,
            Settings(data_dir=tmp_path / "unused"),
            provider,
        )

    assert len(provider.outcomes) == 1


@pytest.mark.parametrize(
    ("state_overrides", "message"),
    [
        (
            {
                "street": "flop",
                "board_cards": [
                    Card.from_code("Qs"),
                    Card.from_code("Jc"),
                    Card.from_code("2h"),
                ],
            },
            "street 'flop' is outside declared",
        ),
        ({"street": None, "board_cards": []}, "street None is outside declared"),
        ({"effective_stack": 99.999}, "effective stack 99.999 BB is outside"),
        ({"effective_stack": None}, "requires an effective stack"),
        ({"hero_structural_position": None}, "requires a structural position"),
        (
            {
                "hero_structural_position": {
                    "dealt_in_player_count": 3,
                    "action_index": 0,
                    "button_distance": 0,
                    "display_label": "BTN",
                }
            },
            "dealt-in count 3 is outside declared",
        ),
        ({"players_in_hand": 3}, "players_in_hand must be between 2"),
        (
            {"board_cards": [Card.from_code("Qs")]},
            "board does not match its declared street",
        ),
    ],
)
def test_schema_five_cases_must_fit_declared_grading_coverage(
    state_overrides: dict[str, object],
    message: str,
) -> None:
    case = covered_preflop_case().model_copy(deep=True)
    state_payload = case.state.model_dump()
    state_payload.update(state_overrides)
    case.state = RecommendationBenchmarkState.model_validate(state_payload)

    with pytest.raises(ValidationError, match=message):
        benchmark_dataset(
            [case],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=grading_reference_evidence(),
        )


@pytest.mark.parametrize(
    ("hero_stack", "opponent_stack"),
    [
        (100.0, 100.0),
        (100.0, 150.0),
        (150.0, 100.0),
        (100.0, None),
        (None, 100.0),
        (None, None),
    ],
)
def test_schema_five_accepts_consistent_heads_up_and_partial_visible_stacks(
    hero_stack: float | None,
    opponent_stack: float | None,
) -> None:
    case = covered_preflop_case().model_copy(deep=True)
    case.state.hero_stack = hero_stack
    case.state.opponent_stack = opponent_stack

    dataset = benchmark_dataset(
        [case],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=grading_reference_evidence(),
    )

    assert dataset.cases[0].state.effective_stack == 100.0


@pytest.mark.parametrize(
    ("field_name", "hero_stack", "opponent_stack"),
    [
        ("hero_stack", 99.999, None),
        ("opponent_stack", None, 99.999),
        ("hero_stack", 0.0, 100.0),
        ("opponent_stack", 100.0, 0.0),
    ],
)
def test_schema_five_rejects_a_visible_stack_below_the_effective_depth(
    field_name: str,
    hero_stack: float | None,
    opponent_stack: float | None,
) -> None:
    case = covered_preflop_case().model_copy(deep=True)
    case.state.hero_stack = hero_stack
    case.state.opponent_stack = opponent_stack

    with pytest.raises(
        ValidationError,
        match=rf"{field_name} .* BB is below effective stack 100 BB",
    ):
        benchmark_dataset(
            [case],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=grading_reference_evidence(),
        )


def test_schema_five_requires_the_exact_visible_minimum_for_heads_up_stacks() -> None:
    case = covered_preflop_case().model_copy(deep=True)
    case.state.hero_stack = 150.0
    case.state.opponent_stack = 120.0

    with pytest.raises(
        ValidationError,
        match="heads-up effective stack 100 BB does not equal.*minimum 120",
    ):
        benchmark_dataset(
            [case],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=grading_reference_evidence(),
        )


@pytest.mark.parametrize(
    ("opponent_stack", "valid"),
    [(120.0, True), (None, True), (99.0, False)],
)
def test_schema_five_multiway_stacks_require_only_visible_lower_bounds(
    opponent_stack: float | None,
    valid: bool,
) -> None:
    table = reference_table_configuration(3)
    structural = table["structural_positions"][0]
    case = benchmark_case(
        "multiway-partial-stacks",
        [reference_line("check")],
        street="preflop",
        board_cards=[],
        effective_stack=100.0,
        hero_stack=150.0,
        opponent_stack=opponent_stack,
        players_in_hand=3,
        economic_model=case_economic_model_evidence(),
        hero_position="button",
        hero_structural_position={
            "dealt_in_player_count": 3,
            **structural,
        },
    )

    if valid:
        dataset = benchmark_dataset(
            [case],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=grading_reference_for_table_counts(3),
        )

        assert dataset.cases[0].state.players_in_hand == 3
    else:
        with pytest.raises(ValidationError, match="opponent_stack .* is below"):
            benchmark_dataset(
                [case],
                schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
                reference_source={"name": "Independent solver export"},
                grading_reference=grading_reference_for_table_counts(3),
            )


def test_schema_five_stack_mismatch_fails_before_provider_execution(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [covered_preflop_case()],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=grading_reference_evidence(),
    )
    payload = dataset.model_dump(mode="json", by_alias=True)
    payload["cases"][0]["state"]["hero_stack"] = 99.0
    path = tmp_path / "mismatched-stack.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    provider = SequenceProvider([recommendation("check")])

    with pytest.raises(RecommendationBenchmarkError, match="hero_stack"):
        benchmark_recommendation_file(
            path,
            Settings(data_dir=tmp_path / "unused"),
            provider,
        )

    assert len(provider.outcomes) == 1


@pytest.mark.parametrize(
    ("dealt_in_count", "button_distance", "hero_position"),
    [
        (2, 0, "dealer"),
        (6, 0, "btn"),
        (6, 1, "small blind"),
        (6, 2, "BB"),
        (6, 3, "under the gun"),
        (6, 4, "middle position"),
        (6, 5, "co"),
    ],
)
def test_schema_five_accepts_exact_legacy_routes_for_structural_positions(
    dealt_in_count: int,
    button_distance: int,
    hero_position: str,
) -> None:
    table = reference_table_configuration(dealt_in_count)
    structural = table["structural_positions"][button_distance]
    case = benchmark_case(
        f"route-{dealt_in_count}-{button_distance}",
        [reference_line("check")],
        street="preflop",
        board_cards=[],
        effective_stack=100.0,
        players_in_hand=2,
        economic_model=case_economic_model_evidence(),
        hero_position=hero_position,
        hero_structural_position={
            "dealt_in_player_count": dealt_in_count,
            **structural,
        },
    )

    dataset = benchmark_dataset(
        [case],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=grading_reference_for_table_counts(dealt_in_count),
    )

    assert dataset.cases[0].state.hero_position == hero_position


def test_schema_five_exact_legacy_routes_cover_every_representable_table_position(
) -> None:
    expected_legacy_position = {
        "BTN/SB": "button",
        "BTN": "button",
        "SB": "small_blind",
        "BB": "big_blind",
        "UTG": "utg",
        "HJ": "hijack",
        "CO": "cutoff",
    }
    cases: list[RecommendationBenchmarkCase] = []
    for dealt_in_count in range(2, 11):
        table = reference_table_configuration(dealt_in_count)
        for structural in table["structural_positions"]:
            hero_position = expected_legacy_position.get(
                structural["display_label"]
            )
            if hero_position is None:
                continue
            cases.append(
                benchmark_case(
                    f"route-{dealt_in_count}-{structural['button_distance']}",
                    [reference_line("check")],
                    street="preflop",
                    board_cards=[],
                    effective_stack=100.0,
                    players_in_hand=2,
                    economic_model=case_economic_model_evidence(),
                    hero_position=hero_position,
                    hero_structural_position={
                        "dealt_in_player_count": dealt_in_count,
                        **structural,
                    },
                )
            )

    dataset = benchmark_dataset(
        cases,
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=grading_reference_for_table_counts(*range(2, 11)),
    )

    assert len(dataset.cases) == 44


@pytest.mark.parametrize("hero_position", ["big_blind", "small_blind", "lojack", None])
def test_schema_five_rejects_a_legacy_route_that_disagrees_with_heads_up_button(
    hero_position: str | None,
) -> None:
    case = covered_preflop_case().model_copy(deep=True)
    case.state.hero_position = hero_position

    with pytest.raises(
        ValidationError,
        match="structural position 'BTN/SB' at 2-handed requires 'button'",
    ):
        benchmark_dataset(
            [case],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=grading_reference_evidence(),
        )


@pytest.mark.parametrize(
    ("dealt_in_count", "button_distance", "hero_position"),
    [
        (6, 0, "small_blind"),
        (6, 1, "button"),
        (6, 2, "button"),
        (6, 3, "hijack"),
        (6, 4, "cutoff"),
        (6, 5, "button"),
    ],
)
def test_schema_five_rejects_mismatched_routes_for_every_exact_legacy_position(
    dealt_in_count: int,
    button_distance: int,
    hero_position: str,
) -> None:
    table = reference_table_configuration(dealt_in_count)
    structural = table["structural_positions"][button_distance]
    case = benchmark_case(
        f"mismatch-{button_distance}",
        [reference_line("check")],
        street="preflop",
        board_cards=[],
        effective_stack=100.0,
        players_in_hand=2,
        economic_model=case_economic_model_evidence(),
        hero_position=hero_position,
        hero_structural_position={
            "dealt_in_player_count": dealt_in_count,
            **structural,
        },
    )

    with pytest.raises(ValidationError, match="routes to .* requires"):
        benchmark_dataset(
            [case],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=grading_reference_for_table_counts(dealt_in_count),
        )


def test_schema_five_route_mismatch_fails_before_provider_execution(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [covered_preflop_case()],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=grading_reference_evidence(),
    )
    payload = dataset.model_dump(mode="json", by_alias=True)
    payload["cases"][0]["state"]["hero_position"] = "big_blind"
    path = tmp_path / "mismatched-route.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    provider = SequenceProvider([recommendation("check")])

    with pytest.raises(RecommendationBenchmarkError, match="hero_position"):
        benchmark_recommendation_file(
            path,
            Settings(data_dir=tmp_path / "unused"),
            provider,
        )

    assert len(provider.outcomes) == 1


@pytest.mark.parametrize(
    ("hero_position", "button_distance", "display_label", "opponent_position"),
    [
        ("dealer", 0, "BTN/SB", "BB"),
        ("button", 0, "BTN/SB", "big blind"),
        ("big_blind", 1, "BB", "dealer"),
        ("BB", 1, "BB", "btn"),
    ],
)
def test_schema_five_accepts_the_remaining_heads_up_postflop_structural_seat(
    hero_position: str,
    button_distance: int,
    display_label: str,
    opponent_position: str,
) -> None:
    case = covered_heads_up_postflop_case(
        hero_position=hero_position,
        opponent_position=opponent_position,
        hero_structural_position={
            "dealt_in_player_count": 2,
            "action_index": button_distance,
            "button_distance": button_distance,
            "display_label": display_label,
        },
    )

    dataset = benchmark_dataset(
        [case],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=postflop_grading_reference_for_table_counts(2),
    )

    assert dataset.cases[0].state.opponent_position == opponent_position


@pytest.mark.parametrize(
    "opponent_position",
    ["button", "dealer", "small_blind", "cutoff", "ip", "", None],
)
def test_schema_five_rejects_an_incompatible_heads_up_postflop_opponent_route(
    opponent_position: str | None,
) -> None:
    case = covered_heads_up_postflop_case(opponent_position=opponent_position)

    with pytest.raises(
        ValidationError,
        match=r"opponent_position .*heads-up postflop structural coverage.*big_blind",
    ):
        benchmark_dataset(
            [case],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=postflop_grading_reference_for_table_counts(2),
        )


@pytest.mark.parametrize(
    ("opponent_position", "valid"),
    [
        ("small blind", True),
        ("BB", True),
        ("under the gun", True),
        ("middle position", True),
        ("co", True),
        ("button", False),
        ("ip", False),
    ],
)
def test_schema_five_heads_up_postflop_opponent_routes_use_distinct_covered_seats(
    opponent_position: str,
    valid: bool,
) -> None:
    table = reference_table_configuration(6)
    case = covered_heads_up_postflop_case(
        hero_structural_position={
            "dealt_in_player_count": 6,
            **table["structural_positions"][0],
        },
        opponent_position=opponent_position,
    )

    if valid:
        dataset = benchmark_dataset(
            [case],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=postflop_grading_reference_for_table_counts(6),
        )
        assert dataset.cases[0].state.opponent_position == opponent_position
    else:
        with pytest.raises(ValidationError, match="opponent_position .*distinct exact seat"):
            benchmark_dataset(
                [case],
                schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
                reference_source={"name": "Independent solver export"},
                grading_reference=postflop_grading_reference_for_table_counts(6),
            )


def test_schema_five_opponent_route_mismatch_fails_before_provider_execution(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [covered_heads_up_postflop_case()],
        schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
        reference_source={"name": "Independent solver export"},
        grading_reference=postflop_grading_reference_for_table_counts(2),
    )
    payload = dataset.model_dump(mode="json", by_alias=True)
    payload["cases"][0]["state"]["opponent_position"] = "button"
    path = tmp_path / "mismatched-opponent-route.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    provider = SequenceProvider([recommendation("check")])

    with pytest.raises(RecommendationBenchmarkError, match="opponent_position"):
        benchmark_recommendation_file(
            path,
            Settings(data_dir=tmp_path / "unused"),
            provider,
        )

    assert len(provider.outcomes) == 1


@pytest.mark.parametrize("schema_version", [1, 2, 3, 4])
def test_legacy_schema_versions_do_not_enforce_postflop_opponent_routing(
    schema_version: int,
) -> None:
    case = covered_heads_up_postflop_case(opponent_position="button")

    dataset = benchmark_dataset([case], schema_version=schema_version)

    assert dataset.schema_version == schema_version
    assert dataset.cases[0].state.opponent_position == "button"


@pytest.mark.parametrize("schema_version", [1, 2, 3, 4])
@pytest.mark.parametrize(
    "economic_model",
    [None, {"kind": "unknown", "reason": "legacy corpus did not record economics"}],
)
def test_legacy_schema_versions_do_not_enforce_economic_model_binding(
    schema_version: int,
    economic_model: dict[str, object] | None,
) -> None:
    case = covered_preflop_case().model_copy(deep=True)
    state_payload = case.state.model_dump()
    state_payload["economic_model"] = economic_model
    case.state = RecommendationBenchmarkState.model_validate(state_payload)

    dataset = benchmark_dataset([case], schema_version=schema_version)

    assert dataset.schema_version == schema_version


@pytest.mark.parametrize("schema_version", [1, 2, 3, 4])
def test_legacy_schema_versions_may_omit_utility_model_without_serialization_drift(
    schema_version: int,
) -> None:
    case = covered_preflop_case().model_copy(deep=True)
    state_payload = case.state.model_dump()
    state_payload.pop("utility_model")
    case.state = RecommendationBenchmarkState.model_validate(state_payload)

    dataset = benchmark_dataset([case], schema_version=schema_version)
    serialized_state = dataset.model_dump(mode="json", by_alias=True)["cases"][
        0
    ]["state"]

    assert dataset.cases[0].state.utility_model is None
    assert "utility_model" not in serialized_state


@pytest.mark.parametrize(
    ("dealt_in_count", "button_distance", "hero_position"),
    [
        (7, 4, "hijack"),
        (8, 4, "utg"),
        (8, 5, "hijack"),
        (9, 4, "utg"),
        (9, 5, "utg"),
        (9, 6, "hijack"),
        (10, 4, "utg"),
        (10, 5, "utg"),
        (10, 6, "utg"),
        (10, 7, "hijack"),
    ],
)
def test_schema_five_rejects_structural_positions_without_an_exact_legacy_route(
    dealt_in_count: int,
    button_distance: int,
    hero_position: str,
) -> None:
    table = reference_table_configuration(dealt_in_count)
    structural = table["structural_positions"][button_distance]
    case = benchmark_case(
        f"unrouteable-{dealt_in_count}-{button_distance}",
        [reference_line("check")],
        street="preflop",
        board_cards=[],
        effective_stack=100.0,
        players_in_hand=2,
        economic_model=case_economic_model_evidence(),
        hero_position=hero_position,
        hero_structural_position={
            "dealt_in_player_count": dealt_in_count,
            **structural,
        },
    )

    with pytest.raises(ValidationError, match="cannot be represented exactly"):
        benchmark_dataset(
            [case],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=grading_reference_for_table_counts(dealt_in_count),
        )


@pytest.mark.parametrize("schema_version", [1, 2, 3, 4])
def test_legacy_schema_versions_do_not_enforce_structural_position_routing(
    schema_version: int,
) -> None:
    case = covered_preflop_case().model_copy(deep=True)
    case.state.hero_position = "big_blind"

    dataset = benchmark_dataset([case], schema_version=schema_version)

    assert dataset.schema_version == schema_version
    assert dataset.cases[0].state.hero_position == "big_blind"


@pytest.mark.parametrize("schema_version", [1, 2, 3, 4])
def test_legacy_schema_versions_do_not_enforce_visible_stack_consistency(
    schema_version: int,
) -> None:
    case = covered_preflop_case().model_copy(deep=True)
    case.state.hero_stack = 99.0
    case.state.opponent_stack = 98.0

    dataset = benchmark_dataset([case], schema_version=schema_version)

    assert dataset.schema_version == schema_version
    assert dataset.cases[0].state.hero_stack == 99.0


def test_recommendation_benchmark_scores_policy_ev_fallback_and_failures() -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "mixed-flop",
                [
                    reference_line("check", frequency=0.4, ev_bb=0.5),
                    reference_line("bet", sizing=5.0, frequency=0.6, ev_bb=0.7),
                ],
            ),
            benchmark_case(
                "unsupported-action",
                [reference_line("fold", frequency=1.0, ev_bb=0.3)],
            ),
            benchmark_case(
                "provider-failure",
                [reference_line("check", frequency=1.0)],
            ),
        ]
    )
    provider = SequenceProvider(
        [
            recommendation(
                "check",
                candidates=[
                    {"action": "check", "sizing": None, "frequency": 0.5},
                    {"action": "bet", "sizing": 5.0, "frequency": 0.5},
                ],
            ),
            recommendation(
                "call",
                fallback_reason="raised pots are not supported",
            ),
            RuntimeError("solver unavailable"),
        ]
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.total_cases == 3
    assert report.completed_cases == 2
    assert report.failed_cases == 1
    assert report.action_correct == 1
    assert report.action_accuracy == 0.5
    assert report.line_correct == 1
    assert report.line_evaluated == 2
    assert report.line_accuracy == 0.5
    assert report.policy_evaluated_cases == 1
    assert report.average_policy_distance == 0.1
    assert report.ev_evaluated_cases == 1
    assert report.average_reference_ev_loss_bb == 0.2
    assert report.maximum_reference_ev_loss_bb == 0.2
    assert report.fallback_cases == 1
    assert report.fallback_rate == 0.5
    assert report.cases[0].engine == "reference_test_v1"
    assert report.cases[1].action_match is False
    assert report.cases[1].line_match is False
    assert report.cases[2].status == "error"
    assert report.cases[2].error == "solver unavailable"
    formatted = format_recommendation_benchmark_report(report)
    assert "Action agreement: 1/2 (50.0%)" in formatted
    assert "Average policy distance: 0.100 across 1 case(s)" in formatted
    assert "unsupported-action: mismatched action, line" in formatted
    assert "provider-failure: solver unavailable" in formatted


def test_recommendation_benchmark_runs_heads_up_limp_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-heads-up-limp-big-blind",
                [reference_line("raise", sizing=4)],
                tags=["preflop", "heads-up-limp", "big-blind-option"],
                hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
                board_cards=[],
                street="preflop",
                pot_size=2.5,
                current_bet=0,
                hero_stack=None,
                effective_stack=100.0,
                players_in_hand=2,
                hero_position="big_blind",
                facing_action=None,
                preflop_action_history=[
                    PreflopAction(actor="button", action="call", amount=1),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_recommendation_benchmark_runs_two_limper_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-two-limpers-big-blind",
                [reference_line("raise", sizing=5.25)],
                tags=["preflop", "two-limpers", "big-blind-option"],
                hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
                board_cards=[],
                street="preflop",
                pot_size=3.5,
                current_bet=0,
                hero_stack=None,
                effective_stack=100.0,
                players_in_hand=3,
                hero_position="big_blind",
                facing_action=None,
                preflop_action_history=[
                    PreflopAction(actor="utg", action="call", amount=1),
                    PreflopAction(actor="button", action="call", amount=1),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_recommendation_benchmark_runs_three_limper_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-three-limpers-big-blind",
                [reference_line("raise", sizing=6.75)],
                tags=["preflop", "three-limpers", "big-blind-option"],
                hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
                board_cards=[],
                street="preflop",
                pot_size=4.5,
                current_bet=0,
                hero_stack=None,
                effective_stack=100.0,
                players_in_hand=4,
                hero_position="big_blind",
                facing_action=None,
                preflop_action_history=[
                    PreflopAction(actor="utg", action="call", amount=1),
                    PreflopAction(actor="cutoff", action="call", amount=1),
                    PreflopAction(actor="button", action="call", amount=1),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_recommendation_benchmark_runs_four_limper_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-four-limpers-big-blind",
                [reference_line("raise", sizing=8.25)],
                tags=["preflop", "four-limpers", "big-blind-option"],
                hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
                board_cards=[],
                street="preflop",
                pot_size=5.5,
                current_bet=0,
                hero_stack=None,
                effective_stack=100.0,
                players_in_hand=5,
                hero_position="big_blind",
                facing_action=None,
                preflop_action_history=[
                    PreflopAction(actor="utg", action="call", amount=1),
                    PreflopAction(actor="hijack", action="call", amount=1),
                    PreflopAction(actor="cutoff", action="call", amount=1),
                    PreflopAction(actor="button", action="call", amount=1),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_recommendation_benchmark_runs_five_limper_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-five-limpers-big-blind",
                [reference_line("raise", sizing=9)],
                tags=["preflop", "five-limpers", "big-blind-option"],
                hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
                board_cards=[],
                street="preflop",
                pot_size=6,
                current_bet=0,
                hero_stack=None,
                effective_stack=100.0,
                players_in_hand=6,
                hero_position="big_blind",
                facing_action=None,
                preflop_action_history=[
                    PreflopAction(actor="utg", action="call", amount=1),
                    PreflopAction(actor="hijack", action="call", amount=1),
                    PreflopAction(actor="cutoff", action="call", amount=1),
                    PreflopAction(actor="button", action="call", amount=1),
                    PreflopAction(actor="small_blind", action="call", amount=1),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_recommendation_benchmark_runs_single_caller_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-single-caller",
                [reference_line("call")],
                tags=["preflop", "single-caller"],
                hero_cards=[Card.from_code("Ah"), Card.from_code("Jh")],
                board_cards=[],
                street="preflop",
                pot_size=6.5,
                current_bet=2.5,
                hero_stack=None,
                effective_stack=100.0,
                players_in_hand=3,
                hero_position="button",
                facing_action="raise",
                preflop_opener_position="utg",
                preflop_open_size=2.5,
                preflop_action_history=[
                    PreflopAction(actor="utg", action="raise", amount=2.5),
                    PreflopAction(actor="hijack", action="call", amount=2.5),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_recommendation_benchmark_runs_triple_caller_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-triple-caller",
                [reference_line("raise", sizing=15)],
                tags=["preflop", "triple-caller"],
                hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
                board_cards=[],
                street="preflop",
                pot_size=11.5,
                current_bet=2,
                hero_stack=None,
                effective_stack=100.0,
                players_in_hand=5,
                hero_position="small_blind",
                facing_action="raise",
                preflop_opener_position="utg",
                preflop_open_size=2.5,
                preflop_action_history=[
                    PreflopAction(actor="utg", action="raise", amount=2.5),
                    PreflopAction(actor="hijack", action="call", amount=2.5),
                    PreflopAction(actor="cutoff", action="call", amount=2.5),
                    PreflopAction(actor="button", action="call", amount=2.5),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_recommendation_benchmark_runs_four_caller_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-four-caller",
                [reference_line("raise", sizing=17.5)],
                tags=["preflop", "four-caller", "full-table"],
                hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
                board_cards=[],
                street="preflop",
                pot_size=13.5,
                current_bet=1.5,
                hero_stack=None,
                effective_stack=100.0,
                players_in_hand=6,
                hero_position="big_blind",
                facing_action="raise",
                preflop_opener_position="utg",
                preflop_open_size=2.5,
                preflop_action_history=[
                    PreflopAction(actor="utg", action="raise", amount=2.5),
                    PreflopAction(actor="hijack", action="call", amount=2.5),
                    PreflopAction(actor="cutoff", action="call", amount=2.5),
                    PreflopAction(actor="button", action="call", amount=2.5),
                    PreflopAction(actor="small_blind", action="call", amount=2.5),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_recommendation_benchmark_runs_cold_three_bet_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-cold-three-bet",
                [reference_line("call")],
                tags=["preflop", "cold-three-bet"],
                hero_cards=[Card.from_code("Th"), Card.from_code("Ts")],
                board_cards=[],
                street="preflop",
                pot_size=12,
                current_bet=7,
                hero_stack=99,
                effective_stack=92,
                players_in_hand=3,
                hero_position="big_blind",
                facing_action="raise",
                preflop_opener_position="utg",
                preflop_open_size=2.5,
                preflop_action_history=[
                    PreflopAction(actor="utg", action="raise", amount=2.5),
                    PreflopAction(actor="button", action="raise", amount=8),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_recommendation_benchmark_runs_squeeze_response_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-facing-squeeze-after-call",
                [reference_line("call")],
                tags=["preflop", "facing-squeeze-after-call"],
                hero_cards=[Card.from_code("Th"), Card.from_code("Ts")],
                board_cards=[],
                street="preflop",
                pot_size=16,
                current_bet=7.5,
                hero_stack=97.5,
                effective_stack=90,
                players_in_hand=2,
                hero_position="button",
                facing_action="raise",
                preflop_opener_position="utg",
                preflop_open_size=2.5,
                preflop_action_history=[
                    PreflopAction(actor="utg", action="raise", amount=2.5),
                    PreflopAction(actor="button", action="call", amount=2.5),
                    PreflopAction(
                        actor="small_blind",
                        action="raise",
                        amount=10,
                    ),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_recommendation_benchmark_runs_four_bet_response_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-facing-four-bet",
                [reference_line("call")],
                tags=["preflop", "facing-four-bet"],
                hero_cards=[Card.from_code("Th"), Card.from_code("Ts")],
                board_cards=[],
                street="preflop",
                pot_size=29.5,
                current_bet=12,
                hero_stack=92,
                effective_stack=80,
                players_in_hand=2,
                hero_position="button",
                facing_action="raise",
                preflop_opener_position="cutoff",
                preflop_open_size=2.5,
                preflop_action_history=[
                    PreflopAction(actor="cutoff", action="raise", amount=2.5),
                    PreflopAction(actor="button", action="raise", amount=8),
                    PreflopAction(actor="cutoff", action="raise", amount=20),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_recommendation_benchmark_runs_cold_four_bet_response_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-facing-cold-four-bet",
                [reference_line("call")],
                tags=["preflop", "facing-cold-four-bet"],
                hero_cards=[Card.from_code("Qh"), Card.from_code("Qd")],
                board_cards=[],
                street="preflop",
                pot_size=32,
                current_bet=12,
                hero_stack=92,
                effective_stack=80,
                players_in_hand=2,
                hero_position="cutoff",
                facing_action="raise",
                preflop_opener_position="utg",
                preflop_open_size=2.5,
                preflop_action_history=[
                    PreflopAction(actor="utg", action="raise", amount=2.5),
                    PreflopAction(actor="cutoff", action="raise", amount=8),
                    PreflopAction(actor="button", action="raise", amount=20),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_report_exposes_provenance_coverage_and_scenario_breakdowns() -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "flop-cbet",
                [
                    reference_line("check", frequency=0.4, ev_bb=0.5),
                    reference_line("bet", sizing=5.0, frequency=0.6, ev_bb=0.7),
                ],
                tags=["single-raised-pot", "in-position"],
            ),
            benchmark_case(
                "turn-facing-bet",
                [
                    reference_line("fold", frequency=0.25, ev_bb=0.0),
                    reference_line("call", frequency=0.75, ev_bb=0.4),
                ],
                tags=["single-raised-pot", "facing-bet"],
                street="turn",
                board_cards=[
                    Card.from_code("Qs"),
                    Card.from_code("Jc"),
                    Card.from_code("2h"),
                    Card.from_code("4d"),
                ],
            ),
        ],
        reference_source={
            "name": "Independent Solver",
            "version": "2.1",
            "configuration": "Heads-up cash, no rake",
        },
    )
    provider = SequenceProvider(
        [
            recommendation(
                "bet",
                sizing=5.0,
                candidates=[
                    {"action": "check", "sizing": None, "frequency": 0.5},
                    {"action": "bet", "sizing": 5.0, "frequency": 0.5},
                ],
            ),
            recommendation("call"),
        ]
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.reference_source is not None
    assert report.reference_source.name == "Independent Solver"
    assert report.line_coverage == 1
    assert report.policy_coverage == 0.5
    assert report.ev_coverage == 1
    assert [item.key for item in report.street_metrics] == ["flop", "turn"]
    assert report.street_metrics[0].policy_coverage == 1
    assert report.street_metrics[1].policy_coverage == 0
    assert [item.key for item in report.tag_metrics] == [
        "facing-bet",
        "in-position",
        "single-raised-pot",
    ]
    assert report.tag_metrics[2].total_cases == 2
    formatted = format_recommendation_benchmark_report(report)
    assert "Reference: Independent Solver 2.1" in formatted
    assert "Policy evaluation coverage: 1/2 (50.0%)" in formatted
    assert "Street breakdown:" in formatted
    assert "Tag breakdown:" in formatted


def test_report_scores_expected_range_conditioning_evidence() -> None:
    turn_state = {
        "street": "turn",
        "board_cards": [
            Card.from_code("Qs"),
            Card.from_code("Jc"),
            Card.from_code("2h"),
            Card.from_code("4d"),
        ],
    }
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "conditioning-applied",
                [reference_line("check")],
                tags=["range-conditioning"],
                expected_range_conditioning="applied",
                **turn_state,
            ),
            benchmark_case(
                "conditioning-wrong-status",
                [reference_line("check")],
                tags=["range-conditioning"],
                expected_range_conditioning="applied",
                **turn_state,
            ),
            benchmark_case(
                "conditioning-missing",
                [reference_line("check")],
                tags=["range-conditioning"],
                expected_range_conditioning="skipped",
                **turn_state,
            ),
            benchmark_case(
                "conditioning-padded-status",
                [reference_line("check")],
                tags=["range-conditioning"],
                expected_range_conditioning="applied",
                **turn_state,
            ),
            benchmark_case(
                "conditioning-not-expected",
                [reference_line("check")],
                **turn_state,
            ),
        ]
    )
    provider = SequenceProvider(
        [
            recommendation(
                "check",
                range_conditioning={"status": "applied"},
            ),
            recommendation(
                "check",
                range_conditioning={"status": "skipped"},
            ),
            recommendation("check"),
            recommendation(
                "check",
                range_conditioning={"status": " applied "},
            ),
            recommendation(
                "check",
                range_conditioning={"status": "pending"},
            ),
        ]
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.conditioning_expected_cases == 4
    assert report.conditioning_evaluated_cases == 2
    assert report.conditioning_correct_cases == 1
    assert report.conditioning_accuracy == 0.5
    assert report.conditioning_coverage == 0.5
    assert report.cases[0].range_conditioning_status == "applied"
    assert report.cases[0].range_conditioning_match is True
    assert report.cases[1].range_conditioning_status == "skipped"
    assert report.cases[1].range_conditioning_match is False
    assert report.cases[2].range_conditioning_status is None
    assert report.cases[2].range_conditioning_match is None
    assert report.cases[3].range_conditioning_status is None
    assert report.cases[3].range_conditioning_match is None
    assert report.cases[4].range_conditioning_status is None
    assert report.street_metrics[0].conditioning_accuracy == 0.5
    assert report.tag_metrics[0].conditioning_coverage == 0.5
    formatted = format_recommendation_benchmark_report(report)
    assert "Range conditioning agreement: 1/2 (50.0%)" in formatted
    assert "Range conditioning evidence coverage: 2/4 (50.0%)" in formatted
    assert "conditioning-wrong-status: mismatched range conditioning" in formatted
    assert (
        "conditioning-missing: mismatched range conditioning"
        " (expected skipped, not reported)"
    ) in formatted
    assert (
        "conditioning-padded-status: mismatched range conditioning"
        " (expected applied, not reported)"
    ) in formatted


def test_conditioning_coverage_includes_failed_expected_cases() -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "conditioning-provider-failure",
                [reference_line("check")],
                expected_range_conditioning="applied",
                street="turn",
                board_cards=[
                    Card.from_code("Qs"),
                    Card.from_code("Jc"),
                    Card.from_code("2h"),
                    Card.from_code("4d"),
                ],
            )
        ]
    )

    report = run_recommendation_benchmark(
        dataset,
        SequenceProvider([RuntimeError("solver unavailable")]),
    )

    assert report.failed_cases == 1
    assert report.conditioning_expected_cases == 1
    assert report.conditioning_evaluated_cases == 0
    assert report.conditioning_accuracy is None
    assert report.conditioning_coverage == 0


def test_report_scores_expected_postflop_range_source_evidence() -> None:
    expected_source = "preflop_chart_single_raised_pot"
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "range-source-correct",
                [reference_line("check")],
                tags=["range-source"],
                expected_range_source=expected_source,
            ),
            benchmark_case(
                "range-source-wrong",
                [reference_line("check")],
                tags=["range-source"],
                expected_range_source=expected_source,
            ),
            benchmark_case(
                "range-source-missing",
                [reference_line("check")],
                tags=["range-source"],
                expected_range_source="configured",
            ),
            benchmark_case(
                "range-source-padded",
                [reference_line("check")],
                tags=["range-source"],
                expected_range_source="configured",
            ),
            benchmark_case(
                "range-source-not-expected",
                [reference_line("check")],
            ),
        ]
    )
    provider = SequenceProvider(
        [
            recommendation("check", range_source=expected_source),
            recommendation(
                "check",
                range_source="preflop_chart_three_bet_pot",
            ),
            recommendation("check"),
            recommendation("check", range_source=" configured "),
            recommendation("check", range_source="configured"),
        ]
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.range_source_expected_cases == 4
    assert report.range_source_evaluated_cases == 2
    assert report.range_source_correct_cases == 1
    assert report.range_source_accuracy == 0.5
    assert report.range_source_coverage == 0.5
    assert report.cases[0].range_source == expected_source
    assert report.cases[0].range_source_match is True
    assert report.cases[1].range_source == "preflop_chart_three_bet_pot"
    assert report.cases[1].range_source_match is False
    assert report.cases[2].range_source is None
    assert report.cases[2].range_source_match is None
    assert report.cases[3].range_source is None
    assert report.cases[3].range_source_match is None
    assert report.cases[4].range_source == "configured"
    assert report.cases[4].range_source_match is None
    assert report.street_metrics[0].range_source_accuracy == 0.5
    assert report.tag_metrics[0].range_source_coverage == 0.5
    formatted = format_recommendation_benchmark_report(report)
    assert "Range source agreement: 1/2 (50.0%)" in formatted
    assert "Range source evidence coverage: 2/4 (50.0%)" in formatted
    assert "range-source-wrong: mismatched range source" in formatted
    assert (
        "range-source-missing: mismatched range source"
        " (expected configured, not reported)"
    ) in formatted
    assert (
        "range-source-padded: mismatched range source"
        " (expected configured, not reported)"
    ) in formatted
    assert "range source 50.0% (50.0% coverage)" in formatted


def test_range_source_coverage_includes_failed_expected_cases() -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "range-source-provider-failure",
                [reference_line("check")],
                expected_range_source="configured",
            )
        ]
    )

    report = run_recommendation_benchmark(
        dataset,
        SequenceProvider([RuntimeError("solver unavailable")]),
    )

    assert report.failed_cases == 1
    assert report.range_source_expected_cases == 1
    assert report.range_source_evaluated_cases == 0
    assert report.range_source_accuracy is None
    assert report.range_source_coverage == 0


def test_action_only_wager_reference_skips_line_accuracy() -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "action-only",
                [reference_line("bet", frequency=1.0, ev_bb=1.0)],
            )
        ]
    )
    provider = SequenceProvider(
        [
            recommendation(
                "bet",
                sizing=7.0,
                candidates=[
                    {"action": "bet", "sizing": 7.0, "frequency": 1.0}
                ],
            )
        ]
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.action_accuracy == 1
    assert report.line_evaluated == 0
    assert report.line_accuracy is None
    assert report.policy_evaluated_cases == 1
    assert report.average_policy_distance == 0
    assert report.average_reference_ev_loss_bb == 0
    assert "Line agreement: not evaluated" in format_recommendation_benchmark_report(
        report
    )


def test_sizing_tolerance_boundary_is_not_a_line_match() -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "sizing-boundary",
                [reference_line("bet", sizing=5.0)],
            )
        ]
    )

    report = run_recommendation_benchmark(
        dataset,
        SequenceProvider([recommendation("bet", sizing=5.01)]),
    )

    assert report.action_accuracy == 1
    assert report.line_accuracy == 0
    assert report.cases[0].line_match is False


def test_reference_sizes_exactly_two_tolerances_apart_are_unambiguous() -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "adjacent-sizes",
                [
                    reference_line("bet", sizing=5.0, frequency=0.5),
                    reference_line("bet", sizing=5.02, frequency=0.5),
                ],
            )
        ]
    )

    assert dataset.cases[0].reference_lines[1].sizing == 5.02


def test_malformed_candidate_metadata_skips_policy_metric() -> None:
    dataset = benchmark_dataset(
        [benchmark_case("bad-candidates", [reference_line("check")])]
    )
    provider = SequenceProvider(
        [
            recommendation(
                "check",
                candidates=[
                    {"action": ["check"], "sizing": None, "frequency": 1.0}
                ],
            )
        ]
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_accuracy == 1
    assert report.policy_evaluated_cases == 0
    assert report.average_policy_distance is None


def test_zero_frequency_unsized_wager_does_not_hide_policy_metric() -> None:
    dataset = benchmark_dataset(
        [benchmark_case("deterministic-check", [reference_line("check")])]
    )
    provider = SequenceProvider(
        [
            recommendation(
                "check",
                candidates=[
                    {"action": "check", "sizing": None, "frequency": 1.0},
                    {"action": "raise", "sizing": None, "frequency": 0.0},
                ],
            )
        ]
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.policy_evaluated_cases == 1
    assert report.average_policy_distance == 0


def test_rounded_candidate_frequencies_are_normalized() -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "rounded-policy",
                [
                    reference_line("check", frequency=1 / 3),
                    reference_line("bet", sizing=5.0, frequency=1 / 3),
                    reference_line("bet", sizing=7.0, frequency=1 / 3),
                ],
            )
        ]
    )
    provider = SequenceProvider(
        [
            recommendation(
                "check",
                candidates=[
                    {"action": "check", "sizing": None, "frequency": 0.3333},
                    {"action": "bet", "sizing": 5.0, "frequency": 0.3333},
                    {"action": "bet", "sizing": 7.0, "frequency": 0.3333},
                ],
            )
        ]
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.policy_evaluated_cases == 1
    assert report.average_policy_distance == 0


def test_incomplete_candidate_frequencies_hide_policy_metric() -> None:
    dataset = benchmark_dataset(
        [benchmark_case("incomplete-policy", [reference_line("check")])]
    )
    provider = SequenceProvider(
        [
            recommendation(
                "check",
                candidates=[
                    {"action": "check", "sizing": None, "frequency": 0.999}
                ],
            )
        ]
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.policy_evaluated_cases == 0
    assert report.average_policy_distance is None


def test_missing_required_state_is_an_isolated_case_failure() -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "missing-cards",
                [reference_line("check")],
                hero_cards=[],
            ),
            benchmark_case("valid", [reference_line("check")]),
        ]
    )
    provider = SequenceProvider([recommendation("check")])

    report = run_recommendation_benchmark(dataset, provider)

    assert report.failed_cases == 1
    assert report.completed_cases == 1
    assert report.cases[0].error == "Missing required fields: hero_cards"
    assert report.cases[1].action_match is True


def test_missing_street_is_visible_in_unknown_breakdown() -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "missing-street",
                [reference_line("check")],
                street=None,
            )
        ]
    )

    report = run_recommendation_benchmark(dataset, SequenceProvider([]))

    assert report.failed_cases == 1
    assert [item.key for item in report.street_metrics] == ["unknown"]
    assert report.street_metrics[0].failed_cases == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "coerced_version",
        "duplicate_case",
        "frequency_total",
        "partial_ev",
        "ambiguous_sizing",
        "duplicate_tag",
        "invalid_tag",
        "invalid_conditioning_status",
        "flop_conditioning_expectation",
        "invalid_range_source",
        "preflop_range_source_expectation",
        "extra_reference_source_field",
        "extra_state_field",
    ],
)
def test_recommendation_benchmark_dataset_rejects_invalid_schema(
    mutation: str,
) -> None:
    payload = {
        "schema": RECOMMENDATION_BENCHMARK_SCHEMA,
        "schema_version": 4,
        "name": "Invalid sample",
        "sizing_tolerance_bb": 0.01,
        "minimum_policy_frequency": 0.05,
        "cases": [
            {
                "id": "case-1",
                "state": benchmark_state().model_dump(mode="json"),
                "reference_lines": [
                    {
                        "action": "check",
                        "sizing": None,
                        "frequency": 1.0,
                        "ev_bb": None,
                    }
                ],
            }
        ],
    }
    if mutation == "coerced_version":
        payload["schema_version"] = True
    elif mutation == "duplicate_case":
        payload["cases"].append(payload["cases"][0])
    elif mutation == "frequency_total":
        payload["cases"][0]["reference_lines"][0]["frequency"] = 0.9
    elif mutation == "partial_ev":
        payload["cases"][0]["reference_lines"] = [
            {"action": "check", "frequency": 0.5, "ev_bb": 0.1},
            {"action": "bet", "sizing": 5.0, "frequency": 0.5},
        ]
    elif mutation == "ambiguous_sizing":
        payload["cases"][0]["reference_lines"] = [
            {"action": "bet", "sizing": 5.0, "frequency": 0.5},
            {"action": "bet", "sizing": 5.01, "frequency": 0.5},
        ]
    elif mutation == "duplicate_tag":
        payload["cases"][0]["tags"] = ["facing-bet", "facing-bet"]
    elif mutation == "invalid_tag":
        payload["cases"][0]["tags"] = ["Facing bet"]
    elif mutation == "invalid_conditioning_status":
        payload["cases"][0]["expected_range_conditioning"] = "pending"
    elif mutation == "flop_conditioning_expectation":
        payload["cases"][0]["expected_range_conditioning"] = "applied"
    elif mutation == "invalid_range_source":
        payload["cases"][0]["expected_range_source"] = "automatic"
    elif mutation == "preflop_range_source_expectation":
        payload["cases"][0]["expected_range_source"] = "configured"
        payload["cases"][0]["state"]["street"] = "preflop"
    elif mutation == "extra_reference_source_field":
        payload["reference_source"] = {
            "name": "Independent Solver",
            "license_key": "not-allowed",
        }
    else:
        payload["cases"][0]["state"]["invented"] = "value"

    with pytest.raises(ValidationError):
        RecommendationBenchmarkDataset.model_validate(payload)


def test_schema_five_requires_structured_reference_evidence() -> None:
    payload = benchmark_dataset(
        [benchmark_case("v4-check", [reference_line("check")])]
    ).model_dump(mode="json", by_alias=True)
    payload["schema_version"] = RECOMMENDATION_BENCHMARK_SCHEMA_VERSION

    with pytest.raises(ValidationError, match="grading reference evidence"):
        RecommendationBenchmarkDataset.model_validate(payload)

    payload["schema_version"] = 4
    payload["grading_reference"] = grading_reference_evidence()
    with pytest.raises(ValidationError, match="requires schema version 5"):
        RecommendationBenchmarkDataset.model_validate(payload)


def test_schema_five_rejects_non_bb_unit_for_legacy_ev_labels() -> None:
    with pytest.raises(ValidationError, match="ev_bb reference labels require"):
        benchmark_dataset(
            [benchmark_case("chip-ev", [reference_line("check", ev_bb=20.0)])],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=grading_reference_evidence(ev_unit="chips"),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_static_grant", "missing grants: redistribution"),
        ("missing_feed_grant", "missing grants: derived_outputs"),
        ("failed_convergence", "must be at most its threshold"),
        ("table_position_gap", "cover every dealt-in seat exactly"),
        ("structural_index_mismatch", "must match its button distance"),
        ("collapsed_position_label", "must match its dealt-in table position"),
        ("invalid_digest", "String should match pattern"),
    ],
)
def test_schema_five_validates_phase_zero_gate_evidence(
    mutation: str,
    message: str,
) -> None:
    evidence = grading_reference_evidence()
    if mutation == "missing_static_grant":
        evidence["rights_evidence"]["grants"].remove("redistribution")
    elif mutation == "missing_feed_grant":
        evidence = grading_reference_evidence(delivery_mode="server_side_feed")
        evidence["rights_evidence"]["grants"].remove("derived_outputs")
    elif mutation == "failed_convergence":
        evidence["convergence_evidence"][0]["observed"] = 0.03
    elif mutation == "table_position_gap":
        evidence["coverage"]["table_configurations"][0]["dealt_in_count"] = 3
    elif mutation == "structural_index_mismatch":
        evidence["coverage"]["table_configurations"][0]["structural_positions"][
            0
        ]["action_index"] = 1
        evidence["coverage"]["table_configurations"][0]["structural_positions"][
            1
        ]["action_index"] = 0
    elif mutation == "collapsed_position_label":
        evidence["coverage"]["table_configurations"][0]["structural_positions"][
            0
        ]["display_label"] = "MP"
    else:
        evidence["source_artifact_sha256"] = "not-a-digest"

    with pytest.raises(ValidationError, match=message):
        benchmark_dataset(
            [benchmark_case("phase-zero", [reference_line("check")])],
            schema_version=RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
            reference_source={"name": "Independent solver export"},
            grading_reference=evidence,
        )


def test_benchmark_file_rejects_invalid_and_oversized_json(tmp_path: Path) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("not json", encoding="utf-8")

    with pytest.raises(RecommendationBenchmarkError, match="invalid"):
        load_recommendation_benchmark_dataset(invalid_path)

    oversized_path = tmp_path / "oversized.json"
    oversized_path.write_bytes(b"x" * (MAX_RECOMMENDATION_BENCHMARK_BYTES + 1))
    with pytest.raises(RecommendationBenchmarkError, match="4 MiB"):
        load_recommendation_benchmark_dataset(oversized_path)


def test_loader_accepts_legacy_version_one_corpus(tmp_path: Path) -> None:
    payload = benchmark_dataset(
        [benchmark_case("legacy-check", [reference_line("check")])]
    ).model_dump(mode="json", by_alias=True)
    payload["schema_version"] = 1
    payload.pop("reference_source")
    payload["cases"][0].pop("tags")
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    dataset = load_recommendation_benchmark_dataset(path)

    assert dataset.schema_version == 1
    assert dataset.reference_source is None
    assert dataset.cases[0].tags == []


def test_loader_accepts_version_two_corpus_without_conditioning(
    tmp_path: Path,
) -> None:
    payload = benchmark_dataset(
        [benchmark_case("version-two-check", [reference_line("check")])]
    ).model_dump(mode="json", by_alias=True)
    payload["schema_version"] = 2
    path = tmp_path / "version-two.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    dataset = load_recommendation_benchmark_dataset(path)

    assert dataset.schema_version == 2
    assert dataset.cases[0].expected_range_conditioning is None


def test_loader_rejects_conditioning_expectation_in_version_two(
    tmp_path: Path,
) -> None:
    payload = benchmark_dataset(
        [
            benchmark_case(
                "version-two-turn",
                [reference_line("check")],
                expected_range_conditioning="applied",
                street="turn",
                board_cards=[
                    Card.from_code("Qs"),
                    Card.from_code("Jc"),
                    Card.from_code("2h"),
                    Card.from_code("4d"),
                ],
            )
        ]
    ).model_dump(mode="json", by_alias=True)
    payload["schema_version"] = 2
    path = tmp_path / "invalid-version-two.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RecommendationBenchmarkError, match="schema version 3"):
        load_recommendation_benchmark_dataset(path)


def test_loader_accepts_version_three_corpus_without_range_source(
    tmp_path: Path,
) -> None:
    payload = benchmark_dataset(
        [benchmark_case("version-three-check", [reference_line("check")])]
    ).model_dump(mode="json", by_alias=True)
    payload["schema_version"] = 3
    path = tmp_path / "version-three.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    dataset = load_recommendation_benchmark_dataset(path)

    assert dataset.schema_version == 3
    assert dataset.cases[0].expected_range_source is None


def test_loader_rejects_range_source_expectation_in_version_three(
    tmp_path: Path,
) -> None:
    payload = benchmark_dataset(
        [
            benchmark_case(
                "version-three-range-source",
                [reference_line("check")],
                expected_range_source="configured",
            )
        ]
    ).model_dump(mode="json", by_alias=True)
    payload["schema_version"] = 3
    path = tmp_path / "invalid-version-three.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RecommendationBenchmarkError, match="schema version 4"):
        load_recommendation_benchmark_dataset(path)


def test_loader_accepts_version_four_corpus_without_grading_reference(
    tmp_path: Path,
) -> None:
    payload = benchmark_dataset(
        [benchmark_case("version-four-check", [reference_line("check")])]
    ).model_dump(mode="json", by_alias=True)
    path = tmp_path / "version-four.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    dataset = load_recommendation_benchmark_dataset(path)

    assert dataset.schema_version == 4
    assert dataset.grading_reference is None


def test_recommendation_benchmark_cli_emits_json_and_enforces_thresholds(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = write_dataset(
        tmp_path / "recommendations.json",
        benchmark_dataset(
            [
                benchmark_case(
                    "mixed-flop",
                    [
                        reference_line("check", frequency=0.4, ev_bb=0.5),
                        reference_line(
                            "bet",
                            sizing=5.0,
                            frequency=0.6,
                            ev_bb=0.7,
                        ),
                    ],
                )
            ]
        ),
    )
    provider = SequenceProvider(
        [
            recommendation(
                "check",
                candidates=[
                    {"action": "check", "sizing": None, "frequency": 0.5},
                    {"action": "bet", "sizing": 5.0, "frequency": 0.5},
                ],
            )
        ]
    )

    exit_code = main(
        [
            str(dataset_path),
            "--json",
            "--minimum-action-accuracy",
            "1",
            "--minimum-line-accuracy",
            "1",
            "--maximum-policy-distance",
            "0.05",
            "--maximum-ev-loss",
            "0.1",
            "--maximum-fallback-rate",
            "0",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=provider,
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert exit_code == 1
    assert report["provider"] == "test_solver"
    assert report["action_accuracy"] == 1
    assert "Average policy distance 0.100 is above the maximum 0.050" in captured.err
    assert "Average reference EV loss 0.200 BB is above the maximum 0.100 BB" in (
        captured.err
    )


def test_recommendation_benchmark_cli_fails_on_accuracy_regression(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = benchmark_dataset(
        [benchmark_case("action", [reference_line("check")])]
    )
    dataset_path = write_dataset(tmp_path / "recommendations.json", dataset)
    baseline_path = write_report(
        tmp_path / "baseline.json",
        run_recommendation_benchmark(
            dataset,
            SequenceProvider([recommendation("check")]),
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--baseline-report",
            str(baseline_path),
            "--maximum-metric-regression",
            "action_accuracy=0",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("fold")]),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Baseline comparison:" in captured.out
    assert "Action accuracy: -100.0 pts" in captured.out
    assert "Action accuracy regressed 100.0 pts" in captured.err


def test_recommendation_benchmark_cli_gates_lower_is_better_metrics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "mixed",
                [
                    reference_line("check", frequency=0.4, ev_bb=0.5),
                    reference_line(
                        "bet",
                        sizing=5.0,
                        frequency=0.6,
                        ev_bb=0.7,
                    ),
                ],
            )
        ]
    )
    dataset_path = write_dataset(tmp_path / "recommendations.json", dataset)
    baseline_path = write_report(
        tmp_path / "baseline.json",
        run_recommendation_benchmark(
            dataset,
            SequenceProvider(
                [
                    recommendation(
                        "bet",
                        sizing=5.0,
                        candidates=[
                            {"action": "check", "sizing": None, "frequency": 0.4},
                            {"action": "bet", "sizing": 5.0, "frequency": 0.6},
                        ],
                    )
                ]
            ),
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--baseline-report",
            str(baseline_path),
            "--maximum-metric-regression",
            "average_policy_distance=0.1",
            "--maximum-metric-regression",
            "average_ev_loss=0.1",
            "--maximum-metric-regression",
            "fallback_rate=0.5",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider(
            [
                recommendation(
                    "check",
                    candidates=[
                        {"action": "check", "sizing": None, "frequency": 0.6},
                        {"action": "bet", "sizing": 5.0, "frequency": 0.4},
                    ],
                    fallback_reason="Unsupported spot",
                )
            ]
        ),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Average policy distance: +0.200" in captured.out
    assert "Average reference EV loss: +0.200 BB" in captured.out
    assert "Fallback rate: +100.0 pts" in captured.out
    assert "Average policy distance regressed 0.200" in captured.err
    assert "Average reference EV loss regressed 0.200 BB" in captured.err
    assert "Fallback rate regressed 100.0 pts" in captured.err


def test_recommendation_benchmark_cli_keeps_json_output_reusable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = benchmark_dataset(
        [benchmark_case("action", [reference_line("check")])]
    )
    dataset_path = write_dataset(tmp_path / "recommendations.json", dataset)
    baseline_report = run_recommendation_benchmark(
        dataset,
        SequenceProvider([recommendation("check")]),
    )
    baseline_path = write_report(tmp_path / "baseline.json", baseline_report)

    exit_code = main(
        [
            str(dataset_path),
            "--baseline-report",
            str(baseline_path),
            "--maximum-metric-regression",
            "action_accuracy=0",
            "--json",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("check")]),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    output = json.loads(captured.out)
    assert output["dataset_fingerprint"] == baseline_report.dataset_fingerprint
    assert "Baseline comparison" not in captured.out
    assert captured.err == ""


def test_recommendation_benchmark_cli_fails_when_regression_metric_disappears(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "mixed",
                [
                    reference_line("check", frequency=0.5),
                    reference_line("bet", sizing=5.0, frequency=0.5),
                ],
            )
        ]
    )
    dataset_path = write_dataset(tmp_path / "recommendations.json", dataset)
    baseline_path = write_report(
        tmp_path / "baseline.json",
        run_recommendation_benchmark(
            dataset,
            SequenceProvider(
                [
                    recommendation(
                        "check",
                        candidates=[
                            {"action": "check", "sizing": None, "frequency": 0.5},
                            {"action": "bet", "sizing": 5.0, "frequency": 0.5},
                        ],
                    )
                ]
            ),
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--baseline-report",
            str(baseline_path),
            "--maximum-metric-regression",
            "average_policy_distance=0",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("check")]),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Average policy distance: not comparable" in captured.out
    assert (
        "Average policy distance was not evaluated in both recommendation reports"
        in captured.err
    )


@pytest.mark.parametrize(
    ("option", "scope", "expected_failure"),
    [
        (
            "--maximum-street-metric-regression",
            "flop",
            "Street flop: Action accuracy regressed 100.0 pts",
        ),
        (
            "--maximum-tag-metric-regression",
            "facing-bet",
            "Tag facing-bet: Action accuracy regressed 100.0 pts",
        ),
    ],
)
def test_recommendation_benchmark_cli_gates_scoped_regressions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    option: str,
    scope: str,
    expected_failure: str,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "flop",
                [reference_line("check")],
                tags=["facing-bet"],
            ),
            benchmark_case(
                "turn",
                [reference_line("check")],
                tags=["checked-to"],
                street="turn",
                board_cards=[
                    Card.from_code("Qs"),
                    Card.from_code("Jc"),
                    Card.from_code("2h"),
                    Card.from_code("4d"),
                ],
            ),
        ]
    )
    dataset_path = write_dataset(tmp_path / "recommendations.json", dataset)
    baseline_path = write_report(
        tmp_path / "baseline.json",
        run_recommendation_benchmark(
            dataset,
            SequenceProvider([recommendation("check"), recommendation("fold")]),
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--baseline-report",
            str(baseline_path),
            option,
            f"{scope}:action_accuracy=0",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("fold"), recommendation("check")]),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Action accuracy: +0.0 pts" in captured.out
    assert expected_failure in captured.err


def test_recommendation_benchmark_cli_gates_case_regression_hidden_by_totals(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "regressed",
                [reference_line("check")],
                tags=["single-raised-pot"],
            ),
            benchmark_case(
                "recovered",
                [reference_line("check")],
                tags=["single-raised-pot"],
            ),
        ]
    )
    dataset_path = write_dataset(tmp_path / "recommendations.json", dataset)
    baseline_path = write_report(
        tmp_path / "baseline.json",
        run_recommendation_benchmark(
            dataset,
            SequenceProvider(
                [
                    recommendation("check"),
                    recommendation("fold", fallback_reason="Unsupported spot"),
                ]
            ),
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--baseline-report",
            str(baseline_path),
            "--maximum-case-metric-regression",
            "action_accuracy=0",
            "--maximum-case-metric-regression",
            "fallback_rate=0",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider(
            [
                recommendation("fold", fallback_reason="Unsupported spot"),
                recommendation("check"),
            ]
        ),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Action accuracy: +0.0 pts" in captured.out
    assert (
        "Case regressed: Action accuracy regressed 100.0 pts"
        in captured.err
    )
    assert "Case regressed: Fallback rate regressed 100.0 pts" in captured.err
    assert "Case recovered:" not in captured.err


def test_recommendation_benchmark_cli_gates_lost_case_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "mixed",
                [
                    reference_line("check", frequency=0.5),
                    reference_line("bet", sizing=5.0, frequency=0.5),
                ],
            )
        ]
    )
    dataset_path = write_dataset(tmp_path / "recommendations.json", dataset)
    baseline_path = write_report(
        tmp_path / "baseline.json",
        run_recommendation_benchmark(
            dataset,
            SequenceProvider(
                [
                    recommendation(
                        "check",
                        candidates=[
                            {
                                "action": "check",
                                "sizing": None,
                                "frequency": 0.5,
                            },
                            {
                                "action": "bet",
                                "sizing": 5.0,
                                "frequency": 0.5,
                            },
                        ],
                    )
                ]
            ),
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--baseline-report",
            str(baseline_path),
            "--maximum-case-metric-regression",
            "average_policy_distance=0",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("check")]),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert (
        "Case mixed: Average policy distance is no longer evaluated"
        " (baseline 0.000)"
    ) in captured.err


def test_recommendation_benchmark_cli_skips_unevaluated_baseline_case_metric(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = benchmark_dataset(
        [benchmark_case("action-only", [reference_line("bet")])]
    )
    dataset_path = write_dataset(tmp_path / "recommendations.json", dataset)
    baseline_path = write_report(
        tmp_path / "baseline.json",
        run_recommendation_benchmark(
            dataset,
            SequenceProvider([recommendation("bet", sizing=5.0)]),
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--baseline-report",
            str(baseline_path),
            "--maximum-case-metric-regression",
            "line_accuracy=0",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("bet", sizing=5.0)]),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""


def test_recommendation_benchmark_cli_skips_fallback_for_errored_baseline_case(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = benchmark_dataset(
        [benchmark_case("recovered", [reference_line("check")])]
    )
    dataset_path = write_dataset(tmp_path / "recommendations.json", dataset)
    baseline_path = write_report(
        tmp_path / "baseline.json",
        run_recommendation_benchmark(
            dataset,
            SequenceProvider([RuntimeError("Solver unavailable")]),
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--baseline-report",
            str(baseline_path),
            "--maximum-case-metric-regression",
            "fallback_rate=0",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider(
            [recommendation("check", fallback_reason="Recovered with fallback")]
        ),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""


def test_recommendation_benchmark_cli_rejects_unknown_regression_scope(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = benchmark_dataset(
        [benchmark_case("action", [reference_line("check")])]
    )
    dataset_path = write_dataset(tmp_path / "recommendations.json", dataset)
    baseline_path = write_report(
        tmp_path / "baseline.json",
        run_recommendation_benchmark(
            dataset,
            SequenceProvider([recommendation("check")]),
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--baseline-report",
            str(baseline_path),
            "--maximum-street-metric-regression",
            "river:action_accuracy=0",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("check")]),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert (
        "Unknown recommendation benchmark street regression scope(s): river"
        in captured.err
    )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {"provider": "other"},
            "Recommendation baseline provider does not match",
        ),
        (
            {"dataset_fingerprint": "f" * 64},
            "Recommendation baseline corpus does not match",
        ),
        (
            {"dataset_fingerprint": None},
            "Recommendation baseline does not include a dataset fingerprint",
        ),
    ],
)
def test_recommendation_benchmark_cli_rejects_incomparable_baselines(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    updates: dict[str, object],
    message: str,
) -> None:
    dataset = benchmark_dataset(
        [benchmark_case("action", [reference_line("check")])]
    )
    dataset_path = write_dataset(tmp_path / "recommendations.json", dataset)
    report = run_recommendation_benchmark(
        dataset,
        SequenceProvider([recommendation("check")]),
    )
    baseline_path = write_report(
        tmp_path / "baseline.json",
        report.model_copy(update=updates),
    )

    exit_code = main(
        [str(dataset_path), "--baseline-report", str(baseline_path)],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("check")]),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert message in captured.err


def test_recommendation_benchmark_cli_rejects_inconsistent_baseline_cases(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = benchmark_dataset(
        [benchmark_case("action", [reference_line("check")])]
    )
    dataset_path = write_dataset(tmp_path / "recommendations.json", dataset)
    report = run_recommendation_benchmark(
        dataset,
        SequenceProvider([recommendation("check")]),
    )
    payload = report.model_dump(mode="json")
    payload["cases"][0]["case_id"] = "other"
    baseline_path = write_report(
        tmp_path / "baseline.json",
        RecommendationBenchmarkReport.model_validate(payload),
    )

    exit_code = main(
        [str(dataset_path), "--baseline-report", str(baseline_path)],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("check")]),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "Recommendation baseline cases do not match" in captured.err


def test_recommendation_benchmark_cli_requires_baseline_and_unique_metrics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            str(tmp_path / "unused.json"),
            "--maximum-metric-regression",
            "action_accuracy=0.1",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Metric regression thresholds require --baseline-report" in captured.err

    exit_code = main(
        [
            str(tmp_path / "unused.json"),
            "--maximum-case-metric-regression",
            "action_accuracy=0.1",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Metric regression thresholds require --baseline-report" in captured.err

    exit_code = main(
        [
            str(tmp_path / "unused.json"),
            "--maximum-street-metric-regression",
            "flop:action_accuracy=0.1",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Metric regression thresholds require --baseline-report" in captured.err

    exit_code = main(
        [
            str(tmp_path / "unused.json"),
            "--baseline-report",
            str(tmp_path / "unused-baseline.json"),
            "--maximum-metric-regression",
            "action_accuracy=0.1",
            "--maximum-metric-regression",
            "action_accuracy=0.2",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "repeats metric action_accuracy" in captured.err

    exit_code = main(
        [
            str(tmp_path / "unused.json"),
            "--baseline-report",
            str(tmp_path / "unused-baseline.json"),
            "--maximum-tag-metric-regression",
            "facing-bet:action_accuracy=0.1",
            "--maximum-tag-metric-regression",
            "facing-bet:action_accuracy=0.2",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert (
        "--maximum-tag-metric-regression repeats metric action_accuracy"
        " for facing-bet"
    ) in captured.err

    exit_code = main(
        [
            str(tmp_path / "unused.json"),
            "--baseline-report",
            str(tmp_path / "unused-baseline.json"),
            "--maximum-case-metric-regression",
            "action_accuracy=0.1",
            "--maximum-case-metric-regression",
            "action_accuracy=0.2",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert (
        "--maximum-case-metric-regression repeats metric action_accuracy"
        in captured.err
    )


def test_recommendation_baseline_report_rejects_invalid_and_oversized_files(
    tmp_path: Path,
) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{}", encoding="utf-8")

    with pytest.raises(RecommendationBenchmarkError, match="report is invalid"):
        load_recommendation_benchmark_report(invalid_path)

    dataset = benchmark_dataset(
        [benchmark_case("action", [reference_line("check")])]
    )
    inconsistent_payload = run_recommendation_benchmark(
        dataset,
        SequenceProvider([recommendation("check")]),
    ).model_dump(mode="json")
    inconsistent_payload["action_accuracy"] = 0.5
    inconsistent_path = tmp_path / "inconsistent.json"
    inconsistent_path.write_text(
        json.dumps(inconsistent_payload),
        encoding="utf-8",
    )
    with pytest.raises(RecommendationBenchmarkError, match="report is invalid"):
        load_recommendation_benchmark_report(inconsistent_path)

    oversized_path = tmp_path / "oversized.json"
    oversized_path.write_bytes(
        b"x" * (MAX_RECOMMENDATION_BENCHMARK_REPORT_BYTES + 1)
    )
    with pytest.raises(RecommendationBenchmarkError, match="exceeds the 16 MiB"):
        load_recommendation_benchmark_report(oversized_path)


def test_recommendation_benchmark_cli_resolves_relative_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invocation_dir = tmp_path / "repository-root"
    invocation_dir.mkdir()
    write_dataset(
        invocation_dir / "recommendations.json",
        benchmark_dataset(
            [benchmark_case("check", [reference_line("check")])]
        ),
    )
    monkeypatch.setenv("POKER_BENCHMARK_BASE_DIR", str(invocation_dir))

    exit_code = main(
        ["recommendations.json"],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("check")]),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Action agreement: 1/1 (100.0%)" in captured.out
    assert captured.err == ""


def test_cli_enforces_reference_source_and_evaluation_coverage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = write_dataset(
        tmp_path / "recommendations.json",
        benchmark_dataset(
            [
                benchmark_case(
                    "action-only",
                    [reference_line("bet")],
                )
            ]
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--require-reference-source",
            "--require-grading-reference",
            "--minimum-line-coverage",
            "1",
            "--minimum-policy-coverage",
            "1",
            "--minimum-ev-coverage",
            "1",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("bet", sizing=5.0)]),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Benchmark reference source is not recorded" in captured.err
    assert "Benchmark grading reference evidence is not recorded" in captured.err
    assert "Line evaluation coverage 0.0% is below the minimum 100.0%" in (
        captured.err
    )
    assert "Policy evaluation coverage 0.0% is below the minimum 100.0%" in (
        captured.err
    )
    assert "EV evaluation coverage 0.0% is below the minimum 100.0%" in captured.err


def test_cli_enforces_range_conditioning_accuracy_and_coverage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    turn_state = {
        "street": "turn",
        "board_cards": [
            Card.from_code("Qs"),
            Card.from_code("Jc"),
            Card.from_code("2h"),
            Card.from_code("4d"),
        ],
    }
    dataset_path = write_dataset(
        tmp_path / "recommendations.json",
        benchmark_dataset(
            [
                benchmark_case(
                    "conditioning-applied",
                    [reference_line("check")],
                    expected_range_conditioning="applied",
                    **turn_state,
                ),
                benchmark_case(
                    "conditioning-wrong",
                    [reference_line("check")],
                    expected_range_conditioning="applied",
                    **turn_state,
                ),
                benchmark_case(
                    "conditioning-missing",
                    [reference_line("check")],
                    expected_range_conditioning="skipped",
                    **turn_state,
                ),
            ]
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--minimum-conditioning-accuracy",
            "1",
            "--minimum-conditioning-coverage",
            "1",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider(
            [
                recommendation("check", range_conditioning={"status": "applied"}),
                recommendation("check", range_conditioning={"status": "skipped"}),
                recommendation("check"),
            ]
        ),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert (
        "Range conditioning agreement 50.0% is below the minimum 100.0%"
        in captured.err
    )
    assert (
        "Range conditioning evidence coverage 66.7% is below the minimum 100.0%"
        in captured.err
    )


def test_cli_enforces_range_source_accuracy_and_coverage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_source = "preflop_chart_single_raised_pot"
    dataset_path = write_dataset(
        tmp_path / "recommendations.json",
        benchmark_dataset(
            [
                benchmark_case(
                    "range-source-correct",
                    [reference_line("check")],
                    expected_range_source=expected_source,
                ),
                benchmark_case(
                    "range-source-wrong",
                    [reference_line("check")],
                    expected_range_source=expected_source,
                ),
                benchmark_case(
                    "range-source-missing",
                    [reference_line("check")],
                    expected_range_source="configured",
                ),
            ]
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--minimum-range-source-accuracy",
            "1",
            "--minimum-range-source-coverage",
            "1",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider(
            [
                recommendation("check", range_source=expected_source),
                recommendation(
                    "check",
                    range_source="preflop_chart_three_bet_pot",
                ),
                recommendation("check"),
            ]
        ),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert (
        "Range source agreement 50.0% is below the minimum 100.0%"
        in captured.err
    )
    assert (
        "Range source evidence coverage 66.7% is below the minimum 100.0%"
        in captured.err
    )


def test_cli_fails_when_a_required_optional_metric_is_unavailable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = write_dataset(
        tmp_path / "recommendations.json",
        benchmark_dataset(
            [
                benchmark_case(
                    "action-only",
                    [reference_line("bet")],
                )
            ]
        ),
    )

    exit_code = main(
        [str(dataset_path), "--minimum-line-accuracy", "0"],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("bet", sizing=5.0)]),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Line accuracy was not evaluated" in captured.err


def test_cli_fails_when_range_conditioning_is_not_expected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = write_dataset(
        tmp_path / "recommendations.json",
        benchmark_dataset(
            [benchmark_case("action-only", [reference_line("check")])]
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--minimum-conditioning-accuracy",
            "0",
            "--minimum-conditioning-coverage",
            "0",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("check")]),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Range conditioning agreement was not evaluated" in captured.err
    assert (
        "Range conditioning evidence coverage was not evaluated" in captured.err
    )


def test_cli_fails_when_range_source_is_not_expected(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = write_dataset(
        tmp_path / "recommendations.json",
        benchmark_dataset(
            [benchmark_case("action-only", [reference_line("check")])]
        ),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--minimum-range-source-accuracy",
            "0",
            "--minimum-range-source-coverage",
            "0",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=SequenceProvider([recommendation("check")]),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Range source agreement was not evaluated" in captured.err
    assert "Range source evidence coverage was not evaluated" in captured.err


def test_cli_reports_unknown_provider_as_configuration_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = write_dataset(
        tmp_path / "recommendations.json",
        benchmark_dataset(
            [benchmark_case("check", [reference_line("check")])]
        ),
    )

    exit_code = main(
        [str(dataset_path), "--provider", "unknown"],
        settings=Settings(data_dir=tmp_path / "unused"),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Unknown recommendation provider: unknown" in captured.err


def test_cli_reports_deferred_provider_configuration_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = write_dataset(
        tmp_path / "recommendations.json",
        benchmark_dataset(
            [benchmark_case("check", [reference_line("check")])]
        ),
    )
    provider = SequenceProvider(
        [ProviderConfigurationError("provider URL is required")]
    )

    exit_code = main(
        [str(dataset_path)],
        settings=Settings(data_dir=tmp_path / "unused"),
        provider=provider,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "provider URL is required" in captured.err


def test_cli_reports_environment_settings_validation_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = write_dataset(
        tmp_path / "recommendations.json",
        benchmark_dataset(
            [benchmark_case("check", [reference_line("check")])]
        ),
    )
    raw_value = "not-a-number-sensitive-sentinel"
    monkeypatch.setenv("POKER_EXTERNAL_REQUEST_TIMEOUT_SECONDS", raw_value)
    get_settings.cache_clear()

    try:
        exit_code = main([str(dataset_path)])
    finally:
        get_settings.cache_clear()

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Settings configuration is invalid" in captured.err
    assert "external_request_timeout_seconds" in captured.err
    assert raw_value not in captured.err


def test_benchmark_file_uses_configured_provider(tmp_path: Path) -> None:
    path = write_dataset(
        tmp_path / "recommendations.json",
        benchmark_dataset(
            [benchmark_case("check", [reference_line("check")])]
        ),
    )

    report = benchmark_recommendation_file(
        path,
        Settings(
            data_dir=tmp_path / "unused",
            recommendation_provider="mock",
        ),
    )

    assert report.provider == "mock"
    assert report.total_cases == 1


def test_recommendation_benchmark_scores_local_solver_range_source(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual range response', "
        "'raw': {"
        "'provider': 'local_solver', 'engine': 'postflop_solver', "
        "'range_source': os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE']"
        "}}))\n",
        encoding="utf-8",
    )
    expected_source = "preflop_chart_single_raised_pot"
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "postflop-single-raised-range-source",
                [reference_line("check")],
                tags=["postflop", "single-raised-pot", "range-source"],
                expected_range_source=expected_source,
                pot_size=5.5,
                current_bet=0,
                hero_stack=97.5,
                opponent_stack=97.5,
                effective_stack=97.5,
                hero_position="button",
                opponent_position="big_blind",
                preflop_opener_position="button",
                preflop_open_size=2.5,
                preflop_action_history=[
                    PreflopAction(actor="button", action="raise", amount=2.5),
                    PreflopAction(actor="big_blind", action="call", amount=2.5),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.range_source_expected_cases == 1
    assert report.range_source_evaluated_cases == 1
    assert report.range_source_correct_cases == 1
    assert report.range_source_accuracy == 1
    assert report.range_source_coverage == 1
    assert report.cases[0].range_source == expected_source
    assert report.cases[0].range_source_match is True


def test_recommendation_benchmark_runs_isolation_response_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-facing-isolation-raise-after-limp",
                [reference_line("call")],
                tags=["preflop", "isolation-raise", "hero-limp"],
                hero_cards=[Card.from_code("9h"), Card.from_code("9s")],
                board_cards=[],
                street="preflop",
                pot_size=6.5,
                current_bet=3,
                hero_stack=99,
                effective_stack=90,
                players_in_hand=2,
                hero_position="utg",
                facing_action="raise",
                preflop_action_history=[
                    PreflopAction(actor="utg", action="call", amount=1),
                    PreflopAction(actor="button", action="raise", amount=4),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"


def test_recommendation_benchmark_runs_limp_reraise_preflop_chart(
    tmp_path: Path,
) -> None:
    dataset = benchmark_dataset(
        [
            benchmark_case(
                "preflop-facing-limp-reraise",
                [reference_line("call")],
                tags=["preflop", "limp-reraise", "hero-isolation"],
                hero_cards=[Card.from_code("Th"), Card.from_code("Ts")],
                board_cards=[],
                street="preflop",
                pot_size=17.5,
                current_bet=8,
                hero_stack=96,
                effective_stack=88,
                players_in_hand=2,
                hero_position="button",
                facing_action="raise",
                preflop_action_history=[
                    PreflopAction(actor="utg", action="call", amount=1),
                    PreflopAction(actor="button", action="raise", amount=4),
                    PreflopAction(actor="utg", action="raise", amount=12),
                ],
            )
        ]
    )
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )

    report = run_recommendation_benchmark(dataset, provider)

    assert report.completed_cases == 1
    assert report.action_correct == 1
    assert report.line_correct == 1
    assert report.fallback_cases == 0
    assert report.cases[0].engine == "preflop_chart_v1"
