"""Player-facing consent lifecycle for optional remote solved references."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.domain.remote_references import (
    RemoteOutboundCategory,
    RemoteReferenceConsent,
    RemoteReferenceDisclosure,
    RemoteReferenceProviderPolicy,
    evaluate_remote_reference_consent,
)
ConsentGeneration = Annotated[int, Field(ge=0, strict=True)]
PlayerRemoteReferenceConsentReason = Literal[
    "clock_invalid",
    "provider_unconfigured",
    "provider_inactive",
    "consent_absent",
    "consent_revoked",
    "consent_not_yet_active",
    "consent_expired",
    "provider_policy_mismatch",
    "disclosure_mismatch",
    "outbound_categories_mismatch",
    "consent_active",
]


class PlayerRemoteReferenceConsentConflict(RuntimeError):
    """The request no longer describes the authoritative consent state."""


class PlayerRemoteReferenceProviderOffer(BaseModel):
    """The non-secret policy details a player must see before consenting."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider_id: str
    provider_configuration_revision: str
    provider_policy_revision: str
    provider_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    endpoint_origin: str
    reference_source_revision: str
    commercial_serving_rights_revision: str
    derived_output_rights_revision: str
    disclosure: RemoteReferenceDisclosure


class PlayerRemoteReferenceConsentSnapshot(BaseModel):
    """A minimized projection of the current install-local consent snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    consent_generation: int = Field(gt=0)
    provider_id: str
    provider_configuration_revision: str
    provider_policy_revision: str
    disclosure_revision: str
    accepted_outbound_categories: tuple[RemoteOutboundCategory, ...]
    status: Literal["active", "revoked"]
    consented_at: AwareDatetime
    expires_at: AwareDatetime | None
    revoked_at: AwareDatetime | None


class PlayerRemoteReferenceConsentStatus(BaseModel):
    """Current consent state without credentials or outbound route data."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_name: Literal["player-remote-reference-consent-status/v1"] = Field(
        default="player-remote-reference-consent-status/v1",
        alias="schema",
    )
    state: Literal["local_only", "consent_required", "consent_active"]
    reason: PlayerRemoteReferenceConsentReason
    consent_generation: ConsentGeneration
    provider: PlayerRemoteReferenceProviderOffer | None
    consent: PlayerRemoteReferenceConsentSnapshot | None


class PlayerRemoteReferenceConsentRequest(BaseModel):
    """Affirmations bound to the exact disclosure shown by the local API."""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_consent_generation: ConsentGeneration
    expected_provider_policy_revision: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]*$",
    )
    expected_provider_policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_disclosure_revision: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]*$",
    )
    disclosure_accepted: Literal[True]
    network_dependency_accepted: Literal[True]
    retention_and_use_accepted: Literal[True]


class PlayerRemoteReferenceRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_consent_generation: ConsentGeneration


def project_player_remote_reference_consent_status(
    *,
    policy: RemoteReferenceProviderPolicy | None,
    consent: RemoteReferenceConsent | None,
    at: datetime,
) -> PlayerRemoteReferenceConsentStatus:
    """Project authoritative policy and consent snapshots for the local player."""

    evaluated_reason = evaluate_remote_reference_consent(
        policy=policy,
        consent=consent,
        now=at,
    )
    if evaluated_reason == "preflight_passed":
        state = "consent_active"
    elif policy is not None and policy.provider_status == "active":
        state = "consent_required"
    else:
        state = "local_only"
    reason: PlayerRemoteReferenceConsentReason = (
        "consent_active"
        if evaluated_reason == "preflight_passed"
        else evaluated_reason
    )
    offer = None
    if policy is not None and policy.provider_status == "active":
        offer = PlayerRemoteReferenceProviderOffer(
            provider_id=policy.provider_id,
            provider_configuration_revision=policy.provider_configuration_revision,
            provider_policy_revision=policy.provider_policy_revision,
            provider_policy_sha256=policy.semantic_digest(),
            endpoint_origin=policy.endpoint_origin,
            reference_source_revision=policy.reference_source_revision,
            commercial_serving_rights_revision=(
                policy.commercial_serving_rights_revision
            ),
            derived_output_rights_revision=policy.derived_output_rights_revision,
            disclosure=policy.disclosure,
        )
    snapshot = None
    if consent is not None:
        snapshot = PlayerRemoteReferenceConsentSnapshot(
            consent_generation=consent.consent_generation,
            provider_id=consent.provider_id,
            provider_configuration_revision=(
                consent.provider_configuration_revision
            ),
            provider_policy_revision=consent.provider_policy_revision,
            disclosure_revision=consent.disclosure_revision,
            accepted_outbound_categories=consent.accepted_outbound_categories,
            status=consent.status,
            consented_at=consent.consented_at,
            expires_at=consent.expires_at,
            revoked_at=consent.revoked_at,
        )
    return PlayerRemoteReferenceConsentStatus(
        state=state,
        reason=reason,
        consent_generation=(consent.consent_generation if consent is not None else 0),
        provider=offer,
        consent=snapshot,
    )


def accept_player_remote_reference_consent(
    *,
    policy: RemoteReferenceProviderPolicy | None,
    current: RemoteReferenceConsent | None,
    request: PlayerRemoteReferenceConsentRequest,
    at: datetime,
) -> RemoteReferenceConsent:
    """Create a server-derived consent snapshot after an exact CAS check."""

    if at.tzinfo is None or at.utcoffset() is None:
        raise PlayerRemoteReferenceConsentConflict(
            "Remote-reference consent requires a valid clock"
        )
    if policy is None or policy.provider_status != "active":
        raise PlayerRemoteReferenceConsentConflict(
            "No active remote-reference provider policy is available"
        )
    current_generation = current.consent_generation if current is not None else 0
    if request.expected_consent_generation != current_generation:
        raise PlayerRemoteReferenceConsentConflict(
            "Remote-reference consent changed; refresh before accepting"
        )
    if (
        request.expected_provider_policy_revision != policy.provider_policy_revision
        or request.expected_provider_policy_sha256 != policy.semantic_digest()
        or request.expected_disclosure_revision
        != policy.disclosure.disclosure_revision
    ):
        raise PlayerRemoteReferenceConsentConflict(
            "The remote-reference provider policy or disclosure changed; "
            "review it again"
        )
    if (
        current is not None
        and evaluate_remote_reference_consent(
            policy=policy,
            consent=current,
            now=at,
        )
        == "preflight_passed"
    ):
        raise PlayerRemoteReferenceConsentConflict(
            "Remote-reference consent is already active"
        )
    consented_at = at
    if current is not None:
        previous_at = current.revoked_at or current.consented_at
        if consented_at <= previous_at:
            try:
                consented_at = previous_at + timedelta(microseconds=1)
            except OverflowError as exc:
                raise PlayerRemoteReferenceConsentConflict(
                    "Remote-reference consent timestamp cannot advance"
                ) from exc
    disclosure = policy.disclosure
    return RemoteReferenceConsent(
        consent_id=f"consent-{uuid4().hex}",
        consent_generation=current_generation + 1,
        provider_id=policy.provider_id,
        provider_configuration_revision=policy.provider_configuration_revision,
        provider_policy_revision=policy.provider_policy_revision,
        provider_policy_sha256=policy.semantic_digest(),
        endpoint_origin=policy.endpoint_origin,
        disclosure_revision=disclosure.disclosure_revision,
        disclosure_sha256=disclosure.semantic_digest(),
        accepted_outbound_categories=disclosure.outbound_categories,
        network_dependency_accepted=True,
        retention_and_use_accepted=True,
        status="active",
        consented_at=consented_at,
    )


def revoke_player_remote_reference_consent(
    *,
    current: RemoteReferenceConsent | None,
    request: PlayerRemoteReferenceRevokeRequest,
    at: datetime,
) -> RemoteReferenceConsent:
    """Revoke the current generation; retries remain idempotent."""

    if at.tzinfo is None or at.utcoffset() is None:
        raise PlayerRemoteReferenceConsentConflict(
            "Remote-reference revocation requires a valid clock"
        )
    if current is None:
        raise PlayerRemoteReferenceConsentConflict(
            "No remote-reference consent exists to revoke"
        )
    if request.expected_consent_generation != current.consent_generation:
        raise PlayerRemoteReferenceConsentConflict(
            "Remote-reference consent changed; refresh before revoking"
        )
    if current.status == "revoked":
        return current
    revoked_at = max(at, current.consented_at)
    return current.model_copy(
        update={"status": "revoked", "revoked_at": revoked_at}
    )
