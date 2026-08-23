"""Educational recommendation request and result contracts."""

from app.domain.recommendations.models import (
    RecommendationAction,
    RecommendationRequest,
    RecommendationResult,
)

__all__ = [
    "RecommendationAction",
    "RecommendationRequest",
    "RecommendationResult",
]
