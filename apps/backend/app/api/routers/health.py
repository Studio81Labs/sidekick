"""Health and system-information transport endpoints."""

from fastapi import APIRouter

from app.api.dependencies import ApiRuntime
from app.domain.health import HealthResponse


def create_health_router(runtime: ApiRuntime) -> APIRouter:
    """Build the health router with its application-owned dependencies."""

    router = APIRouter()

    @router.get("/api/health", operation_id="health_get", response_model=HealthResponse)
    def health() -> HealthResponse:
        return runtime.get_health()

    return router
