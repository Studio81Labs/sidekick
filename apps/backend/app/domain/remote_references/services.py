"""Pure deny-by-default preflight for optional remote reference lookup."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from app.domain.learning_content.models import DecisionBinding
from app.domain.remote_references.models import (
    AbstractionSchemaBinding,
    EconomicConfigurationBinding,
    GameEconomicsRoute,
    HoleCardAbstractionRoute,
    RemoteDispatchReason,
    RemoteLookupUnavailableReason,
    RemoteReferenceConsent,
    RemoteReferenceDispatchPreflight,
    RemoteReferenceLookupUnavailable,
    RemoteReferenceMode,
    RemoteReferenceProviderPolicy,
    RemoteReferenceRouteDerivation,
    RemoteReferenceRouteRequest,
    UtilityConfigurationBinding,
)


def evaluate_remote_reference_preflight(
    decision: DecisionBinding,
    *,
    mode: RemoteReferenceMode,
    policy: RemoteReferenceProviderPolicy | None,
    consent: RemoteReferenceConsent | None,
    route: RemoteReferenceRouteDerivation | None,
    now: datetime,
) -> RemoteReferenceDispatchPreflight:
    """Evaluate snapshots into a candidate, never final transport authority."""

    decision = DecisionBinding.model_validate(decision.model_dump(mode="python"))
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
    if route.decision != decision:
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
