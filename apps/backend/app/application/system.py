"""Application-owned system query service contracts."""

from collections.abc import Callable
from dataclasses import dataclass

from app.domain.health import HealthResponse
from app.domain.pipeline import PipelineCapabilities


@dataclass(frozen=True)
class SystemQueryService:
    """Application queries required by health and pipeline transports."""

    get_health: Callable[[], HealthResponse]
    get_pipeline_capabilities: Callable[[], PipelineCapabilities]


__all__ = ["SystemQueryService"]
