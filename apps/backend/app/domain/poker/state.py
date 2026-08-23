"""Detected and user-approved poker state contracts."""

from typing import Annotated, Any, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.poker.models import (
    Card,
    CompletedPostflopStreetHistory,
    FacingAction,
    NonNegativeFiniteNumber,
    PositiveFiniteNumber,
    PositiveInteger,
    PostflopAction,
    PreflopAction,
    Street,
)


ParserConfidence = Annotated[
    float,
    Field(allow_inf_nan=False, strict=True),
]


def _validate_card_count(field_name: str, cards: list[Card], maximum: int) -> list[Card]:
    if len(cards) > maximum:
        raise ValueError(f"{field_name} cannot contain more than {maximum} cards")
    return cards


def _validate_unique_cards(hero_cards: list[Card], board_cards: list[Card]) -> None:
    seen: set[str] = set()
    for card in [*hero_cards, *board_cards]:
        if card.code in seen:
            raise ValueError(f"Duplicate card in state: {card.code}")
        seen.add(card.code)


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
