"""Processing job transport endpoints."""

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import (
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
)
from app.api.response_contracts import SUPPORTED_IMAGE_RESPONSE_CONTENT
from app.domain.poker import CanonicalState
from app.models import (
    JobQueue,
    JobRecord,
    ScreenshotMetadataRequest,
    TrainingDecisionRequest,
)


def create_jobs_router(runtime: JobsReadRuntime) -> APIRouter:
    """Build the processing job read router with application dependencies."""

    router = APIRouter()

    @router.get("/api/jobs", operation_id="jobs_list", response_model=JobQueue)
    def get_processing_jobs(
        limit: int = Query(default=100, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> JobQueue:
        return runtime.list_jobs(limit, offset)

    @router.get(
        "/api/jobs/{job_id}",
        operation_id="job_get",
        response_model=JobRecord,
    )
    def get_job(job_id: str) -> JobRecord:
        try:
            return runtime.get_job(job_id)
        except JobTransportNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get(
        "/api/jobs/{job_id}/image",
        operation_id="job_image_get",
        response_class=Response,
        responses={"200": {"content": SUPPORTED_IMAGE_RESPONSE_CONTENT}},
    )
    def get_job_image(job_id: str) -> Response:
        try:
            image = runtime.get_image(job_id)
        except JobTransportNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(content=image.content, media_type=image.media_type)

    return router


def create_job_upload_router(runtime: JobsUploadRuntime) -> APIRouter:
    """Build the multipart processing-job upload router."""

    router = APIRouter()

    @router.post(
        "/api/jobs",
        operation_id="jobs_create",
        response_model=JobRecord,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_job(
        file: UploadFile = File(...),
        upload_request_id: str | None = Form(
            default=None,
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
        parser_provider: str | None = Form(
            default=None,
            min_length=1,
            max_length=64,
            pattern=r"^[a-z0-9_]+$",
        ),
        parser_layout_profile: str | None = Form(
            default=None,
            min_length=1,
            max_length=64,
            pattern=r"^[a-z0-9_]+$",
        ),
        recommendation_provider: str | None = Form(
            default=None,
            min_length=1,
            max_length=64,
            pattern=r"^[a-z0-9_]+$",
        ),
        recommendation_engine: str | None = Form(
            default=None,
            min_length=1,
            max_length=64,
            pattern=r"^[a-z0-9_]+$",
        ),
    ) -> JobRecord:
        pipeline_request = JobUploadPipelineRequest(
            parser_provider=parser_provider,
            parser_layout_profile=parser_layout_profile,
            recommendation_provider=recommendation_provider,
            recommendation_engine=recommendation_engine,
        )
        try:
            selection = runtime.resolve_pipeline(pipeline_request)
        except JobUploadInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        image_bytes = await file.read(runtime.max_upload_bytes + 1)
        if len(image_bytes) > runtime.max_upload_bytes:
            raise HTTPException(status_code=413, detail="Upload exceeds maximum size")

        request = JobUploadRequest(
            original_filename=file.filename or "screenshot.png",
            image_bytes=image_bytes,
            upload_request_id=upload_request_id,
            selection=selection,
        )
        try:
            return await run_in_threadpool(runtime.process_upload, request)
        except JobUploadInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except JobUploadConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except JobUploadParserConfigurationError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Parser configuration error: {exc}",
            ) from exc
        except JobUploadParserProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except JobUploadUnexpectedParserError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router


def create_job_mutations_router(runtime: JobsMutationRuntime) -> APIRouter:
    """Build the processing job mutation router with application dependencies."""

    router = APIRouter()

    @router.put(
        "/api/jobs/{job_id}/metadata",
        operation_id="job_metadata_update",
        response_model=JobRecord,
    )
    def update_job_metadata(
        job_id: str,
        metadata: ScreenshotMetadataRequest,
    ) -> JobRecord:
        try:
            return runtime.update_metadata(job_id, metadata)
        except JobTransportNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete(
        "/api/jobs/{job_id}",
        operation_id="job_delete",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    def delete_job(job_id: str) -> Response:
        try:
            runtime.delete_job(job_id)
        except JobTransportNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except JobMutationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/api/jobs/{job_id}/approve",
        operation_id="job_approve",
        response_model=JobRecord,
    )
    def approve_job(job_id: str, state: CanonicalState) -> JobRecord:
        try:
            return runtime.approve_job(job_id, state)
        except JobTransportNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except JobMutationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.put(
        "/api/jobs/{job_id}/decision",
        operation_id="job_decision_record",
        response_model=JobRecord,
    )
    def record_training_decision(
        job_id: str,
        decision: TrainingDecisionRequest,
    ) -> JobRecord:
        try:
            return runtime.record_training_decision(job_id, decision)
        except JobTransportNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except JobMutationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return router


def create_job_recommendation_router(
    runtime: JobsRecommendationRuntime,
) -> APIRouter:
    """Build the processing job recommendation router with application dependencies."""

    router = APIRouter()

    @router.post(
        "/api/jobs/{job_id}/recommend",
        operation_id="job_recommend",
        response_model=JobRecord,
    )
    def recommend(
        job_id: str,
        recommendation_request_id: str | None = Header(
            default=None,
            alias="X-Recommendation-Request-ID",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ) -> JobRecord:
        try:
            return runtime.recommend(job_id, recommendation_request_id)
        except JobTransportNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except JobMutationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except JobRecommendationInputError as exc:
            raise HTTPException(status_code=422, detail=exc.detail) from exc
        except JobRecommendationConfigurationError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Provider configuration error: {exc}",
            ) from exc
        except JobRecommendationProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return router
