import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.api import create_app
from app.config import Settings
from app.mcp_gateway import (
    McpGatewaySettings,
    PokerApiClient,
    PokerApiError,
    PokerMcpGateway,
    build_mcp_server,
)
from app.domain.poker import CanonicalState
from app.domain.training import TrainingDecisionRequest

VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
)


def run(coroutine):
    return asyncio.run(coroutine)


def make_gateway(
    tmp_path: Path,
    *,
    gateway_environment: str = "staging",
    backend_environment: str = "staging",
    allow_writes: bool = False,
) -> tuple[PokerMcpGateway, httpx.AsyncClient]:
    app = create_app(
        Settings(
            data_dir=tmp_path / "data",
            deployment_environment=backend_environment,
            parser_provider="mock",
            recommendation_provider="mock",
            api_rate_limit_enabled=False,
        )
    )
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://poker.test",
    )
    settings = McpGatewaySettings(
        environment=gateway_environment,
        api_base_url="http://127.0.0.1:8000",
        allow_writes=allow_writes,
        image_root=tmp_path,
    )
    api_client = PokerApiClient(settings, client=http_client)
    return PokerMcpGateway(settings, api_client=api_client), http_client


def test_mcp_settings_require_safe_fixed_targets(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="production MCP gateways are read-only"):
        McpGatewaySettings(
            environment="production",
            api_base_url="https://poker.example.com",
            allow_writes=True,
            image_root=tmp_path,
        )

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

    with pytest.raises(ValidationError, match="explicitly configured"):
        McpGatewaySettings(
            environment="staging",
            api_base_url="https://poker.example.com",
            allow_writes=True,
        )


def test_mcp_settings_read_prefixed_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POKER_MCP_ENVIRONMENT", "staging")
    monkeypatch.setenv("POKER_MCP_API_BASE_URL", "https://poker.example.com")
    monkeypatch.setenv("POKER_MCP_ALLOW_WRITES", "true")
    monkeypatch.setenv("POKER_MCP_IMAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("POKER_MCP_CF_ACCESS_CLIENT_ID", "client-id")
    monkeypatch.setenv("POKER_MCP_CF_ACCESS_CLIENT_SECRET", "client-secret")

    settings = McpGatewaySettings()

    assert settings.environment == "staging"
    assert settings.allow_writes is True
    assert settings.image_root == tmp_path.resolve()
    assert settings.cf_access_client_secret is not None
    assert settings.cf_access_client_secret.get_secret_value() == "client-secret"


def test_production_server_registers_only_read_tools(tmp_path: Path) -> None:
    settings = McpGatewaySettings(
        environment="production",
        api_base_url="https://poker.example.com",
        image_root=tmp_path,
    )

    tools = run(build_mcp_server(settings).list_tools())

    assert {tool.name for tool in tools} == {
        "get_environment_status",
        "list_processing_jobs",
        "get_job",
        "search_history",
        "get_training_progress",
        "list_benchmarks",
    }
    assert all(tool.annotations.readOnlyHint is True for tool in tools)


def test_staging_write_profile_registers_curated_mutations(tmp_path: Path) -> None:
    settings = McpGatewaySettings(
        environment="staging",
        api_base_url="https://poker.example.com",
        allow_writes=True,
        image_root=tmp_path,
    )

    tools = run(build_mcp_server(settings).list_tools())
    tools_by_name = {tool.name: tool for tool in tools}

    assert {
        "submit_screenshot",
        "approve_hand_state",
        "record_training_decision",
        "request_recommendation",
        "save_training_review",
    } <= tools_by_name.keys()
    assert tools_by_name["submit_screenshot"].annotations.destructiveHint is False
    assert tools_by_name["approve_hand_state"].annotations.destructiveHint is True


def test_gateway_refuses_backend_environment_mismatch(tmp_path: Path) -> None:
    gateway, http_client = make_gateway(
        tmp_path,
        gateway_environment="staging",
        backend_environment="production",
    )

    with pytest.raises(PokerApiError) as error:
        run(gateway.list_processing_jobs())

    assert error.value.detail == {
        "configured_environment": "staging",
        "backend_environment": "production",
    }
    run(http_client.aclose())


def test_api_client_rechecks_environment_before_every_operation() -> None:
    backend_environment = "staging"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/health"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "environment": backend_environment,
                "parser_provider": "ocr_cv",
                "recommendation_provider": "local_solver",
                "recommendation_engine": "postflop_solver",
            },
        )

    settings = McpGatewaySettings(
        environment="staging",
        api_base_url="https://poker.example.com",
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    api_client = PokerApiClient(settings, client=http_client)

    run(api_client.ensure_environment())
    backend_environment = "production"

    with pytest.raises(PokerApiError, match="does not match"):
        run(api_client.ensure_environment())

    run(http_client.aclose())


def test_api_client_withholds_api_credentials_until_identity_matches() -> None:
    captured_headers: dict[str, httpx.Headers] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers[request.url.path] = request.headers
        if request.url.path == "/api/health":
            return httpx.Response(
                200,
                headers={"X-Request-ID": "request-123"},
                json={
                    "status": "ok",
                    "environment": "staging",
                    "parser_provider": "ocr_cv",
                    "recommendation_provider": "local_solver",
                    "recommendation_engine": "postflop_solver",
                },
            )
        assert request.url.path == "/api/jobs"
        return httpx.Response(
            200,
            json={"total": 0, "jobs": [], "snapshot_version": "test-snapshot"},
        )

    settings = McpGatewaySettings(
        environment="staging",
        api_base_url="https://poker.example.com",
        api_bearer_token="bearer-token",
        api_proxy_secret="p" * 32,
        cf_access_client_id="access-id",
        cf_access_client_secret="access-secret",
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    api_client = PokerApiClient(settings, client=http_client)
    gateway = PokerMcpGateway(settings, api_client=api_client)

    result = run(gateway.list_processing_jobs())

    assert result.queue.total == 0
    health_headers = captured_headers["/api/health"]
    assert "Authorization" not in health_headers
    assert "X-Poker-Proxy-Secret" not in health_headers
    assert health_headers["CF-Access-Client-Id"] == "access-id"
    assert health_headers["CF-Access-Client-Secret"] == "access-secret"
    assert health_headers["X-Request-ID"]

    api_headers = captured_headers["/api/jobs"]
    assert api_headers["Authorization"] == "Bearer bearer-token"
    assert api_headers["X-Poker-Proxy-Secret"] == "p" * 32
    assert api_headers["CF-Access-Client-Id"] == "access-id"
    assert api_headers["CF-Access-Client-Secret"] == "access-secret"
    assert api_headers["X-Request-ID"]
    run(http_client.aclose())


def test_staging_gateway_completes_training_workflow(tmp_path: Path) -> None:
    image_path = tmp_path / "table.png"
    image_path.write_bytes(VALID_PNG)
    gateway, http_client = make_gateway(tmp_path, allow_writes=True)

    submitted = run(gateway.submit_screenshot(str(image_path), "mcp-upload-1"))
    assert submitted.environment == "staging"
    assert submitted.job.status == "parsed"
    assert submitted.job.upload_request_id == "mcp-upload-1"
    assert submitted.job.parser_result is not None

    queue = run(gateway.list_processing_jobs())
    assert queue.queue.total == 1
    assert queue.queue.jobs[0].id == submitted.job.id

    state = CanonicalState.model_validate(
        submitted.job.parser_result.state.model_dump(mode="json")
    )
    approved = run(gateway.approve_hand_state(submitted.job.id, state))
    assert approved.job.status == "approved"
    assert approved.job.approved_state is not None
    assert approved.job.approved_state.user_approved is True

    decision = run(
        gateway.record_training_decision(
            submitted.job.id,
            TrainingDecisionRequest(action="fold", certainty="high"),
        )
    )
    assert decision.job.training_decision is not None
    assert decision.job.training_decision.action == "fold"

    recommended = run(
        gateway.request_recommendation(
            submitted.job.id,
            "mcp-recommend-1",
        )
    )
    assert recommended.job.status == "recommended"
    assert recommended.job.recommendation is not None
    assert recommended.job.recommendation_request_id == "mcp-recommend-1"

    reviewed = run(gateway.save_training_review(submitted.job.id, "Review pot odds"))
    assert reviewed.job.training_reviewed_at is not None
    assert reviewed.job.training_review_note == "Review pot odds"

    progress = run(gateway.get_training_progress())
    assert progress.progress.reviewed_hands == 1
    assert progress.progress.needs_review_hands == 0
    benchmarks = run(gateway.list_benchmarks())
    assert benchmarks.benchmarks.included_cases == 0
    run(http_client.aclose())


def test_submit_screenshot_rejects_paths_outside_configured_root(tmp_path: Path) -> None:
    image_root = tmp_path / "allowed"
    image_root.mkdir()
    outside_path = tmp_path / "outside.png"
    outside_path.write_bytes(VALID_PNG)
    gateway, http_client = make_gateway(image_root, allow_writes=True)

    with pytest.raises(ValueError, match="POKER_MCP_IMAGE_ROOT"):
        run(gateway.submit_screenshot(str(outside_path)))

    run(http_client.aclose())


def test_api_error_preserves_retry_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "environment": "staging",
                    "parser_provider": "ocr_cv",
                    "recommendation_provider": "local_solver",
                    "recommendation_engine": "postflop_solver",
                },
            )
        return httpx.Response(
            429,
            headers={"Retry-After": "17", "X-Request-ID": "limited-request"},
            json={"detail": "Rate limit exceeded"},
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
        run(gateway.list_processing_jobs())

    assert error.value.status_code == 429
    assert error.value.retry_after_seconds == 17
    assert error.value.request_id == "limited-request"
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
