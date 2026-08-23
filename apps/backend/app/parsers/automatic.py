from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.domain.poker import ParserResult
from app.ocr_layouts import OCR_CV_LAYOUT_PROFILE_IDS
from app.parsers.base import ParserError
from app.parsers.http_vision import HttpVisionParser
from app.parsers.ocr_cv import OcrCvParser

AUTO_LOCAL_OCR_LAYOUT_PROFILE_IDS = OCR_CV_LAYOUT_PROFILE_IDS - {"generic"}


class AutomaticParser:
    name = "auto"

    def __init__(self, settings: Settings) -> None:
        self.layout_profile = settings.parser_layout_profile
        self._local_parser = (
            OcrCvParser(self.layout_profile)
            if self.layout_profile in AUTO_LOCAL_OCR_LAYOUT_PROFILE_IDS
            else None
        )
        self._external_parser = HttpVisionParser(settings)

    def parse(self, image_path: Path) -> ParserResult:
        if self._local_parser is None:
            return self._with_routing(
                self._external_parser.parse(image_path),
                selected_provider=self._external_parser.name,
            )

        try:
            result = self._local_parser.parse(image_path)
        except ParserError as local_error:
            try:
                result = self._external_parser.parse(image_path)
            except ParserError as external_error:
                raise ParserError(
                    "Automatic recognition could not parse the screenshot. "
                    f"Local OCR: {local_error}. External vision: {external_error}"
                ) from external_error
            return self._with_routing(
                result,
                selected_provider=self._external_parser.name,
                fallback_from=self._local_parser.name,
                fallback_reason=str(local_error),
            )

        return self._with_routing(
            result,
            selected_provider=self._local_parser.name,
        )

    def _with_routing(
        self,
        result: ParserResult,
        *,
        selected_provider: str,
        fallback_from: str | None = None,
        fallback_reason: str | None = None,
    ) -> ParserResult:
        routing: dict[str, str] = {
            "provider": self.name,
            "selected_provider": selected_provider,
            "layout_profile": self.layout_profile,
        }
        if fallback_from is not None:
            routing["fallback_from"] = fallback_from
        if fallback_reason is not None:
            routing["fallback_reason"] = fallback_reason
        return result.model_copy(
            update={
                "raw": {
                    **result.raw,
                    "parser_routing": routing,
                }
            }
        )
