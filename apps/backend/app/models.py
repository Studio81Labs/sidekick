import math
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Self
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.domain.pipeline import (
    PipelineCapabilities,
    PipelineOption,
    PipelineSelection,
)
from app.domain.poker import (
    Card,
    CompletedPostflopAction,
    CompletedPostflopActionType,
    CompletedPostflopStreet,
    CompletedPostflopStreetHistory,
    FacingAction,
    NonNegativeFiniteNumber,
    PositiveFiniteNumber,
    PositiveInteger,
    PostflopAction,
    PostflopActionType,
    PostflopActor,
    PreflopAction,
    PreflopActionType,
    PreflopPosition,
    Rank,
    Street,
    Suit,
)
from app.domain.poker.models import CODE_BY_SUIT, RANKS, SUIT_BY_CODE


RecommendationAction = Literal["fold", "check", "call", "bet", "raise"]
DeploymentEnvironment = Literal["local", "staging", "production"]
TrainingCertainty = Literal["low", "medium", "high"]
TrainingOutcome = Literal["match", "mixed", "same_action", "mixed_action", "different"]
TrainingReviewOrder = Literal["recent", "ev_loss"]
TrainingReviewCertainty = Literal["low", "medium", "high", "unrated"]
BenchmarkFieldName = Literal[
    "hero_cards",
    "board_cards",
    "street",
    "pot_size",
    "current_bet",
    "hero_stack",
    "opponent_stack",
    "effective_stack",
    "players_in_hand",
    "hero_position",
    "opponent_position",
    "preflop_opener_position",
    "preflop_open_size",
    "preflop_action_history",
    "facing_action",
    "postflop_action_history",
    "completed_postflop_streets",
    "action_context",
]
BENCHMARK_FIELDS: tuple[BenchmarkFieldName, ...] = (
    "hero_cards",
    "board_cards",
    "street",
    "pot_size",
    "current_bet",
    "hero_stack",
    "opponent_stack",
    "effective_stack",
    "players_in_hand",
    "hero_position",
    "opponent_position",
    "preflop_opener_position",
    "preflop_open_size",
    "preflop_action_history",
    "facing_action",
    "postflop_action_history",
    "completed_postflop_streets",
    "action_context",
)
BENCHMARK_POSITION_ALIASES = {
    "btn": "button",
    "dealer": "button",
    "ip": "in position",
    "oop": "out of position",
}
ParserConfidence = Annotated[
    float,
    Field(allow_inf_nan=False, strict=True),
]
NonNegativeInteger = Annotated[int, Field(ge=0, strict=True)]
UnitIntervalNumber = Annotated[
    float,
    Field(ge=0, le=1, allow_inf_nan=False, strict=True),
]

BENCHMARK_IMPORT_REQUEST_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"


def _validate_card_count(field_name: str, cards: list["Card"], maximum: int) -> list["Card"]:
    if len(cards) > maximum:
        raise ValueError(f"{field_name} cannot contain more than {maximum} cards")
    return cards


def _validate_unique_cards(hero_cards: list["Card"], board_cards: list["Card"]) -> None:
    seen: set[str] = set()
    for card in [*hero_cards, *board_cards]:
        if card.code in seen:
            raise ValueError(f"Duplicate card in state: {card.code}")
        seen.add(card.code)


def _validate_accuracy(
    correct: int,
    total: int,
    accuracy: float,
    label: str,
) -> None:
    expected = correct / total if total else 0
    if not math.isclose(accuracy, expected, rel_tol=0, abs_tol=1e-12):
        raise ValueError(f"{label} accuracy does not match its counts")


def _finite_benchmark_number(value: Any) -> float | None:
    if type(value) not in {int, float}:
        return None
    numeric_error = "Benchmark numeric values must be finite and representable"
    try:
        numeric_value = float(value)
    except OverflowError as exc:
        raise ValueError(numeric_error) from exc
    if not math.isfinite(numeric_value):
        raise ValueError(numeric_error)
    return numeric_value


def benchmark_values_match(expected: Any, detected: Any) -> bool:
    expected_numeric = _finite_benchmark_number(expected)
    detected_numeric = _finite_benchmark_number(detected)
    if expected_numeric is not None and detected_numeric is not None:
        return math.isclose(expected_numeric, detected_numeric, abs_tol=0.01)
    return expected == detected


class HealthResponse(BaseModel):
    status: Literal["ok"]
    environment: DeploymentEnvironment
    parser_provider: str
    recommendation_provider: str
    recommendation_engine: str


def normalize_benchmark_value(field_name: BenchmarkFieldName, value: Any) -> Any:
    if value is None:
        return None
    if field_name in {"hero_cards", "board_cards"}:
        codes = [card.code if isinstance(card, Card) else card for card in value]
        return sorted(codes)
    if field_name in {
        "preflop_action_history",
        "postflop_action_history",
    }:
        action_model = (
            PreflopAction
            if field_name == "preflop_action_history"
            else PostflopAction
        )
        return [
            (
                action
                if isinstance(action, action_model)
                else action_model.model_validate(action)
            ).model_dump(mode="json")
            for action in value
        ]
    if field_name == "completed_postflop_streets":
        return [
            (
                history
                if isinstance(history, CompletedPostflopStreetHistory)
                else CompletedPostflopStreetHistory.model_validate(history)
            ).model_dump(mode="json")
            for history in value
        ]
    if isinstance(value, str):
        normalized = re.sub(r"\s+", " ", value.strip().lower())
        if field_name in {
            "hero_position",
            "opponent_position",
            "preflop_opener_position",
        }:
            return BENCHMARK_POSITION_ALIASES.get(normalized, normalized)
        return normalized
    return value


class DetectedState(BaseModel):
    hero_cards: list[Card] = Field(default_factory=list)
    board_cards: list[Card] = Field(default_factory=list)
    pot_size: NonNegativeFiniteNumber | None = None
    current_bet: NonNegativeFiniteNumber | None = None
    hero_stack: NonNegativeFiniteNumber | None = None
    opponent_stack: NonNegativeFiniteNumber | None = None
    effective_stack: NonNegativeFiniteNumber | None = None
    players_in_hand: PositiveInteger | None = None
    opponents_at_current_bet: PositiveInteger | None = None
    opponent_wager: PositiveFiniteNumber | None = None
    opponent_commitment_total: PositiveFiniteNumber | None = None
    hero_position: str | None = Field(default=None)
    opponent_position: str | None = Field(default=None)
    preflop_opener_position: str | None = Field(default=None)
    preflop_open_size: PositiveFiniteNumber | None = None
    preflop_action_history: list[PreflopAction] = Field(default_factory=list, max_length=8)
    street: Street | None = Field(default=None)
    facing_action: FacingAction | None = Field(default=None)
    postflop_action_history: list[PostflopAction] = Field(default_factory=list, max_length=8)
    completed_postflop_streets: list[CompletedPostflopStreetHistory] = Field(
        default_factory=list,
        max_length=2,
        exclude_if=lambda value: not value,
    )
    action_context: str | None = Field(default=None)

    @field_validator("hero_cards")
    @classmethod
    def validate_hero_card_count(cls, value: list[Card]) -> list[Card]:
        return _validate_card_count("hero_cards", value, 2)

    @field_validator("board_cards")
    @classmethod
    def validate_board_card_count(cls, value: list[Card]) -> list[Card]:
        return _validate_card_count("board_cards", value, 5)

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        _validate_unique_cards(self.hero_cards, self.board_cards)
        _validate_opponents_at_current_bet(self)
        _validate_opponent_wager(self)
        _validate_opponent_commitment_total(self)
        _validate_completed_postflop_streets(self)
        return self


class ParserResult(BaseModel):
    state: DetectedState
    confidences: dict[str, ParserConfidence] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("confidences")
    @classmethod
    def validate_confidences(cls, value: dict[str, float]) -> dict[str, float]:
        for field_name, confidence in value.items():
            if confidence < 0 or confidence > 1:
                raise ValueError(f"Confidence for {field_name} must be between 0 and 1")
        return value


class CanonicalState(BaseModel):
    hero_cards: list[Card] = Field(default_factory=list)
    board_cards: list[Card] = Field(default_factory=list)
    pot_size: NonNegativeFiniteNumber | None = None
    current_bet: NonNegativeFiniteNumber | None = None
    hero_stack: NonNegativeFiniteNumber | None = None
    opponent_stack: NonNegativeFiniteNumber | None = None
    effective_stack: NonNegativeFiniteNumber | None = None
    players_in_hand: PositiveInteger | None = None
    opponents_at_current_bet: PositiveInteger | None = None
    opponent_wager: PositiveFiniteNumber | None = None
    opponent_commitment_total: PositiveFiniteNumber | None = None
    hero_position: str | None = Field(default=None)
    opponent_position: str | None = Field(default=None)
    preflop_opener_position: str | None = Field(default=None)
    preflop_open_size: PositiveFiniteNumber | None = None
    preflop_action_history: list[PreflopAction] = Field(default_factory=list, max_length=8)
    street: Street | None = Field(default=None)
    facing_action: FacingAction | None = Field(default=None)
    postflop_action_history: list[PostflopAction] = Field(default_factory=list, max_length=8)
    completed_postflop_streets: list[CompletedPostflopStreetHistory] = Field(
        default_factory=list,
        max_length=2,
        exclude_if=lambda value: not value,
    )
    action_context: str | None = Field(default=None)
    user_approved: bool = Field(default=False)

    @field_validator("hero_cards")
    @classmethod
    def validate_hero_card_count(cls, value: list[Card]) -> list[Card]:
        return _validate_card_count("hero_cards", value, 2)

    @field_validator("board_cards")
    @classmethod
    def validate_board_card_count(cls, value: list[Card]) -> list[Card]:
        return _validate_card_count("board_cards", value, 5)

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        _validate_unique_cards(self.hero_cards, self.board_cards)
        _validate_opponents_at_current_bet(self)
        _validate_opponent_wager(self)
        _validate_opponent_commitment_total(self)
        _validate_completed_postflop_streets(self)
        return self

    @classmethod
    def from_parser_result(cls, parser_result: ParserResult) -> "CanonicalState":
        state = parser_result.state.model_copy(deep=True)
        return cls(
            hero_cards=state.hero_cards,
            board_cards=state.board_cards,
            pot_size=state.pot_size,
            current_bet=state.current_bet,
            hero_stack=state.hero_stack,
            opponent_stack=state.opponent_stack,
            effective_stack=state.effective_stack,
            players_in_hand=state.players_in_hand,
            opponents_at_current_bet=state.opponents_at_current_bet,
            opponent_wager=state.opponent_wager,
            opponent_commitment_total=state.opponent_commitment_total,
            hero_position=state.hero_position,
            opponent_position=state.opponent_position,
            preflop_opener_position=state.preflop_opener_position,
            preflop_open_size=state.preflop_open_size,
            preflop_action_history=state.preflop_action_history,
            street=state.street,
            facing_action=state.facing_action,
            postflop_action_history=state.postflop_action_history,
            completed_postflop_streets=state.completed_postflop_streets,
            action_context=state.action_context,
        )


def _validate_completed_postflop_streets(
    state: DetectedState | CanonicalState,
) -> None:
    histories = state.completed_postflop_streets
    if not histories:
        return

    expected_before = {
        "preflop": (),
        "flop": (),
        "turn": ("flop",),
        "river": ("flop", "turn"),
        None: (),
    }[state.street]
    streets = tuple(history.street for history in histories)
    if streets != expected_before[: len(streets)]:
        raise ValueError(
            "Completed postflop streets must be unique, chronological, and before the current street"
        )


def _validate_opponents_at_current_bet(
    state: DetectedState | CanonicalState,
) -> None:
    committed = state.opponents_at_current_bet
    if committed is None:
        return
    if state.current_bet is None or state.current_bet <= 0:
        raise ValueError("opponents_at_current_bet requires a positive current_bet")
    if state.players_in_hand is None:
        raise ValueError("opponents_at_current_bet requires players_in_hand")
    if committed >= state.players_in_hand:
        raise ValueError(
            "opponents_at_current_bet must be lower than players_in_hand"
        )


def _validate_opponent_wager(state: DetectedState | CanonicalState) -> None:
    wager = state.opponent_wager
    if wager is None:
        return
    if state.current_bet is None or state.current_bet <= 0:
        raise ValueError("opponent_wager requires a positive current_bet")
    if wager < state.current_bet:
        raise ValueError("opponent_wager must be at least current_bet")


def _validate_opponent_commitment_total(
    state: DetectedState | CanonicalState,
) -> None:
    total = state.opponent_commitment_total
    if total is None:
        return
    if state.pot_size is not None and total > state.pot_size + 1e-6:
        raise ValueError("opponent_commitment_total cannot exceed pot_size")
    if state.street == "preflop":
        current_street_history = state.preflop_action_history
    elif state.street is not None:
        current_street_history = state.postflop_action_history
    else:
        current_street_history = []
    recorded_wagers = [
        action.amount
        for action in current_street_history
        if action.amount is not None
    ]
    if state.opponent_wager is not None:
        wager = state.opponent_wager
        known_latest_wagers = [state.opponent_wager]
    else:
        wager = max(state.current_bet or 0, *recorded_wagers)
        known_latest_wagers = recorded_wagers
    if wager <= 0:
        return
    committed_opponents = state.opponents_at_current_bet
    minimum = wager * (committed_opponents or 1)
    if total + 1e-6 < minimum:
        raise ValueError(
            "opponent_commitment_total must cover opponents_at_current_bet"
        )
    if known_latest_wagers and state.players_in_hand is not None:
        latest_wager = max(known_latest_wagers)
        maximum = latest_wager * (state.players_in_hand - 1)
        if total > maximum + 1e-6:
            raise ValueError(
                "opponent_commitment_total cannot exceed the latest wager "
                "across active opponents"
            )


class RecommendationRequest(BaseModel):
    state: CanonicalState
    provider: str


class RecommendationResult(BaseModel):
    action: RecommendationAction
    sizing: float | None = Field(
        default=None,
        gt=0,
        allow_inf_nan=False,
        strict=True,
    )
    confidence: float = Field(
        ge=0,
        le=1,
        allow_inf_nan=False,
        strict=True,
    )
    explanation: str
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_sizing(self) -> Self:
        if self.action not in {"bet", "raise"} and self.sizing is not None:
            raise ValueError("Sizing is only valid for bet or raise recommendations")
        return self


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


class ScreenshotMetadataRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("title", "notes", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in value:
            stripped = tag.strip()
            if not stripped:
                continue
            if len(stripped) > 32:
                raise ValueError("tags must be at most 32 characters")
            if "," in stripped:
                raise ValueError("tags cannot contain commas")
            key = stripped.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(stripped)
        return normalized


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


class JobRecord(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(default_factory=lambda: uuid4().hex)
    status: Literal["created", "parsed", "approved", "recommended", "error"] = "created"
    upload_request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    original_filename: str
    title: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=10)
    image_filename: str
    parser_provider: str
    parser_layout_profile: str | None = None
    recommendation_provider: str
    recommendation_engine: str | None = None
    parser_result: ParserResult | None = None
    parser_auto_approval_eligible: bool | None = None
    approved_state: CanonicalState | None = None
    training_decision: TrainingDecision | None = None
    recommendation: RecommendationResult | None = None
    recommendation_pending: bool = False
    recommendation_request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    benchmark_import_request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=BENCHMARK_IMPORT_REQUEST_ID_PATTERN,
    )
    training_reviewed_at: datetime | None = None
    training_review_note: str | None = None
    benchmark_included: bool = False
    archived_at: datetime | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("title", "notes", mode="before")
    @classmethod
    def normalize_optional_metadata_text(cls, value: str | None) -> str | None:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("tags")
    @classmethod
    def normalize_metadata_tags(cls, value: list[str]) -> list[str]:
        return ScreenshotMetadataRequest.normalize_tags(value)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


class ArchiveJobsRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("job_ids")
    @classmethod
    def validate_job_ids(cls, value: list[str]) -> list[str]:
        unique_ids = list(dict.fromkeys(value))
        if len(unique_ids) != len(value):
            raise ValueError("job_ids must not contain duplicates")
        return value


class JobHistory(BaseModel):
    total: int = Field(ge=0)
    jobs: list[JobRecord] = Field(default_factory=list)
    snapshot_version: str


class JobQueue(BaseModel):
    total: int = Field(ge=0)
    jobs: list[JobRecord] = Field(default_factory=list)
    snapshot_version: str


class ApplicationBackupRestoreResult(BaseModel):
    imported_jobs: int = Field(ge=0)
    reused_jobs: int = Field(ge=0)
    imported_benchmark_reports: int = Field(ge=0)
    reused_benchmark_reports: int = Field(ge=0)
    total_jobs: int = Field(ge=0)
    total_benchmark_reports: int = Field(ge=0)


class BenchmarkSelectionRequest(BaseModel):
    included: bool


class BenchmarkRunRequest(BaseModel):
    parser_provider: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    parser_layout_profile: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )


class BenchmarkDatasetImportResult(BaseModel):
    imported_cases: int = Field(ge=0)
    reused_cases: int = Field(ge=0)
    included_cases: int = Field(ge=0)
    included_cases_by_layout: dict[str, NonNegativeInteger] | None = None
    job_ids: list[str] = Field(default_factory=list)


class BenchmarkDatasetImportReceipt(BaseModel):
    request_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=BENCHMARK_IMPORT_REQUEST_ID_PATTERN,
    )
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["pending", "completed", "failed"]
    result: BenchmarkDatasetImportResult | None = None
    error: str | None = None
    error_status: int | None = Field(default=None, ge=400, le=599)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status == "completed" and (
            self.result is None
            or self.error is not None
            or self.error_status is not None
        ):
            raise ValueError("completed import receipts require a result")
        if self.status == "failed" and (
            self.result is not None
            or self.error is None
            or self.error_status is None
        ):
            raise ValueError("failed import receipts require an error")
        if self.status == "pending" and (
            self.result is not None
            or self.error is not None
            or self.error_status is not None
        ):
            raise ValueError("pending import receipts cannot contain a result")
        return self


_BENCHMARK_CARD_LIMITS = {"hero_cards": 2, "board_cards": 5}
_BENCHMARK_NONNEGATIVE_NUMERIC_FIELDS = {
    "pot_size",
    "current_bet",
    "hero_stack",
    "opponent_stack",
    "effective_stack",
}
_BENCHMARK_TEXT_FIELDS = {
    "hero_position",
    "opponent_position",
    "preflop_opener_position",
    "action_context",
}


def _validate_benchmark_comparison_value(
    field_name: BenchmarkFieldName,
    value: Any,
    *,
    allow_none: bool,
) -> None:
    if value is None:
        if allow_none:
            return
        raise ValueError(f"Benchmark {field_name} expected value is required")

    if field_name in _BENCHMARK_CARD_LIMITS:
        if (
            type(value) is not list
            or len(value) > _BENCHMARK_CARD_LIMITS[field_name]
        ):
            raise ValueError(f"Benchmark {field_name} must contain card codes")
        card_codes: list[str] = []
        for code in value:
            if type(code) is not str:
                raise ValueError(f"Benchmark {field_name} must contain card codes")
            try:
                card = Card.from_code(code)
            except ValueError as exc:
                raise ValueError(
                    f"Benchmark {field_name} must contain card codes"
                ) from exc
            if card.code != code:
                raise ValueError(f"Benchmark {field_name} card codes must be canonical")
            card_codes.append(code)
        if len(card_codes) != len(set(card_codes)):
            raise ValueError(f"Benchmark {field_name} card codes must be unique")
        if card_codes != sorted(card_codes):
            raise ValueError(f"Benchmark {field_name} card codes must be sorted")
        if not allow_none and field_name == "hero_cards" and not card_codes:
            raise ValueError("Benchmark hero_cards expected value cannot be empty")
        return

    if field_name in _BENCHMARK_NONNEGATIVE_NUMERIC_FIELDS:
        numeric_value = _finite_benchmark_number(value)
        if numeric_value is None or numeric_value < 0:
            raise ValueError(f"Benchmark {field_name} must be a non-negative number")
        return

    if field_name == "preflop_open_size":
        numeric_value = _finite_benchmark_number(value)
        if numeric_value is None or numeric_value <= 0:
            raise ValueError("Benchmark preflop_open_size must be a positive number")
        return

    if field_name == "players_in_hand":
        if type(value) is not int or value <= 0:
            raise ValueError("Benchmark players_in_hand must be a positive integer")
        return

    if field_name == "street":
        if type(value) is not str or value not in {"preflop", "flop", "turn", "river"}:
            raise ValueError("Benchmark street value is invalid")
        return

    if field_name == "facing_action":
        if type(value) is not str or value not in {"bet", "raise"}:
            raise ValueError("Benchmark facing_action value is invalid")
        return

    if field_name in {"preflop_action_history", "postflop_action_history"}:
        action_model = (
            PreflopAction
            if field_name == "preflop_action_history"
            else PostflopAction
        )
        if type(value) is not list or len(value) > 8:
            raise ValueError(f"Benchmark {field_name} must contain actions")
        if not allow_none and not value:
            raise ValueError(f"Benchmark {field_name} expected value cannot be empty")
        for item in value:
            if type(item) is not dict:
                raise ValueError(f"Benchmark {field_name} must contain actions")
            try:
                normalized = action_model.model_validate(item).model_dump(mode="json")
            except ValidationError as exc:
                raise ValueError(
                    f"Benchmark {field_name} must contain valid actions"
                ) from exc
            if normalized != item:
                raise ValueError(f"Benchmark {field_name} actions must be canonical")
        return

    if field_name == "completed_postflop_streets":
        if type(value) is not list or len(value) > 2:
            raise ValueError(
                "Benchmark completed_postflop_streets must contain street histories"
            )
        if not allow_none and not value:
            raise ValueError(
                "Benchmark completed_postflop_streets expected value cannot be empty"
            )
        for item in value:
            if type(item) is not dict:
                raise ValueError(
                    "Benchmark completed_postflop_streets must contain street histories"
                )
            try:
                normalized = CompletedPostflopStreetHistory.model_validate(
                    item
                ).model_dump(mode="json")
            except ValidationError as exc:
                raise ValueError(
                    "Benchmark completed_postflop_streets must contain valid street histories"
                ) from exc
            if normalized != item:
                raise ValueError(
                    "Benchmark completed_postflop_streets histories must be canonical"
                )
        return

    if field_name in _BENCHMARK_TEXT_FIELDS:
        if type(value) is not str:
            raise ValueError(f"Benchmark {field_name} must be text")
        if not allow_none and field_name == "action_context" and not value.strip():
            raise ValueError("Benchmark action_context expected value cannot be empty")
        if value != normalize_benchmark_value(field_name, value):
            raise ValueError(f"Benchmark {field_name} text must be normalized")
        return

    raise ValueError(f"Benchmark comparison field {field_name} is unsupported")


class BenchmarkFieldComparison(BaseModel):
    field: BenchmarkFieldName
    expected: Any
    detected: Any
    matched: bool = Field(strict=True)
    confidence: UnitIntervalNumber | None = None

    @model_validator(mode="after")
    def validate_match(self) -> Self:
        _validate_benchmark_comparison_value(
            self.field,
            self.expected,
            allow_none=False,
        )
        _validate_benchmark_comparison_value(
            self.field,
            self.detected,
            allow_none=True,
        )
        if self.matched != benchmark_values_match(self.expected, self.detected):
            raise ValueError("Benchmark comparison matched flag is inconsistent")
        return self


class BenchmarkParserRouting(BaseModel):
    provider: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    selected_provider: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    layout_profile: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    fallback_from: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    fallback_reason: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_fallback(self) -> Self:
        if (self.fallback_from is None) != (self.fallback_reason is None):
            raise ValueError(
                "Benchmark parser fallback source and reason must be recorded together"
            )
        return self


class BenchmarkCaseResult(BaseModel):
    job_id: str
    original_filename: str
    status: Literal["completed", "error"]
    correct_fields: NonNegativeInteger
    evaluated_fields: NonNegativeInteger
    accuracy: UnitIntervalNumber
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    parser_routing: BenchmarkParserRouting | None = None
    comparisons: list[BenchmarkFieldComparison] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        fields = [comparison.field for comparison in self.comparisons]
        if len(fields) != len(set(fields)):
            raise ValueError("Benchmark case comparison fields must be unique")
        card_comparisons = [
            comparison
            for comparison in self.comparisons
            if comparison.field in {"hero_cards", "board_cards"}
        ]
        for side in ("expected", "detected"):
            card_codes = [
                code
                for comparison in card_comparisons
                for code in getattr(comparison, side) or []
            ]
            if len(card_codes) != len(set(card_codes)):
                raise ValueError(
                    f"Benchmark case {side} cards must be unique across fields"
                )
        if self.evaluated_fields != len(self.comparisons):
            raise ValueError("Benchmark case evaluated_fields does not match comparisons")
        matched = sum(comparison.matched for comparison in self.comparisons)
        if self.correct_fields != matched:
            raise ValueError("Benchmark case correct_fields does not match comparisons")
        _validate_accuracy(
            self.correct_fields,
            self.evaluated_fields,
            self.accuracy,
            "Benchmark case",
        )
        if self.status == "completed" and self.error is not None:
            raise ValueError("Completed benchmark cases cannot contain an error")
        if self.status == "error" and self.error is None:
            raise ValueError("Failed benchmark cases require an error")
        return self


class BenchmarkFieldMetric(BaseModel):
    field: BenchmarkFieldName
    correct: NonNegativeInteger
    total: NonNegativeInteger
    accuracy: UnitIntervalNumber

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        if self.correct > self.total:
            raise ValueError("Benchmark field correct count cannot exceed total")
        _validate_accuracy(
            self.correct,
            self.total,
            self.accuracy,
            "Benchmark field",
        )
        return self


class BenchmarkReport(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    parser_provider: str
    layout_profile: str
    corpus_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_cases: NonNegativeInteger
    successful_cases: NonNegativeInteger
    failed_cases: NonNegativeInteger
    correct_fields: NonNegativeInteger
    evaluated_fields: NonNegativeInteger
    accuracy: UnitIntervalNumber
    field_metrics: list[BenchmarkFieldMetric] = Field(default_factory=list)
    cases: list[BenchmarkCaseResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        case_ids = [case.job_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Benchmark report case job IDs must be unique")
        if self.total_cases != len(self.cases):
            raise ValueError("Benchmark report total_cases does not match cases")
        successful_cases = sum(case.status == "completed" for case in self.cases)
        failed_cases = len(self.cases) - successful_cases
        if self.successful_cases != successful_cases:
            raise ValueError("Benchmark report successful_cases does not match cases")
        if self.failed_cases != failed_cases:
            raise ValueError("Benchmark report failed_cases does not match cases")
        correct_fields = sum(case.correct_fields for case in self.cases)
        evaluated_fields = sum(case.evaluated_fields for case in self.cases)
        if self.correct_fields != correct_fields:
            raise ValueError("Benchmark report correct_fields does not match cases")
        if self.evaluated_fields != evaluated_fields:
            raise ValueError("Benchmark report evaluated_fields does not match cases")
        _validate_accuracy(
            self.correct_fields,
            self.evaluated_fields,
            self.accuracy,
            "Benchmark report",
        )

        field_counts: dict[str, list[int]] = {}
        for case in self.cases:
            if (
                case.parser_routing is not None
                and case.parser_routing.provider != self.parser_provider
            ):
                raise ValueError(
                    "Benchmark case routing provider does not match the report"
                )
            if (
                case.parser_routing is not None
                and case.parser_routing.layout_profile != self.layout_profile
            ):
                raise ValueError(
                    "Benchmark case routing layout does not match the report"
                )
            for comparison in case.comparisons:
                counts = field_counts.setdefault(comparison.field, [0, 0])
                counts[1] += 1
                if comparison.matched:
                    counts[0] += 1
        metric_fields = [metric.field for metric in self.field_metrics]
        if len(metric_fields) != len(set(metric_fields)):
            raise ValueError("Benchmark report field metrics must be unique")
        if set(metric_fields) != set(field_counts):
            raise ValueError("Benchmark report field metrics do not match comparisons")
        for metric in self.field_metrics:
            correct, total = field_counts[metric.field]
            if metric.correct != correct or metric.total != total:
                raise ValueError("Benchmark report field metric counts do not match comparisons")
        return self


class BenchmarkReportSummary(BaseModel):
    id: str
    parser_provider: str
    layout_profile: str
    corpus_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    created_at: datetime
    total_cases: NonNegativeInteger
    failed_cases: NonNegativeInteger
    accuracy: UnitIntervalNumber
    field_metrics: list[BenchmarkFieldMetric] = Field(default_factory=list)

    @classmethod
    def from_report(cls, report: BenchmarkReport) -> "BenchmarkReportSummary":
        return cls(
            id=report.id,
            parser_provider=report.parser_provider,
            layout_profile=report.layout_profile,
            corpus_fingerprint=report.corpus_fingerprint,
            created_at=report.created_at,
            total_cases=report.total_cases,
            failed_cases=report.failed_cases,
            accuracy=report.accuracy,
            field_metrics=report.field_metrics,
        )


class BenchmarkParserPipelineSummary(BaseModel):
    parser: PipelineOption
    layout_profile: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    latest_report: BenchmarkReportSummary | None = None
    previous_report: BenchmarkReportSummary | None = None

    @model_validator(mode="after")
    def validate_report_pipeline(self) -> Self:
        for label, report in (
            ("Latest", self.latest_report),
            ("Previous", self.previous_report),
        ):
            if report is None:
                continue
            if report.parser_provider != self.parser.id:
                raise ValueError(f"{label} benchmark report does not match parser")
            if report.layout_profile != self.layout_profile:
                raise ValueError(f"{label} benchmark report does not match layout")
        if self.previous_report is None:
            return self
        if self.latest_report is None:
            raise ValueError("Previous benchmark report requires a latest report")
        if (
            self.latest_report.corpus_fingerprint is None
            or self.previous_report.corpus_fingerprint
            != self.latest_report.corpus_fingerprint
        ):
            raise ValueError("Pipeline benchmark reports must use the same corpus")
        if (
            self.previous_report.created_at,
            self.previous_report.id,
        ) >= (
            self.latest_report.created_at,
            self.latest_report.id,
        ):
            raise ValueError("Previous benchmark report must precede latest report")
        return self


class BenchmarkOverview(BaseModel):
    included_cases: NonNegativeInteger
    included_cases_by_layout: dict[str, NonNegativeInteger]
    corpus_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    default_layout_profile: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    latest_report: BenchmarkReport | None = None
    recent_reports: list[BenchmarkReportSummary] = Field(default_factory=list)
    parser_pipelines: list[BenchmarkParserPipelineSummary] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_layout_counts(self) -> Self:
        if sum(self.included_cases_by_layout.values()) != self.included_cases:
            raise ValueError("Benchmark layout counts must match included cases")
        parser_ids = [pipeline.parser.id for pipeline in self.parser_pipelines]
        if len(parser_ids) != len(set(parser_ids)):
            raise ValueError("Benchmark parser pipelines must be unique")
        return self
