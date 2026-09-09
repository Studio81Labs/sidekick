from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Literal, cast

from PIL import Image, ImageOps, UnidentifiedImageError

from app.domain.poker import Card, DetectedState, ParserResult, Rank, Street, Suit
from app.ocr_layouts import (
    FORTUNA_NATIONS_LAYOUT,
    CardSlot,
    OcrLayout,
    PixelBox,
    TextMode,
    get_ocr_layout,
)
from app.parsers.base import ParserConfigurationError, ParserError

BASE_WIDTH = FORTUNA_NATIONS_LAYOUT.base_width
BASE_HEIGHT = FORTUNA_NATIONS_LAYOUT.base_height
MIN_RANK_PIXELS = 12
RANK_THRESHOLD = 145
RANK_TEMPLATE_WIDTH = 12
RANK_TEMPLATE_HEIGHT = 18
RANK_MATCH_THRESHOLD = 0.58

RankMask = tuple[str, ...]


@dataclass(frozen=True)
class ParsedCard:
    card: Card
    slot: str
    confidence: float
    rank_score: float
    suit_confidence: float


@dataclass(frozen=True)
class NumberRead:
    value: float
    text: str
    confidence: float


@dataclass(frozen=True)
class DecimalCandidate:
    value: float
    start: int
    end: int
    source: str


@dataclass(frozen=True)
class MoneyScale:
    scale: float
    display_unit: Literal["bb", "cash"]
    big_blind: float | None


POT_BOX = FORTUNA_NATIONS_LAYOUT.pot_box
HERO_STACK_BOX = FORTUNA_NATIONS_LAYOUT.hero_stack_box
CALL_AMOUNT_BOX = FORTUNA_NATIONS_LAYOUT.call_amount_box
RAISE_TO_AMOUNT_BOX = FORTUNA_NATIONS_LAYOUT.raise_to_amount_box
HEADER_STAKES_BOX = FORTUNA_NATIONS_LAYOUT.header_stakes_box
ACTION_CONTROL_MIN_CONFIDENCE = 0.7

OPPONENT_SEATS = FORTUNA_NATIONS_LAYOUT.opponent_seats

NUMERIC_TEMPLATE_WIDTH = 10
NUMERIC_TEMPLATE_HEIGHT = 16
NUMERIC_MATCH_THRESHOLD = 0.42

NUMERIC_TEMPLATES: dict[str, tuple[str, ...]] = {
    "0": (
        "0000111000011111111001111111100110000111011000000101100000011000000001100000000110000000011000000001100000000110000000011000000001100000000110000000010110000001",
        "0001111100001111110000111111001110000111111000011111100001111110000111111000011111100001111110000111111000011111100001110010000111001111110000111111000001111000",
        "0011111100001111110000111111110010000111001000011111100000111110000011111000001111100000111110000011111000011100100001110010000111001111111100011111000001111100",
        "0000111000000111111001100001110110000001011000000111100000011000000001100000000110000000011000000001100000000101100000010110000001011000011100011111100000111110",
        "1111111110100000011010000001101000000001100000000110000011101000001110111111100010000001111000000001100000000110000000011000000001100000011110000001111111111110",
        "0001111000011111111001100001100110000110100000000110000000011000000001100000000110000000011000000000110000000110000000010110000001011000000101100001100001111110",
        "0001111110011100011101100000010110000001111000000110000000011000000001100000000110000000011000000001100000000101100000010110000001011000000101111111100001111000",
        "0001110000011111100011100001101000000110100000011010000000011000000001100000000110000000011000000000110000000110000001101000000110111000011001111110000001110000",
        "0000110000011111111001100001101000000001100000000110000000011000000001100000000110000000011000000000110000000110000000011000000001011000011001111110000000110000",
        "0100000010110000001111000000111100000011110000001111000000111100000011110000001111000000111100000011010000001101000000110111001110011111111001111111100000110000",
        "1100000011110000001111000000111100000011110000001111000000111100000011110000001101000000110100000011011100111001110011100111111110011111111000001100000000110000",
    ),
    "1": (
        "0000011111000001111111111111111111111111111111111100000111110000011111000001111100000111110000011111000001111100000111110000011111000001111100000111110000011111",
        "0111111111000000000000000000000000000000000000000001000011001100000000000001001000000100100000010010000001001000000100100000010010000000000000000011000000000000",
        "0000000111000111111111111111111111111111000000011100000001110000000111000000011100000001110000000111000000011100000001110000000111000000011100000001110000000111",
        "0000000111111111111111111111111111111111000000011100000001110000000111000000011100000001110000000111000000011100000001110000000111000000011100000001110000000111",
    ),
    "2": (
        "0011111000111111110011111111000000000011000000001100000000110000000011000000001100000000110000000100000000010000000001000000011000000110000000011000000010000000",
        "0011111000111111110000000001110000000111000000001100000000110000000011000000010000000001000000011000000001100000011000000010000000001000000011111111111111111111",
        "0000000011000000001100000000110000000011000000111000000011100000011110000001110000000111000000110000001110000000111000000111111111111111111111111111110100000001",
        "0000000111000000011100000001110000000111000000111000000011100000111000000011100000011100000001110000011100000001110000001111111111111111111111111111111111111111",
        "1111111000111111100011111111000000000100000000010000000001000000011100000001110000000111000000011100000111100000111000000011100000111111111111111111111111111111",
    ),
    "3": (
        "0011111000111111110000000000110000000011000000001100000000110000011100000111100000011110000000000100000000001100000000110000000011000000001100000001001111111100",
        "0011111000111111110000000001110000000111000000001100000000110000011100000111100000011110000000011100000000001100000000110000000011000000001100000001001111111100",
        "1111111111111111111111111111110000000011000000001100000011110011111100001111110000001111110000111111000000001100000000110000000011111111111111111111001111111100",
    ),
    "4": (
        "0000011110000001111000000111100000111110000011111000001000100011000010001100001000110000100011000010010000001011000000101100000010111111111111111111111111111111",
        "0000011100000001110000000111000001111100000111110000111111000010000100001000010011000001001100000100111111111111111111111111111111000000010000000001000000000100",
        "0000001110000000111000001111100000111110000011111000011111100111001110011100111001100011100110001110111111111111111111111111111111000000111000000011100000001110",
        "0000001110000001111000000111100000011110000010001000000000100011000010010000001001000000100100000010111111111111111111110000000010000000001000000000100000000010",
    ),
    "5": (
        "1111111111111111111111111111110000000000000000000000000000000000000000111111000011111100001111111111000000001100000000110000000011000000001100000000110000000011",
        "1111111100111111110011111111000000000100000000010000000001000000000100111111110011111111001111111000000000010000000001000000000011000000001100000000110000000111",
        "1111111111001111111100111111110010000000001000000000100000000011111100001111111100111111110000000111000000011100000001111100011111111111110011111111000001100000",
        "1111111111111111111111111111111100000000110000000011111100001111111111111111111100000011110000001111000000001100000000110000000011111111111111111111001111111100",
        "1111111111111111111111000000001100000000110000000011111000001111111100000000011100000001110000000011000000001100000000110000000111000000011111111111000011111000",
        "0111111110011111111001100000000110000000011000000001100000000111111000011111111001111111100000000111000000000100000000010000000111000000011100000011101111111000",
        "0111111110011111111001100000000110000000011000000001100000000111110000011111111001111111100000000110000000000100000000010000000110000000011000000001101111111000",
        "0111111110011000000000000000000000000000000000000001110000000111111000000000011000000001100000000111000000000100000001100000000110000000011011111110000001000000",
        "1111111111110000000011000000001100000000110000000011111000001111111100000000011100000001110000000011000000001100000000110000000100000000010011111111000011100000",
        "1000000000100000000010000000001110000000111111111011111111100000001111000000011100000001110000000111000000011100000001110000001111111111111011111111100111110000",
        "1111111110111111111000000011110000001111000000011100000001110000000111000000011100000001110000000111000000111100000011111111111110111111111001111100000111110000",
    ),
    "6": (
        "0000111000000111111001100000000000000000000000000010000000001000000000111111111011100001111000000001100000000110000000011000000001011000000100011111100000111000",
        "0000111000011111111001100000001000000000100000000010000000001000000000111111111010000001101000000001100000000110000000011000000001011000011001111111100000110000",
        "0000111110000111111100011111110110000000011000000000000000000000000000100000100011111111101110000001111000000110000000010110000001011000000101100000010111000001",
    ),
    "7": (
        "1111111111011111100100000000010000000001000000011000000001100000001000000000100000000010000000000000000011000000001100000001000000000100000000010000000111000000",
        "1111111110111111111100000001100000000110000000011000000010000000001000000000000000000000000000110000000011000000010000000001000000000100000001100000000110000000",
        "1111111111111111111111111111110000000001000000000000000001100000000110000000000000000010000000001000000000100000001100000000110000000000000000000000000001000000",
        "1111111111111111110000000001000000000100000000010000000110000000011000000110000000011000000001100000000000000000100000000010000000001000000011000000001100000000",
        "1111111111000000011000000001100000000110000000000000000010000000001000000000100000001100000000110000000011000000010000000001000000000000000000000000000110000000",
    ),
    "8": (
        "0000110000011111111001100001111000000001100000000111100000010111001110000111100001100001111000000001100000000110000000011000000001111000000101111111100000110000",
        "0001111000011111111001100000010110000001000000000101100000010111111110000111111000011111100110000111100000000110000000001000000001100000000101100001110111111110",
    ),
    "9": (
        "0011111100001111110011111111001110000111111000011111100000111111111111111111111100111111110011111111000000011100000001110000000111111111110011111110001111111000",
        "0001110000011111100001111110001000000110100000011010000001101000000001100000000110000000011110001111011111111101111111110000000001000000011000000001100000000110",
        "0001111000011111111001111111101110000111100000000110000000011000000001100000000110000000010111001111000111111100011111110000000001000000000100000000010000000111",
        "0001110000011111100001111110001000000110100000011000000001100000000110100000000111100011110111111111011111111100000000000000000110000000011000000001100000001000",
        "0000100000001111110001000000100100000010010000001010000000100100000001010000001100111111110000000001000000001000000000100000000010000000110001111111000011110000",
        "0001111000011111111011100001111110000111100000000110000000011000000001011100111101110011110001111111000000000100000000010000000110000000011000000011100111111000",
        "0001110000011111111010000001101000000110100000011010000000011000000001111000111111100011110111111111000000000100000001100000000110000000011000000010001111110000",
        "0111111000100000011010000001101000000110100000000110000000011000000001111000111101111111110000000001000000000100000001100000000110000000100000000010001111110000",
        "0111111110111000011111100001111000000001100000000110000000011000000001011100111100011111110000000001000000000100000000010000000111000000111000000011100111111000",
        "1000000110100000011010000001101000000001100000000110000000011110001111011111111101111111110000000001000000011000000001100000000110000000100000000010001111110000",
        "1110000111100000000110000000011000000001111000000111100000010111001111000111111100011111110000000001000000000100000000010000000111000000111000000011100111111000",
        "0001110000011111111011100001101110000110100000000110000000011000000001011000011101100001110111111111000000000100000000010000000110000000011000000011100111111000",
        "0000110000011111110001000000100100000010010000001010000000100100000001011100111101110011110011111111000000000000000000100000000010000000001000000011000111110000",
        "0111111000011000011010000000011000000001100000000110000000011110000001011111111101111111110001110001000000000100000000010000000110000000011001111111100111110000",
        "0001110000011111100010000001101000000110100000011010000000011000000001111000011101111111110000000001000000000100000001100000000110000000011011111110000111000000",
    ),
}


RANK_TEMPLATES: dict[Rank, tuple[RankMask, ...]] = {
    "2": (
        (
            "000000000000",
            "000111111000",
            "001110011000",
            "001000000100",
            "011000000100",
            "011000000110",
            "000000000100",
            "000000001100",
            "000000011000",
            "000000111000",
            "000001110000",
            "000111000000",
            "000110000000",
            "001100000000",
            "001000000000",
            "011000000000",
            "011111111110",
            "000000000000",
        ),
    ),
    "3": (
        (
            "000000000000",
            "000111111000",
            "001111111100",
            "011100001110",
            "011000001110",
            "000000001110",
            "000000011100",
            "000000111100",
            "000001111000",
            "000000011100",
            "000000001110",
            "000000000110",
            "011000000110",
            "011000001110",
            "011100001110",
            "001111111100",
            "000111111000",
            "000000000000",
        ),
        (
            "000000000000",
            "000111111000",
            "001110011100",
            "001100001110",
            "011100000110",
            "000000000110",
            "000000000110",
            "000000011100",
            "000001111000",
            "000000011100",
            "000000000110",
            "000000000110",
            "000000000110",
            "011000000110",
            "011100000110",
            "001110001100",
            "000111111100",
            "000000000000",
        ),
    ),
    "4": (
        (
            "000000000000",
            "000000011100",
            "000000111100",
            "000000111100",
            "000000111100",
            "000001011100",
            "000001011100",
            "000011011100",
            "000110011100",
            "001110011100",
            "001100011100",
            "011100011100",
            "011111111111",
            "000000011100",
            "000000011100",
            "000000011100",
            "000000011100",
            "000000000000",
        ),
        (
            "000000000000",
            "000000011000",
            "000000111000",
            "000000111000",
            "000001111000",
            "000011011000",
            "000011001000",
            "000110001000",
            "000100001000",
            "001000001000",
            "001000001000",
            "011111111100",
            "011111111100",
            "000000001000",
            "000000001000",
            "000000001000",
            "000000001000",
            "000000000000",
        ),
        (
            "000000000000",
            "000000111000",
            "000000111000",
            "000001111000",
            "000001111000",
            "000011011000",
            "000110011000",
            "001100011000",
            "001100011000",
            "011000011000",
            "110000011000",
            "111111111110",
            "111111111110",
            "000000011000",
            "000000011000",
            "000000011000",
            "000000011000",
            "000000000000",
        ),
    ),
    "5": (
        (
            "000000000000",
            "001110000000",
            "001100000000",
            "001100000000",
            "001100000000",
            "001000000000",
            "001111111000",
            "001111111100",
            "011100001100",
            "000000000100",
            "000000000100",
            "000000000100",
            "011000000100",
            "011000000100",
            "011000001100",
            "001110011100",
            "001111111000",
            "000000000000",
        ),
    ),
    "7": (
        (
            "000000000000",
            "011111111110",
            "000000001110",
            "000000001100",
            "000000011000",
            "000000011000",
            "000000110000",
            "000000110000",
            "000000100000",
            "000000100000",
            "000001000000",
            "000001000000",
            "000011000000",
            "000011000000",
            "000011000000",
            "000111000000",
            "000111000000",
            "000110000000",
        ),
        (
            "000000000000",
            "000000001110",
            "000000001100",
            "000000011000",
            "000000011000",
            "000000110000",
            "000000100000",
            "000000100000",
            "000001000000",
            "000001000000",
            "000001000000",
            "000011000000",
            "000011000000",
            "000011000000",
            "000110000000",
            "000110000000",
            "000110000000",
            "000000000000",
        ),
    ),
    "8": (
        (
            "000000000000",
            "000111111000",
            "000111111000",
            "001000001100",
            "001000000100",
            "001000000100",
            "001100001000",
            "000100011000",
            "000111111000",
            "001110011000",
            "011000000100",
            "011000000100",
            "011000000110",
            "011000000100",
            "011000000100",
            "001111111000",
            "000111111000",
            "000000000000",
        ),
    ),
    "9": (
        (
            "000000000000",
            "000111111000",
            "001110011100",
            "011100001100",
            "011000000110",
            "011000000110",
            "011000000110",
            "011000000110",
            "011100001110",
            "011100001110",
            "000111111110",
            "000011100110",
            "000000000110",
            "000000000110",
            "001000001100",
            "001100001100",
            "001110011000",
            "000011100000",
        ),
    ),
    "T": (
        (
            "000000000000",
            "011111111111",
            "001111111110",
            "000000110000",
            "000000110000",
            "000000110000",
            "000000110000",
            "000000110000",
            "000000110000",
            "000000110000",
            "000000110000",
            "000000110000",
            "000000110000",
            "000000110000",
            "000000110000",
            "000000110000",
            "000000110000",
            "000000000000",
        ),
        (
            "000000000000",
            "011111111110",
            "001111111100",
            "000000100000",
            "000000100000",
            "000000100000",
            "000000100000",
            "000000100000",
            "000000100000",
            "000000100000",
            "000000100000",
            "000000100000",
            "000000100000",
            "000000100000",
            "000000100000",
            "000000100000",
            "000000100000",
            "000000000000",
        ),
        (
            "000000000000",
            "011111111100",
            "000001100000",
            "000001100000",
            "000001100000",
            "000001100000",
            "000001100000",
            "000001100000",
            "000001100000",
            "000001100000",
            "000001100000",
            "000001100000",
            "000001100000",
            "000001100000",
            "000001100000",
            "000001100000",
            "000001100000",
            "000000000000",
        ),
    ),
    "J": (
        (
            "000000000000",
            "000000000110",
            "000000000110",
            "000000000110",
            "000000000110",
            "000000000110",
            "000000000110",
            "000000000110",
            "000000000110",
            "000000000110",
            "000000000110",
            "000000000110",
            "001000000110",
            "011000000110",
            "011000000110",
            "001100001110",
            "001111111000",
            "000000000000",
        ),
    ),
    "Q": (
        (
            "000000000000",
            "000111111000",
            "001111111100",
            "001100001100",
            "001000001100",
            "011000000100",
            "011000000100",
            "010000000110",
            "010000000110",
            "010000000110",
            "010000000110",
            "010000000110",
            "010000000110",
            "011000000100",
            "011000100100",
            "001000111100",
            "001100011100",
            "001111111100",
        ),
        (
            "000000000000",
            "000111111100",
            "001110011100",
            "001100000100",
            "001000000110",
            "001000000010",
            "011000000010",
            "011000000010",
            "010000000010",
            "010000000010",
            "011000000010",
            "011000000010",
            "001000000010",
            "001000111100",
            "001100011100",
            "001111111100",
            "000111111110",
            "000000000000",
        ),
    ),
    "K": (
        (
            "000000000000",
            "011000000100",
            "011000001100",
            "011000011000",
            "011000011000",
            "011001110000",
            "011001100000",
            "001011000000",
            "001111100000",
            "011101110000",
            "001100110000",
            "001000011000",
            "001000011000",
            "001000001000",
            "001000000100",
            "001000000110",
            "011000000110",
            "000000000000",
        ),
        (
            "000000000000",
            "011000001100",
            "011000001000",
            "011000011000",
            "011000110000",
            "011001100000",
            "011011100000",
            "011111000000",
            "011111000000",
            "011111100000",
            "011001110000",
            "011000110000",
            "011000011000",
            "011000001000",
            "011000001000",
            "011000000100",
            "011000000110",
            "000000000000",
        ),
        (
            "000000000000",
            "011000001100",
            "011000001000",
            "011000111000",
            "011000111000",
            "011001100000",
            "011011100000",
            "011111000000",
            "011111000000",
            "011111100000",
            "011001110000",
            "011000111000",
            "011000111000",
            "011000011000",
            "011000001000",
            "011000000100",
            "011000000110",
            "000000000000",
        ),
    ),
    "A": (
        (
            "000000000000",
            "000111100000",
            "000111100000",
            "000101100000",
            "000100110000",
            "000100110000",
            "000100110000",
            "001000111000",
            "001000011000",
            "001000011000",
            "011000011000",
            "011111111000",
            "111111111000",
            "110000001100",
            "110000000100",
            "110000000100",
            "110000000110",
            "100000000110",
        ),
        (
            "000000000000",
            "000001100000",
            "000011100000",
            "000011100000",
            "000011110000",
            "000010110000",
            "000110011000",
            "000110011000",
            "000100011000",
            "001100011000",
            "001100001100",
            "001100001100",
            "001111111100",
            "001111111100",
            "001000000100",
            "010000000100",
            "010000000110",
            "010000000010",
        ),
        (
            "000000000000",
            "000001100000",
            "000001100000",
            "000011100000",
            "000010100000",
            "000010010000",
            "000110010000",
            "000110011000",
            "000110011000",
            "001110011000",
            "001100011100",
            "001111111100",
            "011111111100",
            "011000001100",
            "011000000100",
            "011000000100",
            "010000000110",
            "000000000000",
        ),
    ),
}

CARD_SLOTS = FORTUNA_NATIONS_LAYOUT.card_slots


class OcrCvParser:
    name = "ocr_cv"

    def __init__(self, layout_profile: str = "generic") -> None:
        self.layout_profile = layout_profile
        try:
            self.layout = get_ocr_layout(layout_profile)
        except ValueError as exc:
            raise ParserConfigurationError(str(exc)) from exc

    def parse(self, image_path: Path) -> ParserResult:
        image = _load_image(image_path)
        warnings: list[str] = []
        raw_slots: list[dict[str, object]] = []

        try:
            self.layout.validate_capture_dimensions(image.width, image.height)
        except ValueError as exc:
            raise ParserError(str(exc)) from exc

        hero_cards, board_cards = _parse_card_slots(
            image,
            warnings,
            raw_slots,
            layout=self.layout,
        )
        hero_cards, board_cards = _remove_duplicate_cards(hero_cards, board_cards, warnings)
        hero_cards_visible = _hero_slots_have_visible_cards(raw_slots)
        street = _street_from_board_count(len(board_cards))
        numeric_state, numeric_confidences, numeric_raw, manual_review_fields = _parse_numeric_state(
            image,
            hero_cards_visible=hero_cards_visible,
            layout=self.layout,
            street=street,
        )
        if "opponent_wager" in manual_review_fields:
            warnings.append(
                "Opponent wager needs manual review; action controls were not recognized reliably"
            )
        confidences = _field_confidences(hero_cards, board_cards, street)
        confidences.update(numeric_confidences)

        if len(hero_cards) < 2:
            if hero_cards_visible:
                warnings.append("Hero cards need manual review; one or more card ranks were not recognized")
            else:
                warnings.append("Hero cards are not visible; manual review cannot reconstruct this field")

        return ParserResult(
            state=DetectedState(
                hero_cards=[parsed.card for parsed in hero_cards],
                board_cards=[parsed.card for parsed in board_cards],
                street=street,
                pot_size=numeric_state.get("pot_size"),
                current_bet=numeric_state.get("current_bet"),
                hero_stack=numeric_state.get("hero_stack"),
                effective_stack=numeric_state.get("effective_stack"),
                players_in_hand=numeric_state.get("players_in_hand"),
                opponent_wager=numeric_state.get("opponent_wager"),
                hero_position=numeric_state.get("hero_position"),
                facing_action=numeric_state.get("facing_action"),
                action_context=numeric_state.get("action_context"),
            ),
            confidences=confidences,
            warnings=warnings,
            raw={
                "provider": self.name,
                "layout_profile": self.layout_profile,
                "layout_engine": self.layout.engine,
                "image_filename": image_path.name,
                "image_size": [image.width, image.height],
                "manual_review_fields": manual_review_fields,
                "numbers": numeric_raw,
                "slots": raw_slots,
            },
        )


def _load_image(image_path: Path) -> Image.Image:
    try:
        with Image.open(image_path) as opened:
            return ImageOps.exif_transpose(opened).convert("RGB")
    except FileNotFoundError as exc:
        raise ParserError(f"Screenshot file does not exist: {image_path}") from exc
    except (
        Image.DecompressionBombError,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as exc:
        raise ParserError(f"Screenshot file could not be read: {image_path}") from exc


def _parse_card_slots(
    image: Image.Image,
    warnings: list[str],
    raw_slots: list[dict[str, object]],
    *,
    layout: OcrLayout = FORTUNA_NATIONS_LAYOUT,
) -> tuple[list[ParsedCard], list[ParsedCard]]:
    hero_cards: list[ParsedCard] = []
    board_cards: list[ParsedCard] = []

    for slot in layout.card_slots:
        parsed = _parse_card_slot(image, slot, layout)
        raw_slots.append(parsed["raw"])
        card = parsed["card"]
        if card is None:
            reason = parsed["raw"].get("reason")
            if reason != "empty":
                warnings.append(f"{slot.name} was not recognized: {reason}")
            continue
        if slot.kind == "hero":
            hero_cards.append(card)
        else:
            board_cards.append(card)

    return hero_cards, board_cards


def _parse_card_slot(
    image: Image.Image,
    slot: CardSlot,
    layout: OcrLayout = FORTUNA_NATIONS_LAYOUT,
) -> dict[str, object]:
    card_box = _scale_box(slot.box, image.width, image.height, layout)
    rank_box = _scale_box(_rank_box(slot), image.width, image.height, layout)
    rank_mask = _rank_mask_from_crop(image.crop(rank_box))
    raw: dict[str, object] = {
        "slot": slot.name,
        "kind": slot.kind,
        "card_box": list(card_box),
        "rank_box": list(rank_box),
    }
    if rank_mask is None:
        raw["reason"] = "empty"
        return {"card": None, "raw": raw}

    rank, rank_score = _match_rank(rank_mask)
    raw["rank_score"] = round(rank_score, 3)
    if rank is None:
        raw["reason"] = "rank_not_matched"
        return {"card": None, "raw": raw}

    suit, suit_confidence = _classify_suit(image.crop(card_box))
    raw["suit_confidence"] = round(suit_confidence, 3)
    if suit is None:
        raw["rank"] = rank
        raw["reason"] = "suit_not_matched"
        return {"card": None, "raw": raw}

    card = Card(rank=rank, suit=suit)
    confidence = min(0.95, 0.35 + (rank_score * 0.5) + (suit_confidence * 0.1))
    parsed = ParsedCard(
        card=card,
        slot=slot.name,
        confidence=round(confidence, 3),
        rank_score=round(rank_score, 3),
        suit_confidence=round(suit_confidence, 3),
    )
    raw.update(
        {
            "rank": rank,
            "suit": suit,
            "code": card.code,
            "confidence": parsed.confidence,
        }
    )
    return {"card": parsed, "raw": raw}


def _remove_duplicate_cards(
    hero_cards: list[ParsedCard], board_cards: list[ParsedCard], warnings: list[str]
) -> tuple[list[ParsedCard], list[ParsedCard]]:
    seen: set[str] = set()
    kept_hero: list[ParsedCard] = []
    kept_board: list[ParsedCard] = []
    for parsed in hero_cards:
        if parsed.card.code in seen:
            warnings.append(f"Duplicate parsed card {parsed.card.code} ignored from {parsed.slot}")
            continue
        seen.add(parsed.card.code)
        kept_hero.append(parsed)
    for parsed in board_cards:
        if parsed.card.code in seen:
            warnings.append(f"Duplicate parsed card {parsed.card.code} ignored from {parsed.slot}")
            continue
        seen.add(parsed.card.code)
        kept_board.append(parsed)
    return kept_hero, kept_board


def _hero_slots_have_visible_cards(raw_slots: list[dict[str, object]]) -> bool:
    for slot in raw_slots:
        if slot.get("kind") != "hero":
            continue
        if slot.get("reason") != "empty":
            return True
    return False


def _scale_box(
    box: PixelBox,
    width: int,
    height: int,
    layout: OcrLayout = FORTUNA_NATIONS_LAYOUT,
) -> PixelBox:
    x_ratio = width / layout.base_width
    y_ratio = height / layout.base_height
    return (
        round(box[0] * x_ratio),
        round(box[1] * y_ratio),
        round(box[2] * x_ratio),
        round(box[3] * y_ratio),
    )


def _rank_box(slot: CardSlot) -> PixelBox:
    left, top, right, bottom = slot.rank_region
    return (
        slot.box[0] + left,
        slot.box[1] + top,
        slot.box[0] + right,
        slot.box[1] + bottom,
    )


def _rank_mask_from_crop(crop: Image.Image) -> RankMask | None:
    image = crop.convert("RGB")
    points: list[tuple[int, int]] = []
    for y in range(image.height):
        for x in range(image.width):
            if _is_rank_pixel(image.getpixel((x, y))):
                points.append((x, y))

    if len(points) < MIN_RANK_PIXELS:
        return None

    min_x = min(x for x, _ in points)
    min_y = min(y for _, y in points)
    max_x = max(x for x, _ in points)
    max_y = max(y for _, y in points)
    padded_box = (
        max(min_x - 1, 0),
        max(min_y - 1, 0),
        min(max_x + 2, image.width),
        min(max_y + 2, image.height),
    )
    box_width = padded_box[2] - padded_box[0]
    box_height = padded_box[3] - padded_box[1]
    if box_width < 6 or box_height < 14:
        return None

    normalized = image.crop(padded_box).resize(
        (RANK_TEMPLATE_WIDTH, RANK_TEMPLATE_HEIGHT), Image.Resampling.NEAREST
    )
    rows: list[str] = []
    for y in range(RANK_TEMPLATE_HEIGHT):
        row = []
        for x in range(RANK_TEMPLATE_WIDTH):
            row.append("1" if _is_rank_pixel(normalized.getpixel((x, y))) else "0")
        rows.append("".join(row))
    return tuple(rows)


def _is_rank_pixel(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    return red > RANK_THRESHOLD and green > RANK_THRESHOLD and blue > RANK_THRESHOLD


def _match_rank(mask: RankMask) -> tuple[Rank | None, float]:
    mask_bits = _mask_bits(mask)
    best_rank: Rank | None = None
    best_score = 0.0
    for rank, templates in RANK_TEMPLATES.items():
        for template in templates:
            score = _jaccard(mask_bits, _mask_bits(template))
            if score > best_score:
                best_rank = rank
                best_score = score
    if best_score < RANK_MATCH_THRESHOLD:
        return None, best_score
    return best_rank, best_score


def _mask_bits(mask: RankMask) -> str:
    return "".join(mask)


def _jaccard(left: str, right: str) -> float:
    left_pixels = {index for index, value in enumerate(left) if value == "1"}
    right_pixels = {index for index, value in enumerate(right) if value == "1"}
    if not left_pixels and not right_pixels:
        return 0
    return len(left_pixels & right_pixels) / len(left_pixels | right_pixels)


def _classify_suit(crop: Image.Image) -> tuple[Suit | None, float]:
    red, green, blue = _body_median_rgb(crop)
    saturation = max(red, green, blue) - min(red, green, blue)

    if green > red + 35 and green > blue + 20:
        return "clubs", min(0.92, 0.72 + saturation / 500)
    if red > green + 55 and red > blue + 45:
        return "hearts", min(0.94, 0.72 + saturation / 500)
    if blue > red + 55 and green > red + 45:
        return "diamonds", min(0.94, 0.72 + saturation / 500)
    if saturation < 22 and 45 <= red <= 170 and 45 <= green <= 170 and 45 <= blue <= 170:
        return "spades", 0.78
    return None, 0.0


def _body_median_rgb(crop: Image.Image) -> tuple[int, int, int]:
    image = crop.convert("RGB")
    red_values: list[int] = []
    green_values: list[int] = []
    blue_values: list[int] = []
    x_start = int(image.width * 0.18)
    x_end = int(image.width * 0.82)
    y_start = int(image.height * 0.25)
    y_end = int(image.height * 0.9)
    for y in range(y_start, y_end):
        for x in range(x_start, x_end):
            red, green, blue = image.getpixel((x, y))
            red_values.append(red)
            green_values.append(green)
            blue_values.append(blue)
    return int(median(red_values)), int(median(green_values)), int(median(blue_values))


def _parse_numeric_state(
    image: Image.Image,
    *,
    hero_cards_visible: bool = True,
    layout: OcrLayout = FORTUNA_NATIONS_LAYOUT,
    street: Street | None = "preflop",
) -> tuple[dict[str, object], dict[str, float], dict[str, object], list[str]]:
    state: dict[str, object] = {}
    confidences: dict[str, float] = {}
    raw: dict[str, object] = {}
    manual_review_fields: list[str] = ["hero_position"]
    money_scale = _money_scale_from_image(image, layout)
    raw["money_scale"] = {
        "scale": money_scale.scale,
        "display_unit": money_scale.display_unit,
        "big_blind": money_scale.big_blind,
    }

    pot = _read_number_from_box(
        image,
        layout.pot.box,
        layout.pot.mode,
        layout,
        start_group=layout.pot.start_group,
        max_gap=layout.pot.max_gap,
        min_height=layout.pot.min_height,
    )
    raw["pot_size"] = _number_raw(pot)
    if pot is not None:
        normalized_pot = _scale_money_read(pot, money_scale.scale)
        state["pot_size"] = normalized_pot.value
        confidences["pot_size"] = min(0.9, pot.confidence)
        if money_scale.scale != 1:
            raw["pot_size_normalized"] = _number_raw(normalized_pot)
    else:
        manual_review_fields.append("pot_size")

    hero_stack = (
        _read_stack_number_from_box(image, layout.hero_stack_box, layout)
        if hero_cards_visible
        else None
    )
    raw["hero_stack"] = _number_raw(hero_stack)
    if not hero_cards_visible:
        raw["hero_stack_source"] = "hero cards not visible"

    call_amount: NumberRead | None = None
    raise_to_amount: NumberRead | None = None
    if hero_cards_visible:
        call_amount = _read_number_from_box(
            image,
            layout.call_amount.box,
            layout.call_amount.mode,
            layout,
            start_group=layout.call_amount.start_group,
            max_gap=layout.call_amount.max_gap,
            min_height=layout.call_amount.min_height,
        )
        if call_amount is None or (call_amount.value == 0 and call_amount.confidence < 0.6):
            call_amount = NumberRead(value=0.0, text="0", confidence=0.68)
            raw["current_bet_source"] = "no call amount detected; assuming check option"
        else:
            raw["current_bet_source"] = "call button"
        raw["current_bet"] = _number_raw(call_amount)
        normalized_call_amount = _scale_money_read(call_amount, money_scale.scale)
        state["current_bet"] = normalized_call_amount.value
        confidences["current_bet"] = min(0.88, call_amount.confidence)
        if money_scale.scale != 1:
            raw["current_bet_normalized"] = _number_raw(normalized_call_amount)
        if street in {"flop", "turn", "river"} and normalized_call_amount.value > 0:
            raise_to_amount = _read_number_from_box(
                image,
                layout.raise_to_amount.box,
                layout.raise_to_amount.mode,
                layout,
                start_group=layout.raise_to_amount.start_group,
                max_gap=layout.raise_to_amount.max_gap,
                min_height=layout.raise_to_amount.min_height,
            )
            raw["raise_to"] = _number_raw(raise_to_amount)
            normalized_raise_to = (
                _scale_money_read(raise_to_amount, money_scale.scale)
                if raise_to_amount is not None
                else None
            )
            if normalized_raise_to is not None and money_scale.scale != 1:
                raw["raise_to_normalized"] = _number_raw(normalized_raise_to)
            facing_action = _facing_action_from_controls(
                normalized_call_amount.value,
                normalized_raise_to.value if normalized_raise_to is not None else None,
            )
            action_confidence = min(
                call_amount.confidence,
                raise_to_amount.confidence if raise_to_amount is not None else 0,
                0.76,
            )
            if (
                facing_action is not None
                and action_confidence >= ACTION_CONTROL_MIN_CONFIDENCE
            ):
                state["facing_action"] = facing_action
                confidences["facing_action"] = action_confidence
                if facing_action == "bet":
                    state["opponent_wager"] = normalized_call_amount.value
                    confidences["opponent_wager"] = action_confidence
            else:
                manual_review_fields.append("opponent_wager")
    else:
        raw["current_bet_source"] = "hero cards not visible"
        raw["current_bet"] = None
        manual_review_fields.append("current_bet")

    active_seats: list[dict[str, object]] = []
    opponent_stacks: list[float] = []
    for seat in layout.opponent_seats:
        card_box = _scale_box(seat.card_box, image.width, image.height, layout)
        stack_box = _scale_box(seat.stack_box, image.width, image.height, layout)
        activity_confidence = _card_back_confidence(image.crop(card_box))
        seat_raw: dict[str, object] = {
            "seat": seat.name,
            "active_confidence": round(activity_confidence, 3),
            "active": activity_confidence >= 0.18,
            "card_box": list(card_box),
            "stack_box": list(stack_box),
        }
        if activity_confidence >= 0.18:
            stack = _read_stack_number_from_box(image, seat.stack_box, layout)
            seat_raw["stack"] = _number_raw(stack)
            if stack is not None:
                normalized_stack = _scale_money_read(stack, money_scale.scale)
                if money_scale.scale != 1:
                    seat_raw["stack_normalized"] = _number_raw(normalized_stack)
                opponent_stacks.append(normalized_stack.value)
        active_seats.append(seat_raw)

    active_opponent_count = sum(1 for seat in active_seats if seat["active"])
    players_in_hand = active_opponent_count + (1 if hero_cards_visible else 0)
    raw["active_seats"] = active_seats
    if players_in_hand >= 1:
        state["players_in_hand"] = players_in_hand
        confidences["players_in_hand"] = 0.78
    else:
        manual_review_fields.append("players_in_hand")

    if hero_stack is not None and hero_cards_visible:
        normalized_hero_stack = _scale_money_read(hero_stack, money_scale.scale)
        state["hero_stack"] = normalized_hero_stack.value
        confidences["hero_stack"] = min(0.82, hero_stack.confidence)
        if money_scale.scale != 1:
            raw["hero_stack_normalized"] = _number_raw(normalized_hero_stack)
        effective_stack = (
            min([normalized_hero_stack.value, *opponent_stacks]) if opponent_stacks else normalized_hero_stack.value
        )
        state["effective_stack"] = effective_stack
        confidences["effective_stack"] = 0.74 if opponent_stacks else 0.62
    else:
        manual_review_fields.append("hero_stack")
        manual_review_fields.append("effective_stack")

    if pot is not None and call_amount is not None and hero_cards_visible:
        normalized_pot = _scale_money_read(pot, money_scale.scale)
        normalized_call_amount = _scale_money_read(call_amount, money_scale.scale)
        if normalized_call_amount.value > 0:
            facing_action = state.get("facing_action")
            if facing_action == "bet":
                state["action_context"] = (
                    f"Hero faces a {format_number(normalized_call_amount.value)} BB bet into "
                    f"{format_number(normalized_pot.value)} BB pot"
                )
            else:
                manual_review_fields.append("facing_action")
                state["action_context"] = (
                    f"Hero faces {format_number(normalized_call_amount.value)} BB to call into "
                    f"{format_number(normalized_pot.value)} BB pot"
                )
        else:
            state["action_context"] = f"No bet to call; pot is {format_number(normalized_pot.value)} BB"
        confidences["action_context"] = 0.66
    else:
        manual_review_fields.append("action_context")

    return state, confidences, raw, manual_review_fields


def _facing_action_from_controls(
    amount_to_call: float,
    raise_to_amount: float | None,
) -> Literal["bet"] | None:
    """Recognize a first postflop bet when the controls make it unambiguous."""
    if amount_to_call <= 0 or raise_to_amount is None or raise_to_amount <= 0:
        return None
    first_bet_raise_to = amount_to_call * 2
    tolerance = 0.01
    if abs(raise_to_amount - first_bet_raise_to) <= tolerance:
        return "bet"
    return None


def _number_raw(number: NumberRead | None) -> dict[str, object] | None:
    if number is None:
        return None
    return {
        "value": number.value,
        "text": number.text,
        "confidence": round(number.confidence, 3),
    }


def _scale_money_read(number: NumberRead, scale: float) -> NumberRead:
    if scale == 1:
        return number
    return NumberRead(
        value=round(number.value * scale, 2),
        text=format_number(round(number.value * scale, 2)),
        confidence=number.confidence,
    )


def _money_scale_from_image(
    image: Image.Image,
    layout: OcrLayout = FORTUNA_NATIONS_LAYOUT,
) -> MoneyScale:
    big_blind = _read_big_blind_from_header(image, layout)
    if big_blind is None:
        return MoneyScale(scale=1.0, display_unit="bb", big_blind=None)

    if _number_box_has_bb_suffix(
        image,
        layout.pot.box,
        layout,
        mode=layout.pot.mode,
        start_group=layout.pot.start_group,
        max_gap=layout.pot.max_gap,
        min_height=layout.pot.min_height,
    ):
        return MoneyScale(scale=1.0, display_unit="bb", big_blind=big_blind)

    return MoneyScale(scale=round(1 / big_blind, 4), display_unit="cash", big_blind=big_blind)


def _read_big_blind_from_header(
    image: Image.Image,
    layout: OcrLayout = FORTUNA_NATIONS_LAYOUT,
) -> float | None:
    scaled_box = _scale_box(
        layout.header_stakes.box,
        image.width,
        image.height,
        layout,
    )
    crop = image.crop(scaled_box)
    sequence = _numeric_sequence_from_crop(
        crop,
        layout.header_stakes.mode,
        min_height=layout.header_stakes.min_height,
    )
    return _big_blind_from_numeric_sequence(sequence)


def _numeric_sequence_from_crop(crop: Image.Image, mode: TextMode, *, min_height: int = 0) -> str:
    groups, mask = _numeric_groups(crop, mode, min_height=min_height)
    chars: list[str] = []
    for group in groups:
        if _looks_like_decimal_dot(group, crop.height, mode):
            chars.append(".")
            continue
        if mode == "light" and _looks_like_thin_one(group, crop.height):
            chars.append("1")
            continue
        mask_bits = _numeric_group_mask(mask, group)
        digit, score = _match_numeric_digit(mask_bits)
        chars.append(digit if digit is not None and score >= NUMERIC_MATCH_THRESHOLD else "?")
    return "".join(chars)


def _big_blind_from_numeric_sequence(sequence: str) -> float | None:
    candidates = _decimal_candidates_from_numeric_sequence(sequence)
    pair_scores: list[tuple[float, DecimalCandidate]] = []
    for small_blind in candidates:
        if small_blind.value <= 0:
            continue
        for big_blind in candidates:
            if big_blind.start <= small_blind.end or big_blind.value <= small_blind.value:
                continue
            ratio = big_blind.value / small_blind.value
            if not 1.75 <= ratio <= 2.25:
                continue
            gap = big_blind.start - small_blind.end
            if gap > 4:
                continue
            score = abs(ratio - 2) + (gap * 0.05) + (small_blind.value * 0.01)
            pair_scores.append((score, big_blind))

    if not pair_scores:
        return None
    return min(pair_scores, key=lambda item: item[0])[1].value


def _decimal_candidates_from_numeric_sequence(sequence: str) -> list[DecimalCandidate]:
    candidates: list[DecimalCandidate] = []
    for dot_index, char in enumerate(sequence):
        if char != ".":
            continue
        left_start = dot_index
        while left_start > 0 and sequence[left_start - 1].isdigit():
            left_start -= 1
        right_end = dot_index + 1
        while right_end < len(sequence) and sequence[right_end].isdigit():
            right_end += 1
        left = sequence[left_start:dot_index]
        right = sequence[dot_index + 1 : right_end][:2]
        if not left or not right:
            continue
        for whole_digits in {left, left[-1:], left[-2:]}:
            source = f"{whole_digits}.{right}"
            try:
                value = float(source)
            except ValueError:
                continue
            if 0 < value <= 10:
                candidates.append(
                    DecimalCandidate(
                        value=round(value, 2),
                        start=dot_index - len(whole_digits),
                        end=dot_index + 1 + len(right),
                        source=source,
                    )
                )
    unique: dict[tuple[float, int, int], DecimalCandidate] = {}
    for candidate in candidates:
        unique[(candidate.value, candidate.start, candidate.end)] = candidate
    return list(unique.values())


def _number_box_has_bb_suffix(
    image: Image.Image,
    box: PixelBox,
    layout: OcrLayout = FORTUNA_NATIONS_LAYOUT,
    *,
    mode: TextMode = "light",
    start_group: int,
    max_gap: int,
    min_height: int = 0,
) -> bool:
    scaled_box = _scale_box(box, image.width, image.height, layout)
    crop = image.crop(scaled_box)
    groups, _ = _numeric_groups(crop, mode, min_height=min_height)
    selected_groups = _select_numeric_group_run(groups[start_group:], max_gap=max_gap)
    if not selected_groups:
        return False

    last_number_x = selected_groups[-1][2]
    suffix_groups = [
        group
        for group in groups
        if group[0] >= last_number_x + max_gap
        and group[0] - last_number_x <= 28
        and group[2] - group[0] >= 4
        and group[3] - group[1] >= 8
    ]
    return len(suffix_groups) >= 2


def _read_number_from_box(
    image: Image.Image,
    box: PixelBox,
    mode: TextMode,
    layout: OcrLayout = FORTUNA_NATIONS_LAYOUT,
    *,
    start_group: int = 0,
    max_gap: int = 8,
    min_height: int = 0,
) -> NumberRead | None:
    scaled_box = _scale_box(box, image.width, image.height, layout)
    crop = image.crop(scaled_box)
    return _read_number_from_crop(
        crop,
        mode,
        start_group=start_group,
        max_gap=max_gap,
        min_height=min_height,
    )


def _read_stack_number_from_box(
    image: Image.Image,
    box: PixelBox,
    layout: OcrLayout = FORTUNA_NATIONS_LAYOUT,
) -> NumberRead | None:
    scaled_box = _scale_box(box, image.width, image.height, layout)
    crop = image.crop(scaled_box)
    candidates: list[tuple[int, float, float, NumberRead]] = []
    for start_y, end_y in _numeric_row_runs(crop, "light"):
        band = crop.crop((0, max(0, start_y - 1), crop.width, min(crop.height, end_y + 1)))
        number = _read_number_from_crop(band, "light", max_gap=9, min_height=5)
        if number is None:
            continue
        normalized = _normalize_stack_number(number)
        digits = sum(char.isdigit() for char in normalized.text)
        stack_like_score = int(digits >= 2) + int("." in normalized.text) + int(normalized.value >= 5)
        candidates.append((stack_like_score, start_y / max(1, crop.height), normalized.confidence, normalized))

    if candidates:
        return max(candidates, key=lambda candidate: candidate[:3])[3]
    return _normalize_stack_number(_read_number_from_crop(crop, "light", max_gap=9, min_height=5))


def _read_number_from_crop(
    crop: Image.Image,
    mode: TextMode,
    *,
    start_group: int = 0,
    max_gap: int = 8,
    min_height: int = 0,
) -> NumberRead | None:
    groups, mask = _numeric_groups(crop, mode, min_height=min_height)
    selected_groups = _select_numeric_group_run(groups[start_group:], max_gap=max_gap)
    if not selected_groups:
        return None

    chars: list[str] = []
    scores: list[float] = []
    for group in selected_groups:
        if _looks_like_decimal_dot(group, crop.height, mode):
            chars.append(".")
            scores.append(0.9)
            continue
        if mode == "light" and _looks_like_thin_one(group, crop.height):
            chars.append("1")
            scores.append(0.65)
            continue

        mask_bits = _numeric_group_mask(mask, group)
        digit, score = _match_numeric_digit(mask_bits)
        if digit is None or score < NUMERIC_MATCH_THRESHOLD:
            continue
        chars.append(digit)
        scores.append(score)

    text = _clean_number_text("".join(chars))
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    confidence = sum(scores) / len(scores) if scores else 0.0
    return NumberRead(value=value, text=text, confidence=confidence)


def _numeric_row_runs(crop: Image.Image, mode: TextMode) -> list[tuple[int, int]]:
    mask = _numeric_foreground_mask(crop, mode)
    row_counts = [sum(row) for row in mask]
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, count in enumerate(row_counts):
        if count > 0 and start is None:
            start = index
        at_end = index == len(row_counts) - 1
        if (count == 0 or at_end) and start is not None:
            end = index if count == 0 else index + 1
            if end - start >= 3:
                runs.append((start, end))
            start = None
    return _merge_numeric_row_runs(runs)


def _merge_numeric_row_runs(runs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in runs:
        if merged and start - merged[-1][1] <= 2:
            previous_start, _ = merged[-1]
            merged[-1] = (previous_start, end)
        else:
            merged.append((start, end))
    return merged


def _normalize_stack_number(number: NumberRead | None) -> NumberRead | None:
    if number is None or "." in number.text:
        return number
    digits = "".join(char for char in number.text if char.isdigit())
    if len(digits) == 4:
        text = f"{digits[:2]}.{digits[2:]}"
    elif len(digits) == 5:
        text = f"{digits[:3]}.{digits[3:]}"
    else:
        return number
    return NumberRead(value=float(text), text=text, confidence=min(0.86, number.confidence * 0.94))


def _numeric_groups(
    crop: Image.Image, mode: TextMode, *, min_height: int = 0
) -> tuple[list[tuple[int, int, int, int, int]], list[list[bool]]]:
    mask = _numeric_foreground_mask(crop, mode)
    height = len(mask)
    width = len(mask[0]) if height else 0
    column_counts = [sum(mask[y][x] for y in range(height)) for x in range(width)]
    groups: list[tuple[int, int, int, int, int]] = []
    start: int | None = None
    for index, count in enumerate(column_counts):
        if count > 0 and start is None:
            start = index
        at_end = index == width - 1
        if (count == 0 or at_end) and start is not None:
            end = index if count == 0 else index + 1
            points = [(x, y) for x in range(start, end) for y in range(height) if mask[y][x]]
            if points:
                min_x = min(x for x, _ in points)
                min_y = min(y for _, y in points)
                max_x = max(x for x, _ in points) + 1
                max_y = max(y for _, y in points) + 1
                pixel_count = len(points)
                group = (min_x, min_y, max_x, max_y, pixel_count)
                group_width = max_x - min_x
                group_height = max_y - min_y
                if (
                    pixel_count >= 2
                    and group_width <= 25
                    and group_height <= 22
                    and (group_height >= min_height or _looks_like_tiny_numeric_mark(group))
                ):
                    groups.append(group)
            start = None
    return groups, mask


def _numeric_foreground_mask(crop: Image.Image, mode: TextMode) -> list[list[bool]]:
    image = crop.convert("RGB")
    mask: list[list[bool]] = []
    for y in range(image.height):
        row: list[bool] = []
        for x in range(image.width):
            row.append(_is_numeric_foreground(image.getpixel((x, y)), mode))
        mask.append(row)

    for y, row in enumerate(mask):
        if sum(row) > image.width * 0.42:
            mask[y] = [False] * image.width
    for x in range(image.width):
        if sum(mask[y][x] for y in range(image.height)) > image.height * 0.86:
            for y in range(image.height):
                mask[y][x] = False
    return mask


def _is_numeric_foreground(pixel: tuple[int, int, int], mode: TextMode) -> bool:
    red, green, blue = pixel
    if mode == "dark":
        return red < 50 and green < 50 and blue < 50
    return red > 100 and green > 100 and blue > 100 and max(pixel) - min(pixel) < 120


def _select_numeric_group_run(
    groups: list[tuple[int, int, int, int, int]], *, max_gap: int
) -> list[tuple[int, int, int, int, int]]:
    selected: list[tuple[int, int, int, int, int]] = []
    for group in groups:
        if selected and group[0] - selected[-1][2] >= max_gap:
            break
        selected.append(group)
    return selected


def _looks_like_tiny_numeric_mark(group: tuple[int, int, int, int, int]) -> bool:
    min_x, min_y, max_x, max_y, pixel_count = group
    return max_x - min_x <= 3 and max_y - min_y <= 4 and pixel_count <= 8


def _looks_like_decimal_dot(group: tuple[int, int, int, int, int], crop_height: int, mode: TextMode) -> bool:
    min_x, min_y, max_x, max_y, _ = group
    if not _looks_like_tiny_numeric_mark(group):
        return False
    if mode == "dark":
        return True
    return min_y >= crop_height * 0.45


def _looks_like_thin_one(group: tuple[int, int, int, int, int], crop_height: int) -> bool:
    min_x, min_y, max_x, max_y, pixel_count = group
    return max_x - min_x <= 3 and pixel_count >= 4 and min_y < crop_height * 0.7


def _numeric_group_mask(mask: list[list[bool]], group: tuple[int, int, int, int, int]) -> str:
    min_x, min_y, max_x, max_y, _ = group
    width = max_x - min_x
    height = max_y - min_y
    image = Image.new("1", (width, height), 0)
    pixels = image.load()
    for y in range(min_y, max_y):
        for x in range(min_x, max_x):
            if mask[y][x]:
                pixels[x - min_x, y - min_y] = 1
    normalized = image.resize((NUMERIC_TEMPLATE_WIDTH, NUMERIC_TEMPLATE_HEIGHT), Image.Resampling.NEAREST)
    return "".join(
        "1" if normalized.getpixel((x, y)) else "0"
        for y in range(NUMERIC_TEMPLATE_HEIGHT)
        for x in range(NUMERIC_TEMPLATE_WIDTH)
    )


def _match_numeric_digit(mask_bits: str) -> tuple[str | None, float]:
    best_digit: str | None = None
    best_score = 0.0
    for digit, templates in NUMERIC_TEMPLATES.items():
        for template in templates:
            if len(mask_bits) != len(template):
                continue
            score = _jaccard(mask_bits, template)
            if score > best_score:
                best_digit = digit
                best_score = score
    return best_digit, best_score


def _clean_number_text(text: str) -> str | None:
    if not text:
        return None
    cleaned = text.strip(".")
    if not cleaned:
        return None
    if cleaned.count(".") > 1:
        first = cleaned.find(".")
        cleaned = cleaned[: first + 1] + cleaned[first + 1 :].replace(".", "")
    if "." in cleaned:
        whole, fraction = cleaned.split(".", 1)
        cleaned = f"{whole}.{fraction[:2]}"
    if not any(char.isdigit() for char in cleaned):
        return None
    return cleaned


def _card_back_confidence(crop: Image.Image) -> float:
    image = crop.convert("RGB")
    active_pixels = 0
    for red, green, blue in image.getdata():
        is_blue_card = blue > 105 and green > 80 and red < 85
        is_yellow_card = red > 160 and green > 130 and blue < 90
        if is_blue_card or is_yellow_card:
            active_pixels += 1
    return active_pixels / (image.width * image.height)


def format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _street_from_board_count(board_count: int) -> Street | None:
    if board_count == 0:
        return "preflop"
    if board_count == 3:
        return "flop"
    if board_count == 4:
        return "turn"
    if board_count == 5:
        return "river"
    return None


def _field_confidences(
    hero_cards: list[ParsedCard], board_cards: list[ParsedCard], street: Street | None
) -> dict[str, float]:
    if len(hero_cards) == 2:
        hero_confidence = min(card.confidence for card in hero_cards)
    elif hero_cards:
        hero_confidence = 0.45
    else:
        hero_confidence = 0.1

    if board_cards:
        board_confidence = min(card.confidence for card in board_cards)
    else:
        board_confidence = 0.86

    if street is None:
        street_confidence = 0.35
    elif len(board_cards) in {0, 3, 4, 5}:
        street_confidence = min(0.9, board_confidence + 0.04)
    else:
        street_confidence = 0.45

    return {
        "hero_cards": round(hero_confidence, 2),
        "board_cards": round(board_confidence, 2),
        "street": round(street_confidence, 2),
    }


def _rank_template(rank: str) -> RankMask:
    return RANK_TEMPLATES[cast(Rank, rank)][0]
