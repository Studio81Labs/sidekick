from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.domain.training import (
    TrainingActionDifference,
    TrainingCertainty,
    TrainingCertaintySummary,
    TrainingDecision,
    TrainingDecisionRequest,
    TrainingOutcome,
    TrainingPositionSummary,
    TrainingProgress,
    TrainingRecentHand,
    TrainingReviewRequest,
    TrainingReviewCertainty,
    TrainingReviewOrder,
    TrainingSolverCoverage,
    TrainingSolverCoverageTrend,
    TrainingSolverFallbackSummary,
    TrainingSolverRouteSummary,
    TrainingStreetSummary,
    TrainingTrend,
)
from app import models as compatibility_models


TRAINING_MODEL_TYPES = (
    TrainingActionDifference,
    TrainingCertaintySummary,
    TrainingDecision,
    TrainingDecisionRequest,
    TrainingPositionSummary,
    TrainingProgress,
    TrainingRecentHand,
    TrainingReviewRequest,
    TrainingSolverCoverage,
    TrainingSolverCoverageTrend,
    TrainingSolverFallbackSummary,
    TrainingSolverRouteSummary,
    TrainingStreetSummary,
    TrainingTrend,
)


@pytest.mark.parametrize("model_type", TRAINING_MODEL_TYPES)
def test_models_compatibility_surface_reexports_training_contracts(
    model_type: type,
) -> None:
    assert getattr(compatibility_models, model_type.__name__) is model_type


def test_models_compatibility_surface_reexports_training_aliases() -> None:
    assert compatibility_models.TrainingCertainty == TrainingCertainty
    assert compatibility_models.TrainingOutcome == TrainingOutcome
    assert compatibility_models.TrainingReviewCertainty == TrainingReviewCertainty
    assert compatibility_models.TrainingReviewOrder == TrainingReviewOrder


def test_training_decision_json_round_trip_preserves_utc_timestamp() -> None:
    decision = TrainingDecision(action="raise", sizing=7.5, certainty="high")

    restored = TrainingDecision.model_validate_json(decision.model_dump_json())

    assert restored == decision
    assert restored.recorded_at.tzinfo is not None
    assert restored.recorded_at.utcoffset() == timezone.utc.utcoffset(None)


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "fold", "sizing": 2.5},
        {"action": "call", "sizing": 2.5},
        {"action": "bet", "sizing": 0},
        {"action": "raise", "sizing": float("nan")},
    ],
)
def test_training_decision_request_rejects_invalid_sizing(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        TrainingDecisionRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("note", "expected"),
    [
        ("  Review the turn sizing.  ", "Review the turn sizing."),
        ("   ", None),
        (None, None),
    ],
)
def test_training_review_request_normalizes_optional_note(
    note: str | None,
    expected: str | None,
) -> None:
    assert TrainingReviewRequest(note=note).note == expected


def test_training_progress_round_trip_preserves_nested_contracts() -> None:
    recorded_at = datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc)
    progress = TrainingProgress(
        reviewed_hands=1,
        action_matches=0,
        exact_matches=0,
        different_actions=1,
        needs_review_hands=1,
        action_accuracy=0,
        exact_accuracy=0,
        solver_coverage={
            "total_hands": 1,
            "tracked_hands": 1,
            "fallback_hands": 0,
            "fallback_rate": 0,
            "routes": [
                {
                    "key": "a" * 64,
                    "engine": "local_solver",
                    "hands": 1,
                    "street_counts": {"turn": 1},
                }
            ],
        },
        recent_hands=[
            {
                "job_id": "job-1",
                "original_filename": "turn.png",
                "street": "turn",
                "hero_cards": [
                    {"rank": "A", "suit": "clubs"},
                    {"rank": "J", "suit": "clubs"},
                ],
                "decision_action": "call",
                "recommended_action": "fold",
                "outcome": "different",
                "recorded_at": recorded_at,
            }
        ],
    )

    restored = TrainingProgress.model_validate_json(progress.model_dump_json())

    assert restored == progress
    assert type(restored.solver_coverage) is TrainingSolverCoverage
    assert type(restored.solver_coverage.routes[0]) is TrainingSolverRouteSummary
    assert type(restored.recent_hands[0]) is TrainingRecentHand
