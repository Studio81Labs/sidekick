from pathlib import Path
from typing import Protocol

from app.domain.poker import ParserResult


class ParserError(RuntimeError):
    pass


class ParserConfigurationError(ParserError):
    pass


class ScreenshotParser(Protocol):
    name: str

    def parse(self, image_path: Path) -> ParserResult:
        raise NotImplementedError
