from json import JSONDecodeError
from pathlib import Path

import httpx
from pydantic import ValidationError

from app.config import Settings
from app.domain.poker import ParserResult
from app.http_auth import bearer_headers
from app.parsers.base import ParserConfigurationError, ParserError


class HttpVisionParser:
    name = "llm_vision"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def parse(self, image_path: Path) -> ParserResult:
        if not self.settings.external_parser_url:
            raise ParserConfigurationError("POKER_EXTERNAL_PARSER_URL is required for llm_vision parser")
        if not image_path.is_file():
            raise ParserError(f"Screenshot file does not exist or is not a file: {image_path}")

        try:
            with image_path.open("rb") as image_file:
                response = httpx.post(
                    self.settings.external_parser_url,
                    files={"image": (image_path.name, image_file, "application/octet-stream")},
                    data={"layout_profile": self.settings.parser_layout_profile},
                    headers=bearer_headers(self.settings.external_parser_bearer_token),
                    timeout=self.settings.external_request_timeout_seconds,
                )
        except OSError as exc:
            raise ParserError(f"Could not read screenshot file: {image_path}") from exc
        except httpx.RequestError as exc:
            raise ParserError(f"Vision parser request failed for {self.settings.external_parser_url}: {exc}") from exc

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ParserError(f"Vision parser request failed with status {exc.response.status_code}") from exc

        try:
            payload = response.json()
        except JSONDecodeError as exc:
            raise ParserError("Vision parser returned invalid JSON") from exc

        try:
            return ParserResult.model_validate(payload)
        except ValidationError as exc:
            raise ParserError("Vision parser returned invalid payload") from exc
