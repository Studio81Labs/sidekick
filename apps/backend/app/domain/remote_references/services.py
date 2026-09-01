"""Pure deny-by-default preflight for optional remote reference lookup."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from app.domain.imported_hands.decisions import HeroDecisionPoint
from app.domain.imported_hands.models import CashEconomics
from app.domain.learning_content.models import DecisionBinding
from app.domain.remote_references.models import (
    AbstractionSchemaBinding,
    EconomicConfigurationBinding,
    GameEconomicsRoute,
    HoleCardAbstractionRoute,
    HoleCardsRoute,
    PositionedCommitment,
    PositionedStack,
    PriorActionsRoute,
    RemoteDispatchReason,
    RemoteLookupUnavailableReason,
    RemotePriorAction,
    RemoteReferenceConsent,
    RemoteReferenceDispatchPreflight,
    RemoteReferenceLookupUnavailable,
    RemoteReferenceMode,
    RemoteReferenceProviderPolicy,
    RemoteReferenceRouteDerivation,
    RemoteReferenceRouteRequest,
    StackWagerPotRoute,
    TablePositionRoute,
    UtilityConfigurationBinding,
)


_CASH_ECONOMIC_CONFIGURATION_REVISION = "canonical-cash-economics-v1"
_CASH_ECONOMIC_CONFIGURATION_SCHEMA = (
    "sidekick.remote_reference.cash_economics.v1"
)


def derive_cash_economic_configuration(
    decision: HeroDecisionPoint,
) -> EconomicConfigurationBinding | None:
    """Bind provider cash coverage to the approved absolute economics."""

    decision = HeroDecisionPoint.model_validate(decision.model_dump(mode="python"))
    state = decision.state
    economics = state.economics
    if (
        state.variant != "texas_holdem"
        or state.betting_limit != "no_limit"
        or not isinstance(economics, CashEconomics)
        or economics.currency is None
        or economics.rake is None
        or economics.rake.percentage is None
        or economics.rake.cap is None
        or economics.rake.fixed_drop is None
        or state.blinds.small_blind is None
        or state.blinds.big_blind is None
        or state.blinds.ante is None
    ):
        return None

    payload = {
        "schema": _CASH_ECONOMIC_CONFIGURATION_SCHEMA,
        "game_variant": state.variant,
        "betting_limit": state.betting_limit,
        "economics": {
            "kind": economics.kind,
            "currency": economics.currency,
            "rake": {
                "percentage": _canonical_decimal(economics.rake.percentage),
                "cap": _canonical_decimal(economics.rake.cap),
                "fixed_drop": _canonical_decimal(economics.rake.fixed_drop),
                "description": economics.rake.description,
            },
        },
        "blinds": {
            "small_blind": _canonical_decimal(state.blinds.small_blind),
            "big_blind": _canonical_decimal(state.blinds.big_blind),
            "ante": _canonical_decimal(state.blinds.ante),
            "ante_mode": (
                "none" if state.blinds.ante == 0 else state.blinds.ante_mode
            ),
            "straddle": (
                None
                if state.blinds.straddle is None
                else _canonical_decimal(state.blinds.straddle)
            ),
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return EconomicConfigurationBinding(
        economic_model="cash_rake",
        economic_model_revision=_CASH_ECONOMIC_CONFIGURATION_REVISION,
        economic_configuration_sha256=sha256(encoded).hexdigest(),
    )


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def evaluate_remote_reference_preflight(
    decision: HeroDecisionPoint,
    *,
    mode: RemoteReferenceMode,
    policy: RemoteReferenceProviderPolicy | None,
    consent: RemoteReferenceConsent | None,
    route: RemoteReferenceRouteDerivation | None,
    now: datetime,
) -> RemoteReferenceDispatchPreflight:
    """Evaluate snapshots into a candidate, never final transport authority."""

    decision_point = HeroDecisionPoint.model_validate(
        decision.model_dump(mode="python")
    )
    decision = DecisionBinding.from_decision(decision_point)
    if not _is_aware(now):
        return _unavailable(decision, now=None, reason="clock_invalid")
    if mode not in {"local_only", "remote_enabled"}:
        return _unavailable(decision, now=now, reason="mode_invalid")
    if mode == "local_only":
        return _unavailable(decision, now=now, reason="local_only")
    if policy is None:
        return _unavailable(decision, now=now, reason="provider_unconfigured")
    policy = RemoteReferenceProviderPolicy.model_validate(
        policy.model_dump(mode="python")
    )
    if policy.provider_status != "active":
        return _unavailable(
            decision,
            now=now,
            reason="provider_inactive",
            policy=policy,
        )
    if consent is None:
        return _unavailable(
            decision,
            now=now,
            reason="consent_absent",
            policy=policy,
        )
    consent = RemoteReferenceConsent.model_validate(consent.model_dump(mode="python"))
    if consent.status == "revoked":
        return _unavailable(
            decision,
            now=now,
            reason="consent_revoked",
            policy=policy,
            consent=consent,
        )
    if now < consent.consented_at:
        return _unavailable(
            decision,
            now=now,
            reason="consent_not_yet_active",
            policy=policy,
            consent=consent,
        )
    if consent.expires_at is not None and now >= consent.expires_at:
        return _unavailable(
            decision,
            now=now,
            reason="consent_expired",
            policy=policy,
            consent=consent,
        )

    if (
        consent.provider_id,
        consent.provider_configuration_revision,
        consent.provider_policy_revision,
        consent.endpoint_origin,
    ) != (
        policy.provider_id,
        policy.provider_configuration_revision,
        policy.provider_policy_revision,
        policy.endpoint_origin,
    ):
        return _unavailable(
            decision,
            now=now,
            reason="provider_policy_mismatch",
            policy=policy,
            consent=consent,
        )
    disclosure = policy.disclosure
    disclosure_sha256 = disclosure.semantic_digest()
    if (
        consent.disclosure_revision != disclosure.disclosure_revision
        or consent.disclosure_sha256 != disclosure_sha256
    ):
        return _unavailable(
            decision,
            now=now,
            reason="disclosure_mismatch",
            policy=policy,
            consent=consent,
        )
    if consent.accepted_outbound_categories != disclosure.outbound_categories:
        return _unavailable(
            decision,
            now=now,
            reason="outbound_categories_mismatch",
            policy=policy,
            consent=consent,
        )
    if consent.provider_policy_sha256 != policy.semantic_digest():
        return _unavailable(
            decision,
            now=now,
            reason="provider_policy_mismatch",
            policy=policy,
            consent=consent,
        )
    if route is None:
        return _unavailable(
            decision,
            now=now,
            reason="route_unavailable",
            policy=policy,
            consent=consent,
        )
    route = RemoteReferenceRouteDerivation.model_validate(
        route.model_dump(mode="python")
    )
    request = route.outbound_request
    if (
        route.decision != decision
        or route.decision_state_sha256
        != _decision_state_sha256(decision_point)
        or _derive_request_from_decision(decision_point, request) != request
    ):
        return _unavailable(
            decision,
            now=now,
            reason="route_binding_mismatch",
            policy=policy,
            consent=consent,
            request=request,
        )
    request = RemoteReferenceRouteRequest.model_validate(
        request.model_dump(mode="python")
    )
    if (
        request.route_schema_revision != disclosure.route_schema_revision
        or request.route_schema_sha256 != disclosure.route_schema_sha256
    ):
        return _unavailable(
            decision,
            now=now,
            reason="route_schema_mismatch",
            policy=policy,
            consent=consent,
            request=request,
        )
    if request.outbound_categories != disclosure.outbound_categories:
        return _unavailable(
            decision,
            now=now,
            reason="outbound_categories_mismatch",
            policy=policy,
            consent=consent,
            request=request,
        )
    if not _request_matches_manifest(request, policy):
        return _unavailable(
            decision,
            now=now,
            reason="route_manifest_mismatch",
            policy=policy,
            consent=consent,
            request=request,
        )

    return RemoteReferenceDispatchPreflight(
        decision=decision,
        evaluated_at=now,
        outcome="dispatch_candidate",
        reason="preflight_passed",
        provider_id=policy.provider_id,
        provider_configuration_revision=policy.provider_configuration_revision,
        provider_policy_revision=policy.provider_policy_revision,
        provider_policy_sha256=policy.semantic_digest(),
        route_manifest_revision=policy.route_manifest.manifest_revision,
        route_manifest_sha256=policy.route_manifest.semantic_digest(),
        endpoint_origin=policy.endpoint_origin,
        reference_source_revision=policy.reference_source_revision,
        commercial_serving_rights_revision=(
            policy.commercial_serving_rights_revision
        ),
        commercial_serving_rights_sha256=(
            policy.commercial_serving_rights_sha256
        ),
        derived_output_rights_revision=policy.derived_output_rights_revision,
        derived_output_rights_sha256=policy.derived_output_rights_sha256,
        disclosure_sha256=disclosure_sha256,
        consent_id=consent.consent_id,
        consent_generation=consent.consent_generation,
        request_sha256=request.semantic_digest(),
        outbound_request=request,
        fresh_consent_recheck="required_immediately_before_dispatch",
    )


def bind_remote_reference_route(
    decision: HeroDecisionPoint,
    request: RemoteReferenceRouteRequest,
) -> RemoteReferenceRouteDerivation:
    """Bind a closed request only when canonical decision state derives it."""

    decision = HeroDecisionPoint.model_validate(decision.model_dump(mode="python"))
    request = RemoteReferenceRouteRequest.model_validate(
        request.model_dump(mode="python")
    )
    if _derive_request_from_decision(decision, request) != request:
        raise ValueError("remote route does not match canonical decision state")
    return RemoteReferenceRouteDerivation(
        decision=DecisionBinding.from_decision(decision),
        decision_state_sha256=_decision_state_sha256(decision),
        outbound_request=request,
    )


def _decision_state_sha256(decision: HeroDecisionPoint) -> str:
    payload = json.dumps(
        decision.state.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _derive_request_from_decision(
    decision: HeroDecisionPoint,
    template: RemoteReferenceRouteRequest,
) -> RemoteReferenceRouteRequest | None:
    """Reconstruct every route-state field from one canonical decision point."""

    state = decision.state
    if (
        decision.street != "preflop"
        or state.street != "preflop"
        or state.variant != "texas_holdem"
        or state.betting_limit != "no_limit"
        or state.economics.kind != "cash"
        or state.blinds.small_blind is None
        or state.blinds.big_blind is None
        or state.blinds.ante is None
        or state.blinds.ante != 0
        or state.blinds.straddle is not None
    ):
        return None
    expected_categories = {
        "game_economics",
        "prior_actions",
        "stack_wager_pot",
        "table_position",
    }
    categories = set(template.outbound_categories)
    if not expected_categories <= categories or categories - expected_categories not in (
        {"hole_cards"},
        {"hole_card_abstraction"},
    ):
        return None

    big_blind = state.blinds.big_blind
    assert big_blind is not None

    def bb(value: Decimal) -> Decimal:
        return value / big_blind

    economics_template = next(
        component
        for component in template.components
        if isinstance(component, GameEconomicsRoute)
    )
    economic_configuration = derive_cash_economic_configuration(decision)
    if economic_configuration is None:
        return None
    hole_template = next(
        component
        for component in template.components
        if isinstance(component, (HoleCardsRoute, HoleCardAbstractionRoute))
    )
    if isinstance(hole_template, HoleCardsRoute):
        hole_component: HoleCardsRoute | HoleCardAbstractionRoute = HoleCardsRoute(
            cards=tuple(card.code for card in decision.state.hero_cards)
        )
    else:
        hole_component = HoleCardAbstractionRoute(
            abstraction_schema_revision=(
                hole_template.abstraction_schema_revision
            ),
            abstraction_schema_sha256=hole_template.abstraction_schema_sha256,
            starting_hand_class=_starting_hand_class(decision),
        )

    remote_actions: list[RemotePriorAction] = []
    for history in state.action_history:
        remote_sequence = 0
        for action in history.actions:
            if action.action_type in {
                "post_ante",
                "post_small_blind",
                "post_big_blind",
            }:
                continue
            if action.action_type not in {"fold", "check", "call", "bet", "raise"}:
                return None
            if action.action_type in {"call", "bet", "raise"}:
                if action.total_committed is None:
                    return None
                total_committed = bb(action.total_committed)
            else:
                total_committed = None
            remote_actions.append(
                RemotePriorAction(
                    street=history.street,
                    sequence=remote_sequence,
                    actor_position=action.position.display_label,
                    action=action.action_type,
                    total_committed_bb=total_committed,
                    all_in=action.all_in,
                )
            )
            remote_sequence += 1

    active_seats = [seat for seat in state.seats if seat.status != "folded"]
    prior_pot = state.pot_before_action - sum(
        (seat.live_commitment for seat in state.seats),
        start=Decimal(0),
    )
    try:
        return RemoteReferenceRouteRequest(
            route_schema_revision=template.route_schema_revision,
            route_schema_sha256=template.route_schema_sha256,
            decision_street="preflop",
            components=(
                GameEconomicsRoute(
                    game_variant="texas_holdem",
                    betting_limit="no_limit",
                    game_format="cash",
                    economic_model=economic_configuration.economic_model,
                    economic_model_revision=(
                        economic_configuration.economic_model_revision
                    ),
                    economic_configuration_sha256=(
                        economic_configuration.economic_configuration_sha256
                    ),
                    utility_model=economics_template.utility_model,
                    utility_model_revision=economics_template.utility_model_revision,
                    utility_configuration_sha256=(
                        economics_template.utility_configuration_sha256
                    ),
                    small_blind_bb=bb(state.blinds.small_blind),
                    big_blind_bb=Decimal(1),
                    ante_bb=Decimal(0),
                    ante_mode="none",
                ),
                hole_component,
                PriorActionsRoute(actions=tuple(remote_actions)),
                StackWagerPotRoute(
                    hero_stack_bb=bb(state.hero_stack_before_action),
                    active_player_stacks=tuple(
                        sorted(
                            (
                                PositionedStack(
                                    position=seat.position.display_label,
                                    remaining_stack_bb=bb(seat.stack_before_action),
                                )
                                for seat in active_seats
                            ),
                            key=lambda item: item.position,
                        )
                    ),
                    committed_pot_before_street_bb=bb(prior_pot),
                    current_street_commitments=tuple(
                        sorted(
                            (
                                PositionedCommitment(
                                    position=seat.position.display_label,
                                    committed_bb=bb(seat.live_commitment),
                                )
                                for seat in state.seats
                            ),
                            key=lambda item: item.position,
                        )
                    ),
                    pot_bb=bb(state.pot_before_action),
                    current_wager_bb=bb(state.current_wager),
                    amount_to_call_bb=bb(state.amount_to_call),
                ),
                TablePositionRoute(
                    dealt_in_player_count=state.dealt_in_player_count,
                    hero_position=state.hero_position.display_label,
                    hero_button_distance=state.hero_position.button_distance,
                    hero_action_index=state.hero_position.action_index,
                    active_player_positions=tuple(
                        sorted(
                            seat.position.display_label for seat in active_seats
                        )
                    ),
                    relative_position="not_applicable",
                ),
            ),
        )
    except ValueError:
        return None


def _starting_hand_class(decision: HeroDecisionPoint) -> str:
    first, second = decision.state.hero_cards
    if first.rank == second.rank:
        return f"{first.rank}{second.rank}"
    rank_order = "23456789TJQKA"
    high, low = sorted(
        (first, second),
        key=lambda card: rank_order.index(card.rank),
        reverse=True,
    )
    suitedness = "s" if high.suit == low.suit else "o"
    return f"{high.rank}{low.rank}{suitedness}"


def record_remote_reference_unavailable(
    preflight: RemoteReferenceDispatchPreflight,
    *,
    reason: RemoteLookupUnavailableReason,
    occurred_at: datetime,
    response_body: bytes | None = None,
) -> RemoteReferenceLookupUnavailable:
    """Record one post-preflight failure without fallback or grade promotion."""

    preflight = RemoteReferenceDispatchPreflight.model_validate(
        preflight.model_dump(mode="python")
    )
    if preflight.outcome != "dispatch_candidate":
        raise ValueError("only a dispatch candidate can record remote unavailability")
    if not _is_aware(occurred_at):
        raise ValueError("remote unavailability requires an aware clock")
    assert preflight.evaluated_at is not None
    if occurred_at < preflight.evaluated_at:
        raise ValueError("remote unavailability cannot predate its preflight")
    assert preflight.provider_id is not None
    assert preflight.provider_configuration_revision is not None
    assert preflight.provider_policy_revision is not None
    assert preflight.provider_policy_sha256 is not None
    assert preflight.route_manifest_revision is not None
    assert preflight.route_manifest_sha256 is not None
    assert preflight.endpoint_origin is not None
    assert preflight.reference_source_revision is not None
    assert preflight.commercial_serving_rights_revision is not None
    assert preflight.commercial_serving_rights_sha256 is not None
    assert preflight.derived_output_rights_revision is not None
    assert preflight.derived_output_rights_sha256 is not None
    assert preflight.disclosure_sha256 is not None
    assert preflight.consent_id is not None
    assert preflight.consent_generation is not None
    assert preflight.request_sha256 is not None
    assert preflight.outbound_request is not None
    return RemoteReferenceLookupUnavailable(
        decision=preflight.decision,
        preflight_evaluated_at=preflight.evaluated_at,
        occurred_at=occurred_at,
        reason=reason,
        provider_id=preflight.provider_id,
        provider_configuration_revision=(
            preflight.provider_configuration_revision
        ),
        provider_policy_revision=preflight.provider_policy_revision,
        provider_policy_sha256=preflight.provider_policy_sha256,
        route_manifest_revision=preflight.route_manifest_revision,
        route_manifest_sha256=preflight.route_manifest_sha256,
        endpoint_origin=preflight.endpoint_origin,
        reference_source_revision=preflight.reference_source_revision,
        commercial_serving_rights_revision=(
            preflight.commercial_serving_rights_revision
        ),
        commercial_serving_rights_sha256=(
            preflight.commercial_serving_rights_sha256
        ),
        derived_output_rights_revision=preflight.derived_output_rights_revision,
        derived_output_rights_sha256=preflight.derived_output_rights_sha256,
        disclosure_sha256=preflight.disclosure_sha256,
        consent_id=preflight.consent_id,
        consent_generation=preflight.consent_generation,
        route_schema_revision=preflight.outbound_request.route_schema_revision,
        route_schema_sha256=preflight.outbound_request.route_schema_sha256,
        request_sha256=preflight.request_sha256,
        response_sha256=(
            sha256(response_body).hexdigest()
            if response_body is not None
            else None
        ),
    )


def _unavailable(
    decision: DecisionBinding,
    *,
    now: datetime | None,
    reason: RemoteDispatchReason,
    policy: RemoteReferenceProviderPolicy | None = None,
    consent: RemoteReferenceConsent | None = None,
    request: RemoteReferenceRouteRequest | None = None,
) -> RemoteReferenceDispatchPreflight:
    disclosure_sha256 = (
        policy.disclosure.semantic_digest() if policy is not None else None
    )
    return RemoteReferenceDispatchPreflight(
        decision=decision,
        evaluated_at=now,
        outcome="unavailable",
        reason=reason,
        provider_id=policy.provider_id if policy is not None else None,
        provider_configuration_revision=(
            policy.provider_configuration_revision if policy is not None else None
        ),
        provider_policy_revision=(
            policy.provider_policy_revision if policy is not None else None
        ),
        provider_policy_sha256=(
            policy.semantic_digest() if policy is not None else None
        ),
        route_manifest_revision=(
            policy.route_manifest.manifest_revision if policy is not None else None
        ),
        route_manifest_sha256=(
            policy.route_manifest.semantic_digest() if policy is not None else None
        ),
        endpoint_origin=policy.endpoint_origin if policy is not None else None,
        reference_source_revision=(
            policy.reference_source_revision if policy is not None else None
        ),
        commercial_serving_rights_revision=(
            policy.commercial_serving_rights_revision
            if policy is not None
            else None
        ),
        commercial_serving_rights_sha256=(
            policy.commercial_serving_rights_sha256
            if policy is not None
            else None
        ),
        derived_output_rights_sha256=(
            policy.derived_output_rights_sha256 if policy is not None else None
        ),
        derived_output_rights_revision=(
            policy.derived_output_rights_revision
            if policy is not None
            else None
        ),
        disclosure_sha256=disclosure_sha256,
        consent_id=consent.consent_id if consent is not None else None,
        consent_generation=(
            consent.consent_generation if consent is not None else None
        ),
        request_sha256=(
            request.semantic_digest() if request is not None else None
        ),
    )


def _is_aware(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _request_matches_manifest(
    request: RemoteReferenceRouteRequest,
    policy: RemoteReferenceProviderPolicy,
) -> bool:
    if request.decision_street != "preflop":
        return False
    manifest = policy.route_manifest
    if request.semantic_digest() not in manifest.eligible_route_context_sha256s:
        return False
    for component in request.components:
        if isinstance(component, GameEconomicsRoute):
            economics = EconomicConfigurationBinding(
                economic_model=component.economic_model,
                economic_model_revision=component.economic_model_revision,
                economic_configuration_sha256=(
                    component.economic_configuration_sha256
                ),
            )
            utility = UtilityConfigurationBinding(
                utility_model=component.utility_model,
                utility_model_revision=component.utility_model_revision,
                utility_configuration_sha256=(
                    component.utility_configuration_sha256
                ),
            )
            if economics not in manifest.economic_configurations:
                return False
            if utility not in manifest.utility_configurations:
                return False
        elif isinstance(component, HoleCardAbstractionRoute):
            schema = AbstractionSchemaBinding(
                abstraction_schema_revision=component.abstraction_schema_revision,
                abstraction_schema_sha256=component.abstraction_schema_sha256,
            )
            if schema not in manifest.hole_card_abstraction_schemas:
                return False
    return True
