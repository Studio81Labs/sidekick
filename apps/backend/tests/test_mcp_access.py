from datetime import datetime, timedelta, timezone
import asyncio
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import create_app
from app.config import Settings
from app.mcp_access import McpPrincipalStore
from app.mcp_http import HostedMcpAuthMiddleware, _McpBodyReadLimiter


def test_principal_store_issues_once_rotates_and_revokes(tmp_path: Path) -> None:
    store = McpPrincipalStore(tmp_path, "staging")
    issued = store.create(
        name="Codex staging read",
        scopes=["read"],
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )

    assert issued.token.startswith("phmcp_")
    assert store.authenticate(issued.token) is not None
    assert store.list()[0].last_used_at is None
    assert store.record_usage(issued.token) is True
    assert store.list()[0].last_used_at is not None
    serialized = (tmp_path / "mcp" / "principals.json").read_text(encoding="utf-8")
    assert issued.token not in serialized
    assert issued.principal.token_prefix in serialized

    rotated = store.rotate(issued.principal.id)
    assert rotated.token != issued.token
    assert store.authenticate(issued.token) is None
    assert store.authenticate(rotated.token) is not None

    revoked = store.revoke(issued.principal.id)
    assert revoked.status == "revoked"
    assert store.authenticate(rotated.token) is None


def test_principal_store_binds_credentials_to_environment(tmp_path: Path) -> None:
    staging = McpPrincipalStore(tmp_path, "staging")
    production = McpPrincipalStore(tmp_path, "production")
    issued = staging.create(
        name="Codex staging",
        scopes=["read"],
        expires_at=None,
    )

    assert staging.authenticate(issued.token) is not None
    assert production.authenticate(issued.token) is None
    assert production.list() == []


def test_hosted_mcp_is_dark_by_default(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            Settings(
                data_dir=tmp_path,
                deployment_environment="staging",
                api_rate_limit_enabled=False,
            )
        ),
        base_url="https://poker.test",
    )

    assert client.post("/mcp", json={}).status_code == 404
    assert client.get("/api/mcp/config").json() == {
        "enabled": False,
        "environment": "staging",
        "endpoint": None,
        "writes_enabled": False,
    }


def test_production_rejects_write_credentials(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            Settings(
                data_dir=tmp_path,
                deployment_environment="production",
                api_rate_limit_enabled=False,
            )
        ),
        base_url="https://poker.test",
    )

    rejected = client.post(
        "/api/mcp/principals",
        json={
            "name": "Codex production",
            "scopes": ["read", "write"],
            "expires_at": None,
        },
    )

    assert rejected.status_code == 400
    assert rejected.json()["detail"] == (
        "MCP write credentials can only be issued in staging"
    )


def test_hosted_mcp_requires_an_environment_token(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deployment_environment="staging",
        mcp_enabled=True,
        mcp_public_url="https://faß.test:443/mcp",
        mcp_allowed_origins=["https://agent.faß.test:443"],
        api_rate_limit_enabled=False,
    )
    with TestClient(
        create_app(settings),
        base_url="https://xn--fa-hia.test",
    ) as client:
        preflight = client.options(
            "/mcp",
            headers={
                "Origin": "https://agent.xn--fa-hia.test",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == (
            "https://agent.xn--fa-hia.test"
        )
        api_preflight = client.options(
            "/api/health",
            headers={
                "Origin": "https://agent.xn--fa-hia.test",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert api_preflight.status_code == 400
        assert "access-control-allow-origin" not in api_preflight.headers

        missing = client.post("/mcp", json=_initialize_request())
        assert missing.status_code == 401
        assert missing.headers["www-authenticate"] == "Bearer"
        assert missing.headers["cache-control"] == "no-store"

        issued = client.post(
            "/api/mcp/principals",
            json={"name": "Codex staging", "scopes": ["read"], "expires_at": None},
        )
        assert issued.status_code == 201
        token = issued.json()["token"]
        assert token.startswith("phmcp_")
        assert issued.headers["cache-control"] == "no-store"

        initialized = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Origin": "https://agent.xn--fa-hia.test",
            },
            json=_initialize_request(),
        )
        assert initialized.status_code == 200
        assert initialized.headers["cache-control"] == "no-store"
        assert initialized.headers["access-control-allow-origin"] == (
            "https://agent.xn--fa-hia.test"
        )
        assert initialized.json()["result"]["serverInfo"]["name"] == "Poker Hero staging"

        tools = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert tools.status_code == 200
        assert {tool["name"] for tool in tools.json()["result"]["tools"]} == {
            "get_environment_status",
            "list_processing_jobs",
            "get_job",
            "search_history",
            "get_training_progress",
            "list_benchmarks",
        }

        revoked = client.delete(
            f"/api/mcp/principals/{issued.json()['principal']['id']}"
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"
        denied = client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {token}"},
            json=_initialize_request(),
        )
        assert denied.status_code == 401


def test_hosted_mcp_accepts_worker_canonical_ipv6_authority(
    tmp_path: Path,
) -> None:
    proxy_secret = "worker-to-backend-secret-value-123"
    settings = Settings(
        data_dir=tmp_path,
        deployment_environment="staging",
        mcp_enabled=True,
        mcp_public_url="https://[2001:0db8:0:0:0:0:0:1]/mcp",
        proxy_shared_secret=proxy_secret,
        api_rate_limit_enabled=False,
    )
    with TestClient(create_app(settings), base_url="https://backend.test") as client:
        token = client.post(
            "/api/mcp/principals",
            headers={"X-Poker-Proxy-Secret": proxy_secret},
            json={"name": "IPv6 Codex", "scopes": ["read"], "expires_at": None},
        ).json()["token"]
        initialized = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "X-Poker-MCP-Public-Host": "[2001:db8::1]",
                "X-Poker-Proxy-Secret": proxy_secret,
            },
            json=_initialize_request(),
        )

        assert initialized.status_code == 200


def test_hosted_mcp_requires_scope_and_omits_local_upload(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deployment_environment="staging",
        mcp_enabled=True,
        mcp_public_url="https://poker.test/mcp",
        mcp_allow_writes=True,
        api_rate_limit_enabled=False,
    )
    with TestClient(create_app(settings), base_url="https://poker.test") as client:
        issued = client.post(
            "/api/mcp/principals",
            json={"name": "Read-only Codex", "scopes": ["read"], "expires_at": None},
        ).json()
        token = issued["token"]
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
        }
        tools = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        ).json()["result"]["tools"]
        names = {tool["name"] for tool in tools}
        assert "save_training_review" in names
        assert "submit_screenshot" not in names

        denied = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "save_training_review",
                    "arguments": {"job_id": "0" * 32, "note": "review"},
                },
            },
        )
        assert denied.status_code == 200
        assert denied.json()["result"]["isError"] is True
        assert "does not grant write access" in denied.json()["result"]["content"][0]["text"]


def test_hosted_mcp_preserves_internal_api_failure_request_id(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        deployment_environment="staging",
        mcp_enabled=True,
        mcp_public_url="https://poker.test/mcp",
        api_rate_limit_enabled=False,
    )
    with TestClient(create_app(settings), base_url="https://poker.test") as client:
        token = client.post(
            "/api/mcp/principals",
            json={"name": "Codex staging", "scopes": ["read"], "expires_at": None},
        ).json()["token"]
        with caplog.at_level(logging.INFO, logger="poker.access"):
            failed = client.post(
                "/mcp",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "get_job",
                        "arguments": {"job_id": "0" * 32},
                    },
                },
            )

    assert failed.status_code == 200
    assert failed.json()["result"]["isError"] is True
    tool_error_text = failed.json()["result"]["content"][0]["text"]
    tool_error = json.loads(tool_error_text[tool_error_text.index("{") :])
    assert tool_error["status_code"] == 404
    assert tool_error["request_id"]
    access_events = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "poker.access"
    ]
    internal_failure = next(
        event
        for event in access_events
        if event["path"] == f"/api/jobs/{'0' * 32}"
    )
    assert internal_failure["status_code"] == 404
    assert internal_failure["request_id"] == tool_error["request_id"]


def test_hosted_mcp_rate_limits_each_principal_before_recording_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded_tokens: list[str] = []
    original_record_usage = McpPrincipalStore.record_usage

    def record_usage(store: McpPrincipalStore, token: str) -> bool:
        recorded_tokens.append(token)
        return original_record_usage(store, token)

    monkeypatch.setattr(McpPrincipalStore, "record_usage", record_usage)
    settings = Settings(
        data_dir=tmp_path,
        deployment_environment="staging",
        mcp_enabled=True,
        mcp_public_url="https://poker.test/mcp",
        mcp_read_calls_per_minute=1,
        api_rate_limit_enabled=False,
    )
    with TestClient(create_app(settings), base_url="https://poker.test") as client:
        token = client.post(
            "/api/mcp/principals",
            json={"name": "Limited Codex", "scopes": ["read"], "expires_at": None},
        ).json()["token"]
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
        }
        assert client.post(
            "/mcp", headers=headers, json=_initialize_request()
        ).status_code == 200
        limited = client.post(
            "/mcp", headers=headers, json=_initialize_request()
        )
        assert limited.status_code == 429
        assert limited.headers["retry-after"]
        assert recorded_tokens == [token]


def test_hosted_mcp_limits_concurrent_body_reads_before_buffering(
    tmp_path: Path,
) -> None:
    store = McpPrincipalStore(tmp_path, "staging")
    issued = store.create(name="Concurrent Codex", scopes=["read"], expires_at=None)
    first_body_started = asyncio.Event()
    release_first_body = asyncio.Event()
    second_receive_called = False
    second_messages: list[dict[str, object]] = []

    async def app(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = HostedMcpAuthMiddleware(
        app,
        principal_store=store,
        expected_host="poker.test",
        allowed_origins=frozenset(),
        proxy_shared_secret=None,
        read_calls_per_minute=60,
        write_calls_per_minute=10,
    )
    middleware.body_read_limiter = _McpBodyReadLimiter(maximum_per_principal=1)
    scope = {
        "type": "http",
        "path": "/mcp",
        "headers": [
            (b"host", b"poker.test"),
            (b"authorization", f"Bearer {issued.token}".encode("ascii")),
        ],
    }

    async def first_receive() -> dict[str, object]:
        first_body_started.set()
        await release_first_body.wait()
        return {
            "type": "http.request",
            "body": json.dumps(_initialize_request()).encode("utf-8"),
            "more_body": False,
        }

    async def second_receive() -> dict[str, object]:
        nonlocal second_receive_called
        second_receive_called = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def discard_send(message) -> None:
        pass

    async def record_second_send(message) -> None:
        second_messages.append(message)

    async def exercise() -> None:
        first_request = asyncio.create_task(
            middleware(scope, first_receive, discard_send)
        )
        await first_body_started.wait()
        await middleware(scope, second_receive, record_second_send)
        release_first_body.set()
        await first_request

    asyncio.run(exercise())

    assert second_receive_called is False
    assert second_messages[0]["status"] == 429
    assert middleware.body_read_limiter.active == {}
    assert store.list()[0].last_used_at is not None


def _initialize_request() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "poker-tests", "version": "1.0"},
        },
    }
