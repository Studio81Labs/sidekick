import pytest
from pydantic import ValidationError

from app.domain.poker import CanonicalState
from app.domain.recommendations import (
    RecommendationRequest,
    RecommendationResult,
)
from app.models import RecommendationRequest as CompatibilityRecommendationRequest
from app.models import RecommendationResult as CompatibilityRecommendationResult


def test_models_compatibility_surface_reexports_recommendation_contracts() -> None:
    assert CompatibilityRecommendationRequest is RecommendationRequest
    assert CompatibilityRecommendationResult is RecommendationResult


def test_recommendation_request_parses_canonical_state() -> None:
    request = RecommendationRequest(
        state={
            "hero_cards": [
                {"rank": "A", "suit": "hearts"},
                {"rank": "K", "suit": "diamonds"},
            ],
            "street": "preflop",
            "user_approved": True,
        },
        provider="local_solver",
    )

    assert type(request.state) is CanonicalState
    assert request.state.user_approved is True


def test_recommendation_result_json_round_trip_preserves_evidence() -> None:
    result = RecommendationResult(
        action="raise",
        sizing=7.5,
        confidence=0.8,
        explanation="Raise as an educational mixed-frequency example.",
        raw={"frequency": 0.6, "engine": "local"},
    )

    restored = RecommendationResult.model_validate_json(result.model_dump_json())

    assert restored == result


@pytest.mark.parametrize(
    "payload",
    [
        {
            "action": "fold",
            "sizing": 2.5,
            "confidence": 0.8,
            "explanation": "Fold.",
        },
        {
            "action": "bet",
            "sizing": 0,
            "confidence": 0.8,
            "explanation": "Bet.",
        },
        {
            "action": "call",
            "confidence": 1.01,
            "explanation": "Call.",
        },
        {
            "action": "check",
            "confidence": float("nan"),
            "explanation": "Check.",
        },
    ],
)
def test_recommendation_result_rejects_invalid_payloads(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RecommendationResult.model_validate(payload)
