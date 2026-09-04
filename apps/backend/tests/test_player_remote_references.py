from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.player_remote_references import (
    PlayerRemoteReferenceConsentConflict,
    PlayerRemoteReferenceConsentRequest,
    PlayerRemoteReferenceRevokeRequest,
    accept_player_remote_reference_consent,
    project_player_remote_reference_consent_status,
    revoke_player_remote_reference_consent,
)
from app.player_workspace import PlayerWorkspace
from test_remote_references import provider_policy


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def consent_request(**updates: object) -> PlayerRemoteReferenceConsentRequest:
    policy = provider_policy()
    values = {
        "expected_consent_generation": 0,
        "expected_provider_policy_revision": "policy-v1",
        "expected_provider_policy_sha256": policy.semantic_digest(),
        "expected_disclosure_revision": "disclosure-v1",
        "disclosure_accepted": True,
        "network_dependency_accepted": True,
        "retention_and_use_accepted": True,
    }
    values.update(updates)
    return PlayerRemoteReferenceConsentRequest.model_validate(values)


def test_consent_is_server_derived_from_the_exact_active_policy() -> None:
    policy = provider_policy()

    accepted = accept_player_remote_reference_consent(
        policy=policy,
        current=None,
        request=consent_request(),
        at=NOW,
    )

    assert accepted.consent_id.startswith("consent-")
    assert accepted.consent_generation == 1
    assert accepted.provider_id == policy.provider_id
    assert accepted.provider_policy_sha256 == policy.semantic_digest()
    assert accepted.disclosure_sha256 == policy.disclosure.semantic_digest()
    assert (
        accepted.accepted_outbound_categories
        == policy.disclosure.outbound_categories
    )
    assert accepted.status == "active"

    status = project_player_remote_reference_consent_status(
        policy=policy,
        consent=accepted,
        at=NOW,
    )
    assert status.state == "consent_active"
    assert status.reason == "consent_active"
    assert status.provider is not None
    assert status.provider.provider_policy_sha256 == policy.semantic_digest()
    assert status.provider.disclosure == policy.disclosure
    assert status.consent is not None
    assert status.consent.consent_generation == 1
    serialized = status.model_dump(mode="json", by_alias=True)
    assert "route_manifest" not in serialized["provider"]
    assert "provider_policy_sha256" not in serialized["consent"]
    assert "endpoint_origin" not in serialized["consent"]


@pytest.mark.parametrize(
    ("policy", "consent_input", "message"),
    [
        (None, consent_request(), "No active"),
        (
            provider_policy(provider_status="staged"),
            consent_request(),
            "No active",
        ),
        (
            provider_policy(),
            consent_request(expected_consent_generation=1),
            "changed",
        ),
        (
            provider_policy(),
            consent_request(expected_provider_policy_revision="policy-v2"),
            "disclosure changed",
        ),
        (
            provider_policy(endpoint_origin="https://other.vendor.example"),
            consent_request(),
            "disclosure changed",
        ),
        (
            provider_policy(),
            consent_request(expected_disclosure_revision="disclosure-v2"),
            "disclosure changed",
        ),
    ],
)
def test_accept_rejects_unavailable_or_stale_policy_state(
    policy,
    consent_input: PlayerRemoteReferenceConsentRequest,
    message: str,
) -> None:
    with pytest.raises(PlayerRemoteReferenceConsentConflict, match=message):
        accept_player_remote_reference_consent(
            policy=policy,
            current=None,
            request=consent_input,
            at=NOW,
        )


@pytest.mark.parametrize(
    "field",
    [
        "disclosure_accepted",
        "network_dependency_accepted",
        "retention_and_use_accepted",
    ],
)
def test_acceptance_requires_every_affirmation(field: str) -> None:
    values = consent_request().model_dump()
    values[field] = False

    with pytest.raises(ValidationError):
        PlayerRemoteReferenceConsentRequest.model_validate(values)


def test_revocation_is_immediate_idempotent_and_allows_a_new_generation() -> None:
    policy = provider_policy()
    active = accept_player_remote_reference_consent(
        policy=policy,
        current=None,
        request=consent_request(),
        at=NOW,
    )
    request = PlayerRemoteReferenceRevokeRequest(expected_consent_generation=1)

    revoked = revoke_player_remote_reference_consent(
        current=active,
        request=request,
        at=NOW + timedelta(minutes=1),
    )
    repeated = revoke_player_remote_reference_consent(
        current=revoked,
        request=request,
        at=NOW + timedelta(minutes=2),
    )

    assert revoked.status == "revoked"
    assert revoked.consent_generation == 1
    assert repeated == revoked
    assert project_player_remote_reference_consent_status(
        policy=policy,
        consent=revoked,
        at=NOW + timedelta(minutes=2),
    ).reason == "consent_revoked"

    reaccepted = accept_player_remote_reference_consent(
        policy=policy,
        current=revoked,
        request=consent_request(expected_consent_generation=1),
        at=NOW + timedelta(minutes=3),
    )
    assert reaccepted.status == "active"
    assert reaccepted.consent_generation == 2
    assert reaccepted.consent_id != active.consent_id


def test_status_is_local_only_without_an_active_provider() -> None:
    status = project_player_remote_reference_consent_status(
        policy=None,
        consent=None,
        at=NOW,
    )

    assert status.state == "local_only"
    assert status.reason == "provider_unconfigured"
    assert status.consent_generation == 0
    assert status.provider is None
    assert status.consent is None


def test_status_preserves_consent_while_policy_drift_disables_it() -> None:
    original = provider_policy()
    accepted = accept_player_remote_reference_consent(
        policy=original,
        current=None,
        request=consent_request(),
        at=NOW,
    )
    changed = provider_policy(provider_policy_revision="policy-v2")

    status = project_player_remote_reference_consent_status(
        policy=changed,
        consent=accepted,
        at=NOW + timedelta(minutes=1),
    )

    assert status.state == "consent_required"
    assert status.reason == "provider_policy_mismatch"
    assert status.consent_generation == 1
    assert status.consent is not None
    assert status.consent.status == "active"


def test_reacceptance_keeps_generation_timestamps_monotonic() -> None:
    policy = provider_policy()
    active = accept_player_remote_reference_consent(
        policy=policy,
        current=None,
        request=consent_request(),
        at=NOW,
    )
    revoked = revoke_player_remote_reference_consent(
        current=active,
        request=PlayerRemoteReferenceRevokeRequest(expected_consent_generation=1),
        at=NOW + timedelta(minutes=1),
    )

    reaccepted = accept_player_remote_reference_consent(
        policy=policy,
        current=revoked,
        request=consent_request(expected_consent_generation=1),
        at=NOW - timedelta(minutes=1),
    )

    assert revoked.revoked_at is not None
    assert reaccepted.consented_at > revoked.revoked_at


def test_workspace_serializes_concurrent_consent_acceptance(tmp_path: Path) -> None:
    workspace = PlayerWorkspace.open(tmp_path)
    policy = provider_policy()

    def accept() -> str:
        try:
            result = workspace.accept_remote_reference_consent(
                policy=policy,
                request=consent_request(),
                at=NOW,
            )
        except PlayerRemoteReferenceConsentConflict:
            return "conflict"
        return result.state

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _index: accept(), range(2)))

    assert outcomes == ["conflict", "consent_active"]
    stored = workspace.remote_reference_consent.load().consent
    assert stored is not None
    assert stored.consent_generation == 1
