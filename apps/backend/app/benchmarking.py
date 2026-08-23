from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.benchmark_corpus import benchmark_corpus_fingerprint
from app.domain.poker import CanonicalState, DetectedState
from app.domain.hands import JobRecord
from app.models import (
    BENCHMARK_FIELDS,
    BenchmarkCaseResult,
    BenchmarkFieldComparison,
    BenchmarkFieldMetric,
    BenchmarkParserRouting,
    BenchmarkReport,
    benchmark_values_match,
    normalize_benchmark_value,
)
from app.parsers.base import ParserConfigurationError, ScreenshotParser


def run_benchmark(
    jobs: list[JobRecord],
    parser: ScreenshotParser,
    image_path_for: Callable[[JobRecord], Path],
    parser_provider: str,
    layout_profile: str,
) -> BenchmarkReport:
    cases = [
        _run_case(job, parser, image_path_for)
        for job in jobs
        if job.benchmark_included and job.approved_state is not None
    ]
    field_totals = {field: [0, 0] for field in BENCHMARK_FIELDS}
    for case in cases:
        for comparison in case.comparisons:
            field_totals[comparison.field][1] += 1
            if comparison.matched:
                field_totals[comparison.field][0] += 1

    field_metrics = [
        BenchmarkFieldMetric(
            field=field,
            correct=counts[0],
            total=counts[1],
            accuracy=counts[0] / counts[1],
        )
        for field, counts in field_totals.items()
        if counts[1] > 0
    ]
    correct_fields = sum(case.correct_fields for case in cases)
    evaluated_fields = sum(case.evaluated_fields for case in cases)
    failed_cases = sum(case.status == "error" for case in cases)
    return BenchmarkReport(
        parser_provider=parser_provider,
        layout_profile=layout_profile,
        corpus_fingerprint=benchmark_corpus_fingerprint(jobs, image_path_for),
        total_cases=len(cases),
        successful_cases=len(cases) - failed_cases,
        failed_cases=failed_cases,
        correct_fields=correct_fields,
        evaluated_fields=evaluated_fields,
        accuracy=correct_fields / evaluated_fields if evaluated_fields else 0,
        field_metrics=field_metrics,
        cases=cases,
    )


def _run_case(
    job: JobRecord,
    parser: ScreenshotParser,
    image_path_for: Callable[[JobRecord], Path],
) -> BenchmarkCaseResult:
    expected = job.approved_state
    if expected is None:
        raise ValueError("Benchmark case requires an approved state")

    try:
        image_path = image_path_for(job)
        result = parser.parse(image_path)
        parser_routing = (
            BenchmarkParserRouting.model_validate(result.raw["parser_routing"])
            if parser.name == "auto"
            else None
        )
    except ParserConfigurationError:
        raise
    except Exception as exc:
        comparisons = _compare_states(expected, None, {})
        return BenchmarkCaseResult(
            job_id=job.id,
            original_filename=job.original_filename,
            status="error",
            correct_fields=0,
            evaluated_fields=len(comparisons),
            accuracy=0,
            error=str(exc),
            comparisons=comparisons,
        )

    comparisons = _compare_states(expected, result.state, result.confidences)
    correct = sum(comparison.matched for comparison in comparisons)
    return BenchmarkCaseResult(
        job_id=job.id,
        original_filename=job.original_filename,
        status="completed",
        correct_fields=correct,
        evaluated_fields=len(comparisons),
        accuracy=correct / len(comparisons) if comparisons else 0,
        warnings=result.warnings,
        parser_routing=parser_routing,
        comparisons=comparisons,
    )


def _compare_states(
    expected: CanonicalState,
    detected: DetectedState | None,
    confidences: dict[str, float],
) -> list[BenchmarkFieldComparison]:
    comparisons: list[BenchmarkFieldComparison] = []
    for field in BENCHMARK_FIELDS:
        expected_value = getattr(expected, field)
        if not _is_labeled(field, expected_value, expected.street):
            continue
        detected_value = getattr(detected, field) if detected is not None else None
        normalized_expected = normalize_benchmark_value(field, expected_value)
        normalized_detected = normalize_benchmark_value(field, detected_value)
        comparisons.append(
            BenchmarkFieldComparison(
                field=field,
                expected=normalized_expected,
                detected=normalized_detected,
                matched=benchmark_values_match(
                    normalized_expected,
                    normalized_detected,
                ),
                confidence=confidences.get(field),
            )
        )
    return comparisons


def _is_labeled(field: str, value: Any, street: str | None) -> bool:
    if value is None:
        return False
    if field == "hero_cards":
        return bool(value)
    if field == "board_cards":
        return bool(value) or street == "preflop"
    if field in {
        "preflop_action_history",
        "postflop_action_history",
        "completed_postflop_streets",
    }:
        return bool(value)
    if field == "action_context":
        return bool(str(value).strip())
    return True
