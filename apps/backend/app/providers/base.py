from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from app.domain.poker import CanonicalState
from app.domain.recommendations import RecommendationRequest, RecommendationResult


class ProviderError(RuntimeError):
    pass


class ProviderConfigurationError(ProviderError):
    pass


class ProviderInputError(ProviderError):
    pass


@dataclass(frozen=True)
class ProviderGradingContextBinding:
    """Provider-configured route context that the selected engine consumes.

    The context is raw so the benchmark can validate and fingerprint it without
    trusting a provider-computed digest. Providers must derive the complete
    catalog from immutable adapter/engine configuration before seeing a case.
    """

    route_id: str
    engine_id: str
    engine_revision: str
    configuration_sha256: str
    binding_revision: str
    context: Mapping[str, object]


class RecommendationProvider(Protocol):
    name: str
    required_fields: list[str]

    def required_fields_for(self, state: CanonicalState) -> list[str]:
        raise NotImplementedError

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        raise NotImplementedError


class GradingContextBoundRecommendationProvider(Protocol):
    def grading_context_bindings(
        self,
    ) -> Sequence[ProviderGradingContextBinding] | None:
        """Return the engine's configured schema-v5 route catalog, if supported."""

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
