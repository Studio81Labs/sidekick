"""Post-hand training decisions and progress contracts."""

from datetime import datetime, timezone
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.poker import Card, Street
from app.domain.recommendations import RecommendationAction


TrainingCertainty = Literal["low", "medium", "high"]
TrainingOutcome = Literal["match", "mixed", "same_action", "mixed_action", "different"]
TrainingReviewOrder = Literal["recent", "ev_loss"]
TrainingReviewCertainty = Literal["low", "medium", "high", "unrated"]


class TrainingDecisionRequest(BaseModel):
    action: RecommendationAction
    sizing: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        strict=True,
    )
    certainty: TrainingCertainty | None = None

    @model_validator(mode="after")
    def validate_sizing(self) -> Self:
        if self.action not in {"bet", "raise"} and self.sizing is not None:
            raise ValueError("Sizing is only valid for bet or raise decisions")
        return self


class TrainingDecision(TrainingDecisionRequest):
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TrainingReviewRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note", mode="before")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None


class TrainingTrend(BaseModel):
    window_hands: int = Field(ge=1)
    recent_action_accuracy: float = Field(ge=0, le=1)
    previous_action_accuracy: float = Field(ge=0, le=1)
    action_accuracy_delta: float = Field(ge=-1, le=1)
    recent_exact_accuracy: float = Field(ge=0, le=1)
    previous_exact_accuracy: float = Field(ge=0, le=1)
    exact_accuracy_delta: float = Field(ge=-1, le=1)
    recent_ev_compared_hands: int = Field(default=0, ge=0)
    previous_ev_compared_hands: int = Field(default=0, ge=0)
    recent_average_ev_loss_bb: float | None = Field(default=None, ge=0)
    previous_average_ev_loss_bb: float | None = Field(default=None, ge=0)
    average_ev_loss_delta_bb: float | None = None


class TrainingStreetSummary(BaseModel):
    street: Street
    reviewed_hands: int = Field(ge=0)
    action_matches: int = Field(ge=0)
    exact_matches: int = Field(ge=0)
    action_accuracy: float = Field(ge=0, le=1)
    exact_accuracy: float = Field(ge=0, le=1)
    ev_compared_hands: int = Field(default=0, ge=0)
    average_ev_loss_bb: float | None = Field(default=None, ge=0)
    trend: TrainingTrend | None = None


class TrainingCertaintySummary(BaseModel):
    certainty: TrainingCertainty
    hands: int = Field(ge=1)
    action_matches: int = Field(ge=0)
    exact_matches: int = Field(ge=0)
    needs_review_hands: int = Field(default=0, ge=0)
    action_accuracy: float = Field(ge=0, le=1)
    exact_accuracy: float = Field(ge=0, le=1)
    ev_compared_hands: int = Field(default=0, ge=0)
    average_ev_loss_bb: float | None = Field(default=None, ge=0)
    trend: TrainingTrend | None = None


class TrainingRecentHand(BaseModel):
    job_id: str
    original_filename: str
    street: Street | None
    hero_cards: list[Card] = Field(default_factory=list)
    decision_action: RecommendationAction
    decision_sizing: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        strict=True,
    )
    decision_certainty: TrainingCertainty | None = None
    recommended_action: RecommendationAction
    recommended_sizing: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        strict=True,
    )
    outcome: TrainingOutcome
    recorded_at: datetime
    reviewed_at: datetime | None = None
    review_note: str | None = None
    ev_loss_bb: float | None = Field(default=None, ge=0)


class TrainingPositionSummary(BaseModel):
    position: str = Field(min_length=1)
    reviewed_hands: int = Field(ge=1)
    action_matches: int = Field(ge=0)
    exact_matches: int = Field(ge=0)
    needs_review_hands: int = Field(default=0, ge=0)
    action_accuracy: float = Field(ge=0, le=1)
    exact_accuracy: float = Field(ge=0, le=1)
    ev_compared_hands: int = Field(default=0, ge=0)
    average_ev_loss_bb: float | None = Field(default=None, ge=0)
    trend: TrainingTrend | None = None


class TrainingActionDifference(BaseModel):
    decision_action: RecommendationAction
    recommended_action: RecommendationAction
    hands: int = Field(ge=1)
    needs_review_hands: int = Field(default=0, ge=0)
    ev_compared_hands: int = Field(default=0, ge=0)
    average_ev_loss_bb: float | None = Field(default=None, ge=0)


class TrainingSolverRouteSummary(BaseModel):
    key: str = Field(pattern=r"^[0-9a-f]{64}$")
    engine: str
    hands: int = Field(ge=1)
    fallback_hands: int = Field(default=0, ge=0)
    action_matches: int = Field(default=0, ge=0)
    exact_matches: int = Field(default=0, ge=0)
    action_accuracy: float = Field(default=0, ge=0, le=1)
    exact_accuracy: float = Field(default=0, ge=0, le=1)
    ev_compared_hands: int = Field(default=0, ge=0)
    average_ev_loss_bb: float | None = Field(default=None, ge=0)
    trend: TrainingTrend | None = None
    street_counts: dict[Street, int] = Field(default_factory=dict)


class TrainingSolverFallbackSummary(BaseModel):
    key: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str
    hands: int = Field(ge=1)
    action_matches: int = Field(default=0, ge=0)
    exact_matches: int = Field(default=0, ge=0)
    action_accuracy: float = Field(default=0, ge=0, le=1)
    exact_accuracy: float = Field(default=0, ge=0, le=1)
    ev_compared_hands: int = Field(default=0, ge=0)
    average_ev_loss_bb: float | None = Field(default=None, ge=0)
    trend: TrainingTrend | None = None
    street_counts: dict[Street, int] = Field(default_factory=dict)


class TrainingSolverCoverageTrend(BaseModel):
    window_hands: int = Field(ge=1)
    recent_attribution_rate: float = Field(ge=0, le=1)
    previous_attribution_rate: float = Field(ge=0, le=1)
    attribution_rate_delta: float = Field(ge=-1, le=1)
    recent_fallback_rate: float = Field(ge=0, le=1)
    previous_fallback_rate: float = Field(ge=0, le=1)
    fallback_rate_delta: float = Field(ge=-1, le=1)


class TrainingSolverCoverage(BaseModel):
    total_hands: int = Field(ge=0)
    tracked_hands: int = Field(default=0, ge=0)
    unattributed_hands: int = Field(default=0, ge=0)
    fallback_hands: int = Field(default=0, ge=0)
    fallback_rate: float = Field(default=0, ge=0, le=1)
    trend: TrainingSolverCoverageTrend | None = None
    routes: list[TrainingSolverRouteSummary] = Field(default_factory=list)
    fallback_reasons: list[TrainingSolverFallbackSummary] = Field(default_factory=list)


class TrainingProgress(BaseModel):
    reviewed_hands: int = Field(ge=0)
    action_matches: int = Field(ge=0)
    exact_matches: int = Field(ge=0)
    different_actions: int = Field(ge=0)
    needs_review_hands: int = Field(ge=0)
    action_accuracy: float = Field(ge=0, le=1)
    exact_accuracy: float = Field(ge=0, le=1)
    ev_compared_hands: int = Field(default=0, ge=0)
    average_ev_loss_bb: float | None = Field(default=None, ge=0)
    trend: TrainingTrend | None = None
    action_differences: list[TrainingActionDifference] = Field(default_factory=list)
    solver_coverage: TrainingSolverCoverage
    certainty_summaries: list[TrainingCertaintySummary] = Field(default_factory=list)
    unrated_hands: int = Field(default=0, ge=0)
    unrated_needs_review_hands: int = Field(default=0, ge=0)
    street_summaries: list[TrainingStreetSummary] = Field(default_factory=list)
    position_summaries: list[TrainingPositionSummary] = Field(default_factory=list)
    unpositioned_hands: int = Field(default=0, ge=0)
    unpositioned_needs_review_hands: int = Field(default=0, ge=0)
    recent_matching_hands: int = Field(default=0, ge=0)
    recent_hands: list[TrainingRecentHand] = Field(default_factory=list)
    lesson_count: int = Field(default=0, ge=0)
    lesson_matching_hands: int = Field(default=0, ge=0)
    lesson_hands: list[TrainingRecentHand] = Field(default_factory=list)
    review_street_counts: dict[Street, int] = Field(default_factory=dict)
    review_queue_hands: int = Field(default=0, ge=0)
    review_queue: list[TrainingRecentHand] = Field(default_factory=list)
