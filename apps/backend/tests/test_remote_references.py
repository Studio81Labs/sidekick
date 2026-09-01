from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import ValidationError

from app.domain.imported_hands import (
    HeroDecisionPoint,
    ImportedHandState,
    extract_hero_decision_points,
)
from app.domain.learning_content import DecisionBinding
from app.domain.remote_references import (
    AbstractionSchemaBinding,
    BoardCardsRoute,
    ConditionedRange,
    ConditionedRangesRoute,
    EconomicConfigurationBinding,
    GameEconomicsRoute,
    HoleCardAbstractionRoute,
    HoleCardsRoute,
    PriorActionsRoute,
    PositionedCommitment,
    PositionedStack,
    RemotePriorAction,
    RemoteReferenceConsent,
    RemoteReferenceDisclosure,
    RemoteReferenceProviderPolicy,
    RemoteReferenceRouteDerivation,
    RemoteReferenceRouteManifest,
    RemoteReferenceRouteRequest,
    StackWagerPotRoute,
    TablePositionRoute,
    UtilityConfigurationBinding,
    bind_remote_reference_route,
    derive_cash_economic_configuration,
    evaluate_remote_reference_preflight,
    record_remote_reference_unavailable,
)
from test_imported_hand_decisions import baseline_decision_record
from test_imported_hand_models import (
    automatic_action,
    extraction_ready_state_payload,
    extraction_record_for_state,
    hero_facing_a_raise_decision_record,
    wager_action,
)


NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
CATEGORIES = (
    "game_economics",
    "hole_card_abstraction",
    "prior_actions",
    "stack_wager_pot",
    "table_position",
)


def decision_point() -> HeroDecisionPoint:
    extraction = extract_hero_decision_points(baseline_decision_record())
    assert extraction.outcome == "decisions"
    return extraction.decision_points[0]


def equal_blind_decision_point() -> HeroDecisionPoint:
    payload = extraction_ready_state_payload()
    payload["game"]["blinds"]["small_blind"] = Decimal("1")
    payload["game"]["blinds"]["big_blind"] = Decimal("1")
    payload["results"] = {"stated_pot": {"gross_total": Decimal("2")}}
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    1,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(2, "hero", "check", total=Decimal("1")),
                automatic_action(3, "villain", total=Decimal("1")),
            ],
        },
        {
            "street": "flop",
            "actions": [automatic_action(0, "villain", "fold")],
        },
    ]
    state = ImportedHandState.model_validate(payload)
    extraction = extract_hero_decision_points(extraction_record_for_state(state))
    assert extraction.outcome == "decisions"
    return extraction.decision_points[0]


def short_stacked_facing_raise_decision_point() -> HeroDecisionPoint:
    source = hero_facing_a_raise_decision_record(
        hero_stack=Decimal("10")
    ).active_state_for_extraction
    assert source is not None
    payload = source.model_dump(mode="python")
    payload["seats"][0]["starting_stack"] = Decimal("2")
    payload["streets"][0]["actions"][5] = wager_action(
        5,
        "hero",
        "fold",
        total=Decimal("1"),
    )
    for street in payload["streets"][1:]:
        street["actions"] = street["actions"][:2]
    payload["results"] = {"stated_pot": {"gross_total": Decimal("9")}}
    state = ImportedHandState.model_validate(payload)
    extraction = extract_hero_decision_points(extraction_record_for_state(state))
    assert extraction.outcome == "decisions"
    return extraction.decision_points[1]


def decision_binding() -> DecisionBinding:
    return DecisionBinding.from_decision(decision_point())


def canonical_economic_binding() -> EconomicConfigurationBinding:
    binding = derive_cash_economic_configuration(decision_point())
    assert binding is not None
    return binding


def disclosure(**updates: object) -> RemoteReferenceDisclosure:
    values = {
        "disclosure_revision": "disclosure-v1",
        "terms_revision": "terms-v1",
        "terms_sha256": DIGEST_A,
        "privacy_policy_revision": "privacy-v1",
        "privacy_policy_sha256": DIGEST_B,
        "retention_policy_revision": "retention-v1",
        "retention_policy_sha256": DIGEST_C,
        "training_use_policy_revision": "training-v1",
        "training_use_policy_sha256": DIGEST_D,
        "logging_policy_revision": "logging-v1",
        "logging_policy_sha256": DIGEST_A,
        "route_schema_revision": "route-v1",
        "route_schema_sha256": DIGEST_B,
        "outbound_categories": CATEGORIES,
    }
    values.update(updates)
    return RemoteReferenceDisclosure.model_validate(values)


def route_manifest(**updates: object) -> RemoteReferenceRouteManifest:
    values = {
        "manifest_revision": "manifest-v1",
        "eligible_route_context_sha256s": (
            canonical_route_request().semantic_digest(),
        ),
        "economic_configurations": (
            canonical_economic_binding(),
        ),
        "utility_configurations": (
            UtilityConfigurationBinding(
                utility_model="chip_ev",
                utility_model_revision="chip-ev-v1",
                utility_configuration_sha256=DIGEST_B,
            ),
        ),
        "hole_card_abstraction_schemas": (
            AbstractionSchemaBinding(
                abstraction_schema_revision="class-v1",
                abstraction_schema_sha256=DIGEST_C,
            ),
        ),
    }
    values.update(updates)
    return RemoteReferenceRouteManifest.model_validate(values)


def provider_policy(**updates: object) -> RemoteReferenceProviderPolicy:
    values = {
        "provider_id": "vendor-a",
        "provider_configuration_revision": "configuration-v1",
        "provider_policy_revision": "policy-v1",
        "provider_status": "active",
        "endpoint_origin": "https://reference.vendor.example",
        "reference_source_revision": "source-v1",
        "commercial_serving_rights_revision": "commercial-rights-v1",
        "commercial_serving_rights_sha256": DIGEST_C,
        "derived_output_rights_revision": "derived-rights-v1",
        "derived_output_rights_sha256": DIGEST_D,
        "disclosure": disclosure(),
        "route_manifest": route_manifest(),
    }
    values.update(updates)
    return RemoteReferenceProviderPolicy.model_validate(values)


def consent(
    *,
    policy: RemoteReferenceProviderPolicy | None = None,
    **updates: object,
) -> RemoteReferenceConsent:
    selected = policy or provider_policy()
    values = {
        "consent_id": "consent-v1",
        "consent_generation": 1,
        "provider_id": selected.provider_id,
        "provider_configuration_revision": (
            selected.provider_configuration_revision
        ),
        "provider_policy_revision": selected.provider_policy_revision,
        "provider_policy_sha256": selected.semantic_digest(),
        "endpoint_origin": selected.endpoint_origin,
        "disclosure_revision": selected.disclosure.disclosure_revision,
        "disclosure_sha256": selected.disclosure.semantic_digest(),
        "accepted_outbound_categories": (
            selected.disclosure.outbound_categories
        ),
        "status": "active",
        "consented_at": NOW - timedelta(days=1),
    }
    values.update(updates)
    return RemoteReferenceConsent.model_validate(values)


def route_request(**updates: object) -> RemoteReferenceRouteRequest:
    economic_binding = canonical_economic_binding()
    components = (
        GameEconomicsRoute(
            game_variant="texas_holdem",
            betting_limit="no_limit",
            game_format="cash",
            economic_model=economic_binding.economic_model,
            economic_model_revision=economic_binding.economic_model_revision,
            economic_configuration_sha256=(
                economic_binding.economic_configuration_sha256
            ),
            utility_model="chip_ev",
            utility_model_revision="chip-ev-v1",
            utility_configuration_sha256=DIGEST_B,
            small_blind_bb=Decimal("0.5"),
            big_blind_bb=Decimal("1"),
            ante_bb=Decimal("0"),
            ante_mode="none",
        ),
        HoleCardAbstractionRoute(
            abstraction_schema_revision="class-v1",
            abstraction_schema_sha256=DIGEST_C,
            starting_hand_class="AKs",
        ),
        PriorActionsRoute(
            actions=(
                RemotePriorAction(
                    street="preflop",
                    sequence=0,
                    actor_position="UTG",
                    action="fold",
                    all_in=False,
                ),
                RemotePriorAction(
                    street="preflop",
                    sequence=1,
                    actor_position="HJ",
                    action="fold",
                    all_in=False,
                ),
                RemotePriorAction(
                    street="preflop",
                    sequence=2,
                    actor_position="CO",
                    action="fold",
                    all_in=False,
                ),
                RemotePriorAction(
                    street="preflop",
                    sequence=3,
                    actor_position="BTN",
                    action="raise",
                    total_committed_bb=Decimal("2.5"),
                    all_in=False,
                ),
                RemotePriorAction(
                    street="preflop",
                    sequence=4,
                    actor_position="SB",
                    action="fold",
                    all_in=False,
                ),
            ),
        ),
        StackWagerPotRoute(
            hero_stack_bb=Decimal("99"),
            active_player_stacks=(
                PositionedStack(position="BB", remaining_stack_bb=Decimal("99")),
                PositionedStack(
                    position="BTN",
                    remaining_stack_bb=Decimal("97.5"),
                ),
            ),
            committed_pot_before_street_bb=Decimal("0"),
            current_street_commitments=(
                PositionedCommitment(position="BB", committed_bb=Decimal("1")),
                PositionedCommitment(
                    position="BTN",
                    committed_bb=Decimal("2.5"),
                ),
                PositionedCommitment(position="CO", committed_bb=Decimal("0")),
                PositionedCommitment(position="HJ", committed_bb=Decimal("0")),
                PositionedCommitment(
                    position="SB",
                    committed_bb=Decimal("0.5"),
                ),
                PositionedCommitment(position="UTG", committed_bb=Decimal("0")),
            ),
            pot_bb=Decimal("4"),
            current_wager_bb=Decimal("2.5"),
            amount_to_call_bb=Decimal("1.5"),
        ),
        TablePositionRoute(
            dealt_in_player_count=6,
            hero_position="BB",
            hero_button_distance=2,
            hero_action_index=5,
            active_player_positions=("BB", "BTN"),
            relative_position="not_applicable",
        ),
    )
    values = {
        "route_schema_revision": "route-v1",
        "route_schema_sha256": DIGEST_B,
        "decision_street": "preflop",
        "components": components,
    }
    values.update(updates)
    return RemoteReferenceRouteRequest.model_validate(values)


def canonical_route_request(**updates: object) -> RemoteReferenceRouteRequest:
    components = (
        route_request().components[0],
        HoleCardAbstractionRoute(
            abstraction_schema_revision="class-v1",
            abstraction_schema_sha256=DIGEST_C,
            starting_hand_class="AKo",
        ),
        PriorActionsRoute(actions=()),
        StackWagerPotRoute(
            hero_stack_bb=Decimal("99.5"),
            active_player_stacks=(
                PositionedStack(position="BB", remaining_stack_bb=Decimal("99")),
                PositionedStack(
                    position="BTN/SB",
                    remaining_stack_bb=Decimal("99.5"),
                ),
            ),
            committed_pot_before_street_bb=Decimal("0"),
            current_street_commitments=(
                PositionedCommitment(position="BB", committed_bb=Decimal("1")),
                PositionedCommitment(
                    position="BTN/SB",
                    committed_bb=Decimal("0.5"),
                ),
            ),
            pot_bb=Decimal("1.5"),
            current_wager_bb=Decimal("1"),
            amount_to_call_bb=Decimal("0.5"),
        ),
        TablePositionRoute(
            dealt_in_player_count=2,
            hero_position="BTN/SB",
            hero_button_distance=0,
            hero_action_index=0,
            active_player_positions=("BB", "BTN/SB"),
            relative_position="not_applicable",
        ),
    )
    values = {
        "route_schema_revision": "route-v1",
        "route_schema_sha256": DIGEST_B,
        "decision_street": "preflop",
        "components": components,
    }
    values.update(updates)
    return RemoteReferenceRouteRequest.model_validate(values)


def equal_blind_route_request(
    decision: HeroDecisionPoint,
) -> RemoteReferenceRouteRequest:
    request = canonical_route_request()
    economics = request.components[0]
    assert isinstance(economics, GameEconomicsRoute)
    economic_binding = derive_cash_economic_configuration(decision)
    assert economic_binding is not None
    components = list(request.components)
    components[0] = GameEconomicsRoute.model_validate(
        {
            **economics.model_dump(mode="python"),
            "economic_configuration_sha256": (
                economic_binding.economic_configuration_sha256
            ),
            "small_blind_bb": Decimal("1"),
        }
    )
    components[3] = StackWagerPotRoute(
        hero_stack_bb=Decimal("99"),
        active_player_stacks=(
            PositionedStack(position="BB", remaining_stack_bb=Decimal("99")),
            PositionedStack(
                position="BTN/SB",
                remaining_stack_bb=Decimal("99"),
            ),
        ),
        committed_pot_before_street_bb=Decimal("0"),
        current_street_commitments=(
            PositionedCommitment(position="BB", committed_bb=Decimal("1")),
            PositionedCommitment(
                position="BTN/SB",
                committed_bb=Decimal("1"),
            ),
        ),
        pot_bb=Decimal("2"),
        current_wager_bb=Decimal("1"),
        amount_to_call_bb=Decimal("0"),
    )
    return RemoteReferenceRouteRequest.model_validate(
        {
            **request.model_dump(mode="python"),
            "components": tuple(components),
        }
    )


def short_stacked_route_request() -> RemoteReferenceRouteRequest:
    request = canonical_route_request()
    components = (
        request.components[0],
        request.components[1],
        PriorActionsRoute(
            actions=(
                RemotePriorAction(
                    street="preflop",
                    sequence=0,
                    actor_position="BTN",
                    action="call",
                    total_committed_bb=Decimal("1"),
                    all_in=False,
                ),
                RemotePriorAction(
                    street="preflop",
                    sequence=1,
                    actor_position="SB",
                    action="raise",
                    total_committed_bb=Decimal("4"),
                    all_in=False,
                ),
                RemotePriorAction(
                    street="preflop",
                    sequence=2,
                    actor_position="BB",
                    action="call",
                    total_committed_bb=Decimal("4"),
                    all_in=False,
                ),
            )
        ),
        StackWagerPotRoute(
            hero_stack_bb=Decimal("1"),
            active_player_stacks=(
                PositionedStack(position="BB", remaining_stack_bb=Decimal("96")),
                PositionedStack(position="BTN", remaining_stack_bb=Decimal("1")),
                PositionedStack(position="SB", remaining_stack_bb=Decimal("96")),
            ),
            committed_pot_before_street_bb=Decimal("0"),
            current_street_commitments=(
                PositionedCommitment(position="BB", committed_bb=Decimal("4")),
                PositionedCommitment(position="BTN", committed_bb=Decimal("1")),
                PositionedCommitment(position="SB", committed_bb=Decimal("4")),
            ),
            pot_bb=Decimal("9"),
            current_wager_bb=Decimal("4"),
            amount_to_call_bb=Decimal("1"),
        ),
        TablePositionRoute(
            dealt_in_player_count=3,
            hero_position="BTN",
            hero_button_distance=0,
            hero_action_index=0,
            active_player_positions=("BB", "BTN", "SB"),
            relative_position="not_applicable",
        ),
    )
    return RemoteReferenceRouteRequest.model_validate(
        {
            **request.model_dump(mode="python"),
            "components": components,
        }
    )


def route_derivation(
    *,
    decision: HeroDecisionPoint | None = None,
    request: RemoteReferenceRouteRequest | None = None,
) -> RemoteReferenceRouteDerivation:
    return bind_remote_reference_route(
        decision or decision_point(),
        request or canonical_route_request(),
    )


def postflop_route_request() -> RemoteReferenceRouteRequest:
    preflop = route_request()
    prior_actions = preflop.components[2]
    assert isinstance(prior_actions, PriorActionsRoute)
    components = (
        BoardCardsRoute(cards=("As", "7d", "2c")),
        ConditionedRangesRoute(
            ranges=(
                ConditionedRange(position="BTN", range_artifact_sha256=DIGEST_D),
            )
        ),
        preflop.components[0],
        preflop.components[1],
        PriorActionsRoute(
            actions=(
                *prior_actions.actions,
                RemotePriorAction(
                    street="preflop",
                    sequence=5,
                    actor_position="BB",
                    action="call",
                    total_committed_bb=Decimal("2.5"),
                    all_in=False,
                ),
            )
        ),
        StackWagerPotRoute(
            hero_stack_bb=Decimal("97.5"),
            active_player_stacks=(
                PositionedStack(
                    position="BB",
                    remaining_stack_bb=Decimal("97.5"),
                ),
                PositionedStack(
                    position="BTN",
                    remaining_stack_bb=Decimal("97.5"),
                ),
            ),
            committed_pot_before_street_bb=Decimal("5.5"),
            current_street_commitments=tuple(
                PositionedCommitment(position=position, committed_bb=Decimal("0"))
                for position in ("BB", "BTN", "CO", "HJ", "SB", "UTG")
            ),
            pot_bb=Decimal("5.5"),
            current_wager_bb=Decimal("0"),
            amount_to_call_bb=Decimal("0"),
        ),
        TablePositionRoute(
            dealt_in_player_count=6,
            hero_position="BB",
            hero_button_distance=2,
            hero_action_index=5,
            active_player_positions=("BB", "BTN"),
            relative_position="out_of_position",
        ),
    )
    return RemoteReferenceRouteRequest(
        route_schema_revision="route-v1",
        route_schema_sha256=DIGEST_B,
        decision_street="flop",
        components=components,
    )


def preflight(
    *,
    mode: object = "remote_enabled",
    policy: RemoteReferenceProviderPolicy | None = None,
    accepted: RemoteReferenceConsent | None = None,
    request: RemoteReferenceRouteRequest | None = None,
):
    selected = policy or provider_policy()
    selected_consent = accepted if accepted is not None else consent(policy=selected)
    selected_request = request if request is not None else canonical_route_request()
    return evaluate_remote_reference_preflight(
        decision_point(),
        mode=mode,  # type: ignore[arg-type]
        policy=selected,
        consent=selected_consent,
        route=route_derivation(request=selected_request),
        now=NOW,
    )


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        ({"mode": "unknown"}, "mode_invalid"),
        ({"mode": "local_only"}, "local_only"),
        ({"policy": None}, "provider_unconfigured"),
        (
            {"policy": provider_policy(provider_status="staged")},
            "provider_inactive",
        ),
    ],
)
def test_preflight_fails_closed_before_consent(
    overrides: dict[str, object],
    expected_reason: str,
) -> None:
    result = evaluate_remote_reference_preflight(
        decision_point(),
        mode=overrides.get("mode", "remote_enabled"),  # type: ignore[arg-type]
        policy=overrides.get("policy", provider_policy()),  # type: ignore[arg-type]
        consent=None,
        route=None,
        now=NOW,
    )

    assert result.outcome == "unavailable"
    assert result.reason == expected_reason
    assert result.outbound_request is None
    assert result.resolved_reference is None
    assert result.policy_grade_eligibility == "ungraded"


def test_preflight_rejects_a_naive_clock_without_crashing() -> None:
    result = evaluate_remote_reference_preflight(
        decision_point(),
        mode="remote_enabled",
        policy=provider_policy(),
        consent=consent(),
        route=route_derivation(),
        now=datetime(2026, 9, 1, 8, 0),
    )

    assert result.outcome == "unavailable"
    assert result.reason == "clock_invalid"
    assert result.evaluated_at is None
    assert result.outbound_request is None


def test_exact_active_consent_yields_only_a_dispatch_candidate() -> None:
    result = preflight()

    assert result.outcome == "dispatch_candidate"
    assert result.reason == "preflight_passed"
    assert result.fresh_consent_recheck == (
        "required_immediately_before_dispatch"
    )
    assert result.policy_grade_eligibility == "ungraded"
    assert result.resolved_reference is None
    assert result.outbound_request == canonical_route_request()
    assert result.request_sha256 == canonical_route_request().semantic_digest()
    assert result.decision_state_sha256 == route_derivation().decision_state_sha256
    assert "decision_state_sha256" not in result.outbound_request.model_dump(
        mode="json"
    )
    assert result.provider_policy_sha256 == provider_policy().semantic_digest()
    assert result.route_manifest_sha256 == route_manifest().semantic_digest()
    assert result.commercial_serving_rights_revision == "commercial-rights-v1"
    assert result.derived_output_rights_revision == "derived-rights-v1"


def test_route_factory_binds_the_full_canonical_decision_state() -> None:
    decision = decision_point()

    route = bind_remote_reference_route(decision, canonical_route_request())

    assert route.decision == DecisionBinding.from_decision(decision)
    assert route.outbound_request == canonical_route_request()
    assert len(route.decision_state_sha256) == 64


def test_route_factory_accepts_equal_blind_cash_game() -> None:
    decision = equal_blind_decision_point()
    request = equal_blind_route_request(decision)

    route = bind_remote_reference_route(decision, request)

    economics = route.outbound_request.components[0]
    assert isinstance(economics, GameEconomicsRoute)
    assert economics.small_blind_bb == economics.big_blind_bb == Decimal("1")


def test_route_factory_caps_call_at_short_stacked_hero_chips() -> None:
    decision = short_stacked_facing_raise_decision_point()
    assert decision.state.amount_to_call == Decimal("3")
    assert decision.state.hero_stack_before_action == Decimal("1")
    request = short_stacked_route_request()

    route = bind_remote_reference_route(decision, request)

    stacks = route.outbound_request.components[3]
    assert isinstance(stacks, StackWagerPotRoute)
    assert stacks.amount_to_call_bb == stacks.hero_stack_bb == Decimal("1")


def test_cash_economic_configuration_is_derived_from_approved_state() -> None:
    decision = decision_point()
    binding = derive_cash_economic_configuration(decision)

    assert binding is not None
    assert binding.economic_model == "cash_rake"
    assert binding.economic_model_revision == "canonical-cash-economics-v1"
    economics = canonical_route_request().components[0]
    assert isinstance(economics, GameEconomicsRoute)
    assert economics.economic_configuration_sha256 == (
        binding.economic_configuration_sha256
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("currency", "EUR"),
        ("percentage", Decimal("0.06")),
        ("cap", Decimal("4")),
        ("fixed_drop", Decimal("0.1")),
        ("description", "time collection applies"),
    ],
)
def test_route_factory_rejects_a_different_approved_cash_schedule(
    field: str,
    value: object,
) -> None:
    payload = decision_point().model_dump(mode="python")
    economics = payload["state"]["economics"]
    if field == "currency":
        economics[field] = value
    else:
        economics["rake"][field] = value
    changed_decision = HeroDecisionPoint.model_validate(payload)

    changed_binding = derive_cash_economic_configuration(changed_decision)
    assert changed_binding is not None
    assert changed_binding != canonical_economic_binding()
    with pytest.raises(ValueError, match="canonical decision state"):
        bind_remote_reference_route(changed_decision, canonical_route_request())


def test_route_factory_binds_the_absolute_blind_level() -> None:
    payload = decision_point().model_dump(mode="python")
    economics = payload["state"]["economics"]

    def scale_chips(value: object) -> object:
        if isinstance(value, Decimal):
            return value * 2
        if isinstance(value, list):
            return [scale_chips(item) for item in value]
        if isinstance(value, dict):
            return {key: scale_chips(item) for key, item in value.items()}
        return value

    payload["state"] = scale_chips(payload["state"])
    payload["state"]["economics"] = economics
    payload["table_action"] = scale_chips(payload["table_action"])
    changed_decision = HeroDecisionPoint.model_validate(payload)

    changed_binding = derive_cash_economic_configuration(changed_decision)
    assert changed_binding is not None
    assert changed_binding != canonical_economic_binding()
    with pytest.raises(ValueError, match="canonical decision state"):
        bind_remote_reference_route(changed_decision, canonical_route_request())


def test_route_derivation_must_match_the_canonical_decision() -> None:
    original_decision = decision_point()
    decision_payload = original_decision.model_dump(mode="python")
    decision_payload["state"]["hero_cards"] = [
        {"rank": "Q", "suit": "spades"},
        {"rank": "Q", "suit": "hearts"},
    ]
    different_decision = HeroDecisionPoint.model_validate(decision_payload)
    different_components = list(canonical_route_request().components)
    different_components[1] = HoleCardAbstractionRoute(
        abstraction_schema_revision="class-v1",
        abstraction_schema_sha256=DIGEST_C,
        starting_hand_class="QQ",
    )
    different_route = bind_remote_reference_route(
        different_decision,
        canonical_route_request(components=tuple(different_components)),
    )
    forged_route = RemoteReferenceRouteDerivation(
        decision=DecisionBinding.from_decision(different_decision),
        decision_state_sha256=different_route.decision_state_sha256,
        outbound_request=canonical_route_request(),
    )
    request = canonical_route_request()
    policy = provider_policy()

    with pytest.raises(ValueError, match="canonical decision state"):
        bind_remote_reference_route(different_decision, request)

    result = evaluate_remote_reference_preflight(
        different_decision,
        mode="remote_enabled",
        policy=policy,
        consent=consent(policy=policy),
        route=forged_route,
        now=NOW,
    )

    assert result.outcome == "unavailable"
    assert result.reason == "route_binding_mismatch"
    assert result.decision == DecisionBinding.from_decision(different_decision)
    assert result.request_sha256 == request.semantic_digest()
    assert result.outbound_request is None


@pytest.mark.parametrize(
    ("accepted", "reason"),
    [
        (None, "consent_absent"),
        (
            consent(
                status="revoked",
                revoked_at=NOW - timedelta(hours=1),
                consent_generation=2,
            ),
            "consent_revoked",
        ),
        (
            consent(consented_at=NOW + timedelta(minutes=1)),
            "consent_not_yet_active",
        ),
        (
            consent(expires_at=NOW),
            "consent_expired",
        ),
    ],
)
def test_consent_lifecycle_blocks_egress(
    accepted: RemoteReferenceConsent | None,
    reason: str,
) -> None:
    policy = provider_policy()
    result = evaluate_remote_reference_preflight(
        decision_point(),
        mode="remote_enabled",
        policy=policy,
        consent=accepted,
        route=route_derivation(),
        now=NOW,
    )

    assert result.outcome == "unavailable"
    assert result.reason == reason
    assert result.outbound_request is None


def test_revocation_requires_a_fresh_preflight() -> None:
    initial = preflight()
    revoked = consent(
        status="revoked",
        revoked_at=NOW + timedelta(seconds=1),
        consent_generation=2,
    )

    after_revocation = evaluate_remote_reference_preflight(
        decision_point(),
        mode="remote_enabled",
        policy=provider_policy(),
        consent=revoked,
        route=route_derivation(),
        now=NOW + timedelta(seconds=1),
    )

    assert initial.outcome == "dispatch_candidate"
    assert after_revocation.outcome == "unavailable"
    assert after_revocation.reason == "consent_revoked"
    assert after_revocation.outbound_request is None


@pytest.mark.parametrize(
    "policy_update",
    [
        {"provider_id": "vendor-b"},
        {"provider_configuration_revision": "configuration-v2"},
        {"provider_policy_revision": "policy-v2"},
        {"endpoint_origin": "https://other.vendor.example"},
        {"reference_source_revision": "source-v2"},
        {"commercial_serving_rights_sha256": DIGEST_A},
    ],
)
def test_consent_is_bound_to_exact_provider_policy(
    policy_update: dict[str, object],
) -> None:
    original = provider_policy()
    changed = provider_policy(**policy_update)
    result = evaluate_remote_reference_preflight(
        decision_point(),
        mode="remote_enabled",
        policy=changed,
        consent=consent(policy=original),
        route=route_derivation(),
        now=NOW,
    )

    assert result.outcome == "unavailable"
    assert result.reason == "provider_policy_mismatch"
    assert result.outbound_request is None


def test_consent_is_bound_to_exact_disclosure() -> None:
    original = provider_policy()
    changed = provider_policy(
        disclosure=disclosure(terms_revision="terms-v2")
    )

    result = evaluate_remote_reference_preflight(
        decision_point(),
        mode="remote_enabled",
        policy=changed,
        consent=consent(policy=original),
        route=route_derivation(),
        now=NOW,
    )

    assert result.reason == "disclosure_mismatch"
    assert result.outbound_request is None


def test_categories_and_route_schema_are_exactly_bound() -> None:
    policy = provider_policy()
    category_mismatch = evaluate_remote_reference_preflight(
        decision_point(),
        mode="remote_enabled",
        policy=policy,
        consent=consent(
            policy=policy,
            accepted_outbound_categories=("game_economics",),
        ),
        route=route_derivation(),
        now=NOW,
    )
    schema_mismatch = evaluate_remote_reference_preflight(
        decision_point(),
        mode="remote_enabled",
        policy=policy,
        consent=consent(policy=policy),
        route=route_derivation(
            request=canonical_route_request(route_schema_revision="route-v2")
        ),
        now=NOW,
    )
    request_missing = evaluate_remote_reference_preflight(
        decision_point(),
        mode="remote_enabled",
        policy=policy,
        consent=consent(policy=policy),
        route=None,
        now=NOW,
    )
    raw_components = list(canonical_route_request().components)
    raw_components[1] = HoleCardsRoute(cards=("Ah", "Kd"))
    request_category_mismatch = evaluate_remote_reference_preflight(
        decision_point(),
        mode="remote_enabled",
        policy=policy,
        consent=consent(policy=policy),
        route=route_derivation(
            request=canonical_route_request(components=tuple(raw_components))
        ),
        now=NOW,
    )

    assert category_mismatch.reason == "outbound_categories_mismatch"
    assert schema_mismatch.reason == "route_schema_mismatch"
    assert request_missing.reason == "route_unavailable"
    assert request_category_mismatch.reason == "outbound_categories_mismatch"
    assert category_mismatch.outbound_request is None
    assert schema_mismatch.outbound_request is None


def test_route_revisions_and_digests_require_provider_manifest_membership() -> None:
    policy = provider_policy()
    components = list(canonical_route_request().components)
    components[1] = HoleCardAbstractionRoute(
        abstraction_schema_revision="class-v2",
        abstraction_schema_sha256=DIGEST_D,
        starting_hand_class="AKo",
    )

    result = evaluate_remote_reference_preflight(
        decision_point(),
        mode="remote_enabled",
        policy=policy,
        consent=consent(policy=policy),
        route=route_derivation(
            request=canonical_route_request(components=tuple(components))
        ),
        now=NOW,
    )

    assert result.outcome == "unavailable"
    assert result.reason == "route_manifest_mismatch"
    assert result.outbound_request is None


def test_provider_manifest_binds_the_exact_route_context() -> None:
    request = canonical_route_request()
    policy = provider_policy(
        route_manifest=route_manifest(
            eligible_route_context_sha256s=(DIGEST_D,),
        )
    )

    result = evaluate_remote_reference_preflight(
        decision_point(),
        mode="remote_enabled",
        policy=policy,
        consent=consent(policy=policy),
        route=route_derivation(request=request),
        now=NOW,
    )

    assert request.semantic_digest() not in (
        policy.route_manifest.eligible_route_context_sha256s
    )
    assert result.outcome == "unavailable"
    assert result.reason == "route_manifest_mismatch"
    assert result.outbound_request is None


def test_postflop_ranges_remain_unavailable_until_context_bound() -> None:
    categories = (
        "board_cards",
        "conditioned_ranges",
        "game_economics",
        "hole_card_abstraction",
        "prior_actions",
        "stack_wager_pot",
        "table_position",
    )
    policy = provider_policy(
        disclosure=disclosure(outbound_categories=categories)
    )

    with pytest.raises(ValueError, match="canonical decision state"):
        bind_remote_reference_route(decision_point(), postflop_route_request())

    result = evaluate_remote_reference_preflight(
        decision_point(),
        mode="remote_enabled",
        policy=policy,
        consent=consent(policy=policy),
        route=None,
        now=NOW,
    )

    assert result.outcome == "unavailable"
    assert result.reason == "route_unavailable"
    assert result.outbound_request is None


@pytest.mark.parametrize(
    "origin",
    [
        "http://reference.vendor.example",
        "https://reference.vendor.example/",
        "https://reference.vendor.example/path",
        "https://user@reference.vendor.example",
        "https://reference.vendor.example?query=yes",
        "https://reference.vendor.example#fragment",
        "https://REFERENCE.vendor.example",
        "https://[::1]",
        "https://127.0.0.1",
        "https://localhost",
        "https://reference.vendor.example:0",
        "https://reference.vendor.example:99999",
    ],
)
def test_provider_and_consent_reject_noncanonical_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        provider_policy(endpoint_origin=origin)
    with pytest.raises(ValidationError):
        consent(endpoint_origin=origin)


def test_route_models_are_closed_and_forbid_identity_fields() -> None:
    root_payload = route_request().model_dump(mode="python")
    root_payload["source_hand_id"] = "secret-hand"
    with pytest.raises(ValidationError):
        RemoteReferenceRouteRequest.model_validate(root_payload)

    nested_payload = route_request().model_dump(mode="python")
    nested_payload["components"][0]["session_id"] = "secret-session"
    with pytest.raises(ValidationError):
        RemoteReferenceRouteRequest.model_validate(nested_payload)


def test_outbound_payload_excludes_local_identity_and_prohibited_categories() -> None:
    request = route_request()
    payload = request.model_dump(mode="json")
    serialized = json.dumps(payload, sort_keys=True)
    forbidden_keys = {
        "canonical_revision",
        "decision_index",
        "deletion_generation",
        "hand_history",
        "hand_id",
        "identity",
        "import_id",
        "mastery",
        "namespace",
        "player_name",
        "profile",
        "screenshot",
        "session_id",
        "site",
        "source_hand_id",
        "timestamp",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {
                nested
                for item in value.values()
                for nested in keys(item)
            }
        if isinstance(value, list):
            return {nested for item in value for nested in keys(item)}
        return set()

    assert keys(payload).isdisjoint(forbidden_keys)
    binding = decision_binding()
    assert binding.identity.source_hand_id not in serialized
    assert binding.identity.namespace not in serialized


def test_request_digest_binds_exact_route_content() -> None:
    original = route_request()
    changed_components = list(original.components)
    changed_components[3] = StackWagerPotRoute(
        hero_stack_bb=Decimal("98"),
        active_player_stacks=(
            PositionedStack(position="BB", remaining_stack_bb=Decimal("98")),
            PositionedStack(position="BTN", remaining_stack_bb=Decimal("95")),
        ),
        committed_pot_before_street_bb=Decimal("0"),
        current_street_commitments=(
            PositionedCommitment(position="BB", committed_bb=Decimal("1")),
            PositionedCommitment(position="BTN", committed_bb=Decimal("2.5")),
            PositionedCommitment(position="CO", committed_bb=Decimal("0")),
            PositionedCommitment(position="HJ", committed_bb=Decimal("0")),
            PositionedCommitment(position="SB", committed_bb=Decimal("0.5")),
            PositionedCommitment(position="UTG", committed_bb=Decimal("0")),
        ),
        pot_bb=Decimal("4"),
        current_wager_bb=Decimal("2.5"),
        amount_to_call_bb=Decimal("1.5"),
    )
    changed = route_request(components=tuple(changed_components))

    assert original.semantic_digest() != changed.semantic_digest()
    assert original.canonical_bytes() != changed.canonical_bytes()


def test_route_requires_complete_structural_state() -> None:
    incomplete = tuple(
        component
        for component in route_request().components
        if component.category != "prior_actions"
    )

    with pytest.raises(ValidationError, match="required structural state"):
        route_request(components=incomplete)


@pytest.mark.parametrize(
    "updates",
    [
        {
            "game_format": "cash",
            "economic_model": "tournament_icm",
            "utility_model": "icm_equity",
        },
        {
            "game_format": "tournament",
            "economic_model": "cash_rake",
            "utility_model": "chip_ev",
        },
        {
            "game_format": "tournament",
            "economic_model": "tournament_icm",
            "utility_model": "icm_equity",
        },
        {"betting_limit": "pot_limit"},
    ],
)
def test_economics_reject_incompatible_or_impossible_inputs(
    updates: dict[str, object],
) -> None:
    payload = route_request().components[0].model_dump(mode="python")
    payload.update(updates)
    with pytest.raises(ValidationError):
        GameEconomicsRoute.model_validate(payload)


def test_positions_must_exist_at_the_dealt_in_table() -> None:
    with pytest.raises(ValidationError, match="hero position"):
        TablePositionRoute(
            dealt_in_player_count=2,
            hero_position="UTG",
            hero_button_distance=0,
            hero_action_index=0,
            active_player_positions=("BB", "BTN/SB"),
            relative_position="out_of_position",
        )

    request = route_request()
    invalid_prior_actions = PriorActionsRoute(
        actions=(
            RemotePriorAction(
                street="preflop",
                sequence=0,
                actor_position="UTG+3",
                action="raise",
                total_committed_bb=Decimal("2.5"),
                all_in=False,
            ),
        )
    )
    components = list(request.components)
    components[2] = invalid_prior_actions
    with pytest.raises(ValidationError, match="position must exist"):
        route_request(components=tuple(components))


@pytest.mark.parametrize(
    "action",
    [
        RemotePriorAction.model_construct(
            street="preflop",
            sequence=0,
            actor_position="BTN",
            action="raise",
            total_committed_bb=Decimal("0"),
            all_in=False,
        ),
        RemotePriorAction.model_construct(
            street="preflop",
            sequence=0,
            actor_position="BTN",
            action="check",
            total_committed_bb=None,
            all_in=True,
        ),
    ],
)
def test_prior_actions_reject_impossible_all_in_or_zero_chip_routes(
    action: RemotePriorAction,
) -> None:
    with pytest.raises(ValidationError):
        RemotePriorAction.model_validate(action.model_dump(mode="python"))


def test_route_rejects_cards_repeated_between_board_and_hole() -> None:
    preflop = route_request()
    postflop_components = (
        BoardCardsRoute(cards=("As", "7d", "2c")),
        ConditionedRangesRoute(
            ranges=(
                ConditionedRange(position="BTN", range_artifact_sha256=DIGEST_B),
            )
        ),
        preflop.components[0],
        HoleCardsRoute(cards=("As", "Kd")),
        preflop.components[2],
        preflop.components[3],
        TablePositionRoute(
            dealt_in_player_count=6,
            hero_position="BB",
            hero_button_distance=2,
            hero_action_index=5,
            active_player_positions=("BB", "BTN"),
            relative_position="out_of_position",
        ),
    )

    with pytest.raises(ValidationError, match="globally unique"):
        route_request(
            decision_street="flop",
            components=postflop_components,
        )


def test_hole_cards_are_canonicalized_before_exact_route_hashing() -> None:
    original_components = list(route_request().components)
    original_components[1] = HoleCardsRoute(cards=("As", "Kd"))
    reversed_components = list(route_request().components)
    reversed_components[1] = HoleCardsRoute(cards=("Kd", "As"))

    original = route_request(components=tuple(original_components))
    reversed_order = route_request(components=tuple(reversed_components))

    assert original.components[1] == HoleCardsRoute(cards=("As", "Kd"))
    assert original == reversed_order
    assert original.semantic_digest() == reversed_order.semantic_digest()


def test_route_hash_normalizes_equivalent_decimal_exponents() -> None:
    original = canonical_route_request()
    components = list(original.components)
    stack = components[3]
    assert isinstance(stack, StackWagerPotRoute)
    stack_payload = stack.model_dump(mode="python")
    stack_payload["hero_stack_bb"] = Decimal("99.500")
    stack_payload["pot_bb"] = Decimal("1.5000")
    components[3] = StackWagerPotRoute.model_validate(stack_payload)
    equivalent = canonical_route_request(components=tuple(components))

    assert original == equivalent
    assert original.canonical_bytes() == equivalent.canonical_bytes()
    assert original.semantic_digest() == equivalent.semantic_digest()


def test_decision_state_hash_normalizes_equivalent_decimal_exponents() -> None:
    original = decision_point()
    equivalent_payload = original.model_dump(mode="python")
    equivalent_payload["state"]["hero_stack_before_action"] = Decimal("99.500")
    equivalent = HeroDecisionPoint.model_validate(equivalent_payload)
    route = route_derivation(decision=original)
    policy = provider_policy()

    result = evaluate_remote_reference_preflight(
        equivalent,
        mode="remote_enabled",
        policy=policy,
        consent=consent(policy=policy),
        route=route,
        now=NOW,
    )

    assert original.state == equivalent.state
    assert result.outcome == "dispatch_candidate"
    assert result.reason == "preflight_passed"


def test_postflop_ranges_cover_every_active_opponent_exactly() -> None:
    preflop = route_request()
    incomplete_ranges = (
        BoardCardsRoute(cards=("As", "7d", "2c")),
        ConditionedRangesRoute(
            ranges=(
                ConditionedRange(position="BTN", range_artifact_sha256=DIGEST_B),
            )
        ),
        preflop.components[0],
        HoleCardsRoute(cards=("Ah", "Kd")),
        preflop.components[2],
        preflop.components[3],
        TablePositionRoute(
            dealt_in_player_count=6,
            hero_position="BB",
            hero_button_distance=2,
            hero_action_index=5,
            active_player_positions=("BB", "BTN", "CO"),
            relative_position="not_applicable",
        ),
    )

    with pytest.raises(ValidationError, match="every active opponent"):
        route_request(
            decision_street="flop",
            components=incomplete_ranges,
        )


def test_position_bound_stacks_cover_every_active_player() -> None:
    request = route_request()
    components = list(request.components)
    components[4] = TablePositionRoute(
        dealt_in_player_count=6,
        hero_position="BB",
        hero_button_distance=2,
        hero_action_index=5,
        active_player_positions=("BB", "BTN", "CO"),
        relative_position="not_applicable",
    )

    with pytest.raises(ValidationError, match="every active player"):
        route_request(components=tuple(components))


@pytest.mark.parametrize(
    "update",
    [
        {"current_wager_bb": Decimal("1")},
        {"pot_bb": Decimal("3.5")},
    ],
)
def test_wager_and_pot_are_derived_from_position_commitments(
    update: dict[str, object],
) -> None:
    stack = route_request().components[3]
    payload = stack.model_dump(mode="python")
    payload.update(update)
    with pytest.raises(ValidationError):
        StackWagerPotRoute.model_validate(payload)


def test_call_and_action_totals_match_position_commitments() -> None:
    request = route_request()
    stack_payload = request.components[3].model_dump(mode="python")
    stack_payload["amount_to_call_bb"] = Decimal("1")
    components = list(request.components)
    components[3] = StackWagerPotRoute.model_validate(stack_payload)
    with pytest.raises(ValidationError, match="amount to call"):
        route_request(components=tuple(components))

    prior_actions = request.components[2]
    assert isinstance(prior_actions, PriorActionsRoute)
    actions = list(prior_actions.actions)
    actions[3] = RemotePriorAction(
        street="preflop",
        sequence=3,
        actor_position="BTN",
        action="raise",
        total_committed_bb=Decimal("3"),
        all_in=False,
    )
    components = list(request.components)
    components[2] = PriorActionsRoute(actions=tuple(actions))
    with pytest.raises(ValidationError, match="action totals"):
        route_request(components=tuple(components))


@pytest.mark.parametrize(
    ("action_update", "message"),
    [
        ({"action": "call"}, "call must match the running wager"),
        (
            {"action": "check", "total_committed_bb": None},
            "facing a wager cannot check",
        ),
        ({"action": "bet"}, "bet cannot be made into an existing wager"),
        (
            {"total_committed_bb": Decimal("1.5")},
            "non-all-in raise must meet the minimum",
        ),
    ],
)
def test_action_types_are_validated_against_the_running_wager(
    action_update: dict[str, object],
    message: str,
) -> None:
    request = route_request()
    prior_actions = request.components[2]
    assert isinstance(prior_actions, PriorActionsRoute)
    actions = list(prior_actions.actions)
    action_payload = actions[3].model_dump(mode="python")
    action_payload.update(action_update)
    actions[3] = RemotePriorAction.model_validate(action_payload)
    components = list(request.components)
    components[2] = PriorActionsRoute(actions=tuple(actions))

    with pytest.raises(ValidationError, match=message):
        route_request(components=tuple(components))


def test_active_players_are_derived_from_action_line_survivors() -> None:
    request = route_request()
    components = list(request.components)
    stack_payload = components[3].model_dump(mode="python")
    stack_payload["active_player_stacks"] = (
        PositionedStack(position="BB", remaining_stack_bb=Decimal("99")),
        PositionedStack(position="CO", remaining_stack_bb=Decimal("100")),
    )
    components[3] = StackWagerPotRoute.model_validate(stack_payload)
    components[4] = TablePositionRoute(
        dealt_in_player_count=6,
        hero_position="BB",
        hero_button_distance=2,
        hero_action_index=5,
        active_player_positions=("BB", "CO"),
        relative_position="not_applicable",
    )

    with pytest.raises(ValidationError, match="action-line survivors"):
        route_request(components=tuple(components))


def test_all_in_players_remain_active_with_no_remaining_stack() -> None:
    request = route_request()
    components = list(request.components)
    prior_actions = components[2]
    assert isinstance(prior_actions, PriorActionsRoute)
    actions = list(prior_actions.actions)
    actions[3] = RemotePriorAction(
        street="preflop",
        sequence=3,
        actor_position="BTN",
        action="raise",
        total_committed_bb=Decimal("100"),
        all_in=True,
    )
    components[2] = PriorActionsRoute(actions=tuple(actions))
    components[3] = StackWagerPotRoute(
        hero_stack_bb=Decimal("99"),
        active_player_stacks=(
            PositionedStack(position="BB", remaining_stack_bb=Decimal("99")),
            PositionedStack(position="BTN", remaining_stack_bb=Decimal("0")),
        ),
        committed_pot_before_street_bb=Decimal("0"),
        current_street_commitments=(
            PositionedCommitment(position="BB", committed_bb=Decimal("1")),
            PositionedCommitment(position="BTN", committed_bb=Decimal("100")),
            PositionedCommitment(position="CO", committed_bb=Decimal("0")),
            PositionedCommitment(position="HJ", committed_bb=Decimal("0")),
            PositionedCommitment(position="SB", committed_bb=Decimal("0.5")),
            PositionedCommitment(position="UTG", committed_bb=Decimal("0")),
        ),
        pot_bb=Decimal("101.5"),
        current_wager_bb=Decimal("100"),
        amount_to_call_bb=Decimal("99"),
    )

    result = route_request(components=tuple(components))

    table = result.components[4]
    assert isinstance(table, TablePositionRoute)
    assert table.active_player_positions == ("BB", "BTN")


def test_stackless_hero_cannot_become_a_dispatchable_decision() -> None:
    request = route_request()
    components = list(request.components)
    stack_payload = components[3].model_dump(mode="python")
    stack_payload["hero_stack_bb"] = Decimal("0")
    stack_payload["active_player_stacks"] = (
        PositionedStack(position="BB", remaining_stack_bb=Decimal("0")),
        PositionedStack(position="BTN", remaining_stack_bb=Decimal("97.5")),
    )
    stack_payload["amount_to_call_bb"] = Decimal("0")
    components[3] = StackWagerPotRoute.model_validate(stack_payload)

    with pytest.raises(ValidationError, match="no remaining stack"):
        route_request(components=tuple(components))


def test_forced_post_all_in_is_not_treated_as_pending_action() -> None:
    request = route_request()
    components = list(request.components)
    prior_actions = components[2]
    assert isinstance(prior_actions, PriorActionsRoute)
    components[2] = PriorActionsRoute(actions=prior_actions.actions[:-1])
    stack_payload = components[3].model_dump(mode="python")
    stack_payload["active_player_stacks"] = (
        PositionedStack(position="BB", remaining_stack_bb=Decimal("99")),
        PositionedStack(position="BTN", remaining_stack_bb=Decimal("97.5")),
        PositionedStack(position="SB", remaining_stack_bb=Decimal("0")),
    )
    stack_payload["current_street_commitments"] = (
        PositionedCommitment(position="BB", committed_bb=Decimal("1")),
        PositionedCommitment(position="BTN", committed_bb=Decimal("2.5")),
        PositionedCommitment(position="CO", committed_bb=Decimal("0")),
        PositionedCommitment(position="HJ", committed_bb=Decimal("0")),
        PositionedCommitment(position="SB", committed_bb=Decimal("0.3")),
        PositionedCommitment(position="UTG", committed_bb=Decimal("0")),
    )
    stack_payload["pot_bb"] = Decimal("3.8")
    components[3] = StackWagerPotRoute.model_validate(stack_payload)
    components[4] = TablePositionRoute(
        dealt_in_player_count=6,
        hero_position="BB",
        hero_button_distance=2,
        hero_action_index=5,
        active_player_positions=("BB", "BTN", "SB"),
        relative_position="not_applicable",
    )

    result = route_request(components=tuple(components))

    table = result.components[4]
    assert isinstance(table, TablePositionRoute)
    assert table.active_player_positions == ("BB", "BTN", "SB")


def test_heads_up_short_big_blind_uses_the_actual_posted_wager() -> None:
    base = route_request()
    components = (
        base.components[0],
        base.components[1],
        PriorActionsRoute(actions=()),
        StackWagerPotRoute(
            hero_stack_bb=Decimal("99.5"),
            active_player_stacks=(
                PositionedStack(position="BB", remaining_stack_bb=Decimal("0")),
                PositionedStack(
                    position="BTN/SB",
                    remaining_stack_bb=Decimal("99.5"),
                ),
            ),
            committed_pot_before_street_bb=Decimal("0"),
            current_street_commitments=(
                PositionedCommitment(position="BB", committed_bb=Decimal("0.7")),
                PositionedCommitment(
                    position="BTN/SB",
                    committed_bb=Decimal("0.5"),
                ),
            ),
            pot_bb=Decimal("1.2"),
            current_wager_bb=Decimal("0.7"),
            amount_to_call_bb=Decimal("0.2"),
        ),
        TablePositionRoute(
            dealt_in_player_count=2,
            hero_position="BTN/SB",
            hero_button_distance=0,
            hero_action_index=0,
            active_player_positions=("BB", "BTN/SB"),
            relative_position="not_applicable",
        ),
    )

    result = route_request(components=components)

    stack = result.components[3]
    assert isinstance(stack, StackWagerPotRoute)
    assert stack.pot_bb == Decimal("1.2")
    assert stack.current_wager_bb == Decimal("0.7")


def test_multiway_short_big_blind_keeps_the_nominal_betting_wager() -> None:
    base = route_request()
    components = (
        base.components[0],
        base.components[1],
        PriorActionsRoute(actions=()),
        StackWagerPotRoute(
            hero_stack_bb=Decimal("100"),
            active_player_stacks=(
                PositionedStack(position="BB", remaining_stack_bb=Decimal("0")),
                PositionedStack(position="BTN", remaining_stack_bb=Decimal("100")),
                PositionedStack(position="SB", remaining_stack_bb=Decimal("99.5")),
            ),
            committed_pot_before_street_bb=Decimal("0"),
            current_street_commitments=(
                PositionedCommitment(position="BB", committed_bb=Decimal("0.7")),
                PositionedCommitment(position="BTN", committed_bb=Decimal("0")),
                PositionedCommitment(position="SB", committed_bb=Decimal("0.5")),
            ),
            pot_bb=Decimal("1.2"),
            current_wager_bb=Decimal("1"),
            amount_to_call_bb=Decimal("1"),
        ),
        TablePositionRoute(
            dealt_in_player_count=3,
            hero_position="BTN",
            hero_button_distance=0,
            hero_action_index=0,
            active_player_positions=("BB", "BTN", "SB"),
            relative_position="not_applicable",
        ),
    )

    result = route_request(components=components)

    stack = result.components[3]
    assert isinstance(stack, StackWagerPotRoute)
    assert stack.current_wager_bb == Decimal("1")


def test_betting_closes_when_the_only_chipped_player_already_matches() -> None:
    base = route_request()
    components = (
        base.components[0],
        base.components[1],
        PriorActionsRoute(actions=()),
        StackWagerPotRoute(
            hero_stack_bb=Decimal("99"),
            active_player_stacks=(
                PositionedStack(position="BB", remaining_stack_bb=Decimal("99")),
                PositionedStack(
                    position="BTN/SB",
                    remaining_stack_bb=Decimal("0"),
                ),
            ),
            committed_pot_before_street_bb=Decimal("0"),
            current_street_commitments=(
                PositionedCommitment(position="BB", committed_bb=Decimal("1")),
                PositionedCommitment(
                    position="BTN/SB",
                    committed_bb=Decimal("0.5"),
                ),
            ),
            pot_bb=Decimal("1.5"),
            current_wager_bb=Decimal("1"),
            amount_to_call_bb=Decimal("0"),
        ),
        TablePositionRoute(
            dealt_in_player_count=2,
            hero_position="BB",
            hero_button_distance=1,
            hero_action_index=1,
            active_player_positions=("BB", "BTN/SB"),
            relative_position="not_applicable",
        ),
    )

    with pytest.raises(ValidationError, match="betting round closed"):
        route_request(components=components)


def test_sole_chipped_hero_remains_pending_when_facing_an_all_in() -> None:
    base = route_request()
    components = (
        base.components[0],
        base.components[1],
        PriorActionsRoute(
            actions=(
                RemotePriorAction(
                    street="preflop",
                    sequence=0,
                    actor_position="BTN/SB",
                    action="raise",
                    total_committed_bb=Decimal("2"),
                    all_in=True,
                ),
            )
        ),
        StackWagerPotRoute(
            hero_stack_bb=Decimal("99"),
            active_player_stacks=(
                PositionedStack(position="BB", remaining_stack_bb=Decimal("99")),
                PositionedStack(
                    position="BTN/SB",
                    remaining_stack_bb=Decimal("0"),
                ),
            ),
            committed_pot_before_street_bb=Decimal("0"),
            current_street_commitments=(
                PositionedCommitment(position="BB", committed_bb=Decimal("1")),
                PositionedCommitment(
                    position="BTN/SB",
                    committed_bb=Decimal("2"),
                ),
            ),
            pot_bb=Decimal("3"),
            current_wager_bb=Decimal("2"),
            amount_to_call_bb=Decimal("1"),
        ),
        TablePositionRoute(
            dealt_in_player_count=2,
            hero_position="BB",
            hero_button_distance=1,
            hero_action_index=1,
            active_player_positions=("BB", "BTN/SB"),
            relative_position="not_applicable",
        ),
    )

    result = route_request(components=components)

    assert result.decision_street == "preflop"


def repeated_raise_request(
    *,
    bb_raise_total: Decimal,
    bb_all_in: bool,
    btn_reraise_total: Decimal,
) -> RemoteReferenceRouteRequest:
    request = route_request()
    components = list(request.components)
    components[2] = PriorActionsRoute(
        actions=(
            RemotePriorAction(
                street="preflop",
                sequence=0,
                actor_position="UTG",
                action="fold",
                all_in=False,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=1,
                actor_position="HJ",
                action="fold",
                all_in=False,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=2,
                actor_position="CO",
                action="fold",
                all_in=False,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=3,
                actor_position="BTN",
                action="raise",
                total_committed_bb=Decimal("2.5"),
                all_in=False,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=4,
                actor_position="SB",
                action="call",
                total_committed_bb=Decimal("2.5"),
                all_in=False,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=5,
                actor_position="BB",
                action="raise",
                total_committed_bb=bb_raise_total,
                all_in=bb_all_in,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=6,
                actor_position="BTN",
                action="raise",
                total_committed_bb=btn_reraise_total,
                all_in=False,
            ),
        )
    )
    components[3] = StackWagerPotRoute(
        hero_stack_bb=Decimal("97.5"),
        active_player_stacks=(
            PositionedStack(
                position="BB",
                remaining_stack_bb=(
                    Decimal("0") if bb_all_in else Decimal("100") - bb_raise_total
                ),
            ),
            PositionedStack(
                position="BTN",
                remaining_stack_bb=Decimal("100") - btn_reraise_total,
            ),
            PositionedStack(position="SB", remaining_stack_bb=Decimal("97.5")),
        ),
        committed_pot_before_street_bb=Decimal("0"),
        current_street_commitments=(
            PositionedCommitment(position="BB", committed_bb=bb_raise_total),
            PositionedCommitment(position="BTN", committed_bb=btn_reraise_total),
            PositionedCommitment(position="CO", committed_bb=Decimal("0")),
            PositionedCommitment(position="HJ", committed_bb=Decimal("0")),
            PositionedCommitment(position="SB", committed_bb=Decimal("2.5")),
            PositionedCommitment(position="UTG", committed_bb=Decimal("0")),
        ),
        pot_bb=bb_raise_total + btn_reraise_total + Decimal("2.5"),
        current_wager_bb=btn_reraise_total,
        amount_to_call_bb=btn_reraise_total - Decimal("2.5"),
    )
    components[4] = TablePositionRoute(
        dealt_in_player_count=6,
        hero_position="SB",
        hero_button_distance=1,
        hero_action_index=4,
        active_player_positions=("BB", "BTN", "SB"),
        relative_position="not_applicable",
    )
    return route_request(components=tuple(components))


def test_short_all_in_does_not_reopen_a_prior_actors_raise() -> None:
    with pytest.raises(ValidationError, match="did not reopen"):
        repeated_raise_request(
            bb_raise_total=Decimal("3"),
            bb_all_in=True,
            btn_reraise_total=Decimal("4.5"),
        )


@pytest.mark.parametrize("bb_all_in", [False, True])
def test_full_raise_reopens_a_prior_actors_raise(bb_all_in: bool) -> None:
    request = repeated_raise_request(
        bb_raise_total=Decimal("4"),
        bb_all_in=bb_all_in,
        btn_reraise_total=Decimal("5.5"),
    )

    assert request.decision_street == "preflop"


def test_cumulative_short_all_ins_reopen_a_prior_actors_raise() -> None:
    request = route_request()
    components = list(request.components)
    components[2] = PriorActionsRoute(
        actions=(
            RemotePriorAction(
                street="preflop",
                sequence=0,
                actor_position="UTG",
                action="call",
                total_committed_bb=Decimal("1"),
                all_in=False,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=1,
                actor_position="HJ",
                action="fold",
                all_in=False,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=2,
                actor_position="CO",
                action="fold",
                all_in=False,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=3,
                actor_position="BTN",
                action="raise",
                total_committed_bb=Decimal("3"),
                all_in=False,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=4,
                actor_position="SB",
                action="call",
                total_committed_bb=Decimal("3"),
                all_in=False,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=5,
                actor_position="BB",
                action="raise",
                total_committed_bb=Decimal("4"),
                all_in=True,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=6,
                actor_position="UTG",
                action="raise",
                total_committed_bb=Decimal("5"),
                all_in=True,
            ),
            RemotePriorAction(
                street="preflop",
                sequence=7,
                actor_position="BTN",
                action="raise",
                total_committed_bb=Decimal("7"),
                all_in=False,
            ),
        )
    )
    components[3] = StackWagerPotRoute(
        hero_stack_bb=Decimal("97"),
        active_player_stacks=(
            PositionedStack(position="BB", remaining_stack_bb=Decimal("0")),
            PositionedStack(position="BTN", remaining_stack_bb=Decimal("93")),
            PositionedStack(position="SB", remaining_stack_bb=Decimal("97")),
            PositionedStack(position="UTG", remaining_stack_bb=Decimal("0")),
        ),
        committed_pot_before_street_bb=Decimal("0"),
        current_street_commitments=(
            PositionedCommitment(position="BB", committed_bb=Decimal("4")),
            PositionedCommitment(position="BTN", committed_bb=Decimal("7")),
            PositionedCommitment(position="CO", committed_bb=Decimal("0")),
            PositionedCommitment(position="HJ", committed_bb=Decimal("0")),
            PositionedCommitment(position="SB", committed_bb=Decimal("3")),
            PositionedCommitment(position="UTG", committed_bb=Decimal("5")),
        ),
        pot_bb=Decimal("19"),
        current_wager_bb=Decimal("7"),
        amount_to_call_bb=Decimal("4"),
    )
    components[4] = TablePositionRoute(
        dealt_in_player_count=6,
        hero_position="SB",
        hero_button_distance=1,
        hero_action_index=4,
        active_player_positions=("BB", "BTN", "SB", "UTG"),
        relative_position="not_applicable",
    )

    result = route_request(components=tuple(components))

    assert result.decision_street == "preflop"


def test_completed_betting_round_cannot_fabricate_another_decision() -> None:
    request = route_request()
    components = list(request.components)
    prior_actions = components[2]
    assert isinstance(prior_actions, PriorActionsRoute)
    components[2] = PriorActionsRoute(
        actions=(
            *prior_actions.actions,
            RemotePriorAction(
                street="preflop",
                sequence=5,
                actor_position="BB",
                action="call",
                total_committed_bb=Decimal("2.5"),
                all_in=False,
            ),
        )
    )
    components[3] = StackWagerPotRoute(
        hero_stack_bb=Decimal("97.5"),
        active_player_stacks=(
            PositionedStack(position="BB", remaining_stack_bb=Decimal("97.5")),
            PositionedStack(position="BTN", remaining_stack_bb=Decimal("97.5")),
        ),
        committed_pot_before_street_bb=Decimal("0"),
        current_street_commitments=(
            PositionedCommitment(position="BB", committed_bb=Decimal("2.5")),
            PositionedCommitment(position="BTN", committed_bb=Decimal("2.5")),
            PositionedCommitment(position="CO", committed_bb=Decimal("0")),
            PositionedCommitment(position="HJ", committed_bb=Decimal("0")),
            PositionedCommitment(position="SB", committed_bb=Decimal("0.5")),
            PositionedCommitment(position="UTG", committed_bb=Decimal("0")),
        ),
        pot_bb=Decimal("5.5"),
        current_wager_bb=Decimal("2.5"),
        amount_to_call_bb=Decimal("0"),
    )
    components[4] = TablePositionRoute(
        dealt_in_player_count=6,
        hero_position="BTN",
        hero_button_distance=0,
        hero_action_index=3,
        active_player_positions=("BB", "BTN"),
        relative_position="not_applicable",
    )

    with pytest.raises(ValidationError, match="betting round closed"):
        route_request(components=tuple(components))


def test_preflop_action_line_is_complete_and_structurally_ordered() -> None:
    request = route_request()
    prior_actions = request.components[2]
    assert isinstance(prior_actions, PriorActionsRoute)
    actions = list(prior_actions.actions)
    actions[0] = RemotePriorAction(
        street="preflop",
        sequence=0,
        actor_position="HJ",
        action="fold",
        all_in=False,
    )
    actions[1] = RemotePriorAction(
        street="preflop",
        sequence=1,
        actor_position="UTG",
        action="fold",
        all_in=False,
    )
    components = list(request.components)
    components[2] = PriorActionsRoute(actions=tuple(actions))

    with pytest.raises(ValidationError, match="complete and in structural order"):
        route_request(components=tuple(components))


@pytest.mark.parametrize("starting_hand_class", ["bob", "KAs", "AAs"])
def test_hole_abstraction_is_a_closed_poker_class(
    starting_hand_class: str,
) -> None:
    with pytest.raises(ValidationError):
        HoleCardAbstractionRoute(
            abstraction_schema_revision="class-v1",
            abstraction_schema_sha256=DIGEST_C,
            starting_hand_class=starting_hand_class,
        )


@pytest.mark.parametrize(
    "categories",
    [
        ("board_abstraction", "board_cards"),
        ("hole_card_abstraction", "hole_cards"),
        ("table_position", "game_economics"),
        ("game_economics", "game_economics"),
    ],
)
def test_disclosure_rejects_ambiguous_or_noncanonical_categories(
    categories: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError):
        disclosure(outbound_categories=categories)


def test_remote_failures_remain_ungraded_without_fallback() -> None:
    candidate = preflight()
    failure = record_remote_reference_unavailable(
        candidate,
        reason="network_failure",
        occurred_at=NOW + timedelta(seconds=1),
    )

    assert failure.remote_coverage == "unavailable"
    assert failure.policy_grade_eligibility == "ungraded"
    assert failure.fallback_behavior == "forbidden"
    assert failure.resolved_reference is None
    assert failure.request_sha256 == candidate.request_sha256
    assert failure.decision_state_sha256 == candidate.decision_state_sha256
    assert failure.provider_policy_sha256 == candidate.provider_policy_sha256
    assert failure.route_manifest_sha256 == candidate.route_manifest_sha256
    assert failure.commercial_serving_rights_revision == (
        candidate.commercial_serving_rights_revision
    )


def test_response_failures_require_only_a_local_response_digest() -> None:
    candidate = preflight()
    response_failure = record_remote_reference_unavailable(
        candidate,
        reason="response_invalid",
        occurred_at=NOW + timedelta(seconds=1),
        response_body=b"invalid-response",
    )

    assert response_failure.response_sha256 == sha256(b"invalid-response").hexdigest()
    with pytest.raises(ValidationError):
        record_remote_reference_unavailable(
            candidate,
            reason="response_invalid",
            occurred_at=NOW + timedelta(seconds=1),
        )
    with pytest.raises(ValidationError):
        record_remote_reference_unavailable(
            candidate,
            reason="network_failure",
            occurred_at=NOW + timedelta(seconds=1),
            response_body=b"must-not-exist",
        )


def test_only_a_current_dispatch_candidate_can_record_failure() -> None:
    unavailable = evaluate_remote_reference_preflight(
        decision_point(),
        mode="local_only",
        policy=None,
        consent=None,
        route=None,
        now=NOW,
    )
    with pytest.raises(ValueError, match="only a dispatch candidate"):
        record_remote_reference_unavailable(
            unavailable,
            reason="network_failure",
            occurred_at=NOW,
        )
    with pytest.raises(ValueError, match="cannot predate"):
        record_remote_reference_unavailable(
            preflight(),
            reason="network_failure",
            occurred_at=NOW - timedelta(seconds=1),
        )
