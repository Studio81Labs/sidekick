from json import JSONDecodeError

import httpx
from pydantic import SecretStr, ValidationError

from app.domain.poker import CanonicalState
from app.http_auth import bearer_headers
from app.models import RecommendationRequest, RecommendationResult
from app.providers.base import ProviderConfigurationError, ProviderError


class HttpRecommendationProvider:
    required_fields = ["hero_cards", "street", "pot_size"]

    def __init__(
        self,
        name: str,
        url: str | None,
        missing_message: str,
        bearer_token: SecretStr | None,
        timeout_seconds: float,
    ) -> None:
        self.name = name
        self.url = url
        self.missing_message = missing_message
        self.bearer_token = bearer_token
        self.timeout_seconds = timeout_seconds

    def required_fields_for(self, state: CanonicalState) -> list[str]:
        return self.required_fields

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        if not self.url:
            raise ProviderConfigurationError(self.missing_message)

        payload = request.model_dump(mode="json")
        state_payload = payload["state"]
        for field in (
            "preflop_opener_position",
            "preflop_open_size",
            "opponent_stack",
            "opponents_at_current_bet",
            "opponent_wager",
            "opponent_commitment_total",
            "opponent_position",
        ):
            if state_payload[field] is None:
                del state_payload[field]
        for history_field in (
            "preflop_action_history",
            "postflop_action_history",
            "completed_postflop_streets",
        ):
            if not state_payload.get(history_field):
                state_payload.pop(history_field, None)

        try:
            response = httpx.post(
                self.url,
                json=payload,
                headers=bearer_headers(self.bearer_token),
                timeout=self.timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise ProviderError(f"{self.name} request failed for {self.url}: {exc}") from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"{self.name} request failed with status {exc.response.status_code}") from exc

        try:
            payload = response.json()
        except JSONDecodeError as exc:
            raise ProviderError(f"{self.name} returned invalid JSON") from exc

        try:
            return RecommendationResult.model_validate(payload)
        except ValidationError as exc:
            raise ProviderError(f"{self.name} returned invalid payload") from exc
