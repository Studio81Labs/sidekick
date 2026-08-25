import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import KNOWN_RECOMMENDATION_PROVIDERS, Settings
from app.domain.poker import (
    CanonicalState,
    Card,
    CompletedPostflopAction,
    CompletedPostflopStreetHistory,
    PostflopAction,
    PreflopAction,
)
from app.domain.recommendations import RecommendationRequest
from app.providers.base import (
    ProviderConfigurationError,
    ProviderError,
    ProviderInputError,
    missing_required_fields,
)
from app.providers.local_solver import _postflop_position
from app.providers.registry import (
    RECOMMENDATION_PLUGINS,
    RECOMMENDATION_PLUGIN_IDS,
    RecommendationPlugin,
    _plugin_catalog,
    build_provider,
    get_recommendation_plugin,
)
from app.solvers.ev_solver_cli import _hero_outcomes
from app.solvers.wager_context import (
    resolve_hero_wager,
    resolve_opponent_commitment_total,
    resolve_opponent_wager,
)


def approved_state() -> CanonicalState:
    return CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
        board_cards=[Card.from_code("Qs"), Card.from_code("Jc"), Card.from_code("2h")],
        pot_size=12.5,
        current_bet=2.5,
        hero_stack=97.5,
        effective_stack=96.0,
        players_in_hand=3,
        opponents_at_current_bet=1,
        hero_position="button",
        street="flop",
        facing_action="bet",
        action_context="Cutoff bet 2.5 into 12.5",
        user_approved=True,
    )


def heads_up_postflop_state() -> CanonicalState:
    state = approved_state().model_copy(deep=True)
    state.players_in_hand = 2
    state.hero_position = "IP"
    return state


@pytest.mark.parametrize(
    ("hero_position", "opponent_position", "expected"),
    [
        ("IP", None, "ip"),
        ("button", None, "ip"),
        ("BB", "button", "oop"),
        ("cutoff", "HJ", "ip"),
        ("HJ", "cutoff", "oop"),
        ("under-the-gun", "CO", "oop"),
        ("middle", "early", "ip"),
        (None, "IP", "oop"),
        ("IP", "IP", None),
        ("SB", "BB", None),
        ("cutoff", None, None),
    ],
)
def test_postflop_position_inference(
    hero_position: str | None,
    opponent_position: str | None,
    expected: str | None,
) -> None:
    assert _postflop_position(hero_position, opponent_position) == expected


def raised_postflop_state() -> CanonicalState:
    state = heads_up_postflop_state()
    state.pot_size = 19.0
    state.current_bet = 5.0
    state.hero_stack = 98.0
    state.opponent_stack = 93.0
    state.effective_stack = 93.0
    state.hero_position = "OOP"
    state.facing_action = "raise"
    state.postflop_action_history = [
        PostflopAction(actor="oop", action="bet", amount=2.0),
        PostflopAction(actor="ip", action="raise", amount=7.0),
    ]
    return state


def test_mock_provider_uses_rule_based_training_recommendation(tmp_path: Path) -> None:
    provider = build_provider(Settings(data_dir=tmp_path, recommendation_provider="mock"))
    request = RecommendationRequest(state=approved_state(), provider=provider.name)

    result = provider.recommend(request)

    assert result.action == "call"
    assert result.sizing is None
    assert "rule-based training recommendation" in result.explanation.lower()
    assert result.raw["provider"] == "mock"
    assert result.raw["engine"] == "rule_based_training_v2"
    assert "equity" in result.raw


def test_rule_based_provider_checks_missed_flop_with_no_bet(tmp_path: Path) -> None:
    provider = build_provider(Settings(data_dir=tmp_path, recommendation_provider="rule_based"))
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("9c")],
        board_cards=[Card.from_code("Th"), Card.from_code("Kd"), Card.from_code("4c")],
        pot_size=10,
        current_bet=0,
        effective_stack=16.1,
        players_in_hand=4,
        street="flop",
        user_approved=True,
    )

    result = provider.recommend(RecommendationRequest(state=state, provider=provider.name))

    assert result.action == "check"
    assert result.sizing is None
    assert result.raw["provider"] == "rule_based"
    assert result.raw["hand_category"] == "high card"
    assert result.raw["equity"]["iterations"] > 0


def test_rule_based_provider_controls_weak_top_pair_multiway(tmp_path: Path) -> None:
    provider = build_provider(Settings(data_dir=tmp_path, recommendation_provider="rule_based"))
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("7d")],
        board_cards=[Card.from_code("As"), Card.from_code("8s"), Card.from_code("Qh")],
        pot_size=3,
        current_bet=0,
        effective_stack=96.5,
        players_in_hand=3,
        street="flop",
        user_approved=True,
    )

    result = provider.recommend(RecommendationRequest(state=state, provider=provider.name))

    assert result.action == "check"
    assert result.sizing is None
    assert result.raw["hand_category"] == "one pair"
    assert result.raw["top_pair_kicker"] == 7
    assert result.raw["wet_board"] is True


def test_rule_based_provider_folds_weak_offsuit_preflop_call(tmp_path: Path) -> None:
    provider = build_provider(Settings(data_dir=tmp_path, recommendation_provider="rule_based"))
    state = CanonicalState(
        hero_cards=[Card.from_code("Kc"), Card.from_code("7d")],
        pot_size=4.5,
        current_bet=2.5,
        effective_stack=38.3,
        players_in_hand=3,
        street="preflop",
        user_approved=True,
    )

    result = provider.recommend(RecommendationRequest(state=state, provider=provider.name))

    assert result.action == "fold"
    assert result.sizing is None
    assert result.raw["provider"] == "rule_based"
    assert result.raw["realized_equity"] < result.raw["required_equity"]


def test_rule_based_provider_defends_ace_high_heads_up_preflop(tmp_path: Path) -> None:
    provider = build_provider(Settings(data_dir=tmp_path, recommendation_provider="rule_based"))
    state = CanonicalState(
        hero_cards=[Card.from_code("7d"), Card.from_code("Ah")],
        pot_size=3.5,
        current_bet=1.5,
        effective_stack=100.4,
        players_in_hand=2,
        street="preflop",
        user_approved=True,
    )

    result = provider.recommend(RecommendationRequest(state=state, provider=provider.name))

    assert result.action == "call"
    assert result.sizing is None
    assert result.raw["realized_equity"] > result.raw["required_equity"]


def test_rule_based_provider_bets_strong_made_hand(tmp_path: Path) -> None:
    provider = build_provider(Settings(data_dir=tmp_path, recommendation_provider="rule_based"))
    state = CanonicalState(
        hero_cards=[Card.from_code("Kh"), Card.from_code("Ks")],
        board_cards=[Card.from_code("Kd"), Card.from_code("7c"), Card.from_code("2h")],
        pot_size=10,
        current_bet=0,
        effective_stack=80,
        players_in_hand=2,
        street="flop",
        user_approved=True,
    )

    result = provider.recommend(RecommendationRequest(state=state, provider=provider.name))

    assert result.action == "bet"
    assert result.sizing == 7
    assert "strong made hand" in result.explanation.lower()


def test_required_field_validation_reports_missing_values() -> None:
    state = CanonicalState(street="flop", user_approved=True)

    assert missing_required_fields(state, ["hero_cards", "street"]) == ["hero_cards"]


def test_required_field_validation_treats_blank_strings_as_missing() -> None:
    state = CanonicalState(hero_position="  ", street="flop", user_approved=True)

    assert missing_required_fields(state, ["hero_position", "street"]) == ["hero_position"]


def test_required_field_validation_rejects_unknown_field() -> None:
    state = CanonicalState(street="flop", user_approved=True)

    with pytest.raises(ProviderConfigurationError, match="Unknown required field: missing_field"):
        missing_required_fields(state, ["missing_field"])
    with pytest.raises(ProviderConfigurationError, match="Unknown required field: model_dump"):
        missing_required_fields(state, ["model_dump"])


def test_registry_rejects_unknown_provider(tmp_path: Path) -> None:
    with pytest.raises(ProviderConfigurationError, match="Unknown recommendation provider"):
        build_provider(Settings(data_dir=tmp_path, recommendation_provider="missing"))


def test_recommendation_plugin_catalog_matches_configuration_allowlist(
    tmp_path: Path,
) -> None:
    assert RECOMMENDATION_PLUGIN_IDS == KNOWN_RECOMMENDATION_PROVIDERS
    assert list(RECOMMENDATION_PLUGINS) == [
        "rule_based",
        "mock",
        "local_solver",
        "external_solver",
        "llm_advice",
    ]

    assert get_recommendation_plugin("rule_based").label == "Rule-based training"
    assert get_recommendation_plugin("mock").label == "Mock recommendation"
    assert get_recommendation_plugin("local_solver").label == "Local solver"

    external = get_recommendation_plugin("external_solver")
    assert external.label == "External solver"
    assert external.unavailable_reason(Settings(data_dir=tmp_path)) == (
        "External solver URL is not configured"
    )
    assert (
        external.unavailable_reason(
            Settings(
                data_dir=tmp_path,
                external_provider_url="https://solver.example.com/recommend",
            )
        )
        is None
    )

    llm = get_recommendation_plugin("llm_advice")
    assert llm.label == "LLM advice"
    assert llm.unavailable_reason(Settings(data_dir=tmp_path)) == (
        "LLM advice URL is not configured"
    )
    assert (
        llm.unavailable_reason(
            Settings(
                data_dir=tmp_path,
                llm_advice_url="https://llm.example.com/recommend",
            )
        )
        is None
    )


def test_recommendation_plugin_rejects_factory_identity_mismatch(
    tmp_path: Path,
) -> None:
    mismatched = RecommendationPlugin(
        id="different",
        label="Different provider",
        factory=RECOMMENDATION_PLUGINS["mock"].factory,
    )

    with pytest.raises(
        ProviderConfigurationError,
        match="built provider 'mock'",
    ):
        mismatched.build(Settings(data_dir=tmp_path))


def test_recommendation_plugin_catalog_rejects_invalid_descriptors() -> None:
    factory = RECOMMENDATION_PLUGINS["mock"].factory

    with pytest.raises(ValueError, match="identity fields"):
        RecommendationPlugin(id="", label="Missing ID", factory=factory)
    with pytest.raises(TypeError, match="factory must be callable"):
        RecommendationPlugin(  # type: ignore[arg-type]
            id="invalid_factory",
            label="Invalid factory",
            factory=None,
        )
    with pytest.raises(TypeError, match="availability check must be callable"):
        RecommendationPlugin(  # type: ignore[arg-type]
            id="invalid_availability",
            label="Invalid availability",
            factory=factory,
            availability_check="invalid",
        )
    with pytest.raises(ValueError, match="IDs must be unique"):
        _plugin_catalog(
            RECOMMENDATION_PLUGINS["mock"],
            RECOMMENDATION_PLUGINS["mock"],
        )


def test_local_solver_uses_bundled_solver_when_command_is_missing(tmp_path: Path) -> None:
    provider = build_provider(Settings(data_dir=tmp_path, recommendation_provider="local_solver"))
    request = RecommendationRequest(state=approved_state(), provider=provider.name)

    result = provider.recommend(request)

    assert result.action == "call"
    assert result.raw["provider"] == "local_solver"
    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["requested_engine"] == "postflop_solver"
    assert result.raw["opponents_at_current_bet"] == 1
    assert "heads-up postflop" in result.raw["fallback_reason"]
    assert result.raw["equity"]["method"] == "monte_carlo_range"
    assert len(result.raw["candidates"]) >= 2
    assert "solver compared candidate actions" in result.explanation.lower()
    assert "every opponent to fold" in result.explanation.lower()
    wager_candidates = [
        candidate
        for candidate in result.raw["candidates"]
        if candidate["fold_equity"] is not None
    ]
    assert wager_candidates
    for candidate in wager_candidates:
        per_opponent = candidate["per_opponent_fold_equity"]
        assert candidate["fold_equity"] == pytest.approx(per_opponent**2)
        continuations = candidate["continuations"]
        assert [branch["callers"] for branch in continuations] == [1, 2]
        assert continuations[0]["probability"] == pytest.approx(
            2 * (1 - per_opponent) * per_opponent
        )
        assert continuations[1]["probability"] == pytest.approx(
            (1 - per_opponent) ** 2
        )
        assert continuations[0]["existing_wager_adjustment"] == 1.25
        assert continuations[1]["existing_wager_adjustment"] == 2.5
        assert continuations[0]["final_pot"] == pytest.approx(
            approved_state().pot_size + 2 * candidate["sizing"] - 1.25
        )
        assert continuations[1]["final_pot"] == pytest.approx(
            approved_state().pot_size + 3 * candidate["sizing"] - 2.5
        )
        assert candidate["fold_equity"] + sum(
            branch["probability"] for branch in continuations
        ) == pytest.approx(1)
        assert candidate["ev"] == pytest.approx(
            candidate["fold_equity"] * approved_state().pot_size
            + sum(
                branch["probability"] * branch["ev"] for branch in continuations
            ),
            abs=0.002,
        )


def test_local_solver_requires_committed_opponent_count_for_multiway_bet(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = approved_state().model_copy(
        update={"opponents_at_current_bet": None}
    )

    assert "opponents_at_current_bet" in provider.required_fields_for(state)


def test_local_solver_requires_total_wager_when_it_cannot_be_derived(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
        pot_size=4,
        current_bet=1.5,
        effective_stack=99,
        players_in_hand=2,
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert "opponent_wager" in provider.required_fields_for(state)


def test_opponent_wager_resolution_uses_reviewed_and_structured_context() -> None:
    base = CanonicalState(
        current_bet=1.5,
        hero_position="big_blind",
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert resolve_opponent_wager(base) is None
    assert resolve_opponent_wager(
        base.model_copy(update={"opponent_wager": 3.0})
    ) == 3.0
    assert resolve_opponent_wager(
        base.model_copy(
            update={
                "preflop_action_history": [
                    PreflopAction(actor="cutoff", action="raise", amount=2.5),
                    PreflopAction(actor="button", action="call", amount=2.5),
                ]
            }
        )
    ) == 2.5
    assert resolve_opponent_wager(
        base.model_copy(update={"preflop_open_size": 2.5})
    ) == 2.5
    assert resolve_opponent_wager(
        base.model_copy(update={"action_context": "Cutoff opens to 2.5 BB"})
    ) == 2.5
    assert resolve_opponent_wager(
        base.model_copy(update={"street": "flop", "facing_action": "bet"})
    ) == 1.5
    assert resolve_opponent_wager(
        base.model_copy(
            update={
                "current_bet": 2,
                "hero_position": "cutoff",
                "preflop_open_size": 3,
                "action_context": "Cutoff opens to 3 BB, then button reraises",
            }
        )
    ) is None
    assert resolve_opponent_wager(
        base.model_copy(
            update={"facing_action": "bet", "preflop_open_size": 2.5}
        )
    ) is None

    reraised = CanonicalState(
        current_bet=2,
        players_in_hand=2,
        opponents_at_current_bet=1,
        hero_position="cutoff",
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=3),
            PreflopAction(actor="button", action="raise", amount=5),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )
    assert resolve_opponent_commitment_total(
        reraised,
        opponent_wager=5,
        opponents_at_current_bet=1,
    ) == 5
    ambiguous_multiway = reraised.model_copy(
        update={"players_in_hand": 3, "hero_position": None}
    )
    assert resolve_opponent_commitment_total(
        ambiguous_multiway,
        opponent_wager=5,
        opponents_at_current_bet=1,
    ) is None

    big_blind_option = CanonicalState(
        pot_size=3.5,
        current_bet=0,
        players_in_hand=3,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="call", amount=1),
            PreflopAction(actor="button", action="call", amount=1),
        ],
        street="preflop",
        user_approved=True,
    )
    hero_wager = resolve_hero_wager(big_blind_option, opponent_wager=0)
    assert hero_wager == 1
    assert resolve_opponent_commitment_total(
        big_blind_option,
        opponent_wager=0,
        opponents_at_current_bet=0,
        hero_wager=hero_wager,
    ) == 2


def test_local_ev_uses_total_preflop_wager_in_continuation_pots(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_engine="local_ev",
        )
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
        pot_size=4,
        current_bet=1.5,
        effective_stack=99,
        players_in_hand=2,
        hero_position="big_blind",
        preflop_open_size=2.5,
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["opponent_wager"] == 2.5
    assert result.raw["hero_wager"] == 1
    wager_candidates = [
        candidate
        for candidate in result.raw["candidates"]
        if candidate["fold_equity"] is not None
    ]
    assert wager_candidates
    for candidate in wager_candidates:
        continuation = candidate["continuations"][0]
        assert continuation["existing_wager_adjustment"] == 1.5
        assert continuation["final_pot"] == pytest.approx(
            state.pot_size + 2 * candidate["sizing"] - state.current_bet
        )
        assert continuation["ev"] == pytest.approx(
            continuation["called_equity"] * continuation["final_pot"]
            - candidate["sizing"],
            abs=0.001,
        )


def test_local_ev_reconstructs_multiway_calls_from_both_existing_wagers(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_engine="local_ev",
        )
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
        pot_size=5,
        current_bet=1.5,
        effective_stack=99,
        players_in_hand=3,
        opponents_at_current_bet=1,
        opponent_wager=2.5,
        opponent_commitment_total=2.5,
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["hero_wager"] == 1
    wager_candidates = [
        candidate
        for candidate in result.raw["candidates"]
        if candidate["fold_equity"] is not None
    ]
    assert wager_candidates
    for candidate in wager_candidates:
        continuations = candidate["continuations"]
        assert continuations[0]["existing_wager_adjustment"] == 0.25
        assert continuations[1]["existing_wager_adjustment"] == 0.5
        for continuation in continuations:
            callers = continuation["callers"]
            assert continuation["final_pot"] == pytest.approx(
                state.pot_size
                + (callers + 1) * candidate["sizing"]
                - continuation["existing_wager_adjustment"]
            )


def test_local_ev_includes_every_recorded_opponent_commitment(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_engine="local_ev",
        )
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
        pot_size=14.5,
        current_bet=9,
        effective_stack=99,
        players_in_hand=3,
        opponents_at_current_bet=1,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=3),
            PreflopAction(actor="button", action="raise", amount=10),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["opponent_wager"] == 10
    assert result.raw["opponent_commitment_total"] == 13
    assert result.raw["hero_wager"] == 1
    wager_candidates = [
        candidate
        for candidate in result.raw["candidates"]
        if candidate["fold_equity"] is not None
    ]
    assert wager_candidates
    for candidate in wager_candidates:
        continuations = candidate["continuations"]
        assert continuations[0]["existing_wager_adjustment"] == 5.5
        assert continuations[1]["existing_wager_adjustment"] == 11
        for continuation in continuations:
            callers = continuation["callers"]
            expected_opponent_commitment = 13 * callers / 2
            expected_caller_contribution = (
                callers * (candidate["sizing"] + 1)
                - expected_opponent_commitment
            )
            assert continuation["final_pot"] == pytest.approx(
                state.pot_size
                + candidate["sizing"]
                + expected_caller_contribution
            )


def test_local_ev_requires_multiway_postflop_commitment_total(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_engine="local_ev",
        )
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
        board_cards=[
            Card.from_code("Qs"),
            Card.from_code("Jc"),
            Card.from_code("2h"),
        ],
        pot_size=30,
        current_bet=15,
        effective_stack=85,
        players_in_hand=3,
        opponents_at_current_bet=1,
        opponent_wager=15,
        hero_position="button",
        street="flop",
        facing_action="raise",
        user_approved=True,
    )

    assert "opponent_commitment_total" in provider.required_fields_for(state)

    reviewed_state = state.model_copy(
        update={"opponent_commitment_total": 20}
    )
    result = provider.recommend(
        RecommendationRequest(state=reviewed_state, provider=provider.name)
    )

    assert result.raw["opponent_commitment_total"] == 20
    wager_candidates = [
        candidate
        for candidate in result.raw["candidates"]
        if candidate["fold_equity"] is not None
    ]
    assert wager_candidates
    for candidate in wager_candidates:
        continuations = candidate["continuations"]
        assert continuations[0]["existing_wager_adjustment"] == 10
        assert continuations[1]["existing_wager_adjustment"] == 20


def test_local_ev_accounts_for_multiple_opponents_already_at_bet(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_engine="local_ev",
        )
    )
    state = approved_state().model_copy(
        update={"opponents_at_current_bet": 2}
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    wager_candidates = [
        candidate
        for candidate in result.raw["candidates"]
        if candidate["fold_equity"] is not None
    ]
    assert wager_candidates
    for candidate in wager_candidates:
        assert candidate["continuations"][0]["existing_wager_adjustment"] == 2.5
        assert candidate["continuations"][1]["existing_wager_adjustment"] == 5


def test_local_ev_preserves_heads_up_fold_equity(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_engine="local_ev",
        )
    )

    result = provider.recommend(
        RecommendationRequest(state=heads_up_postflop_state(), provider=provider.name)
    )

    wager_candidates = [
        candidate
        for candidate in result.raw["candidates"]
        if candidate["fold_equity"] is not None
    ]
    assert wager_candidates
    for candidate in wager_candidates:
        assert candidate["fold_equity"] == candidate["per_opponent_fold_equity"]
        assert len(candidate["continuations"]) == 1
        assert candidate["continuations"][0]["callers"] == 1
        assert candidate["continuations"][0]["probability"] == pytest.approx(
            1 - candidate["fold_equity"]
        )
        assert candidate["continuations"][0]["existing_wager_adjustment"] == 2.5
        assert candidate["continuations"][0]["final_pot"] == pytest.approx(
            12.5 + 2 * candidate["sizing"] - 2.5
        )
    assert "every opponent to fold" not in result.explanation.lower()


def test_multiway_outcomes_track_each_surviving_field_size() -> None:
    tied_board = [Card.from_code(code) for code in ("As", "Ks", "Qs", "Js", "Ts")]
    tied_outcomes = _hero_outcomes(
        [Card.from_code("2c"), Card.from_code("3d")],
        [
            [Card.from_code("4c"), Card.from_code("5d")],
            [Card.from_code("6c"), Card.from_code("7d")],
        ],
        tied_board,
    )
    assert tied_outcomes[1] == 0.5
    assert tied_outcomes[2] == pytest.approx(1 / 3)

    changing_outcomes = _hero_outcomes(
        [Card.from_code("Ah"), Card.from_code("Kd")],
        [
            [Card.from_code("Qh"), Card.from_code("Jd")],
            [Card.from_code("6h"), Card.from_code("7d")],
        ],
        [Card.from_code(code) for code in ("2c", "3d", "4h", "5s", "9c")],
    )
    assert changing_outcomes == {1: 1.0, 2: 0.0}


def test_local_solver_uses_bundled_solver_when_command_is_blank(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command="   ",
        )
    )

    result = provider.recommend(
        RecommendationRequest(state=approved_state(), provider=provider.name)
    )

    assert result.raw["provider"] == "local_solver"
    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["requested_engine"] == "postflop_solver"


def test_local_solver_can_select_bundled_ev_engine(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_engine="local_ev",
        )
    )

    result = provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert "requested_engine" not in result.raw


def test_local_ev_selection_bypasses_supported_preflop_chart(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_engine="local_ev",
        )
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("2h")],
        pot_size=1.5,
        current_bet=0,
        effective_stack=100,
        players_in_hand=6,
        hero_position="button",
        street="preflop",
        user_approved=True,
    )

    result = provider.recommend(RecommendationRequest(state=state, provider=provider.name))

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert "requested_engine" not in result.raw
    assert "routing_reason" not in result.raw


def test_local_ev_accounts_for_posted_blinds_in_open_branches(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_engine="local_ev",
        )
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("2h")],
        pot_size=1.5,
        current_bet=0,
        effective_stack=100,
        players_in_hand=3,
        hero_position="button",
        street="preflop",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["hero_wager"] == 0
    assert result.raw["opponent_commitment_total"] == 1.5
    open_candidate = next(
        candidate
        for candidate in result.raw["candidates"]
        if candidate["action"] == "bet" and candidate["sizing"] == 2.5
    )
    continuations = open_candidate["continuations"]
    assert [branch["callers"] for branch in continuations] == [1, 2]
    assert continuations[0]["existing_wager_adjustment"] == 0.75
    assert continuations[0]["final_pot"] == 5.75
    assert continuations[1]["existing_wager_adjustment"] == 1.5
    assert continuations[1]["final_pot"] == 7.5


@pytest.mark.parametrize("fallback_enabled", [True, False])
def test_local_solver_routes_supported_preflop_spot_to_chart(
    tmp_path: Path, fallback_enabled: bool
) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=fallback_enabled,
        )
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("2h")],
        pot_size=1.5,
        current_bet=0,
        effective_stack=100,
        players_in_hand=6,
        hero_position="button",
        street="preflop",
        user_approved=True,
    )

    result = provider.recommend(RecommendationRequest(state=state, provider=provider.name))

    assert result.action == "raise"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["requested_engine"] == "postflop_solver"
    assert result.raw["routing_reason"] == "the hand is preflop"
    assert "fallback_reason" not in result.raw
    assert "routed this hand to the preflop chart" in result.explanation
    assert "range/EV fallback" not in result.explanation


def test_local_solver_requires_hero_stack_for_structured_three_bet(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=12,
        current_bet=5.5,
        effective_stack=92,
        players_in_hand=6,
        hero_position="cutoff",
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert "hero_stack" in provider.required_fields_for(state)


def test_local_solver_requires_hero_stack_for_cold_three_bet(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=12,
        current_bet=7,
        effective_stack=92,
        players_in_hand=3,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert "hero_stack" in provider.required_fields_for(state)


def test_local_solver_requires_hero_stack_for_squeeze_response(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=16,
        current_bet=7.5,
        effective_stack=90,
        players_in_hand=2,
        hero_position="button",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="button", action="call", amount=2.5),
            PreflopAction(actor="small_blind", action="raise", amount=10),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert "hero_stack" in provider.required_fields_for(state)


def test_local_solver_requires_hero_stack_when_facing_four_bet(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=29.5,
        current_bet=12,
        effective_stack=80,
        players_in_hand=2,
        hero_position="button",
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
            PreflopAction(actor="cutoff", action="raise", amount=20),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert "hero_stack" in provider.required_fields_for(state)


def test_local_solver_requires_hero_stack_when_facing_cold_four_bet(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=32,
        current_bet=12,
        effective_stack=80,
        players_in_hand=2,
        hero_position="cutoff",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="cutoff", action="raise", amount=8),
            PreflopAction(actor="button", action="raise", amount=20),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert "hero_stack" in provider.required_fields_for(state)


def test_local_solver_does_not_require_hero_stack_for_hidden_four_bet_player(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=29.5,
        current_bet=12,
        effective_stack=80,
        players_in_hand=3,
        hero_position="button",
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
            PreflopAction(actor="cutoff", action="raise", amount=20),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert "hero_stack" not in provider.required_fields_for(state)


def test_local_solver_does_not_require_hero_stack_for_oversized_four_bet(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=38.5,
        current_bet=21,
        effective_stack=71,
        players_in_hand=2,
        hero_position="button",
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
            PreflopAction(actor="cutoff", action="raise", amount=29),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert "hero_stack" not in provider.required_fields_for(state)


def test_local_solver_does_not_require_hero_stack_for_unsupported_history(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=12,
        current_bet=5.5,
        effective_stack=92,
        players_in_hand=6,
        hero_position="cutoff",
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="call", amount=8),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert "hero_stack" not in provider.required_fields_for(state)


@pytest.mark.parametrize(
    "settings_override",
    [
        {"local_solver_engine": "local_ev"},
        {"local_solver_command": "external-solver"},
    ],
)
def test_local_solver_does_not_require_chart_fields_for_other_engines(
    tmp_path: Path,
    settings_override: dict[str, str],
) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            **settings_override,
        )
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=12,
        current_bet=5.5,
        effective_stack=92,
        players_in_hand=6,
        hero_position="cutoff",
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert "hero_stack" not in provider.required_fields_for(state)


def test_local_solver_routes_structured_three_bet_to_preflop_chart(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("8h"), Card.from_code("8s")],
        pot_size=12,
        current_bet=5.5,
        hero_stack=97.5,
        effective_stack=92,
        players_in_hand=2,
        hero_position="cutoff",
        preflop_opener_position="cutoff",
        preflop_open_size=2.5,
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "facing_three_bet"
    assert result.raw["routing_reason"] == "the hand is preflop"


def test_local_solver_routes_cold_three_bet_to_preflop_chart(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Th"), Card.from_code("Ts")],
        pot_size=12,
        current_bet=7,
        hero_stack=99,
        effective_stack=92,
        players_in_hand=3,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "facing_cold_three_bet"
    assert result.raw["routing_reason"] == "the hand is preflop"


def test_local_solver_keeps_fallback_for_cold_three_bet_with_hidden_player(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Th"), Card.from_code("Ts")],
        pot_size=12,
        current_bet=7,
        hero_stack=99,
        effective_stack=92,
        players_in_hand=4,
        opponents_at_current_bet=1,
        opponent_commitment_total=10.5,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["fallback_reason"] == "the hand is preflop"


def test_local_solver_routes_squeeze_response_to_preflop_chart(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Th"), Card.from_code("Ts")],
        pot_size=16,
        current_bet=7.5,
        hero_stack=97.5,
        effective_stack=90,
        players_in_hand=2,
        hero_position="button",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="button", action="call", amount=2.5),
            PreflopAction(actor="small_blind", action="raise", amount=10),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "facing_squeeze_after_call"
    assert result.raw["routing_reason"] == "the hand is preflop"


def test_local_solver_keeps_fallback_for_squeeze_with_active_opener(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Th"), Card.from_code("Ts")],
        pot_size=16,
        current_bet=7.5,
        hero_stack=97.5,
        effective_stack=90,
        players_in_hand=3,
        opponents_at_current_bet=1,
        hero_position="button",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="button", action="call", amount=2.5),
            PreflopAction(actor="small_blind", action="raise", amount=10),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["fallback_reason"] == "the hand is preflop"


def test_local_solver_routes_four_bet_response_to_preflop_chart(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Th"), Card.from_code("Ts")],
        pot_size=29.5,
        current_bet=12,
        hero_stack=92,
        effective_stack=80,
        players_in_hand=2,
        hero_position="button",
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
            PreflopAction(actor="cutoff", action="raise", amount=20),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "facing_four_bet"
    assert result.raw["routing_reason"] == "the hand is preflop"


def test_local_solver_routes_cold_four_bet_response_to_preflop_chart(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Qh"), Card.from_code("Qd")],
        pot_size=32,
        current_bet=12,
        hero_stack=92,
        effective_stack=80,
        players_in_hand=2,
        hero_position="cutoff",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="cutoff", action="raise", amount=8),
            PreflopAction(actor="button", action="raise", amount=20),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "facing_cold_four_bet"
    assert result.raw["routing_reason"] == "the hand is preflop"


def test_local_solver_keeps_fallback_for_cold_four_bet_with_hidden_player(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Qh"), Card.from_code("Qd")],
        pot_size=32,
        current_bet=12,
        hero_stack=92,
        effective_stack=80,
        players_in_hand=3,
        opponents_at_current_bet=1,
        hero_position="cutoff",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="cutoff", action="raise", amount=8),
            PreflopAction(actor="button", action="raise", amount=20),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["fallback_reason"] == "the hand is preflop"


def test_local_solver_keeps_fallback_for_four_bet_with_hidden_player(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Th"), Card.from_code("Ts")],
        pot_size=29.5,
        current_bet=12,
        hero_stack=92,
        effective_stack=80,
        players_in_hand=3,
        opponents_at_current_bet=1,
        opponent_commitment_total=20,
        hero_position="button",
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
            PreflopAction(actor="cutoff", action="raise", amount=20),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["fallback_reason"] == "the hand is preflop"


def test_local_solver_routes_heads_up_limp_to_preflop_chart(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=2.5,
        current_bet=0,
        effective_stack=100,
        players_in_hand=2,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="button", action="call", amount=1),
        ],
        street="preflop",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "raise"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "heads_up_limp_big_blind"
    assert result.raw["limper_position"] == "button"
    assert result.raw["routing_reason"] == "the hand is preflop"
    assert "hero_stack" not in provider.required_fields_for(state)


def test_local_solver_routes_two_limpers_to_preflop_chart(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=3.5,
        current_bet=0,
        effective_stack=100,
        players_in_hand=3,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="utg", action="call", amount=1),
            PreflopAction(actor="button", action="call", amount=1),
        ],
        street="preflop",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "raise"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "two_limpers_big_blind"
    assert result.raw["limper_positions"] == ["utg", "button"]
    assert result.raw["routing_reason"] == "the hand is preflop"
    assert "hero_stack" not in provider.required_fields_for(state)


def test_local_solver_routes_three_limpers_to_preflop_chart(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=4.5,
        current_bet=0,
        effective_stack=100,
        players_in_hand=4,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="utg", action="call", amount=1),
            PreflopAction(actor="cutoff", action="call", amount=1),
            PreflopAction(actor="button", action="call", amount=1),
        ],
        street="preflop",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "raise"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "three_limpers_big_blind"
    assert result.raw["limper_positions"] == ["utg", "cutoff", "button"]
    assert result.raw["routing_reason"] == "the hand is preflop"
    assert "hero_stack" not in provider.required_fields_for(state)


def test_local_solver_routes_four_limpers_to_preflop_chart(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=5.5,
        current_bet=0,
        effective_stack=100,
        players_in_hand=5,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="utg", action="call", amount=1),
            PreflopAction(actor="hijack", action="call", amount=1),
            PreflopAction(actor="cutoff", action="call", amount=1),
            PreflopAction(actor="button", action="call", amount=1),
        ],
        street="preflop",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "raise"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "four_limpers_big_blind"
    assert result.raw["limper_positions"] == [
        "utg",
        "hijack",
        "cutoff",
        "button",
    ]
    assert result.raw["routing_reason"] == "the hand is preflop"
    assert "hero_stack" not in provider.required_fields_for(state)


def test_local_solver_routes_five_limpers_to_preflop_chart(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=6,
        current_bet=0,
        effective_stack=100,
        players_in_hand=6,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="utg", action="call", amount=1),
            PreflopAction(actor="hijack", action="call", amount=1),
            PreflopAction(actor="cutoff", action="call", amount=1),
            PreflopAction(actor="button", action="call", amount=1),
            PreflopAction(actor="small_blind", action="call", amount=1),
        ],
        street="preflop",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "raise"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "five_limpers_big_blind"
    assert result.raw["limper_positions"] == [
        "utg",
        "hijack",
        "cutoff",
        "button",
        "small_blind",
    ]
    assert result.raw["routing_reason"] == "the hand is preflop"
    assert "hero_stack" not in provider.required_fields_for(state)


def test_local_solver_keeps_fallback_for_limp_with_hidden_player(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=2.5,
        current_bet=0,
        effective_stack=100,
        players_in_hand=3,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="button", action="call", amount=1),
        ],
        street="preflop",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["fallback_reason"] == "the hand is preflop"


def test_local_solver_routes_single_caller_to_preflop_chart(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Jh")],
        pot_size=6.5,
        current_bet=2.5,
        effective_stack=100,
        players_in_hand=3,
        hero_position="button",
        preflop_opener_position="utg",
        preflop_open_size=2.5,
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="hijack", action="call", amount=2.5),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "facing_open_with_caller"
    assert result.raw["caller_positions"] == ["hijack"]
    assert result.raw["routing_reason"] == "the hand is preflop"
    assert "opponents_at_current_bet" not in provider.required_fields_for(state)


def test_local_solver_routes_double_caller_to_preflop_chart(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Jh")],
        pot_size=9,
        current_bet=2.5,
        effective_stack=100,
        players_in_hand=4,
        hero_position="button",
        preflop_opener_position="utg",
        preflop_open_size=2.5,
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="hijack", action="call", amount=2.5),
            PreflopAction(actor="cutoff", action="call", amount=2.5),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "facing_open_with_callers"
    assert result.raw["caller_positions"] == ["hijack", "cutoff"]
    assert result.raw["routing_reason"] == "the hand is preflop"


def test_local_solver_routes_triple_caller_to_preflop_chart(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=11.5,
        current_bet=2,
        effective_stack=100,
        players_in_hand=5,
        hero_position="small_blind",
        preflop_opener_position="utg",
        preflop_open_size=2.5,
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="hijack", action="call", amount=2.5),
            PreflopAction(actor="cutoff", action="call", amount=2.5),
            PreflopAction(actor="button", action="call", amount=2.5),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "raise"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "facing_open_with_three_callers"
    assert result.raw["caller_positions"] == ["hijack", "cutoff", "button"]
    assert result.raw["routing_reason"] == "the hand is preflop"


def test_local_solver_routes_four_caller_to_preflop_chart(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=13.5,
        current_bet=1.5,
        effective_stack=100,
        players_in_hand=6,
        hero_position="big_blind",
        preflop_opener_position="utg",
        preflop_open_size=2.5,
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="hijack", action="call", amount=2.5),
            PreflopAction(actor="cutoff", action="call", amount=2.5),
            PreflopAction(actor="button", action="call", amount=2.5),
            PreflopAction(actor="small_blind", action="call", amount=2.5),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "raise"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "facing_open_with_four_callers"
    assert result.raw["caller_positions"] == [
        "hijack",
        "cutoff",
        "button",
        "small_blind",
    ]
    assert result.raw["routing_reason"] == "the hand is preflop"


def test_local_solver_keeps_fallback_for_four_caller_with_repeated_seat(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=13.5,
        current_bet=1.5,
        effective_stack=100,
        players_in_hand=6,
        opponents_at_current_bet=5,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="hijack", action="call", amount=2.5),
            PreflopAction(actor="cutoff", action="call", amount=2.5),
            PreflopAction(actor="button", action="call", amount=2.5),
            PreflopAction(actor="button", action="call", amount=2.5),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["fallback_reason"] == "the hand is preflop"


def test_local_solver_keeps_fallback_for_triple_caller_with_hidden_player(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=11.5,
        current_bet=2,
        effective_stack=100,
        players_in_hand=6,
        opponents_at_current_bet=4,
        opponent_commitment_total=11,
        hero_position="small_blind",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="hijack", action="call", amount=2.5),
            PreflopAction(actor="cutoff", action="call", amount=2.5),
            PreflopAction(actor="button", action="call", amount=2.5),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["fallback_reason"] == "the hand is preflop"


def test_local_solver_keeps_fallback_for_double_caller_with_hidden_player(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Jh")],
        pot_size=9,
        current_bet=2.5,
        effective_stack=100,
        players_in_hand=5,
        opponents_at_current_bet=3,
        opponent_commitment_total=8.5,
        hero_position="button",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="hijack", action="call", amount=2.5),
            PreflopAction(actor="cutoff", action="call", amount=2.5),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["fallback_reason"] == "the hand is preflop"


def test_local_solver_keeps_fallback_for_single_caller_with_hidden_player(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Jh")],
        pot_size=6.5,
        current_bet=2.5,
        effective_stack=100,
        players_in_hand=4,
        opponents_at_current_bet=2,
        opponent_commitment_total=6,
        hero_position="button",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="hijack", action="call", amount=2.5),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["fallback_reason"] == "the hand is preflop"


def test_local_solver_keeps_ev_fallback_for_preflop_spot_without_position(tmp_path: Path) -> None:
    provider = build_provider(Settings(data_dir=tmp_path, recommendation_provider="local_solver"))
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("2h")],
        pot_size=1.5,
        current_bet=0,
        effective_stack=100,
        players_in_hand=6,
        street="preflop",
        user_approved=True,
    )

    result = provider.recommend(RecommendationRequest(state=state, provider=provider.name))

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["requested_engine"] == "postflop_solver"
    assert "range/EV fallback" in result.explanation


def test_local_solver_runs_postflop_plugin_for_supported_spot(tmp_path: Path) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "assert payload['state']['hero_position'] == 'IP'\n"
        "assert payload['state']['hero_stack'] == 97.5\n"
        "assert payload['state']['facing_action'] == 'bet'\n"
        "expected = {"
        "'POKER_POSTFLOP_SOLVER_MAX_ITERATIONS': '17', "
        "'POKER_POSTFLOP_SOLVER_TARGET_EXPLOITABILITY': '0.025', "
        "'POKER_POSTFLOP_SOLVER_MAX_MEMORY_MB': '321', "
        "'POKER_POSTFLOP_SOLVER_BET_SIZES': '50%,100%', "
        "'POKER_POSTFLOP_SOLVER_RAISE_SIZES': '3x', "
        "'POKER_POSTFLOP_SOLVER_RAKE_RATE': '0.05', "
        "'POKER_POSTFLOP_SOLVER_RAKE_CAP': '2.5', "
        "'POKER_POSTFLOP_SOLVER_RANGE_SOURCE': 'configured', "
        "'POKER_POSTFLOP_SOLVER_RANGE_CONTEXT': '{}', "
        "'POKER_POSTFLOP_SOLVER_OOP_RANGE': 'AA', "
        "'POKER_POSTFLOP_SOLVER_IP_RANGE': 'KK'"
        "}\n"
        "assert {key: os.environ[key] for key in expected} == expected\n"
        "print(json.dumps({"
        "'action': 'raise', "
        "'sizing': 8.5, "
        "'confidence': 0.88, "
        "'explanation': 'Postflop tree response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_max_iterations=17,
            postflop_solver_target_exploitability=0.025,
            postflop_solver_max_memory_mb=321,
            postflop_solver_bet_sizes="50%,100%",
            postflop_solver_raise_sizes="3x",
            postflop_solver_rake_rate=0.05,
            postflop_solver_rake_cap=2.5,
            postflop_solver_oop_range="AA",
            postflop_solver_ip_range="KK",
        )
    )

    result = provider.recommend(
        RecommendationRequest(state=heads_up_postflop_state(), provider=provider.name)
    )

    assert result.action == "raise"
    assert result.sizing == 8.5
    assert result.raw["engine"] == "postflop_solver"
    assert "fallback_reason" not in result.raw


def test_local_solver_derives_ranges_from_complete_single_raised_pot(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_single_raised_pot'\n"
        "assert context['scenario'] == 'single_raised_pot'\n"
        "assert context['opener_position'] == 'button'\n"
        "assert context['caller_position'] == 'big_blind'\n"
        "assert 'AA' in os.environ['POKER_POSTFLOP_SOLVER_IP_RANGE'].split(',')\n"
        "assert 'AA' not in os.environ['POKER_POSTFLOP_SOLVER_OOP_RANGE'].split(',')\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual range response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 5.5
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.hero_position = "big_blind"
    state.opponent_position = "button"
    state.preflop_action_history = [
        PreflopAction(actor="button", action="raise", amount=2.5),
        PreflopAction(actor="big_blind", action="call", amount=2.5),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_derives_ranges_on_turn_from_completed_flop(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_single_raised_pot'\n"
        "assert context['starting_effective_stack_bb'] == 100\n"
        "assert context['stack_depth_source'] == 'reconstructed'\n"
        "assert payload['state']['completed_postflop_streets'][0]['street'] == 'flop'\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual turn range response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.board_cards.append(Card.from_code("3d"))
    state.street = "turn"
    state.current_bet = 0
    state.pot_size = 9.5
    state.hero_stack = 95.5
    state.opponent_stack = 95.5
    state.effective_stack = 95.5
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.hero_position = "big_blind"
    state.opponent_position = "button"
    state.preflop_action_history = [
        PreflopAction(actor="button", action="raise", amount=2.5),
        PreflopAction(actor="big_blind", action="call", amount=2.5),
    ]
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(
                    actor="oop",
                    action="bet",
                    amount=2.0,
                ),
                CompletedPostflopAction(
                    actor="ip",
                    action="call",
                    amount=2.0,
                ),
            ],
        )
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_derives_ranges_from_complete_three_bet_pot(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_three_bet_pot'\n"
        "assert context['scenario'] == 'three_bet_pot'\n"
        "assert context['opener_position'] == 'button'\n"
        "assert context['three_bettor_position'] == 'big_blind'\n"
        "assert context['three_bet_size_bb'] == 8\n"
        "assert context['stack_depth_policy'] == 'medium'\n"
        "assert context['starting_effective_stack_bb'] == 50\n"
        "assert context['stack_depth_source'] == 'reconstructed'\n"
        "assert context['three_bettor_fraction'] == 0.138\n"
        "assert context['opener_continue_fraction'] == 0.171\n"
        "assert 'AA' not in os.environ['POKER_POSTFLOP_SOLVER_IP_RANGE'].split(',')\n"
        "assert 'AA' in os.environ['POKER_POSTFLOP_SOLVER_OOP_RANGE'].split(',')\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual 3-bet range response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 16.5
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.effective_stack = 42.0
    state.hero_position = "button"
    state.opponent_position = "big_blind"
    state.preflop_action_history = [
        PreflopAction(actor="button", action="raise", amount=2.5),
        PreflopAction(actor="big_blind", action="raise", amount=8.0),
        PreflopAction(actor="button", action="call", amount=8.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_derives_ranges_from_cold_three_bet_pot(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_cold_three_bet_pot'\n"
        "assert context['scenario'] == 'cold_three_bet_pot'\n"
        "assert context['folded_opener_position'] == 'utg'\n"
        "assert context['folded_opener_commitment_bb'] == 2.5\n"
        "assert context['three_bettor_position'] == 'cutoff'\n"
        "assert context['cold_caller_position'] == 'button'\n"
        "assert context['cold_three_bet_policy'] == 'conservative_three_player'\n"
        "assert context['starting_effective_stack_bb'] == 100\n"
        "assert 'AA' in os.environ['POKER_POSTFLOP_SOLVER_OOP_RANGE'].split(',')\n"
        "assert 'AA' not in os.environ['POKER_POSTFLOP_SOLVER_IP_RANGE'].split(',')\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual cold 3-bet range response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 20.0
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.effective_stack = 92.0
    state.hero_position = "button"
    state.opponent_position = "cutoff"
    state.preflop_action_history = [
        PreflopAction(actor="utg", action="raise", amount=2.5),
        PreflopAction(actor="cutoff", action="raise", amount=8.0),
        PreflopAction(actor="button", action="call", amount=8.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_derives_ranges_from_squeeze_pot(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_squeeze_pot'\n"
        "assert context['scenario'] == 'squeeze_pot'\n"
        "assert context['folded_opener_position'] == 'utg'\n"
        "assert context['folded_opener_commitment_bb'] == 2.5\n"
        "assert context['caller_position'] == 'button'\n"
        "assert context['squeezer_position'] == 'small_blind'\n"
        "assert context['squeeze_response_policy'] == "
        "'conservative_heads_up_squeeze'\n"
        "assert context['caller_adjustment_policy'] == "
        "'single_caller_conservative'\n"
        "assert context['starting_effective_stack_bb'] == 100\n"
        "assert 'AA' in os.environ['POKER_POSTFLOP_SOLVER_OOP_RANGE'].split(',')\n"
        "assert 'AA' not in os.environ['POKER_POSTFLOP_SOLVER_IP_RANGE'].split(',')\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual squeeze range response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 23.5
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.effective_stack = 90.0
    state.hero_position = "button"
    state.opponent_position = "small_blind"
    state.preflop_action_history = [
        PreflopAction(actor="utg", action="raise", amount=2.5),
        PreflopAction(actor="button", action="call", amount=2.5),
        PreflopAction(actor="small_blind", action="raise", amount=10.0),
        PreflopAction(actor="button", action="call", amount=10.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_keeps_fallback_for_ambiguous_blind_limped_pot(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 2.0
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.effective_stack = 99.0
    state.hero_position = "big_blind"
    state.opponent_position = "small_blind"
    state.preflop_action_history = [
        PreflopAction(actor="small_blind", action="call", amount=1.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["requested_engine"] == "postflop_solver"
    assert "position must identify IP or OOP" in result.raw["fallback_reason"]


def test_local_solver_resolves_blind_isolation_raised_pot(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_isolation_raised_pot'\n"
        "assert context['limper_position'] == 'small_blind'\n"
        "assert context['isolation_raiser_position'] == 'big_blind'\n"
        "assert 'AA' in os.environ['POKER_POSTFLOP_SOLVER_IP_RANGE'].split(',')\n"
        "assert 'AA' not in os.environ['POKER_POSTFLOP_SOLVER_OOP_RANGE'].split(',')\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual blind isolation response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 8.0
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.effective_stack = 96.0
    state.hero_position = "big_blind"
    state.opponent_position = "small_blind"
    state.preflop_action_history = [
        PreflopAction(actor="small_blind", action="call", amount=1.0),
        PreflopAction(actor="big_blind", action="raise", amount=4.0),
        PreflopAction(actor="small_blind", action="call", amount=4.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_resolves_relative_isolation_raised_pot_ranges(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_isolation_raised_pot'\n"
        "assert context['limper_position'] == 'button'\n"
        "assert context['isolation_raiser_position'] == 'big_blind'\n"
        "assert 'AA' in os.environ['POKER_POSTFLOP_SOLVER_OOP_RANGE'].split(',')\n"
        "assert 'AA' not in os.environ['POKER_POSTFLOP_SOLVER_IP_RANGE'].split(',')\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual relative isolation response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 8.5
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.effective_stack = 96.0
    state.hero_position = "OOP"
    state.opponent_position = "IP"
    state.preflop_action_history = [
        PreflopAction(actor="button", action="call", amount=1.0),
        PreflopAction(actor="big_blind", action="raise", amount=4.0),
        PreflopAction(actor="button", action="call", amount=4.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_falls_back_for_contradictory_isolation_labels(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == 'configured'\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Configured-range fallback', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 8.0
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.effective_stack = 96.0
    state.hero_position = "small_blind"
    state.opponent_position = "OOP"
    state.preflop_action_history = [
        PreflopAction(actor="small_blind", action="call", amount=1.0),
        PreflopAction(actor="big_blind", action="raise", amount=4.0),
        PreflopAction(actor="small_blind", action="call", amount=4.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_resolves_blind_limp_reraised_pot(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_limp_reraised_pot'\n"
        "assert context['limper_position'] == 'small_blind'\n"
        "assert context['isolation_raiser_position'] == 'big_blind'\n"
        "assert context['limp_reraise_size_bb'] == 12\n"
        "assert 'AA' in os.environ['POKER_POSTFLOP_SOLVER_OOP_RANGE'].split(',')\n"
        "assert 'AA' not in os.environ['POKER_POSTFLOP_SOLVER_IP_RANGE'].split(',')\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual blind limp-reraised response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 24.0
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.effective_stack = 88.0
    state.hero_position = "big_blind"
    state.opponent_position = "small_blind"
    state.preflop_action_history = [
        PreflopAction(actor="small_blind", action="call", amount=1.0),
        PreflopAction(actor="big_blind", action="raise", amount=4.0),
        PreflopAction(actor="small_blind", action="raise", amount=12.0),
        PreflopAction(actor="big_blind", action="call", amount=12.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_derives_blind_limp_ranges_with_relative_evidence(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_limped_pot'\n"
        "assert context['limper_position'] == 'small_blind'\n"
        "assert 'AA' in os.environ['POKER_POSTFLOP_SOLVER_OOP_RANGE'].split(',')\n"
        "assert 'AA' not in os.environ['POKER_POSTFLOP_SOLVER_IP_RANGE'].split(',')\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual limped-pot response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 2.0
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.effective_stack = 99.0
    state.hero_position = "big_blind"
    state.opponent_position = "OOP"
    state.preflop_action_history = [
        PreflopAction(actor="small_blind", action="call", amount=1.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_derives_blind_limp_ranges_with_dealer_evidence(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_limped_pot'\n"
        "assert context['limper_position'] == 'small_blind'\n"
        "assert 'AA' in os.environ['POKER_POSTFLOP_SOLVER_IP_RANGE'].split(',')\n"
        "assert 'AA' not in os.environ['POKER_POSTFLOP_SOLVER_OOP_RANGE'].split(',')\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual heads-up limped-pot response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 2.0
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.effective_stack = 99.0
    state.hero_position = "dealer"
    state.opponent_position = "big_blind"
    state.preflop_action_history = [
        PreflopAction(actor="small_blind", action="call", amount=1.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_derives_ranges_for_blind_squeeze_survivors(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_squeeze_pot'\n"
        "assert context['folded_opener_position'] == 'button'\n"
        "assert context['caller_position'] == 'small_blind'\n"
        "assert context['squeezer_position'] == 'big_blind'\n"
        "assert 'AA' in os.environ['POKER_POSTFLOP_SOLVER_IP_RANGE'].split(',')\n"
        "assert 'AA' not in os.environ['POKER_POSTFLOP_SOLVER_OOP_RANGE'].split(',')\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual blind squeeze response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 22.5
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.effective_stack = 90.0
    state.hero_position = "small_blind"
    state.opponent_position = "big_blind"
    state.preflop_action_history = [
        PreflopAction(actor="button", action="raise", amount=2.5),
        PreflopAction(actor="small_blind", action="call", amount=2.5),
        PreflopAction(actor="big_blind", action="raise", amount=10.0),
        PreflopAction(actor="small_blind", action="call", amount=10.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_derives_ranges_from_complete_four_bet_pot(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_four_bet_pot'\n"
        "assert context['scenario'] == 'four_bet_pot'\n"
        "assert context['opener_position'] == 'button'\n"
        "assert context['three_bettor_position'] == 'big_blind'\n"
        "assert context['four_bet_size_bb'] == 20\n"
        "assert 'AA' in os.environ['POKER_POSTFLOP_SOLVER_IP_RANGE'].split(',')\n"
        "assert 'AA' not in os.environ['POKER_POSTFLOP_SOLVER_OOP_RANGE'].split(',')\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual 4-bet range response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 40.5
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.hero_position = "button"
    state.opponent_position = "big_blind"
    state.preflop_action_history = [
        PreflopAction(actor="button", action="raise", amount=2.5),
        PreflopAction(actor="big_blind", action="raise", amount=8.0),
        PreflopAction(actor="button", action="raise", amount=20.0),
        PreflopAction(actor="big_blind", action="call", amount=20.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_derives_ranges_from_complete_cold_four_bet_pot(
    tmp_path: Path,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, os\n"
        "context = json.loads(os.environ['POKER_POSTFLOP_SOLVER_RANGE_CONTEXT'])\n"
        "assert os.environ['POKER_POSTFLOP_SOLVER_RANGE_SOURCE'] == "
        "'preflop_chart_cold_four_bet_pot'\n"
        "assert context['scenario'] == 'cold_four_bet_pot'\n"
        "assert context['folded_opener_position'] == 'button'\n"
        "assert context['folded_opener_commitment_bb'] == 2.5\n"
        "assert context['three_bettor_position'] == 'small_blind'\n"
        "assert context['cold_four_bettor_position'] == 'big_blind'\n"
        "assert context['four_bet_size_bb'] == 20\n"
        "assert context['cold_four_bettor_range_policy'] == "
        "'conservative_three_player'\n"
        "assert context['cold_four_bet_policy'] == "
        "'conservative_heads_up_after_opener_folds'\n"
        "assert 'AA' in os.environ['POKER_POSTFLOP_SOLVER_IP_RANGE'].split(',')\n"
        "assert 'AA' not in os.environ['POKER_POSTFLOP_SOLVER_OOP_RANGE'].split(',')\n"
        "print(json.dumps({"
        "'action': 'check', 'sizing': None, 'confidence': 0.8, "
        "'explanation': 'Contextual cold 4-bet range response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.pot_size = 42.5
    state.opponents_at_current_bet = None
    state.opponent_wager = None
    state.opponent_commitment_total = None
    state.facing_action = None
    state.hero_position = "small_blind"
    state.opponent_position = "big_blind"
    state.preflop_action_history = [
        PreflopAction(actor="button", action="raise", amount=2.5),
        PreflopAction(actor="small_blind", action="raise", amount=8.0),
        PreflopAction(actor="big_blind", action="raise", amount=20.0),
        PreflopAction(actor="small_blind", action="call", amount=20.0),
    ]

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "check"
    assert result.raw["engine"] == "postflop_solver"


def test_postflop_solver_routes_dealer_as_ip(tmp_path: Path) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "assert payload['state']['hero_position'] == 'dealer'\n"
        "print(json.dumps({"
        "'action': 'call', "
        "'sizing': None, "
        "'confidence': 0.84, "
        "'explanation': 'Dealer postflop response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.hero_position = "dealer"

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw["engine"] == "postflop_solver"
    assert "fallback_reason" not in result.raw


def test_postflop_solver_routes_unambiguous_absolute_seats(tmp_path: Path) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "state = payload['state']\n"
        "assert state['hero_position'] == 'big_blind'\n"
        "assert state['opponent_position'] == 'button'\n"
        "print(json.dumps({"
        "'action': 'call', "
        "'sizing': None, "
        "'confidence': 0.84, "
        "'explanation': 'Inferred OOP postflop response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )
    state = heads_up_postflop_state()
    state.hero_position = "big_blind"
    state.opponent_position = "button"

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw["engine"] == "postflop_solver"


def test_postflop_solver_routes_complete_raised_history(tmp_path: Path) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, sys\n"
        "payload = json.loads(sys.stdin.read())\n"
        "state = payload['state']\n"
        "assert state['opponent_stack'] == 93.0\n"
        "assert state['postflop_action_history'] == [\n"
        "    {'actor': 'oop', 'action': 'bet', 'amount': 2.0},\n"
        "    {'actor': 'ip', 'action': 'raise', 'amount': 7.0},\n"
        "]\n"
        "print(json.dumps({"
        "'action': 'call', "
        "'sizing': None, "
        "'confidence': 0.86, "
        "'explanation': 'Raised tree response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )

    result = provider.recommend(
        RecommendationRequest(state=raised_postflop_state(), provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw["engine"] == "postflop_solver"


def test_postflop_solver_failure_uses_ev_fallback(tmp_path: Path) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text("import sys\nprint('tree too large', file=sys.stderr)\nsys.exit(8)\n")
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
        )
    )

    result = provider.recommend(
        RecommendationRequest(state=heads_up_postflop_state(), provider=provider.name)
    )

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["requested_engine"] == "postflop_solver"
    assert "tree too large" in result.raw["fallback_reason"]
    assert "range/EV fallback" in result.explanation


@pytest.mark.parametrize(
    ("solver_output", "error_message"),
    [
        ("not-json", "invalid JSON"),
        (
            '{"action":"call","sizing":2.5,"confidence":0.8,'
            '"explanation":"Malformed recommendation"}',
            "invalid payload",
        ),
    ],
)
def test_postflop_solver_malformed_response_does_not_use_ev_fallback(
    tmp_path: Path,
    solver_output: str,
    error_message: str,
) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(f"print({solver_output!r})\n")
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_engine="postflop_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=True,
        )
    )

    with pytest.raises(ProviderError, match=error_message):
        provider.recommend(
            RecommendationRequest(
                state=heads_up_postflop_state(),
                provider=provider.name,
            )
        )


def test_postflop_solver_requires_position_when_fallback_is_disabled(tmp_path: Path) -> None:
    state = heads_up_postflop_state()
    state.hero_position = "SB"
    state.opponent_position = "BB"
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=False,
        )
    )

    with pytest.raises(ProviderInputError, match="position must identify IP or OOP"):
        provider.recommend(RecommendationRequest(state=state, provider=provider.name))


def test_postflop_solver_rejects_contradictory_relative_positions(tmp_path: Path) -> None:
    state = heads_up_postflop_state()
    state.opponent_position = "IP"
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=False,
        )
    )

    with pytest.raises(ProviderInputError, match="position must identify IP or OOP"):
        provider.recommend(RecommendationRequest(state=state, provider=provider.name))


def test_postflop_solver_requires_hero_stack_when_facing_bet(tmp_path: Path) -> None:
    state = heads_up_postflop_state()
    state.hero_stack = None
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=False,
        )
    )

    with pytest.raises(ProviderInputError, match="hero stack is required"):
        provider.recommend(RecommendationRequest(state=state, provider=provider.name))


def test_postflop_solver_rejects_unknown_facing_action(tmp_path: Path) -> None:
    state = heads_up_postflop_state()
    state.facing_action = None
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=False,
        )
    )

    with pytest.raises(ProviderInputError, match="identify the outstanding wager"):
        provider.recommend(RecommendationRequest(state=state, provider=provider.name))


def test_postflop_solver_rejects_facing_action_without_call_amount(tmp_path: Path) -> None:
    state = heads_up_postflop_state()
    state.current_bet = 0
    state.opponents_at_current_bet = None
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=False,
        )
    )

    with pytest.raises(ProviderInputError, match="requires a positive amount to call"):
        provider.recommend(RecommendationRequest(state=state, provider=provider.name))


def test_postflop_solver_rejects_raise_without_structured_history(tmp_path: Path) -> None:
    state = heads_up_postflop_state()
    state.facing_action = "raise"
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=False,
        )
    )

    with pytest.raises(ProviderInputError, match="requires structured action history"):
        provider.recommend(RecommendationRequest(state=state, provider=provider.name))


def test_postflop_solver_rejects_history_that_does_not_end_at_hero(tmp_path: Path) -> None:
    state = raised_postflop_state()
    state.hero_position = "IP"
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=False,
        )
    )

    with pytest.raises(ProviderInputError, match="does not end at the hero decision"):
        provider.recommend(RecommendationRequest(state=state, provider=provider.name))


def test_postflop_solver_rejects_call_amount_that_differs_after_cent_rounding(
    tmp_path: Path,
) -> None:
    state = raised_postflop_state()
    state.current_bet = 4.991
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=False,
        )
    )

    with pytest.raises(ProviderInputError, match="current bet does not match"):
        provider.recommend(RecommendationRequest(state=state, provider=provider.name))


def test_postflop_solver_rejects_history_wager_that_rounds_to_zero(tmp_path: Path) -> None:
    state = raised_postflop_state()
    state.current_bet = 1.0
    state.postflop_action_history[0].amount = 0.001
    state.postflop_action_history[1].amount = 1.0
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=False,
        )
    )

    with pytest.raises(ProviderInputError, match="must round to at least 0.01 BB"):
        provider.recommend(RecommendationRequest(state=state, provider=provider.name))


def test_postflop_solver_rejects_history_beyond_reconstructed_effective_stack(
    tmp_path: Path,
) -> None:
    state = raised_postflop_state()
    state.pot_size = 25.0
    state.current_bet = 10.0
    state.hero_stack = 8.0
    state.opponent_stack = 0.0
    state.effective_stack = 0.0
    state.postflop_action_history[1].amount = 12.0
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=False,
        )
    )

    with pytest.raises(ProviderInputError, match="exceeds the reconstructed effective stack"):
        provider.recommend(RecommendationRequest(state=state, provider=provider.name))


def test_postflop_solver_rejects_subminimum_non_all_in_raise(tmp_path: Path) -> None:
    state = raised_postflop_state()
    state.pot_size = 15.0
    state.current_bet = 1.0
    state.postflop_action_history[1].amount = 3.0
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=False,
        )
    )

    with pytest.raises(ProviderInputError, match="below the minimum full-raise amount"):
        provider.recommend(RecommendationRequest(state=state, provider=provider.name))


def test_postflop_solver_tracks_minimum_increment_across_reraises(tmp_path: Path) -> None:
    state = raised_postflop_state()
    state.pot_size = 27.0
    state.current_bet = 3.0
    state.hero_stack = 93.0
    state.opponent_stack = 91.0
    state.effective_stack = 91.0
    state.hero_position = "IP"
    state.postflop_action_history = [
        PostflopAction(actor="oop", action="bet", amount=2.0),
        PostflopAction(actor="ip", action="raise", amount=6.0),
        PostflopAction(actor="oop", action="raise", amount=9.0),
    ]
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_fallback_enabled=False,
        )
    )

    with pytest.raises(ProviderInputError, match="below the minimum full-raise amount"):
        provider.recommend(RecommendationRequest(state=state, provider=provider.name))


def test_postflop_solver_accepts_subminimum_all_in_raise(tmp_path: Path) -> None:
    solver_script = tmp_path / "postflop.py"
    solver_script.write_text(
        "import json, sys\n"
        "json.loads(sys.stdin.read())\n"
        "print(json.dumps({"
        "'action': 'call', "
        "'sizing': None, "
        "'confidence': 0.8, "
        "'explanation': 'Short all-in response', "
        "'raw': {'provider': 'local_solver', 'engine': 'postflop_solver'}"
        "}))\n"
    )
    state = raised_postflop_state()
    state.pot_size = 15.0
    state.current_bet = 1.0
    state.opponent_stack = 0.0
    state.effective_stack = 0.0
    state.postflop_action_history[1].amount = 3.0
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            postflop_solver_command=f"{sys.executable} {solver_script}",
            postflop_solver_fallback_enabled=False,
        )
    )

    result = provider.recommend(RecommendationRequest(state=state, provider=provider.name))

    assert result.action == "call"
    assert result.raw["engine"] == "postflop_solver"


def test_local_solver_rejects_unknown_engine(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_engine="missing",
        )
    )

    with pytest.raises(ProviderConfigurationError, match="Unknown local solver engine"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))


def test_local_solver_reads_json_response(tmp_path: Path) -> None:
    solver_script = tmp_path / "solver.py"
    solver_script.write_text(
        "import json, sys\n"
        "json.loads(sys.stdin.read())\n"
        "print(json.dumps({"
        "'action': 'call', "
        "'sizing': None, "
        "'confidence': 0.64, "
        "'explanation': 'Local command response', "
        "'raw': {'provider': 'local_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command=f"{sys.executable} {solver_script}",
        )
    )

    result = provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))

    assert result.action == "call"
    assert result.raw["provider"] == "local_solver"


def test_local_solver_nonzero_exit_includes_return_code_and_output(tmp_path: Path) -> None:
    solver_script = tmp_path / "solver.py"
    solver_script.write_text("import sys\nprint('solver exploded', file=sys.stderr)\nsys.exit(7)\n")
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command=f"{sys.executable} {solver_script}",
        )
    )

    with pytest.raises(ProviderError, match="return code 7.*solver exploded"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))


def test_local_solver_nonzero_exit_falls_back_to_stdout(tmp_path: Path) -> None:
    solver_script = tmp_path / "solver.py"
    solver_script.write_text("import sys\nprint('stdout failure')\nsys.exit(9)\n")
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command=f"{sys.executable} {solver_script}",
        )
    )

    with pytest.raises(ProviderError, match="return code 9.*stdout failure"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))


def test_local_solver_startup_error_raises_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(*args: object, **kwargs: object) -> object:
        raise OSError("command missing")

    monkeypatch.setattr("subprocess.run", fake_run)
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command="solver",
        )
    )

    with pytest.raises(ProviderError, match="could not be started.*command missing"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))


def test_local_solver_timeout_raises_provider_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=["solver"], timeout=30.0)

    monkeypatch.setattr("subprocess.run", fake_run)
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command="solver",
        )
    )

    with pytest.raises(ProviderError, match="timed out"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))


def test_local_solver_invalid_json_raises_provider_error(tmp_path: Path) -> None:
    solver_script = tmp_path / "solver.py"
    solver_script.write_text("print('not-json')\n")
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command=f"{sys.executable} {solver_script}",
        )
    )

    with pytest.raises(ProviderError, match="invalid JSON"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))


def test_local_solver_invalid_payload_raises_provider_error(tmp_path: Path) -> None:
    solver_script = tmp_path / "solver.py"
    solver_script.write_text("print('{\"action\": \"jam\"}')\n")
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command=f"{sys.executable} {solver_script}",
        )
    )

    with pytest.raises(ProviderError, match="invalid payload"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))


def test_local_solver_rejects_sizing_for_non_wager_action(tmp_path: Path) -> None:
    solver_script = tmp_path / "solver.py"
    solver_script.write_text(
        "print('{\"action\":\"call\",\"sizing\":2.5,\"confidence\":0.8,"
        "\"explanation\":\"Malformed recommendation\"}')\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command=f"{sys.executable} {solver_script}",
        )
    )

    with pytest.raises(ProviderError, match="invalid payload"):
        provider.recommend(
            RecommendationRequest(state=approved_state(), provider=provider.name)
        )


def test_local_solver_rejects_nonfinite_sizing(tmp_path: Path) -> None:
    solver_script = tmp_path / "solver.py"
    solver_script.write_text(
        "print('{\"action\":\"raise\",\"sizing\":Infinity,\"confidence\":0.8,"
        "\"explanation\":\"Malformed recommendation\"}')\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command=f"{sys.executable} {solver_script}",
        )
    )

    with pytest.raises(ProviderError, match="invalid payload"):
        provider.recommend(
            RecommendationRequest(state=approved_state(), provider=provider.name)
        )


def test_local_solver_rejects_zero_wager_sizing(tmp_path: Path) -> None:
    solver_script = tmp_path / "solver.py"
    solver_script.write_text(
        "print('{\"action\":\"raise\",\"sizing\":0,\"confidence\":0.8,"
        "\"explanation\":\"Malformed recommendation\"}')\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command=f"{sys.executable} {solver_script}",
        )
    )

    with pytest.raises(ProviderError, match="invalid payload"):
        provider.recommend(
            RecommendationRequest(state=approved_state(), provider=provider.name)
        )


@pytest.mark.parametrize("sizing_json", ["true", '"7.5"'])
def test_local_solver_rejects_coerced_wager_sizing(
    tmp_path: Path,
    sizing_json: str,
) -> None:
    solver_script = tmp_path / "solver.py"
    payload = (
        '{"action":"raise","sizing":'
        f"{sizing_json},"
        '"confidence":0.8,"explanation":"Malformed recommendation"}'
    )
    solver_script.write_text(f"print({payload!r})\n")
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command=f"{sys.executable} {solver_script}",
        )
    )

    with pytest.raises(ProviderError, match="invalid payload"):
        provider.recommend(
            RecommendationRequest(state=approved_state(), provider=provider.name)
        )


@pytest.mark.parametrize("confidence_json", ["true", '"0.8"'])
def test_local_solver_rejects_coerced_confidence(
    tmp_path: Path,
    confidence_json: str,
) -> None:
    solver_script = tmp_path / "solver.py"
    payload = (
        '{"action":"check","sizing":null,"confidence":'
        f"{confidence_json},"
        '"explanation":"Malformed recommendation"}'
    )
    solver_script.write_text(f"print({payload!r})\n")
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command=f"{sys.executable} {solver_script}",
        )
    )

    with pytest.raises(ProviderError, match="invalid payload"):
        provider.recommend(
            RecommendationRequest(state=approved_state(), provider=provider.name)
        )


def test_external_solver_posts_canonical_json_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://solver.example/recommend")
    captured: dict[str, Any] = {}

    def fake_post(
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            json={
                "action": "bet",
                "sizing": 8.0,
                "confidence": 0.81,
                "explanation": "External solver response",
                "raw": {"provider": "external_solver"},
            },
            request=request,
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="external_solver",
            external_provider_url="https://solver.example/recommend",
            external_provider_bearer_token="solver-token",
            external_request_timeout_seconds=9.5,
        )
    )

    state = approved_state()
    state.opponent_position = "big_blind"
    result = provider.recommend(RecommendationRequest(state=state, provider=provider.name))

    assert result.action == "bet"
    assert result.raw["provider"] == "external_solver"
    assert captured == {
        "url": "https://solver.example/recommend",
        "json": {
            "state": {
                "hero_cards": [
                    {"rank": "A", "suit": "hearts"},
                    {"rank": "K", "suit": "diamonds"},
                ],
                "board_cards": [
                    {"rank": "Q", "suit": "spades"},
                    {"rank": "J", "suit": "clubs"},
                    {"rank": "2", "suit": "hearts"},
                ],
                "pot_size": 12.5,
                "current_bet": 2.5,
                "hero_stack": 97.5,
                "effective_stack": 96.0,
                "players_in_hand": 3,
                "opponents_at_current_bet": 1,
                "hero_position": "button",
                "opponent_position": "big_blind",
                "street": "flop",
                "facing_action": "bet",
                "action_context": "Cutoff bet 2.5 into 12.5",
                "user_approved": True,
            },
            "provider": "external_solver",
        },
        "headers": {"Authorization": "Bearer solver-token"},
        "timeout": 9.5,
    }


def test_external_solver_posts_structured_preflop_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "https://solver.example/recommend")
    captured: dict[str, Any] = {}

    def fake_post(
        url: str,
        *,
        json: dict[str, object],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        captured.update(json)
        return httpx.Response(
            200,
            json={
                "action": "call",
                "sizing": None,
                "confidence": 0.8,
                "explanation": "External three-bet response",
            },
            request=request,
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="external_solver",
            external_provider_url="https://solver.example/recommend",
        )
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("8h"), Card.from_code("8s")],
        pot_size=12,
        current_bet=5.5,
        hero_stack=97.5,
        effective_stack=92,
        players_in_hand=6,
        hero_position="cutoff",
        preflop_opener_position="cutoff",
        preflop_open_size=2.5,
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    provider.recommend(RecommendationRequest(state=state, provider=provider.name))

    assert captured["state"]["preflop_action_history"] == [
        {"actor": "cutoff", "action": "raise", "amount": 2.5},
        {"actor": "button", "action": "raise", "amount": 8.0},
    ]


def test_local_solver_requires_hero_stack_for_isolation_response(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=6.5,
        current_bet=3,
        effective_stack=90,
        players_in_hand=2,
        hero_position="utg",
        preflop_action_history=[
            PreflopAction(actor="utg", action="call", amount=1),
            PreflopAction(actor="button", action="raise", amount=4),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert "hero_stack" in provider.required_fields_for(state)


def test_local_solver_routes_isolation_response_to_preflop_chart(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("9h"), Card.from_code("9s")],
        pot_size=6.5,
        current_bet=3,
        hero_stack=99,
        effective_stack=90,
        players_in_hand=2,
        hero_position="utg",
        preflop_action_history=[
            PreflopAction(actor="utg", action="call", amount=1),
            PreflopAction(actor="button", action="raise", amount=4),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "facing_isolation_raise_after_limp"
    assert result.raw["routing_reason"] == "the hand is preflop"


def test_local_solver_keeps_fallback_when_limper_is_not_hero(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("9h"), Card.from_code("9s")],
        pot_size=6.5,
        current_bet=3,
        hero_stack=99,
        effective_stack=90,
        players_in_hand=3,
        opponents_at_current_bet=1,
        hero_position="big_blind",
        preflop_action_history=[
            PreflopAction(actor="utg", action="call", amount=1),
            PreflopAction(actor="button", action="raise", amount=4),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.raw["engine"] == "local_ev_solver_v1"
    assert result.raw["fallback_reason"] == "the hand is preflop"


def test_local_solver_requires_hero_stack_for_limp_reraise_response(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Ad")],
        pot_size=17.5,
        current_bet=8,
        effective_stack=88,
        players_in_hand=2,
        hero_position="button",
        preflop_action_history=[
            PreflopAction(actor="utg", action="call", amount=1),
            PreflopAction(actor="button", action="raise", amount=4),
            PreflopAction(actor="utg", action="raise", amount=12),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    assert "hero_stack" in provider.required_fields_for(state)


def test_local_solver_routes_limp_reraise_response_to_preflop_chart(
    tmp_path: Path,
) -> None:
    provider = build_provider(
        Settings(data_dir=tmp_path, recommendation_provider="local_solver")
    )
    state = CanonicalState(
        hero_cards=[Card.from_code("Th"), Card.from_code("Ts")],
        pot_size=17.5,
        current_bet=8,
        hero_stack=96,
        effective_stack=88,
        players_in_hand=2,
        hero_position="button",
        preflop_action_history=[
            PreflopAction(actor="utg", action="call", amount=1),
            PreflopAction(actor="button", action="raise", amount=4),
            PreflopAction(actor="utg", action="raise", amount=12),
        ],
        street="preflop",
        facing_action="raise",
        user_approved=True,
    )

    result = provider.recommend(
        RecommendationRequest(state=state, provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "facing_limp_reraise"
    assert result.raw["routing_reason"] == "the hand is preflop"


def test_llm_advice_uses_its_own_bearer_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "https://llm.example/recommend")
    captured_headers: dict[str, str] = {}

    def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        captured_headers.update(kwargs["headers"])
        return httpx.Response(
            200,
            json={
                "action": "call",
                "sizing": None,
                "confidence": 0.7,
                "explanation": "LLM advice",
                "raw": {"provider": "llm_advice"},
            },
            request=request,
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="llm_advice",
            llm_advice_url="https://llm.example/recommend",
            llm_advice_bearer_token="llm-token",
        )
    )

    result = provider.recommend(
        RecommendationRequest(state=approved_state(), provider=provider.name)
    )

    assert result.raw["provider"] == "llm_advice"
    assert captured_headers == {"Authorization": "Bearer llm-token"}


def test_external_solver_requires_url(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="external_solver",
            external_provider_url=None,
        )
    )

    with pytest.raises(ProviderConfigurationError, match="POKER_EXTERNAL_PROVIDER_URL"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))


def test_llm_advice_requires_url(tmp_path: Path) -> None:
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="llm_advice",
            llm_advice_url=None,
        )
    )

    with pytest.raises(ProviderConfigurationError, match="POKER_LLM_ADVICE_URL"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))


def test_http_provider_non_success_status_raises_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = httpx.Request("POST", "https://solver.example/recommend")

    def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"}, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="external_solver",
            external_provider_url="https://solver.example/recommend",
        )
    )

    with pytest.raises(ProviderError, match="status 503"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))


def test_http_provider_request_failure_raises_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.RequestError("connection refused")

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="external_solver",
            external_provider_url="https://solver.example/recommend",
        )
    )

    with pytest.raises(ProviderError, match="external_solver request failed"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))


def test_http_provider_invalid_json_raises_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = httpx.Request("POST", "https://solver.example/recommend")

    def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", request=request)

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="external_solver",
            external_provider_url="https://solver.example/recommend",
        )
    )

    with pytest.raises(ProviderError, match="invalid JSON"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))


def test_http_provider_invalid_payload_raises_provider_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = httpx.Request("POST", "https://solver.example/recommend")

    def fake_post(*args: object, **kwargs: object) -> httpx.Response:
        return httpx.Response(200, json={"action": "jam"}, request=request)

    monkeypatch.setattr(httpx, "post", fake_post)
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="external_solver",
            external_provider_url="https://solver.example/recommend",
        )
    )

    with pytest.raises(ProviderError, match="invalid payload"):
        provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))
