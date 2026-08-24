import asyncio
from contextlib import ExitStack, asynccontextmanager, suppress
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import logging
import math
from mimetypes import guess_type
import re
from secrets import compare_digest
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from PIL import Image, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.dependencies import (
    BACKGROUND_TASK_STATE_KEY,
    ApplicationBackupTransportError,
    BenchmarkConfigurationError,
    BenchmarkConflictError,
    BenchmarkDatasetInputError,
    BenchmarkInputError,
    BenchmarkTransportNotFoundError,
    JobMutationConflictError,
    JobRecommendationConfigurationError,
    JobRecommendationInputError,
    JobRecommendationProviderError,
    JobTransportNotFoundError,
    JobUploadConflictError,
    JobUploadInputError,
    JobUploadParserConfigurationError,
    JobUploadParserProviderError,
    JobUploadUnexpectedParserError,
)
from app.application.backups import ApplicationBackupExport, BackupService
from app.application.benchmarks import (
    BenchmarkDatasetExport,
    BenchmarkImportStatus,
    BenchmarkService,
)
from app.application.jobs import (
    JobHistoryService,
    JobImage,
    JobMutationService,
    JobQueryService,
    JobRecommendationService,
    JobUploadPipelineRequest,
    JobUploadRequest,
    JobUploadService,
)
from app.application.mcp_admin import McpAdminService
from app.application.training import TrainingProgressQuery, TrainingService
from app.application.system import SystemQueryService
from app.api.dependencies import PipelineCapabilitiesUnavailableError
from app.api.routers.backups import create_backups_router
from app.api.routers.benchmarks import create_benchmarks_router
from app.api.routers.health import create_health_router
from app.api.routers.history import create_history_router
from app.api.routers.jobs import (
    create_job_mutations_router,
    create_job_recommendation_router,
    create_job_upload_router,
    create_jobs_router,
)
from app.api.routers.mcp_admin import create_mcp_admin_router
from app.api.routers.pipeline import create_pipeline_router
from app.api.routers.training import create_training_router
from app.application_backup import (
    ApplicationBackupError,
    MAX_BACKUP_EXPANSION_RATIO,
    build_application_backup_archive,
    parse_application_backup_archive,
    restore_application_backup,
    stream_application_backup,
)
from app.benchmark_corpus import (
    benchmark_corpus_fingerprint,
    benchmark_jobs_for_layout,
    benchmark_layout_counts,
    benchmark_layout_profile,
)
from app.benchmarking import run_benchmark
from app.config import Settings, get_settings
from app.data_lock import InterprocessDataLock
from app.error_monitoring import (
    capture_unhandled_exception,
    configure_error_monitoring,
    route_template,
)
from app.dataset_export import (
    DatasetExportError,
    MAX_DATASET_CASES,
    MAX_DATASET_EXPANSION_RATIO,
    build_parser_dataset_archive,
    dataset_case_limit_message,
    stream_archive,
)
from app.dataset_import import (
    DatasetImportError,
    ParsedParserDataset,
    import_parser_dataset,
    parse_parser_dataset_archive,
)
from app.domain.pipeline import PipelineCapabilities, PipelineSelection
from app.domain.poker import CanonicalState, Street
from app.domain.recommendations import RecommendationRequest
from app.domain.hands import ArchiveJobsRequest, JobHistory, JobQueue, JobRecord, ScreenshotMetadataRequest
from app.domain.health import HealthResponse
from app.domain.backups import ApplicationBackupRestoreResult
from app.domain.training import (
    TrainingDecision,
    TrainingDecisionRequest,
    TrainingProgress,
    TrainingReviewOrder,
    TrainingReviewRequest,
)
from app.domain.benchmarks import (
    BenchmarkDatasetImportResult,
    BenchmarkOverview,
    BenchmarkParserPipelineSummary,
    BenchmarkReport,
    BenchmarkRunRequest,
    BenchmarkSelectionRequest,
)
from app.mcp_access import (
    CreateMcpPrincipalRequest,
    McpAccessConfig,
    McpIssuedPrincipal,
    McpPrincipalList,
    McpPrincipalStore,
    McpPrincipalSummary,
)
from app.mcp_http import HostedMcpRuntime, build_hosted_mcp_runtime
from app.parsers.base import ParserConfigurationError, ParserError
from app.parsers.registry import build_parser
from app.pipeline import (
    PipelineSelectionError,
    configured_recommendation_engine,
    parser_options_for_layout,
    pipeline_capabilities,
    resolve_pipeline_selection,
    settings_for_selection,
)
from app.providers.base import (
    ProviderConfigurationError,
    ProviderError,
    ProviderInputError,
    missing_required_fields,
)
from app.providers.registry import build_provider
from app.rate_limiting import (
    ApiRateLimiter,
    rate_limit_category,
    request_rate_limit_identity,
)
from app.storage.file_job_store import FileJobStore
from app.storage.persistence import (
    BenchmarkImportNotFoundError,
    BenchmarkNotFoundError,
    JobNotFoundError,
)
from app.training import (
    build_training_lessons_markdown,
    summarize_training,
    training_outcome,
)
from app.workspace import DEFAULT_JOB_LOCK_STRIPES, WorkspaceCoordinator

JOB_LOCK_STRIPES = DEFAULT_JOB_LOCK_STRIPES
SUPPORTED_IMAGE_FORMATS = {"PNG", "JPEG", "GIF", "WEBP"}
HISTORY_QUERY_TRANSLATION = str.maketrans({
    "♣": "c",
    "♦": "d",
    "♥": "h",
    "♠": "s",
    "\ufe0e": None,
    "\ufe0f": None,
})
HISTORY_PRESENTATION_SELECTOR_TRANSLATION = str.maketrans({
    "\ufe0e": None,
    "\ufe0f": None,
})
HISTORY_CARD_QUERY_TOKEN_PATTERN = re.compile(
    r"(?i:(?:[2-9tjqka]|10)[cdhs♣♦♥♠])",
)
HISTORY_LOWERCASE_FACE_CARD_QUERY_PATTERN = re.compile(r"[tjqka][cdhs]")
HISTORY_QUERY_SEPARATOR_PATTERN = re.compile(r"[,\s]+")
HISTORY_METADATA_CARD_CANDIDATE_PATTERN = re.compile(
    r"(?<!\w)[0-9A-Za-z♣♦♥♠]+(?!\w)",
)
PROXY_SHARED_SECRET_HEADER = "X-Poker-Proxy-Secret"
PROXY_AUTH_EXEMPT_PATHS = frozenset({"/api/health"})
REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ACCESS_LOG_HANDLER_NAME = "poker-json-access"
ERROR_MONITORING_CAPTURED_STATE_KEY = "poker_error_monitoring_captured"
ACCESS_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def _build_access_logger() -> logging.Logger:
    logger = logging.getLogger("poker.access")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not any(
        handler.get_name() == ACCESS_LOG_HANDLER_NAME
        for handler in logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.set_name(ACCESS_LOG_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger


LOGGER = _build_access_logger()


def _request_id(value: str | None) -> str:
    if value is not None and REQUEST_ID_PATTERN.fullmatch(value) is not None:
        return value
    return uuid4().hex


def _request_log_message(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    outcome: str,
    level: str,
) -> str:
    return json.dumps(
        {
            "duration_ms": round(duration_ms, 3),
            "event": "http_request",
            "level": level,
            "method": method,
            "outcome": outcome,
            "path": path,
            "request_id": request_id,
            "status_code": status_code,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _log_http_request(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    outcome: str,
    minimum_log_level: int,
) -> None:
    if outcome == "failed" or status_code >= 500:
        log_level = logging.ERROR
    elif status_code >= 400:
        log_level = logging.WARNING
    elif path == "/api/health":
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO
    if log_level < minimum_log_level:
        return
    message = _request_log_message(
        request_id=request_id,
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=duration_ms,
        outcome=outcome,
        level=logging.getLevelName(log_level).lower(),
    )
    LOGGER.log(log_level, message)


class RequestObservabilityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        access_log_level: int = logging.INFO,
        api_application: FastAPI | None = None,
    ) -> None:
        self.app = app
        self.access_log_level = access_log_level
        self.api_application = api_application

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_headers = Headers(scope=scope)
        request_id = _request_id(request_headers.get(REQUEST_ID_HEADER))
        scope.setdefault("state", {})["request_id"] = request_id
        method = scope.get("method", "")
        path = scope.get("path", "")
        started_at = perf_counter()
        status_code: int | None = None
        response_completed = False
        final_body_started = False
        client_disconnected = False
        access_event_logged = False
        request_body_consumed = False
        discard_unread_request_frames = False
        receive_lock = asyncio.Lock()
        receive_queue: asyncio.Queue[Message | Exception] = asyncio.Queue(
            maxsize=1
        )
        receive_task: asyncio.Task[None] | None = None

        async def pump_receive() -> None:
            nonlocal client_disconnected
            try:
                while True:
                    async with receive_lock:
                        message = await receive()
                    if message["type"] == "http.disconnect":
                        if not final_body_started:
                            client_disconnected = True
                        await receive_queue.put(message)
                        return
                    if (
                        discard_unread_request_frames
                        and message["type"] == "http.request"
                    ):
                        continue
                    # One message of read-ahead observes disconnects without
                    # buffering an upload body in memory.
                    await receive_queue.put(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await receive_queue.put(exc)

        def start_receive_task() -> None:
            nonlocal receive_task
            if receive_task is None:
                receive_task = asyncio.create_task(pump_receive())

        async def receive_observed() -> Message:
            nonlocal client_disconnected, request_body_consumed
            if receive_task is None:
                async with receive_lock:
                    message = await receive()
                if message["type"] == "http.disconnect":
                    if not final_body_started:
                        client_disconnected = True
                elif (
                    message["type"] == "http.request"
                    and not message.get("more_body", False)
                ):
                    request_body_consumed = True
                    start_receive_task()
                return message

            message = await receive_queue.get()
            if isinstance(message, Exception):
                raise message
            return message

        async def stop_receive_task() -> None:
            if receive_task is None:
                return
            receive_task.cancel()
            with suppress(asyncio.CancelledError):
                await receive_task

        def log_access_event(outcome: str) -> None:
            nonlocal access_event_logged
            if access_event_logged:
                return
            access_event_logged = True
            _log_http_request(
                request_id=request_id,
                method=method,
                path=path,
                status_code=(
                    status_code
                    if status_code is not None
                    else status.HTTP_500_INTERNAL_SERVER_ERROR
                ),
                duration_ms=(perf_counter() - started_at) * 1000,
                outcome=outcome,
                minimum_log_level=self.access_log_level,
            )

        async def send_observed(message: Message) -> None:
            nonlocal discard_unread_request_frames, final_body_started
            nonlocal response_completed, status_code
            message_type = message["type"]
            if message_type == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
                await send(message)
                status_code = message["status"]
                if status_code >= 200:
                    discard_unread_request_frames = not request_body_consumed
                    start_receive_task()
                    await asyncio.sleep(0)
                return

            is_final_body = (
                message_type == "http.response.body"
                and not message.get("more_body", False)
            ) or message_type == "http.response.pathsend"
            await send(message)
            if is_final_body:
                final_body_started = True
                response_completed = True
                if scope["state"].get(BACKGROUND_TASK_STATE_KEY, False):
                    await stop_receive_task()
                    log_access_event(
                        "failed" if client_disconnected else "completed"
                    )

        try:
            await self.app(scope, receive_observed, send_observed)
        except BaseException as exc:
            await stop_receive_task()
            log_access_event("failed")
            if (
                isinstance(exc, Exception)
                and not scope["state"].get(
                    ERROR_MONITORING_CAPTURED_STATE_KEY,
                    False,
                )
            ):
                scope["state"][ERROR_MONITORING_CAPTURED_STATE_KEY] = True
                capture_unhandled_exception(
                    exc,
                    request_id=request_id,
                    method=method,
                    route=route_template(scope),
                )
            raise

        await stop_receive_task()
        log_access_event(
            "completed"
            if response_completed and not client_disconnected
            else "failed"
        )


class PathCorsMiddleware:
    """Keep browser MCP origins from gaining CORS access to the admin API."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_origins: list[str],
        mcp_origins: list[str],
    ) -> None:
        self.app = app
        options: dict[str, Any] = {
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
            "expose_headers": [
                REQUEST_ID_HEADER,
                "Retry-After",
                "X-RateLimit-Limit",
                "X-RateLimit-Remaining",
            ],
        }
        self.api_app = CORSMiddleware(app, allow_origins=api_origins, **options)
        self.mcp_app = CORSMiddleware(app, allow_origins=mcp_origins, **options)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        target = self.mcp_app if scope.get("path") == "/mcp" else self.api_app
        await target(scope, receive, send)


class DataMutationLockMiddleware:
    """Coordinate API mutations with consistent cross-process snapshots."""

    MUTATING_METHODS = frozenset({"DELETE", "PATCH", "POST", "PUT"})
    MUTATING_GET_PATH_PREFIXES = ("/api/benchmarks/imports/",)

    def __init__(self, app: ASGIApp, data_lock: InterprocessDataLock) -> None:
        self.app = app
        self.data_lock = data_lock

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        path = scope.get("path", "")
        if path == "/mcp":
            await self.app(scope, receive, send)
            return
        mutating_get = method == "GET" and path.startswith(
            self.MUTATING_GET_PATH_PREFIXES
        )
        if method not in self.MUTATING_METHODS and not mutating_get:
            await self.app(scope, receive, send)
            return

        descriptor = await self.data_lock.acquire_async(
            exclusive=False,
        )
        try:
            await self.app(scope, receive, send)
        finally:
            self.data_lock.release(descriptor)


def _json_safe_validation_content(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {
            key: _json_safe_validation_content(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_json_safe_validation_content(item) for item in value]
    return value


def create_app(settings: Settings | None = None) -> RequestObservabilityMiddleware:
    active_settings = settings or get_settings()
    configure_error_monitoring(active_settings)
    workspace = WorkspaceCoordinator.open(
        active_settings.data_dir,
        job_lock_stripes=JOB_LOCK_STRIPES,
        job_lock_factory=Lock,
    )
    data_lock = workspace.data_lock
    store = workspace.jobs
    benchmark_store = workspace.benchmarks
    job_locks = workspace.job_locks
    history_lock = workspace.history_lock
    dataset_import_lock = workspace.dataset_import_lock
    benchmark_corpus_lock = workspace.benchmark_corpus_lock
    application_backup_lock = workspace.application_backup_lock
    rate_limiter = ApiRateLimiter(
        {
            "uploads": active_settings.api_rate_limit_uploads_per_minute,
            "recommendations": (
                active_settings.api_rate_limit_recommendations_per_minute
            ),
            "benchmarks": active_settings.api_rate_limit_benchmarks_per_minute,
            "data_transfers": (
                active_settings.api_rate_limit_data_transfers_per_minute
            ),
        }
    )
    mcp_principal_store = (
        McpPrincipalStore(
            active_settings.data_dir,
            active_settings.deployment_environment,
        )
        if active_settings.deployment_environment in {"staging", "production"}
        else None
    )
    hosted_mcp_runtime: HostedMcpRuntime | None = None

    def job_lock_index(job_id: str) -> int:
        return workspace.job_lock_index(job_id)

    def job_lock_for(job_id: str):
        return workspace.job_lock_for(job_id)

    def save_job(job: JobRecord) -> JobRecord:
        return workspace.save_job(job)

    def require_benchmark_corpus_ready() -> None:
        if benchmark_store.has_pending_import():
            raise BenchmarkConflictError(
                "A benchmark dataset import is still pending"
            )

    def ensure_benchmark_corpus_ready() -> None:
        try:
            require_benchmark_corpus_ready()
        except BenchmarkConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            ) from exc

    def current_recommendation_target(
        job_id: str,
        expected_state: CanonicalState,
        expected_request_id: str | None,
    ) -> JobRecord:
        try:
            current = store.get(job_id)
        except JobNotFoundError as exc:
            raise JobTransportNotFoundError("Job not found") from exc
        if current.approved_state != expected_state:
            raise JobMutationConflictError(
                "Approved state changed while the recommendation was running"
            )
        if current.recommendation_request_id != expected_request_id:
            raise JobMutationConflictError(
                "A newer recommendation request replaced this attempt"
            )
        return current

    def execute_pending_benchmark_import(
        request_id: str,
        dataset: ParsedParserDataset | None = None,
    ) -> BenchmarkDatasetImportResult:
        receipt = benchmark_store.get_import(request_id)
        if receipt.status == "completed" and receipt.result is not None:
            return receipt.result
        if receipt.status == "failed":
            raise DatasetImportError(receipt.error or "Dataset import failed")
        if dataset is None:
            archive_bytes = benchmark_store.get_import_archive(request_id)
            dataset = parse_parser_dataset_archive(
                archive_bytes,
                max_image_bytes=active_settings.max_upload_bytes,
                max_uncompressed_bytes=(
                    active_settings.max_dataset_upload_bytes
                    * MAX_DATASET_EXPANSION_RATIO
                ),
            )
        with workspace.hold_benchmark_import(
            case.job_id for case in dataset.cases
        ):
            result = import_parser_dataset(
                dataset,
                store,
                recommendation_provider=active_settings.recommendation_provider,
                recommendation_engine=configured_recommendation_engine(
                    active_settings
                ),
                default_layout_profile=active_settings.parser_layout_profile,
                max_archive_bytes=active_settings.max_dataset_upload_bytes,
                import_request_id=request_id,
            )
            benchmark_store.complete_import(request_id, result)
            return result

    def resume_benchmark_import(request_id: str) -> None:
        with dataset_import_lock:
            try:
                receipt = benchmark_store.get_import(request_id)
                if receipt.status != "pending":
                    return
                execute_pending_benchmark_import(request_id)
            except DatasetImportError as exc:
                benchmark_store.fail_import(
                    request_id,
                    str(exc),
                    exc.status_code,
                )
            except (BenchmarkImportNotFoundError, OSError):
                # A later poll can retry an interrupted or temporarily unavailable journal.
                return

    def resolve_upload_pipeline(
        request: JobUploadPipelineRequest,
    ) -> PipelineSelection:
        try:
            return resolve_pipeline_selection(
                active_settings,
                parser_provider=request.parser_provider,
                parser_layout_profile=request.parser_layout_profile,
                recommendation_provider=request.recommendation_provider,
                recommendation_engine=request.recommendation_engine,
            )
        except PipelineSelectionError as exc:
            raise JobUploadInputError(str(exc)) from exc

    def process_uploaded_image(request: JobUploadRequest) -> JobRecord:
        selection = request.selection
        image_bytes = request.image_bytes
        if not is_supported_image(image_bytes):
            raise JobUploadInputError("Upload must contain supported image data")
        with application_backup_lock:
            job = store.create_job(
                original_filename=request.original_filename,
                image_bytes=image_bytes,
                parser_provider=selection.parser_provider,
                parser_layout_profile=selection.parser_layout_profile,
                recommendation_provider=selection.recommendation_provider,
                recommendation_engine=selection.recommendation_engine,
                upload_request_id=request.upload_request_id,
            )
        with job_lock_for(job.id):
            try:
                job = store.get(job.id)
            except JobNotFoundError as exc:
                raise JobUploadConflictError(
                    "Upload was deleted before parsing started"
                ) from exc

        def save_parser_failure(message: str) -> JobRecord:
            with job_lock_for(job.id):
                try:
                    current = store.get(job.id)
                except JobNotFoundError as exc:
                    raise JobUploadConflictError(
                        "Upload was deleted while parsing"
                    ) from exc
                if current.approved_state is not None:
                    return current
                current.status = "error"
                current.error = message
                return save_job(current)

        try:
            parser = build_parser(settings_for_selection(active_settings, selection))
            parser_result = parser.parse(store.image_path(job))
        except ParserConfigurationError as exc:
            save_parser_failure(str(exc))
            raise JobUploadParserConfigurationError(str(exc)) from exc
        except ParserError as exc:
            save_parser_failure(str(exc))
            raise JobUploadParserProviderError(str(exc)) from exc
        except Exception as exc:
            error = f"Unexpected parser error: {exc}"
            save_parser_failure(error)
            raise JobUploadUnexpectedParserError(error) from exc

        with job_lock_for(job.id):
            try:
                current = store.get(job.id)
            except JobNotFoundError as exc:
                raise JobUploadConflictError(
                    "Upload was deleted while parsing"
                ) from exc
            current.parser_result = parser_result
            current.parser_auto_approval_eligible = meets_auto_approve_thresholds(
                parser_result.confidences,
                active_settings,
            )
            if current.approved_state is None:
                current.status = "parsed"
                if (
                    active_settings.parser_auto_approve_enabled
                    and current.parser_auto_approval_eligible
                    and not parser_result.warnings
                ):
                    current.approved_state = CanonicalState.from_parser_result(
                        parser_result
                    )
                    current.approved_state.user_approved = True
                    current.status = "approved"
            return save_job(current)

    def restore_uploaded_application_backup(
        archive_bytes: bytes,
    ) -> ApplicationBackupRestoreResult:
        try:
            backup = parse_application_backup_archive(
                archive_bytes,
                max_image_bytes=active_settings.max_upload_bytes,
                max_uncompressed_bytes=(
                    active_settings.max_backup_upload_bytes
                    * MAX_BACKUP_EXPANSION_RATIO
                ),
            )
            with workspace.hold_backup_transaction():
                ensure_benchmark_corpus_ready()
                if any(
                    job.status == "created" or job.recommendation_pending
                    for job in store.list()
                ):
                    raise ApplicationBackupTransportError(
                        (
                            "Wait for active parsing and recommendations "
                            "before restoring a backup"
                        ),
                        409,
                    )
                return restore_application_backup(
                    backup,
                    job_store=store,
                    benchmark_store=benchmark_store,
                )
        except ApplicationBackupError as exc:
            raise ApplicationBackupTransportError(
                str(exc),
                exc.status_code,
            ) from exc

    @asynccontextmanager
    async def app_lifespan(_app: FastAPI):
        if hosted_mcp_runtime is None:
            yield
            return
        async with hosted_mcp_runtime.lifespan():
            yield

    app = FastAPI(title="Poker Training Analyzer API", lifespan=app_lifespan)
    app.add_middleware(DataMutationLockMiddleware, data_lock=data_lock)

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None) or _request_id(None)
        request.scope["state"][ERROR_MONITORING_CAPTURED_STATE_KEY] = True
        capture_unhandled_exception(
            exc,
            request_id=request_id,
            method=request.method,
            route=route_template(request.scope),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal Server Error"},
            headers={REQUEST_ID_HEADER: request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        content = jsonable_encoder({"detail": exc.errors()})
        return JSONResponse(
            status_code=422,
            content=_json_safe_validation_content(content),
        )

    @app.middleware("http")
    async def require_proxy_shared_secret(request, call_next):
        configured_secret = active_settings.proxy_shared_secret
        if (
            configured_secret is not None
            and request.url.path.startswith("/api/")
            and request.url.path not in PROXY_AUTH_EXEMPT_PATHS
        ):
            supplied_secret = request.headers.get(PROXY_SHARED_SECRET_HEADER, "")
            if not compare_digest(
                supplied_secret,
                configured_secret.get_secret_value(),
            ):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Unauthorized"},
                )

        category = rate_limit_category(request.method, request.url.path)
        decision = None
        if active_settings.api_rate_limit_enabled and category is not None:
            decision = rate_limiter.check(
                category,
                request_rate_limit_identity(
                    request,
                    trust_proxy_headers=configured_secret is not None,
                ),
            )
            if not decision.allowed:
                retry_after = str(decision.retry_after_seconds)
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": f"Rate limit exceeded for {category.replace('_', ' ')}",
                        "retry_after_seconds": decision.retry_after_seconds,
                    },
                    headers={
                        "Retry-After": retry_after,
                        "X-RateLimit-Limit": str(decision.limit),
                        "X-RateLimit-Remaining": "0",
                    },
                )

        response = await call_next(request)
        if decision is not None:
            response.headers["X-RateLimit-Limit"] = str(decision.limit)
            response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return response

    def get_health() -> HealthResponse:
        configured_engine = configured_recommendation_engine(active_settings)
        return HealthResponse(
            status="ok",
            environment=active_settings.deployment_environment,
            parser_provider=active_settings.parser_provider,
            recommendation_provider=active_settings.recommendation_provider,
            recommendation_engine=(
                active_settings.recommendation_provider
                if configured_engine is None
                else configured_engine
            ),
        )

    def get_pipeline_capabilities() -> PipelineCapabilities:
        try:
            return pipeline_capabilities(active_settings)
        except PipelineSelectionError as exc:
            raise PipelineCapabilitiesUnavailableError(str(exc)) from exc

    def list_history(
        limit: int,
        offset: int,
        query: str | None,
    ) -> JobHistory:
        with history_lock:
            return build_job_history(store, limit, offset, query)

    def archive_jobs(request: ArchiveJobsRequest, limit: int) -> JobHistory:
        lock_indexes = sorted({job_lock_index(job_id) for job_id in request.job_ids})
        with ExitStack() as job_lock_stack:
            for lock_index in lock_indexes:
                job_lock_stack.enter_context(job_locks[lock_index])

            jobs = [load_job_or_404(store, job_id) for job_id in request.job_ids]
            if any(not is_history_ready(job) for job in jobs):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Only successful approved or recommended jobs "
                        "can be moved to history"
                    ),
                )

            with history_lock:
                archived_at = datetime.now(timezone.utc)
                for job in jobs:
                    if job.archived_at is None:
                        job.archived_at = archived_at
                        store.save(job)
                return build_job_history(store, limit)

    def get_mcp_access_config() -> McpAccessConfig:
        return McpAccessConfig(
            enabled=active_settings.mcp_enabled,
            environment=active_settings.deployment_environment,
            endpoint=(
                active_settings.mcp_public_url if active_settings.mcp_enabled else None
            ),
            writes_enabled=active_settings.mcp_allow_writes,
        )

    async def list_mcp_principals() -> McpPrincipalList:
        if mcp_principal_store is None:
            return McpPrincipalList(principals=[])
        principals = await run_in_threadpool(mcp_principal_store.list)
        return McpPrincipalList(principals=principals)

    async def create_mcp_principal(
        request: CreateMcpPrincipalRequest,
    ) -> McpIssuedPrincipal:
        store_for_mcp = require_mcp_principal_store(mcp_principal_store)
        if (
            active_settings.deployment_environment != "staging"
            and "write" in request.scopes
        ):
            raise HTTPException(
                status_code=400,
                detail="MCP write credentials can only be issued in staging",
            )
        return await run_in_threadpool(
            store_for_mcp.create,
            name=request.name,
            scopes=request.scopes,
            expires_at=request.expires_at,
        )

    async def rotate_mcp_principal(principal_id: str) -> McpIssuedPrincipal:
        store_for_mcp = require_mcp_principal_store(mcp_principal_store)
        return await run_in_threadpool(store_for_mcp.rotate, principal_id)

    async def revoke_mcp_principal(principal_id: str) -> McpPrincipalSummary:
        store_for_mcp = require_mcp_principal_store(mcp_principal_store)
        return await run_in_threadpool(store_for_mcp.revoke, principal_id)

    def training_job(job_id: str) -> JobRecord:
        try:
            return store.get(job_id)
        except JobNotFoundError as exc:
            raise KeyError("Job not found") from exc

    def complete_training_review(
        job_id: str,
        review: TrainingReviewRequest | None,
    ) -> JobRecord:
        with job_lock_for(job_id):
            job = training_job(job_id)
            if job.training_decision is None or job.recommendation is None:
                raise ValueError(
                    "A completed decision comparison is required before review"
                )
            if training_outcome(job) in {"match", "mixed"}:
                raise ValueError("Exact matches do not need review")
            changed = False
            if job.training_reviewed_at is None:
                job.training_reviewed_at = datetime.now(timezone.utc)
                changed = True
            if review is not None and job.training_review_note != review.note:
                job.training_review_note = review.note
                changed = True
            if changed:
                return save_job(job)
            return job

    def reopen_training_review(job_id: str) -> JobRecord:
        with job_lock_for(job_id):
            job = training_job(job_id)
            if job.training_decision is None or job.recommendation is None:
                raise ValueError(
                    "A completed decision comparison is required before reopening review"
                )
            if training_outcome(job) in {"match", "mixed"}:
                raise ValueError("Exact matches do not need review")
            if job.training_reviewed_at is not None:
                job.training_reviewed_at = None
                return save_job(job)
            return job

    def get_training_progress(query: TrainingProgressQuery) -> TrainingProgress:
        return summarize_training(
            store.list(),
            review_order=query.review_order,
            review_street=query.review_street,
            review_certainty=query.review_certainty,
            review_position=query.review_position,
            review_unpositioned=query.review_unpositioned,
            review_action_difference=query.review_action_difference,
            lesson_street=query.lesson_street,
            lesson_query=query.lesson_query,
            lesson_order=query.lesson_order,
            solver_fallback_key=query.solver_fallback_key,
            solver_route_key=query.solver_route_key,
            solver_unattributed=query.solver_unattributed,
            recent_street=query.recent_street,
            recent_position=query.recent_position,
            recent_unpositioned=query.recent_unpositioned,
            recent_certainty=query.recent_certainty,
        )

    def export_training_lessons(
        lesson_order: TrainingReviewOrder,
        lesson_street: Street | None,
        lesson_query: str | None,
    ) -> tuple[str, str]:
        document, lesson_count = build_training_lessons_markdown(
            store.list(),
            lesson_street=lesson_street,
            lesson_query=lesson_query,
            lesson_order=lesson_order,
        )
        if lesson_count == 0:
            raise ValueError("No saved lesson notes match the selected filters")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return document, f"poker-hero-lessons-{timestamp}.md"

    def list_processing_jobs(limit: int, offset: int) -> JobQueue:
        with history_lock:
            return build_job_queue(store, limit, offset)

    def get_processing_job(job_id: str) -> JobRecord:
        with job_lock_for(job_id):
            try:
                return store.get(job_id)
            except JobNotFoundError as exc:
                raise JobTransportNotFoundError("Job not found") from exc

    def get_processing_job_image(job_id: str) -> JobImage:
        with job_lock_for(job_id):
            try:
                job = store.get(job_id)
                image_path = store.image_path(job)
            except JobNotFoundError as exc:
                raise JobTransportNotFoundError("Job not found") from exc
            try:
                image_bytes = image_path.read_bytes()
            except FileNotFoundError as exc:
                raise JobTransportNotFoundError("Job image not found") from exc
            media_type = guess_type(image_path.name)[0] or "application/octet-stream"
        return JobImage(content=image_bytes, media_type=media_type)

    def update_processing_job_metadata(
        job_id: str,
        metadata: ScreenshotMetadataRequest,
    ) -> JobRecord:
        with job_lock_for(job_id):
            try:
                job = store.get(job_id)
            except JobNotFoundError as exc:
                raise JobTransportNotFoundError("Job not found") from exc
            job.title = metadata.title
            job.notes = metadata.notes
            job.tags = metadata.tags
            return save_job(job)

    def delete_processing_job(job_id: str) -> None:
        with benchmark_corpus_lock:
            if benchmark_store.has_pending_import():
                raise JobMutationConflictError(
                    "A benchmark dataset import is still pending"
                )
            with job_lock_for(job_id), history_lock:
                try:
                    store.get(job_id)
                    store.delete(job_id)
                except JobNotFoundError as exc:
                    raise JobTransportNotFoundError("Job not found") from exc

    def approve_processing_job(job_id: str, state: CanonicalState) -> JobRecord:
        with job_lock_for(job_id):
            try:
                job = store.get(job_id)
            except JobNotFoundError as exc:
                raise JobTransportNotFoundError("Job not found") from exc
            if job.recommendation_pending:
                raise JobMutationConflictError("Recommendation is already running")
            state.user_approved = True
            job.approved_state = state
            job.training_decision = None
            job.recommendation = None
            job.training_reviewed_at = None
            job.training_review_note = None
            job.status = "approved"
            job.error = None
            return save_job(job)

    def record_processing_training_decision(
        job_id: str,
        decision: TrainingDecisionRequest,
    ) -> JobRecord:
        with job_lock_for(job_id):
            try:
                job = store.get(job_id)
            except JobNotFoundError as exc:
                raise JobTransportNotFoundError("Job not found") from exc
            if job.approved_state is None or not job.approved_state.user_approved:
                raise JobMutationConflictError(
                    "Approve corrected state before recording your decision"
                )
            if job.recommendation is not None:
                raise JobMutationConflictError(
                    "Your decision must be recorded before revealing the recommendation"
                )

            job.training_decision = TrainingDecision(
                action=decision.action,
                sizing=decision.sizing,
                certainty=decision.certainty,
            )
            job.training_reviewed_at = None
            job.training_review_note = None
            job.status = "approved"
            job.error = None
            return save_job(job)

    def recommend_processing_job(
        job_id: str,
        recommendation_request_id: str | None,
    ) -> JobRecord:
        with job_lock_for(job_id):
            try:
                job = store.get(job_id)
            except JobNotFoundError as exc:
                raise JobTransportNotFoundError("Job not found") from exc
            if job.approved_state is None or not job.approved_state.user_approved:
                raise JobMutationConflictError(
                    "Approve corrected state before requesting recommendation"
                )
            if job.recommendation_pending:
                raise JobMutationConflictError("Recommendation is already running")
            approved_state = job.approved_state.model_copy(deep=True)
            job.recommendation_pending = True
            job.recommendation_request_id = recommendation_request_id
            job.error = None
            save_job(job)

        try:
            selection = resolve_pipeline_selection(
                active_settings,
                parser_provider=job.parser_provider,
                parser_layout_profile=(
                    job.parser_layout_profile
                    or active_settings.parser_layout_profile
                ),
                recommendation_provider=job.recommendation_provider,
                recommendation_engine=job.recommendation_engine,
                validate_parser=False,
                enforce_recommendation_allowlist=False,
            )
            provider = build_provider(settings_for_selection(active_settings, selection))
            missing = missing_required_fields(
                approved_state,
                provider.required_fields_for(approved_state),
            )
        except (PipelineSelectionError, ProviderConfigurationError) as exc:
            with job_lock_for(job_id):
                current = current_recommendation_target(
                    job_id,
                    approved_state,
                    recommendation_request_id,
                )
                current.recommendation_pending = False
                current.status = "error"
                current.error = str(exc)
                save_job(current)
            raise JobRecommendationConfigurationError(str(exc)) from exc
        except Exception as exc:
            with job_lock_for(job_id):
                current = current_recommendation_target(
                    job_id,
                    approved_state,
                    recommendation_request_id,
                )
                current.recommendation_pending = False
                current.status = "error"
                current.error = f"Unexpected provider error: {exc}"
                save_job(current)
            raise

        if missing:
            with job_lock_for(job_id):
                current = current_recommendation_target(
                    job_id,
                    approved_state,
                    recommendation_request_id,
                )
                current.recommendation_pending = False
                current.status = "approved"
                current.error = None
                save_job(current)
            raise JobRecommendationInputError({"missing_fields": missing})

        try:
            result = provider.recommend(
                RecommendationRequest(state=approved_state, provider=provider.name)
            )
        except ProviderInputError as exc:
            with job_lock_for(job_id):
                current = current_recommendation_target(
                    job_id,
                    approved_state,
                    recommendation_request_id,
                )
                current.recommendation_pending = False
                current.status = "approved"
                current.error = None
                save_job(current)
            raise JobRecommendationInputError(str(exc)) from exc
        except ProviderConfigurationError as exc:
            with job_lock_for(job_id):
                current = current_recommendation_target(
                    job_id,
                    approved_state,
                    recommendation_request_id,
                )
                current.recommendation_pending = False
                current.status = "error"
                current.error = str(exc)
                save_job(current)
            raise JobRecommendationConfigurationError(str(exc)) from exc
        except ProviderError as exc:
            with job_lock_for(job_id):
                current = current_recommendation_target(
                    job_id,
                    approved_state,
                    recommendation_request_id,
                )
                current.recommendation_pending = False
                current.status = "error"
                current.error = str(exc)
                save_job(current)
            raise JobRecommendationProviderError(str(exc)) from exc
        except Exception as exc:
            with job_lock_for(job_id):
                current = current_recommendation_target(
                    job_id,
                    approved_state,
                    recommendation_request_id,
                )
                current.recommendation_pending = False
                current.status = "error"
                current.error = f"Unexpected provider error: {exc}"
                save_job(current)
            raise

        with job_lock_for(job_id):
            current = current_recommendation_target(
                job_id,
                approved_state,
                recommendation_request_id,
            )
            current.recommendation = result
            current.recommendation_pending = False
            current.training_reviewed_at = None
            current.training_review_note = None
            current.status = "recommended"
            current.error = None
            return save_job(current)

    api_runtime = SystemQueryService(
        get_health=get_health,
        get_pipeline_capabilities=get_pipeline_capabilities,
    )
    history_runtime = JobHistoryService(
        list_history=list_history,
        archive_jobs=archive_jobs,
    )
    mcp_admin_runtime = McpAdminService(
        get_config=get_mcp_access_config,
        list_principals=list_mcp_principals,
        create_principal=create_mcp_principal,
        rotate_principal=rotate_mcp_principal,
        revoke_principal=revoke_mcp_principal,
    )
    training_runtime = TrainingService(
        complete_review=complete_training_review,
        reopen_review=reopen_training_review,
        get_progress=get_training_progress,
        export_lessons=export_training_lessons,
    )
    jobs_read_runtime = JobQueryService(
        list_jobs=list_processing_jobs,
        get_job=get_processing_job,
        get_image=get_processing_job_image,
    )
    jobs_mutation_runtime = JobMutationService(
        update_metadata=update_processing_job_metadata,
        delete_job=delete_processing_job,
        approve_job=approve_processing_job,
        record_training_decision=record_processing_training_decision,
    )
    jobs_recommendation_runtime = JobRecommendationService(
        recommend=recommend_processing_job,
    )
    jobs_upload_runtime = JobUploadService(
        max_upload_bytes=active_settings.max_upload_bytes,
        resolve_pipeline=resolve_upload_pipeline,
        process_upload=process_uploaded_image,
    )
    app.include_router(create_health_router(api_runtime))
    app.include_router(create_pipeline_router(api_runtime))
    app.include_router(create_mcp_admin_router(mcp_admin_runtime))
    app.include_router(create_training_router(training_runtime))

    app.include_router(create_history_router(history_runtime))
    app.include_router(create_jobs_router(jobs_read_runtime))
    app.include_router(create_job_upload_router(jobs_upload_runtime))
    app.include_router(create_job_mutations_router(jobs_mutation_runtime))
    app.include_router(create_job_recommendation_router(jobs_recommendation_runtime))

    def set_benchmark_inclusion(
        job_id: str,
        selection: BenchmarkSelectionRequest,
    ) -> JobRecord:
        with benchmark_corpus_lock, job_lock_for(job_id):
            require_benchmark_corpus_ready()
            try:
                job = store.get(job_id)
            except JobNotFoundError as exc:
                raise BenchmarkTransportNotFoundError("Job not found") from exc
            if selection.included and (
                job.approved_state is None or not job.approved_state.user_approved
            ):
                raise BenchmarkConflictError(
                    "Approve corrected state before adding it to the benchmark"
                )
            if selection.included and not job.benchmark_included:
                included_cases = sum(
                    candidate.benchmark_included for candidate in store.list()
                )
                if included_cases >= MAX_DATASET_CASES:
                    raise BenchmarkConflictError(
                        dataset_case_limit_message(MAX_DATASET_CASES)
                    )
                layout_profile = benchmark_layout_profile(
                    job,
                    active_settings.parser_layout_profile,
                )
                candidate_jobs = benchmark_jobs_for_layout(
                    store.list(),
                    layout_profile,
                    active_settings.parser_layout_profile,
                )
                candidate_jobs.append(job)
                try:
                    candidate_archive = build_parser_dataset_archive(
                        jobs=candidate_jobs,
                        image_path_for=store.image_path,
                        parser_provider=active_settings.parser_provider,
                        layout_profile=layout_profile,
                        max_archive_bytes=active_settings.max_dataset_upload_bytes,
                    )
                except DatasetExportError as exc:
                    raise BenchmarkConflictError(str(exc)) from exc
                candidate_archive.close()
            job.benchmark_included = selection.included
            return save_job(job)

    def get_benchmark_overview(
        parser_provider: str | None,
        parser_layout_profile: str | None,
    ) -> BenchmarkOverview:
        jobs = store.list()
        included_cases = sum(job.benchmark_included for job in jobs)
        selected_parser = active_settings.parser_provider
        selected_layout = active_settings.parser_layout_profile
        if parser_provider is not None or parser_layout_profile is not None:
            try:
                selection = resolve_pipeline_selection(
                    active_settings,
                    parser_provider=parser_provider,
                    parser_layout_profile=parser_layout_profile,
                    validate_recommendation=False,
                    validate_availability=False,
                )
            except PipelineSelectionError as exc:
                raise BenchmarkInputError(str(exc)) from exc
            selected_parser = selection.parser_provider
            selected_layout = selection.parser_layout_profile
        selected_jobs = benchmark_jobs_for_layout(
            jobs,
            selected_layout,
            active_settings.parser_layout_profile,
        )
        recent_reports = benchmark_store.list_summaries(
            parser_provider=selected_parser,
            layout_profile=selected_layout,
        )
        parser_pipelines: list[BenchmarkParserPipelineSummary] = []
        for parser_option in parser_options_for_layout(
            active_settings,
            selected_layout,
        ):
            parser_reports = (
                recent_reports[:1]
                if parser_option.id == selected_parser
                else benchmark_store.list_summaries(
                    limit=1,
                    parser_provider=parser_option.id,
                    layout_profile=selected_layout,
                )
            )
            latest_parser_report = parser_reports[0] if parser_reports else None
            previous_parser_report = (
                benchmark_store.find_previous_comparable_summary(
                    latest_parser_report,
                )
                if latest_parser_report is not None
                else None
            )
            parser_pipelines.append(BenchmarkParserPipelineSummary(
                parser=parser_option,
                layout_profile=selected_layout,
                latest_report=latest_parser_report,
                previous_report=previous_parser_report,
            ))
        return BenchmarkOverview(
            included_cases=included_cases,
            included_cases_by_layout=benchmark_layout_counts(
                jobs,
                active_settings.parser_layout_profile,
            ),
            corpus_fingerprint=benchmark_corpus_fingerprint(
                selected_jobs,
                store.image_path,
            ),
            default_layout_profile=active_settings.parser_layout_profile,
            latest_report=(
                benchmark_store.get(recent_reports[0].id)
                if recent_reports
                else None
            ),
            recent_reports=recent_reports,
            parser_pipelines=parser_pipelines,
        )

    def build_browser_application_backup():
        with workspace.hold_backup_transaction():
            ensure_benchmark_corpus_ready()
            try:
                return build_application_backup_archive(
                    jobs=store.list(),
                    benchmark_reports=benchmark_store.list(limit=None),
                    image_path_for=store.image_path,
                    max_archive_bytes=active_settings.max_backup_upload_bytes,
                    max_image_bytes=active_settings.max_upload_bytes,
                )
            except ApplicationBackupError as exc:
                raise ApplicationBackupTransportError(
                    str(exc),
                    exc.status_code,
                ) from exc

    async def export_application_backup() -> ApplicationBackupExport:
        descriptor = await data_lock.acquire_async(
            exclusive=True,
        )
        try:
            archive_file = await run_in_threadpool(
                build_browser_application_backup,
            )
        finally:
            data_lock.release(descriptor)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return ApplicationBackupExport(
            content=stream_application_backup(archive_file),
            filename=f"poker-hero-backup-{timestamp}.zip",
        )

    backups_runtime = BackupService(
        max_upload_bytes=active_settings.max_backup_upload_bytes,
        export_backup=export_application_backup,
        restore_backup=restore_uploaded_application_backup,
    )
    app.include_router(create_backups_router(backups_runtime))

    def export_benchmark_dataset(
        parser_provider: str | None,
        parser_layout_profile: str | None,
    ) -> BenchmarkDatasetExport:
        with benchmark_corpus_lock:
            require_benchmark_corpus_ready()
            export_settings = active_settings
            if parser_provider is not None or parser_layout_profile is not None:
                try:
                    selection = resolve_pipeline_selection(
                        active_settings,
                        parser_provider=parser_provider,
                        parser_layout_profile=parser_layout_profile,
                        validate_recommendation=False,
                        validate_availability=False,
                    )
                    export_settings = settings_for_selection(
                        active_settings,
                        selection,
                    )
                except PipelineSelectionError as exc:
                    raise BenchmarkInputError(str(exc)) from exc
            jobs = benchmark_jobs_for_layout(
                store.list(),
                export_settings.parser_layout_profile,
                active_settings.parser_layout_profile,
            )
            if not jobs:
                detail = (
                    "Add at least one approved hand to the benchmark"
                    if parser_provider is None and parser_layout_profile is None
                    else (
                        "Add at least one approved hand for layout "
                        f"'{export_settings.parser_layout_profile}' to the benchmark"
                    )
                )
                raise BenchmarkConflictError(detail)
            try:
                archive_file = build_parser_dataset_archive(
                    jobs=jobs,
                    image_path_for=store.image_path,
                    parser_provider=export_settings.parser_provider,
                    layout_profile=export_settings.parser_layout_profile,
                    max_archive_bytes=active_settings.max_dataset_upload_bytes,
                )
            except DatasetExportError as exc:
                raise BenchmarkConflictError(str(exc)) from exc

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return BenchmarkDatasetExport(
            content=stream_archive(archive_file),
            filename=f"poker-hero-parser-dataset-{timestamp}.zip",
        )

    def import_benchmark_dataset(
        archive_bytes: bytes,
        benchmark_import_request_id: str | None,
    ) -> BenchmarkDatasetImportResult:
        try:
            if benchmark_import_request_id is not None:
                with dataset_import_lock:
                    try:
                        receipt = benchmark_store.get_import(
                            benchmark_import_request_id,
                        )
                    except BenchmarkImportNotFoundError:
                        if benchmark_store.has_pending_import():
                            raise BenchmarkConflictError(
                                "A benchmark dataset import is still pending"
                            )
                        receipt = benchmark_store.begin_import(
                            benchmark_import_request_id,
                            archive_bytes,
                        )
                    if receipt.archive_sha256 != sha256(archive_bytes).hexdigest():
                        raise BenchmarkConflictError(
                            "Import request ID belongs to another dataset"
                        )
                    if receipt.status == "completed" and receipt.result is not None:
                        return receipt.result
                    if receipt.status == "failed":
                        raise BenchmarkDatasetInputError(
                            receipt.error or "Dataset import failed",
                            receipt.error_status or 409,
                        )
                    try:
                        return execute_pending_benchmark_import(
                            benchmark_import_request_id,
                        )
                    except DatasetImportError as exc:
                        benchmark_store.fail_import(
                            benchmark_import_request_id,
                            str(exc),
                            exc.status_code,
                        )
                        raise

            dataset = parse_parser_dataset_archive(
                archive_bytes,
                max_image_bytes=active_settings.max_upload_bytes,
                max_uncompressed_bytes=(
                    active_settings.max_dataset_upload_bytes
                    * MAX_DATASET_EXPANSION_RATIO
                ),
            )

            with workspace.hold_benchmark_import(
                case.job_id for case in dataset.cases
            ):
                require_benchmark_corpus_ready()
                return import_parser_dataset(
                    dataset,
                    store,
                    recommendation_provider=active_settings.recommendation_provider,
                    recommendation_engine=configured_recommendation_engine(
                        active_settings
                    ),
                    default_layout_profile=(
                        active_settings.parser_layout_profile
                    ),
                    max_archive_bytes=active_settings.max_dataset_upload_bytes,
                )
        except DatasetImportError as exc:
            raise BenchmarkDatasetInputError(str(exc), exc.status_code) from exc

    def get_benchmark_dataset_import(
        request_id: str,
    ) -> BenchmarkImportStatus:
        try:
            receipt = benchmark_store.get_import(request_id)
        except BenchmarkImportNotFoundError as exc:
            raise BenchmarkTransportNotFoundError(
                "Benchmark dataset import not found"
            ) from exc
        return BenchmarkImportStatus(
            receipt=receipt,
            should_resume=(
                receipt.status == "pending" and not dataset_import_lock.locked()
            ),
        )

    def get_benchmark_report(report_id: str) -> BenchmarkReport:
        try:
            return benchmark_store.get(report_id)
        except BenchmarkNotFoundError as exc:
            raise BenchmarkTransportNotFoundError(
                "Benchmark report not found"
            ) from exc

    def run_parser_benchmark(
        benchmark_request: BenchmarkRunRequest | None = None,
    ) -> BenchmarkReport:
        with benchmark_corpus_lock:
            require_benchmark_corpus_ready()
            try:
                benchmark_settings = active_settings
                if benchmark_request is not None:
                    selection = resolve_pipeline_selection(
                        active_settings,
                        parser_provider=benchmark_request.parser_provider,
                        parser_layout_profile=(
                            benchmark_request.parser_layout_profile
                        ),
                        validate_recommendation=False,
                    )
                    benchmark_settings = settings_for_selection(
                        active_settings,
                        selection,
                    )
                jobs = benchmark_jobs_for_layout(
                    store.list(),
                    benchmark_settings.parser_layout_profile,
                    active_settings.parser_layout_profile,
                )
                if not jobs:
                    detail = (
                        "Add at least one approved hand to the benchmark"
                        if benchmark_request is None
                        else (
                            "Add at least one approved hand for layout "
                            f"'{benchmark_settings.parser_layout_profile}' "
                            "to the benchmark"
                        )
                    )
                    raise BenchmarkConflictError(detail)
                parser = build_parser(benchmark_settings)
                report = run_benchmark(
                    jobs=jobs,
                    parser=parser,
                    image_path_for=store.image_path,
                    parser_provider=benchmark_settings.parser_provider,
                    layout_profile=benchmark_settings.parser_layout_profile,
                )
            except PipelineSelectionError as exc:
                raise BenchmarkInputError(str(exc)) from exc
            except ParserConfigurationError as exc:
                raise BenchmarkConfigurationError(str(exc)) from exc
            return benchmark_store.save(report)

    benchmarks_runtime = BenchmarkService(
        update_inclusion=set_benchmark_inclusion,
        get_overview=get_benchmark_overview,
        export_dataset=export_benchmark_dataset,
        max_dataset_upload_bytes=active_settings.max_dataset_upload_bytes,
        import_dataset=import_benchmark_dataset,
        get_import=get_benchmark_dataset_import,
        resume_import=resume_benchmark_import,
        get_report=get_benchmark_report,
        run=run_parser_benchmark,
    )
    app.include_router(create_benchmarks_router(benchmarks_runtime))

    if active_settings.mcp_enabled:
        assert mcp_principal_store is not None
        hosted_mcp_runtime = build_hosted_mcp_runtime(
            active_settings,
            api_app=RequestObservabilityMiddleware(
                app,
                access_log_level=ACCESS_LOG_LEVELS[
                    active_settings.access_log_level
                ],
            ),
            principal_store=mcp_principal_store,
        )
        app.mount("/", hosted_mcp_runtime.app, name="mcp")

    return RequestObservabilityMiddleware(
        PathCorsMiddleware(
            app,
            api_origins=active_settings.cors_origins,
            mcp_origins=(
                active_settings.mcp_allowed_origins
                if active_settings.mcp_enabled
                else []
            ),
        ),
        access_log_level=ACCESS_LOG_LEVELS[active_settings.access_log_level],
        api_application=app,
    )


def create_openapi_document(settings: Settings) -> dict[str, Any]:
    application = create_app(settings)
    if application.api_application is None:
        raise RuntimeError("Expected the API application to be available")
    return application.api_application.openapi()


def load_job_or_404(store: FileJobStore, job_id: str) -> JobRecord:
    try:
        return store.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


def require_mcp_principal_store(
    store: McpPrincipalStore | None,
) -> McpPrincipalStore:
    if store is None:
        raise HTTPException(
            status_code=409,
            detail="MCP principals are available only in staging or production",
        )
    return store


def is_history_ready(job: JobRecord) -> bool:
    if job.archived_at is not None:
        return True
    return (
        job.status != "error"
        and not job.recommendation_pending
        and (
            job.status in {"approved", "recommended"}
            or job.approved_state is not None
            or job.recommendation is not None
        )
    )


def is_pristine_benchmark_import(job: JobRecord) -> bool:
    return (
        job.benchmark_included
        and job.status == "approved"
        and not job.recommendation_pending
        and job.parser_result is None
        and job.approved_state is not None
        and job.training_decision is None
        and job.recommendation is None
        and job.recommendation_request_id is None
        and job.training_reviewed_at is None
        and job.training_review_note is None
        and job.error is None
    )


def build_job_queue(
    store: FileJobStore,
    limit: int,
    offset: int = 0,
) -> JobQueue:
    processing_jobs = sorted(
        (
            job
            for job in store.list()
            if job.archived_at is None
            and not is_pristine_benchmark_import(job)
        ),
        key=lambda job: (job.created_at, job.id),
    )
    return JobQueue(
        total=len(processing_jobs),
        jobs=processing_jobs[offset : offset + limit],
        snapshot_version=job_snapshot_version(processing_jobs),
    )


def build_job_history(
    store: FileJobStore,
    limit: int,
    offset: int = 0,
    query: str | None = None,
) -> JobHistory:
    archived_jobs = sorted(
        (job for job in store.list() if job.archived_at is not None),
        key=lambda job: (job.archived_at, job.created_at),
        reverse=True,
    )
    query_terms = history_query_terms(query)
    if query_terms:
        archived_jobs = [
            job
            for job in archived_jobs
            if history_matches_query(job, query_terms)
        ]
    elif query is not None and query.strip():
        archived_jobs = []
    return JobHistory(
        total=len(archived_jobs),
        jobs=archived_jobs[offset : offset + limit],
        snapshot_version=job_snapshot_version(archived_jobs),
    )


def job_snapshot_version(jobs: list[JobRecord]) -> str:
    digest = sha256()
    for job in jobs:
        digest.update(job.id.encode())
        digest.update(b"\0")
        digest.update(job.updated_at.isoformat().encode())
        digest.update(b"\0")
        digest.update((job.archived_at.isoformat() if job.archived_at else "").encode())
        digest.update(b"\n")
    return digest.hexdigest()


def normalize_history_query(value: str | None) -> str:
    return (value or "").translate(HISTORY_QUERY_TRANSLATION).casefold().strip()


def compact_history_card_terms(value: str) -> list[str] | None:
    matches = list(HISTORY_CARD_QUERY_TOKEN_PATTERN.finditer(value))
    if (
        not matches
        or matches[0].start() != 0
        or matches[-1].end() != len(value)
        or any(
            previous.end() != current.start()
            for previous, current in zip(matches, matches[1:])
        )
    ):
        return None
    return [normalize_history_query(match.group()) for match in matches]


def history_query_terms(value: str | None) -> list[tuple[str, bool]]:
    query_value = (value or "").translate(
        HISTORY_PRESENTATION_SELECTOR_TRANSLATION
    )
    raw_terms = [
        raw_term
        for raw_term in HISTORY_QUERY_SEPARATOR_PATTERN.split(query_value)
        if raw_term
    ]
    card_term_groups = [
        compact_history_card_terms(raw_term)
        for raw_term in raw_terms
    ]
    card_term_count = sum(
        len(card_terms)
        for card_terms in card_term_groups
        if card_terms is not None
    )
    terms: list[tuple[str, bool]] = []
    for raw_term, card_terms in zip(raw_terms, card_term_groups):
        lowercase_singleton_is_prose = (
            card_term_count == 1
            and HISTORY_LOWERCASE_FACE_CARD_QUERY_PATTERN.fullmatch(raw_term)
            is not None
        )
        if card_terms is not None and not lowercase_singleton_is_prose:
            terms.extend((card_term, True) for card_term in card_terms)
            continue
        normalized_term = normalize_history_query(raw_term)
        if not normalized_term:
            continue
        terms.append((normalized_term, False))
    return terms


def history_matches_query(
    job: JobRecord,
    query_terms: list[tuple[str, bool]],
) -> bool:
    search_text = history_search_text(job)
    card_tokens = history_card_tokens(job)
    metadata_card_tokens = history_metadata_card_tokens(job)
    return all(
        term in card_tokens or term in metadata_card_tokens
        if is_card
        else term in search_text
        for term, is_card in query_terms
    )


def history_card_tokens(job: JobRecord) -> set[str]:
    state = job.approved_state or (job.parser_result.state if job.parser_result else None)
    if state is None:
        return set()
    tokens = {card.code.casefold() for card in [*state.hero_cards, *state.board_cards]}
    add_history_ten_aliases(tokens)
    return tokens


def add_history_ten_aliases(tokens: set[str]) -> None:
    for token in tuple(tokens):
        if token.startswith("t"):
            tokens.add(f"10{token[1:]}")
        elif token.startswith("10"):
            tokens.add(f"t{token[2:]}")


def history_metadata_card_tokens(job: JobRecord) -> set[str]:
    tokens: set[str] = set()
    values = [job.title or "", job.notes or "", *job.tags]
    for value in values:
        normalized_value = value.translate(
            HISTORY_PRESENTATION_SELECTOR_TRANSLATION
        )
        for candidate in HISTORY_METADATA_CARD_CANDIDATE_PATTERN.findall(
            normalized_value
        ):
            card_terms = compact_history_card_terms(candidate)
            if card_terms is not None:
                tokens.update(card_terms)
    add_history_ten_aliases(tokens)
    return tokens


def history_search_text(job: JobRecord) -> str:
    state = job.approved_state or (job.parser_result.state if job.parser_result else None)
    values: list[str] = [
        job.original_filename,
        job.title or "",
        job.notes or "",
        *job.tags,
        job.status,
        job.parser_provider,
        job.recommendation_provider,
    ]
    if state is not None:
        values.extend(
            value
            for value in [
                state.street,
                state.hero_position,
                state.opponent_position,
                state.preflop_opener_position,
                state.facing_action,
                state.action_context,
            ]
            if value is not None
        )
        for card in [*state.hero_cards, *state.board_cards]:
            values.extend([card.code, card.rank, card.suit])
            if card.rank == "T":
                values.append(f"10{card.code[1:]}")
    if job.training_decision is not None:
        values.extend([
            job.training_decision.action,
            job.training_decision.certainty or "",
        ])
        if job.training_decision.sizing is not None:
            values.append(str(job.training_decision.sizing))
    if job.recommendation is not None:
        values.extend([
            job.recommendation.action,
            job.recommendation.explanation,
        ])
        if job.recommendation.sizing is not None:
            values.append(str(job.recommendation.sizing))
    if job.training_review_note:
        values.append(job.training_review_note)
    return normalize_history_query(" ".join(values))


def is_supported_image(image_bytes: bytes) -> bool:
    if not image_bytes:
        return False
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = image.format
            image.verify()
            return image_format in SUPPORTED_IMAGE_FORMATS
    except (
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        ValueError,
    ):
        return False


def meets_auto_approve_thresholds(
    confidences: dict[str, float],
    settings: Settings,
) -> bool:
    for field_name, threshold in settings.parser_auto_approve_thresholds.items():
        if confidences.get(field_name, 0) < threshold:
            return False
    return True
