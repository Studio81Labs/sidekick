import asyncio
from dataclasses import replace
from threading import Event, Timer

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from app.api.dependencies import (
    ApiRuntime,
    BenchmarkConfigurationError,
    BenchmarkConflictError,
    BenchmarkDatasetExport,
    BenchmarkDatasetInputError,
    BenchmarkImportStatus,
    BenchmarkInputError,
    BenchmarksRuntime,
    BenchmarkTransportNotFoundError,
)
from app.api.routers.benchmarks import create_benchmarks_router
from app.api.routers.health import create_health_router
from app.application.admin_ocr_test import AdminOcrTestAccessPolicy
from app.domain.benchmarks import (
    BenchmarkDatasetImportReceipt,
    BenchmarkDatasetImportResult,
    BenchmarkOverview,
    BenchmarkReport,
    BenchmarkRunRequest,
    BenchmarkSelectionRequest,
)
from app.domain.hands import JobRecord
from app.domain.health import HealthResponse
from app.domain.pipeline import PipelineCapabilities, PipelineSelection
from api_test_support import ADMIN_OCR_TEST_HEADERS, ADMIN_OCR_TEST_TOKEN


ADMIN_OCR_TEST_POLICY = AdminOcrTestAccessPolicy.for_token(ADMIN_OCR_TEST_TOKEN)


def job_record() -> JobRecord:
    return JobRecord(
        id="a" * 32,
        original_filename="table.png",
        image_filename="table.png",
        parser_provider="ocr_cv",
    )


def benchmark_report() -> BenchmarkReport:
    return BenchmarkReport(
        parser_provider="ocr_cv",
        layout_profile="fortuna",
        total_cases=0,
        successful_cases=0,
        failed_cases=0,
        correct_fields=0,
        evaluated_fields=0,
        accuracy=0,
    )


def benchmark_overview() -> BenchmarkOverview:
    return BenchmarkOverview(
        included_cases=0,
        included_cases_by_layout={},
        default_layout_profile="fortuna",
    )


def benchmark_import_result() -> BenchmarkDatasetImportResult:
    return BenchmarkDatasetImportResult(
        imported_cases=0,
        reused_cases=0,
        included_cases=0,
        included_cases_by_layout={},
    )


def benchmark_import_status(*, pending: bool = False) -> BenchmarkImportStatus:
    return BenchmarkImportStatus(
        receipt=BenchmarkDatasetImportReceipt(
            request_id="import-1",
            archive_sha256="a" * 64,
            status="pending" if pending else "completed",
            result=None if pending else benchmark_import_result(),
        ),
        should_resume=pending,
    )


def default_runtime() -> BenchmarksRuntime:
    return BenchmarksRuntime(
        update_inclusion=lambda _job_id, _selection: job_record(),
        get_overview=lambda _provider, _layout: benchmark_overview(),
        export_dataset=lambda _provider, _layout: BenchmarkDatasetExport(
            content=iter([b"dataset archive"]),
            filename="poker-hero-parser-dataset-20260820T000000Z.zip",
        ),
        max_dataset_upload_bytes=1024,
        import_dataset=lambda _archive, _request_id: benchmark_import_result(),
        get_import=lambda _request_id: benchmark_import_status(),
        resume_import=lambda _request_id: None,
        get_report=lambda _report_id: benchmark_report(),
        run=lambda _request: benchmark_report(),
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )


def make_client(runtime: BenchmarksRuntime | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(create_benchmarks_router(runtime or default_runtime()))
    return TestClient(app)


def test_benchmarks_router_delegates_validated_requests_and_streams_exports() -> None:
    calls: list[tuple[object, ...]] = []

    def update_inclusion(
        job_id: str,
        selection: BenchmarkSelectionRequest,
    ) -> JobRecord:
        calls.append(("inclusion", job_id, selection))
        return job_record()

    def get_overview(
        parser_provider: str | None,
        parser_layout_profile: str | None,
    ) -> BenchmarkOverview:
        calls.append(("overview", parser_provider, parser_layout_profile))
        return benchmark_overview()

    def export_dataset(
        parser_provider: str | None,
        parser_layout_profile: str | None,
    ) -> BenchmarkDatasetExport:
        calls.append(("export", parser_provider, parser_layout_profile))
        return BenchmarkDatasetExport(
            content=iter([b"benchmark archive"]),
            filename="poker-hero-parser-dataset-20260820T000000Z.zip",
        )

    def import_dataset(
        archive: bytes,
        request_id: str | None,
    ) -> BenchmarkDatasetImportResult:
        calls.append(("import", archive, request_id))
        return benchmark_import_result()

    def get_import(request_id: str) -> BenchmarkImportStatus:
        calls.append(("get-import", request_id))
        return benchmark_import_status(pending=True)

    def resume_import(request_id: str) -> None:
        calls.append(("resume-import", request_id))

    def get_report(report_id: str) -> BenchmarkReport:
        calls.append(("report", report_id))
        return benchmark_report()

    def run(request: BenchmarkRunRequest | None) -> BenchmarkReport:
        calls.append(("run", request))
        return benchmark_report()

    runtime = BenchmarksRuntime(
        update_inclusion=update_inclusion,
        get_overview=get_overview,
        export_dataset=export_dataset,
        max_dataset_upload_bytes=1024,
        import_dataset=import_dataset,
        get_import=get_import,
        resume_import=resume_import,
        get_report=get_report,
        run=run,
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )
    with make_client(runtime) as client:
        responses = [
            client.put("/api/jobs/job-1/benchmark", json={"included": True}),
            client.get(
                "/api/benchmarks",
                params={
                    "parser_provider": "mock",
                    "parser_layout_profile": "pokerstars",
                },
            ),
            client.get(
                "/api/benchmarks/export",
                params={
                    "parser_provider": "mock",
                    "parser_layout_profile": "pokerstars",
                },
            ),
            client.post(
                "/api/benchmarks/import",
                files={"file": ("dataset.zip", b"dataset", "application/zip")},
                headers={
                    **ADMIN_OCR_TEST_HEADERS,
                    "X-Benchmark-Import-Request-ID": "import-1",
                },
            ),
            client.get("/api/benchmarks/imports/import-1"),
            client.get("/api/benchmarks/report-1"),
            client.post(
                "/api/benchmarks/run",
                json={
                    "parser_provider": "mock",
                    "parser_layout_profile": "pokerstars",
                },
            ),
        ]

    assert [response.status_code for response in responses] == [200] * 7
    assert responses[2].content == b"benchmark archive"
    assert responses[2].headers["content-type"] == "application/zip"
    assert responses[2].headers["content-disposition"] == (
        'attachment; filename="poker-hero-parser-dataset-20260820T000000Z.zip"'
    )
    assert responses[4].json()["status"] == "pending"
    assert calls == [
        ("inclusion", "job-1", BenchmarkSelectionRequest(included=True)),
        ("overview", "mock", "pokerstars"),
        ("export", "mock", "pokerstars"),
        ("import", b"dataset", "import-1"),
        ("get-import", "import-1"),
        ("resume-import", "import-1"),
        ("report", "report-1"),
        (
            "run",
            BenchmarkRunRequest(
                parser_provider="mock",
                parser_layout_profile="pokerstars",
            ),
        ),
    ]


def test_benchmarks_router_preserves_request_validation_and_upload_bounds() -> None:
    calls: list[str] = []
    runtime = replace(
        default_runtime(),
        update_inclusion=lambda _job_id, _selection: calls.append("inclusion")
        or job_record(),
        get_overview=lambda _provider, _layout: calls.append("overview")
        or benchmark_overview(),
        export_dataset=lambda _provider, _layout: calls.append("export")
        or BenchmarkDatasetExport(iter([b"archive"]), "archive.zip"),
        max_dataset_upload_bytes=3,
        import_dataset=lambda _archive, _request_id: calls.append("import")
        or benchmark_import_result(),
        run=lambda _request: calls.append("run") or benchmark_report(),
    )
    with make_client(runtime) as client:
        responses = [
            client.put("/api/jobs/job-1/benchmark", json={}),
            client.get(
                "/api/benchmarks",
                params={"parser_provider": "invalid-provider"},
            ),
            client.get(
                "/api/benchmarks/export",
                params={"parser_layout_profile": "invalid-profile"},
            ),
            client.post(
                "/api/benchmarks/import",
                files={"file": ("dataset.zip", b"zip", "application/zip")},
                headers={
                    **ADMIN_OCR_TEST_HEADERS,
                    "X-Benchmark-Import-Request-ID": "invalid request id",
                },
            ),
            client.post(
                "/api/benchmarks/import",
                files={"file": ("dataset.zip", b"four", "application/zip")},
                headers=ADMIN_OCR_TEST_HEADERS,
            ),
            client.post("/api/benchmarks/run", json={}),
        ]

    assert [response.status_code for response in responses] == [
        422,
        422,
        422,
        422,
        413,
        422,
    ]
    assert responses[4].json() == {"detail": "Dataset ZIP exceeds maximum size"}
    assert calls == []


def test_benchmark_import_runs_application_work_outside_event_loop() -> None:
    import_started = Event()
    release_import = Event()

    def import_dataset(
        _archive: bytes,
        _request_id: str | None,
    ) -> BenchmarkDatasetImportResult:
        import_started.set()
        assert release_import.wait(timeout=3)
        return benchmark_import_result()

    runtime = replace(default_runtime(), import_dataset=import_dataset)
    app = FastAPI()
    app.include_router(create_benchmarks_router(runtime))
    app.include_router(create_health_router(ApiRuntime(
        get_health=lambda: HealthResponse(
            status="ok",
            environment="local",
            parser_provider="ocr_cv",
        ),
        get_pipeline_capabilities=lambda: PipelineCapabilities(
            defaults=PipelineSelection(
                parser_provider="ocr_cv",
                parser_layout_profile="fortuna",
            ),
            parser_providers=[],
            parser_layout_profiles=[],
            parser_layout_compatibility={},
        ),
    )))

    async def exercise() -> None:
        safety_release = Timer(2, release_import.set)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            safety_release.start()
            import_task = asyncio.create_task(client.post(
                "/api/benchmarks/import",
                files={"file": ("dataset.zip", b"zip", "application/zip")},
                headers=ADMIN_OCR_TEST_HEADERS,
            ))
            try:
                while not import_started.is_set():
                    await asyncio.sleep(0)
                assert not import_task.done()
                health = await asyncio.wait_for(client.get("/api/health"), timeout=1)
            finally:
                release_import.set()
                safety_release.cancel()
            imported = await import_task

        assert health.status_code == 200
        assert imported.status_code == 200

    asyncio.run(exercise())


def test_benchmarks_router_maps_typed_application_errors() -> None:
    def fail_update(
        _job_id: str,
        _selection: BenchmarkSelectionRequest,
    ) -> JobRecord:
        raise BenchmarkConflictError("Benchmark corpus is busy")

    def fail_overview(
        _provider: str | None,
        _layout: str | None,
    ) -> BenchmarkOverview:
        raise BenchmarkInputError("Unknown parser provider")

    def fail_export(
        _provider: str | None,
        _layout: str | None,
    ) -> BenchmarkDatasetExport:
        raise BenchmarkConflictError("No approved benchmark hands")

    def fail_import(
        _archive: bytes,
        _request_id: str | None,
    ) -> BenchmarkDatasetImportResult:
        raise BenchmarkDatasetInputError("Dataset ZIP is invalid", 400)

    def fail_get_import(_request_id: str) -> BenchmarkImportStatus:
        raise BenchmarkTransportNotFoundError("Benchmark dataset import not found")

    def fail_get_report(_report_id: str) -> BenchmarkReport:
        raise BenchmarkTransportNotFoundError("Benchmark report not found")

    def fail_run(_request: BenchmarkRunRequest | None) -> BenchmarkReport:
        raise BenchmarkConfigurationError("parser is unavailable")

    runtime = BenchmarksRuntime(
        update_inclusion=fail_update,
        get_overview=fail_overview,
        export_dataset=fail_export,
        max_dataset_upload_bytes=1024,
        import_dataset=fail_import,
        get_import=fail_get_import,
        resume_import=lambda _request_id: None,
        get_report=fail_get_report,
        run=fail_run,
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )
    with make_client(runtime) as client:
        responses = [
            client.put("/api/jobs/job-1/benchmark", json={"included": True}),
            client.get("/api/benchmarks"),
            client.get("/api/benchmarks/export"),
            client.post(
                "/api/benchmarks/import",
                files={"file": ("dataset.zip", b"zip", "application/zip")},
                headers=ADMIN_OCR_TEST_HEADERS,
            ),
            client.get("/api/benchmarks/imports/missing"),
            client.get("/api/benchmarks/missing"),
            client.post(
                "/api/benchmarks/run",
                json={
                    "parser_provider": "mock",
                    "parser_layout_profile": "pokerstars",
                },
            ),
        ]

    assert [
        (response.status_code, response.json()) for response in responses
    ] == [
        (409, {"detail": "Benchmark corpus is busy"}),
        (400, {"detail": "Unknown parser provider"}),
        (409, {"detail": "No approved benchmark hands"}),
        (400, {"detail": "Dataset ZIP is invalid"}),
        (404, {"detail": "Benchmark dataset import not found"}),
        (404, {"detail": "Benchmark report not found"}),
        (500, {"detail": "Parser configuration error: parser is unavailable"}),
    ]


def test_benchmarks_router_refuses_import_without_the_administrator_credential() -> None:
    imports: list[bytes] = []

    def should_not_import(
        archive_bytes: bytes,
        _request_id: str | None,
    ) -> BenchmarkDatasetImportResult:
        imports.append(archive_bytes)
        return benchmark_import_result()

    def runtime_deciding(decision: str) -> BenchmarksRuntime:
        return replace(
            default_runtime(),
            import_dataset=should_not_import,
            authorize_administrator=lambda _authorization_header: decision,
        )

    with make_client(runtime_deciding("disabled")) as client:
        disabled = client.post(
            "/api/benchmarks/import",
            files={"file": ("dataset.zip", b"dataset", "application/zip")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )
    authorizing = replace(default_runtime(), import_dataset=should_not_import)
    with make_client(authorizing) as client:
        missing = client.post(
            "/api/benchmarks/import",
            files={"file": ("dataset.zip", b"dataset", "application/zip")},
        )
    with make_client(runtime_deciding("expired")) as client:
        unexpected = client.post(
            "/api/benchmarks/import",
            files={"file": ("dataset.zip", b"dataset", "application/zip")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )

    assert (disabled.status_code, disabled.json()) == (
        403,
        {"detail": "Administrative OCR test mode is disabled"},
    )
    assert (missing.status_code, missing.json()) == (
        401,
        {"detail": "Administrative OCR test authorization is required"},
    )
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert (unexpected.status_code, unexpected.json()) == (
        403,
        {"detail": "Administrative OCR test authorization was refused"},
    )
    assert imports == []


def test_benchmarks_router_denies_before_reading_an_oversize_archive() -> None:
    runtime = replace(default_runtime(), max_dataset_upload_bytes=3)

    with make_client(runtime) as client:
        response = client.post(
            "/api/benchmarks/import",
            files={"file": ("dataset.zip", b"far too large", "application/zip")},
        )

    assert response.status_code == 401


def test_benchmarks_router_preserves_public_operation_ids() -> None:
    with make_client() as client:
        paths = client.app.openapi()["paths"]

    assert paths["/api/jobs/{job_id}/benchmark"]["put"]["operationId"] == (
        "job_benchmark_update"
    )
    assert paths["/api/benchmarks"]["get"]["operationId"] == "benchmarks_get"
    assert paths["/api/benchmarks/export"]["get"]["operationId"] == (
        "benchmarks_export"
    )
    assert paths["/api/benchmarks/import"]["post"]["operationId"] == (
        "benchmarks_import"
    )
    assert paths["/api/benchmarks/imports/{request_id}"]["get"]["operationId"] == (
        "benchmark_import_get"
    )
    assert paths["/api/benchmarks/{report_id}"]["get"]["operationId"] == (
        "benchmark_report_get"
    )
    assert paths["/api/benchmarks/run"]["post"]["operationId"] == "benchmarks_run"
