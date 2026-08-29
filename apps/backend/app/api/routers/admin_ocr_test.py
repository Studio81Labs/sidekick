"""Administrative OCR test session transport endpoints."""

from fastapi import APIRouter, Header, Response

from app.api.administrative_access import require_administrator

from app.application.admin_ocr_test import AdminOcrTestService
from app.domain.admin_ocr_test import AdminOcrTestSession


def create_admin_ocr_test_router(runtime: AdminOcrTestService) -> APIRouter:
    """Build the administrative OCR test session router."""

    router = APIRouter()

    @router.get(
        "/api/admin/ocr-test/session",
        operation_id="admin_ocr_test_session_get",
        response_model=AdminOcrTestSession,
    )
    def get_admin_ocr_test_session(
        response: Response,
        authorization: str | None = Header(
            default=None,
            alias="Authorization",
            include_in_schema=False,
        ),
    ) -> AdminOcrTestSession:
        require_administrator(runtime.authorize_administrator(authorization))

        # The confirmation is scoped to the presented credential, so no cache
        # between the client and the backend may replay it for another request.
        response.headers["Cache-Control"] = "no-store"
        return AdminOcrTestSession(enabled=runtime.enabled, authorized=True)

    return router
