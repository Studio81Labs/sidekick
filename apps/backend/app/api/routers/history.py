"""History transport endpoints."""

from fastapi import APIRouter, Query

from app.api.dependencies import HistoryRuntime
from app.domain.hands import ArchiveJobsRequest, JobHistory


def create_history_router(runtime: HistoryRuntime) -> APIRouter:
    """Build the history router with its application-owned dependencies."""

    router = APIRouter()

    @router.get("/api/history", operation_id="history_get", response_model=JobHistory)
    def get_history(
        limit: int = Query(default=24, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        query: str | None = Query(default=None, max_length=100),
    ) -> JobHistory:
        return runtime.list_history(limit, offset, query)

    @router.put(
        "/api/history",
        operation_id="history_archive",
        response_model=JobHistory,
    )
    def archive_jobs(
        request: ArchiveJobsRequest,
        limit: int = Query(default=24, ge=1, le=100),
    ) -> JobHistory:
        return runtime.archive_jobs(request, limit)

    return router
