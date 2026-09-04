"""Last-moment authorization guard for an injected remote-reference transport."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from hashlib import sha256
from typing import Protocol, TypeAlias

from app.domain.remote_references import (
    MAX_REMOTE_REFERENCE_RESPONSE_BYTES,
    RemoteDispatchReason,
    RemoteEventTimeBasis,
    RemoteReferenceDispatchAuthority,
    RemoteReferenceDispatchPreflight,
    RemoteReferenceLookupResponseCandidate,
    RemoteReferenceLookupUnavailable,
    RemoteReferenceRouteDerivation,
    RemoteReferenceRouteRequest,
    RemoteReferenceTransportBinding,
    bind_remote_reference_route,
    evaluate_remote_reference_preflight,
    record_remote_reference_unavailable,
)


RemoteReferenceAuthorityLoader: TypeAlias = Callable[
    [], RemoteReferenceDispatchAuthority
]
RemoteReferenceAuthorityLockFactory: TypeAlias = Callable[
    [], AbstractContextManager[object]
]
RemoteReferenceClock: TypeAlias = Callable[[], datetime]
RemoteReferenceDispatchAttempt: TypeAlias = (
    RemoteReferenceDispatchPreflight
    | RemoteReferenceLookupUnavailable
    | RemoteReferenceLookupResponseCandidate
)
RemoteReferenceAuthorityOperation: TypeAlias = Callable[
    [RemoteReferenceDispatchAuthority], RemoteReferenceDispatchAttempt
]


class RemoteReferenceTransport(Protocol):
    """One bounded adapter pinned to the provider configuration it can call."""

    binding: RemoteReferenceTransportBinding

    def __call__(
        self,
        request: RemoteReferenceRouteRequest,
        *,
        max_response_bytes: int,
    ) -> bytes: ...


class RemoteReferenceAuthorityGuard:
    """Run one attempt while holding the consent-mutation exclusion boundary."""

    def __init__(
        self,
        *,
        lock_factory: RemoteReferenceAuthorityLockFactory,
        load_authority: RemoteReferenceAuthorityLoader,
    ) -> None:
        self._lock_factory = lock_factory
        self._load_authority = load_authority

    def run(
        self,
        operation: RemoteReferenceAuthorityOperation,
    ) -> RemoteReferenceDispatchAttempt:
        with self._lock_factory():
            snapshot = self._load_authority()
            authority = RemoteReferenceDispatchAuthority.model_validate(
                snapshot.model_dump(mode="python")
            )
            return operation(authority)


class RemoteReferenceNetworkError(RuntimeError):
    """The injected transport could not reach the configured provider."""


class RemoteReferenceProviderError(RuntimeError):
    """The injected transport received an explicit provider failure."""


def dispatch_remote_reference_lookup(
    *,
    candidate: RemoteReferenceDispatchPreflight,
    authority_guard: RemoteReferenceAuthorityGuard,
    transport: RemoteReferenceTransport,
    clock: RemoteReferenceClock,
) -> RemoteReferenceDispatchAttempt:
    """Reauthorize one candidate immediately before one injected transport call."""

    candidate = RemoteReferenceDispatchPreflight.model_validate(
        candidate.model_dump(mode="python")
    )
    if candidate.outcome != "dispatch_candidate":
        raise ValueError("remote dispatch requires a passing preflight candidate")
    assert candidate.evaluated_at is not None
    assert candidate.outbound_request is not None

    return authority_guard.run(
        lambda authority: _dispatch_under_authority(
            candidate=candidate,
            authority=authority,
            transport=transport,
            clock=clock,
        )
    )


def _dispatch_under_authority(
    *,
    candidate: RemoteReferenceDispatchPreflight,
    authority: RemoteReferenceDispatchAuthority,
    transport: RemoteReferenceTransport,
    clock: RemoteReferenceClock,
) -> RemoteReferenceDispatchAttempt:
    recheck_at = _pre_dispatch_time(clock)
    if recheck_at is None:
        return _dispatch_denied(
            candidate,
            reason="clock_invalid",
            evaluated_at=None,
        )
    if recheck_at < candidate.evaluated_at:
        return _dispatch_denied(
            candidate,
            reason="preflight_candidate_stale",
            evaluated_at=recheck_at,
        )

    if authority.mode == "local_only":
        return _dispatch_denied(
            candidate,
            reason="local_only",
            evaluated_at=recheck_at,
        )
    if authority.decision is None:
        return _dispatch_denied(
            candidate,
            reason="decision_unavailable",
            evaluated_at=recheck_at,
        )
    try:
        route: RemoteReferenceRouteDerivation = bind_remote_reference_route(
            authority.decision,
            candidate.outbound_request,
        )
    except ValueError:
        return _dispatch_denied(
            candidate,
            reason="route_binding_mismatch",
            evaluated_at=recheck_at,
        )

    fresh = evaluate_remote_reference_preflight(
        authority.decision,
        mode=authority.mode,
        policy=authority.policy,
        consent=authority.consent,
        route=route,
        now=recheck_at,
    )
    if fresh.outcome != "dispatch_candidate":
        return fresh
    if not _same_dispatch_authority(candidate, fresh):
        return _dispatch_denied(
            candidate,
            reason="preflight_candidate_stale",
            evaluated_at=recheck_at,
        )

    expected_transport = RemoteReferenceTransportBinding(
        provider_id=fresh.provider_id,
        provider_configuration_revision=fresh.provider_configuration_revision,
        provider_policy_revision=fresh.provider_policy_revision,
        provider_policy_sha256=fresh.provider_policy_sha256,
        endpoint_origin=fresh.endpoint_origin,
    )
    actual_transport = RemoteReferenceTransportBinding.model_validate(
        transport.binding.model_dump(mode="python")
    )
    if actual_transport != expected_transport:
        return _dispatch_denied(
            candidate,
            reason="transport_binding_mismatch",
            evaluated_at=recheck_at,
        )

    assert fresh.outbound_request is not None
    try:
        response_body = transport(
            fresh.outbound_request,
            max_response_bytes=MAX_REMOTE_REFERENCE_RESPONSE_BYTES,
        )
    except RemoteReferenceNetworkError:
        occurred_at, occurred_at_basis = _post_dispatch_time(
            clock,
            dispatched_at=recheck_at,
        )
        return record_remote_reference_unavailable(
            fresh,
            reason="network_failure",
            occurred_at=occurred_at,
            occurred_at_basis=occurred_at_basis,
        )
    except RemoteReferenceProviderError:
        occurred_at, occurred_at_basis = _post_dispatch_time(
            clock,
            dispatched_at=recheck_at,
        )
        return record_remote_reference_unavailable(
            fresh,
            reason="provider_failure",
            occurred_at=occurred_at,
            occurred_at_basis=occurred_at_basis,
        )

    if not isinstance(response_body, bytes):
        occurred_at, occurred_at_basis = _post_dispatch_time(
            clock,
            dispatched_at=recheck_at,
        )
        return record_remote_reference_unavailable(
            fresh,
            reason="transport_contract_failure",
            occurred_at=occurred_at,
            occurred_at_basis=occurred_at_basis,
        )
    received_at, received_at_basis = _post_dispatch_time(
        clock,
        dispatched_at=recheck_at,
    )
    if not response_body or len(response_body) > MAX_REMOTE_REFERENCE_RESPONSE_BYTES:
        return record_remote_reference_unavailable(
            fresh,
            reason="response_invalid",
            occurred_at=received_at,
            occurred_at_basis=received_at_basis,
            response_body=response_body,
        )
    return RemoteReferenceLookupResponseCandidate(
        preflight=fresh,
        dispatched_at=recheck_at,
        received_at=received_at,
        received_at_basis=received_at_basis,
        response_body=response_body,
        response_sha256=sha256(response_body).hexdigest(),
    )


def _same_dispatch_authority(
    earlier: RemoteReferenceDispatchPreflight,
    fresh: RemoteReferenceDispatchPreflight,
) -> bool:
    return earlier.model_dump(
        mode="python",
        exclude={"evaluated_at"},
    ) == fresh.model_dump(
        mode="python",
        exclude={"evaluated_at"},
    )


def _dispatch_denied(
    candidate: RemoteReferenceDispatchPreflight,
    *,
    reason: RemoteDispatchReason,
    evaluated_at: datetime | None,
) -> RemoteReferenceDispatchPreflight:
    return RemoteReferenceDispatchPreflight.model_validate(
        {
            "decision": candidate.decision,
            "evaluated_at": evaluated_at,
            "outcome": "unavailable",
            "reason": reason,
        }
    )


def _pre_dispatch_time(clock: RemoteReferenceClock) -> datetime | None:
    try:
        at = clock()
    except Exception:
        return None
    if not _is_aware(at):
        return None
    return at


def _post_dispatch_time(
    clock: RemoteReferenceClock,
    *,
    dispatched_at: datetime,
) -> tuple[datetime, RemoteEventTimeBasis]:
    try:
        at = clock()
    except Exception:
        return dispatched_at, "dispatch_authorization_fallback"
    if not _is_aware(at) or at < dispatched_at:
        return dispatched_at, "dispatch_authorization_fallback"
    return at, "observed"


def _is_aware(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )
