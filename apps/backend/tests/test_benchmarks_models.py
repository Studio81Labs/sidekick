import pytest
from pydantic import ValidationError

from app.domain.benchmarks import (
    BENCHMARK_FIELDS,
    BENCHMARK_IMPORT_REQUEST_ID_PATTERN,
    BENCHMARK_POSITION_ALIASES,
    BenchmarkCaseResult,
    BenchmarkDatasetImportReceipt,
    BenchmarkDatasetImportResult,
    BenchmarkSelectionRequest,
    BenchmarkReport,
    benchmark_values_match,
    normalize_benchmark_value,
)
from app.models import (
    BENCHMARK_FIELDS as CompatibilityBenchmarkFields,
    BENCHMARK_IMPORT_REQUEST_ID_PATTERN as CompatibilityBenchmarkRequestIdPattern,
    BENCHMARK_POSITION_ALIASES as CompatibilityBenchmarkPositionAliases,
    BenchmarkCaseResult as CompatibilityBenchmarkCaseResult,
    BenchmarkDatasetImportReceipt as CompatibilityBenchmarkDatasetImportReceipt,
    BenchmarkDatasetImportResult as CompatibilityBenchmarkDatasetImportResult,
    BenchmarkReport as CompatibilityBenchmarkReport,
    BenchmarkSelectionRequest as CompatibilityBenchmarkSelectionRequest,
)
from app.storage import FileBenchmarkStore


def test_benchmarks_contracts_reexported_from_app_models() -> None:
    assert CompatibilityBenchmarkFields is BENCHMARK_FIELDS
    assert CompatibilityBenchmarkRequestIdPattern == BENCHMARK_IMPORT_REQUEST_ID_PATTERN
    assert CompatibilityBenchmarkPositionAliases == BENCHMARK_POSITION_ALIASES
    assert CompatibilityBenchmarkCaseResult is BenchmarkCaseResult
    assert CompatibilityBenchmarkDatasetImportReceipt is BenchmarkDatasetImportReceipt
    assert CompatibilityBenchmarkDatasetImportResult is BenchmarkDatasetImportResult
    assert CompatibilityBenchmarkReport is BenchmarkReport
    assert CompatibilityBenchmarkSelectionRequest is BenchmarkSelectionRequest


def test_benchmark_dataset_import_receipt_validation() -> None:
    with pytest.raises(ValidationError):
        BenchmarkDatasetImportReceipt(
            request_id="request-1",
            archive_sha256="a" * 64,
            status="pending",
            result={"imported_cases": 1, "reused_cases": 0, "included_cases": 0},
        )

    with pytest.raises(ValidationError):
        BenchmarkDatasetImportReceipt(
            request_id="request-1",
            archive_sha256="a" * 64,
            status="completed",
        )

    with pytest.raises(ValidationError):
        BenchmarkDatasetImportReceipt(
            request_id="request-1",
            archive_sha256="a" * 64,
            status="failed",
            error="invalid dataset",
        )

    BenchmarkDatasetImportReceipt(
        request_id="request-1",
        archive_sha256="a" * 64,
        status="pending",
    )
    BenchmarkDatasetImportReceipt(
        request_id="request-1",
        archive_sha256="a" * 64,
        status="completed",
        result={"imported_cases": 1, "reused_cases": 0, "included_cases": 1},
    )
    BenchmarkDatasetImportReceipt(
        request_id="request-1",
        archive_sha256="a" * 64,
        status="failed",
        error="invalid dataset",
        error_status=422,
    )


def test_benchmark_normalization_and_values_match() -> None:
    assert normalize_benchmark_value("hero_position", " BTN ") == "button"
    assert normalize_benchmark_value("preflop_action_history", []) == []

    assert not benchmark_values_match(1.0, 1.1)
    assert benchmark_values_match(1, 1.0)


def test_benchmark_case_and_report_round_trip_and_persistence(tmp_path) -> None:
    error_case = BenchmarkCaseResult(
        job_id="a" * 32,
        original_filename="sample.png",
        status="error",
        correct_fields=0,
        evaluated_fields=0,
        accuracy=0,
        error="parser failed",
    )
    report = BenchmarkReport(
        parser_provider="mock",
        layout_profile="generic",
        total_cases=1,
        successful_cases=0,
        failed_cases=1,
        correct_fields=0,
        evaluated_fields=0,
        accuracy=0,
        cases=[error_case],
    )

    report_payload = report.model_dump_json()
    reloaded_report = BenchmarkReport.model_validate_json(report_payload)
    assert reloaded_report == report

    report_store = FileBenchmarkStore(tmp_path)
    report_store.save(report)
    persisted_report = report_store.get(report.id)
    persisted_summary = report_store.list(limit=1)[0]
    latest_report = report_store.get_latest()

    assert persisted_report == report
    assert persisted_summary == report
    assert latest_report == report
