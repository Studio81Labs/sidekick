from typing import Protocol

from app.domain.poker import CanonicalState
from app.models import RecommendationRequest, RecommendationResult


class ProviderError(RuntimeError):
    pass


class ProviderConfigurationError(ProviderError):
    pass


class ProviderInputError(ProviderError):
    pass


class RecommendationProvider(Protocol):
    name: str
    required_fields: list[str]

    def required_fields_for(self, state: CanonicalState) -> list[str]:
        raise NotImplementedError

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        raise NotImplementedError


def field_has_value(state: CanonicalState, field_name: str) -> bool:
    if field_name not in state.__class__.model_fields:
        raise ProviderConfigurationError(f"Unknown required field: {field_name}")

    try:
        value = getattr(state, field_name)
    except AttributeError as exc:
        raise ProviderConfigurationError(f"Unknown required field: {field_name}") from exc

    if isinstance(value, list):
        return len(value) > 0
    if isinstance(value, str):
        return value.strip() != ""
    return value is not None


def missing_required_fields(state: CanonicalState, required_fields: list[str]) -> list[str]:
    return [field_name for field_name in required_fields if not field_has_value(state, field_name)]
