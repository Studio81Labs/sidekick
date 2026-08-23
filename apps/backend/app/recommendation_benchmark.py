import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal, Self, Sequence, cast, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.config import Settings, get_settings
from app.domain.poker import Street
from app.models import (
    CanonicalState,
    RecommendationAction,
    RecommendationRequest,
    RecommendationResult,
)
from app.providers.base import (
    ProviderConfigurationError,
    RecommendationProvider,
    missing_required_fields,
)
from app.providers.registry import build_provider
from app.solvers.postflop_ranges import RangeSource


RECOMMENDATION_BENCHMARK_SCHEMA = "poker-hero-recommendation-benchmark"
RECOMMENDATION_BENCHMARK_SCHEMA_VERSION = 4
RECOMMENDATION_BENCHMARK_PREVIOUS_SCHEMA_VERSION = 3
RECOMMENDATION_BENCHMARK_TAGGED_SCHEMA_VERSION = 2
RECOMMENDATION_BENCHMARK_LEGACY_SCHEMA_VERSION = 1
MAX_RECOMMENDATION_BENCHMARK_BYTES = 4 * 1024 * 1024
MAX_RECOMMENDATION_BENCHMARK_REPORT_BYTES = 16 * 1024 * 1024
MAX_RECOMMENDATION_BENCHMARK_CASES = 1_000
MAX_REFERENCE_LINES = 20
PROVIDER_FREQUENCY_ROUNDING_UNIT = 0.0001
MAX_PROVIDER_FREQUENCY_ROUNDING_ERROR = 0.001
WAGER_ACTIONS = {"bet", "raise"}
VALID_ACTIONS: frozenset[str] = frozenset(get_args(RecommendationAction))
VALID_RANGE_SOURCES: frozenset[str] = frozenset(get_args(RangeSource))
RangeConditioningStatus = Literal["applied", "skipped"]

FiniteNumber = Annotated[
    float,
    Field(allow_inf_nan=False, strict=True),
]
PositiveFiniteNumber = Annotated[
    float,
    Field(gt=0, allow_inf_nan=False, strict=True),
]
Probability = Annotated[
    float,
    Field(ge=0, le=1, allow_inf_nan=False, strict=True),
]
PositiveProbability = Annotated[
    float,
    Field(gt=0, le=1, allow_inf_nan=False, strict=True),
]
BenchmarkTag = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    ),
]


@dataclass(frozen=True)
class RegressionMetricSpec:
    attribute: str
    label: str
    higher_is_better: bool
    unit: Literal["percent", "decimal", "bb"]


REGRESSION_METRICS = {
    "action_accuracy": RegressionMetricSpec(
        "action_accuracy", "Action accuracy", True, "percent"
    ),
    "line_accuracy": RegressionMetricSpec(
        "line_accuracy", "Line accuracy", True, "percent"
    ),
    "line_coverage": RegressionMetricSpec(
        "line_coverage", "Line evaluation coverage", True, "percent"
    ),
    "policy_coverage": RegressionMetricSpec(
        "policy_coverage", "Policy evaluation coverage", True, "percent"
    ),
    "average_policy_distance": RegressionMetricSpec(
        "average_policy_distance", "Average policy distance", False, "decimal"
    ),
    "ev_coverage": RegressionMetricSpec(
        "ev_coverage", "EV evaluation coverage", True, "percent"
    ),
    "average_ev_loss": RegressionMetricSpec(
        "average_reference_ev_loss_bb",
        "Average reference EV loss",
        False,
        "bb",
    ),
    "maximum_ev_loss": RegressionMetricSpec(
        "maximum_reference_ev_loss_bb",
        "Maximum reference EV loss",
        False,
        "bb",
    ),
    "conditioning_accuracy": RegressionMetricSpec(
        "conditioning_accuracy",
        "Range conditioning agreement",
        True,
        "percent",
    ),
    "conditioning_coverage": RegressionMetricSpec(
        "conditioning_coverage",
        "Range conditioning evidence coverage",
        True,
        "percent",
    ),
    "range_source_accuracy": RegressionMetricSpec(
        "range_source_accuracy", "Range source agreement", True, "percent"
    ),
    "range_source_coverage": RegressionMetricSpec(
        "range_source_coverage",
        "Range source evidence coverage",
        True,
        "percent",
    ),
    "fallback_rate": RegressionMetricSpec(
        "fallback_rate", "Fallback rate", False, "percent"
    ),
}
CASE_REGRESSION_METRICS = frozenset(
    {
        "action_accuracy",
        "line_accuracy",
        "line_coverage",
        "policy_coverage",
        "average_policy_distance",
        "ev_coverage",
        "average_ev_loss",
        "maximum_ev_loss",
        "conditioning_accuracy",
        "conditioning_coverage",
        "range_source_accuracy",
        "range_source_coverage",
        "fallback_rate",
    }
)


class RecommendationBenchmarkError(RuntimeError):
    pass


class RecommendationBenchmarkState(CanonicalState):
    model_config = ConfigDict(extra="forbid")


class RecommendationReferenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    version: str | None = Field(default=None, min_length=1, max_length=100)
    configuration: str | None = Field(default=None, min_length=1, max_length=1_000)


class RecommendationReferenceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: RecommendationAction
    sizing: PositiveFiniteNumber | None = None
    frequency: PositiveProbability
    ev_bb: FiniteNumber | None = None

    @model_validator(mode="after")
    def validate_sizing(self) -> Self:
        if self.action not in WAGER_ACTIONS and self.sizing is not None:
            raise ValueError("Sizing is only valid for bet or raise reference lines")
        return self


class RecommendationBenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    description: str | None = Field(default=None, max_length=500)
    tags: list[BenchmarkTag] = Field(default_factory=list, max_length=10)
    state: RecommendationBenchmarkState
    expected_range_conditioning: RangeConditioningStatus | None = None
    expected_range_source: RangeSource | None = None
    reference_lines: list[RecommendationReferenceLine] = Field(
        min_length=1,
        max_length=MAX_REFERENCE_LINES,
    )

    @model_validator(mode="after")
    def validate_reference_lines(self) -> Self:
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("Recommendation benchmark case tags must be unique")
        line_keys = [(line.action, line.sizing) for line in self.reference_lines]
        if len(line_keys) != len(set(line_keys)):
            raise ValueError("Reference line identities must be unique")
        if not math.isclose(
            sum(line.frequency for line in self.reference_lines),
            1.0,
            rel_tol=0,
            abs_tol=1e-9,
        ):
            raise ValueError("Reference line frequencies must sum to 1")
        ev_labels = [line.ev_bb is not None for line in self.reference_lines]
        if any(ev_labels) and not all(ev_labels):
            raise ValueError("Reference EV labels must cover every line or none")
        for action in WAGER_ACTIONS:
            action_lines = [
                line for line in self.reference_lines if line.action == action
            ]
            if len(action_lines) > 1 and any(
                line.sizing is None for line in action_lines
            ):
                raise ValueError(
                    "An action-only wager reference cannot share an action with sized lines"
                )
        return self


class RecommendationBenchmarkDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: Literal[RECOMMENDATION_BENCHMARK_SCHEMA] = Field(alias="schema")
    schema_version: Literal[
        RECOMMENDATION_BENCHMARK_LEGACY_SCHEMA_VERSION,
        RECOMMENDATION_BENCHMARK_TAGGED_SCHEMA_VERSION,
        RECOMMENDATION_BENCHMARK_PREVIOUS_SCHEMA_VERSION,
        RECOMMENDATION_BENCHMARK_SCHEMA_VERSION,
    ]
    name: str = Field(min_length=1, max_length=200)
    reference_source: RecommendationReferenceSource | None = None
    sizing_tolerance_bb: PositiveFiniteNumber = 0.01
    minimum_policy_frequency: PositiveProbability = 0.05
    cases: list[RecommendationBenchmarkCase] = Field(
        min_length=1,
        max_length=MAX_RECOMMENDATION_BENCHMARK_CASES,
    )

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version_type(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Schema version must be a JSON integer")
        return value

    @model_validator(mode="after")
    def validate_cases(self) -> Self:
        if self.schema_version == RECOMMENDATION_BENCHMARK_LEGACY_SCHEMA_VERSION:
            if self.reference_source is not None or any(
                case.tags for case in self.cases
            ):
                raise ValueError(
                    "Reference source and case tags require schema version 2"
                )
        if (
            self.schema_version < RECOMMENDATION_BENCHMARK_PREVIOUS_SCHEMA_VERSION
            and any(
                case.expected_range_conditioning is not None
                for case in self.cases
            )
        ):
            raise ValueError(
                "Range conditioning expectations require schema version 3"
            )
        if (
            self.schema_version < RECOMMENDATION_BENCHMARK_SCHEMA_VERSION
            and any(case.expected_range_source is not None for case in self.cases)
        ):
            raise ValueError("Range source expectations require schema version 4")
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Recommendation benchmark case IDs must be unique")
        for case in self.cases:
            if (
                case.expected_range_conditioning is not None
                and case.state.street not in {"turn", "river"}
            ):
                raise ValueError(
                    f"Case {case.id} can expect range conditioning only on turn or river"
                )
            if (
                case.expected_range_source is not None
                and case.state.street not in {"flop", "turn", "river"}
            ):
                raise ValueError(
                    f"Case {case.id} can expect a range source only postflop"
                )
            if not any(
                line.frequency >= self.minimum_policy_frequency
                for line in case.reference_lines
            ):
                raise ValueError(
                    f"Case {case.id} has no line at the supported frequency"
                )
            for action in WAGER_ACTIONS:
                sizings = sorted(
                    line.sizing
                    for line in case.reference_lines
                    if line.action == action and line.sizing is not None
                )
                for left, right in zip(sizings, sizings[1:], strict=False):
                    sizing_gap = Decimal(str(right)) - Decimal(str(left))
                    minimum_gap = Decimal(str(self.sizing_tolerance_bb)) * 2
                    if sizing_gap < minimum_gap:
                        raise ValueError(
                            f"Case {case.id} has ambiguous {action} sizings"
                        )
        return self


class RecommendationBenchmarkCaseResult(BaseModel):
    case_id: str
    description: str | None = None
    street: Street | None = None
    tags: list[BenchmarkTag] = Field(default_factory=list)
    status: Literal["completed", "error"]
    error: str | None = None
    action: RecommendationAction | None = None
    sizing: float | None = None
    confidence: float | None = None
    action_match: bool | None = None
    line_match: bool | None = None
    policy_distance: float | None = None
    reference_ev_loss_bb: float | None = None
    engine: str | None = None
    fallback_reason: str | None = None
    expected_range_conditioning: RangeConditioningStatus | None = None
    range_conditioning_status: RangeConditioningStatus | None = None
    range_conditioning_match: bool | None = None
    expected_range_source: RangeSource | None = None
    range_source: RangeSource | None = None
    range_source_match: bool | None = None


class RecommendationBenchmarkMetrics(BaseModel):
    total_cases: int = Field(ge=0)
    completed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    action_correct: int = Field(ge=0)
    action_evaluated: int = Field(ge=0)
    action_accuracy: float = Field(ge=0, le=1)
    line_correct: int = Field(ge=0)
    line_evaluated: int = Field(ge=0)
    line_accuracy: float | None = Field(default=None, ge=0, le=1)
    line_coverage: float = Field(ge=0, le=1)
    policy_evaluated_cases: int = Field(ge=0)
    policy_coverage: float = Field(ge=0, le=1)
    average_policy_distance: float | None = Field(default=None, ge=0, le=1)
    ev_evaluated_cases: int = Field(ge=0)
    ev_coverage: float = Field(ge=0, le=1)
    average_reference_ev_loss_bb: float | None = Field(default=None, ge=0)
    maximum_reference_ev_loss_bb: float | None = Field(default=None, ge=0)
    conditioning_expected_cases: int = Field(ge=0)
    conditioning_evaluated_cases: int = Field(ge=0)
    conditioning_correct_cases: int = Field(ge=0)
    conditioning_accuracy: float | None = Field(default=None, ge=0, le=1)
    conditioning_coverage: float | None = Field(default=None, ge=0, le=1)
    range_source_expected_cases: int = Field(ge=0)
    range_source_evaluated_cases: int = Field(ge=0)
    range_source_correct_cases: int = Field(ge=0)
    range_source_accuracy: float | None = Field(default=None, ge=0, le=1)
    range_source_coverage: float | None = Field(default=None, ge=0, le=1)
    fallback_cases: int = Field(ge=0)
    fallback_rate: float = Field(ge=0, le=1)


class RecommendationBenchmarkBreakdown(RecommendationBenchmarkMetrics):
    key: str


class RecommendationBenchmarkReport(RecommendationBenchmarkMetrics):
    dataset_name: str
    dataset_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    provider: str
    reference_source: RecommendationReferenceSource | None = None
    street_metrics: list[RecommendationBenchmarkBreakdown] = Field(
        default_factory=list
    )
    tag_metrics: list[RecommendationBenchmarkBreakdown] = Field(default_factory=list)
    cases: list[RecommendationBenchmarkCaseResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_report_metrics(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Recommendation benchmark case IDs must be unique")
        if any(len(case.tags) != len(set(case.tags)) for case in self.cases):
            raise ValueError("Recommendation benchmark case tags must be unique")
        expected = _aggregate_metrics(self.cases)
        if _metrics_payload(self) != expected.model_dump():
            raise ValueError("Recommendation benchmark aggregate metrics are inconsistent")
        expected_streets = {
            street or "unknown": _aggregate_metrics(
                [case for case in self.cases if case.street == street]
            ).model_dump()
            for street in (*get_args(Street), None)
            if any(case.street == street for case in self.cases)
        }
        if _breakdown_payload(self.street_metrics) != expected_streets:
            raise ValueError("Recommendation benchmark street metrics are inconsistent")
        expected_tags = {
            tag: _aggregate_metrics(
                [case for case in self.cases if tag in case.tags]
            ).model_dump()
            for tag in sorted({tag for case in self.cases for tag in case.tags})
        }
        if _breakdown_payload(self.tag_metrics) != expected_tags:
            raise ValueError("Recommendation benchmark tag metrics are inconsistent")
        return self


def recommendation_dataset_fingerprint(
    dataset: RecommendationBenchmarkDataset,
) -> str:
    normalized = dataset.model_dump(mode="json", by_alias=True)
    normalized.pop("name", None)
    for case in normalized["cases"]:
        case.pop("description", None)
        case["tags"] = sorted(case["tags"])
        case["reference_lines"] = sorted(
            case["reference_lines"],
            key=lambda line: json.dumps(
                line,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    normalized["cases"] = sorted(
        normalized["cases"],
        key=lambda case: case["id"],
    )
    payload = json.dumps(
        normalized,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _metrics_payload(
    metrics: RecommendationBenchmarkMetrics,
) -> dict[str, object]:
    return metrics.model_dump(
        include=set(RecommendationBenchmarkMetrics.model_fields)
    )


def _breakdown_payload(
    breakdowns: list[RecommendationBenchmarkBreakdown],
) -> dict[str, dict[str, object]]:
    keys = [breakdown.key for breakdown in breakdowns]
    if len(keys) != len(set(keys)):
        raise ValueError("Recommendation benchmark breakdown keys must be unique")
    return {
        breakdown.key: _metrics_payload(breakdown)
        for breakdown in breakdowns
    }


def load_recommendation_benchmark_dataset(
    path: Path,
) -> RecommendationBenchmarkDataset:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise RecommendationBenchmarkError(
            f"Could not read recommendation benchmark: {path}"
        ) from exc
    if size > MAX_RECOMMENDATION_BENCHMARK_BYTES:
        raise RecommendationBenchmarkError(
            "Recommendation benchmark exceeds the 4 MiB file limit"
        )
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise RecommendationBenchmarkError(
            f"Could not read recommendation benchmark: {path}"
        ) from exc
    try:
        return RecommendationBenchmarkDataset.model_validate_json(payload)
    except ValidationError as exc:
        first_error = exc.errors(include_url=False)[0]
        location = (
            ".".join(str(part) for part in first_error["loc"]) or "settings"
        )
        raise RecommendationBenchmarkError(
            "Recommendation benchmark is invalid at "
            f"{location}: {first_error['msg']}"
        ) from exc


def run_recommendation_benchmark(
    dataset: RecommendationBenchmarkDataset,
    provider: RecommendationProvider,
) -> RecommendationBenchmarkReport:
    results = [
        _run_case(case, dataset, provider)
        for case in dataset.cases
    ]
    metrics = _aggregate_metrics(results)
    street_metrics = [
        RecommendationBenchmarkBreakdown(
            key=street or "unknown",
            **_aggregate_metrics(
                [result for result in results if result.street == street]
            ).model_dump(),
        )
        for street in (*get_args(Street), None)
        if any(result.street == street for result in results)
    ]
    tag_metrics = [
        RecommendationBenchmarkBreakdown(
            key=tag,
            **_aggregate_metrics(
                [result for result in results if tag in result.tags]
            ).model_dump(),
        )
        for tag in sorted({tag for result in results for tag in result.tags})
    ]
    return RecommendationBenchmarkReport(
        dataset_name=dataset.name,
        dataset_fingerprint=recommendation_dataset_fingerprint(dataset),
        provider=provider.name,
        reference_source=dataset.reference_source,
        street_metrics=street_metrics,
        tag_metrics=tag_metrics,
        cases=results,
        **metrics.model_dump(),
    )


def _aggregate_metrics(
    results: list[RecommendationBenchmarkCaseResult],
) -> RecommendationBenchmarkMetrics:
    completed = [result for result in results if result.status == "completed"]
    action_correct = sum(result.action_match is True for result in completed)
    line_results = [
        result.line_match
        for result in completed
        if result.line_match is not None
    ]
    policy_distances = [
        result.policy_distance
        for result in completed
        if result.policy_distance is not None
    ]
    ev_losses = [
        result.reference_ev_loss_bb
        for result in completed
        if result.reference_ev_loss_bb is not None
    ]
    conditioning_expected = [
        result
        for result in results
        if result.expected_range_conditioning is not None
    ]
    conditioning_evaluated = [
        result
        for result in conditioning_expected
        if result.range_conditioning_status is not None
    ]
    conditioning_correct = sum(
        result.range_conditioning_match is True
        for result in conditioning_evaluated
    )
    range_source_expected = [
        result for result in results if result.expected_range_source is not None
    ]
    range_source_evaluated = [
        result
        for result in range_source_expected
        if result.range_source is not None
    ]
    range_source_correct = sum(
        result.range_source_match is True for result in range_source_evaluated
    )
    fallback_cases = sum(result.fallback_reason is not None for result in completed)
    completed_count = len(completed)
    return RecommendationBenchmarkMetrics(
        total_cases=len(results),
        completed_cases=completed_count,
        failed_cases=len(results) - completed_count,
        action_correct=action_correct,
        action_evaluated=completed_count,
        action_accuracy=action_correct / completed_count if completed else 0,
        line_correct=sum(line_results),
        line_evaluated=len(line_results),
        line_accuracy=(
            sum(line_results) / len(line_results) if line_results else None
        ),
        line_coverage=len(line_results) / completed_count if completed else 0,
        policy_evaluated_cases=len(policy_distances),
        policy_coverage=(
            len(policy_distances) / completed_count if completed else 0
        ),
        average_policy_distance=_average(policy_distances),
        ev_evaluated_cases=len(ev_losses),
        ev_coverage=len(ev_losses) / completed_count if completed else 0,
        average_reference_ev_loss_bb=_average(ev_losses),
        maximum_reference_ev_loss_bb=max(ev_losses) if ev_losses else None,
        conditioning_expected_cases=len(conditioning_expected),
        conditioning_evaluated_cases=len(conditioning_evaluated),
        conditioning_correct_cases=conditioning_correct,
        conditioning_accuracy=(
            conditioning_correct / len(conditioning_evaluated)
            if conditioning_evaluated
            else None
        ),
        conditioning_coverage=(
            len(conditioning_evaluated) / len(conditioning_expected)
            if conditioning_expected
            else None
        ),
        range_source_expected_cases=len(range_source_expected),
        range_source_evaluated_cases=len(range_source_evaluated),
        range_source_correct_cases=range_source_correct,
        range_source_accuracy=(
            range_source_correct / len(range_source_evaluated)
            if range_source_evaluated
            else None
        ),
        range_source_coverage=(
            len(range_source_evaluated) / len(range_source_expected)
            if range_source_expected
            else None
        ),
        fallback_cases=fallback_cases,
        fallback_rate=fallback_cases / completed_count if completed else 0,
    )


def benchmark_recommendation_file(
    path: Path,
    settings: Settings,
    provider: RecommendationProvider | None = None,
) -> RecommendationBenchmarkReport:
    dataset = load_recommendation_benchmark_dataset(path)
    try:
        active_provider = provider or build_provider(settings)
        return run_recommendation_benchmark(dataset, active_provider)
    except ProviderConfigurationError as exc:
        raise RecommendationBenchmarkError(
            f"Recommendation provider configuration error: {exc}"
        ) from exc


def load_recommendation_benchmark_report(
    path: Path,
) -> RecommendationBenchmarkReport:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise RecommendationBenchmarkError(
            f"Could not read recommendation baseline report: {path}"
        ) from exc
    if size > MAX_RECOMMENDATION_BENCHMARK_REPORT_BYTES:
        raise RecommendationBenchmarkError(
            "Recommendation baseline report exceeds the 16 MiB file limit"
        )
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise RecommendationBenchmarkError(
            f"Could not read recommendation baseline report: {path}"
        ) from exc
    if len(payload) > MAX_RECOMMENDATION_BENCHMARK_REPORT_BYTES:
        raise RecommendationBenchmarkError(
            "Recommendation baseline report exceeds the 16 MiB file limit"
        )
    try:
        return RecommendationBenchmarkReport.model_validate_json(payload)
    except ValidationError as exc:
        raise RecommendationBenchmarkError(
            "Recommendation baseline report is invalid"
        ) from exc


def validate_comparable_recommendation_baseline(
    report: RecommendationBenchmarkReport,
    baseline: RecommendationBenchmarkReport,
) -> None:
    if baseline.provider != report.provider:
        raise RecommendationBenchmarkError(
            "Recommendation baseline provider does not match the benchmark provider"
        )
    if baseline.dataset_fingerprint is None:
        raise RecommendationBenchmarkError(
            "Recommendation baseline does not include a dataset fingerprint"
        )
    if baseline.dataset_fingerprint != report.dataset_fingerprint:
        raise RecommendationBenchmarkError(
            "Recommendation baseline corpus does not match the benchmark dataset"
        )
    if sorted(case.case_id for case in baseline.cases) != sorted(
        case.case_id for case in report.cases
    ):
        raise RecommendationBenchmarkError(
            "Recommendation baseline cases do not match the benchmark dataset"
        )


def format_recommendation_benchmark_report(
    report: RecommendationBenchmarkReport,
    baseline: RecommendationBenchmarkReport | None = None,
) -> str:
    lines = [
        "Recommendation benchmark",
        f"Dataset: {report.dataset_name}",
        f"Reference: {_reference_source_label(report.reference_source)}",
        f"Provider: {report.provider}",
        (
            f"Cases: {report.completed_cases}/{report.total_cases} completed"
            f" ({report.failed_cases} failed)"
        ),
        (
            f"Action agreement: {report.action_correct}/{report.action_evaluated}"
            f" ({report.action_accuracy:.1%})"
        ),
        _optional_ratio(
            "Line agreement",
            report.line_correct,
            report.line_evaluated,
            report.line_accuracy,
        ),
        _coverage_metric(
            "Line evaluation coverage",
            report.line_evaluated,
            report.completed_cases,
            report.line_coverage,
        ),
        _optional_metric(
            "Average policy distance",
            report.average_policy_distance,
            report.policy_evaluated_cases,
        ),
        _coverage_metric(
            "Policy evaluation coverage",
            report.policy_evaluated_cases,
            report.completed_cases,
            report.policy_coverage,
        ),
        _optional_metric(
            "Average reference EV loss",
            report.average_reference_ev_loss_bb,
            report.ev_evaluated_cases,
            suffix=" BB",
        ),
        _coverage_metric(
            "EV evaluation coverage",
            report.ev_evaluated_cases,
            report.completed_cases,
            report.ev_coverage,
        ),
    ]
    if report.conditioning_expected_cases:
        lines.extend(
            [
                _optional_ratio(
                    "Range conditioning agreement",
                    report.conditioning_correct_cases,
                    report.conditioning_evaluated_cases,
                    report.conditioning_accuracy,
                ),
                _optional_ratio(
                    "Range conditioning evidence coverage",
                    report.conditioning_evaluated_cases,
                    report.conditioning_expected_cases,
                    report.conditioning_coverage,
                ),
            ]
        )
    if report.range_source_expected_cases:
        lines.extend(
            [
                _optional_ratio(
                    "Range source agreement",
                    report.range_source_correct_cases,
                    report.range_source_evaluated_cases,
                    report.range_source_accuracy,
                ),
                _optional_ratio(
                    "Range source evidence coverage",
                    report.range_source_evaluated_cases,
                    report.range_source_expected_cases,
                    report.range_source_coverage,
                ),
            ]
        )
    lines.append(
        f"Fallback: {report.fallback_cases}/{report.completed_cases}"
        f" ({report.fallback_rate:.1%})"
    )
    _append_breakdowns(lines, "Street breakdown", report.street_metrics)
    _append_breakdowns(lines, "Tag breakdown", report.tag_metrics)
    if baseline is not None:
        lines.append("Baseline comparison:")
        for metric, spec in REGRESSION_METRICS.items():
            lines.append(
                f"  {spec.label}: {_metric_change(report, baseline, metric)}"
            )
    cases_needing_review = [
        case
        for case in report.cases
        if case.status == "error"
        or case.action_match is False
        or case.line_match is False
        or (
            case.expected_range_conditioning is not None
            and case.range_conditioning_match is not True
        )
        or (
            case.expected_range_source is not None
            and case.range_source_match is not True
        )
    ]
    if cases_needing_review:
        lines.append("Cases needing review:")
        for case in cases_needing_review:
            detail = case.error or _case_mismatch_detail(case)
            lines.append(f"  {case.case_id}: {detail}")
    return "\n".join(lines)


def _run_case(
    case: RecommendationBenchmarkCase,
    dataset: RecommendationBenchmarkDataset,
    provider: RecommendationProvider,
) -> RecommendationBenchmarkCaseResult:
    try:
        missing = missing_required_fields(
            case.state,
            provider.required_fields_for(case.state),
        )
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        result = provider.recommend(
            RecommendationRequest(state=case.state, provider=provider.name)
        )
    except ProviderConfigurationError:
        raise
    except Exception as exc:
        return RecommendationBenchmarkCaseResult(
            case_id=case.id,
            description=case.description,
            street=case.state.street,
            tags=case.tags,
            status="error",
            error=str(exc) or exc.__class__.__name__,
            expected_range_conditioning=case.expected_range_conditioning,
            expected_range_source=case.expected_range_source,
        )

    supported_lines = [
        line
        for line in case.reference_lines
        if line.frequency >= dataset.minimum_policy_frequency
    ]
    supported_actions = {
        action
        for action in VALID_ACTIONS
        if sum(
            line.frequency
            for line in case.reference_lines
            if line.action == action
        )
        >= dataset.minimum_policy_frequency
    }
    action_match = result.action in supported_actions
    line_evaluated = all(
        line.action not in WAGER_ACTIONS or line.sizing is not None
        for line in supported_lines
    )
    line_match = (
        any(
            _reference_line_matches(
                line,
                result.action,
                result.sizing,
                dataset.sizing_tolerance_bb,
            )
            for line in supported_lines
        )
        if line_evaluated
        else None
    )
    raw = result.raw
    engine = _nonempty_string(raw.get("engine"))
    fallback_reason = _nonempty_string(raw.get("fallback_reason"))
    range_conditioning_status = _range_conditioning_status(
        raw.get("range_conditioning")
    )
    range_conditioning_match = (
        range_conditioning_status == case.expected_range_conditioning
        if range_conditioning_status is not None
        and case.expected_range_conditioning is not None
        else None
    )
    range_source = _range_source(raw.get("range_source"))
    range_source_match = (
        range_source == case.expected_range_source
        if range_source is not None and case.expected_range_source is not None
        else None
    )
    return RecommendationBenchmarkCaseResult(
        case_id=case.id,
        description=case.description,
        street=case.state.street,
        tags=case.tags,
        status="completed",
        action=result.action,
        sizing=result.sizing,
        confidence=result.confidence,
        action_match=action_match,
        line_match=line_match,
        policy_distance=_policy_distance(
            case,
            result,
            dataset.sizing_tolerance_bb,
        ),
        reference_ev_loss_bb=_reference_ev_loss(
            case,
            result,
            dataset.sizing_tolerance_bb,
        ),
        engine=engine,
        fallback_reason=fallback_reason,
        expected_range_conditioning=case.expected_range_conditioning,
        range_conditioning_status=range_conditioning_status,
        range_conditioning_match=range_conditioning_match,
        expected_range_source=case.expected_range_source,
        range_source=range_source,
        range_source_match=range_source_match,
    )


def _policy_distance(
    case: RecommendationBenchmarkCase,
    result: RecommendationResult,
    sizing_tolerance: float,
) -> float | None:
    candidates = result.raw.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    provider_frequencies = [0.0] * len(case.reference_lines)
    unmatched_frequency = 0.0
    total_frequency = 0.0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return None
        action = candidate.get("action")
        if not isinstance(action, str) or action not in VALID_ACTIONS:
            return None
        frequency = _finite_number(candidate.get("frequency"))
        if frequency is None or frequency < 0 or frequency > 1:
            return None
        total_frequency += frequency
        if frequency == 0:
            continue
        sizing = _candidate_sizing(action, candidate.get("sizing"))
        if sizing is _INVALID_SIZING:
            return None
        matching_indexes = [
            index
            for index, line in enumerate(case.reference_lines)
            if _reference_line_matches(line, action, sizing, sizing_tolerance)
        ]
        if len(matching_indexes) > 1:
            return None
        if matching_indexes:
            provider_frequencies[matching_indexes[0]] += frequency
        else:
            unmatched_frequency += frequency
    rounding_tolerance = min(
        len(candidates) * PROVIDER_FREQUENCY_ROUNDING_UNIT / 2 + 1e-9,
        MAX_PROVIDER_FREQUENCY_ROUNDING_ERROR,
    )
    if not math.isclose(
        total_frequency,
        1.0,
        rel_tol=0,
        abs_tol=rounding_tolerance,
    ):
        return None
    provider_frequencies = [
        frequency / total_frequency for frequency in provider_frequencies
    ]
    unmatched_frequency /= total_frequency
    difference = unmatched_frequency + sum(
        abs(provider_frequency - reference.frequency)
        for provider_frequency, reference in zip(
            provider_frequencies,
            case.reference_lines,
            strict=True,
        )
    )
    return round(difference / 2, 6)


def _reference_ev_loss(
    case: RecommendationBenchmarkCase,
    result: RecommendationResult,
    sizing_tolerance: float,
) -> float | None:
    if not all(line.ev_bb is not None for line in case.reference_lines):
        return None
    matching_lines = [
        line
        for line in case.reference_lines
        if _reference_line_matches(
            line,
            result.action,
            result.sizing,
            sizing_tolerance,
        )
    ]
    if len(matching_lines) != 1:
        return None
    best_ev = max(
        line.ev_bb
        for line in case.reference_lines
        if line.ev_bb is not None
    )
    selected_ev = matching_lines[0].ev_bb
    if selected_ev is None:
        return None
    return round(max(0.0, best_ev - selected_ev), 6)


def _reference_line_matches(
    line: RecommendationReferenceLine,
    action: str,
    sizing: float | None | object,
    tolerance: float,
) -> bool:
    if line.action != action:
        return False
    if line.action not in WAGER_ACTIONS or line.sizing is None:
        return True
    if not isinstance(sizing, (int, float)) or isinstance(sizing, bool):
        return False
    if not math.isfinite(sizing):
        return False
    return abs(Decimal(str(line.sizing)) - Decimal(str(sizing))) < Decimal(
        str(tolerance)
    )


_INVALID_SIZING = object()


def _candidate_sizing(action: str, value: object) -> float | None | object:
    if action in WAGER_ACTIONS:
        sizing = _finite_number(value)
        return sizing if sizing is not None and sizing > 0 else _INVALID_SIZING
    return None if value is None else _INVALID_SIZING


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _nonempty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _range_conditioning_status(value: object) -> RangeConditioningStatus | None:
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    if not isinstance(status, str):
        return None
    if status == "applied":
        return "applied"
    if status == "skipped":
        return "skipped"
    return None


def _range_source(value: object) -> RangeSource | None:
    if not isinstance(value, str) or value not in VALID_RANGE_SOURCES:
        return None
    return cast(RangeSource, value)


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _optional_ratio(
    label: str,
    correct: int,
    evaluated: int,
    value: float | None,
) -> str:
    if value is None:
        return f"{label}: not evaluated"
    return f"{label}: {correct}/{evaluated} ({value:.1%})"


def _optional_metric(
    label: str,
    value: float | None,
    evaluated: int,
    *,
    suffix: str = "",
) -> str:
    if value is None:
        return f"{label}: not evaluated"
    return f"{label}: {value:.3f}{suffix} across {evaluated} case(s)"


def _coverage_metric(
    label: str,
    evaluated: int,
    completed: int,
    coverage: float,
) -> str:
    return f"{label}: {evaluated}/{completed} ({coverage:.1%})"


def _reference_source_label(
    source: RecommendationReferenceSource | None,
) -> str:
    if source is None:
        return "not recorded"
    return f"{source.name} {source.version}" if source.version else source.name


def _append_breakdowns(
    lines: list[str],
    heading: str,
    breakdowns: list[RecommendationBenchmarkBreakdown],
) -> None:
    if not breakdowns:
        return
    lines.append(f"{heading}:")
    for item in breakdowns:
        line_accuracy = (
            f"{item.line_accuracy:.1%}"
            if item.line_accuracy is not None
            else "n/a"
        )
        policy_distance = (
            f"{item.average_policy_distance:.3f}"
            if item.average_policy_distance is not None
            else "n/a"
        )
        ev_loss = (
            f"{item.average_reference_ev_loss_bb:.3f} BB"
            if item.average_reference_ev_loss_bb is not None
            else "n/a"
        )
        conditioning = ""
        if item.conditioning_expected_cases:
            conditioning_accuracy = (
                f"{item.conditioning_accuracy:.1%}"
                if item.conditioning_accuracy is not None
                else "n/a"
            )
            conditioning_coverage = (
                f"{item.conditioning_coverage:.1%}"
                if item.conditioning_coverage is not None
                else "n/a"
            )
            conditioning = (
                f", conditioning {conditioning_accuracy}"
                f" ({conditioning_coverage} coverage)"
            )
        range_source = ""
        if item.range_source_expected_cases:
            range_source_accuracy = (
                f"{item.range_source_accuracy:.1%}"
                if item.range_source_accuracy is not None
                else "n/a"
            )
            range_source_coverage = (
                f"{item.range_source_coverage:.1%}"
                if item.range_source_coverage is not None
                else "n/a"
            )
            range_source = (
                f", range source {range_source_accuracy}"
                f" ({range_source_coverage} coverage)"
            )
        lines.append(
            f"  {item.key}: {item.completed_cases}/{item.total_cases} completed, "
            f"action {item.action_accuracy:.1%}, "
            f"line {line_accuracy} ({item.line_coverage:.1%} coverage), "
            f"policy distance {policy_distance} ({item.policy_coverage:.1%} coverage), "
            f"EV loss {ev_loss} ({item.ev_coverage:.1%} coverage)"
            f"{conditioning}{range_source}, "
            f"fallback {item.fallback_rate:.1%}"
        )


def _case_mismatch_detail(case: RecommendationBenchmarkCaseResult) -> str:
    mismatches = []
    if case.action_match is False:
        mismatches.append("action")
    if case.line_match is False:
        mismatches.append("line")
    if case.expected_range_conditioning is not None:
        if case.range_conditioning_status is None:
            mismatches.append(
                "range conditioning"
                f" (expected {case.expected_range_conditioning}, not reported)"
            )
        elif case.range_conditioning_match is False:
            mismatches.append(
                "range conditioning"
                f" (expected {case.expected_range_conditioning},"
                f" got {case.range_conditioning_status})"
            )
    if case.expected_range_source is not None:
        if case.range_source is None:
            mismatches.append(
                "range source"
                f" (expected {case.expected_range_source}, not reported)"
            )
        elif case.range_source_match is False:
            mismatches.append(
                "range source"
                f" (expected {case.expected_range_source}, got {case.range_source})"
            )
    return f"mismatched {', '.join(mismatches)}"


def _dataset_path_from_invocation(dataset_path: Path) -> Path:
    if dataset_path.is_absolute():
        return dataset_path
    invocation_dir = os.environ.get("POKER_BENCHMARK_BASE_DIR")
    return Path(invocation_dir) / dataset_path if invocation_dir else dataset_path


def _unit_interval(value: str) -> float:
    try:
        threshold = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number between 0 and 1") from exc
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return threshold


def _nonnegative_number(value: str) -> float:
    try:
        threshold = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative number") from exc
    if not math.isfinite(threshold) or threshold < 0:
        raise argparse.ArgumentTypeError("must be a non-negative number")
    return threshold


def _metric_regression_threshold(value: str) -> tuple[str, float]:
    metric, separator, raw_threshold = value.partition("=")
    if not separator or not metric or not raw_threshold:
        raise argparse.ArgumentTypeError("must use METRIC=DELTA")
    spec = REGRESSION_METRICS.get(metric)
    if spec is None:
        raise argparse.ArgumentTypeError(
            f"unknown recommendation benchmark metric: {metric}"
        )
    threshold_parser = (
        _unit_interval if spec.unit in {"percent", "decimal"}
        else _nonnegative_number
    )
    return metric, threshold_parser(raw_threshold)


def _scoped_metric_regression_threshold(value: str) -> tuple[str, str, float]:
    scope, separator, metric_requirement = value.partition(":")
    if not separator or not scope or not metric_requirement:
        raise argparse.ArgumentTypeError("must use KEY:METRIC=DELTA")
    metric, threshold = _metric_regression_threshold(metric_requirement)
    return scope, metric, threshold


def _case_metric_regression_threshold(value: str) -> tuple[str, float]:
    metric, threshold = _metric_regression_threshold(value)
    if metric not in CASE_REGRESSION_METRICS:
        raise argparse.ArgumentTypeError(
            f"metric is not available for individual cases: {metric}"
        )
    return metric, threshold


def _regression_requirement_map(
    requirements: list[tuple[str, float]],
    *,
    option_name: str = "--maximum-metric-regression",
) -> dict[str, float]:
    result: dict[str, float] = {}
    for metric, threshold in requirements:
        if metric in result:
            raise RecommendationBenchmarkError(
                f"{option_name} repeats metric {metric}"
            )
        result[metric] = threshold
    return result


def _scoped_regression_requirement_map(
    requirements: list[tuple[str, str, float]],
    *,
    option_name: str,
) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for scope, metric, threshold in requirements:
        scope_requirements = result.setdefault(scope, {})
        if metric in scope_requirements:
            raise RecommendationBenchmarkError(
                f"{option_name} repeats metric {metric} for {scope}"
            )
        scope_requirements[metric] = threshold
    return result


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark a Poker Hero recommendation provider against trusted references."
        ),
    )
    parser.add_argument("dataset", type=Path, help="Path to benchmark JSON")
    parser.add_argument(
        "--provider",
        help="Override POKER_RECOMMENDATION_PROVIDER for this run",
    )
    parser.add_argument(
        "--minimum-action-accuracy",
        type=_unit_interval,
        help="Fail below this action agreement ratio",
    )
    parser.add_argument(
        "--minimum-line-accuracy",
        type=_unit_interval,
        help="Fail below this sizing-line agreement ratio",
    )
    parser.add_argument(
        "--minimum-line-coverage",
        type=_unit_interval,
        help="Fail when too few completed cases evaluate exact sizing lines",
    )
    parser.add_argument(
        "--minimum-policy-coverage",
        type=_unit_interval,
        help="Fail when too few completed cases expose comparable frequencies",
    )
    parser.add_argument(
        "--minimum-ev-coverage",
        type=_unit_interval,
        help="Fail when too few completed cases produce comparable reference EV",
    )
    parser.add_argument(
        "--minimum-conditioning-accuracy",
        type=_unit_interval,
        help="Fail below this expected range-conditioning agreement ratio",
    )
    parser.add_argument(
        "--minimum-conditioning-coverage",
        type=_unit_interval,
        help="Fail when too few expected cases report range-conditioning status",
    )
    parser.add_argument(
        "--minimum-range-source-accuracy",
        type=_unit_interval,
        help="Fail below this expected postflop range-source agreement ratio",
    )
    parser.add_argument(
        "--minimum-range-source-coverage",
        type=_unit_interval,
        help="Fail when too few expected cases report a valid postflop range source",
    )
    parser.add_argument(
        "--maximum-policy-distance",
        type=_unit_interval,
        help="Fail above this average policy distance",
    )
    parser.add_argument(
        "--maximum-ev-loss",
        type=_nonnegative_number,
        help="Fail above this average reference EV loss in BB",
    )
    parser.add_argument(
        "--maximum-fallback-rate",
        type=_unit_interval,
        help="Fail above this provider fallback ratio",
    )
    parser.add_argument(
        "--require-reference-source",
        action="store_true",
        help="Fail when the corpus does not identify its independent reference source",
    )
    parser.add_argument(
        "--baseline-report",
        type=Path,
        help="Compare with a prior --json report for the same provider and corpus",
    )
    parser.add_argument(
        "--maximum-metric-regression",
        action="append",
        type=_metric_regression_threshold,
        default=[],
        metavar="METRIC=DELTA",
        help="Repeat to limit a direction-aware aggregate metric regression",
    )
    parser.add_argument(
        "--maximum-street-metric-regression",
        action="append",
        type=_scoped_metric_regression_threshold,
        default=[],
        metavar="STREET:METRIC=DELTA",
        help="Repeat to limit a metric regression for one street breakdown",
    )
    parser.add_argument(
        "--maximum-tag-metric-regression",
        action="append",
        type=_scoped_metric_regression_threshold,
        default=[],
        metavar="TAG:METRIC=DELTA",
        help="Repeat to limit a metric regression for one tag breakdown",
    )
    parser.add_argument(
        "--maximum-case-metric-regression",
        action="append",
        type=_case_metric_regression_threshold,
        default=[],
        metavar="METRIC=DELTA",
        help="Repeat to limit a metric regression in every benchmark case",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write the complete benchmark report as JSON",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    settings: Settings | None = None,
    provider: RecommendationProvider | None = None,
) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        regression_thresholds = _regression_requirement_map(
            args.maximum_metric_regression
        )
        street_regression_thresholds = _scoped_regression_requirement_map(
            args.maximum_street_metric_regression,
            option_name="--maximum-street-metric-regression",
        )
        tag_regression_thresholds = _scoped_regression_requirement_map(
            args.maximum_tag_metric_regression,
            option_name="--maximum-tag-metric-regression",
        )
        case_regression_thresholds = _regression_requirement_map(
            args.maximum_case_metric_regression,
            option_name="--maximum-case-metric-regression",
        )
        if args.baseline_report is None and any(
            (
                regression_thresholds,
                street_regression_thresholds,
                tag_regression_thresholds,
                case_regression_thresholds,
            )
        ):
            raise RecommendationBenchmarkError(
                "Metric regression thresholds require --baseline-report"
            )
    except RecommendationBenchmarkError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        active_settings = settings or get_settings()
    except ValidationError as exc:
        first_error = exc.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first_error["loc"])
        print(
            "Settings configuration is invalid at "
            f"{location}: {first_error['msg']}",
            file=sys.stderr,
        )
        return 2
    if args.provider:
        active_settings = active_settings.model_copy(
            update={"recommendation_provider": args.provider}
        )
    baseline: RecommendationBenchmarkReport | None = None
    try:
        if args.baseline_report is not None:
            baseline = load_recommendation_benchmark_report(
                _dataset_path_from_invocation(args.baseline_report)
            )
            _validate_scoped_regression_requirements(
                baseline,
                street_regression_thresholds,
                tag_regression_thresholds,
            )
        report = benchmark_recommendation_file(
            _dataset_path_from_invocation(args.dataset),
            active_settings,
            provider,
        )
        if baseline is not None:
            validate_comparable_recommendation_baseline(report, baseline)
    except RecommendationBenchmarkError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(
        report.model_dump_json(indent=2)
        if args.json
        else format_recommendation_benchmark_report(report, baseline)
    )
    failures = _threshold_failures(report, args)
    if baseline is not None:
        failures.extend(
            _regression_failures(report, baseline, regression_thresholds)
        )
        failures.extend(
            _breakdown_regression_failures(
                report.street_metrics,
                baseline.street_metrics,
                street_regression_thresholds,
                scope_label="Street",
            )
        )
        failures.extend(
            _breakdown_regression_failures(
                report.tag_metrics,
                baseline.tag_metrics,
                tag_regression_thresholds,
                scope_label="Tag",
            )
        )
        failures.extend(
            _case_regression_failures(
                report,
                baseline,
                case_regression_thresholds,
            )
        )
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


def _threshold_failures(
    report: RecommendationBenchmarkReport,
    args: argparse.Namespace,
) -> list[str]:
    failures = []
    if report.failed_cases:
        failures.append(f"Benchmark has {report.failed_cases} failed case(s)")
    if args.require_reference_source and report.reference_source is None:
        failures.append("Benchmark reference source is not recorded")
    if (
        args.minimum_action_accuracy is not None
        and report.action_accuracy < args.minimum_action_accuracy
    ):
        failures.append(
            f"Action accuracy {report.action_accuracy:.1%} is below the minimum"
            f" {args.minimum_action_accuracy:.1%}"
        )
    failures.extend(
        _optional_threshold_failure(
            "Line accuracy",
            report.line_accuracy,
            args.minimum_line_accuracy,
            comparison="minimum",
            percent=True,
        )
    )
    failures.extend(
        _optional_threshold_failure(
            "Line evaluation coverage",
            report.line_coverage,
            args.minimum_line_coverage,
            comparison="minimum",
            percent=True,
        )
    )
    failures.extend(
        _optional_threshold_failure(
            "Policy evaluation coverage",
            report.policy_coverage,
            args.minimum_policy_coverage,
            comparison="minimum",
            percent=True,
        )
    )
    failures.extend(
        _optional_threshold_failure(
            "EV evaluation coverage",
            report.ev_coverage,
            args.minimum_ev_coverage,
            comparison="minimum",
            percent=True,
        )
    )
    failures.extend(
        _optional_threshold_failure(
            "Range conditioning agreement",
            report.conditioning_accuracy,
            args.minimum_conditioning_accuracy,
            comparison="minimum",
            percent=True,
        )
    )
    failures.extend(
        _optional_threshold_failure(
            "Range conditioning evidence coverage",
            report.conditioning_coverage,
            args.minimum_conditioning_coverage,
            comparison="minimum",
            percent=True,
        )
    )
    failures.extend(
        _optional_threshold_failure(
            "Range source agreement",
            report.range_source_accuracy,
            args.minimum_range_source_accuracy,
            comparison="minimum",
            percent=True,
        )
    )
    failures.extend(
        _optional_threshold_failure(
            "Range source evidence coverage",
            report.range_source_coverage,
            args.minimum_range_source_coverage,
            comparison="minimum",
            percent=True,
        )
    )
    failures.extend(
        _optional_threshold_failure(
            "Average policy distance",
            report.average_policy_distance,
            args.maximum_policy_distance,
            comparison="maximum",
        )
    )
    failures.extend(
        _optional_threshold_failure(
            "Average reference EV loss",
            report.average_reference_ev_loss_bb,
            args.maximum_ev_loss,
            comparison="maximum",
            suffix=" BB",
        )
    )
    if (
        args.maximum_fallback_rate is not None
        and report.fallback_rate > args.maximum_fallback_rate
    ):
        failures.append(
            f"Fallback rate {report.fallback_rate:.1%} is above the maximum"
            f" {args.maximum_fallback_rate:.1%}"
        )
    return failures


def _regression_failures(
    report: RecommendationBenchmarkMetrics,
    baseline: RecommendationBenchmarkMetrics,
    thresholds: dict[str, float],
    *,
    context: str | None = None,
) -> list[str]:
    failures: list[str] = []
    for metric, threshold in thresholds.items():
        spec = REGRESSION_METRICS[metric]
        current = _metric_value(report, spec)
        previous = _metric_value(baseline, spec)
        label = f"{context}: {spec.label}" if context else spec.label
        if current is None or previous is None:
            failures.append(
                f"{label} was not evaluated in both recommendation reports"
            )
            continue
        regression = previous - current if spec.higher_is_better else current - previous
        if regression > threshold + 1e-12:
            failures.append(
                f"{label} regressed {_format_metric_delta(regression, spec)}"
                f" ({_format_metric_value(previous, spec)} to"
                f" {_format_metric_value(current, spec)}), above the maximum"
                f" {_format_metric_delta(threshold, spec)}"
            )
    return failures


def _validate_scoped_regression_requirements(
    report: RecommendationBenchmarkReport,
    street_thresholds: dict[str, dict[str, float]],
    tag_thresholds: dict[str, dict[str, float]],
) -> None:
    for scope_label, breakdowns, thresholds in (
        ("street", report.street_metrics, street_thresholds),
        ("tag", report.tag_metrics, tag_thresholds),
    ):
        missing = sorted(
            set(thresholds).difference(item.key for item in breakdowns)
        )
        if missing:
            raise RecommendationBenchmarkError(
                f"Unknown recommendation benchmark {scope_label} regression scope(s):"
                f" {', '.join(missing)}"
            )


def _breakdown_regression_failures(
    report: list[RecommendationBenchmarkBreakdown],
    baseline: list[RecommendationBenchmarkBreakdown],
    thresholds: dict[str, dict[str, float]],
    *,
    scope_label: str,
) -> list[str]:
    current_by_key = {item.key: item for item in report}
    baseline_by_key = {item.key: item for item in baseline}
    failures: list[str] = []
    for key, scoped_thresholds in thresholds.items():
        failures.extend(
            _regression_failures(
                current_by_key[key],
                baseline_by_key[key],
                scoped_thresholds,
                context=f"{scope_label} {key}",
            )
        )
    return failures


def _case_regression_failures(
    report: RecommendationBenchmarkReport,
    baseline: RecommendationBenchmarkReport,
    thresholds: dict[str, float],
) -> list[str]:
    baseline_by_id = {case.case_id: case for case in baseline.cases}
    failures: list[str] = []
    for case in report.cases:
        previous_case = baseline_by_id[case.case_id]
        for metric, threshold in thresholds.items():
            spec = REGRESSION_METRICS[metric]
            current = _case_metric_value(case, metric)
            previous = _case_metric_value(previous_case, metric)
            if previous is None:
                continue
            label = f"Case {case.case_id}: {spec.label}"
            if current is None:
                failures.append(
                    f"{label} is no longer evaluated"
                    f" (baseline {_format_metric_value(previous, spec)})"
                )
                continue
            regression = (
                previous - current
                if spec.higher_is_better
                else current - previous
            )
            if regression > threshold + 1e-12:
                failures.append(
                    f"{label} regressed"
                    f" {_format_metric_delta(regression, spec)}"
                    f" ({_format_metric_value(previous, spec)} to"
                    f" {_format_metric_value(current, spec)}), above the maximum"
                    f" {_format_metric_delta(threshold, spec)}"
                )
    return failures


def _case_metric_value(
    case: RecommendationBenchmarkCaseResult,
    metric: str,
) -> float | None:
    if metric == "action_accuracy":
        return _boolean_metric_value(case.action_match)
    if metric == "line_accuracy":
        return _boolean_metric_value(case.line_match)
    if metric == "line_coverage":
        return float(case.line_match is not None)
    if metric == "policy_coverage":
        return float(case.policy_distance is not None)
    if metric == "average_policy_distance":
        return case.policy_distance
    if metric == "ev_coverage":
        return float(case.reference_ev_loss_bb is not None)
    if metric in {"average_ev_loss", "maximum_ev_loss"}:
        return case.reference_ev_loss_bb
    if metric == "conditioning_accuracy":
        return _boolean_metric_value(case.range_conditioning_match)
    if metric == "conditioning_coverage":
        return (
            float(case.range_conditioning_status is not None)
            if case.expected_range_conditioning is not None
            else None
        )
    if metric == "range_source_accuracy":
        return _boolean_metric_value(case.range_source_match)
    if metric == "range_source_coverage":
        return (
            float(case.range_source is not None)
            if case.expected_range_source is not None
            else None
        )
    if metric == "fallback_rate":
        return (
            float(case.fallback_reason is not None)
            if case.status == "completed"
            else None
        )
    raise KeyError(metric)


def _boolean_metric_value(value: bool | None) -> float | None:
    return float(value) if value is not None else None


def _metric_change(
    report: RecommendationBenchmarkReport,
    baseline: RecommendationBenchmarkReport,
    metric: str,
) -> str:
    spec = REGRESSION_METRICS[metric]
    current = _metric_value(report, spec)
    previous = _metric_value(baseline, spec)
    if current is None and previous is None:
        return "not evaluated"
    if current is None or previous is None:
        return "not comparable"
    return _format_metric_delta(current - previous, spec, signed=True)


def _metric_value(
    report: RecommendationBenchmarkMetrics,
    spec: RegressionMetricSpec,
) -> float | None:
    return cast(float | None, getattr(report, spec.attribute))


def _format_metric_delta(
    value: float,
    spec: RegressionMetricSpec,
    *,
    signed: bool = False,
) -> str:
    sign = "+" if signed else ""
    if spec.unit == "percent":
        return f"{value * 100:{sign}.1f} pts"
    if spec.unit == "bb":
        return f"{value:{sign}.3f} BB"
    return f"{value:{sign}.3f}"


def _format_metric_value(
    value: float,
    spec: RegressionMetricSpec,
) -> str:
    if spec.unit == "percent":
        return f"{value:.1%}"
    if spec.unit == "bb":
        return f"{value:.3f} BB"
    return f"{value:.3f}"


def _optional_threshold_failure(
    label: str,
    actual: float | None,
    threshold: float | None,
    *,
    comparison: Literal["minimum", "maximum"],
    percent: bool = False,
    suffix: str = "",
) -> list[str]:
    if threshold is None:
        return []
    if actual is None:
        return [f"{label} was not evaluated"]
    failed = actual < threshold if comparison == "minimum" else actual > threshold
    if not failed:
        return []
    if percent:
        actual_text = f"{actual:.1%}"
        threshold_text = f"{threshold:.1%}"
    else:
        actual_text = f"{actual:.3f}{suffix}"
        threshold_text = f"{threshold:.3f}{suffix}"
    direction = "below" if comparison == "minimum" else "above"
    return [
        f"{label} {actual_text} is {direction} the {comparison} {threshold_text}"
    ]


if __name__ == "__main__":
    raise SystemExit(main())
