from collections.abc import Callable
from datetime import datetime, timezone
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.api.dependencies import (
    ApiRuntime,
    HistoryRuntime,
    JobImage,
    JobMutationConflictError,
    JobRecommendationConfigurationError,
    JobRecommendationInputError,
    JobRecommendationProviderError,
    JobTransportNotFoundError,
    JobUploadConflictError,
    JobUploadInputError,
    JobUploadParserConfigurationError,
    JobUploadParserProviderError,
    JobUploadPipelineRequest,
    JobUploadRequest,
    JobUploadUnexpectedParserError,
    JobsMutationRuntime,
    JobsRecommendationRuntime,
    JobsReadRuntime,
    JobsUploadRuntime,
    McpAdminRuntime,
    TrainingProgressQuery,
    TrainingRuntime,
)
from app.api.dependencies import PipelineCapabilitiesUnavailableError
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
from app.mcp_access import (
    CreateMcpPrincipalRequest,
    McpAccessConfig,
    McpIssuedPrincipal,
    McpPrincipalList,
    McpPrincipalSummary,
)
from app.domain.hands import (
    ArchiveJobsRequest,
    JobHistory,
    JobQueue,
    JobRecord,
    ScreenshotMetadataRequest,
)
from app.domain.health import HealthResponse
from app.domain.pipeline import PipelineCapabilities, PipelineSelection
from app.domain.poker import CanonicalState
from app.domain.training import (
    TrainingDecisionRequest,
    TrainingProgress,
    TrainingReviewRequest,
)
from app.domain.training.aggregation import summarize_training
from app.application.admin_ocr_test import AdminOcrTestAccessPolicy
from api_test_support import ADMIN_OCR_TEST_HEADERS, ADMIN_OCR_TEST_TOKEN

ADMIN_OCR_TEST_POLICY = AdminOcrTestAccessPolicy.for_token(ADMIN_OCR_TEST_TOKEN)


def pipeline_capabilities() -> PipelineCapabilities:
    return PipelineCapabilities(
        defaults=PipelineSelection(
            parser_provider="ocr_cv",
            parser_layout_profile="fortuna",
            recommendation_provider="local_solver",
            recommendation_engine="local_solver",
        ),
        parser_providers=[],
        parser_layout_profiles=[],
        parser_layout_compatibility={},
        recommendation_providers=[],
        recommendation_engines=[],
    )


def health_response() -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment="local",
        parser_provider="ocr_cv",
        recommendation_provider="local_solver",
        recommendation_engine="local_solver",
    )


def job_history() -> JobHistory:
    return JobHistory(total=0, jobs=[], snapshot_version="history-snapshot")


def job_record() -> JobRecord:
    return JobRecord(
        id="a" * 32,
        original_filename="table.png",
        image_filename="table.png",
        parser_provider="ocr_cv",
        recommendation_provider="local_solver",
    )


def job_queue() -> JobQueue:
    return JobQueue(total=1, jobs=[job_record()], snapshot_version="queue-snapshot")


def job_image() -> JobImage:
    return JobImage(content=b"image bytes", media_type="image/png")


def default_jobs_read_runtime() -> JobsReadRuntime:
    return JobsReadRuntime(
        list_jobs=lambda _limit, _offset: job_queue(),
        get_job=lambda _job_id: job_record(),
        get_image=lambda _job_id: job_image(),
    )


def default_jobs_mutation_runtime() -> JobsMutationRuntime:
    return JobsMutationRuntime(
        update_metadata=lambda _job_id, _metadata: job_record(),
        delete_job=lambda _job_id: None,
        approve_job=lambda _job_id, _state: job_record(),
        record_training_decision=lambda _job_id, _decision: job_record(),
    )


def default_jobs_recommendation_runtime() -> JobsRecommendationRuntime:
    return JobsRecommendationRuntime(
        recommend=lambda _job_id, _request_id: job_record()
    )


def default_jobs_upload_runtime() -> JobsUploadRuntime:
    return JobsUploadRuntime(
        max_upload_bytes=1024,
        resolve_pipeline=lambda _request: PipelineSelection(
            parser_provider="ocr_cv",
            parser_layout_profile="fortuna",
            recommendation_provider="local_solver",
            recommendation_engine="local_solver",
        ),
        process_upload=lambda _request: job_record(),
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )


def training_progress(_query: TrainingProgressQuery) -> TrainingProgress:
    return summarize_training([])


def complete_training_review(
    _job_id: str,
    _review: TrainingReviewRequest | None,
) -> JobRecord:
    return job_record()


def reopen_training_review(_job_id: str) -> JobRecord:
    return job_record()


def export_training_lessons(
    _lesson_order: str,
    _lesson_street: str | None,
    _lesson_query: str | None,
) -> tuple[str, str]:
    return "# Poker Hero Lessons\n", "poker-hero-lessons-20260820T000000Z.md"


def default_training_runtime() -> TrainingRuntime:
    return TrainingRuntime(
        complete_review=complete_training_review,
        reopen_review=reopen_training_review,
        get_progress=training_progress,
        export_lessons=export_training_lessons,
    )


def mcp_config() -> McpAccessConfig:
    return McpAccessConfig(
        enabled=True,
        environment="staging",
        endpoint="https://poker.test/mcp",
        writes_enabled=True,
    )


def mcp_principal() -> McpPrincipalSummary:
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    return McpPrincipalSummary(
        id="mcp_" + "a" * 32,
        name="Codex test",
        environment="staging",
        token_prefix="tokenprefix1",
        scopes=["read"],
        status="active",
        created_at=now,
        updated_at=now,
    )


def issued_mcp_principal() -> McpIssuedPrincipal:
    return McpIssuedPrincipal(principal=mcp_principal(), token="phmcp_test")


async def list_mcp_principals() -> McpPrincipalList:
    return McpPrincipalList(principals=[mcp_principal()])


async def create_mcp_principal(
    _request: CreateMcpPrincipalRequest,
) -> McpIssuedPrincipal:
    return issued_mcp_principal()


async def rotate_mcp_principal(_principal_id: str) -> McpIssuedPrincipal:
    return issued_mcp_principal()


async def revoke_mcp_principal(_principal_id: str) -> McpPrincipalSummary:
    return mcp_principal()


def default_mcp_admin_runtime() -> McpAdminRuntime:
    return McpAdminRuntime(
        get_config=mcp_config,
        list_principals=list_mcp_principals,
        create_principal=create_mcp_principal,
        rotate_principal=rotate_mcp_principal,
        revoke_principal=revoke_mcp_principal,
    )


def make_client(
    *,
    get_health: Callable[[], HealthResponse] = health_response,
    get_pipeline_capabilities: Callable[[], PipelineCapabilities] = pipeline_capabilities,
    list_history: Callable[[int, int, str | None], JobHistory] = (
        lambda _limit, _offset, _query: job_history()
    ),
    archive_jobs: Callable[[ArchiveJobsRequest, int], JobHistory] = (
        lambda _request, _limit: job_history()
    ),
    mcp_admin_runtime: McpAdminRuntime | None = None,
    training_runtime: TrainingRuntime | None = None,
    jobs_read_runtime: JobsReadRuntime | None = None,
    jobs_mutation_runtime: JobsMutationRuntime | None = None,
    jobs_recommendation_runtime: JobsRecommendationRuntime | None = None,
    jobs_upload_runtime: JobsUploadRuntime | None = None,
) -> TestClient:
    runtime = ApiRuntime(
        get_health=get_health,
        get_pipeline_capabilities=get_pipeline_capabilities,
    )
    history_runtime = HistoryRuntime(
        list_history=list_history,
        archive_jobs=archive_jobs,
    )
    app = FastAPI()
    app.include_router(create_health_router(runtime))
    app.include_router(create_pipeline_router(runtime))
    app.include_router(create_history_router(history_runtime))
    app.include_router(
        create_mcp_admin_router(mcp_admin_runtime or default_mcp_admin_runtime())
    )
    app.include_router(
        create_training_router(training_runtime or default_training_runtime())
    )
    app.include_router(
        create_jobs_router(jobs_read_runtime or default_jobs_read_runtime())
    )
    app.include_router(
        create_job_mutations_router(
            jobs_mutation_runtime or default_jobs_mutation_runtime()
        )
    )
    app.include_router(
        create_job_recommendation_router(
            jobs_recommendation_runtime or default_jobs_recommendation_runtime()
        )
    )
    app.include_router(
        create_job_upload_router(jobs_upload_runtime or default_jobs_upload_runtime())
    )
    return TestClient(app)


def test_read_only_routers_use_injected_runtime_callables() -> None:
    calls: list[str] = []

    def get_health() -> HealthResponse:
        calls.append("health")
        return health_response()

    def get_pipeline_capabilities() -> PipelineCapabilities:
        calls.append("pipeline")
        return pipeline_capabilities()

    with make_client(
        get_health=get_health,
        get_pipeline_capabilities=get_pipeline_capabilities,
    ) as client:
        health = client.get("/api/health")
        pipeline = client.get("/api/pipeline")

    assert health.status_code == 200
    assert health.json()["environment"] == "local"
    assert pipeline.status_code == 200
    assert pipeline.json()["defaults"]["parser_layout_profile"] == "fortuna"
    assert calls == ["health", "pipeline"]


def test_history_router_forwards_defaults_and_explicit_parameters() -> None:
    calls: list[tuple[object, ...]] = []

    def list_history(limit: int, offset: int, query: str | None) -> JobHistory:
        calls.append(("list", limit, offset, query))
        return job_history()

    def archive_jobs(request: ArchiveJobsRequest, limit: int) -> JobHistory:
        calls.append(("archive", request.job_ids, limit))
        return job_history()

    with make_client(
        list_history=list_history,
        archive_jobs=archive_jobs,
    ) as client:
        default_list = client.get("/api/history")
        explicit_list = client.get(
            "/api/history",
            params={"limit": 7, "offset": 3, "query": "river"},
        )
        default_archive = client.put("/api/history", json={"job_ids": ["a"]})
        explicit_archive = client.put(
            "/api/history?limit=7",
            json={"job_ids": ["a", "b"]},
        )

    assert [response.status_code for response in (
        default_list,
        explicit_list,
        default_archive,
        explicit_archive,
    )] == [200, 200, 200, 200]
    assert default_list.json() == {
        "total": 0,
        "jobs": [],
        "snapshot_version": "history-snapshot",
    }
    assert calls == [
        ("list", 24, 0, None),
        ("list", 7, 3, "river"),
        ("archive", ["a"], 24),
        ("archive", ["a", "b"], 7),
    ]


def test_history_router_preserves_request_validation() -> None:
    with make_client() as client:
        invalid_limit = client.get("/api/history", params={"limit": 101})
        duplicate_job_ids = client.put("/api/history", json={"job_ids": ["a", "a"]})

    assert invalid_limit.status_code == 422
    assert duplicate_job_ids.status_code == 422


def test_history_router_preserves_callback_http_errors() -> None:
    def cannot_archive(_request: ArchiveJobsRequest, _limit: int) -> JobHistory:
        raise HTTPException(status_code=409, detail="History is not ready")

    with make_client(archive_jobs=cannot_archive) as client:
        response = client.put("/api/history", json={"job_ids": ["a"]})

    assert response.status_code == 409
    assert response.json() == {"detail": "History is not ready"}


def test_jobs_read_router_delegates_list_get_and_image() -> None:
    calls: list[tuple[object, ...]] = []

    def list_jobs(limit: int, offset: int) -> JobQueue:
        calls.append(("list", limit, offset))
        return job_queue()

    def get_job(job_id: str) -> JobRecord:
        calls.append(("get", job_id))
        return job_record()

    def get_image(job_id: str) -> JobImage:
        calls.append(("image", job_id))
        return JobImage(content=b"gif bytes", media_type="image/gif")

    runtime = JobsReadRuntime(
        list_jobs=list_jobs,
        get_job=get_job,
        get_image=get_image,
    )
    with make_client(jobs_read_runtime=runtime) as client:
        listed = client.get("/api/jobs", params={"limit": 7, "offset": 3})
        job = client.get("/api/jobs/job-1")
        image = client.get("/api/jobs/job-1/image")

    assert listed.status_code == 200
    assert listed.json()["snapshot_version"] == "queue-snapshot"
    assert job.status_code == 200
    assert job.json()["id"] == "a" * 32
    assert image.status_code == 200
    assert image.content == b"gif bytes"
    assert image.headers["content-type"] == "image/gif"
    assert calls == [
        ("list", 7, 3),
        ("get", "job-1"),
        ("image", "job-1"),
    ]


def test_jobs_read_router_validates_pagination_without_delegating() -> None:
    calls: list[tuple[int, int]] = []

    def list_jobs(limit: int, offset: int) -> JobQueue:
        calls.append((limit, offset))
        return job_queue()

    runtime = JobsReadRuntime(
        list_jobs=list_jobs,
        get_job=lambda _job_id: job_record(),
        get_image=lambda _job_id: job_image(),
    )
    with make_client(jobs_read_runtime=runtime) as client:
        invalid_limit = client.get("/api/jobs", params={"limit": 101})
        invalid_offset = client.get("/api/jobs", params={"offset": -1})

    assert [response.status_code for response in (invalid_limit, invalid_offset)] == [
        422,
        422,
    ]
    assert calls == []


def test_jobs_read_router_maps_not_found_details() -> None:
    def missing_job(_job_id: str) -> JobRecord:
        raise JobTransportNotFoundError("Job not found")

    def missing_image(_job_id: str) -> JobImage:
        raise JobTransportNotFoundError("Job image not found")

    def missing_image_job(_job_id: str) -> JobImage:
        raise JobTransportNotFoundError("Job not found")

    runtime = JobsReadRuntime(
        list_jobs=lambda _limit, _offset: job_queue(),
        get_job=missing_job,
        get_image=missing_image,
    )
    with make_client(jobs_read_runtime=runtime) as client:
        missing_job = client.get("/api/jobs/missing")
        missing_image = client.get("/api/jobs/missing/image")
    image_job_runtime = JobsReadRuntime(
        list_jobs=lambda _limit, _offset: job_queue(),
        get_job=lambda _job_id: job_record(),
        get_image=missing_image_job,
    )
    with make_client(jobs_read_runtime=image_job_runtime) as client:
        missing_image_job_response = client.get("/api/jobs/missing/image")

    assert (missing_job.status_code, missing_job.json()) == (
        404,
        {"detail": "Job not found"},
    )
    assert (missing_image.status_code, missing_image.json()) == (
        404,
        {"detail": "Job image not found"},
    )
    assert (
        missing_image_job_response.status_code,
        missing_image_job_response.json(),
    ) == (404, {"detail": "Job not found"})


def test_job_upload_router_delegates_defaults_and_all_form_values() -> None:
    pipeline_requests: list[JobUploadPipelineRequest] = []
    upload_requests: list[JobUploadRequest] = []
    selection = PipelineSelection(
        parser_provider="mock",
        parser_layout_profile="pokerstars",
        recommendation_provider="external",
        recommendation_engine="solver_v2",
    )

    def resolve_pipeline(request: JobUploadPipelineRequest) -> PipelineSelection:
        pipeline_requests.append(request)
        return selection

    def process_upload(request: JobUploadRequest) -> JobRecord:
        upload_requests.append(request)
        return job_record()

    runtime = JobsUploadRuntime(
        max_upload_bytes=1024,
        resolve_pipeline=resolve_pipeline,
        process_upload=process_upload,
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )
    with make_client(jobs_upload_runtime=runtime) as client:
        default_upload = client.post(
            "/api/jobs",
            content=(
                b"--upload-boundary\r\n"
                b'Content-Disposition: form-data; name="file"; filename=""\r\n'
                b"Content-Type: image/png\r\n\r\n"
                b"default image\r\n"
                b"--upload-boundary--\r\n"
            ),
            headers={
                "content-type": "multipart/form-data; boundary=upload-boundary",
                **ADMIN_OCR_TEST_HEADERS,
            },
        )
        configured_upload = client.post(
            "/api/jobs",
            files={"file": ("table.png", b"configured image", "image/png")},
            data={
                "upload_request_id": "upload-42",
                "parser_provider": "mock",
                "parser_layout_profile": "pokerstars",
                "recommendation_provider": "external",
                "recommendation_engine": "solver_v2",
            },
            headers=ADMIN_OCR_TEST_HEADERS,
        )

    assert [response.status_code for response in (default_upload, configured_upload)] == [
        201,
        201,
    ]
    assert pipeline_requests == [
        JobUploadPipelineRequest(None, None, None, None),
        JobUploadPipelineRequest("mock", "pokerstars", "external", "solver_v2"),
    ]
    assert upload_requests == [
        JobUploadRequest(
            original_filename="screenshot.png",
            image_bytes=b"default image",
            upload_request_id=None,
            selection=selection,
        ),
        JobUploadRequest(
            original_filename="table.png",
            image_bytes=b"configured image",
            upload_request_id="upload-42",
            selection=selection,
        ),
    ]


def test_job_upload_router_validates_each_form_field_without_delegating() -> None:
    calls: list[str] = []
    runtime = JobsUploadRuntime(
        max_upload_bytes=1024,
        resolve_pipeline=lambda _request: calls.append("pipeline") or PipelineSelection(
            parser_provider="ocr_cv",
            parser_layout_profile="fortuna",
            recommendation_provider="local_solver",
            recommendation_engine="local_solver",
        ),
        process_upload=lambda _request: calls.append("upload") or job_record(),
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )
    invalid_fields = [
        {"upload_request_id": "invalid request"},
        {"parser_provider": "invalid-provider"},
        {"parser_layout_profile": "invalid-profile"},
        {"recommendation_provider": "invalid-provider"},
        {"recommendation_engine": "invalid-engine"},
    ]

    with make_client(jobs_upload_runtime=runtime) as client:
        responses = [
            client.post(
                "/api/jobs",
                files={"file": ("table.png", b"image", "image/png")},
                data=data,
                headers=ADMIN_OCR_TEST_HEADERS,
            )
            for data in invalid_fields
        ]

    assert [response.status_code for response in responses] == [422] * len(invalid_fields)
    assert calls == []


def test_job_upload_router_rejects_oversize_before_processing() -> None:
    calls: list[str] = []
    runtime = JobsUploadRuntime(
        max_upload_bytes=3,
        resolve_pipeline=lambda _request: calls.append("pipeline") or PipelineSelection(
            parser_provider="ocr_cv",
            parser_layout_profile="fortuna",
            recommendation_provider="local_solver",
            recommendation_engine="local_solver",
        ),
        process_upload=lambda _request: calls.append("upload") or job_record(),
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )

    with make_client(jobs_upload_runtime=runtime) as client:
        response = client.post(
            "/api/jobs",
            files={"file": ("table.png", b"four", "image/png")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )

    assert (response.status_code, response.json()) == (
        413,
        {"detail": "Upload exceeds maximum size"},
    )
    assert calls == ["pipeline"]


def test_job_upload_router_maps_typed_errors() -> None:
    selection = PipelineSelection(
        parser_provider="ocr_cv",
        parser_layout_profile="fortuna",
        recommendation_provider="local_solver",
        recommendation_engine="local_solver",
    )

    def resolve_pipeline(request: JobUploadPipelineRequest) -> PipelineSelection:
        if request.parser_provider == "invalid":
            raise JobUploadInputError("Unknown parser provider: invalid")
        return selection

    def process_upload(request: JobUploadRequest) -> JobRecord:
        if request.original_filename == "invalid.png":
            raise JobUploadInputError("Upload must contain supported image data")
        if request.original_filename == "deleted.png":
            raise JobUploadConflictError("Upload was deleted while parsing")
        if request.original_filename == "configuration.png":
            raise JobUploadParserConfigurationError("Unknown parser provider: missing")
        if request.original_filename == "provider.png":
            raise JobUploadParserProviderError("parser exploded")
        raise JobUploadUnexpectedParserError("Unexpected parser error: parser crash")

    runtime = JobsUploadRuntime(
        max_upload_bytes=1024,
        resolve_pipeline=resolve_pipeline,
        process_upload=process_upload,
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )
    with make_client(jobs_upload_runtime=runtime) as client:
        selection_error = client.post(
            "/api/jobs",
            files={"file": ("table.png", b"image", "image/png")},
            data={"parser_provider": "invalid"},
            headers=ADMIN_OCR_TEST_HEADERS,
        )
        invalid_image = client.post(
            "/api/jobs",
            files={"file": ("invalid.png", b"image", "image/png")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )
        deleted = client.post(
            "/api/jobs",
            files={"file": ("deleted.png", b"image", "image/png")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )
        configuration = client.post(
            "/api/jobs",
            files={"file": ("configuration.png", b"image", "image/png")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )
        provider = client.post(
            "/api/jobs",
            files={"file": ("provider.png", b"image", "image/png")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )
        unexpected = client.post(
            "/api/jobs",
            files={"file": ("unexpected.png", b"image", "image/png")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )

    assert (selection_error.status_code, selection_error.json()) == (
        400,
        {"detail": "Unknown parser provider: invalid"},
    )
    assert (invalid_image.status_code, invalid_image.json()) == (
        400,
        {"detail": "Upload must contain supported image data"},
    )
    assert (deleted.status_code, deleted.json()) == (
        409,
        {"detail": "Upload was deleted while parsing"},
    )
    assert (configuration.status_code, configuration.json()) == (
        500,
        {"detail": "Parser configuration error: Unknown parser provider: missing"},
    )
    assert (provider.status_code, provider.json()) == (502, {"detail": "parser exploded"})
    assert (unexpected.status_code, unexpected.json()) == (
        500,
        {"detail": "Unexpected parser error: parser crash"},
    )


def test_jobs_mutation_router_delegates_validated_requests() -> None:
    calls: list[tuple[object, ...]] = []

    def update_metadata(
        job_id: str,
        metadata: ScreenshotMetadataRequest,
    ) -> JobRecord:
        calls.append(("metadata", job_id, metadata))
        return job_record()

    def delete_job(job_id: str) -> None:
        calls.append(("delete", job_id))

    def approve_job(job_id: str, state: CanonicalState) -> JobRecord:
        calls.append(("approve", job_id, state))
        return job_record()

    def record_training_decision(
        job_id: str,
        decision: TrainingDecisionRequest,
    ) -> JobRecord:
        calls.append(("decision", job_id, decision))
        return job_record()

    runtime = JobsMutationRuntime(
        update_metadata=update_metadata,
        delete_job=delete_job,
        approve_job=approve_job,
        record_training_decision=record_training_decision,
    )
    with make_client(jobs_mutation_runtime=runtime) as client:
        metadata = client.put(
            "/api/jobs/job-1/metadata",
            json={
                "title": "  Turn study  ",
                "notes": "  Check blockers.  ",
                "tags": [" Turn ", "study", "turn", ""],
            },
        )
        deleted = client.delete("/api/jobs/job-1")
        approved = client.post("/api/jobs/job-1/approve", json={})
        decision = client.put(
            "/api/jobs/job-1/decision",
            json={"action": "check", "certainty": "high"},
        )

    assert [response.status_code for response in (
        metadata,
        deleted,
        approved,
        decision,
    )] == [200, 204, 200, 200]
    assert deleted.content == b""
    assert calls[0] == (
        "metadata",
        "job-1",
        ScreenshotMetadataRequest(
            title="Turn study",
            notes="Check blockers.",
            tags=["Turn", "study"],
        ),
    )
    assert calls[1] == ("delete", "job-1")
    assert calls[2][0:2] == ("approve", "job-1")
    assert calls[3] == (
        "decision",
        "job-1",
        TrainingDecisionRequest(action="check", certainty="high"),
    )


def test_jobs_mutation_router_preserves_request_validation_without_delegating() -> None:
    calls: list[str] = []

    def update_metadata(
        _job_id: str,
        _metadata: ScreenshotMetadataRequest,
    ) -> JobRecord:
        calls.append("metadata")
        return job_record()

    def delete_job(_job_id: str) -> None:
        calls.append("delete")

    def approve_job(_job_id: str, _state: CanonicalState) -> JobRecord:
        calls.append("approve")
        return job_record()

    def record_training_decision(
        _job_id: str,
        _decision: TrainingDecisionRequest,
    ) -> JobRecord:
        calls.append("decision")
        return job_record()

    runtime = JobsMutationRuntime(
        update_metadata=update_metadata,
        delete_job=delete_job,
        approve_job=approve_job,
        record_training_decision=record_training_decision,
    )
    with make_client(jobs_mutation_runtime=runtime) as client:
        invalid_tags = client.put(
            "/api/jobs/job-1/metadata",
            json={"tags": ["turn,river"]},
        )
        invalid_state = client.post(
            "/api/jobs/job-1/approve",
            json={"hero_cards": ["Ah"]},
        )
        invalid_decision = client.put(
            "/api/jobs/job-1/decision",
            json={"action": "check", "sizing": 2},
        )

    assert [response.status_code for response in (
        invalid_tags,
        invalid_state,
        invalid_decision,
    )] == [422, 422, 422]
    assert calls == []


def test_jobs_mutation_router_maps_typed_errors() -> None:
    def missing_metadata(
        _job_id: str,
        _metadata: ScreenshotMetadataRequest,
    ) -> JobRecord:
        raise JobTransportNotFoundError("Job not found")

    def blocked_delete(_job_id: str) -> None:
        raise JobMutationConflictError("A benchmark dataset import is still pending")

    def blocked_approval(_job_id: str, _state: CanonicalState) -> JobRecord:
        raise JobMutationConflictError("Recommendation is already running")

    def missing_decision(
        _job_id: str,
        _decision: TrainingDecisionRequest,
    ) -> JobRecord:
        raise JobTransportNotFoundError("Job not found")

    runtime = JobsMutationRuntime(
        update_metadata=missing_metadata,
        delete_job=blocked_delete,
        approve_job=blocked_approval,
        record_training_decision=missing_decision,
    )
    with make_client(jobs_mutation_runtime=runtime) as client:
        missing_metadata_response = client.put("/api/jobs/missing/metadata", json={})
        pending_import = client.delete("/api/jobs/job-1")
        pending_recommendation = client.post("/api/jobs/job-1/approve", json={})
        missing_decision_response = client.put(
            "/api/jobs/missing/decision",
            json={"action": "fold"},
        )

    assert (missing_metadata_response.status_code, missing_metadata_response.json()) == (
        404,
        {"detail": "Job not found"},
    )
    assert (pending_import.status_code, pending_import.json()) == (
        409,
        {"detail": "A benchmark dataset import is still pending"},
    )
    assert (pending_recommendation.status_code, pending_recommendation.json()) == (
        409,
        {"detail": "Recommendation is already running"},
    )
    assert (missing_decision_response.status_code, missing_decision_response.json()) == (
        404,
        {"detail": "Job not found"},
    )


def test_job_recommendation_router_delegates_request_id() -> None:
    calls: list[tuple[str, str | None]] = []

    def recommend(job_id: str, request_id: str | None) -> JobRecord:
        calls.append((job_id, request_id))
        return job_record()

    runtime = JobsRecommendationRuntime(recommend=recommend)
    with make_client(jobs_recommendation_runtime=runtime) as client:
        default_request = client.post("/api/jobs/job-1/recommend")
        identified_request = client.post(
            "/api/jobs/job-2/recommend",
            headers={"X-Recommendation-Request-ID": "request-id_2"},
        )

    assert [response.status_code for response in (
        default_request,
        identified_request,
    )] == [200, 200]
    assert calls == [("job-1", None), ("job-2", "request-id_2")]


def test_job_recommendation_router_validates_header_without_delegating() -> None:
    calls: list[tuple[str, str | None]] = []

    def recommend(job_id: str, request_id: str | None) -> JobRecord:
        calls.append((job_id, request_id))
        return job_record()

    runtime = JobsRecommendationRuntime(recommend=recommend)
    with make_client(jobs_recommendation_runtime=runtime) as client:
        invalid_request_id = client.post(
            "/api/jobs/job-1/recommend",
            headers={"X-Recommendation-Request-ID": "invalid request id"},
        )
        oversized_request_id = client.post(
            "/api/jobs/job-1/recommend",
            headers={"X-Recommendation-Request-ID": "a" * 129},
        )

    assert [response.status_code for response in (
        invalid_request_id,
        oversized_request_id,
    )] == [422, 422]
    assert calls == []


def test_job_recommendation_router_maps_typed_errors() -> None:
    def recommend(job_id: str, _request_id: str | None) -> JobRecord:
        if job_id == "missing":
            raise JobTransportNotFoundError("Job not found")
        if job_id == "blocked":
            raise JobMutationConflictError("Recommendation is already running")
        if job_id == "missing-fields":
            raise JobRecommendationInputError({"missing_fields": ["hero_cards"]})
        if job_id == "invalid-input":
            raise JobRecommendationInputError("Add the missing table context")
        if job_id == "misconfigured":
            raise JobRecommendationConfigurationError("Provider is unavailable")
        raise JobRecommendationProviderError("provider exploded")

    runtime = JobsRecommendationRuntime(recommend=recommend)
    with make_client(jobs_recommendation_runtime=runtime) as client:
        missing = client.post("/api/jobs/missing/recommend")
        blocked = client.post("/api/jobs/blocked/recommend")
        missing_fields = client.post("/api/jobs/missing-fields/recommend")
        invalid_input = client.post("/api/jobs/invalid-input/recommend")
        misconfigured = client.post("/api/jobs/misconfigured/recommend")
        provider_failure = client.post("/api/jobs/provider-failure/recommend")

    assert (missing.status_code, missing.json()) == (404, {"detail": "Job not found"})
    assert (blocked.status_code, blocked.json()) == (
        409,
        {"detail": "Recommendation is already running"},
    )
    assert (missing_fields.status_code, missing_fields.json()) == (
        422,
        {"detail": {"missing_fields": ["hero_cards"]}},
    )
    assert (invalid_input.status_code, invalid_input.json()) == (
        422,
        {"detail": "Add the missing table context"},
    )
    assert (misconfigured.status_code, misconfigured.json()) == (
        500,
        {"detail": "Provider configuration error: Provider is unavailable"},
    )
    assert (provider_failure.status_code, provider_failure.json()) == (
        502,
        {"detail": "provider exploded"},
    )


def test_job_recommendation_router_propagates_unexpected_errors() -> None:
    def recommend(_job_id: str, _request_id: str | None) -> JobRecord:
        raise RuntimeError("provider implementation defect")

    runtime = JobsRecommendationRuntime(recommend=recommend)
    with make_client(jobs_recommendation_runtime=runtime) as client:
        with pytest.raises(RuntimeError, match="provider implementation defect"):
            client.post("/api/jobs/job-1/recommend")


def test_training_router_delegates_review_progress_and_lesson_export() -> None:
    calls: list[tuple[object, ...]] = []

    def complete_review(
        job_id: str,
        review: TrainingReviewRequest | None,
    ) -> JobRecord:
        calls.append(("complete", job_id, review.note if review else None))
        return job_record()

    def reopen_review(job_id: str) -> JobRecord:
        calls.append(("reopen", job_id))
        return job_record()

    def get_progress(query: TrainingProgressQuery) -> TrainingProgress:
        calls.append(("progress", query))
        return summarize_training([])

    def export_lessons(
        lesson_order: str,
        lesson_street: str | None,
        lesson_query: str | None,
    ) -> tuple[str, str]:
        calls.append(("export", lesson_order, lesson_street, lesson_query))
        return "# Poker Hero Lessons\n", "poker-hero-lessons-20260820T000000Z.md"

    runtime = TrainingRuntime(
        complete_review=complete_review,
        reopen_review=reopen_review,
        get_progress=get_progress,
        export_lessons=export_lessons,
    )
    with make_client(training_runtime=runtime) as client:
        completed = client.put(
            "/api/jobs/job-1/training-review",
            json={"note": "Review blockers"},
        )
        reopened = client.delete("/api/jobs/job-1/training-review")
        progress = client.get(
            "/api/training/progress?review_order=ev_loss&review_street=flop"
            "&review_certainty=high&review_position=button"
            "&review_decision_action=fold&review_recommended_action=call"
            "&lesson_order=ev_loss&lesson_street=turn&lesson_query=blockers"
            f"&solver_fallback_key={'a' * 64}"
        )
        exported = client.get(
            "/api/training/lessons/export?lesson_order=ev_loss"
            "&lesson_street=flop&lesson_query=blockers"
        )

    assert [response.status_code for response in (
        completed,
        reopened,
        progress,
        exported,
    )] == [200, 200, 200, 200]
    assert exported.text == "# Poker Hero Lessons\n"
    assert exported.headers["content-type"] == "text/markdown; charset=utf-8"
    assert exported.headers["content-disposition"] == (
        'attachment; filename="poker-hero-lessons-20260820T000000Z.md"'
    )
    assert calls == [
        ("complete", "job-1", "Review blockers"),
        ("reopen", "job-1"),
        (
            "progress",
            TrainingProgressQuery(
                review_order="ev_loss",
                review_street="flop",
                review_certainty="high",
                review_position="button",
                review_unpositioned=False,
                review_action_difference=("fold", "call"),
                lesson_order="ev_loss",
                lesson_street="turn",
                lesson_query="blockers",
                solver_fallback_key="a" * 64,
                solver_route_key=None,
                solver_unattributed=False,
                recent_street=None,
                recent_position=None,
                recent_unpositioned=False,
                recent_certainty=None,
            ),
        ),
        ("export", "ev_loss", "flop", "blockers"),
    ]


def test_training_router_preserves_query_validation_without_delegating() -> None:
    calls: list[tuple[object, ...]] = []

    def get_progress(query: TrainingProgressQuery) -> TrainingProgress:
        calls.append((query,))
        return summarize_training([])

    runtime = TrainingRuntime(
        complete_review=complete_training_review,
        reopen_review=reopen_training_review,
        get_progress=get_progress,
        export_lessons=export_training_lessons,
    )
    with make_client(training_runtime=runtime) as client:
        incomplete_difference = client.get(
            "/api/training/progress?review_decision_action=fold"
        )
        conflicting_filters = client.get(
            "/api/training/progress?recent_position=button"
            f"&solver_route_key={'b' * 64}"
        )
        invalid_position = client.get("/api/training/progress?review_position=%20")

    assert [response.status_code for response in (
        incomplete_difference,
        conflicting_filters,
        invalid_position,
    )] == [422, 422, 422]
    assert calls == []


def test_training_router_maps_review_and_lesson_export_errors() -> None:
    def missing_review(
        _job_id: str,
        _review: TrainingReviewRequest | None,
    ) -> JobRecord:
        raise KeyError("Job not found")

    def incomplete_reopen(_job_id: str) -> JobRecord:
        raise ValueError(
            "A completed decision comparison is required before reopening review"
        )

    def no_lessons(
        _lesson_order: str,
        _lesson_street: str | None,
        _lesson_query: str | None,
    ) -> tuple[str, str]:
        raise ValueError("No saved lesson notes match the selected filters")

    runtime = TrainingRuntime(
        complete_review=missing_review,
        reopen_review=incomplete_reopen,
        get_progress=training_progress,
        export_lessons=no_lessons,
    )
    with make_client(training_runtime=runtime) as client:
        missing = client.put("/api/jobs/missing/training-review")
        incomplete = client.delete("/api/jobs/job-1/training-review")
        empty_export = client.get("/api/training/lessons/export")

    assert (missing.status_code, missing.json()) == (404, {"detail": "Job not found"})
    assert (incomplete.status_code, incomplete.json()) == (
        409,
        {
            "detail": (
                "A completed decision comparison is required before reopening review"
            )
        },
    )
    assert (empty_export.status_code, empty_export.json()) == (
        409,
        {"detail": "No saved lesson notes match the selected filters"},
    )


def test_mcp_admin_router_forwards_requests_and_preserves_issued_token_cache_rules() -> None:
    calls: list[tuple[object, ...]] = []

    async def list_principals() -> McpPrincipalList:
        calls.append(("list",))
        return McpPrincipalList(principals=[mcp_principal()])

    async def create_principal(
        request: CreateMcpPrincipalRequest,
    ) -> McpIssuedPrincipal:
        calls.append(("create", request.name, request.scopes, request.expires_at))
        return issued_mcp_principal()

    async def rotate_principal(principal_id: str) -> McpIssuedPrincipal:
        calls.append(("rotate", principal_id))
        return issued_mcp_principal()

    async def revoke_principal(principal_id: str) -> McpPrincipalSummary:
        calls.append(("revoke", principal_id))
        return mcp_principal()

    runtime = McpAdminRuntime(
        get_config=mcp_config,
        list_principals=list_principals,
        create_principal=create_principal,
        rotate_principal=rotate_principal,
        revoke_principal=revoke_principal,
    )
    principal_id = mcp_principal().id
    with make_client(mcp_admin_runtime=runtime) as client:
        config = client.get("/api/mcp/config")
        listed = client.get("/api/mcp/principals")
        created = client.post(
            "/api/mcp/principals",
            json={"name": "Codex test", "scopes": ["read"], "expires_at": None},
        )
        rotated = client.post(f"/api/mcp/principals/{principal_id}/rotate")
        revoked = client.delete(f"/api/mcp/principals/{principal_id}")

    assert config.json() == {
        "enabled": True,
        "environment": "staging",
        "endpoint": "https://poker.test/mcp",
        "writes_enabled": True,
    }
    assert listed.json()["principals"][0]["id"] == principal_id
    assert [response.status_code for response in (created, rotated, revoked)] == [
        201,
        201,
        200,
    ]
    assert created.headers["cache-control"] == "no-store"
    assert rotated.headers["cache-control"] == "no-store"
    assert calls == [
        ("list",),
        ("create", "Codex test", ["read"], None),
        ("rotate", principal_id),
        ("revoke", principal_id),
    ]


def test_mcp_admin_router_maps_store_errors_without_changing_callback_policy() -> None:
    async def invalid_create(
        _request: CreateMcpPrincipalRequest,
    ) -> McpIssuedPrincipal:
        raise ValueError("invalid principal")

    async def missing_principal(_principal_id: str) -> McpIssuedPrincipal:
        raise KeyError("MCP principal not found")

    async def inactive_principal(_principal_id: str) -> McpIssuedPrincipal:
        raise ValueError("MCP principal is not active")

    async def missing_revoke(_principal_id: str) -> McpPrincipalSummary:
        raise KeyError("MCP principal not found")

    async def invalid_revoke(_principal_id: str) -> McpPrincipalSummary:
        raise ValueError("invalid principal id")

    with make_client(
        mcp_admin_runtime=McpAdminRuntime(
            get_config=mcp_config,
            list_principals=list_mcp_principals,
            create_principal=invalid_create,
            rotate_principal=missing_principal,
            revoke_principal=missing_revoke,
        )
    ) as client:
        create_error = client.post(
            "/api/mcp/principals",
            json={"name": "Codex test", "scopes": ["read"]},
        )
        rotate_missing = client.post("/api/mcp/principals/mcp_missing/rotate")
        revoke_missing = client.delete("/api/mcp/principals/mcp_missing")

    with make_client(
        mcp_admin_runtime=McpAdminRuntime(
            get_config=mcp_config,
            list_principals=list_mcp_principals,
            create_principal=create_mcp_principal,
            rotate_principal=inactive_principal,
            revoke_principal=invalid_revoke,
        )
    ) as client:
        rotate_inactive = client.post("/api/mcp/principals/mcp_inactive/rotate")
        revoke_invalid = client.delete("/api/mcp/principals/mcp_invalid")

    assert (create_error.status_code, create_error.json()) == (
        400,
        {"detail": "invalid principal"},
    )
    assert (rotate_missing.status_code, rotate_missing.json()) == (
        404,
        {"detail": "MCP principal not found"},
    )
    assert (rotate_inactive.status_code, rotate_inactive.json()) == (
        409,
        {"detail": "MCP principal is not active"},
    )
    assert (revoke_missing.status_code, revoke_missing.json()) == (
        404,
        {"detail": "MCP principal not found"},
    )
    assert (revoke_invalid.status_code, revoke_invalid.json()) == (
        400,
        {"detail": "invalid principal id"},
    )


def test_pipeline_router_preserves_configuration_error_contract() -> None:
    def invalid_pipeline() -> PipelineCapabilities:
        raise PipelineCapabilitiesUnavailableError("missing parser configuration")

    with make_client(get_pipeline_capabilities=invalid_pipeline) as client:
        response = client.get("/api/pipeline")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Pipeline configuration error: missing parser configuration"
    }


def test_router_composition_preserves_public_operation_ids() -> None:
    with make_client() as client:
        document = client.app.openapi()

    assert document["paths"]["/api/health"]["get"]["operationId"] == "health_get"
    assert document["paths"]["/api/history"]["get"]["operationId"] == "history_get"
    assert document["paths"]["/api/history"]["put"]["operationId"] == "history_archive"
    assert document["paths"]["/api/mcp/config"]["get"]["operationId"] == "mcp_config_get"
    assert (
        document["paths"]["/api/mcp/principals"]["get"]["operationId"]
        == "mcp_principals_list"
    )
    assert (
        document["paths"]["/api/mcp/principals"]["post"]["operationId"]
        == "mcp_principals_create"
    )
    assert (
        document["paths"]["/api/mcp/principals/{principal_id}/rotate"]["post"][
            "operationId"
        ]
        == "mcp_principal_rotate"
    )
    assert (
        document["paths"]["/api/mcp/principals/{principal_id}"]["delete"][
            "operationId"
        ]
        == "mcp_principal_revoke"
    )
    assert document["paths"]["/api/pipeline"]["get"]["operationId"] == "pipeline_get"
    assert document["paths"]["/api/jobs"]["get"]["operationId"] == "jobs_list"
    assert document["paths"]["/api/jobs"]["post"]["operationId"] == "jobs_create"
    assert document["paths"]["/api/jobs/{job_id}"]["get"]["operationId"] == "job_get"
    assert (
        document["paths"]["/api/jobs/{job_id}/metadata"]["put"]["operationId"]
        == "job_metadata_update"
    )
    assert (
        document["paths"]["/api/jobs/{job_id}"]["delete"]["operationId"]
        == "job_delete"
    )
    assert (
        document["paths"]["/api/jobs/{job_id}/approve"]["post"]["operationId"]
        == "job_approve"
    )
    assert (
        document["paths"]["/api/jobs/{job_id}/decision"]["put"]["operationId"]
        == "job_decision_record"
    )
    job_image_response = document["paths"]["/api/jobs/{job_id}/image"]["get"][
        "responses"
    ]["200"]
    assert (
        document["paths"]["/api/jobs/{job_id}/image"]["get"]["operationId"]
        == "job_image_get"
    )
    assert job_image_response["content"] == {
        "image/gif": {"schema": {"type": "string", "format": "binary"}},
        "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
        "image/png": {"schema": {"type": "string", "format": "binary"}},
        "image/webp": {"schema": {"type": "string", "format": "binary"}},
    }
    assert (
        document["paths"]["/api/jobs/{job_id}/training-review"]["put"][
            "operationId"
        ]
        == "job_training_review_complete"
    )
    assert (
        document["paths"]["/api/jobs/{job_id}/training-review"]["delete"][
            "operationId"
        ]
        == "job_training_review_reopen"
    )
    assert (
        document["paths"]["/api/training/progress"]["get"]["operationId"]
        == "training_progress_get"
    )
    assert (
        document["paths"]["/api/training/lessons/export"]["get"]["operationId"]
        == "training_lessons_export"
    )


def test_router_imports_do_not_initialize_the_legacy_bootstrap() -> None:
    program = """
import importlib
import sys

importlib.import_module('app.api.routers.health')
importlib.import_module('app.api.routers.backups')
importlib.import_module('app.api.routers.benchmarks')
importlib.import_module('app.api.routers.history')
importlib.import_module('app.api.routers.jobs')
importlib.import_module('app.api.routers.mcp_admin')
importlib.import_module('app.api.routers.pipeline')
importlib.import_module('app.api.routers.training')

for module_name in (
    'app.bootstrap',
    'app.storage',
    'app.parsers.registry',
    'app.providers.registry',
    'app.solvers.registry',
):
    assert module_name not in sys.modules, module_name
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
