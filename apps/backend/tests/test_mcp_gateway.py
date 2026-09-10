import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from app.mcp_gateway import (
    McpGatewaySettings,
    PokerApiClient,
    PokerApiError,
    PokerMcpGateway,
    build_mcp_server,
)


def run(coroutine):
    return asyncio.run(coroutine)


def test_mcp_settings_require_safe_fixed_targets() -> None:
    with pytest.raises(ValidationError, match="HTTPS or loopback HTTP"):
        McpGatewaySettings(
            environment="staging",
            api_base_url="http://poker.example.com",
        )

    with pytest.raises(ValidationError, match="configured together"):
        McpGatewaySettings(
            environment="staging",
            api_base_url="https://poker.example.com",
            cf_access_client_id="client-id",
        )


def test_mcp_settings_read_prefixed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POKER_MCP_ENVIRONMENT", "staging")
    monkeypatch.setenv("POKER_MCP_API_BASE_URL", "https://poker.example.com")
    monkeypatch.setenv("POKER_MCP_CF_ACCESS_CLIENT_ID", "client-id")
    monkeypatch.setenv("POKER_MCP_CF_ACCESS_CLIENT_SECRET", "client-secret")

    settings = McpGatewaySettings()

    assert settings.environment == "staging"
    assert settings.cf_access_client_secret is not None
    assert settings.cf_access_client_secret.get_secret_value() == "client-secret"


def test_server_exposes_only_environment_status() -> None:
    settings = McpGatewaySettings(
        environment="production",
        api_base_url="https://poker.example.com",
    )

    tools = run(build_mcp_server(settings).list_tools())

    assert {tool.name for tool in tools} == {"get_environment_status"}
    assert tools[0].annotations.readOnlyHint is True
    assert tools[0].annotations.destructiveHint is False


def test_gateway_refuses_backend_environment_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/health"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "environment": "production",
                "parser_provider": "ocr_cv",
            },
        )

    settings = McpGatewaySettings(
        environment="staging",
        api_base_url="https://poker.example.com",
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = PokerMcpGateway(
        settings,
        api_client=PokerApiClient(settings, client=http_client),
    )

    with pytest.raises(PokerApiError) as error:
        run(gateway.get_environment_status())

    assert error.value.detail == {
        "configured_environment": "staging",
        "backend_environment": "production",
    }
    run(http_client.aclose())


def test_environment_status_uses_only_the_public_health_route() -> None:
    captured_headers: dict[str, httpx.Headers] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers[request.url.path] = request.headers
        assert request.url.path == "/api/health"
        return httpx.Response(
            200,
            headers={"X-Request-ID": "request-123"},
            json={
                "status": "ok",
                "environment": "staging",
                "parser_provider": "ocr_cv",
            },
        )

    settings = McpGatewaySettings(
        environment="staging",
        api_base_url="https://poker.example.com",
        cf_access_client_id="access-id",
        cf_access_client_secret="access-secret",
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = PokerMcpGateway(
        settings,
        api_client=PokerApiClient(settings, client=http_client),
    )

    result = run(gateway.get_environment_status())

    assert result.health.status == "ok"
    headers = captured_headers["/api/health"]
    assert "Authorization" not in headers
    assert "X-Poker-Proxy-Secret" not in headers
    assert headers["CF-Access-Client-Id"] == "access-id"
    assert headers["CF-Access-Client-Secret"] == "access-secret"
    assert headers["X-Request-ID"]
    run(http_client.aclose())


def test_tool_error_bounds_backend_detail() -> None:
    error = PokerApiError(
        "Poker API request failed",
        environment="staging",
        status_code=422,
        detail="x" * 8_000,
    )

    payload = json.loads(error.tool_message())

    assert payload["detail"]["truncated"] is True
    assert len(payload["detail"]["preview"]) == 4_000
