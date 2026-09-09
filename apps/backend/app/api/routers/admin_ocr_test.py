"""Administrative OCR test session transport endpoints."""

from fastapi import APIRouter, Response

from app.api.administrative_access import administrator_access_route
from app.application.admin_ocr_test import AdminOcrTestService
from app.domain.admin_ocr_test import AdminOcrTestSession


def create_admin_ocr_test_router(runtime: AdminOcrTestService) -> APIRouter:
    """Build the administrative OCR test session router."""

    router = APIRouter(
        route_class=administrator_access_route(runtime.authorize_administrator)
    )

    @router.get(
        "/api/admin/ocr/session",
        operation_id="admin_ocr_session_get",
        response_model=AdminOcrTestSession,
    )
    def get_admin_ocr_test_session(
        response: Response,
    ) -> AdminOcrTestSession:
        # The confirmation is scoped to the presented credential, so no cache
        # between the client and the backend may replay it for another request.
        response.headers["Cache-Control"] = "no-store"
        return AdminOcrTestSession(enabled=runtime.enabled, authorized=True)

    return router
