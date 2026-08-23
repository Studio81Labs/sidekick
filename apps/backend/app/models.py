import math
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Self
from uuid import uuid4

from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.domain.pipeline import (
    PipelineCapabilities,
    PipelineOption,
    PipelineSelection,
)
from app.domain.poker import (
    Card,
    CompletedPostflopAction,
    CompletedPostflopActionType,
    CanonicalState,
    CompletedPostflopStreet,
    CompletedPostflopStreetHistory,
    DetectedState,
    FacingAction,
    NonNegativeFiniteNumber,
    PositiveFiniteNumber,
    PositiveInteger,
    ParserResult,
    PostflopAction,
    PostflopActionType,
    PostflopActor,
    PreflopAction,
    PreflopActionType,
    PreflopPosition,
    Rank,
    Street,
    Suit,
)
from app.domain.poker.models import CODE_BY_SUIT, RANKS, SUIT_BY_CODE
from app.domain.recommendations import (
    RecommendationAction,
    RecommendationRequest,
    RecommendationResult,
)
from app.domain.training import (
    TrainingActionDifference,
    TrainingCertainty,
    TrainingCertaintySummary,
    TrainingDecision,
    TrainingDecisionRequest,
    TrainingOutcome,
    TrainingPositionSummary,
    TrainingProgress,
    TrainingRecentHand,
    TrainingReviewCertainty,
    TrainingReviewOrder,
    TrainingReviewRequest,
    TrainingSolverCoverage,
    TrainingSolverCoverageTrend,
    TrainingSolverFallbackSummary,
    TrainingSolverRouteSummary,
    TrainingStreetSummary,
    TrainingTrend,
)
from app.domain.hands import (
    ArchiveJobsRequest,
    JobHistory,
    JobQueue,
    JobRecord,
    ScreenshotMetadataRequest,
)


DeploymentEnvironment = Literal["local", "staging", "production"]
BenchmarkFieldName = Literal[
    "hero_cards",
    "board_cards",
    "street",
    "pot_size",
    "current_bet",
    "hero_stack",
    "opponent_stack",
    "effective_stack",
    "players_in_hand",
    "hero_position",
    "opponent_position",
    "preflop_opener_position",
    "preflop_open_size",
    "preflop_action_history",
    "facing_action",
    "postflop_action_history",
    "completed_postflop_streets",
    "action_context",
]
BENCHMARK_FIELDS: tuple[BenchmarkFieldName, ...] = (
    "hero_cards",
    "board_cards",
    "street",
    "pot_size",
    "current_bet",
    "hero_stack",
    "opponent_stack",
    "effective_stack",
    "players_in_hand",
    "hero_position",
    "opponent_position",
    "preflop_opener_position",
    "preflop_open_size",
    "preflop_action_history",
    "facing_action",
    "postflop_action_history",
    "completed_postflop_streets",
    "action_context",
)
BENCHMARK_POSITION_ALIASES = {
    "btn": "button",
    "dealer": "button",
    "ip": "in position",
    "oop": "out of position",
}
NonNegativeInteger = Annotated[int, Field(ge=0, strict=True)]
UnitIntervalNumber = Annotated[
    float,
    Field(ge=0, le=1, allow_inf_nan=False, strict=True),
]

BENCHMARK_IMPORT_REQUEST_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"


def _validate_accuracy(
    correct: int,
    total: int,
    accuracy: float,
    label: str,
) -> None:
    expected = correct / total if total else 0
    if not math.isclose(accuracy, expected, rel_tol=0, abs_tol=1e-12):
        raise ValueError(f"{label} accuracy does not match its counts")


def _finite_benchmark_number(value: Any) -> float | None:
    if type(value) not in {int, float}:
        return None
    numeric_error = "Benchmark numeric values must be finite and representable"
    try:
        numeric_value = float(value)
    except OverflowError as exc:
        raise ValueError(numeric_error) from exc
    if not math.isfinite(numeric_value):
        raise ValueError(numeric_error)
    return numeric_value


def benchmark_values_match(expected: Any, detected: Any) -> bool:
    expected_numeric = _finite_benchmark_number(expected)
    detected_numeric = _finite_benchmark_number(detected)
    if expected_numeric is not None and detected_numeric is not None:
        return math.isclose(expected_numeric, detected_numeric, abs_tol=0.01)
    return expected == detected


class HealthResponse(BaseModel):
    status: Literal["ok"]
    environment: DeploymentEnvironment
    parser_provider: str
    recommendation_provider: str
    recommendation_engine: str


def normalize_benchmark_value(field_name: BenchmarkFieldName, value: Any) -> Any:
    if value is None:
        return None
    if field_name in {"hero_cards", "board_cards"}:
        codes = [card.code if isinstance(card, Card) else card for card in value]
        return sorted(codes)
    if field_name in {
        "preflop_action_history",
        "postflop_action_history",
    }:
        action_model = (
            PreflopAction
            if field_name == "preflop_action_history"
            else PostflopAction
        )
        return [
            (
                action
                if isinstance(action, action_model)
                else action_model.model_validate(action)
            ).model_dump(mode="json")
            for action in value
        ]
    if field_name == "completed_postflop_streets":
        return [
            (
                history
                if isinstance(history, CompletedPostflopStreetHistory)
                else CompletedPostflopStreetHistory.model_validate(history)
            ).model_dump(mode="json")
            for history in value
        ]
    if isinstance(value, str):
        normalized = re.sub(r"\s+", " ", value.strip().lower())
        if field_name in {
            "hero_position",
            "opponent_position",
            "preflop_opener_position",
        }:
            return BENCHMARK_POSITION_ALIASES.get(normalized, normalized)
        return normalized
    return value


class ApplicationBackupRestoreResult(BaseModel):
    imported_jobs: int = Field(ge=0)
    reused_jobs: int = Field(ge=0)
    imported_benchmark_reports: int = Field(ge=0)
    reused_benchmark_reports: int = Field(ge=0)
    total_jobs: int = Field(ge=0)
    total_benchmark_reports: int = Field(ge=0)


class BenchmarkSelectionRequest(BaseModel):
    included: bool


class BenchmarkRunRequest(BaseModel):
    parser_provider: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    parser_layout_profile: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )


class BenchmarkDatasetImportResult(BaseModel):
    imported_cases: int = Field(ge=0)
    reused_cases: int = Field(ge=0)
    included_cases: int = Field(ge=0)
    included_cases_by_layout: dict[str, NonNegativeInteger] | None = None
    job_ids: list[str] = Field(default_factory=list)


class BenchmarkDatasetImportReceipt(BaseModel):
    request_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=BENCHMARK_IMPORT_REQUEST_ID_PATTERN,
    )
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["pending", "completed", "failed"]
    result: BenchmarkDatasetImportResult | None = None
    error: str | None = None
    error_status: int | None = Field(default=None, ge=400, le=599)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status == "completed" and (
            self.result is None
            or self.error is not None
            or self.error_status is not None
        ):
            raise ValueError("completed import receipts require a result")
        if self.status == "failed" and (
            self.result is not None
            or self.error is None
            or self.error_status is None
        ):
            raise ValueError("failed import receipts require an error")
        if self.status == "pending" and (
            self.result is not None
            or self.error is not None
            or self.error_status is not None
        ):
            raise ValueError("pending import receipts cannot contain a result")
        return self


_BENCHMARK_CARD_LIMITS = {"hero_cards": 2, "board_cards": 5}
_BENCHMARK_NONNEGATIVE_NUMERIC_FIELDS = {
    "pot_size",
    "current_bet",
    "hero_stack",
    "opponent_stack",
    "effective_stack",
}
_BENCHMARK_TEXT_FIELDS = {
    "hero_position",
    "opponent_position",
    "preflop_opener_position",
    "action_context",
}


def _validate_benchmark_comparison_value(
    field_name: BenchmarkFieldName,
    value: Any,
    *,
    allow_none: bool,
) -> None:
    if value is None:
        if allow_none:
            return
        raise ValueError(f"Benchmark {field_name} expected value is required")

    if field_name in _BENCHMARK_CARD_LIMITS:
        if (
            type(value) is not list
            or len(value) > _BENCHMARK_CARD_LIMITS[field_name]
        ):
            raise ValueError(f"Benchmark {field_name} must contain card codes")
        card_codes: list[str] = []
        for code in value:
            if type(code) is not str:
                raise ValueError(f"Benchmark {field_name} must contain card codes")
            try:
                card = Card.from_code(code)
            except ValueError as exc:
                raise ValueError(
                    f"Benchmark {field_name} must contain card codes"
                ) from exc
            if card.code != code:
                raise ValueError(f"Benchmark {field_name} card codes must be canonical")
            card_codes.append(code)
        if len(card_codes) != len(set(card_codes)):
            raise ValueError(f"Benchmark {field_name} card codes must be unique")
        if card_codes != sorted(card_codes):
            raise ValueError(f"Benchmark {field_name} card codes must be sorted")
        if not allow_none and field_name == "hero_cards" and not card_codes:
            raise ValueError("Benchmark hero_cards expected value cannot be empty")
        return

    if field_name in _BENCHMARK_NONNEGATIVE_NUMERIC_FIELDS:
        numeric_value = _finite_benchmark_number(value)
        if numeric_value is None or numeric_value < 0:
            raise ValueError(f"Benchmark {field_name} must be a non-negative number")
        return

    if field_name == "preflop_open_size":
        numeric_value = _finite_benchmark_number(value)
        if numeric_value is None or numeric_value <= 0:
            raise ValueError("Benchmark preflop_open_size must be a positive number")
        return

    if field_name == "players_in_hand":
        if type(value) is not int or value <= 0:
            raise ValueError("Benchmark players_in_hand must be a positive integer")
        return

    if field_name == "street":
        if type(value) is not str or value not in {"preflop", "flop", "turn", "river"}:
            raise ValueError("Benchmark street value is invalid")
        return

    if field_name == "facing_action":
        if type(value) is not str or value not in {"bet", "raise"}:
            raise ValueError("Benchmark facing_action value is invalid")
        return

    if field_name in {"preflop_action_history", "postflop_action_history"}:
        action_model = (
            PreflopAction
            if field_name == "preflop_action_history"
            else PostflopAction
        )
        if type(value) is not list or len(value) > 8:
            raise ValueError(f"Benchmark {field_name} must contain actions")
        if not allow_none and not value:
            raise ValueError(f"Benchmark {field_name} expected value cannot be empty")
        for item in value:
            if type(item) is not dict:
                raise ValueError(f"Benchmark {field_name} must contain actions")
            try:
                normalized = action_model.model_validate(item).model_dump(mode="json")
            except ValidationError as exc:
                raise ValueError(
                    f"Benchmark {field_name} must contain valid actions"
                ) from exc
            if normalized != item:
                raise ValueError(f"Benchmark {field_name} actions must be canonical")
        return

    if field_name == "completed_postflop_streets":
        if type(value) is not list or len(value) > 2:
            raise ValueError(
                "Benchmark completed_postflop_streets must contain street histories"
            )
        if not allow_none and not value:
            raise ValueError(
                "Benchmark completed_postflop_streets expected value cannot be empty"
            )
        for item in value:
            if type(item) is not dict:
                raise ValueError(
                    "Benchmark completed_postflop_streets must contain street histories"
                )
            try:
                normalized = CompletedPostflopStreetHistory.model_validate(
                    item
                ).model_dump(mode="json")
            except ValidationError as exc:
                raise ValueError(
                    "Benchmark completed_postflop_streets must contain valid street histories"
                ) from exc
            if normalized != item:
                raise ValueError(
                    "Benchmark completed_postflop_streets histories must be canonical"
                )
        return

    if field_name in _BENCHMARK_TEXT_FIELDS:
        if type(value) is not str:
            raise ValueError(f"Benchmark {field_name} must be text")
        if not allow_none and field_name == "action_context" and not value.strip():
            raise ValueError("Benchmark action_context expected value cannot be empty")
        if value != normalize_benchmark_value(field_name, value):
            raise ValueError(f"Benchmark {field_name} text must be normalized")
        return

    raise ValueError(f"Benchmark comparison field {field_name} is unsupported")


class BenchmarkFieldComparison(BaseModel):
    field: BenchmarkFieldName
    expected: Any
    detected: Any
    matched: bool = Field(strict=True)
    confidence: UnitIntervalNumber | None = None

    @model_validator(mode="after")
    def validate_match(self) -> Self:
        _validate_benchmark_comparison_value(
            self.field,
            self.expected,
            allow_none=False,
        )
        _validate_benchmark_comparison_value(
            self.field,
            self.detected,
            allow_none=True,
        )
        if self.matched != benchmark_values_match(self.expected, self.detected):
            raise ValueError("Benchmark comparison matched flag is inconsistent")
        return self


class BenchmarkParserRouting(BaseModel):
    provider: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    selected_provider: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    layout_profile: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    fallback_from: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    fallback_reason: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_fallback(self) -> Self:
        if (self.fallback_from is None) != (self.fallback_reason is None):
            raise ValueError(
                "Benchmark parser fallback source and reason must be recorded together"
            )
        return self


class BenchmarkCaseResult(BaseModel):
    job_id: str
    original_filename: str
    status: Literal["completed", "error"]
    correct_fields: NonNegativeInteger
    evaluated_fields: NonNegativeInteger
    accuracy: UnitIntervalNumber
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    parser_routing: BenchmarkParserRouting | None = None
    comparisons: list[BenchmarkFieldComparison] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        fields = [comparison.field for comparison in self.comparisons]
        if len(fields) != len(set(fields)):
            raise ValueError("Benchmark case comparison fields must be unique")
        card_comparisons = [
            comparison
            for comparison in self.comparisons
            if comparison.field in {"hero_cards", "board_cards"}
        ]
        for side in ("expected", "detected"):
            card_codes = [
                code
                for comparison in card_comparisons
                for code in getattr(comparison, side) or []
            ]
            if len(card_codes) != len(set(card_codes)):
                raise ValueError(
                    f"Benchmark case {side} cards must be unique across fields"
                )
        if self.evaluated_fields != len(self.comparisons):
            raise ValueError("Benchmark case evaluated_fields does not match comparisons")
        matched = sum(comparison.matched for comparison in self.comparisons)
        if self.correct_fields != matched:
            raise ValueError("Benchmark case correct_fields does not match comparisons")
        _validate_accuracy(
            self.correct_fields,
            self.evaluated_fields,
            self.accuracy,
            "Benchmark case",
        )
        if self.status == "completed" and self.error is not None:
            raise ValueError("Completed benchmark cases cannot contain an error")
        if self.status == "error" and self.error is None:
            raise ValueError("Failed benchmark cases require an error")
        return self


class BenchmarkFieldMetric(BaseModel):
    field: BenchmarkFieldName
    correct: NonNegativeInteger
    total: NonNegativeInteger
    accuracy: UnitIntervalNumber

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        if self.correct > self.total:
            raise ValueError("Benchmark field correct count cannot exceed total")
        _validate_accuracy(
            self.correct,
            self.total,
            self.accuracy,
            "Benchmark field",
        )
        return self


class BenchmarkReport(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    parser_provider: str
    layout_profile: str
    corpus_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_cases: NonNegativeInteger
    successful_cases: NonNegativeInteger
    failed_cases: NonNegativeInteger
    correct_fields: NonNegativeInteger
    evaluated_fields: NonNegativeInteger
    accuracy: UnitIntervalNumber
    field_metrics: list[BenchmarkFieldMetric] = Field(default_factory=list)
    cases: list[BenchmarkCaseResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_metrics(self) -> Self:
        case_ids = [case.job_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Benchmark report case job IDs must be unique")
        if self.total_cases != len(self.cases):
            raise ValueError("Benchmark report total_cases does not match cases")
        successful_cases = sum(case.status == "completed" for case in self.cases)
        failed_cases = len(self.cases) - successful_cases
        if self.successful_cases != successful_cases:
            raise ValueError("Benchmark report successful_cases does not match cases")
        if self.failed_cases != failed_cases:
            raise ValueError("Benchmark report failed_cases does not match cases")
        correct_fields = sum(case.correct_fields for case in self.cases)
        evaluated_fields = sum(case.evaluated_fields for case in self.cases)
        if self.correct_fields != correct_fields:
            raise ValueError("Benchmark report correct_fields does not match cases")
        if self.evaluated_fields != evaluated_fields:
            raise ValueError("Benchmark report evaluated_fields does not match cases")
        _validate_accuracy(
            self.correct_fields,
            self.evaluated_fields,
            self.accuracy,
            "Benchmark report",
        )

        field_counts: dict[str, list[int]] = {}
        for case in self.cases:
            if (
                case.parser_routing is not None
                and case.parser_routing.provider != self.parser_provider
            ):
                raise ValueError(
                    "Benchmark case routing provider does not match the report"
                )
            if (
                case.parser_routing is not None
                and case.parser_routing.layout_profile != self.layout_profile
            ):
                raise ValueError(
                    "Benchmark case routing layout does not match the report"
                )
            for comparison in case.comparisons:
                counts = field_counts.setdefault(comparison.field, [0, 0])
                counts[1] += 1
                if comparison.matched:
                    counts[0] += 1
        metric_fields = [metric.field for metric in self.field_metrics]
        if len(metric_fields) != len(set(metric_fields)):
            raise ValueError("Benchmark report field metrics must be unique")
        if set(metric_fields) != set(field_counts):
            raise ValueError("Benchmark report field metrics do not match comparisons")
        for metric in self.field_metrics:
            correct, total = field_counts[metric.field]
            if metric.correct != correct or metric.total != total:
                raise ValueError("Benchmark report field metric counts do not match comparisons")
        return self


class BenchmarkReportSummary(BaseModel):
    id: str
    parser_provider: str
    layout_profile: str
    corpus_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    created_at: datetime
    total_cases: NonNegativeInteger
    failed_cases: NonNegativeInteger
    accuracy: UnitIntervalNumber
    field_metrics: list[BenchmarkFieldMetric] = Field(default_factory=list)

    @classmethod
    def from_report(cls, report: BenchmarkReport) -> "BenchmarkReportSummary":
        return cls(
            id=report.id,
            parser_provider=report.parser_provider,
            layout_profile=report.layout_profile,
            corpus_fingerprint=report.corpus_fingerprint,
            created_at=report.created_at,
            total_cases=report.total_cases,
            failed_cases=report.failed_cases,
            accuracy=report.accuracy,
            field_metrics=report.field_metrics,
        )


class BenchmarkParserPipelineSummary(BaseModel):
    parser: PipelineOption
    layout_profile: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    latest_report: BenchmarkReportSummary | None = None
    previous_report: BenchmarkReportSummary | None = None

    @model_validator(mode="after")
    def validate_report_pipeline(self) -> Self:
        for label, report in (
            ("Latest", self.latest_report),
            ("Previous", self.previous_report),
        ):
            if report is None:
                continue
            if report.parser_provider != self.parser.id:
                raise ValueError(f"{label} benchmark report does not match parser")
            if report.layout_profile != self.layout_profile:
                raise ValueError(f"{label} benchmark report does not match layout")
        if self.previous_report is None:
            return self
        if self.latest_report is None:
            raise ValueError("Previous benchmark report requires a latest report")
        if (
            self.latest_report.corpus_fingerprint is None
            or self.previous_report.corpus_fingerprint
            != self.latest_report.corpus_fingerprint
        ):
            raise ValueError("Pipeline benchmark reports must use the same corpus")
        if (
            self.previous_report.created_at,
            self.previous_report.id,
        ) >= (
            self.latest_report.created_at,
            self.latest_report.id,
        ):
            raise ValueError("Previous benchmark report must precede latest report")
        return self


class BenchmarkOverview(BaseModel):
    included_cases: NonNegativeInteger
    included_cases_by_layout: dict[str, NonNegativeInteger]
    corpus_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    default_layout_profile: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
    )
    latest_report: BenchmarkReport | None = None
    recent_reports: list[BenchmarkReportSummary] = Field(default_factory=list)
    parser_pipelines: list[BenchmarkParserPipelineSummary] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_layout_counts(self) -> Self:
        if sum(self.included_cases_by_layout.values()) != self.included_cases:
            raise ValueError("Benchmark layout counts must match included cases")
        parser_ids = [pipeline.parser.id for pipeline in self.parser_pipelines]
        if len(parser_ids) != len(set(parser_ids)):
            raise ValueError("Benchmark parser pipelines must be unique")
        return self
