import base64
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.benchmark_corpus import benchmark_corpus_fingerprint
from app.benchmarking import run_benchmark
from app.config import Settings
from app.dataset_benchmark import (
    DatasetBenchmarkError,
    benchmark_dataset_archive,
    format_benchmark_report,
    load_baseline_report,
    main,
)
from app.dataset_export import (
    ParserDatasetArchiveCase,
    build_parser_dataset_archive_from_cases,
)
from app.domain.benchmarks import BenchmarkReport
from app.domain.hands import JobRecord
from app.domain.poker import (
    CanonicalState,
    Card,
    CompletedPostflopAction,
    CompletedPostflopStreetHistory,
    PostflopAction,
    PreflopAction,
)
from app.parsers.mock import MockParser


VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
)


def expected_mock_state(**overrides: object) -> CanonicalState:
    values = {
        "hero_cards": [Card.from_code("Ah"), Card.from_code("Kd")],
        "board_cards": [
            Card.from_code("Qs"),
            Card.from_code("Jc"),
            Card.from_code("2h"),
        ],
        "pot_size": 12.5,
        "current_bet": 2.5,
        "hero_stack": 97.5,
        "effective_stack": 96.0,
        "players_in_hand": 3,
        "hero_position": "button",
        "street": "flop",
        "facing_action": "bet",
        "action_context": "Cutoff bet 2.5 into 12.5",
        "user_approved": True,
    }
    values.update(overrides)
    return CanonicalState.model_validate(values)


def test_benchmark_corpus_fingerprint_tracks_stable_labels_and_images(
    tmp_path: Path,
) -> None:
    first = JobRecord(
        id="1" * 32,
        original_filename="first.png",
        image_filename="original.png",
        parser_provider="mock",
        recommendation_provider="mock",
        approved_state=expected_mock_state(),
        benchmark_included=True,
    )
    second = first.model_copy(deep=True, update={
        "id": "2" * 32,
        "original_filename": "second.png",
    })
    first_image = tmp_path / "first.png"
    second_image = tmp_path / "second.png"
    changed_first_image = tmp_path / "changed-first.png"
    first_image.write_bytes(b"first image")
    second_image.write_bytes(b"second image")
    changed_first_image.write_bytes(b"changed first image")
    image_paths = {
        first.id: first_image,
        second.id: second_image,
    }
    baseline = benchmark_corpus_fingerprint(
        [first, second],
        lambda job: image_paths[job.id],
    )

    metadata_change = first.model_copy(deep=True, update={
        "notes": "Reviewed during QA",
        "tags": ["trusted"],
        "title": "Flop benchmark",
    })
    state_change = first.model_copy(deep=True, update={
        "approved_state": expected_mock_state(pot_size=13.0),
    })
    excluded = second.model_copy(deep=True, update={
        "id": "3" * 32,
        "benchmark_included": False,
    })

    assert (
        benchmark_corpus_fingerprint(
            [second, first],
            lambda job: image_paths[job.id],
        )
        == baseline
    )
    assert (
        benchmark_corpus_fingerprint(
            [metadata_change, second],
            lambda job: image_paths[job.id],
        )
        == baseline
    )
    assert (
        benchmark_corpus_fingerprint(
            [first, second, excluded],
            lambda job: image_paths[job.id],
        )
        == baseline
    )
    assert (
        benchmark_corpus_fingerprint(
            [state_change, second],
            lambda job: image_paths[job.id],
        )
        != baseline
    )
    changed_image_paths = {
        **image_paths,
        first.id: changed_first_image,
    }
    assert (
        benchmark_corpus_fingerprint(
            [first, second],
            lambda job: changed_image_paths[job.id],
        )
        != baseline
    )


def test_benchmark_preserves_automatic_parser_routing(tmp_path: Path) -> None:
    class RoutedParser:
        name = "auto"

        def parse(self, image_path: Path):
            result = MockParser().parse(image_path)
            return result.model_copy(
                update={
                    "raw": {
                        **result.raw,
                        "parser_routing": {
                            "provider": "auto",
                            "selected_provider": "llm_vision",
                            "layout_profile": "fortuna_nations",
                            "fallback_from": "ocr_cv",
                            "fallback_reason": "capture geometry did not match",
                        },
                    }
                }
            )

    job = JobRecord(
        original_filename="table.png",
        image_filename="original.png",
        parser_provider="auto",
        parser_layout_profile="fortuna_nations",
        recommendation_provider="mock",
        approved_state=expected_mock_state(),
        benchmark_included=True,
    )

    image_path = tmp_path / "table.png"
    image_path.write_bytes(VALID_PNG)
    report = run_benchmark(
        [job],
        RoutedParser(),
        lambda _job: image_path,
        parser_provider="auto",
        layout_profile="fortuna_nations",
    )
    restored = BenchmarkReport.model_validate_json(report.model_dump_json())

    assert restored.cases[0].parser_routing is not None
    assert restored.cases[0].parser_routing.model_dump() == {
        "provider": "auto",
        "selected_provider": "llm_vision",
        "layout_profile": "fortuna_nations",
        "fallback_from": "ocr_cv",
        "fallback_reason": "capture geometry did not match",
    }

    incompatible = report.model_dump(mode="json")
    incompatible["cases"][0]["parser_routing"]["layout_profile"] = "pokerstars"
    with pytest.raises(ValueError, match="routing layout does not match"):
        BenchmarkReport.model_validate(incompatible)


def write_dataset_archive(
    path: Path,
    expected_state: CanonicalState,
) -> Path:
    archive = build_parser_dataset_archive_from_cases(
        [
            ParserDatasetArchiveCase(
                job_id="a" * 32,
                original_filename="table.png",
                image_suffix=".png",
                image_source=VALID_PNG,
                expected_state=expected_state,
            )
        ],
        parser_provider="ocr_cv",
        layout_profile="fortuna_nations",
        max_archive_bytes=1024 * 1024,
    )
    try:
        path.write_bytes(archive.read())
    finally:
        archive.close()
    return path


def report_with_matching_field(
    report: BenchmarkReport,
    field: str,
) -> BenchmarkReport:
    payload = report.model_dump(mode="json")
    field_found = False
    for case in payload["cases"]:
        for comparison in case["comparisons"]:
            if comparison["field"] != field:
                continue
            comparison["detected"] = comparison["expected"]
            comparison["matched"] = True
            field_found = True
        case["correct_fields"] = sum(
            comparison["matched"] for comparison in case["comparisons"]
        )
        case["accuracy"] = (
            case["correct_fields"] / case["evaluated_fields"]
            if case["evaluated_fields"]
            else 0
        )
    assert field_found
    payload["correct_fields"] = sum(
        case["correct_fields"] for case in payload["cases"]
    )
    payload["accuracy"] = (
        payload["correct_fields"] / payload["evaluated_fields"]
        if payload["evaluated_fields"]
        else 0
    )
    for metric in payload["field_metrics"]:
        comparisons = [
            comparison
            for case in payload["cases"]
            for comparison in case["comparisons"]
            if comparison["field"] == metric["field"]
        ]
        metric["correct"] = sum(
            comparison["matched"] for comparison in comparisons
        )
        metric["accuracy"] = metric["correct"] / metric["total"]
    return BenchmarkReport.model_validate(payload)


def write_baseline_report(path: Path, report: BenchmarkReport) -> Path:
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def test_dataset_archive_preserves_structured_postflop_history() -> None:
    expected_state = expected_mock_state(
        pot_size=19,
        current_bet=5,
        hero_stack=8,
        opponent_stack=3,
        effective_stack=3,
        players_in_hand=2,
        hero_position="OOP",
        facing_action="raise",
        postflop_action_history=[
            PostflopAction(actor="oop", action="bet", amount=2),
            PostflopAction(actor="ip", action="raise", amount=7),
        ],
    )

    archive = build_parser_dataset_archive_from_cases(
        [
            ParserDatasetArchiveCase(
                job_id="a" * 32,
                original_filename="raised.png",
                image_suffix=".png",
                image_source=VALID_PNG,
                expected_state=expected_state,
            )
        ],
        parser_provider="ocr_cv",
        layout_profile="fortuna_nations",
        max_archive_bytes=1024 * 1024,
    )
    try:
        with ZipFile(BytesIO(archive.read())) as dataset:
            manifest = json.loads(dataset.read("manifest.json"))
    finally:
        archive.close()

    exported = manifest["cases"][0]["expected_state"]
    assert exported["opponent_stack"] == 3
    assert exported["postflop_action_history"] == [
        {"actor": "oop", "action": "bet", "amount": 2},
        {"actor": "ip", "action": "raise", "amount": 7},
    ]


def test_dataset_archive_preserves_completed_postflop_streets() -> None:
    expected_state = expected_mock_state(
        board_cards=[
            Card.from_code("Qs"),
            Card.from_code("Jc"),
            Card.from_code("2h"),
            Card.from_code("3d"),
        ],
        street="turn",
        completed_postflop_streets=[
            CompletedPostflopStreetHistory(
                street="flop",
                actions=[
                    CompletedPostflopAction(
                        actor="oop",
                        action="bet",
                        amount=2,
                    ),
                    CompletedPostflopAction(
                        actor="ip",
                        action="call",
                        amount=2,
                    ),
                ],
            )
        ],
    )

    archive = build_parser_dataset_archive_from_cases(
        [
            ParserDatasetArchiveCase(
                job_id="a" * 32,
                original_filename="turn.png",
                image_suffix=".png",
                image_source=VALID_PNG,
                expected_state=expected_state,
            )
        ],
        parser_provider="ocr_cv",
        layout_profile="fortuna_nations",
        max_archive_bytes=1024 * 1024,
    )
    try:
        with ZipFile(BytesIO(archive.read())) as dataset:
            manifest = json.loads(dataset.read("manifest.json"))
    finally:
        archive.close()

    assert manifest["cases"][0]["expected_state"][
        "completed_postflop_streets"
    ] == [
        {
            "street": "flop",
            "actions": [
                {"actor": "oop", "action": "bet", "amount": 2},
                {"actor": "ip", "action": "call", "amount": 2},
            ],
        }
    ]


def test_dataset_archive_preserves_structured_preflop_history() -> None:
    expected_state = expected_mock_state(
        board_cards=[],
        pot_size=12,
        current_bet=5.5,
        hero_stack=97.5,
        effective_stack=92,
        players_in_hand=6,
        hero_position="cutoff",
        preflop_opener_position="cutoff",
        preflop_open_size=2.5,
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
        ],
        street="preflop",
        facing_action="raise",
    )

    archive = build_parser_dataset_archive_from_cases(
        [
            ParserDatasetArchiveCase(
                job_id="a" * 32,
                original_filename="three-bet.png",
                image_suffix=".png",
                image_source=VALID_PNG,
                expected_state=expected_state,
            )
        ],
        parser_provider="ocr_cv",
        layout_profile="fortuna_nations",
        max_archive_bytes=1024 * 1024,
    )
    try:
        with ZipFile(BytesIO(archive.read())) as dataset:
            manifest = json.loads(dataset.read("manifest.json"))
    finally:
        archive.close()

    assert manifest["cases"][0]["expected_state"]["preflop_action_history"] == [
        {"actor": "cutoff", "action": "raise", "amount": 2.5},
        {"actor": "button", "action": "raise", "amount": 8.0},
    ]


def test_benchmark_scores_structured_postflop_fields(tmp_path: Path) -> None:
    expected_state = expected_mock_state(
        opponent_stack=93,
        postflop_action_history=[
            PostflopAction(actor="oop", action="bet", amount=2),
            PostflopAction(actor="ip", action="raise", amount=7),
        ],
    )
    dataset_path = write_dataset_archive(tmp_path / "raised-dataset.zip", expected_state)

    report = benchmark_dataset_archive(
        dataset_path,
        Settings(data_dir=tmp_path / "unused", parser_provider="mock"),
    )

    metrics = {metric.field: metric for metric in report.field_metrics}
    assert report.evaluated_fields == 13
    assert report.correct_fields == 11
    assert metrics["opponent_stack"].total == 1
    assert metrics["opponent_stack"].correct == 0
    assert metrics["postflop_action_history"].total == 1
    assert metrics["postflop_action_history"].correct == 0


def test_benchmark_scores_completed_postflop_streets(tmp_path: Path) -> None:
    expected_state = expected_mock_state(
        board_cards=[
            Card.from_code("Qs"),
            Card.from_code("Jc"),
            Card.from_code("2h"),
            Card.from_code("3d"),
        ],
        street="turn",
        completed_postflop_streets=[
            CompletedPostflopStreetHistory(
                street="flop",
                actions=[
                    CompletedPostflopAction(
                        actor="oop",
                        action="bet",
                        amount=2,
                    ),
                    CompletedPostflopAction(
                        actor="ip",
                        action="call",
                        amount=2,
                    ),
                ],
            )
        ],
    )
    dataset_path = write_dataset_archive(
        tmp_path / "completed-streets-dataset.zip",
        expected_state,
    )

    report = benchmark_dataset_archive(
        dataset_path,
        Settings(data_dir=tmp_path / "unused", parser_provider="mock"),
    )

    metrics = {metric.field: metric for metric in report.field_metrics}
    assert metrics["completed_postflop_streets"].total == 1
    assert metrics["completed_postflop_streets"].correct == 0


def test_benchmark_scores_structured_preflop_history(tmp_path: Path) -> None:
    expected_state = expected_mock_state(
        preflop_action_history=[
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
        ]
    )
    dataset_path = write_dataset_archive(
        tmp_path / "preflop-history-dataset.zip",
        expected_state,
    )

    report = benchmark_dataset_archive(
        dataset_path,
        Settings(data_dir=tmp_path / "unused", parser_provider="mock"),
    )

    metrics = {metric.field: metric for metric in report.field_metrics}
    assert metrics["preflop_action_history"].total == 1
    assert metrics["preflop_action_history"].correct == 0


def test_benchmark_dataset_archive_scores_without_mutating_configured_data(
    tmp_path: Path,
) -> None:
    dataset_path = write_dataset_archive(
        tmp_path / "dataset.zip",
        expected_mock_state(),
    )
    data_dir = tmp_path / "production-data"
    settings = Settings(
        data_dir=data_dir,
        parser_provider="mock",
        parser_layout_profile="generic",
    )

    report = benchmark_dataset_archive(dataset_path, settings)

    assert report.parser_provider == "mock"
    assert report.layout_profile == "generic"
    assert report.total_cases == 1
    assert report.failed_cases == 0
    assert report.accuracy == 1
    assert not data_dir.exists()
    assert dataset_path.exists()
    assert "Accuracy: 11/11 (100.0%)" in format_benchmark_report(report)


def test_benchmark_cli_emits_json_and_fails_below_threshold(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = write_dataset_archive(
        tmp_path / "dataset.zip",
        expected_mock_state(pot_size=99),
    )
    settings = Settings(data_dir=tmp_path / "unused", parser_provider="ocr_cv")

    exit_code = main(
        [
            str(dataset_path),
            "--parser-provider",
            "mock",
            "--layout-profile",
            "generic",
            "--minimum-accuracy",
            "1",
            "--json",
        ],
        settings=settings,
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert exit_code == 1
    assert report["parser_provider"] == "mock"
    assert report["accuracy"] == pytest.approx(10 / 11)
    assert "below the minimum 100.0%" in captured.err


def test_benchmark_cli_resolves_relative_dataset_from_invocation_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invocation_dir = tmp_path / "repository-root"
    invocation_dir.mkdir()
    write_dataset_archive(
        invocation_dir / "dataset.zip",
        expected_mock_state(),
    )
    monkeypatch.setenv("POKER_BENCHMARK_BASE_DIR", str(invocation_dir))

    exit_code = main(
        [
            "dataset.zip",
            "--parser-provider",
            "mock",
            "--minimum-cases",
            "1",
            "--minimum-field-cases",
            "hero_cards=1",
            "--minimum-field-accuracy",
            "hero_cards=1",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Accuracy: 11/11 (100.0%)" in captured.out
    assert captured.err == ""


def test_benchmark_cli_enforces_corpus_and_per_field_thresholds(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = write_dataset_archive(
        tmp_path / "dataset.zip",
        expected_mock_state(pot_size=99),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--parser-provider",
            "mock",
            "--minimum-cases",
            "2",
            "--minimum-field-cases",
            "hero_cards=2",
            "--minimum-field-cases",
            "opponent_stack=1",
            "--minimum-field-accuracy",
            "pot_size=1",
            "--minimum-field-accuracy",
            "opponent_stack=1",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Benchmark corpus has 1 case(s), below the minimum 2" in captured.err
    assert "Field hero_cards has 1 labeled case(s), below the minimum 2" in (
        captured.err
    )
    assert "Field opponent_stack has 0 labeled case(s), below the minimum 1" in (
        captured.err
    )
    assert "Field pot_size accuracy 0.0% is below the minimum 100.0%" in captured.err
    assert "Field opponent_stack accuracy was not evaluated" in captured.err


def test_benchmark_cli_fails_when_comparable_baseline_regresses(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = write_dataset_archive(
        tmp_path / "dataset.zip",
        expected_mock_state(pot_size=99),
    )
    settings = Settings(
        data_dir=tmp_path / "unused",
        parser_provider="mock",
        parser_layout_profile="generic",
    )
    current_report = benchmark_dataset_archive(dataset_path, settings)
    baseline_path = write_baseline_report(
        tmp_path / "baseline.json",
        report_with_matching_field(current_report, "pot_size"),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--baseline-report",
            str(baseline_path),
            "--maximum-accuracy-drop",
            "0",
            "--maximum-field-accuracy-drop",
            "pot_size=0",
        ],
        settings=settings,
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Baseline comparison:" in captured.out
    assert "Accuracy: -9.1 pts" in captured.out
    assert "pot_size: -100.0 pts" in captured.out
    assert "Benchmark accuracy dropped 9.1 pts" in captured.err
    assert "Field pot_size accuracy dropped 100.0 pts" in captured.err


def test_benchmark_cli_allows_configured_baseline_drops_with_json_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = write_dataset_archive(
        tmp_path / "dataset.zip",
        expected_mock_state(pot_size=99),
    )
    settings = Settings(
        data_dir=tmp_path / "unused",
        parser_provider="mock",
        parser_layout_profile="generic",
    )
    current_report = benchmark_dataset_archive(dataset_path, settings)
    baseline_path = write_baseline_report(
        tmp_path / "baseline.json",
        report_with_matching_field(current_report, "pot_size"),
    )

    exit_code = main(
        [
            str(dataset_path),
            "--baseline-report",
            str(baseline_path),
            "--maximum-accuracy-drop",
            "0.1",
            "--maximum-field-accuracy-drop",
            "pot_size=1",
            "--json",
        ],
        settings=settings,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["accuracy"] == pytest.approx(10 / 11)
    assert "Baseline comparison" not in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {"parser_provider": "other"},
            "Baseline report parser does not match",
        ),
        (
            {"layout_profile": "other"},
            "Baseline report layout does not match",
        ),
        (
            {"corpus_fingerprint": "f" * 64},
            "Baseline report corpus does not match",
        ),
        (
            {"corpus_fingerprint": None},
            "Baseline report does not include a corpus fingerprint",
        ),
    ],
)
def test_benchmark_cli_rejects_incomparable_baselines(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    updates: dict[str, object],
    message: str,
) -> None:
    dataset_path = write_dataset_archive(
        tmp_path / "dataset.zip",
        expected_mock_state(),
    )
    settings = Settings(
        data_dir=tmp_path / "unused",
        parser_provider="mock",
        parser_layout_profile="generic",
    )
    report = benchmark_dataset_archive(dataset_path, settings)
    baseline_path = write_baseline_report(
        tmp_path / "baseline.json",
        report.model_copy(update=updates),
    )

    exit_code = main(
        [str(dataset_path), "--baseline-report", str(baseline_path)],
        settings=settings,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert message in captured.err


def test_benchmark_cli_rejects_baseline_with_inconsistent_case_labels(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset_path = write_dataset_archive(
        tmp_path / "dataset.zip",
        expected_mock_state(),
    )
    settings = Settings(
        data_dir=tmp_path / "unused",
        parser_provider="mock",
        parser_layout_profile="generic",
    )
    report = benchmark_dataset_archive(dataset_path, settings)
    payload = report.model_dump(mode="json")
    payload["cases"][0]["job_id"] = "b" * 32
    baseline_path = write_baseline_report(
        tmp_path / "baseline.json",
        BenchmarkReport.model_validate(payload),
    )

    exit_code = main(
        [str(dataset_path), "--baseline-report", str(baseline_path)],
        settings=settings,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "Baseline report cases do not match" in captured.err


def test_benchmark_cli_requires_baseline_for_regression_thresholds(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            str(tmp_path / "unused.zip"),
            "--maximum-accuracy-drop",
            "0.01",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "Regression thresholds require --baseline-report" in captured.err


def test_benchmark_cli_rejects_duplicate_field_regression_thresholds(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            str(tmp_path / "unused.zip"),
            "--baseline-report",
            str(tmp_path / "unused.json"),
            "--maximum-field-accuracy-drop",
            "hero_cards=0.1",
            "--maximum-field-accuracy-drop",
            "hero_cards=0.2",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert (
        "--maximum-field-accuracy-drop repeats field hero_cards"
        in captured.err
    )


def test_benchmark_cli_rejects_duplicate_field_thresholds(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            str(tmp_path / "unused.zip"),
            "--minimum-field-accuracy",
            "hero_cards=0.9",
            "--minimum-field-accuracy",
            "hero_cards=1",
        ],
        settings=Settings(data_dir=tmp_path / "unused"),
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--minimum-field-accuracy repeats field hero_cards" in captured.err


def test_benchmark_dataset_archive_rejects_invalid_and_oversized_files(
    tmp_path: Path,
) -> None:
    invalid_path = tmp_path / "invalid.zip"
    invalid_path.write_bytes(b"not a zip")
    settings = Settings(data_dir=tmp_path / "unused")

    with pytest.raises(DatasetBenchmarkError, match="valid dataset ZIP"):
        benchmark_dataset_archive(invalid_path, settings)

    with pytest.raises(
        DatasetBenchmarkError,
        match="POKER_MAX_DATASET_UPLOAD_BYTES",
    ):
        benchmark_dataset_archive(
            invalid_path,
            Settings(
                data_dir=tmp_path / "unused",
                max_dataset_upload_bytes=4,
            ),
        )


def test_baseline_report_rejects_invalid_and_oversized_files(
    tmp_path: Path,
) -> None:
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{}", encoding="utf-8")

    with pytest.raises(DatasetBenchmarkError, match="Baseline report is invalid"):
        load_baseline_report(invalid_path, max_report_bytes=1024)

    with pytest.raises(DatasetBenchmarkError, match="Baseline report is too large"):
        load_baseline_report(invalid_path, max_report_bytes=1)
