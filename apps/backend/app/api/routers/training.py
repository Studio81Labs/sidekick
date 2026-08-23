"""Training review and lesson transport endpoints."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.dependencies import TrainingProgressQuery, TrainingRuntime
from app.api.response_contracts import MARKDOWN_RESPONSE_CONTENT
from app.domain.poker import Street
from app.domain.recommendations import RecommendationAction
from app.domain.training import (
    TrainingProgress,
    TrainingReviewCertainty,
    TrainingReviewOrder,
    TrainingReviewRequest,
)
from app.models import JobRecord


def create_training_router(runtime: TrainingRuntime) -> APIRouter:
    """Build the training router with its application-owned dependencies."""

    router = APIRouter()

    @router.put(
        "/api/jobs/{job_id}/training-review",
        operation_id="job_training_review_complete",
        response_model=JobRecord,
    )
    def complete_training_review(
        job_id: str,
        review: TrainingReviewRequest | None = None,
    ) -> JobRecord:
        try:
            return runtime.complete_review(job_id, review)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.delete(
        "/api/jobs/{job_id}/training-review",
        operation_id="job_training_review_reopen",
        response_model=JobRecord,
    )
    def reopen_training_review(job_id: str) -> JobRecord:
        try:
            return runtime.reopen_review(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get(
        "/api/training/progress",
        operation_id="training_progress_get",
        response_model=TrainingProgress,
    )
    def get_training_progress(
        review_order: TrainingReviewOrder = "recent",
        review_street: Street | None = None,
        review_certainty: TrainingReviewCertainty | None = None,
        review_position: str | None = Query(
            default=None,
            min_length=1,
            max_length=120,
            pattern=r".*\S.*",
        ),
        review_unpositioned: bool = False,
        review_decision_action: RecommendationAction | None = None,
        review_recommended_action: RecommendationAction | None = None,
        lesson_order: TrainingReviewOrder = "recent",
        lesson_street: Street | None = None,
        lesson_query: str | None = Query(default=None, max_length=120),
        solver_fallback_key: str | None = Query(
            default=None,
            pattern=r"^[0-9a-f]{64}$",
        ),
        solver_route_key: str | None = Query(
            default=None,
            pattern=r"^[0-9a-f]{64}$",
        ),
        solver_unattributed: bool = False,
        recent_street: Street | None = None,
        recent_position: str | None = Query(
            default=None,
            min_length=1,
            max_length=120,
            pattern=r".*\S.*",
        ),
        recent_unpositioned: bool = False,
        recent_certainty: TrainingReviewCertainty | None = None,
    ) -> TrainingProgress:
        if (review_decision_action is None) != (review_recommended_action is None):
            raise HTTPException(
                status_code=422,
                detail=(
                    "review_decision_action and review_recommended_action "
                    "must be provided together"
                ),
            )
        if review_position is not None and review_unpositioned:
            raise HTTPException(
                status_code=422,
                detail=(
                    "review_position and review_unpositioned "
                    "are mutually exclusive"
                ),
            )
        solver_filter_count = sum((
            solver_fallback_key is not None,
            solver_route_key is not None,
            solver_unattributed,
        ))
        if solver_filter_count > 1:
            raise HTTPException(
                status_code=422,
                detail=(
                    "solver_fallback_key, solver_route_key, and "
                    "solver_unattributed are mutually exclusive"
                ),
            )
        position_filter_count = sum((
            recent_position is not None,
            recent_unpositioned,
        ))
        if position_filter_count > 1:
            raise HTTPException(
                status_code=422,
                detail=(
                    "recent_position and recent_unpositioned "
                    "are mutually exclusive"
                ),
            )
        if position_filter_count > 0 and solver_filter_count > 0:
            raise HTTPException(
                status_code=422,
                detail=(
                    "position and solver recent-hand filters "
                    "are mutually exclusive"
                ),
            )
        if recent_street is not None and (
            position_filter_count > 0 or solver_filter_count > 0
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "street, position, and solver recent-hand filters "
                    "are mutually exclusive"
                ),
            )
        if recent_certainty is not None and (
            recent_street is not None
            or position_filter_count > 0
            or solver_filter_count > 0
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "certainty, street, position, and solver recent-hand "
                    "filters are mutually exclusive"
                ),
            )
        review_action_difference = (
            (review_decision_action, review_recommended_action)
            if review_decision_action is not None
            and review_recommended_action is not None
            else None
        )
        return runtime.get_progress(
            TrainingProgressQuery(
                review_order=review_order,
                review_street=review_street,
                review_certainty=review_certainty,
                review_position=review_position,
                review_unpositioned=review_unpositioned,
                review_action_difference=review_action_difference,
                lesson_order=lesson_order,
                lesson_street=lesson_street,
                lesson_query=lesson_query,
                solver_fallback_key=solver_fallback_key,
                solver_route_key=solver_route_key,
                solver_unattributed=solver_unattributed,
                recent_street=recent_street,
                recent_position=recent_position,
                recent_unpositioned=recent_unpositioned,
                recent_certainty=recent_certainty,
            )
        )

    @router.get(
        "/api/training/lessons/export",
        operation_id="training_lessons_export",
        response_class=StreamingResponse,
        responses={"200": {"content": MARKDOWN_RESPONSE_CONTENT}},
    )
    def export_training_lessons(
        lesson_order: TrainingReviewOrder = "recent",
        lesson_street: Street | None = None,
        lesson_query: str | None = Query(default=None, max_length=120),
    ) -> StreamingResponse:
        try:
            document, filename = runtime.export_lessons(
                lesson_order,
                lesson_street,
                lesson_query,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return StreamingResponse(
            iter([document]),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
