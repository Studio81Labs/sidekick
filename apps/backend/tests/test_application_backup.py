import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Event, Thread
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.bootstrap as bootstrap_module
import app.application_backup as application_backup_module
from app.bootstrap import create_app
from app.config import Settings
from app.data_lock import InterprocessDataLock
from app.storage.file_benchmark_store import FileBenchmarkStore
from app.storage.file_job_store import FileJobStore
from api_test_support import (
    ADMIN_OCR_TEST_HEADERS,
    ADMIN_OCR_TEST_TOKEN,
    restore_application_backup,
)


VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
)
APPROVED_STATE = {
    "hero_cards": [
        {"rank": "A", "suit": "hearts"},
        {"rank": "K", "suit": "diamonds"},
    ],
    "board_cards": [
        {"rank": "Q", "suit": "spades"},
        {"rank": "J", "suit": "clubs"},
        {"rank": "2", "suit": "hearts"},
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


def make_client(data_dir: Path, **overrides: object) -> TestClient:
    values = {
        "data_dir": data_dir,
        "parser_provider": "mock",
        "admin_ocr_test_enabled": True,
        "admin_ocr_test_token": ADMIN_OCR_TEST_TOKEN,
    }
    values.update(overrides)
    return TestClient(create_app(Settings(**values)))


def create_reviewed_job(client: TestClient) -> dict[str, object]:
    upload = client.post(
        "/api/jobs",
        files={"file": ("table.png", VALID_PNG, "image/png")},
        data={"upload_request_id": "backup-upload-1"},
        headers=ADMIN_OCR_TEST_HEADERS,
    )
    assert upload.status_code == 201
    job_id = upload.json()["id"]
    assert client.post(
        f"/api/jobs/{job_id}/approve",
        json=APPROVED_STATE,
    ).status_code == 200
    assert client.put(
        f"/api/jobs/{job_id}/metadata",
        json={
            "title": "Backup review hand",
            "notes": "Imported from the weekly study session.",
            "tags": ["backup", "turn"],
        },
    ).status_code == 200
    assert client.put(
        f"/api/jobs/{job_id}/benchmark",
        json={"included": True},
    ).status_code == 200
    benchmark = client.post("/api/benchmarks/run")
    assert benchmark.status_code == 200
    archive = client.put("/api/history", json={"job_ids": [job_id]})
    assert archive.status_code == 200
    return archive.json()["jobs"][0]


def rebuild_archive(
    archive_bytes: bytes,
    replacements: dict[str, bytes],
) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(archive_bytes)) as source:
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as target:
            for info in source.infolist():
                target.writestr(
                    info.filename,
                    replacements.get(info.filename, source.read(info)),
                )
    return output.getvalue()


def test_application_backup_round_trip_preserves_all_durable_state(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source = make_client(source_dir)
    source_job = create_reviewed_job(source)

    export = source.get("/api/backups/export")

    assert export.status_code == 200
    assert export.headers["content-type"] == "application/zip"
    assert "poker-hero-backup-" in export.headers["content-disposition"]
    with ZipFile(BytesIO(export.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema"] == "poker-hero-application-backup"
        assert manifest["schema_version"] == 1
        assert manifest["job_count"] == 1
        assert manifest["benchmark_report_count"] == 1
        assert set(archive.namelist()) == {
            "manifest.json",
            f"jobs/{source_job['id']}/job.json",
            f"jobs/{source_job['id']}/original.png",
            f"benchmarks/{manifest['benchmark_reports'][0]['report_id']}.json",
        }

    destination_dir = tmp_path / "destination"
    destination = make_client(destination_dir)
    restore = restore_application_backup(destination, export.content)

    assert restore.status_code == 200
    assert restore.json() == {
        "imported_jobs": 1,
        "reused_jobs": 0,
        "imported_benchmark_reports": 1,
        "reused_benchmark_reports": 0,
        "total_jobs": 1,
        "total_benchmark_reports": 1,
    }
    restored_job = FileJobStore(destination_dir).get(str(source_job["id"]))
    assert restored_job == FileJobStore(source_dir).get(str(source_job["id"]))
    assert FileJobStore(destination_dir).image_path(restored_job).read_bytes() == VALID_PNG
    history = destination.get("/api/history")
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert history.json()["jobs"][0]["title"] == "Backup review hand"
    assert history.json()["jobs"][0]["notes"] == (
        "Imported from the weekly study session."
    )
    assert history.json()["jobs"][0]["tags"] == ["backup", "turn"]
    source_report = FileBenchmarkStore(source_dir).get_latest()
    restored_report = FileBenchmarkStore(destination_dir).get_latest()
    assert source_report is not None
    assert restored_report == source_report

    repeated = restore_application_backup(destination, export.content)

    assert repeated.status_code == 200
    assert repeated.json() == {
        "imported_jobs": 0,
        "reused_jobs": 1,
        "imported_benchmark_reports": 0,
        "reused_benchmark_reports": 1,
        "total_jobs": 1,
        "total_benchmark_reports": 1,
    }


def test_empty_application_backup_round_trips(
    tmp_path: Path,
) -> None:
    source = make_client(tmp_path / "source")

    export = source.get("/api/backups/export")

    assert export.status_code == 200
    destination = make_client(tmp_path / "destination")
    restore = restore_application_backup(destination, export.content)
    assert restore.status_code == 200
    assert restore.json() == {
        "imported_jobs": 0,
        "reused_jobs": 0,
        "imported_benchmark_reports": 0,
        "reused_benchmark_reports": 0,
        "total_jobs": 0,
        "total_benchmark_reports": 0,
    }


def test_restore_does_not_block_unrelated_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_client(tmp_path / "source")
    export = source.get("/api/backups/export")
    assert export.status_code == 200

    parse_started = Event()
    release_parse = Event()
    original_parse = bootstrap_module.parse_application_backup_archive

    def paused_parse(*args: object, **kwargs: object):
        parse_started.set()
        assert release_parse.wait(timeout=2)
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(
        bootstrap_module,
        "parse_application_backup_archive",
        paused_parse,
    )
    destination_app = create_app(
        Settings(
            data_dir=tmp_path / "destination",
            parser_provider="mock",
            admin_ocr_test_enabled=True,
            admin_ocr_test_token=ADMIN_OCR_TEST_TOKEN,
        )
    )

    async def exercise_restore() -> None:
        transport = httpx.ASGITransport(app=destination_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            restore_task = asyncio.create_task(
                restore_application_backup(client, export.content)
            )
            try:
                assert await asyncio.to_thread(parse_started.wait, 2)
                health = await asyncio.wait_for(
                    client.get("/api/health"),
                    timeout=1,
                )
                assert health.status_code == 200
            finally:
                release_parse.set()
            restore = await restore_task
            assert restore.status_code == 200

    asyncio.run(exercise_restore())


def test_upload_waiting_for_backup_does_not_block_unrelated_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_started = Event()
    release_export = Event()
    original_build = bootstrap_module.build_application_backup_archive

    def paused_build(*args: object, **kwargs: object):
        export_started.set()
        assert release_export.wait(timeout=2)
        return original_build(*args, **kwargs)

    monkeypatch.setattr(
        bootstrap_module,
        "build_application_backup_archive",
        paused_build,
    )
    app = create_app(
        Settings(
            data_dir=tmp_path,
            parser_provider="mock",
            admin_ocr_test_enabled=True,
            admin_ocr_test_token=ADMIN_OCR_TEST_TOKEN,
        )
    )

    async def exercise_upload() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            export_task = asyncio.create_task(client.get("/api/backups/export"))
            assert await asyncio.to_thread(export_started.wait, 2)
            upload_task = asyncio.create_task(
                client.post(
                    "/api/jobs",
                    files={"file": ("table.png", VALID_PNG, "image/png")},
                    headers=ADMIN_OCR_TEST_HEADERS,
                )
            )
            try:
                await asyncio.sleep(0.05)
                assert not upload_task.done()
                health = await asyncio.wait_for(
                    client.get("/api/health"),
                    timeout=1,
                )
                assert health.status_code == 200
            finally:
                release_export.set()
            export = await export_task
            upload = await upload_task
            assert export.status_code == 200
            assert upload.status_code == 201

    asyncio.run(exercise_upload())


def test_backup_export_returns_conflict_after_its_lock_wait_budget(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        data_lock_export_timeout_seconds=1,
    )
    blocker = InterprocessDataLock(tmp_path)
    responses: list[httpx.Response] = []
    failures: list[Exception] = []

    def request_export() -> None:
        try:
            responses.append(client.get("/api/backups/export"))
        except Exception as exc:
            failures.append(exc)

    with blocker.hold(exclusive=False):
        request = Thread(target=request_export)
        request.start()
        request.join(timeout=3)
        completed_before_release = not request.is_alive()

    request.join(timeout=5)

    assert completed_before_release
    assert not request.is_alive()
    assert failures == []
    assert len(responses) == 1
    assert responses[0].status_code == 409
    assert responses[0].json() == {
        "detail": "Application backup export is busy; try again"
    }

    retry = client.get("/api/backups/export")
    assert retry.status_code == 200


def test_slow_backup_download_does_not_block_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream_started = Event()
    release_stream = Event()
    original_stream = bootstrap_module.stream_application_backup

    def paused_stream(archive_file):
        stream_started.set()
        assert release_stream.wait(timeout=5)
        yield from original_stream(archive_file)

    monkeypatch.setattr(
        bootstrap_module,
        "stream_application_backup",
        paused_stream,
    )
    app = create_app(
        Settings(
            data_dir=tmp_path,
            parser_provider="mock",
            admin_ocr_test_enabled=True,
            admin_ocr_test_token=ADMIN_OCR_TEST_TOKEN,
        )
    )

    async def exercise_slow_download() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            export_task = asyncio.create_task(client.get("/api/backups/export"))
            assert await asyncio.to_thread(stream_started.wait, 2)
            try:
                upload = await asyncio.wait_for(
                    client.post(
                        "/api/jobs",
                        files={"file": ("table.png", VALID_PNG, "image/png")},
                        headers=ADMIN_OCR_TEST_HEADERS,
                    ),
                    timeout=2,
                )
                assert upload.status_code == 201
            finally:
                release_stream.set()
            export = await export_task
            assert export.status_code == 200

    asyncio.run(exercise_slow_download())


def test_restored_old_reports_do_not_displace_recent_report_history(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source = make_client(source_dir)
    create_reviewed_job(source)
    old_report = FileBenchmarkStore(source_dir).get_latest()
    assert old_report is not None

    destination_store = FileBenchmarkStore(tmp_path / "destination")
    baseline = datetime(2026, 7, 1, tzinfo=timezone.utc)
    recent_reports = [
        old_report.model_copy(
            update={
                "id": f"{index + 1:032x}",
                "created_at": baseline + timedelta(days=index),
            }
        )
        for index in range(10)
    ]
    for report in recent_reports:
        destination_store.save(report)
    restored_old_report = old_report.model_copy(
        update={
            "id": f"{100:032x}",
            "created_at": baseline - timedelta(days=1),
        }
    )

    destination_store.restore(restored_old_report)
    recent_history = destination_store.list(limit=10)

    assert [report.id for report in recent_history] == [
        report.id for report in reversed(recent_reports)
    ]


def test_restore_tracks_published_report_when_temp_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_client(tmp_path / "source")
    source_job = create_reviewed_job(source)
    export = source.get("/api/backups/export")
    assert export.status_code == 200

    original_unlink = Path.unlink

    def fail_report_temp_cleanup(
        path: Path,
        *args: object,
        **kwargs: object,
    ) -> None:
        if path.name.startswith(".backup-report."):
            raise OSError("simulated temporary file cleanup failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_report_temp_cleanup)
    destination_dir = tmp_path / "destination"
    destination = make_client(destination_dir)

    restore = restore_application_backup(destination, export.content)

    assert restore.status_code == 200
    assert restore.json()["imported_benchmark_reports"] == 1
    assert FileJobStore(destination_dir).get(str(source_job["id"])).id == source_job["id"]
    restored_report = FileBenchmarkStore(destination_dir).get_latest()
    assert restored_report is not None
    assert list((destination_dir / "benchmarks").glob(".backup-report.*.tmp"))


def test_backup_rejects_decompression_bomb_images_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_client(tmp_path / "source")
    create_reviewed_job(source)
    valid_export = source.get("/api/backups/export")
    assert valid_export.status_code == 200

    def raise_decompression_bomb(*args: object, **kwargs: object):
        raise Image.DecompressionBombError("image dimensions are unsafe")

    monkeypatch.setattr(
        application_backup_module.Image,
        "open",
        raise_decompression_bomb,
    )

    rejected_export = source.get("/api/backups/export")
    destination_dir = tmp_path / "destination"
    destination = make_client(destination_dir)
    rejected_restore = restore_application_backup(destination, valid_export.content)

    assert rejected_export.status_code == 409
    assert "Image is invalid" in rejected_export.json()["detail"]
    assert rejected_restore.status_code == 400
    assert "image is invalid" in rejected_restore.json()["detail"]
    assert FileJobStore(destination_dir).list() == []
    assert FileBenchmarkStore(destination_dir).list(limit=None) == []


def test_restore_rejects_checksum_tampering_before_writing(
    tmp_path: Path,
) -> None:
    source = make_client(tmp_path / "source")
    source_job = create_reviewed_job(source)
    export = source.get("/api/backups/export")
    tampered = rebuild_archive(
        export.content,
        {f"jobs/{source_job['id']}/original.png": VALID_PNG + b"tampered"},
    )
    destination_dir = tmp_path / "destination"
    destination = make_client(destination_dir)

    response = restore_application_backup(destination, tampered)

    assert response.status_code == 400
    assert "size does not match" in response.json()["detail"]
    assert FileJobStore(destination_dir).list() == []
    assert FileBenchmarkStore(destination_dir).list(limit=None) == []


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("job_count", "1"),
        ("job_count", 1.0),
        ("benchmark_report_count", True),
        ("jobs.0.image_size", str(len(VALID_PNG))),
        ("jobs.0.image_size", float(len(VALID_PNG))),
    ],
)
def test_restore_rejects_coerced_manifest_integers_before_writing(
    tmp_path: Path,
    field_path: str,
    value: object,
) -> None:
    source = make_client(tmp_path / "source")
    create_reviewed_job(source)
    export = source.get("/api/backups/export")
    with ZipFile(BytesIO(export.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    if field_path == "jobs.0.image_size":
        manifest["jobs"][0]["image_size"] = value
    else:
        manifest[field_path] = value
    modified = rebuild_archive(
        export.content,
        {
            "manifest.json": (
                json.dumps(manifest, indent=2) + "\n"
            ).encode(),
        },
    )
    destination_dir = tmp_path / "destination"
    destination = make_client(destination_dir)

    response = restore_application_backup(destination, modified)

    assert response.status_code == 400
    assert f"invalid at {field_path}" in response.json()["detail"]
    assert FileJobStore(destination_dir).list() == []
    assert FileBenchmarkStore(destination_dir).list(limit=None) == []


def test_restore_rejects_naive_job_timestamp_before_writing(
    tmp_path: Path,
) -> None:
    source = make_client(tmp_path / "source")
    source_job = create_reviewed_job(source)
    export = source.get("/api/backups/export")
    with ZipFile(BytesIO(export.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        record_name = f"jobs/{source_job['id']}/job.json"
        record = json.loads(archive.read(record_name))
    record["created_at"] = "2026-07-31T12:00:00"
    record_bytes = (json.dumps(record, indent=2) + "\n").encode()
    manifest["jobs"][0]["record_sha256"] = sha256(record_bytes).hexdigest()
    modified = rebuild_archive(
        export.content,
        {
            record_name: record_bytes,
            "manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
        },
    )
    destination_dir = tmp_path / "destination"
    destination = make_client(destination_dir)

    response = restore_application_backup(destination, modified)

    assert response.status_code == 400
    assert "job" in response.json()["detail"]
    assert "created_at must include a timezone" in response.json()["detail"]
    assert FileJobStore(destination_dir).list() == []
    assert FileBenchmarkStore(destination_dir).list(limit=None) == []


def test_restore_rejects_naive_report_timestamp_before_writing(
    tmp_path: Path,
) -> None:
    source = make_client(tmp_path / "source")
    create_reviewed_job(source)
    export = source.get("/api/backups/export")
    with ZipFile(BytesIO(export.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        report_name = manifest["benchmark_reports"][0]["report_file"]
        report = json.loads(archive.read(report_name))
    report["created_at"] = "2026-07-31T12:00:00"
    report_bytes = (json.dumps(report, indent=2) + "\n").encode()
    manifest["benchmark_reports"][0]["report_sha256"] = sha256(
        report_bytes
    ).hexdigest()
    modified = rebuild_archive(
        export.content,
        {
            report_name: report_bytes,
            "manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
        },
    )
    destination_dir = tmp_path / "destination"
    destination = make_client(destination_dir)

    response = restore_application_backup(destination, modified)

    assert response.status_code == 400
    assert "report" in response.json()["detail"]
    assert "created_at must include a timezone" in response.json()["detail"]
    assert FileJobStore(destination_dir).list() == []
    assert FileBenchmarkStore(destination_dir).list(limit=None) == []


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        ("total_cases", True),
        ("total_cases", "1"),
        ("total_cases", 1.0),
        ("accuracy", "1"),
        ("cases.0.correct_fields", True),
        ("cases.0.accuracy", "1"),
        ("cases.0.comparisons.0.matched", "false"),
        ("cases.0.comparisons.0.confidence", "0.99"),
        ("field_metrics.0.correct", True),
        ("field_metrics.0.accuracy", "1"),
    ],
)
def test_restore_rejects_coerced_benchmark_report_metrics_before_writing(
    tmp_path: Path,
    field_path: str,
    value: object,
) -> None:
    source = make_client(tmp_path / "source")
    create_reviewed_job(source)
    export = source.get("/api/backups/export")
    with ZipFile(BytesIO(export.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        report_name = manifest["benchmark_reports"][0]["report_file"]
        report = json.loads(archive.read(report_name))
    cursor: Any = report
    path_parts = field_path.split(".")
    for part in path_parts[:-1]:
        cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[part]
    cursor[path_parts[-1]] = value
    report_bytes = (json.dumps(report, indent=2) + "\n").encode()
    manifest["benchmark_reports"][0]["report_sha256"] = sha256(
        report_bytes
    ).hexdigest()
    modified = rebuild_archive(
        export.content,
        {
            report_name: report_bytes,
            "manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
        },
    )
    destination_dir = tmp_path / "destination"
    destination = make_client(destination_dir)

    response = restore_application_backup(destination, modified)

    assert response.status_code == 400
    assert "report" in response.json()["detail"]
    assert "is invalid" in response.json()["detail"]
    assert FileJobStore(destination_dir).list() == []
    assert FileBenchmarkStore(destination_dir).list(limit=None) == []


@pytest.mark.parametrize(
    ("field_path", "value"),
    [
        ("total_cases", 2),
        ("successful_cases", 0),
        ("failed_cases", 1),
        ("correct_fields", 10),
        ("evaluated_fields", 12),
        ("accuracy", 0.5),
        ("cases.0.correct_fields", 10),
        ("cases.0.evaluated_fields", 12),
        ("cases.0.accuracy", 0.5),
        ("cases.0.status", "error"),
        ("cases.0.comparisons.1.field", "hero_cards"),
        ("field_metrics.0.correct", 0),
        ("field_metrics.1.field", "hero_cards"),
    ],
)
def test_restore_rejects_inconsistent_benchmark_report_metrics_before_writing(
    tmp_path: Path,
    field_path: str,
    value: object,
) -> None:
    source = make_client(tmp_path / "source")
    create_reviewed_job(source)
    export = source.get("/api/backups/export")
    with ZipFile(BytesIO(export.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        report_name = manifest["benchmark_reports"][0]["report_file"]
        report = json.loads(archive.read(report_name))
    cursor: Any = report
    path_parts = field_path.split(".")
    for part in path_parts[:-1]:
        cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[part]
    cursor[path_parts[-1]] = value
    report_bytes = (json.dumps(report, indent=2) + "\n").encode()
    manifest["benchmark_reports"][0]["report_sha256"] = sha256(
        report_bytes
    ).hexdigest()
    modified = rebuild_archive(
        export.content,
        {
            report_name: report_bytes,
            "manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
        },
    )
    destination_dir = tmp_path / "destination"
    destination = make_client(destination_dir)

    response = restore_application_backup(destination, modified)

    assert response.status_code == 400
    assert "report" in response.json()["detail"]
    assert "is invalid" in response.json()["detail"]
    assert FileJobStore(destination_dir).list() == []
    assert FileBenchmarkStore(destination_dir).list(limit=None) == []


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_field",
        "incorrect_match",
        "oversized_number",
        "nested_oversized_number",
        "nonfinite_number",
        "duplicate_card_across_fields",
        "unnormalized_text",
    ],
)
def test_restore_rejects_invalid_benchmark_comparisons_before_writing(
    tmp_path: Path,
    mutation: str,
) -> None:
    source = make_client(tmp_path / "source")
    create_reviewed_job(source)
    export = source.get("/api/backups/export")
    with ZipFile(BytesIO(export.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        report_name = manifest["benchmark_reports"][0]["report_file"]
        report = json.loads(archive.read(report_name))

    case = report["cases"][0]
    comparison = case["comparisons"][0]
    metric = next(
        item
        for item in report["field_metrics"]
        if item["field"] == comparison["field"]
    )
    if mutation == "unknown_field":
        comparison["field"] = "invented_field"
        metric["field"] = "invented_field"
    elif mutation == "incorrect_match":
        assert comparison["matched"] is True
        comparison["matched"] = False
        case["correct_fields"] -= 1
        case["accuracy"] = case["correct_fields"] / case["evaluated_fields"]
        report["correct_fields"] -= 1
        report["accuracy"] = report["correct_fields"] / report["evaluated_fields"]
        metric["correct"] -= 1
        metric["accuracy"] = metric["correct"] / metric["total"]
    elif mutation == "oversized_number":
        comparison["expected"] = 10**400
    elif mutation == "nested_oversized_number":
        comparison["expected"] = [10**400]
        comparison["detected"] = [10**400]
    elif mutation == "nonfinite_number":
        comparison["expected"] = float("inf")
    elif mutation == "duplicate_card_across_fields":
        hero_cards = next(
            item for item in case["comparisons"] if item["field"] == "hero_cards"
        )
        board_cards = next(
            item for item in case["comparisons"] if item["field"] == "board_cards"
        )
        for side in ("expected", "detected"):
            board_cards[side][0] = hero_cards[side][0]
            board_cards[side].sort()
    else:
        position = next(
            item
            for item in case["comparisons"]
            if item["field"] == "hero_position"
        )
        position["expected"] = "BTN"
        position["detected"] = "BTN"

    report_bytes = (json.dumps(report, indent=2) + "\n").encode()
    manifest["benchmark_reports"][0]["report_sha256"] = sha256(
        report_bytes
    ).hexdigest()
    modified = rebuild_archive(
        export.content,
        {
            report_name: report_bytes,
            "manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
        },
    )
    destination_dir = tmp_path / "destination"
    destination = make_client(destination_dir)

    response = restore_application_backup(destination, modified)

    assert response.status_code == 400
    assert "report" in response.json()["detail"]
    assert "is invalid" in response.json()["detail"]
    assert FileJobStore(destination_dir).list() == []
    assert FileBenchmarkStore(destination_dir).list(limit=None) == []


def test_restore_rejects_conflicting_existing_job_without_partial_import(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "source"
    source = make_client(source_dir)
    first_upload = source.post(
        "/api/jobs",
        files={"file": ("first.png", VALID_PNG, "image/png")},
        headers=ADMIN_OCR_TEST_HEADERS,
    )
    assert first_upload.status_code == 201
    first_job_id = first_upload.json()["id"]
    source_job_data = create_reviewed_job(source)
    source_job = FileJobStore(source_dir).get(str(source_job_data["id"]))
    export = source.get("/api/backups/export")

    destination_dir = tmp_path / "destination"
    conflicting_job = source_job.model_copy(
        update={"original_filename": "different.png"},
    )
    FileJobStore(destination_dir).restore(conflicting_job, VALID_PNG)
    destination = make_client(destination_dir)

    response = restore_application_backup(destination, export.content)

    assert response.status_code == 409
    assert "conflicts with existing data" in response.json()["detail"]
    assert FileJobStore(destination_dir).get(source_job.id) == conflicting_job
    assert not (destination_dir / "jobs" / first_job_id).exists()
    assert len(FileJobStore(destination_dir).list()) == 1
    assert FileBenchmarkStore(destination_dir).list(limit=None) == []


def test_restore_rejects_unexpected_archive_members(
    tmp_path: Path,
) -> None:
    source = make_client(tmp_path / "source")
    create_reviewed_job(source)
    export = source.get("/api/backups/export")
    unexpected = rebuild_archive(export.content, {})
    output = BytesIO()
    with ZipFile(BytesIO(unexpected)) as source_archive:
        with ZipFile(output, "w", compression=ZIP_DEFLATED) as target:
            for info in source_archive.infolist():
                target.writestr(info.filename, source_archive.read(info))
            target.writestr("../outside.txt", b"unexpected")
    destination = make_client(tmp_path / "destination")

    response = restore_application_backup(destination, output.getvalue())

    assert response.status_code == 400
    assert "missing or unexpected files" in response.json()["detail"]


def test_backup_size_limits_apply_to_export_and_restore(
    tmp_path: Path,
) -> None:
    source = make_client(
        tmp_path / "source",
        max_backup_upload_bytes=64,
    )
    upload = source.post(
        "/api/jobs",
        files={"file": ("table.png", VALID_PNG, "image/png")},
        headers=ADMIN_OCR_TEST_HEADERS,
    )
    assert upload.status_code == 201

    export = source.get("/api/backups/export")

    assert export.status_code == 409
    assert "configured 64-byte archive limit" in export.json()["detail"]

    destination = make_client(
        tmp_path / "destination",
        max_backup_upload_bytes=64,
    )
    response = restore_application_backup(destination, b"x" * 65)

    assert response.status_code == 413


def test_export_rejects_active_jobs_and_images_over_the_current_limit(
    tmp_path: Path,
) -> None:
    active_dir = tmp_path / "active"
    active = make_client(active_dir)
    upload = active.post(
        "/api/jobs",
        files={"file": ("table.png", VALID_PNG, "image/png")},
        headers=ADMIN_OCR_TEST_HEADERS,
    )
    assert upload.status_code == 201
    active_store = FileJobStore(active_dir)
    active_job = active_store.get(upload.json()["id"])
    active_job.status = "created"
    active_store.save(active_job)

    active_export = active.get("/api/backups/export")

    assert active_export.status_code == 409
    assert "Wait for active parsing" in active_export.json()["detail"]

    oversized_dir = tmp_path / "oversized"
    oversized_store = FileJobStore(oversized_dir)
    oversized_job = oversized_store.create_job(
        original_filename="large.png",
        image_bytes=VALID_PNG,
        parser_provider="mock",
    )
    oversized_job.status = "error"
    oversized_job.error = "Stored under an earlier upload limit"
    oversized_store.save(oversized_job)
    oversized = make_client(oversized_dir, max_upload_bytes=1)

    oversized_export = oversized.get("/api/backups/export")

    assert oversized_export.status_code == 409
    assert "Image exceeds the allowed size" in oversized_export.json()["detail"]


def test_restore_rejects_record_with_mismatched_job_id(
    tmp_path: Path,
) -> None:
    source = make_client(tmp_path / "source")
    source_job = create_reviewed_job(source)
    export = source.get("/api/backups/export")
    with ZipFile(BytesIO(export.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        record_name = f"jobs/{source_job['id']}/job.json"
        record = json.loads(archive.read(record_name))
    record["id"] = "0" * 32
    record_bytes = (json.dumps(record, indent=2) + "\n").encode()
    manifest["jobs"][0]["record_sha256"] = sha256(record_bytes).hexdigest()
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode()
    modified = rebuild_archive(
        export.content,
        {
            record_name: record_bytes,
            "manifest.json": manifest_bytes,
        },
    )
    destination = make_client(tmp_path / "destination")

    response = restore_application_backup(destination, modified)

    assert response.status_code == 400
    assert "job ID does not match" in response.json()["detail"]
    assert FileJobStore(tmp_path / "destination").list() == []
