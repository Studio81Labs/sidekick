from __future__ import annotations

from collections import deque
from contextlib import asynccontextmanager
import json
from secrets import compare_digest
from threading import Lock
from time import monotonic
from typing import AsyncIterator, cast
from urllib.parse import urlsplit

import httpx
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import Settings, normalize_https_authority
from app.mcp_access import (
    MCP_PRINCIPAL_CONTEXT,
    McpEnvironment,
    McpPrincipalStore,
)
from app.mcp_gateway import (
    McpGatewaySettings,
    PokerApiClient,
    PokerMcpGateway,
    build_mcp_server,
)


class HostedMcpRuntime:
    def __init__(
        self,
        app: ASGIApp,
        client: httpx.AsyncClient,
        lifespan_app: ASGIApp,
    ) -> None:
        self.app = app
        self.client = client
        self.lifespan_app = lifespan_app

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        router = getattr(self.lifespan_app, "router")
        async with router.lifespan_context(self.lifespan_app):
            try:
                yield
            finally:
                await self.client.aclose()


def build_hosted_mcp_runtime(
    settings: Settings,
    *,
    api_app: ASGIApp,
    principal_store: McpPrincipalStore,
) -> HostedMcpRuntime:
    assert settings.mcp_public_url is not None
    parsed_url = urlsplit(settings.mcp_public_url)
    public_authority = normalize_https_authority(parsed_url)
    public_origin = f"https://{public_authority}"
    environment = cast(McpEnvironment, settings.deployment_environment)
    gateway_settings = McpGatewaySettings(
        environment=environment,
        api_base_url=public_origin,
        request_timeout_seconds=settings.external_request_timeout_seconds,
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_app),
        base_url=public_origin,
        timeout=gateway_settings.request_timeout_seconds,
        follow_redirects=False,
    )
    gateway = PokerMcpGateway(
        gateway_settings,
        api_client=PokerApiClient(gateway_settings, client=client),
    )
    server = build_mcp_server(
        gateway_settings,
        gateway=gateway,
        require_auth=True,
        http_host=parsed_url.hostname or "poker-mcp",
    )
    app = server.streamable_http_app()
    return HostedMcpRuntime(
        HostedMcpAuthMiddleware(
            app,
            principal_store=principal_store,
            expected_host=public_authority,
            allowed_origins=frozenset(settings.mcp_allowed_origins),
            proxy_shared_secret=(
                settings.proxy_shared_secret.get_secret_value()
                if settings.proxy_shared_secret is not None
                else None
            ),
            read_calls_per_minute=settings.mcp_read_calls_per_minute,
        ),
        client,
        app,
    )


class HostedMcpAuthMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        principal_store: McpPrincipalStore,
        expected_host: str,
        allowed_origins: frozenset[str],
        proxy_shared_secret: str | None,
        read_calls_per_minute: int,
    ) -> None:
        self.app = app
        self.principal_store = principal_store
        self.expected_host = expected_host.casefold()
        self.allowed_origins = allowed_origins
        self.proxy_shared_secret = proxy_shared_secret
        self.rate_limiter = _McpRateLimiter(
            read_calls_per_minute=read_calls_per_minute,
        )
        self.body_read_limiter = _McpBodyReadLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("path") != "/mcp":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").casefold(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        direct_host_matches = (
            headers.get("host", "").casefold() == self.expected_host
        )
        forwarded_host_matches = (
            self.proxy_shared_secret is not None
            and headers.get("x-poker-mcp-public-host", "").casefold()
            == self.expected_host
            and compare_digest(
                headers.get("x-poker-proxy-secret", ""),
                self.proxy_shared_secret,
            )
        )
        if not direct_host_matches and not forwarded_host_matches:
            await _send_json(send, 403, {"detail": "Forbidden"})
            return
        origin = headers.get("origin")
        if origin is not None and origin.casefold() not in self.allowed_origins:
            await _send_json(send, 403, {"detail": "Forbidden"})
            return
        authorization = headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.casefold() != "bearer" or not token:
            await _send_unauthorized(send)
            return
        principal = await run_in_threadpool(self.principal_store.authenticate, token)
        if principal is None:
            await _send_unauthorized(send)
            return

        if not self.body_read_limiter.acquire(principal.id):
            await _send_json(
                send,
                429,
                {"detail": "MCP concurrent request limit exceeded"},
                extra_headers=[(b"retry-after", b"1")],
            )
            return
        try:
            try:
                _body, replay_receive = await _buffer_request_body(receive)
            except _McpRequestTooLarge:
                await _send_json(
                    send,
                    413,
                    {"detail": "MCP request body is too large"},
                )
                return
        finally:
            self.body_read_limiter.release(principal.id)
        allowed, retry_after = self.rate_limiter.check(principal.id)
        if not allowed:
            await _send_json(
                send,
                429,
                {"detail": "MCP rate limit exceeded"},
                extra_headers=[
                    (b"retry-after", str(retry_after).encode("ascii")),
                ],
            )
            return
        usage_recorded = await run_in_threadpool(
            self.principal_store.record_usage,
            token,
        )
        if not usage_recorded:
            await _send_unauthorized(send)
            return

        context_token = MCP_PRINCIPAL_CONTEXT.set(principal)

        async def send_private(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, replay_receive, send_private)
        finally:
            MCP_PRINCIPAL_CONTEXT.reset(context_token)


async def _send_unauthorized(send: Send) -> None:
    await _send_json(
        send,
        401,
        {"detail": "MCP authentication required"},
        extra_headers=[(b"www-authenticate", b"Bearer")],
    )


async def _send_json(
    send: Send,
    status_code: int,
    payload: dict[str, str],
    *,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
                *(extra_headers or []),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


MCP_MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024
MCP_MAX_CONCURRENT_BODY_READS_PER_PRINCIPAL = 4


class _McpRequestTooLarge(ValueError):
    pass


class _McpBodyReadLimiter:
    def __init__(
        self,
        maximum_per_principal: int = MCP_MAX_CONCURRENT_BODY_READS_PER_PRINCIPAL,
    ) -> None:
        self.maximum_per_principal = maximum_per_principal
        self.active: dict[str, int] = {}
        self.lock = Lock()

    def acquire(self, principal_id: str) -> bool:
        with self.lock:
            active = self.active.get(principal_id, 0)
            if active >= self.maximum_per_principal:
                return False
            self.active[principal_id] = active + 1
            return True

    def release(self, principal_id: str) -> None:
        with self.lock:
            active = self.active.get(principal_id, 0)
            if active <= 1:
                self.active.pop(principal_id, None)
            else:
                self.active[principal_id] = active - 1


async def _buffer_request_body(receive: Receive) -> tuple[bytes, Receive]:
    frames: list[Message] = []
    body_parts: list[bytes] = []
    body_size = 0
    while True:
        message = await receive()
        frames.append(message)
        if message["type"] != "http.request":
            break
        body_part = message.get("body", b"")
        body_parts.append(body_part)
        body_size += len(body_part)
        if body_size > MCP_MAX_REQUEST_BODY_BYTES:
            raise _McpRequestTooLarge
        if not message.get("more_body", False):
            break

    frame_index = 0

    async def replay() -> Message:
        nonlocal frame_index
        if frame_index < len(frames):
            message = frames[frame_index]
            frame_index += 1
            return message
        return await receive()

    return b"".join(body_parts), replay


class _McpRateLimiter:
    MAX_BUCKETS = 4_096

    def __init__(self, *, read_calls_per_minute: int) -> None:
        self.limit = read_calls_per_minute
        self.calls: dict[str, deque[float]] = {}
        self.lock = Lock()

    def check(self, principal_id: str) -> tuple[bool, int]:
        now = monotonic()
        cutoff = now - 60
        with self.lock:
            if principal_id not in self.calls and len(self.calls) >= self.MAX_BUCKETS:
                inactive = [
                    candidate_id
                    for candidate_id, candidate_calls in self.calls.items()
                    if not candidate_calls or candidate_calls[-1] <= cutoff
                ]
                for candidate_id in inactive:
                    self.calls.pop(candidate_id, None)
                if len(self.calls) >= self.MAX_BUCKETS:
                    oldest_id = min(
                        self.calls,
                        key=lambda candidate_id: self.calls[candidate_id][-1],
                    )
                    self.calls.pop(oldest_id)
            calls = self.calls.setdefault(principal_id, deque())
            while calls and calls[0] <= cutoff:
                calls.popleft()
            if len(calls) >= self.limit:
                retry_after = max(1, int(61 - (now - calls[0])))
                return False, retry_after
            calls.append(now)
            return True, 0
