from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from hashlib import sha256
from threading import Lock

import pytest
from pydantic import ValidationError

from app.application.remote_reference_dispatch import (
    RemoteReferenceAuthorityGuard,
    RemoteReferenceNetworkError,
    RemoteReferenceProviderError,
    dispatch_remote_reference_lookup,
)
from app.domain.remote_references import (
    MAX_REMOTE_REFERENCE_RESPONSE_BYTES,
    RemoteReferenceDispatchAuthority,
    RemoteReferenceDispatchPreflight,
    RemoteReferenceLookupResponseCandidate,
    RemoteReferenceLookupUnavailable,
    RemoteReferenceProviderPolicy,
    RemoteReferenceRouteRequest,
    RemoteReferenceTransportBinding,
)
from test_remote_references import (
    NOW,
    canonical_route_request,
    consent,
    decision_point,
    equal_blind_decision_point,
    preflight,
    provider_policy,
)


class RecordingTransport:
    def __init__(
        self,
        *,
        binding: RemoteReferenceTransportBinding | None = None,
        response_body: object = b'{"status":"unvalidated"}',
        error: RuntimeError | None = None,
        on_call: Callable[[], None] | None = None,
    ) -> None:
        self.binding = binding or transport_binding()
        self.response_body = response_body
        self.error = error
        self.on_call = on_call
        self.calls: list[tuple[RemoteReferenceRouteRequest, int]] = []

    def __call__(
        self,
        request: RemoteReferenceRouteRequest,
        *,
        max_response_bytes: int,
    ) -> bytes:
        self.calls.append((request, max_response_bytes))
        if self.on_call is not None:
            self.on_call()
        if self.error is not None:
            raise self.error
        return self.response_body  # type: ignore[return-value]


def clock(*values: datetime):
    times = iter(values)
    return lambda: next(times)


def authority(**updates: object) -> RemoteReferenceDispatchAuthority:
    values = {
        "mode": "remote_enabled",
        "decision": decision_point(),
        "policy": provider_policy(),
        "consent": consent(),
    }
    values.update(updates)
    return RemoteReferenceDispatchAuthority.model_validate(values)


def authority_guard(
    current: RemoteReferenceDispatchAuthority | None = None,
) -> RemoteReferenceAuthorityGuard:
    snapshot = current or authority()
    return RemoteReferenceAuthorityGuard(
        lock=Lock(),
        load_authority=lambda: snapshot,
    )


def transport_binding(
    policy: RemoteReferenceProviderPolicy | None = None,
    **updates: object,
) -> RemoteReferenceTransportBinding:
    selected = policy or provider_policy()
    values = {
        "provider_id": selected.provider_id,
        "provider_configuration_revision": (
            selected.provider_configuration_revision
        ),
        "provider_policy_revision": selected.provider_policy_revision,
        "provider_policy_sha256": selected.semantic_digest(),
        "endpoint_origin": selected.endpoint_origin,
    }
    values.update(updates)
    return RemoteReferenceTransportBinding.model_validate(values)


def test_dispatch_rechecks_authority_and_sends_only_the_closed_request() -> None:
    response_body = b'{"status":"unvalidated"}'
    transport = RecordingTransport(response_body=response_body)

    result = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(),
        transport=transport,
        clock=clock(NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)),
    )

    assert isinstance(result, RemoteReferenceLookupResponseCandidate)
    assert transport.calls == [
        (canonical_route_request(), MAX_REMOTE_REFERENCE_RESPONSE_BYTES)
    ]
    assert result.preflight.evaluated_at == NOW + timedelta(seconds=1)
    assert result.response_body == response_body
    assert result.response_sha256 == sha256(response_body).hexdigest()
    assert result.fresh_authority_recheck == "passed_immediately_before_dispatch"
    assert result.response_validation == "pending"
    assert result.policy_grade_eligibility == "ungraded"
    assert result.resolved_reference is None
    outbound = transport.calls[0][0].model_dump(mode="json")
    assert "decision" not in outbound
    assert "decision_state_sha256" not in outbound
    assert "consent" not in outbound
    assert "provider" not in outbound


def test_authority_guard_holds_its_lock_through_the_transport_call() -> None:
    shared_lock = Lock()
    observed: list[str] = []

    def load_authority() -> RemoteReferenceDispatchAuthority:
        assert shared_lock.locked()
        observed.append("loaded")
        return authority()

    def observe_transport() -> None:
        assert shared_lock.locked()
        observed.append("transported")

    result = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=RemoteReferenceAuthorityGuard(
            lock=shared_lock,
            load_authority=load_authority,
        ),
        transport=RecordingTransport(on_call=observe_transport),
        clock=clock(NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)),
    )

    assert isinstance(result, RemoteReferenceLookupResponseCandidate)
    assert observed == ["loaded", "transported"]
    assert not shared_lock.locked()


def test_dispatch_requires_an_initial_candidate() -> None:
    unavailable = RemoteReferenceDispatchPreflight(
        decision=preflight().decision,
        evaluated_at=NOW,
        outcome="unavailable",
        reason="local_only",
    )

    with pytest.raises(ValueError, match="passing preflight candidate"):
        dispatch_remote_reference_lookup(
            candidate=unavailable,
            authority_guard=authority_guard(),
            transport=RecordingTransport(response_body=b"must-not-run"),
            clock=clock(NOW + timedelta(seconds=1)),
        )


@pytest.mark.parametrize(
    ("current_authority", "expected_reason"),
    [
        (authority(mode="local_only"), "local_only"),
        (authority(decision=None), "decision_unavailable"),
        (
            authority(
                consent=consent(
                    consent_generation=2,
                    status="revoked",
                    revoked_at=NOW + timedelta(seconds=1),
                )
            ),
            "consent_revoked",
        ),
        (
            authority(
                policy=provider_policy(provider_status="disabled"),
                consent=consent(),
            ),
            "provider_inactive",
        ),
    ],
)
def test_current_authority_can_deny_without_calling_transport(
    current_authority: RemoteReferenceDispatchAuthority,
    expected_reason: str,
) -> None:
    transport = RecordingTransport(response_body=b"must-not-run")

    result = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(current_authority),
        transport=transport,
        clock=clock(NOW + timedelta(seconds=2)),
    )

    assert isinstance(result, RemoteReferenceDispatchPreflight)
    assert result.outcome == "unavailable"
    assert result.reason == expected_reason
    assert result.outbound_request is None
    assert transport.calls == []


def test_new_valid_consent_generation_requires_a_new_candidate() -> None:
    current = consent(consent_id="consent-v2", consent_generation=2)
    transport = RecordingTransport(response_body=b"must-not-run")

    result = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(authority(consent=current)),
        transport=transport,
        clock=clock(NOW + timedelta(seconds=1)),
    )

    assert isinstance(result, RemoteReferenceDispatchPreflight)
    assert result.reason == "preflight_candidate_stale"
    assert result.outbound_request is None
    assert transport.calls == []


def test_changed_or_withdrawn_decision_cannot_reuse_a_candidate() -> None:
    changed_transport = RecordingTransport(response_body=b"must-not-run")
    changed = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(
            authority(decision=equal_blind_decision_point())
        ),
        transport=changed_transport,
        clock=clock(NOW + timedelta(seconds=1)),
    )
    withdrawn_transport = RecordingTransport(response_body=b"must-not-run")
    withdrawn = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(authority(decision=None)),
        transport=withdrawn_transport,
        clock=clock(NOW + timedelta(seconds=1)),
    )

    assert changed.reason == "route_binding_mismatch"
    assert withdrawn.reason == "decision_unavailable"
    assert changed_transport.calls == []
    assert withdrawn_transport.calls == []


def test_transport_must_match_the_fresh_provider_and_origin() -> None:
    transport = RecordingTransport(
        binding=transport_binding(
            provider_id="vendor-b",
            endpoint_origin="https://other.vendor.example",
        ),
        response_body=b"must-not-run",
    )

    result = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(),
        transport=transport,
        clock=clock(NOW + timedelta(seconds=1)),
    )

    assert result.reason == "transport_binding_mismatch"
    assert result.outbound_request is None
    assert transport.calls == []


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    [
        (RemoteReferenceNetworkError("offline"), "network_failure"),
        (RemoteReferenceProviderError("rejected"), "provider_failure"),
    ],
)
def test_explicit_transport_failures_remain_ungraded(
    error: RuntimeError,
    expected_reason: str,
) -> None:
    transport = RecordingTransport(error=error)

    result = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(),
        transport=transport,
        clock=clock(NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)),
    )

    assert isinstance(result, RemoteReferenceLookupUnavailable)
    assert result.reason == expected_reason
    assert result.response_sha256 is None
    assert result.policy_grade_eligibility == "ungraded"
    assert result.fallback_behavior == "forbidden"
    assert result.request_sha256 == preflight().request_sha256
    assert len(transport.calls) == 1


def test_non_bytes_output_is_an_audited_transport_contract_failure() -> None:
    result = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(),
        transport=RecordingTransport(response_body="not-bytes"),
        clock=clock(NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)),
    )

    assert isinstance(result, RemoteReferenceLookupUnavailable)
    assert result.reason == "transport_contract_failure"
    assert result.response_sha256 is None


@pytest.mark.parametrize(
    "response_body",
    [
        b"",
        b"x" * (MAX_REMOTE_REFERENCE_RESPONSE_BYTES + 1),
    ],
)
def test_invalid_response_bounds_retain_only_a_local_digest(
    response_body: bytes,
) -> None:
    result = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(),
        transport=RecordingTransport(response_body=response_body),
        clock=clock(NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)),
    )

    assert isinstance(result, RemoteReferenceLookupUnavailable)
    assert result.reason == "response_invalid"
    assert result.response_sha256 == sha256(response_body).hexdigest()
    assert result.resolved_reference is None


def test_dispatch_rejects_invalid_or_reversed_clocks_without_transport() -> None:
    naive = NOW.replace(tzinfo=None)
    invalid_transport = RecordingTransport(response_body=b"must-not-run")
    invalid = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(),
        transport=invalid_transport,
        clock=clock(naive),
    )
    reversed_transport = RecordingTransport(response_body=b"must-not-run")
    reversed_clock = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(),
        transport=reversed_transport,
        clock=clock(NOW - timedelta(seconds=1)),
    )

    assert invalid.reason == "clock_invalid"
    assert invalid.evaluated_at is None
    assert reversed_clock.reason == "preflight_candidate_stale"
    assert invalid_transport.calls == []
    assert reversed_transport.calls == []


@pytest.mark.parametrize(
    "transport",
    [
        RecordingTransport(response_body=b"response"),
        RecordingTransport(error=RemoteReferenceNetworkError("offline")),
    ],
)
def test_post_dispatch_clock_failure_retains_auditable_provenance(
    transport: RecordingTransport,
) -> None:
    result = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(),
        transport=transport,
        clock=clock(NOW + timedelta(seconds=1), NOW.replace(tzinfo=None)),
    )

    if isinstance(result, RemoteReferenceLookupResponseCandidate):
        assert result.received_at == result.dispatched_at
        assert result.received_at_basis == "dispatch_authorization_fallback"
        assert result.response_sha256 == sha256(b"response").hexdigest()
    else:
        assert isinstance(result, RemoteReferenceLookupUnavailable)
        assert result.occurred_at == result.preflight_evaluated_at
        assert result.occurred_at_basis == "dispatch_authorization_fallback"
        assert result.reason == "network_failure"


def test_raising_post_dispatch_clock_retains_auditable_provenance() -> None:
    times = iter((NOW + timedelta(seconds=1),))

    def failing_clock() -> datetime:
        try:
            return next(times)
        except StopIteration as exc:
            raise RuntimeError("clock unavailable") from exc

    result = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(),
        transport=RecordingTransport(
            error=RemoteReferenceProviderError("rejected")
        ),
        clock=failing_clock,
    )

    assert isinstance(result, RemoteReferenceLookupUnavailable)
    assert result.reason == "provider_failure"
    assert result.occurred_at == result.preflight_evaluated_at
    assert result.occurred_at_basis == "dispatch_authorization_fallback"


def test_response_contract_rejects_forged_digest_and_non_candidate() -> None:
    result = dispatch_remote_reference_lookup(
        candidate=preflight(),
        authority_guard=authority_guard(),
        transport=RecordingTransport(response_body=b"response"),
        clock=clock(NOW + timedelta(seconds=1), NOW + timedelta(seconds=2)),
    )
    assert isinstance(result, RemoteReferenceLookupResponseCandidate)

    with pytest.raises(ValidationError, match="digest"):
        RemoteReferenceLookupResponseCandidate.model_validate(
            result.model_copy(update={"response_sha256": "0" * 64}).model_dump(
                mode="python"
            )
        )
    unavailable = RemoteReferenceDispatchPreflight(
        decision=preflight().decision,
        evaluated_at=NOW,
        outcome="unavailable",
        reason="local_only",
    )
    with pytest.raises(ValidationError, match="passing fresh preflight"):
        RemoteReferenceLookupResponseCandidate.model_validate(
            result.model_copy(update={"preflight": unavailable}).model_dump(
                mode="python"
            )
        )
