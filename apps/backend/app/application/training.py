"""Application services for training review and lesson use cases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.domain.hands import JobRecord
from app.domain.poker import Street
from app.domain.recommendations import RecommendationAction
from app.domain.training import (
    TrainingProgress,
    TrainingReviewCertainty,
    TrainingReviewOrder,
    TrainingReviewRequest,
)


@dataclass(frozen=True)
class TrainingProgressQuery:
    """Validated filters passed to training progress aggregation."""

    review_order: TrainingReviewOrder
    review_street: Street | None
    review_certainty: TrainingReviewCertainty | None
    review_position: str | None
    review_unpositioned: bool
    review_action_difference: (
        tuple[RecommendationAction, RecommendationAction] | None
    )
    lesson_order: TrainingReviewOrder
    lesson_street: Street | None
    lesson_query: str | None
    solver_fallback_key: str | None
    solver_route_key: str | None
    solver_unattributed: bool
    recent_street: Street | None
    recent_position: str | None
    recent_unpositioned: bool
    recent_certainty: TrainingReviewCertainty | None


CompleteTrainingReview = Callable[[str, TrainingReviewRequest | None], JobRecord]
ReopenTrainingReview = Callable[[str], JobRecord]
GetTrainingProgress = Callable[[TrainingProgressQuery], TrainingProgress]
ExportTrainingLessons = Callable[
    [TrainingReviewOrder, Street | None, str | None],
    tuple[str, str],
]


class TrainingService:
    """Dispatch training use cases through application-owned callbacks."""

    def __init__(
        self,
        complete_review: CompleteTrainingReview,
        reopen_review: ReopenTrainingReview,
        get_progress: GetTrainingProgress,
        export_lessons: ExportTrainingLessons,
    ) -> None:
        self._complete_review = complete_review
        self._reopen_review = reopen_review
        self._get_progress = get_progress
        self._export_lessons = export_lessons

    def complete_review(
        self,
        job_id: str,
        review: TrainingReviewRequest | None,
    ) -> JobRecord:
        return self._complete_review(job_id, review)

    def reopen_review(self, job_id: str) -> JobRecord:
        return self._reopen_review(job_id)

    def get_progress(self, query: TrainingProgressQuery) -> TrainingProgress:
        return self._get_progress(query)

    def export_lessons(
        self,
        lesson_order: TrainingReviewOrder,
        lesson_street: Street | None,
        lesson_query: str | None,
    ) -> tuple[str, str]:
        return self._export_lessons(
            lesson_order,
            lesson_street,
            lesson_query,
        )
