from typing import cast

from app.api.dependencies import (
    TrainingProgressQuery as CompatibilityTrainingProgressQuery,
)
from app.api.dependencies import TrainingRuntime
from app.application.training import TrainingProgressQuery, TrainingService
from app.domain.hands import JobRecord
from app.domain.training import TrainingProgress, TrainingReviewRequest


def progress_query() -> TrainingProgressQuery:
    return TrainingProgressQuery(
        review_order="recent",
        review_street=None,
        review_certainty=None,
        review_position=None,
        review_unpositioned=False,
        review_action_difference=None,
        lesson_order="recent",
        lesson_street=None,
        lesson_query=None,
        solver_fallback_key=None,
        solver_route_key=None,
        solver_unattributed=False,
        recent_street=None,
        recent_position=None,
        recent_unpositioned=False,
        recent_certainty=None,
    )


def test_training_service_dispatches_use_cases() -> None:
    calls: list[tuple[object, ...]] = []
    job = JobRecord(
        original_filename="table.png",
        image_filename="image.png",
        parser_provider="mock",
        recommendation_provider="mock",
    )
    review = cast(TrainingReviewRequest, object())
    progress = cast(TrainingProgress, object())
    query = progress_query()

    def complete_review(
        job_id: str,
        request: TrainingReviewRequest | None,
    ) -> JobRecord:
        calls.append(("complete", job_id, request))
        return job

    def reopen_review(job_id: str) -> JobRecord:
        calls.append(("reopen", job_id))
        return job

    def get_progress(request: TrainingProgressQuery) -> TrainingProgress:
        calls.append(("progress", request))
        return progress

    def export_lessons(
        lesson_order: str,
        lesson_street: None,
        lesson_query: str | None,
    ) -> tuple[str, str]:
        calls.append(("export", lesson_order, lesson_street, lesson_query))
        return "# Lessons", "lessons.md"

    service = TrainingService(
        complete_review=complete_review,
        reopen_review=reopen_review,
        get_progress=get_progress,
        export_lessons=export_lessons,
    )

    assert service.complete_review(job.id, review) is job
    assert service.reopen_review(job.id) is job
    assert service.get_progress(query) is progress
    assert service.export_lessons("recent", None, "river") == (
        "# Lessons",
        "lessons.md",
    )
    assert calls == [
        ("complete", job.id, review),
        ("reopen", job.id),
        ("progress", query),
        ("export", "recent", None, "river"),
    ]


def test_training_transport_compatibility_aliases_preserve_identity() -> None:
    assert CompatibilityTrainingProgressQuery is TrainingProgressQuery
    assert TrainingRuntime is TrainingService
