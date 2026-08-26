# Poker Training Analyzer MVP Implementation Plan

> Historical implementation plan. Paths, package-manager commands, and MVP
> limitations in this document describe the original repository and are not
> current instructions. Use `AGENTS.md`, `README.md`, and the current product
> spec instead.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first poker training web app that uploads one Texas Hold'em screenshot, parses table state through a configurable parser, lets the user verify/correct it, and returns a configurable strategy recommendation.

**Architecture:** Use a two-package repo with `backend/` for FastAPI orchestration and `frontend/` for the React control panel. The backend owns parser/provider registries, file-backed job state, state normalization, and proxy calls to local or external engines; the frontend only talks to backend endpoints and edits canonical state.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, httpx, pytest, React 18, TypeScript, Vite, Vitest, Testing Library, lucide-react.

---

## File Structure

- `backend/pyproject.toml`: backend package metadata, runtime dependencies, pytest config.
- `backend/app/__init__.py`: package marker and version.
- `backend/app/config.py`: environment-driven runtime configuration.
- `backend/app/models.py`: shared Pydantic domain models for cards, parsed state, jobs, and recommendations.
- `backend/app/parsers/base.py`: parser protocol and parser error types.
- `backend/app/parsers/mock.py`: deterministic parser for tests and UI development.
- `backend/app/parsers/http_vision.py`: configurable HTTP parser adapter for LLM/vision services.
- `backend/app/parsers/ocr_cv.py`: registered OCR/CV parser adapter that returns a clear configuration error until a concrete OCR command is provided.
- `backend/app/parsers/registry.py`: parser selection by config.
- `backend/app/providers/base.py`: recommendation provider protocol and validation helpers.
- `backend/app/providers/mock.py`: deterministic training recommendation provider.
- `backend/app/providers/local_solver.py`: local command adapter using JSON over stdin/stdout.
- `backend/app/providers/http_provider.py`: configurable HTTP provider adapter for external solver and LLM advice services.
- `backend/app/providers/registry.py`: recommendation provider selection by config.
- `backend/app/storage.py`: file-backed job store under `backend/data/` or configured `POKER_DATA_DIR`.
- `backend/app/api.py`: FastAPI app factory and REST endpoints.
- `backend/app/main.py`: uvicorn entrypoint.
- `backend/tests/*.py`: backend unit/API tests.
- `frontend/package.json`: frontend package metadata and scripts.
- `frontend/index.html`: Vite entry HTML.
- `frontend/tsconfig.json`, `frontend/tsconfig.node.json`, `frontend/vite.config.ts`: TypeScript and test config.
- `frontend/src/types.ts`: TypeScript API/domain types.
- `frontend/src/api.ts`: backend API client.
- `frontend/src/App.tsx`: upload, review, approval, recommendation flow.
- `frontend/src/App.css`: utilitarian control-panel layout.
- `frontend/src/main.tsx`: React entrypoint.
- `frontend/src/test/setup.ts`, `frontend/src/App.test.tsx`: frontend test setup and smoke test.
- `.gitignore`: ignore generated data, virtualenvs, node modules, caches, and build output.
- `.env.example`: root example config for parser/provider switching.
- `README.md`: local setup, running, testing, and configuration guide.

## Task 1: Backend Domain Models And Configuration

**Files:**

- Create: `backend/pyproject.toml`
- Create: `backend/tests/test_config_and_models.py`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/models.py`

- [ ] **Step 1: Write the failing backend core tests**

Create `backend/pyproject.toml`:

```toml
[project]
name = "poker-training-api"
version = "0.1.0"
description = "Local-first poker screenshot training analyzer API"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "httpx>=0.27",
  "pydantic>=2.8",
  "pydantic-settings>=2.4",
  "python-multipart>=0.0.9",
  "uvicorn[standard]>=0.30"
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2"
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

Create `backend/tests/test_config_and_models.py`:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models import Card, CanonicalState, DetectedState, ParserResult


def test_settings_defaults_use_mock_backends(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)

    assert settings.data_dir == tmp_path
    assert settings.parser_provider == "mock"
    assert settings.parser_layout_profile == "generic"
    assert settings.parser_auto_approve_enabled is False
    assert settings.recommendation_provider == "mock"
    assert settings.cors_origins == ["http://localhost:5173"]


def test_card_from_code_normalizes_rank_and_suit() -> None:
    card = Card.from_code("Ah")

    assert card.rank == "A"
    assert card.suit == "hearts"
    assert card.code == "Ah"


def test_card_rejects_unknown_rank() -> None:
    with pytest.raises(ValidationError):
        Card(rank="1", suit="hearts")


def test_canonical_state_copies_detected_values() -> None:
    detected = DetectedState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
        board_cards=[Card.from_code("Qs"), Card.from_code("Jc"), Card.from_code("2h")],
        pot_size=12.5,
        current_bet=2.5,
        effective_stack=96.0,
        players_in_hand=3,
        hero_position="button",
        street="flop",
        action_context="Cutoff bet 2.5 into 12.5",
    )
    parser_result = ParserResult(
        state=detected,
        confidences={"hero_cards": 0.99, "board_cards": 0.98, "pot_size": 0.92, "street": 1.0},
        warnings=[],
        raw={"provider": "mock"},
    )

    canonical = CanonicalState.from_parser_result(parser_result)

    assert canonical.hero_cards == detected.hero_cards
    assert canonical.board_cards == detected.board_cards
    assert canonical.pot_size == 12.5
    assert canonical.user_approved is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend
python -m pip install -e ".[dev]"
python -m pytest tests/test_config_and_models.py -q
```

Expected: `python -m pytest` exits non-zero with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 3: Add backend config and domain models**

Create `backend/app/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `backend/app/config.py`:

```python
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="POKER_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    data_dir: Path = Field(default=Path("data"))
    parser_provider: str = Field(default="mock")
    parser_layout_profile: str = Field(default="generic")
    parser_auto_approve_enabled: bool = Field(default=False)
    parser_auto_approve_thresholds: dict[str, float] = Field(
        default_factory=lambda: {
            "hero_cards": 0.98,
            "board_cards": 0.98,
            "pot_size": 0.95,
            "street": 0.99,
        }
    )
    recommendation_provider: str = Field(default="mock")
    external_parser_url: str | None = Field(default=None)
    external_provider_url: str | None = Field(default=None)
    llm_advice_url: str | None = Field(default=None)
    local_solver_command: str | None = Field(default=None)
    local_solver_timeout_seconds: float = Field(default=30.0)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Create `backend/app/models.py`:

```python
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


Rank = Literal["2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"]
Suit = Literal["clubs", "diamonds", "hearts", "spades"]
Street = Literal["preflop", "flop", "turn", "river"]
RecommendationAction = Literal["fold", "check", "call", "bet", "raise"]

RANKS = {"2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"}
SUIT_BY_CODE = {
    "c": "clubs",
    "d": "diamonds",
    "h": "hearts",
    "s": "spades",
}
CODE_BY_SUIT = {value: key for key, value in SUIT_BY_CODE.items()}


class Card(BaseModel):
    rank: str
    suit: str

    @field_validator("rank")
    @classmethod
    def validate_rank(cls, value: str) -> str:
        normalized = value.upper()
        if normalized == "10":
            normalized = "T"
        if normalized not in RANKS:
            raise ValueError(f"Unknown card rank: {value}")
        return normalized

    @field_validator("suit")
    @classmethod
    def validate_suit(cls, value: str) -> str:
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


class DetectedState(BaseModel):
    hero_cards: list[Card] = Field(default_factory=list)
    board_cards: list[Card] = Field(default_factory=list)
    pot_size: float | None = Field(default=None, ge=0)
    current_bet: float | None = Field(default=None, ge=0)
    effective_stack: float | None = Field(default=None, ge=0)
    players_in_hand: int | None = Field(default=None, ge=1)
    hero_position: str | None = Field(default=None)
    street: Street | None = Field(default=None)
    action_context: str | None = Field(default=None)


class ParserResult(BaseModel):
    state: DetectedState
    confidences: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)

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
    pot_size: float | None = Field(default=None, ge=0)
    current_bet: float | None = Field(default=None, ge=0)
    effective_stack: float | None = Field(default=None, ge=0)
    players_in_hand: int | None = Field(default=None, ge=1)
    hero_position: str | None = Field(default=None)
    street: Street | None = Field(default=None)
    action_context: str | None = Field(default=None)
    user_approved: bool = Field(default=False)

    @classmethod
    def from_parser_result(cls, parser_result: ParserResult) -> "CanonicalState":
        state = parser_result.state
        return cls(
            hero_cards=state.hero_cards,
            board_cards=state.board_cards,
            pot_size=state.pot_size,
            current_bet=state.current_bet,
            effective_stack=state.effective_stack,
            players_in_hand=state.players_in_hand,
            hero_position=state.hero_position,
            street=state.street,
            action_context=state.action_context,
        )


class RecommendationRequest(BaseModel):
    state: CanonicalState
    provider: str


class RecommendationResult(BaseModel):
    action: RecommendationAction
    sizing: float | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0, le=1)
    explanation: str
    raw: dict = Field(default_factory=dict)


class JobRecord(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(default_factory=lambda: uuid4().hex)
    status: Literal["created", "parsed", "approved", "recommended", "error"] = "created"
    original_filename: str
    image_filename: str
    parser_provider: str
    recommendation_provider: str
    parser_result: ParserResult | None = None
    approved_state: CanonicalState | None = None
    recommendation: RecommendationResult | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
```

- [ ] **Step 4: Run backend core tests**

Run:

```bash
cd backend
python -m pytest tests/test_config_and_models.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit backend core**

Run:

```bash
git add backend/pyproject.toml backend/app/__init__.py backend/app/config.py backend/app/models.py backend/tests/test_config_and_models.py
git commit -m "feat: add backend domain models and config"
```

Expected: commit succeeds.

## Task 2: Configurable Screenshot Parsers

**Files:**

- Create: `backend/app/parsers/__init__.py`
- Create: `backend/app/parsers/base.py`
- Create: `backend/app/parsers/mock.py`
- Create: `backend/app/parsers/http_vision.py`
- Create: `backend/app/parsers/ocr_cv.py`
- Create: `backend/app/parsers/registry.py`
- Create: `backend/tests/test_parsers.py`

- [ ] **Step 1: Write parser tests**

Create `backend/tests/test_parsers.py`:

```python
from pathlib import Path

import pytest

from app.config import Settings
from app.parsers.base import ParserConfigurationError
from app.parsers.registry import build_parser


def test_registry_builds_mock_parser(tmp_path: Path) -> None:
    image_path = tmp_path / "table.png"
    image_path.write_bytes(b"fake image bytes")
    parser = build_parser(Settings(data_dir=tmp_path, parser_provider="mock"))

    result = parser.parse(image_path)

    assert result.state.hero_cards[0].code == "Ah"
    assert result.state.hero_cards[1].code == "Kd"
    assert result.state.street == "flop"
    assert result.confidences["hero_cards"] == 0.99
    assert result.raw["provider"] == "mock"


def test_registry_rejects_unknown_parser(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, parser_provider="missing")

    with pytest.raises(ParserConfigurationError, match="Unknown parser provider"):
        build_parser(settings)


def test_http_vision_parser_requires_url(tmp_path: Path) -> None:
    parser = build_parser(Settings(data_dir=tmp_path, parser_provider="llm_vision", external_parser_url=None))

    with pytest.raises(ParserConfigurationError, match="POKER_EXTERNAL_PARSER_URL"):
        parser.parse(tmp_path / "table.png")


def test_ocr_cv_parser_returns_configuration_error(tmp_path: Path) -> None:
    parser = build_parser(Settings(data_dir=tmp_path, parser_provider="ocr_cv"))

    with pytest.raises(ParserConfigurationError, match="OCR/CV parser requires"):
        parser.parse(tmp_path / "table.png")
```

- [ ] **Step 2: Run parser tests to verify they fail**

Run:

```bash
cd backend
python -m pytest tests/test_parsers.py -q
```

Expected: exits non-zero with `ModuleNotFoundError: No module named 'app.parsers'`.

- [ ] **Step 3: Add parser interfaces and adapters**

Create `backend/app/parsers/__init__.py`:

```python
from app.parsers.registry import build_parser

__all__ = ["build_parser"]
```

Create `backend/app/parsers/base.py`:

```python
from pathlib import Path
from typing import Protocol

from app.models import ParserResult


class ParserError(RuntimeError):
    pass


class ParserConfigurationError(ParserError):
    pass


class ScreenshotParser(Protocol):
    name: str

    def parse(self, image_path: Path) -> ParserResult:
        raise NotImplementedError
```

Create `backend/app/parsers/mock.py`:

```python
from pathlib import Path

from app.models import Card, DetectedState, ParserResult


class MockParser:
    name = "mock"

    def parse(self, image_path: Path) -> ParserResult:
        return ParserResult(
            state=DetectedState(
                hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
                board_cards=[Card.from_code("Qs"), Card.from_code("Jc"), Card.from_code("2h")],
                pot_size=12.5,
                current_bet=2.5,
                effective_stack=96.0,
                players_in_hand=3,
                hero_position="button",
                street="flop",
                action_context="Cutoff bet 2.5 into 12.5",
            ),
            confidences={
                "hero_cards": 0.99,
                "board_cards": 0.98,
                "pot_size": 0.92,
                "current_bet": 0.9,
                "effective_stack": 0.88,
                "players_in_hand": 0.93,
                "hero_position": 0.87,
                "street": 1.0,
            },
            warnings=[],
            raw={
                "provider": self.name,
                "image_filename": image_path.name,
            },
        )
```

Create `backend/app/parsers/http_vision.py`:

```python
from pathlib import Path

import httpx

from app.config import Settings
from app.models import ParserResult
from app.parsers.base import ParserConfigurationError, ParserError


class HttpVisionParser:
    name = "llm_vision"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def parse(self, image_path: Path) -> ParserResult:
        if not self.settings.external_parser_url:
            raise ParserConfigurationError("POKER_EXTERNAL_PARSER_URL is required for llm_vision parser")
        if not image_path.exists():
            raise ParserError(f"Screenshot file does not exist: {image_path}")

        with image_path.open("rb") as image_file:
            response = httpx.post(
                self.settings.external_parser_url,
                files={"image": (image_path.name, image_file, "application/octet-stream")},
                data={"layout_profile": self.settings.parser_layout_profile},
                timeout=60.0,
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ParserError(f"Vision parser request failed with status {exc.response.status_code}") from exc

        return ParserResult.model_validate(response.json())
```

Create `backend/app/parsers/ocr_cv.py`:

```python
from pathlib import Path

from app.models import ParserResult
from app.parsers.base import ParserConfigurationError


class OcrCvParser:
    name = "ocr_cv"

    def parse(self, image_path: Path) -> ParserResult:
        raise ParserConfigurationError(
            "OCR/CV parser requires a concrete OCR command or library adapter before it can parse screenshots"
        )
```

Create `backend/app/parsers/registry.py`:

```python
from app.config import Settings
from app.parsers.base import ParserConfigurationError, ScreenshotParser
from app.parsers.http_vision import HttpVisionParser
from app.parsers.mock import MockParser
from app.parsers.ocr_cv import OcrCvParser


def build_parser(settings: Settings) -> ScreenshotParser:
    if settings.parser_provider == "mock":
        return MockParser()
    if settings.parser_provider == "llm_vision":
        return HttpVisionParser(settings)
    if settings.parser_provider == "ocr_cv":
        return OcrCvParser()
    raise ParserConfigurationError(f"Unknown parser provider: {settings.parser_provider}")
```

- [ ] **Step 4: Run parser tests**

Run:

```bash
cd backend
python -m pytest tests/test_parsers.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Run all backend tests**

Run:

```bash
cd backend
python -m pytest -q
```

Expected: `8 passed`.

- [ ] **Step 6: Commit parser slice**

Run:

```bash
git add backend/app/parsers backend/tests/test_parsers.py
git commit -m "feat: add configurable screenshot parsers"
```

Expected: commit succeeds.

## Task 3: Configurable Recommendation Providers

**Files:**

- Create: `backend/app/providers/__init__.py`
- Create: `backend/app/providers/base.py`
- Create: `backend/app/providers/mock.py`
- Create: `backend/app/providers/local_solver.py`
- Create: `backend/app/providers/http_provider.py`
- Create: `backend/app/providers/registry.py`
- Create: `backend/tests/test_providers.py`

- [ ] **Step 1: Write provider tests**

Create `backend/tests/test_providers.py`:

```python
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.models import CanonicalState, Card, RecommendationRequest
from app.providers.base import ProviderConfigurationError, missing_required_fields
from app.providers.registry import build_provider


def approved_state() -> CanonicalState:
    return CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
        board_cards=[Card.from_code("Qs"), Card.from_code("Jc"), Card.from_code("2h")],
        pot_size=12.5,
        current_bet=2.5,
        effective_stack=96.0,
        players_in_hand=3,
        hero_position="button",
        street="flop",
        action_context="Cutoff bet 2.5 into 12.5",
        user_approved=True,
    )


def test_mock_provider_returns_training_recommendation(tmp_path: Path) -> None:
    provider = build_provider(Settings(data_dir=tmp_path, recommendation_provider="mock"))
    request = RecommendationRequest(state=approved_state(), provider=provider.name)

    result = provider.recommend(request)

    assert result.action == "raise"
    assert result.sizing == 7.5
    assert result.confidence == 0.72
    assert "training" in result.explanation.lower()
    assert result.raw["provider"] == "mock"


def test_required_field_validation_reports_missing_values() -> None:
    state = CanonicalState(street="flop", user_approved=True)

    assert missing_required_fields(state, ["hero_cards", "street"]) == ["hero_cards"]


def test_registry_rejects_unknown_provider(tmp_path: Path) -> None:
    with pytest.raises(ProviderConfigurationError, match="Unknown recommendation provider"):
        build_provider(Settings(data_dir=tmp_path, recommendation_provider="missing"))


def test_local_solver_requires_command(tmp_path: Path) -> None:
    provider = build_provider(Settings(data_dir=tmp_path, recommendation_provider="local_solver"))
    request = RecommendationRequest(state=approved_state(), provider=provider.name)

    with pytest.raises(ProviderConfigurationError, match="POKER_LOCAL_SOLVER_COMMAND"):
        provider.recommend(request)


def test_local_solver_reads_json_response(tmp_path: Path) -> None:
    solver_script = tmp_path / "solver.py"
    solver_script.write_text(
        "import json, sys\n"
        "json.loads(sys.stdin.read())\n"
        "print(json.dumps({"
        "'action': 'call', "
        "'sizing': None, "
        "'confidence': 0.64, "
        "'explanation': 'Local command response', "
        "'raw': {'provider': 'local_solver'}"
        "}))\n"
    )
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="local_solver",
            local_solver_command=f"{sys.executable} {solver_script}",
        )
    )

    result = provider.recommend(RecommendationRequest(state=approved_state(), provider=provider.name))

    assert result.action == "call"
    assert result.raw["provider"] == "local_solver"
```

- [ ] **Step 2: Run provider tests to verify they fail**

Run:

```bash
cd backend
python -m pytest tests/test_providers.py -q
```

Expected: exits non-zero with `ModuleNotFoundError: No module named 'app.providers'`.

- [ ] **Step 3: Add provider interfaces and adapters**

Create `backend/app/providers/__init__.py`:

```python
from app.providers.registry import build_provider

__all__ = ["build_provider"]
```

Create `backend/app/providers/base.py`:

```python
from typing import Protocol

from app.models import CanonicalState, RecommendationRequest, RecommendationResult


class ProviderError(RuntimeError):
    pass


class ProviderConfigurationError(ProviderError):
    pass


class RecommendationProvider(Protocol):
    name: str
    required_fields: list[str]

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        raise NotImplementedError


def field_has_value(state: CanonicalState, field_name: str) -> bool:
    value = getattr(state, field_name)
    if isinstance(value, list):
        return len(value) > 0
    return value is not None


def missing_required_fields(state: CanonicalState, required_fields: list[str]) -> list[str]:
    return [field_name for field_name in required_fields if not field_has_value(state, field_name)]
```

Create `backend/app/providers/mock.py`:

```python
from app.models import RecommendationRequest, RecommendationResult


class MockRecommendationProvider:
    name = "mock"
    required_fields = ["hero_cards", "street"]

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        state = request.state
        has_broadway = any(card.rank in {"A", "K", "Q", "J", "T"} for card in state.hero_cards)
        action = "raise" if has_broadway else "call"
        sizing = 7.5 if action == "raise" else None
        return RecommendationResult(
            action=action,
            sizing=sizing,
            confidence=0.72,
            explanation=(
                "Training recommendation from the mock provider: hero has strong high-card equity, "
                "so raising is preferred in this reviewed scenario."
            ),
            raw={
                "provider": self.name,
                "street": state.street,
                "hero_cards": [card.code for card in state.hero_cards],
            },
        )
```

Create `backend/app/providers/local_solver.py`:

```python
import json
import shlex
import subprocess

from app.config import Settings
from app.models import RecommendationRequest, RecommendationResult
from app.providers.base import ProviderConfigurationError, ProviderError


class LocalSolverProvider:
    name = "local_solver"
    required_fields = ["hero_cards", "street", "pot_size", "effective_stack"]

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        if not self.settings.local_solver_command:
            raise ProviderConfigurationError("POKER_LOCAL_SOLVER_COMMAND is required for local_solver provider")

        completed = subprocess.run(
            shlex.split(self.settings.local_solver_command),
            input=request.model_dump_json(),
            text=True,
            capture_output=True,
            timeout=self.settings.local_solver_timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise ProviderError(f"Local solver failed: {completed.stderr.strip()}")

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderError("Local solver returned invalid JSON") from exc

        return RecommendationResult.model_validate(payload)
```

Create `backend/app/providers/http_provider.py`:

```python
import httpx

from app.models import RecommendationRequest, RecommendationResult
from app.providers.base import ProviderConfigurationError, ProviderError


class HttpRecommendationProvider:
    required_fields = ["hero_cards", "street", "pot_size"]

    def __init__(self, name: str, url: str | None, missing_message: str) -> None:
        self.name = name
        self.url = url
        self.missing_message = missing_message

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        if not self.url:
            raise ProviderConfigurationError(self.missing_message)

        response = httpx.post(
            self.url,
            json=request.model_dump(mode="json"),
            timeout=60.0,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"{self.name} request failed with status {exc.response.status_code}") from exc

        return RecommendationResult.model_validate(response.json())
```

Create `backend/app/providers/registry.py`:

```python
from app.config import Settings
from app.providers.base import ProviderConfigurationError, RecommendationProvider
from app.providers.http_provider import HttpRecommendationProvider
from app.providers.local_solver import LocalSolverProvider
from app.providers.mock import MockRecommendationProvider


def build_provider(settings: Settings) -> RecommendationProvider:
    if settings.recommendation_provider == "mock":
        return MockRecommendationProvider()
    if settings.recommendation_provider == "local_solver":
        return LocalSolverProvider(settings)
    if settings.recommendation_provider == "external_solver":
        return HttpRecommendationProvider(
            name="external_solver",
            url=settings.external_provider_url,
            missing_message="POKER_EXTERNAL_PROVIDER_URL is required for external_solver provider",
        )
    if settings.recommendation_provider == "llm_advice":
        return HttpRecommendationProvider(
            name="llm_advice",
            url=settings.llm_advice_url,
            missing_message="POKER_LLM_ADVICE_URL is required for llm_advice provider",
        )
    raise ProviderConfigurationError(f"Unknown recommendation provider: {settings.recommendation_provider}")
```

- [ ] **Step 4: Run provider tests**

Run:

```bash
cd backend
python -m pytest tests/test_providers.py -q
```

Expected: `5 passed`.

- [ ] **Step 5: Run all backend tests**

Run:

```bash
cd backend
python -m pytest -q
```

Expected: `13 passed`.

- [ ] **Step 6: Commit provider slice**

Run:

```bash
git add backend/app/providers backend/tests/test_providers.py
git commit -m "feat: add configurable recommendation providers"
```

Expected: commit succeeds.

## Task 4: Backend Job Store And REST API

**Files:**

- Create: `backend/app/storage.py`
- Create: `backend/app/api.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/test_api_flow.py`

- [ ] **Step 1: Write API flow tests**

Create `backend/tests/test_api_flow.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings


def make_client(tmp_path: Path) -> TestClient:
    app = create_app(Settings(data_dir=tmp_path, parser_provider="mock", recommendation_provider="mock"))
    return TestClient(app)


def test_upload_parse_approve_and_recommend(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    upload = client.post(
        "/api/jobs",
        files={"file": ("table.png", b"not a real image but accepted for mock parser", "image/png")},
    )

    assert upload.status_code == 200
    job = upload.json()
    assert job["status"] == "parsed"
    assert job["parser_result"]["state"]["hero_cards"][0]["rank"] == "A"
    assert job["parser_result"]["confidences"]["hero_cards"] == 0.99

    approve = client.post(
        f"/api/jobs/{job['id']}/approve",
        json={
            "hero_cards": [{"rank": "A", "suit": "hearts"}, {"rank": "K", "suit": "diamonds"}],
            "board_cards": [
                {"rank": "Q", "suit": "spades"},
                {"rank": "J", "suit": "clubs"},
                {"rank": "2", "suit": "hearts"},
            ],
            "pot_size": 12.5,
            "current_bet": 2.5,
            "effective_stack": 96.0,
            "players_in_hand": 3,
            "hero_position": "button",
            "street": "flop",
            "action_context": "Cutoff bet 2.5 into 12.5",
            "user_approved": True,
        },
    )

    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    recommend = client.post(f"/api/jobs/{job['id']}/recommend")

    assert recommend.status_code == 200
    result = recommend.json()
    assert result["status"] == "recommended"
    assert result["recommendation"]["action"] == "raise"
    assert result["recommendation"]["sizing"] == 7.5


def test_recommend_requires_approval(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    upload = client.post(
        "/api/jobs",
        files={"file": ("table.png", b"image", "image/png")},
    )
    job_id = upload.json()["id"]

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 409
    assert response.json()["detail"] == "Approve corrected state before requesting recommendation"


def test_job_image_endpoint_returns_upload(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    upload = client.post(
        "/api/jobs",
        files={"file": ("table.png", b"image-bytes", "image/png")},
    )
    job_id = upload.json()["id"]

    image_response = client.get(f"/api/jobs/{job_id}/image")

    assert image_response.status_code == 200
    assert image_response.content == b"image-bytes"
```

- [ ] **Step 2: Run API tests to verify they fail**

Run:

```bash
cd backend
python -m pytest tests/test_api_flow.py -q
```

Expected: exits non-zero with `ModuleNotFoundError: No module named 'app.api'`.

- [ ] **Step 3: Add file-backed storage and API endpoints**

Create `backend/app/storage.py`:

```python
from pathlib import Path

from app.models import JobRecord


class JobNotFoundError(KeyError):
    pass


class FileJobStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.jobs_dir = self.data_dir / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def create_job(self, original_filename: str, image_bytes: bytes, parser_provider: str, recommendation_provider: str) -> JobRecord:
        image_suffix = Path(original_filename).suffix or ".png"
        job = JobRecord(
            original_filename=original_filename,
            image_filename=f"original{image_suffix}",
            parser_provider=parser_provider,
            recommendation_provider=recommendation_provider,
        )
        job_dir = self._job_dir(job.id)
        job_dir.mkdir(parents=True, exist_ok=False)
        (job_dir / job.image_filename).write_bytes(image_bytes)
        self.save(job)
        return job

    def image_path(self, job: JobRecord) -> Path:
        return self._job_dir(job.id) / job.image_filename

    def get(self, job_id: str) -> JobRecord:
        path = self._job_path(job_id)
        if not path.exists():
            raise JobNotFoundError(job_id)
        return JobRecord.model_validate_json(path.read_text())

    def save(self, job: JobRecord) -> JobRecord:
        job.touch()
        path = self._job_path(job.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(job.model_dump_json(indent=2))
        return job

    def _job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def _job_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "job.json"
```

Create `backend/app/api.py`:

```python
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import Settings, get_settings
from app.models import CanonicalState, JobRecord, RecommendationRequest
from app.parsers.base import ParserError
from app.parsers.registry import build_parser
from app.providers.base import ProviderError, missing_required_fields
from app.providers.registry import build_provider
from app.storage import FileJobStore, JobNotFoundError


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    store = FileJobStore(active_settings.data_dir)
    app = FastAPI(title="Poker Training Analyzer API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "parser_provider": active_settings.parser_provider,
            "recommendation_provider": active_settings.recommendation_provider,
        }

    @app.post("/api/jobs", response_model=JobRecord)
    async def create_job(file: UploadFile = File(...)) -> JobRecord:
        content_type = file.content_type or ""
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Upload must be an image")

        image_bytes = await file.read()
        job = store.create_job(
            original_filename=file.filename or "screenshot.png",
            image_bytes=image_bytes,
            parser_provider=active_settings.parser_provider,
            recommendation_provider=active_settings.recommendation_provider,
        )
        parser = build_parser(active_settings)
        try:
            parser_result = parser.parse(store.image_path(job))
        except ParserError as exc:
            job.status = "error"
            job.error = str(exc)
            store.save(job)
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        job.parser_result = parser_result
        job.status = "parsed"
        if should_auto_approve(parser_result.confidences, active_settings):
            job.approved_state = CanonicalState.from_parser_result(parser_result)
            job.approved_state.user_approved = True
            job.status = "approved"
        return store.save(job)

    @app.get("/api/jobs/{job_id}", response_model=JobRecord)
    def get_job(job_id: str) -> JobRecord:
        return load_job_or_404(store, job_id)

    @app.get("/api/jobs/{job_id}/image")
    def get_job_image(job_id: str) -> FileResponse:
        job = load_job_or_404(store, job_id)
        return FileResponse(store.image_path(job))

    @app.post("/api/jobs/{job_id}/approve", response_model=JobRecord)
    def approve_job(job_id: str, state: CanonicalState) -> JobRecord:
        job = load_job_or_404(store, job_id)
        state.user_approved = True
        job.approved_state = state
        job.status = "approved"
        job.error = None
        return store.save(job)

    @app.post("/api/jobs/{job_id}/recommend", response_model=JobRecord)
    def recommend(job_id: str) -> JobRecord:
        job = load_job_or_404(store, job_id)
        if job.approved_state is None or not job.approved_state.user_approved:
            raise HTTPException(status_code=409, detail="Approve corrected state before requesting recommendation")

        provider = build_provider(active_settings)
        missing = missing_required_fields(job.approved_state, provider.required_fields)
        if missing:
            raise HTTPException(status_code=422, detail={"missing_fields": missing})

        try:
            result = provider.recommend(RecommendationRequest(state=job.approved_state, provider=provider.name))
        except ProviderError as exc:
            job.status = "error"
            job.error = str(exc)
            store.save(job)
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        job.recommendation = result
        job.status = "recommended"
        job.error = None
        return store.save(job)

    return app


def load_job_or_404(store: FileJobStore, job_id: str) -> JobRecord:
    try:
        return store.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Job not found") from exc


def should_auto_approve(confidences: dict[str, float], settings: Settings) -> bool:
    if not settings.parser_auto_approve_enabled:
        return False
    for field_name, threshold in settings.parser_auto_approve_thresholds.items():
        if confidences.get(field_name, 0) < threshold:
            return False
    return True
```

Create `backend/app/main.py`:

```python
from app.api import create_app

app = create_app()
```

- [ ] **Step 4: Run API tests**

Run:

```bash
cd backend
python -m pytest tests/test_api_flow.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Run all backend tests**

Run:

```bash
cd backend
python -m pytest -q
```

Expected: `16 passed`.

- [ ] **Step 6: Commit API slice**

Run:

```bash
git add backend/app/storage.py backend/app/api.py backend/app/main.py backend/tests/test_api_flow.py
git commit -m "feat: add analysis job API"
```

Expected: commit succeeds.

## Task 5: Frontend Control Panel

**Files:**

- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/App.css`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write frontend smoke test and package config**

Create `frontend/package.json`:

```json
{
  "name": "poker-training-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^4.3.0",
    "lucide-react": "^0.468.0",
    "vite": "^5.4.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.5.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "typescript": "^5.5.0",
    "vitest": "^2.0.0",
    "jsdom": "^25.0.0"
  }
}
```

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Poker Training Analyzer</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2020"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create `frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

Create `frontend/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

Create `frontend/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

Create `frontend/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import App from "./App";

describe("App", () => {
  it("renders the upload control panel", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Poker Training Analyzer" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Upload and parse" }),
    ).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run frontend test to verify it fails**

Run:

```bash
cd frontend
npm install
npm test
```

Expected: exits non-zero with `Failed to resolve import "./App"`.

- [ ] **Step 3: Add frontend API types, client, and control panel**

Create `frontend/src/types.ts`:

```ts
export type Suit = "clubs" | "diamonds" | "hearts" | "spades";
export type Street = "preflop" | "flop" | "turn" | "river";
export type RecommendationAction = "fold" | "check" | "call" | "bet" | "raise";

export interface Card {
  rank: string;
  suit: Suit;
}

export interface DetectedState {
  hero_cards: Card[];
  board_cards: Card[];
  pot_size: number | null;
  current_bet: number | null;
  effective_stack: number | null;
  players_in_hand: number | null;
  hero_position: string | null;
  street: Street | null;
  action_context: string | null;
}

export interface ParserResult {
  state: DetectedState;
  confidences: Record<string, number>;
  warnings: string[];
  raw: Record<string, unknown>;
}

export interface CanonicalState extends DetectedState {
  user_approved: boolean;
}

export interface RecommendationResult {
  action: RecommendationAction;
  sizing: number | null;
  confidence: number;
  explanation: string;
  raw: Record<string, unknown>;
}

export interface JobRecord {
  id: string;
  status: "created" | "parsed" | "approved" | "recommended" | "error";
  original_filename: string;
  image_filename: string;
  parser_provider: string;
  recommendation_provider: string;
  parser_result: ParserResult | null;
  approved_state: CanonicalState | null;
  recommendation: RecommendationResult | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}
```

Create `frontend/src/api.ts`:

```ts
import type { CanonicalState, JobRecord } from "./types";

const API_BASE_URL =
  typeof import.meta.env.VITE_API_BASE_URL === "string" &&
  import.meta.env.VITE_API_BASE_URL.length > 0
    ? import.meta.env.VITE_API_BASE_URL
    : "http://localhost:8000";

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail =
        typeof payload.detail === "string"
          ? payload.detail
          : JSON.stringify(payload.detail);
    } catch {
      detail = response.statusText;
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function imageUrl(jobId: string): string {
  return `${API_BASE_URL}/api/jobs/${jobId}/image`;
}

export async function uploadScreenshot(file: File): Promise<JobRecord> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE_URL}/api/jobs`, {
    method: "POST",
    body: form,
  });
  return readJson<JobRecord>(response);
}

export async function approveState(
  jobId: string,
  state: CanonicalState,
): Promise<JobRecord> {
  const response = await fetch(`${API_BASE_URL}/api/jobs/${jobId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...state, user_approved: true }),
  });
  return readJson<JobRecord>(response);
}

export async function requestRecommendation(jobId: string): Promise<JobRecord> {
  const response = await fetch(`${API_BASE_URL}/api/jobs/${jobId}/recommend`, {
    method: "POST",
  });
  return readJson<JobRecord>(response);
}
```

Create `frontend/src/App.tsx`:

```tsx
import { AlertTriangle, Check, Play, RefreshCcw, Upload } from "lucide-react";
import type { ChangeEvent, ReactNode } from "react";
import { useMemo, useState } from "react";

import "./App.css";
import {
  approveState,
  imageUrl,
  requestRecommendation,
  uploadScreenshot,
} from "./api";
import type { CanonicalState, Card, JobRecord, Street, Suit } from "./types";

const SUIT_BY_CODE: Record<string, Suit> = {
  c: "clubs",
  d: "diamonds",
  h: "hearts",
  s: "spades",
};

const CODE_BY_SUIT: Record<Suit, string> = {
  clubs: "c",
  diamonds: "d",
  hearts: "h",
  spades: "s",
};

const EMPTY_STATE: CanonicalState = {
  hero_cards: [],
  board_cards: [],
  pot_size: null,
  current_bet: null,
  effective_stack: null,
  players_in_hand: null,
  hero_position: null,
  street: null,
  action_context: null,
  user_approved: false,
};

function cardToCode(card: Card): string {
  return `${card.rank}${CODE_BY_SUIT[card.suit]}`;
}

function parseCards(value: string): Card[] {
  return value
    .split(/[,\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((code) => {
      const rank = code.slice(0, -1).toUpperCase().replace("10", "T");
      const suit = SUIT_BY_CODE[code.slice(-1).toLowerCase()];
      if (!rank || !suit) {
        throw new Error(`Invalid card code: ${code}`);
      }
      return { rank, suit };
    });
}

function formatCards(cards: Card[]): string {
  return cards.map(cardToCode).join(" ");
}

function parseOptionalNumber(value: string): number | null {
  if (value.trim() === "") {
    return null;
  }
  const parsed = Number(value);
  if (Number.isNaN(parsed)) {
    throw new Error(`Invalid number: ${value}`);
  }
  return parsed;
}

function confidenceLabel(value: number | undefined): string {
  if (value === undefined) {
    return "not detected";
  }
  return `${Math.round(value * 100)}%`;
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [draft, setDraft] = useState<CanonicalState>(EMPTY_STATE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confidences = job?.parser_result?.confidences || {};
  const canApprove = Boolean(
    job?.parser_result && draft.hero_cards.length > 0 && draft.street,
  );
  const canRecommend = Boolean(job?.approved_state);
  const screenshotUrl = useMemo(() => (job ? imageUrl(job.id) : null), [job]);

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(
      event.target.files && event.target.files[0]
        ? event.target.files[0]
        : null,
    );
  }

  async function onUpload() {
    if (!file) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await uploadScreenshot(file);
      setJob(created);
      setDraft(
        created.approved_state || created.parser_result?.state || EMPTY_STATE,
      );
    } catch (uploadError) {
      setError(
        uploadError instanceof Error ? uploadError.message : "Upload failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function onApprove() {
    if (!job) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const approved = await approveState(job.id, draft);
      setJob(approved);
      setDraft(approved.approved_state || draft);
    } catch (approveError) {
      setError(
        approveError instanceof Error
          ? approveError.message
          : "Approval failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function onRecommend() {
    if (!job) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setJob(await requestRecommendation(job.id));
    } catch (recommendError) {
      setError(
        recommendError instanceof Error
          ? recommendError.message
          : "Recommendation failed",
      );
    } finally {
      setBusy(false);
    }
  }

  function updateCards(field: "hero_cards" | "board_cards", value: string) {
    setDraft((current) => ({ ...current, [field]: parseCards(value) }));
  }

  function updateNumber(
    field: "pot_size" | "current_bet" | "effective_stack" | "players_in_hand",
    value: string,
  ) {
    setDraft((current) => ({
      ...current,
      [field]: parseOptionalNumber(value),
    }));
  }

  function updateText(
    field: "hero_position" | "action_context",
    value: string,
  ) {
    setDraft((current) => ({
      ...current,
      [field]: value.trim() === "" ? null : value,
    }));
  }

  function updateStreet(value: string) {
    setDraft((current) => ({
      ...current,
      street: value === "" ? null : (value as Street),
    }));
  }

  return (
    <main className="app-shell">
      <section className="toolbar" aria-label="Analyzer controls">
        <div>
          <h1>Poker Training Analyzer</h1>
          <p>Post-hand review for Texas Hold&apos;em screenshots.</p>
        </div>
        <div className="toolbar-actions">
          <label className="file-picker">
            <Upload size={18} aria-hidden="true" />
            <span>{file ? file.name : "Choose screenshot"}</span>
            <input type="file" accept="image/*" onChange={onFileChange} />
          </label>
          <button type="button" onClick={onUpload} disabled={!file || busy}>
            <Upload size={18} aria-hidden="true" />
            Upload and parse
          </button>
        </div>
      </section>

      {error ? (
        <div className="notice error" role="alert">
          <AlertTriangle size={18} aria-hidden="true" />
          <span>{error}</span>
        </div>
      ) : null}

      <section className="workspace">
        <div className="screenshot-pane">
          {screenshotUrl ? (
            <img src={screenshotUrl} alt="Uploaded poker table screenshot" />
          ) : (
            <div className="empty-screenshot">No screenshot uploaded</div>
          )}
        </div>

        <div className="review-pane">
          <div className="panel-header">
            <div>
              <h2>Detected State</h2>
              <span>
                {job ? `${job.parser_provider} parser` : "Waiting for upload"}
              </span>
            </div>
            {job ? <StatusPill status={job.status} /> : null}
          </div>

          <div className="field-grid">
            <Field
              label="Hero cards"
              confidence={confidenceLabel(confidences.hero_cards)}
            >
              <input
                value={formatCards(draft.hero_cards)}
                onChange={(event) =>
                  updateCards("hero_cards", event.target.value)
                }
              />
            </Field>
            <Field
              label="Board cards"
              confidence={confidenceLabel(confidences.board_cards)}
            >
              <input
                value={formatCards(draft.board_cards)}
                onChange={(event) =>
                  updateCards("board_cards", event.target.value)
                }
              />
            </Field>
            <Field
              label="Street"
              confidence={confidenceLabel(confidences.street)}
            >
              <select
                value={draft.street || ""}
                onChange={(event) => updateStreet(event.target.value)}
              >
                <option value="">Select street</option>
                <option value="preflop">Preflop</option>
                <option value="flop">Flop</option>
                <option value="turn">Turn</option>
                <option value="river">River</option>
              </select>
            </Field>
            <Field
              label="Pot"
              confidence={confidenceLabel(confidences.pot_size)}
            >
              <input
                value={draft.pot_size === null ? "" : draft.pot_size}
                onChange={(event) =>
                  updateNumber("pot_size", event.target.value)
                }
              />
            </Field>
            <Field
              label="Current bet"
              confidence={confidenceLabel(confidences.current_bet)}
            >
              <input
                value={draft.current_bet === null ? "" : draft.current_bet}
                onChange={(event) =>
                  updateNumber("current_bet", event.target.value)
                }
              />
            </Field>
            <Field
              label="Effective stack"
              confidence={confidenceLabel(confidences.effective_stack)}
            >
              <input
                value={
                  draft.effective_stack === null ? "" : draft.effective_stack
                }
                onChange={(event) =>
                  updateNumber("effective_stack", event.target.value)
                }
              />
            </Field>
            <Field
              label="Players in hand"
              confidence={confidenceLabel(confidences.players_in_hand)}
            >
              <input
                value={
                  draft.players_in_hand === null ? "" : draft.players_in_hand
                }
                onChange={(event) =>
                  updateNumber("players_in_hand", event.target.value)
                }
              />
            </Field>
            <Field
              label="Hero position"
              confidence={confidenceLabel(confidences.hero_position)}
            >
              <input
                value={draft.hero_position || ""}
                onChange={(event) =>
                  updateText("hero_position", event.target.value)
                }
              />
            </Field>
            <Field label="Action context" confidence="manual review">
              <textarea
                value={draft.action_context || ""}
                onChange={(event) =>
                  updateText("action_context", event.target.value)
                }
              />
            </Field>
          </div>

          <div className="review-actions">
            <button
              type="button"
              onClick={onApprove}
              disabled={!canApprove || busy}
            >
              <Check size={18} aria-hidden="true" />
              Approve state
            </button>
            <button
              type="button"
              onClick={onRecommend}
              disabled={!canRecommend || busy}
            >
              <Play size={18} aria-hidden="true" />
              Request recommendation
            </button>
            <button
              type="button"
              onClick={() =>
                job?.parser_result && setDraft(job.parser_result.state)
              }
              disabled={!job?.parser_result || busy}
            >
              <RefreshCcw size={18} aria-hidden="true" />
              Reset to parser
            </button>
          </div>

          {job?.recommendation ? (
            <section className="recommendation" aria-label="Recommendation">
              <div>
                <span className="recommendation-action">
                  {job.recommendation.action}
                </span>
                <span className="recommendation-confidence">
                  {Math.round(job.recommendation.confidence * 100)}% confidence
                </span>
              </div>
              {job.recommendation.sizing !== null ? (
                <p>Suggested sizing: {job.recommendation.sizing}</p>
              ) : null}
              <p>{job.recommendation.explanation}</p>
            </section>
          ) : null}
        </div>
      </section>
    </main>
  );
}

function Field({
  label,
  confidence,
  children,
}: {
  label: string;
  confidence: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>
        {label}
        <small>{confidence}</small>
      </span>
      {children}
    </label>
  );
}

function StatusPill({ status }: { status: JobRecord["status"] }) {
  return <span className={`status-pill status-${status}`}>{status}</span>;
}
```

Create `frontend/src/App.css`:

```css
:root {
  color: #17201d;
  background: #f5f7f4;
  font-family:
    Inter,
    ui-sans-serif,
    system-ui,
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
}

button,
input,
select,
textarea {
  font: inherit;
}

button {
  align-items: center;
  background: #1f6f5b;
  border: 1px solid #1f6f5b;
  border-radius: 6px;
  color: #ffffff;
  cursor: pointer;
  display: inline-flex;
  gap: 8px;
  min-height: 40px;
  padding: 0 14px;
}

button:disabled {
  background: #d4ddd8;
  border-color: #d4ddd8;
  color: #74817b;
  cursor: not-allowed;
}

.app-shell {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 100vh;
  padding: 20px;
}

.toolbar {
  align-items: center;
  background: #ffffff;
  border: 1px solid #dce4df;
  border-radius: 8px;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 16px;
}

.toolbar h1 {
  font-size: 24px;
  letter-spacing: 0;
  line-height: 1.2;
  margin: 0;
}

.toolbar p {
  color: #5f6f68;
  margin: 4px 0 0;
}

.toolbar-actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.file-picker {
  align-items: center;
  background: #ffffff;
  border: 1px solid #bdc9c3;
  border-radius: 6px;
  color: #24312d;
  cursor: pointer;
  display: inline-flex;
  gap: 8px;
  min-height: 40px;
  max-width: 280px;
  padding: 0 14px;
}

.file-picker span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-picker input {
  display: none;
}

.notice {
  align-items: center;
  border-radius: 8px;
  display: flex;
  gap: 8px;
  padding: 12px 14px;
}

.notice.error {
  background: #fff0ed;
  border: 1px solid #e7aaa0;
  color: #8b2d1f;
}

.workspace {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(320px, 1.2fr) minmax(360px, 0.8fr);
  min-height: 0;
}

.screenshot-pane,
.review-pane {
  background: #ffffff;
  border: 1px solid #dce4df;
  border-radius: 8px;
  min-height: 640px;
}

.screenshot-pane {
  display: grid;
  place-items: center;
  overflow: hidden;
}

.screenshot-pane img {
  height: 100%;
  max-height: calc(100vh - 156px);
  max-width: 100%;
  object-fit: contain;
  width: 100%;
}

.empty-screenshot {
  color: #6d7c75;
  display: grid;
  min-height: 320px;
  place-items: center;
}

.review-pane {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
}

.panel-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.panel-header h2 {
  font-size: 18px;
  letter-spacing: 0;
  line-height: 1.2;
  margin: 0;
}

.panel-header span {
  color: #66756f;
  font-size: 14px;
}

.status-pill {
  border-radius: 999px;
  font-size: 13px;
  padding: 4px 10px;
  text-transform: capitalize;
}

.status-created,
.status-parsed {
  background: #eef2f7;
  color: #415167;
}

.status-approved {
  background: #e9f5ef;
  color: #1f6f5b;
}

.status-recommended {
  background: #fff6dd;
  color: #7a5b10;
}

.status-error {
  background: #fff0ed;
  color: #8b2d1f;
}

.field-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field span {
  align-items: baseline;
  color: #25332f;
  display: flex;
  font-size: 14px;
  justify-content: space-between;
}

.field small {
  color: #697a72;
  font-size: 12px;
}

.field input,
.field select,
.field textarea {
  border: 1px solid #bdc9c3;
  border-radius: 6px;
  min-height: 38px;
  padding: 8px 10px;
  width: 100%;
}

.field textarea {
  min-height: 76px;
  resize: vertical;
}

.field:last-child {
  grid-column: 1 / -1;
}

.review-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.review-actions button:nth-child(3) {
  background: #ffffff;
  border-color: #bdc9c3;
  color: #24312d;
}

.recommendation {
  background: #f8fbf0;
  border: 1px solid #d6e5ad;
  border-radius: 8px;
  padding: 14px;
}

.recommendation div {
  align-items: baseline;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.recommendation-action {
  color: #1f6f5b;
  font-size: 24px;
  font-weight: 700;
  text-transform: capitalize;
}

.recommendation-confidence {
  color: #65715f;
  font-size: 14px;
}

.recommendation p {
  margin: 8px 0 0;
}

@media (max-width: 920px) {
  .toolbar,
  .workspace {
    grid-template-columns: 1fr;
  }

  .toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .toolbar-actions {
    justify-content: flex-start;
  }

  .screenshot-pane,
  .review-pane {
    min-height: auto;
  }
}

@media (max-width: 620px) {
  .app-shell {
    padding: 12px;
  }

  .field-grid {
    grid-template-columns: 1fr;
  }

  .toolbar-actions,
  .review-actions {
    align-items: stretch;
    flex-direction: column;
  }

  button,
  .file-picker {
    justify-content: center;
    width: 100%;
  }
}
```

Create `frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 4: Run frontend tests and build**

Run:

```bash
cd frontend
npm test
npm run build
```

Expected: test output includes `1 passed`; build exits `0` and writes `frontend/dist/`.

- [ ] **Step 5: Commit frontend control panel**

Run:

```bash
git add frontend/package.json frontend/package-lock.json frontend/index.html frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts frontend/src
git commit -m "feat: add training analyzer control panel"
```

Expected: commit succeeds.

## Task 6: Developer Documentation And Local Run Config

**Files:**

- Create: `.gitignore`
- Create: `.env.example`
- Create: `README.md`

- [ ] **Step 1: Write documentation verification test**

Run:

```bash
test -f README.md
```

Expected: exits non-zero because `README.md` does not exist yet.

- [ ] **Step 2: Add ignore rules, config example, and README**

Create `.gitignore`:

```gitignore
.DS_Store
.env
.venv/
__pycache__/
.pytest_cache/
backend/*.egg-info/
backend/data/
frontend/node_modules/
frontend/dist/
frontend/.vite/
```

Create `.env.example`:

```dotenv
POKER_DATA_DIR=backend/data
POKER_PARSER_PROVIDER=mock
POKER_PARSER_LAYOUT_PROFILE=generic
POKER_PARSER_AUTO_APPROVE_ENABLED=false
POKER_PARSER_AUTO_APPROVE_THRESHOLDS={"hero_cards":0.98,"board_cards":0.98,"pot_size":0.95,"street":0.99}
POKER_RECOMMENDATION_PROVIDER=mock
POKER_EXTERNAL_PARSER_URL=
POKER_EXTERNAL_PROVIDER_URL=
POKER_LLM_ADVICE_URL=
POKER_LOCAL_SOLVER_COMMAND=
POKER_LOCAL_SOLVER_TIMEOUT_SECONDS=30
```

Create `README.md`:

````markdown
# Poker Training Analyzer

Local-first training app for reviewing Texas Hold'em screenshots. The app uploads one screenshot at a time, parses table state through a configurable backend parser, lets the user verify or correct the extracted state, then requests a configurable training recommendation.

This project is for post-hand study and game understanding. It is not built for live-play automation or covert real-time assistance.

## Project Layout

- `backend/`: FastAPI API, parser/provider registries, file-backed job storage.
- `frontend/`: React/Vite control panel for upload, review, approval, and recommendation.
- `docs/superpowers/specs/`: approved design spec.
- `docs/superpowers/plans/`: implementation plan.

## Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
````

Health check:

```bash
curl http://127.0.0.1:8000/api/health
```

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Configuration

Copy `.env.example` to `backend/.env` for local backend settings.

Parser choices:

- `POKER_PARSER_PROVIDER=mock`: deterministic parser for development.
- `POKER_PARSER_PROVIDER=llm_vision`: sends screenshots to `POKER_EXTERNAL_PARSER_URL`.
- `POKER_PARSER_PROVIDER=ocr_cv`: registered adapter that returns a configuration error until a concrete OCR command or library adapter is added.

Recommendation choices:

- `POKER_RECOMMENDATION_PROVIDER=mock`: deterministic training recommendation.
- `POKER_RECOMMENDATION_PROVIDER=local_solver`: runs `POKER_LOCAL_SOLVER_COMMAND` and expects JSON on stdout.
- `POKER_RECOMMENDATION_PROVIDER=external_solver`: posts canonical state to `POKER_EXTERNAL_PROVIDER_URL`.
- `POKER_RECOMMENDATION_PROVIDER=llm_advice`: posts canonical state to `POKER_LLM_ADVICE_URL`.

## Test Commands

Backend:

```bash
cd backend
python -m pytest -q
```

Frontend:

```bash
cd frontend
npm test
npm run build
```

````

- [ ] **Step 3: Verify documentation files**

Run:

```bash
test -f README.md
test -f .env.example
test -f .gitignore
rg -n "live-play automation|post-hand study|POKER_RECOMMENDATION_PROVIDER" README.md .env.example
````

Expected: all commands exit `0`, and `rg` prints matching lines from `README.md` and `.env.example`.

- [ ] **Step 4: Commit docs and config**

Run:

```bash
git add .gitignore .env.example README.md
git commit -m "docs: add local setup guide"
```

Expected: commit succeeds.

## Task 7: Full Verification

**Files:**

- Modify only files needed to fix failures revealed by this task.

- [ ] **Step 1: Run backend verification**

Run:

```bash
cd backend
python -m pytest -q
```

Expected: `16 passed`.

- [ ] **Step 2: Run frontend verification**

Run:

```bash
cd frontend
npm test
npm run build
```

Expected: `npm test` reports `1 passed`; `npm run build` exits `0`.

- [ ] **Step 3: Run a local API smoke check**

Start the backend in one terminal:

```bash
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run in another terminal:

```bash
curl -s http://127.0.0.1:8000/api/health
```

Expected JSON:

```json
{ "status": "ok", "parser_provider": "mock", "recommendation_provider": "mock" }
```

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short
```

Expected: no output.
