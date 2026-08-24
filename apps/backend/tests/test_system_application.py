"""Focused coverage for the application system-query service boundary."""

from dataclasses import replace
from typing import cast

from app.api.dependencies import ApiRuntime
from app.application.system import SystemQueryService
from app.domain.health import HealthResponse
from app.domain.pipeline import PipelineCapabilities


def test_api_runtime_compatibility_export_preserves_object_identity() -> None:
    assert ApiRuntime is SystemQueryService


def test_system_query_service_preserves_callbacks_and_replacement() -> None:
    health = cast(HealthResponse, object())
    capabilities = cast(PipelineCapabilities, object())
    health_calls: list[None] = []
    pipeline_calls: list[None] = []

    def get_health() -> HealthResponse:
        health_calls.append(None)
        return health

    def get_pipeline_capabilities() -> PipelineCapabilities:
        pipeline_calls.append(None)
        return capabilities

    service = SystemQueryService(
        get_health=get_health,
        get_pipeline_capabilities=get_pipeline_capabilities,
    )

    assert service.get_health() is health
    assert service.get_pipeline_capabilities() is capabilities
    assert health_calls == [None]
    assert pipeline_calls == [None]
    assert replace(service, get_health=lambda: health).get_health() is health
