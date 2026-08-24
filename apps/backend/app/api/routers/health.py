"""Health and system-information transport endpoints."""

from fastapi import APIRouter

from app.application.system import SystemQueryService
from app.domain.health import HealthResponse


def create_health_router(runtime: SystemQueryService) -> APIRouter:
    """Build the health router with its application-owned dependencies."""

    router = APIRouter()

    @router.get("/api/health", operation_id="health_get", response_model=HealthResponse)
    def health() -> HealthResponse:
        return runtime.get_health()

    return router
