"""History transport endpoints."""

from fastapi import APIRouter, Header, Query

from app.api.administrative_access import require_administrator
from app.application.admin_ocr_test import AuthorizeAdministrator
from app.application.jobs import JobHistoryService
from app.domain.hands import ArchiveJobsRequest, JobHistory


def create_history_router(
    runtime: JobHistoryService,
    authorize_administrator: AuthorizeAdministrator,
) -> APIRouter:
    """Build the history router with its application-owned dependencies."""

    router = APIRouter()

    @router.get(
        "/api/admin/ocr/history",
        operation_id="admin_ocr_history_get",
        response_model=JobHistory,
    )
    def get_history(
        limit: int = Query(default=24, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        query: str | None = Query(default=None, max_length=100),
        authorization: str | None = Header(
            default=None,
            alias="Authorization",
            include_in_schema=False,
        ),
    ) -> JobHistory:
        require_administrator(authorize_administrator(authorization))
        return runtime.list_history(limit, offset, query)

    @router.put(
        "/api/admin/ocr/history",
        operation_id="admin_ocr_history_archive",
        response_model=JobHistory,
    )
    def archive_jobs(
        request: ArchiveJobsRequest,
        limit: int = Query(default=24, ge=1, le=100),
        authorization: str | None = Header(
            default=None,
            alias="Authorization",
            include_in_schema=False,
        ),
    ) -> JobHistory:
        require_administrator(authorize_administrator(authorization))
        return runtime.archive_jobs(request, limit)

    return router
