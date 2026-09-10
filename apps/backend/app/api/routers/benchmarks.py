"""Parser benchmark transport endpoints."""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.application.benchmarks import BenchmarkService
from app.api.administrative_access import administrator_access_router
from app.api.dependencies import (
    BACKGROUND_TASK_STATE_KEY,
    BenchmarkConfigurationError,
    BenchmarkConflictError,
    BenchmarkDatasetInputError,
    BenchmarkInputError,
    BenchmarkTransportNotFoundError,
)
from app.api.response_contracts import ZIP_RESPONSE_CONTENT
from app.domain.benchmarks import (
    BENCHMARK_IMPORT_REQUEST_ID_PATTERN,
    BenchmarkDatasetImportReceipt,
    BenchmarkDatasetImportResult,
    BenchmarkOverview,
    BenchmarkReport,
    BenchmarkRunRequest,
    BenchmarkSelectionRequest,
)
from app.domain.hands import JobRecord


def create_benchmarks_router(runtime: BenchmarkService) -> APIRouter:
    """Build the parser benchmark router with application-owned operations."""

    router = administrator_access_router(runtime.authorize_administrator)

    @router.put(
        "/api/admin/ocr/jobs/{job_id}/benchmark",
        operation_id="admin_ocr_job_benchmark_update",
        response_model=JobRecord,
    )
    def set_benchmark_inclusion(
        job_id: str,
        selection: BenchmarkSelectionRequest,
    ) -> JobRecord:
        try:
            return runtime.update_inclusion(job_id, selection)
        except BenchmarkTransportNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except BenchmarkConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get(
        "/api/admin/ocr/benchmarks",
        operation_id="admin_ocr_benchmarks_get",
        response_model=BenchmarkOverview,
    )
    def get_benchmark_overview(
        parser_provider: str | None = Query(
            default=None,
            min_length=1,
            max_length=64,
            pattern=r"^[a-z0-9_]+$",
        ),
        parser_layout_profile: str | None = Query(
            default=None,
            min_length=1,
            max_length=64,
            pattern=r"^[a-z0-9_]+$",
        ),
    ) -> BenchmarkOverview:
        try:
            return runtime.get_overview(parser_provider, parser_layout_profile)
        except BenchmarkInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get(
        "/api/admin/ocr/benchmarks/export",
        operation_id="admin_ocr_benchmarks_export",
        response_class=StreamingResponse,
        responses={"200": {"content": ZIP_RESPONSE_CONTENT}},
    )
    def export_benchmark_dataset(
        parser_provider: str | None = Query(
            default=None,
            min_length=1,
            max_length=64,
            pattern=r"^[a-z0-9_]+$",
        ),
        parser_layout_profile: str | None = Query(
            default=None,
            min_length=1,
            max_length=64,
            pattern=r"^[a-z0-9_]+$",
        ),
    ) -> StreamingResponse:
        try:
            export = runtime.export_dataset(parser_provider, parser_layout_profile)
        except BenchmarkInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except BenchmarkConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return StreamingResponse(
            export.content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{export.filename}"'
            },
        )

    @router.post(
        "/api/admin/ocr/benchmarks/import",
        operation_id="admin_ocr_benchmarks_import",
        response_model=BenchmarkDatasetImportResult,
    )
    async def import_benchmark_dataset(
        file: UploadFile = File(...),
        benchmark_import_request_id: str | None = Header(
            default=None,
            alias="X-Benchmark-Import-Request-ID",
            min_length=1,
            max_length=128,
            pattern=BENCHMARK_IMPORT_REQUEST_ID_PATTERN,
        ),
    ) -> BenchmarkDatasetImportResult:
        archive_bytes = await file.read(runtime.max_dataset_upload_bytes + 1)
        if len(archive_bytes) > runtime.max_dataset_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail="Dataset ZIP exceeds maximum size",
            )
        try:
            return await run_in_threadpool(
                runtime.import_dataset,
                archive_bytes,
                benchmark_import_request_id,
            )
        except BenchmarkConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except BenchmarkDatasetInputError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=str(exc),
            ) from exc

    @router.get(
        "/api/admin/ocr/benchmarks/imports/{request_id}",
        operation_id="admin_ocr_benchmark_import_get",
        response_model=BenchmarkDatasetImportReceipt,
    )
    def get_benchmark_dataset_import(
        request_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> BenchmarkDatasetImportReceipt:
        try:
            import_status = runtime.get_import(request_id)
        except BenchmarkTransportNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if import_status.should_resume:
            setattr(request.state, BACKGROUND_TASK_STATE_KEY, True)
            background_tasks.add_task(runtime.resume_import, request_id)
        return import_status.receipt

    @router.get(
        "/api/admin/ocr/benchmarks/{report_id}",
        operation_id="admin_ocr_benchmark_report_get",
        response_model=BenchmarkReport,
    )
    def get_benchmark_report(
        report_id: str,
    ) -> BenchmarkReport:
        try:
            return runtime.get_report(report_id)
        except BenchmarkTransportNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post(
        "/api/admin/ocr/benchmarks/run",
        operation_id="admin_ocr_benchmarks_run",
        response_model=BenchmarkReport,
    )
    def run_parser_benchmark(
        benchmark_request: BenchmarkRunRequest | None = None,
    ) -> BenchmarkReport:
        try:
            return runtime.run(benchmark_request)
        except BenchmarkInputError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except BenchmarkConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except BenchmarkConfigurationError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Parser configuration error: {exc}",
            ) from exc

    return router
