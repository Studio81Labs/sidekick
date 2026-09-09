from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Self, TypeVar
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.benchmarks import BenchmarkOverview
from app.domain.poker import CanonicalState
from app.domain.hands import JobHistory, JobQueue, JobRecord
from app.mcp_access import MCP_PRINCIPAL_CONTEXT

McpEnvironment = Literal["staging", "production"]
JobId = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
ModelT = TypeVar("ModelT", bound=BaseModel)

PROXY_SHARED_SECRET_HEADER = "X-Poker-Proxy-Secret"
REQUEST_ID_HEADER = "X-Request-ID"


class McpGatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="POKER_MCP_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: McpEnvironment
    api_base_url: str = Field(min_length=1)
    allow_writes: bool = False
    request_timeout_seconds: float = Field(default=130.0, gt=0)
    api_bearer_token: SecretStr | None = None
    api_proxy_secret: SecretStr | None = None
    cf_access_client_id: SecretStr | None = None
    cf_access_client_secret: SecretStr | None = None

    @field_validator(
        "api_bearer_token",
        "api_proxy_secret",
        "cf_access_client_id",
        "cf_access_client_secret",
        mode="before",
    )
    @classmethod
    def normalize_optional_secret(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator(
        "api_bearer_token",
        "api_proxy_secret",
        "cf_access_client_id",
        "cf_access_client_secret",
    )
    @classmethod
    def validate_http_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return value
        secret = value.get_secret_value()
        if not secret.isascii() or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in secret
        ):
            raise ValueError(
                "MCP HTTP credentials must contain printable ASCII without whitespace"
            )
        return value

    @field_validator("api_proxy_secret")
    @classmethod
    def validate_proxy_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < 32:
            raise ValueError("api_proxy_secret must contain at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_gateway_target(self) -> Self:
        parsed_url = urlsplit(self.api_base_url)
        is_loopback_http = parsed_url.scheme.lower() == "http" and parsed_url.hostname in {
            "127.0.0.1",
            "::1",
            "localhost",
        }
        if parsed_url.scheme.lower() != "https" and not is_loopback_http:
            raise ValueError("api_base_url must use HTTPS or loopback HTTP")
        if (
            not parsed_url.hostname
            or parsed_url.username
            or parsed_url.password
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError(
                "api_base_url must be an absolute origin or base path without "
                "credentials, query, or fragment"
            )
        if is_loopback_http and any(
            credential is not None
            for credential in (
                self.api_bearer_token,
                self.api_proxy_secret,
                self.cf_access_client_id,
                self.cf_access_client_secret,
            )
        ):
            raise ValueError("MCP HTTP credentials require an HTTPS api_base_url")
        if (self.cf_access_client_id is None) != (self.cf_access_client_secret is None):
            raise ValueError(
                "cf_access_client_id and cf_access_client_secret must be configured together"
            )
        if self.environment == "production" and self.allow_writes:
            raise ValueError("production MCP gateways are read-only")
        self.api_base_url = self.api_base_url.rstrip("/")
        return self


class ApiHealth(BaseModel):
    status: Literal["ok"]
    environment: Literal["local", "staging", "production"]
    parser_provider: str


class EnvironmentStatus(BaseModel):
    environment: McpEnvironment
    write_enabled: bool
    api_base_url: str
    health: ApiHealth


class JobResult(BaseModel):
    environment: McpEnvironment
    job: JobRecord


class JobQueueResult(BaseModel):
    environment: McpEnvironment
    queue: JobQueue


class JobHistoryResult(BaseModel):
    environment: McpEnvironment
    history: JobHistory


class BenchmarkOverviewResult(BaseModel):
    environment: McpEnvironment
    benchmarks: BenchmarkOverview


class PokerApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        environment: McpEnvironment,
        status_code: int | None = None,
        detail: Any = None,
        request_id: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.environment = environment
        self.status_code = status_code
        self.detail = detail
        self.request_id = request_id
        self.retry_after_seconds = retry_after_seconds

    def tool_message(self) -> str:
        encoded_detail = json.dumps(self.detail, default=str, separators=(",", ":"))
        detail = self.detail
        if len(encoded_detail) > 4_000:
            detail = {
                "truncated": True,
                "preview": encoded_detail[:4_000],
            }
        return json.dumps(
            {
                "error": "poker_api_error",
                "environment": self.environment,
                "message": str(self),
                "status_code": self.status_code,
                "detail": detail,
                "request_id": self.request_id,
                "retry_after_seconds": self.retry_after_seconds,
            },
            separators=(",", ":"),
            default=str,
        )


class PokerApiClient:
    def __init__(
        self,
        settings: McpGatewaySettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def url_for(self, api_path: str) -> str:
        base_url = self.settings.api_base_url
        base_path = urlsplit(base_url).path.rstrip("/")
        proxied_path = api_path
        if base_path.endswith("/api") and proxied_path.startswith("/api/"):
            proxied_path = proxied_path[len("/api") :]
        return f"{base_url}{proxied_path}"

    def request_headers(
        self,
        extra: dict[str, str] | None = None,
        *,
        include_api_credentials: bool = True,
    ) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            REQUEST_ID_HEADER: str(uuid4()),
            "User-Agent": "poker-hero-mcp/0.1.0",
        }
        if include_api_credentials and self.settings.api_bearer_token is not None:
            headers["Authorization"] = (
                f"Bearer {self.settings.api_bearer_token.get_secret_value()}"
            )
        if include_api_credentials and self.settings.api_proxy_secret is not None:
            headers[PROXY_SHARED_SECRET_HEADER] = (
                self.settings.api_proxy_secret.get_secret_value()
            )
        if self.settings.cf_access_client_id is not None:
            assert self.settings.cf_access_client_secret is not None
            headers["CF-Access-Client-Id"] = (
                self.settings.cf_access_client_id.get_secret_value()
            )
            headers["CF-Access-Client-Secret"] = (
                self.settings.cf_access_client_secret.get_secret_value()
            )
        if extra:
            headers.update(extra)
        return headers

    async def health(self) -> ApiHealth:
        payload, response = await self._request_json(
            "GET",
            "/api/health",
            verify_environment=False,
            include_api_credentials=False,
        )
        health = self._validate_response(ApiHealth, payload, response)
        if health.environment != self.settings.environment:
            raise PokerApiError(
                "Configured MCP environment does not match the backend",
                environment=self.settings.environment,
                status_code=response.status_code,
                detail={
                    "configured_environment": self.settings.environment,
                    "backend_environment": health.environment,
                },
                request_id=response.headers.get(REQUEST_ID_HEADER),
            )
        return health

    async def ensure_environment(self) -> None:
        await self.health()

    async def get_model(
        self,
        model_type: type[ModelT],
        api_path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> ModelT:
        payload, response = await self._request_json("GET", api_path, params=params)
        return self._validate_response(model_type, payload, response)

    async def send_model(
        self,
        model_type: type[ModelT],
        method: Literal["POST", "PUT", "DELETE"],
        api_path: str,
        *,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> ModelT:
        payload, response = await self._request_json(
            method,
            api_path,
            json=json_body,
            headers=headers,
        )
        return self._validate_response(model_type, payload, response)

    async def _request_json(
        self,
        method: str,
        api_path: str,
        *,
        verify_environment: bool = True,
        include_api_credentials: bool = True,
        **kwargs: Any,
    ) -> tuple[Any, httpx.Response]:
        if verify_environment:
            await self.ensure_environment()
        supplied_headers = kwargs.pop("headers", None)
        try:
            response = await self._client.request(
                method,
                self.url_for(api_path),
                headers=self.request_headers(
                    supplied_headers,
                    include_api_credentials=include_api_credentials,
                ),
                **kwargs,
            )
        except httpx.RequestError as exc:
            raise self._network_error(exc) from exc
        return self._response_payload(response), response

    def _response_payload(self, response: httpx.Response) -> Any:
        try:
            payload = response.json()
        except ValueError as exc:
            raise PokerApiError(
                "Poker API returned a non-JSON response",
                environment=self.settings.environment,
                status_code=response.status_code,
                request_id=response.headers.get(REQUEST_ID_HEADER),
            ) from exc

        if response.is_error:
            retry_after = response.headers.get("Retry-After")
            raise PokerApiError(
                "Poker API request failed",
                environment=self.settings.environment,
                status_code=response.status_code,
                detail=payload.get("detail") if isinstance(payload, dict) else payload,
                request_id=response.headers.get(REQUEST_ID_HEADER),
                retry_after_seconds=(
                    int(retry_after)
                    if retry_after is not None and retry_after.isdigit()
                    else None
                ),
            )
        return payload

    def _validate_response(
        self,
        model_type: type[ModelT],
        payload: Any,
        response: httpx.Response,
    ) -> ModelT:
        try:
            return model_type.model_validate(payload)
        except ValidationError as exc:
            raise PokerApiError(
                "Poker API returned an invalid response contract",
                environment=self.settings.environment,
                status_code=response.status_code,
                detail={"model": model_type.__name__},
                request_id=response.headers.get(REQUEST_ID_HEADER),
            ) from exc

    def _network_error(self, exc: httpx.RequestError) -> PokerApiError:
        return PokerApiError(
            "Poker API is unreachable",
            environment=self.settings.environment,
            detail=type(exc).__name__,
        )


class PokerMcpGateway:
    def __init__(
        self,
        settings: McpGatewaySettings,
        *,
        api_client: PokerApiClient | None = None,
    ) -> None:
        self.settings = settings
        self.api = api_client or PokerApiClient(settings)

    async def get_environment_status(self) -> EnvironmentStatus:
        return EnvironmentStatus(
            environment=self.settings.environment,
            write_enabled=self.settings.allow_writes,
            api_base_url=self.settings.api_base_url,
            health=await self.api.health(),
        )

    async def list_processing_jobs(self, limit: int = 25, offset: int = 0) -> JobQueueResult:
        queue = await self.api.get_model(
            JobQueue,
            "/api/jobs",
            params={"limit": limit, "offset": offset},
        )
        return JobQueueResult(environment=self.settings.environment, queue=queue)

    async def get_job(self, job_id: JobId) -> JobResult:
        job = await self.api.get_model(JobRecord, f"/api/jobs/{job_id}")
        return JobResult(environment=self.settings.environment, job=job)

    async def search_history(
        self,
        query: str | None = None,
        limit: int = 24,
        offset: int = 0,
    ) -> JobHistoryResult:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if query is not None:
            params["query"] = query
        history = await self.api.get_model(JobHistory, "/api/history", params=params)
        return JobHistoryResult(environment=self.settings.environment, history=history)

    async def list_benchmarks(self) -> BenchmarkOverviewResult:
        benchmarks = await self.api.get_model(BenchmarkOverview, "/api/benchmarks")
        return BenchmarkOverviewResult(
            environment=self.settings.environment,
            benchmarks=benchmarks,
        )

    async def approve_hand_state(
        self,
        job_id: JobId,
        state: CanonicalState,
    ) -> JobResult:
        self._require_writes()
        approved_state = state.model_copy(update={"user_approved": True})
        job = await self.api.send_model(
            JobRecord,
            "POST",
            f"/api/jobs/{job_id}/approve",
            json_body=approved_state.model_dump(mode="json"),
        )
        return JobResult(environment=self.settings.environment, job=job)

    def _require_writes(self) -> None:
        if not self.settings.allow_writes:
            raise PermissionError(
                f"The {self.settings.environment} MCP gateway is read-only"
            )


def _tool_error(exc: Exception, environment: McpEnvironment) -> ToolError:
    if isinstance(exc, PokerApiError):
        return ToolError(exc.tool_message())
    return ToolError(
        json.dumps(
            {
                "error": "poker_mcp_error",
                "environment": environment,
                "message": str(exc),
            },
            separators=(",", ":"),
        )
    )


def build_mcp_server(
    settings: McpGatewaySettings,
    *,
    gateway: PokerMcpGateway | None = None,
    require_auth: bool = False,
    http_host: str = "127.0.0.1",
) -> FastMCP:
    active_gateway = gateway or PokerMcpGateway(settings)
    server = FastMCP(
        name=f"Poker Hero {settings.environment}",
        instructions=(
            "Use this server only to inspect the administrator OCR test queue, "
            "search approved hand history, read parser benchmark summaries, and "
            "approve reviewed hand state. "
            f"Every tool is permanently bound to {settings.environment}. "
            "Parser output is never ground truth until a reviewer approves it."
        ),
        json_response=True,
        stateless_http=require_auth,
        host=http_host,
    )
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )

    @server.tool(annotations=read_only)
    async def get_environment_status() -> EnvironmentStatus:
        """Verify the bound environment and report its active parser and solver."""
        try:
            _require_hosted_scope("read", require_auth=require_auth)
            return await active_gateway.get_environment_status()
        except Exception as exc:
            raise _tool_error(exc, settings.environment) from exc

    @server.tool(annotations=read_only)
    async def list_processing_jobs(
        limit: Annotated[int, Field(ge=1, le=100)] = 25,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> JobQueueResult:
        """List active post-hand analysis jobs in stable queue order."""
        try:
            _require_hosted_scope("read", require_auth=require_auth)
            return await active_gateway.list_processing_jobs(limit, offset)
        except Exception as exc:
            raise _tool_error(exc, settings.environment) from exc

    @server.tool(annotations=read_only)
    async def get_job(job_id: JobId) -> JobResult:
        """Read one persisted analysis job, including reviewable parser evidence."""
        try:
            _require_hosted_scope("read", require_auth=require_auth)
            return await active_gateway.get_job(job_id)
        except Exception as exc:
            raise _tool_error(exc, settings.environment) from exc

    @server.tool(annotations=read_only)
    async def search_history(
        query: Annotated[str | None, Field(max_length=100)] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 24,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> JobHistoryResult:
        """Search or page persisted post-hand review history."""
        try:
            _require_hosted_scope("read", require_auth=require_auth)
            return await active_gateway.search_history(query, limit, offset)
        except Exception as exc:
            raise _tool_error(exc, settings.environment) from exc

    @server.tool(annotations=read_only)
    async def list_benchmarks() -> BenchmarkOverviewResult:
        """Read parser benchmark coverage and recent report summaries."""
        try:
            _require_hosted_scope("read", require_auth=require_auth)
            return await active_gateway.list_benchmarks()
        except Exception as exc:
            raise _tool_error(exc, settings.environment) from exc

    if settings.allow_writes:
        replace_annotation = ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        )

        @server.tool(annotations=replace_annotation)
        async def approve_hand_state(
            job_id: JobId,
            state: CanonicalState,
        ) -> JobResult:
            """Save explicitly reviewed corrections as the job's approved state."""
            try:
                _require_hosted_scope("write", require_auth=require_auth)
                return await active_gateway.approve_hand_state(job_id, state)
            except Exception as exc:
                raise _tool_error(exc, settings.environment) from exc

    return server


def _require_hosted_scope(
    scope: Literal["read", "write"],
    *,
    require_auth: bool,
) -> None:
    if not require_auth:
        return
    principal = MCP_PRINCIPAL_CONTEXT.get()
    if principal is None or scope not in principal.scopes:
        raise PermissionError(f"The MCP credential does not grant {scope} access")


def main() -> None:
    settings = McpGatewaySettings()
    build_mcp_server(settings).run(transport="stdio")


if __name__ == "__main__":
    main()
