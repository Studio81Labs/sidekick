"""Provider-neutral recommendation contracts."""

from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.domain.poker import CanonicalState


RecommendationAction = Literal["fold", "check", "call", "bet", "raise"]


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
