"""Pipeline capability transport endpoints."""

from fastapi import APIRouter, HTTPException

from app.api.dependencies import PipelineCapabilitiesUnavailableError
from app.application.system import SystemQueryService
from app.domain.pipeline import PipelineCapabilities


def create_pipeline_router(runtime: SystemQueryService) -> APIRouter:
    """Build the pipeline router with its application-owned dependencies."""

    router = APIRouter()

    @router.get(
        "/api/pipeline",
        operation_id="pipeline_get",
        response_model=PipelineCapabilities,
    )
    def get_pipeline_capabilities() -> PipelineCapabilities:
        try:
            return runtime.get_pipeline_capabilities()
        except PipelineCapabilitiesUnavailableError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Pipeline configuration error: {exc}",
            ) from exc

    return router
