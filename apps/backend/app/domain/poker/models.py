"""Provider-neutral poker values and action-history validation."""

import math
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator


Rank = Literal["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
Suit = Literal["clubs", "diamonds", "hearts", "spades"]
Street = Literal["preflop", "flop", "turn", "river"]
FacingAction = Literal["bet", "raise"]
PreflopPosition = Literal[
    "utg",
    "hijack",
    "cutoff",
    "button",
    "small_blind",
    "big_blind",
]
PreflopActionType = Literal["call", "raise"]
PostflopActor = Literal["oop", "ip"]
PostflopActionType = Literal["check", "bet", "raise"]
CompletedPostflopActionType = Literal["check", "bet", "raise", "call"]
CompletedPostflopStreet = Literal["flop", "turn"]
NonNegativeFiniteNumber = Annotated[
    float,
    Field(ge=0, allow_inf_nan=False, strict=True),
]
PositiveFiniteNumber = Annotated[
    float,
    Field(gt=0, allow_inf_nan=False, strict=True),
]
PositiveInteger = Annotated[int, Field(ge=1, strict=True)]

RANKS = {"2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"}
SUIT_BY_CODE = {
    "c": "clubs",
    "d": "diamonds",
    "h": "hearts",
    "s": "spades",
}
CODE_BY_SUIT = {value: key for key, value in SUIT_BY_CODE.items()}


class Card(BaseModel):
    rank: Rank
    suit: Suit

    @field_validator("rank", mode="before")
    @classmethod
    def validate_rank(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        normalized = value.upper()
        if normalized == "10":
            normalized = "T"
        if normalized not in RANKS:
            raise ValueError(f"Unknown card rank: {value}")
        return normalized

    @field_validator("suit", mode="before")
    @classmethod
    def validate_suit(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        normalized = value.lower()
        if normalized in SUIT_BY_CODE:
            normalized = SUIT_BY_CODE[normalized]
        if normalized not in CODE_BY_SUIT:
            raise ValueError(f"Unknown card suit: {value}")
        return normalized

    @property
    def code(self) -> str:
        return f"{self.rank}{CODE_BY_SUIT[self.suit]}"

    @classmethod
    def from_code(cls, value: str) -> "Card":
        stripped = value.strip()
        if len(stripped) not in {2, 3}:
            raise ValueError(f"Card code must be rank plus suit: {value}")
        rank = stripped[:-1]
        suit = stripped[-1]
        return cls(rank=rank, suit=suit)


class PostflopAction(BaseModel):
    actor: PostflopActor
    action: PostflopActionType
    amount: PositiveFiniteNumber | None = None

    @model_validator(mode="after")
    def validate_amount(self) -> Self:
        if self.action == "check" and self.amount is not None:
            raise ValueError("A postflop check cannot have an amount")
        if self.action in {"bet", "raise"} and self.amount is None:
            raise ValueError(f"A postflop {self.action} requires an amount")
        return self


class CompletedPostflopAction(BaseModel):
    actor: PostflopActor
    action: CompletedPostflopActionType
    amount: PositiveFiniteNumber | None = None

    @model_validator(mode="after")
    def validate_amount(self) -> Self:
        if self.action == "check" and self.amount is not None:
            raise ValueError("A completed postflop check cannot have an amount")
        if self.action in {"bet", "raise", "call"} and self.amount is None:
            raise ValueError(
                f"A completed postflop {self.action} requires an amount"
            )
        return self


class CompletedPostflopStreetHistory(BaseModel):
    street: CompletedPostflopStreet
    actions: list[CompletedPostflopAction] = Field(
        min_length=2,
        max_length=8,
    )

    @model_validator(mode="after")
    def validate_completed_line(self) -> Self:
        contributions: dict[PostflopActor, float] = {"oop": 0.0, "ip": 0.0}
        next_actor: PostflopActor = "oop"
        terminal = False
        previous_action: CompletedPostflopActionType | None = None

        for index, action in enumerate(self.actions):
            if terminal:
                raise ValueError(
                    f"The completed {self.street} history continues after its terminal action"
                )
            if action.actor != next_actor:
                raise ValueError(
                    f"The completed {self.street} history must alternate from OOP"
                )
            opponent: PostflopActor = "ip" if action.actor == "oop" else "oop"
            actor_total = contributions[action.actor]
            opponent_total = contributions[opponent]

            if action.action == "check":
                if not math.isclose(
                    actor_total,
                    opponent_total,
                    rel_tol=0,
                    abs_tol=0.01,
                ):
                    raise ValueError(
                        f"A completed {self.street} check cannot face a wager"
                    )
                terminal = previous_action == "check"
            elif action.action == "bet":
                if (
                    not math.isclose(
                        actor_total,
                        opponent_total,
                        rel_tol=0,
                        abs_tol=0.01,
                    )
                    or actor_total > 0.01
                ):
                    raise ValueError(
                        f"A completed {self.street} bet requires an unopened street"
                    )
                contributions[action.actor] = action.amount or 0.0
            elif action.action == "raise":
                if (
                    actor_total >= opponent_total - 0.01
                    or (action.amount or 0.0) <= opponent_total + 0.01
                ):
                    raise ValueError(
                        f"A completed {self.street} raise must increase a faced wager"
                    )
                contributions[action.actor] = action.amount or 0.0
            else:
                if (
                    actor_total >= opponent_total - 0.01
                    or not math.isclose(
                        action.amount or 0.0,
                        opponent_total,
                        rel_tol=0,
                        abs_tol=0.01,
                    )
                ):
                    raise ValueError(
                        f"A completed {self.street} call must match the faced total"
                    )
                contributions[action.actor] = opponent_total
                terminal = True

            previous_action = action.action
            next_actor = opponent
            if terminal and index != len(self.actions) - 1:
                raise ValueError(
                    f"The completed {self.street} history continues after its terminal action"
                )

        if not terminal:
            raise ValueError(
                f"The completed {self.street} history must end with check-check or a call"
            )
        return self


class PreflopAction(BaseModel):
    actor: PreflopPosition
    action: PreflopActionType
    amount: PositiveFiniteNumber
