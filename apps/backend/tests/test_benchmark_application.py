from typing import cast

from app.api.dependencies import (
    BenchmarkDatasetExport as CompatibilityBenchmarkDatasetExport,
)
from app.api.dependencies import BenchmarkImportStatus as CompatibilityBenchmarkImportStatus
from app.api.dependencies import BenchmarksRuntime
from app.application.benchmarks import (
    BenchmarkDatasetExport,
    BenchmarkImportStatus,
    BenchmarkService,
)
from app.domain.benchmarks import (
    BenchmarkDatasetImportReceipt,
    BenchmarkDatasetImportResult,
    BenchmarkOverview,
    BenchmarkReport,
    BenchmarkRunRequest,
    BenchmarkSelectionRequest,
)
from app.domain.hands import JobRecord


def test_benchmark_service_dispatches_use_cases() -> None:
    calls: list[tuple[object, ...]] = []
    job = cast(JobRecord, object())
    selection = cast(BenchmarkSelectionRequest, object())
    overview = cast(BenchmarkOverview, object())
    export = BenchmarkDatasetExport(iter([b"archive"]), "dataset.zip")
    import_result = cast(BenchmarkDatasetImportResult, object())
    receipt = cast(BenchmarkDatasetImportReceipt, object())
    import_status = BenchmarkImportStatus(receipt=receipt, should_resume=True)
    report = cast(BenchmarkReport, object())
    run_request = cast(BenchmarkRunRequest, object())

    def update_inclusion(
        job_id: str,
        request: BenchmarkSelectionRequest,
    ) -> JobRecord:
        calls.append(("update", job_id, request))
        return job

    def get_overview(
        parser_provider: str | None,
        parser_layout_profile: str | None,
    ) -> BenchmarkOverview:
        calls.append(("overview", parser_provider, parser_layout_profile))
        return overview

    def export_dataset(
        parser_provider: str | None,
        parser_layout_profile: str | None,
    ) -> BenchmarkDatasetExport:
        calls.append(("export", parser_provider, parser_layout_profile))
        return export

    def import_dataset(
        archive_bytes: bytes,
        request_id: str | None,
    ) -> BenchmarkDatasetImportResult:
        calls.append(("import", archive_bytes, request_id))
        return import_result

    def get_import(request_id: str) -> BenchmarkImportStatus:
        calls.append(("get_import", request_id))
        return import_status

    def resume_import(request_id: str) -> None:
        calls.append(("resume", request_id))

    def get_report(report_id: str) -> BenchmarkReport:
        calls.append(("get_report", report_id))
        return report

    def run(request: BenchmarkRunRequest | None) -> BenchmarkReport:
        calls.append(("run", request))
        return report

    service = BenchmarkService(
        update_inclusion=update_inclusion,
        get_overview=get_overview,
        export_dataset=export_dataset,
        max_dataset_upload_bytes=1024,
        import_dataset=import_dataset,
        get_import=get_import,
        resume_import=resume_import,
        get_report=get_report,
        run=run,
    )

    assert service.max_dataset_upload_bytes == 1024
    assert service.update_inclusion("job-a", selection) is job
    assert service.get_overview("ocr_cv", "fortuna") is overview
    assert service.export_dataset(None, None) is export
    assert service.import_dataset(b"zip", "import-a") is import_result
    assert service.get_import("import-a") is import_status
    assert service.resume_import("import-a") is None
    assert service.get_report("report-a") is report
    assert service.run(run_request) is report
    assert calls == [
        ("update", "job-a", selection),
        ("overview", "ocr_cv", "fortuna"),
        ("export", None, None),
        ("import", b"zip", "import-a"),
        ("get_import", "import-a"),
        ("resume", "import-a"),
        ("get_report", "report-a"),
        ("run", run_request),
    ]


def test_benchmark_transport_compatibility_aliases_preserve_identity() -> None:
    assert CompatibilityBenchmarkDatasetExport is BenchmarkDatasetExport
    assert CompatibilityBenchmarkImportStatus is BenchmarkImportStatus
    assert BenchmarksRuntime is BenchmarkService
