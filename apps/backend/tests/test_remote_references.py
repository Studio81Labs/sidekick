from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import ValidationError

from app.domain.imported_hands import extract_hero_decision_points
from app.domain.learning_content import DecisionBinding
from app.domain.remote_references import (
    BoardCardsRoute,
    ConditionedRange,
    ConditionedRangesRoute,
    GameEconomicsRoute,
    HoleCardAbstractionRoute,
    HoleCardsRoute,
    PriorActionsRoute,
    RemotePriorAction,
    RemoteReferenceConsent,
    RemoteReferenceDisclosure,
    RemoteReferenceProviderPolicy,
    RemoteReferenceRouteRequest,
    StackWagerPotRoute,
    TablePositionRoute,
    evaluate_remote_reference_preflight,
    record_remote_reference_unavailable,
)
from test_imported_hand_decisions import baseline_decision_record


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


def decision_binding() -> DecisionBinding:
    extraction = extract_hero_decision_points(baseline_decision_record())
    assert extraction.outcome == "decisions"
    return DecisionBinding.from_decision(extraction.decision_points[0])


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
    components = (
        GameEconomicsRoute(
            game_variant="texas_holdem",
            betting_limit="no_limit",
            game_format="cash",
            economic_model="cash_rake",
            economic_model_revision="cash-ev-v1",
            economic_configuration_sha256=DIGEST_A,
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
                    actor_position="BTN",
                    action="raise",
                    total_committed_bb=Decimal("2.5"),
                    all_in=False,
                ),
            ),
        ),
        StackWagerPotRoute(
            effective_stack_bb=Decimal("99"),
            hero_stack_bb=Decimal("99"),
            pot_bb=Decimal("2.5"),
            current_wager_bb=Decimal("1"),
            amount_to_call_bb=Decimal("1"),
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


def preflight(
    *,
    mode: object = "remote_enabled",
    policy: RemoteReferenceProviderPolicy | None = None,
    accepted: RemoteReferenceConsent | None = None,
    request: RemoteReferenceRouteRequest | None = None,
):
    selected = policy or provider_policy()
    selected_consent = accepted if accepted is not None else consent(policy=selected)
    selected_request = request if request is not None else route_request()
    return evaluate_remote_reference_preflight(
        decision_binding(),
        mode=mode,  # type: ignore[arg-type]
        policy=selected,
        consent=selected_consent,
        request=selected_request,
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
        decision_binding(),
        mode=overrides.get("mode", "remote_enabled"),  # type: ignore[arg-type]
        policy=overrides.get("policy", provider_policy()),  # type: ignore[arg-type]
        consent=None,
        request=None,
        now=NOW,
    )

    assert result.outcome == "unavailable"
    assert result.reason == expected_reason
    assert result.outbound_request is None
    assert result.resolved_reference is None
    assert result.policy_grade_eligibility == "ungraded"


def test_exact_active_consent_yields_only_a_dispatch_candidate() -> None:
    result = preflight()

    assert result.outcome == "dispatch_candidate"
    assert result.reason == "preflight_passed"
    assert result.fresh_consent_recheck == (
        "required_immediately_before_dispatch"
    )
    assert result.policy_grade_eligibility == "ungraded"
    assert result.resolved_reference is None
    assert result.outbound_request == route_request()
    assert result.request_sha256 == route_request().semantic_digest()
    assert result.provider_policy_sha256 == provider_policy().semantic_digest()
    assert result.commercial_serving_rights_revision == "commercial-rights-v1"
    assert result.derived_output_rights_revision == "derived-rights-v1"


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
        decision_binding(),
        mode="remote_enabled",
        policy=policy,
        consent=accepted,
        request=route_request(),
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
        decision_binding(),
        mode="remote_enabled",
        policy=provider_policy(),
        consent=revoked,
        request=route_request(),
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
        decision_binding(),
        mode="remote_enabled",
        policy=changed,
        consent=consent(policy=original),
        request=route_request(),
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
        decision_binding(),
        mode="remote_enabled",
        policy=changed,
        consent=consent(policy=original),
        request=route_request(),
        now=NOW,
    )

    assert result.reason == "disclosure_mismatch"
    assert result.outbound_request is None


def test_categories_and_route_schema_are_exactly_bound() -> None:
    policy = provider_policy()
    category_mismatch = evaluate_remote_reference_preflight(
        decision_binding(),
        mode="remote_enabled",
        policy=policy,
        consent=consent(
            policy=policy,
            accepted_outbound_categories=("game_economics",),
        ),
        request=route_request(),
        now=NOW,
    )
    schema_mismatch = evaluate_remote_reference_preflight(
        decision_binding(),
        mode="remote_enabled",
        policy=policy,
        consent=consent(policy=policy),
        request=route_request(route_schema_revision="route-v2"),
        now=NOW,
    )
    request_missing = evaluate_remote_reference_preflight(
        decision_binding(),
        mode="remote_enabled",
        policy=policy,
        consent=consent(policy=policy),
        request=None,
        now=NOW,
    )
    raw_components = list(route_request().components)
    raw_components[1] = HoleCardsRoute(cards=("As", "Kd"))
    request_category_mismatch = evaluate_remote_reference_preflight(
        decision_binding(),
        mode="remote_enabled",
        policy=policy,
        consent=consent(policy=policy),
        request=route_request(components=tuple(raw_components)),
        now=NOW,
    )

    assert category_mismatch.reason == "outbound_categories_mismatch"
    assert schema_mismatch.reason == "route_schema_mismatch"
    assert request_missing.reason == "route_unavailable"
    assert request_category_mismatch.reason == "outbound_categories_mismatch"
    assert category_mismatch.outbound_request is None
    assert schema_mismatch.outbound_request is None


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
        effective_stack_bb=Decimal("98"),
        hero_stack_bb=Decimal("98"),
        pot_bb=Decimal("2.5"),
        current_wager_bb=Decimal("1"),
        amount_to_call_bb=Decimal("1"),
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
        {"small_blind_bb": Decimal("1")},
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
    assert failure.provider_policy_sha256 == candidate.provider_policy_sha256
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
        decision_binding(),
        mode="local_only",
        policy=None,
        consent=None,
        request=None,
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
