import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence, TypeVar

from pydantic import ValidationError

from app.benchmarking import run_benchmark
from app.config import Settings, get_settings
from app.dataset_export import MAX_DATASET_EXPANSION_RATIO
from app.domain.benchmarks import BENCHMARK_FIELDS, BenchmarkReport
from app.dataset_import import (
    DatasetImportError,
    import_parser_dataset,
    parse_parser_dataset_archive,
)
from app.parsers.base import ParserConfigurationError
from app.parsers.registry import build_parser
from app.storage.file_job_store import FileJobStore


class DatasetBenchmarkError(RuntimeError):
    pass


RequirementValue = TypeVar("RequirementValue", float, int)


def _dataset_path_from_invocation(dataset_path: Path) -> Path:
    if dataset_path.is_absolute():
        return dataset_path
    invocation_dir = os.environ.get("POKER_BENCHMARK_BASE_DIR")
    return Path(invocation_dir) / dataset_path if invocation_dir else dataset_path


def load_baseline_report(
    report_path: Path,
    *,
    max_report_bytes: int,
) -> BenchmarkReport:
    try:
        report_size = report_path.stat().st_size
    except OSError as exc:
        raise DatasetBenchmarkError(
            f"Could not read baseline report: {report_path}"
        ) from exc
    if report_size > max_report_bytes:
        raise DatasetBenchmarkError("Baseline report is too large")
    try:
        report_bytes = report_path.read_bytes()
        if len(report_bytes) > max_report_bytes:
            raise DatasetBenchmarkError("Baseline report is too large")
        return BenchmarkReport.model_validate_json(report_bytes)
    except OSError as exc:
        raise DatasetBenchmarkError(
            f"Could not read baseline report: {report_path}"
        ) from exc
    except ValidationError as exc:
        raise DatasetBenchmarkError("Baseline report is invalid") from exc


def validate_comparable_baseline(
    report: BenchmarkReport,
    baseline: BenchmarkReport,
) -> None:
    if baseline.parser_provider != report.parser_provider:
        raise DatasetBenchmarkError(
            "Baseline report parser does not match the benchmark parser"
        )
    if baseline.layout_profile != report.layout_profile:
        raise DatasetBenchmarkError(
            "Baseline report layout does not match the benchmark layout"
        )
    if not baseline.corpus_fingerprint:
        raise DatasetBenchmarkError(
            "Baseline report does not include a corpus fingerprint"
        )
    if baseline.corpus_fingerprint != report.corpus_fingerprint:
        raise DatasetBenchmarkError(
            "Baseline report corpus does not match the benchmark dataset"
        )
    current_labels = {
        case.job_id: {
            comparison.field: comparison.expected
            for comparison in case.comparisons
        }
        for case in report.cases
    }
    baseline_labels = {
        case.job_id: {
            comparison.field: comparison.expected
            for comparison in case.comparisons
        }
        for case in baseline.cases
    }
    if baseline_labels != current_labels:
        raise DatasetBenchmarkError(
            "Baseline report cases do not match the benchmark dataset"
        )


def benchmark_dataset_archive(
    dataset_path: Path,
    settings: Settings,
) -> BenchmarkReport:
    try:
        archive_size = dataset_path.stat().st_size
    except OSError as exc:
        raise DatasetBenchmarkError(f"Could not read dataset ZIP: {dataset_path}") from exc
    if archive_size > settings.max_dataset_upload_bytes:
        raise DatasetBenchmarkError(
            "Dataset ZIP exceeds POKER_MAX_DATASET_UPLOAD_BYTES"
        )

    try:
        archive_bytes = dataset_path.read_bytes()
    except OSError as exc:
        raise DatasetBenchmarkError(f"Could not read dataset ZIP: {dataset_path}") from exc

    try:
        dataset = parse_parser_dataset_archive(
            archive_bytes,
            max_image_bytes=settings.max_upload_bytes,
            max_uncompressed_bytes=(
                settings.max_dataset_upload_bytes * MAX_DATASET_EXPANSION_RATIO
            ),
        )
        with TemporaryDirectory(prefix="poker-hero-benchmark-") as temp_dir:
            store = FileJobStore(Path(temp_dir))
            import_parser_dataset(
                dataset,
                store,
                default_layout_profile=settings.parser_layout_profile,
                max_archive_bytes=settings.max_dataset_upload_bytes,
            )
            parser = build_parser(settings)
            return run_benchmark(
                jobs=store.list(),
                parser=parser,
                image_path_for=store.image_path,
                parser_provider=settings.parser_provider,
                layout_profile=settings.parser_layout_profile,
            )
    except DatasetImportError as exc:
        raise DatasetBenchmarkError(f"Dataset ZIP is invalid: {exc}") from exc
    except ParserConfigurationError as exc:
        raise DatasetBenchmarkError(f"Parser configuration error: {exc}") from exc


def format_benchmark_report(
    report: BenchmarkReport,
    baseline: BenchmarkReport | None = None,
) -> str:
    lines = [
        "Parser dataset benchmark",
        f"Parser: {report.parser_provider}",
        f"Layout: {report.layout_profile}",
        (
            f"Cases: {report.successful_cases}/{report.total_cases} completed"
            f" ({report.failed_cases} failed)"
        ),
        (
            f"Accuracy: {report.correct_fields}/{report.evaluated_fields}"
            f" ({report.accuracy:.1%})"
        ),
        "Fields:",
    ]
    lines.extend(
        f"  {metric.field}: {metric.correct}/{metric.total} ({metric.accuracy:.1%})"
        for metric in report.field_metrics
    )

    if baseline is not None:
        lines.extend(
            [
                "Baseline comparison:",
                f"  Report: {baseline.id}",
                (
                    "  Accuracy:"
                    f" {_percentage_point_change(report.accuracy, baseline.accuracy)}"
                ),
                "  Fields:",
            ]
        )
        baseline_metrics = {
            metric.field: metric for metric in baseline.field_metrics
        }
        lines.extend(
            (
                f"    {metric.field}:"
                f" {_percentage_point_change(metric.accuracy, baseline_metrics[metric.field].accuracy)}"
            )
            for metric in report.field_metrics
            if metric.field in baseline_metrics
        )

    cases_needing_review = [
        case
        for case in report.cases
        if case.status == "error" or any(not item.matched for item in case.comparisons)
    ]
    if cases_needing_review:
        lines.append("Cases needing review:")
        for case in cases_needing_review:
            if case.error:
                detail = case.error
            else:
                detail = ", ".join(
                    comparison.field
                    for comparison in case.comparisons
                    if not comparison.matched
                )
            lines.append(f"  {case.original_filename}: {detail}")
    return "\n".join(lines)


def _percentage_point_change(current: float, baseline: float) -> str:
    return f"{(current - baseline) * 100:+.1f} pts"


def _accuracy_threshold(value: str) -> float:
    try:
        threshold = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number between 0 and 1") from exc
    if not 0 <= threshold <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return threshold


def _positive_integer(value: str) -> int:
    try:
        threshold = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if threshold <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return threshold


def _field_accuracy_threshold(value: str) -> tuple[str, float]:
    field, separator, raw_threshold = value.partition("=")
    if not separator or not field or not raw_threshold:
        raise argparse.ArgumentTypeError("must use FIELD=ACCURACY")
    if field not in BENCHMARK_FIELDS:
        raise argparse.ArgumentTypeError(f"unknown benchmark field: {field}")
    return field, _accuracy_threshold(raw_threshold)


def _field_accuracy_drop_threshold(value: str) -> tuple[str, float]:
    field, separator, raw_threshold = value.partition("=")
    if not separator or not field or not raw_threshold:
        raise argparse.ArgumentTypeError("must use FIELD=DROP")
    if field not in BENCHMARK_FIELDS:
        raise argparse.ArgumentTypeError(f"unknown benchmark field: {field}")
    return field, _accuracy_threshold(raw_threshold)


def _field_case_threshold(value: str) -> tuple[str, int]:
    field, separator, raw_threshold = value.partition("=")
    if not separator or not field or not raw_threshold:
        raise argparse.ArgumentTypeError("must use FIELD=COUNT")
    if field not in BENCHMARK_FIELDS:
        raise argparse.ArgumentTypeError(f"unknown benchmark field: {field}")
    return field, _positive_integer(raw_threshold)


def _requirement_map(
    requirements: list[tuple[str, RequirementValue]],
    option: str,
) -> dict[str, RequirementValue]:
    result: dict[str, RequirementValue] = {}
    for field, threshold in requirements:
        if field in result:
            raise DatasetBenchmarkError(f"{option} repeats field {field}")
        result[field] = threshold
    return result


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark a Poker Hero parser against an exported dataset ZIP.",
    )
    parser.add_argument("dataset", type=Path, help="Path to an exported dataset ZIP")
    parser.add_argument(
        "--parser-provider",
        help="Override POKER_PARSER_PROVIDER for this run",
    )
    parser.add_argument(
        "--layout-profile",
        help="Override POKER_PARSER_LAYOUT_PROFILE for this run",
    )
    parser.add_argument(
        "--minimum-accuracy",
        type=_accuracy_threshold,
        help="Exit with status 1 when field accuracy is below this 0-1 threshold",
    )
    parser.add_argument(
        "--minimum-cases",
        type=_positive_integer,
        help="Fail when the corpus contains fewer cases",
    )
    parser.add_argument(
        "--minimum-field-accuracy",
        action="append",
        type=_field_accuracy_threshold,
        default=[],
        metavar="FIELD=ACCURACY",
        help="Repeat to require an accuracy ratio for a specific labeled field",
    )
    parser.add_argument(
        "--minimum-field-cases",
        action="append",
        type=_field_case_threshold,
        default=[],
        metavar="FIELD=COUNT",
        help="Repeat to require enough labeled cases for a specific field",
    )
    parser.add_argument(
        "--baseline-report",
        type=Path,
        help="Compare with a prior --json report for the same parser, layout, and corpus",
    )
    parser.add_argument(
        "--maximum-accuracy-drop",
        type=_accuracy_threshold,
        help="Fail when overall accuracy drops by more than this 0-1 ratio",
    )
    parser.add_argument(
        "--maximum-field-accuracy-drop",
        action="append",
        type=_field_accuracy_drop_threshold,
        default=[],
        metavar="FIELD=DROP",
        help="Repeat to limit the accuracy drop for a specific labeled field",
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
) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        field_accuracy_thresholds = _requirement_map(
            args.minimum_field_accuracy,
            "--minimum-field-accuracy",
        )
        field_case_thresholds = _requirement_map(
            args.minimum_field_cases,
            "--minimum-field-cases",
        )
        field_accuracy_drop_thresholds = _requirement_map(
            args.maximum_field_accuracy_drop,
            "--maximum-field-accuracy-drop",
        )
        if args.baseline_report is None and (
            args.maximum_accuracy_drop is not None
            or field_accuracy_drop_thresholds
        ):
            raise DatasetBenchmarkError(
                "Regression thresholds require --baseline-report"
            )
    except DatasetBenchmarkError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    active_settings = settings or get_settings()
    overrides: dict[str, str] = {}
    if args.parser_provider:
        overrides["parser_provider"] = args.parser_provider
    if args.layout_profile:
        overrides["parser_layout_profile"] = args.layout_profile
    if overrides:
        active_settings = active_settings.model_copy(update=overrides)

    baseline: BenchmarkReport | None = None
    try:
        if args.baseline_report is not None:
            baseline = load_baseline_report(
                _dataset_path_from_invocation(args.baseline_report),
                max_report_bytes=active_settings.max_dataset_upload_bytes,
            )
        report = benchmark_dataset_archive(
            _dataset_path_from_invocation(args.dataset),
            active_settings,
        )
        if baseline is not None:
            validate_comparable_baseline(report, baseline)
    except DatasetBenchmarkError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(format_benchmark_report(report, baseline))

    failures = _threshold_failures(
        report,
        minimum_accuracy=args.minimum_accuracy,
        minimum_cases=args.minimum_cases,
        field_accuracy_thresholds=field_accuracy_thresholds,
        field_case_thresholds=field_case_thresholds,
    )
    if baseline is not None:
        failures.extend(
            _regression_failures(
                report,
                baseline,
                maximum_accuracy_drop=args.maximum_accuracy_drop,
                field_accuracy_drop_thresholds=field_accuracy_drop_thresholds,
            )
        )
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


def _threshold_failures(
    report: BenchmarkReport,
    *,
    minimum_accuracy: float | None,
    minimum_cases: int | None,
    field_accuracy_thresholds: dict[str, float],
    field_case_thresholds: dict[str, int],
) -> list[str]:
    failures: list[str] = []
    if report.failed_cases:
        failures.append(f"Benchmark has {report.failed_cases} failed case(s)")
    if minimum_cases is not None and report.total_cases < minimum_cases:
        failures.append(
            f"Benchmark corpus has {report.total_cases} case(s), below the minimum"
            f" {minimum_cases}"
        )
    if minimum_accuracy is not None and report.accuracy < minimum_accuracy:
        failures.append(
            f"Benchmark accuracy {report.accuracy:.1%} is below the minimum"
            f" {minimum_accuracy:.1%}"
        )

    metrics = {metric.field: metric for metric in report.field_metrics}
    for field, threshold in field_case_thresholds.items():
        total = metrics[field].total if field in metrics else 0
        if total < threshold:
            failures.append(
                f"Field {field} has {total} labeled case(s), below the minimum"
                f" {threshold}"
            )
    for field, threshold in field_accuracy_thresholds.items():
        metric = metrics.get(field)
        if metric is None:
            failures.append(f"Field {field} accuracy was not evaluated")
        elif metric.accuracy < threshold:
            failures.append(
                f"Field {field} accuracy {metric.accuracy:.1%} is below the minimum"
                f" {threshold:.1%}"
            )
    return failures


def _regression_failures(
    report: BenchmarkReport,
    baseline: BenchmarkReport,
    *,
    maximum_accuracy_drop: float | None,
    field_accuracy_drop_thresholds: dict[str, float],
) -> list[str]:
    failures: list[str] = []
    if maximum_accuracy_drop is not None:
        accuracy_drop = baseline.accuracy - report.accuracy
        if accuracy_drop > maximum_accuracy_drop + 1e-12:
            failures.append(
                f"Benchmark accuracy dropped {accuracy_drop * 100:.1f} pts"
                f" ({baseline.accuracy:.1%} to {report.accuracy:.1%}), above"
                f" the maximum {maximum_accuracy_drop * 100:.1f} pts"
            )

    metrics = {metric.field: metric for metric in report.field_metrics}
    baseline_metrics = {
        metric.field: metric for metric in baseline.field_metrics
    }
    for field, threshold in field_accuracy_drop_thresholds.items():
        metric = metrics.get(field)
        baseline_metric = baseline_metrics.get(field)
        if metric is None or baseline_metric is None:
            failures.append(
                f"Field {field} accuracy was not evaluated in both reports"
            )
            continue
        accuracy_drop = baseline_metric.accuracy - metric.accuracy
        if accuracy_drop > threshold + 1e-12:
            failures.append(
                f"Field {field} accuracy dropped {accuracy_drop * 100:.1f} pts"
                f" ({baseline_metric.accuracy:.1%} to {metric.accuracy:.1%}),"
                f" above the maximum {threshold * 100:.1f} pts"
            )
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
