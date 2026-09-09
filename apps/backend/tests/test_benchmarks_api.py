import json
import os
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Event, Thread
from zipfile import ZipFile

import pytest

import app.bootstrap as bootstrap_module
from app import dataset_export as dataset_export_module
from app import dataset_import as dataset_import_module
from app.config import Settings
from app.parsers.base import ParserConfigurationError, ParserError
from app.parsers.mock import MockParser
from app.storage.file_benchmark_store import FileBenchmarkStore
from app.storage.file_job_store import FileJobStore
from app.storage.persistence import BenchmarkImportNotFoundError, JobNotFoundError
from api_test_support import (
    APPROVED_STATE,
    VALID_PNG,
    approve_job,
    archive_with_unsupported_compression,
    import_benchmark_dataset,
    make_client,
    rebuild_zip_archive,
    upload_job,
    upload_job_with_pipeline,
)


def test_benchmark_requires_explicitly_approved_ground_truth(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]

    rejected = client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})

    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "Approve corrected state before adding it to the benchmark"
    overview = client.get("/api/benchmarks")
    assert overview.status_code == 200
    assert overview.json() == {
        "included_cases": 0,
        "included_cases_by_layout": {},
        "corpus_fingerprint": (
            "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
        ),
        "default_layout_profile": "generic",
        "latest_report": None,
        "recent_reports": [],
        "parser_pipelines": [
            {
                "parser": {
                    "id": "mock",
                    "label": "Mock parser",
                    "available": True,
                    "unavailable_reason": None,
                },
                "layout_profile": "generic",
                "latest_report": None,
                "previous_report": None,
            }
        ],
    }
    export = client.get("/api/benchmarks/export")
    assert export.status_code == 409
    assert export.json()["detail"] == "Add at least one approved hand to the benchmark"


def test_benchmark_exports_selected_images_and_approved_labels(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        parser_provider="mock",
        parser_layout_profile="fortuna",
    )
    included_id = upload_job(client, filename="included.png").json()["id"]
    excluded_id = upload_job(client, filename="excluded.png").json()["id"]
    corrected_state = {**APPROVED_STATE, "pot_size": 18.0}
    approve_job(client, included_id, corrected_state)
    approve_job(client, excluded_id)
    client.put(f"/api/jobs/{included_id}/benchmark", json={"included": True})

    response = client.get("/api/benchmarks/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="poker-hero-parser-dataset-'
    )
    with ZipFile(BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            f"images/{included_id}.png",
        }
        manifest = json.loads(archive.read("manifest.json"))
        assert archive.read(f"images/{included_id}.png") == VALID_PNG

    assert manifest["schema"] == "poker-hero-parser-dataset"
    assert manifest["schema_version"] == 1
    assert manifest["parser_provider"] == "mock"
    assert manifest["layout_profile"] == "fortuna"
    assert manifest["case_count"] == 1
    assert manifest["cases"] == [
        {
            "job_id": included_id,
            "original_filename": "included.png",
            "image_file": f"images/{included_id}.png",
            "expected_state": {
                key: value
                for key, value in corrected_state.items()
                if key != "user_approved"
            },
        }
    ]
    assert all(case["job_id"] != excluded_id for case in manifest["cases"])


def test_benchmark_case_limit_applies_to_selection_and_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path)
    first_id = upload_job(client, filename="first.png").json()["id"]
    second_id = upload_job(client, filename="second.png").json()["id"]
    approve_job(client, first_id)
    approve_job(client, second_id)
    monkeypatch.setattr(bootstrap_module, "MAX_DATASET_CASES", 1)

    first = client.put(f"/api/jobs/{first_id}/benchmark", json={"included": True})
    rejected = client.put(
        f"/api/jobs/{second_id}/benchmark",
        json={"included": True},
    )

    assert first.status_code == 200
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == "Parser datasets support at most 1 case"

    store = FileJobStore(tmp_path)
    second = store.get(second_id)
    second.benchmark_included = True
    store.save(second)
    monkeypatch.setattr(dataset_export_module, "MAX_DATASET_CASES", 1)

    export = client.get("/api/benchmarks/export")

    assert export.status_code == 409
    assert export.json()["detail"] == "Parser datasets support at most 1 case"


def test_benchmark_archive_limit_applies_to_selection_and_export(tmp_path: Path) -> None:
    archive_limit = 8_000
    client = make_client(tmp_path, max_dataset_upload_bytes=archive_limit)
    job_id = upload_job(client, content=VALID_PNG + os.urandom(9_000)).json()["id"]
    approve_job(client, job_id)

    selection = client.put(
        f"/api/jobs/{job_id}/benchmark",
        json={"included": True},
    )

    assert selection.status_code == 409
    assert selection.json()["detail"] == (
        f"Parser dataset exceeds the configured {archive_limit}-byte archive limit"
    )
    store = FileJobStore(tmp_path)
    job = store.get(job_id)
    assert job.benchmark_included is False

    job.benchmark_included = True
    store.save(job)
    export = client.get("/api/benchmarks/export")

    assert export.status_code == 409
    assert export.json()["detail"] == selection.json()["detail"]


def test_benchmark_export_reports_missing_source_image(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client, filename="missing.png").json()["id"]
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    store = FileJobStore(tmp_path)
    store.image_path(store.get(job_id)).unlink()

    response = client.get("/api/benchmarks/export")

    assert response.status_code == 409
    assert response.json()["detail"] == "Image is unavailable for missing.png"


def test_benchmark_dataset_import_round_trips_and_reuses_existing_cases(
    tmp_path: Path,
) -> None:
    source_client = make_client(tmp_path / "source", parser_layout_profile="fortuna")
    source_job_id = upload_job(source_client, filename="labeled.tmp").json()["id"]
    corrected_state = {**APPROVED_STATE, "pot_size": 18.0}
    approve_job(source_client, source_job_id, corrected_state)
    source_client.put(
        f"/api/jobs/{source_job_id}/benchmark",
        json={"included": True},
    )
    archive = source_client.get("/api/benchmarks/export").content
    target_dir = tmp_path / "target"
    target_client = make_client(target_dir)

    imported = import_benchmark_dataset(target_client, archive)
    repeated = import_benchmark_dataset(target_client, archive)

    assert imported.status_code == 200
    assert imported.json() == {
        "imported_cases": 1,
        "reused_cases": 0,
        "included_cases": 1,
        "included_cases_by_layout": {"fortuna": 1},
        "job_ids": [source_job_id],
    }
    assert repeated.status_code == 200
    assert repeated.json() == {
        "imported_cases": 0,
        "reused_cases": 1,
        "included_cases": 1,
        "included_cases_by_layout": {"fortuna": 1},
        "job_ids": [source_job_id],
    }
    imported_job = FileJobStore(target_dir).get(source_job_id)
    assert imported_job.original_filename == "labeled.tmp"
    assert imported_job.approved_state is not None
    assert imported_job.approved_state.model_dump(mode="json", exclude_none=True) == {
        **corrected_state,
        "preflop_action_history": [],
        "postflop_action_history": [],
    }
    assert imported_job.benchmark_included is True
    assert imported_job.status == "approved"
    assert imported_job.parser_result is None
    assert FileJobStore(target_dir).image_path(imported_job).read_bytes() == VALID_PNG


def test_benchmark_dataset_import_rejects_cross_layout_job_reuse(
    tmp_path: Path,
) -> None:
    source_client = make_client(tmp_path / "source")
    job_id = upload_job(source_client, filename="layout-label.png").json()["id"]
    approve_job(source_client, job_id)
    source_client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    archive = source_client.get("/api/benchmarks/export").content
    with ZipFile(BytesIO(archive)) as dataset:
        manifest = json.loads(dataset.read("manifest.json"))
    manifest["layout_profile"] = "pokerstars"
    cross_layout_archive = rebuild_zip_archive(
        archive,
        {"manifest.json": json.dumps(manifest).encode()},
    )
    target_dir = tmp_path / "target"
    target_client = make_client(target_dir)
    imported = import_benchmark_dataset(target_client, archive)

    response = import_benchmark_dataset(target_client, cross_layout_archive)

    assert imported.status_code == 200
    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"Imported case {job_id} conflicts with an existing job"
    )
    existing = FileJobStore(target_dir).get(job_id)
    assert existing.parser_layout_profile == "generic"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("case_count", "1"),
        ("case_count", 1.0),
    ],
)
def test_benchmark_dataset_import_rejects_coerced_manifest_integers(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    source_client = make_client(tmp_path / "source")
    source_job_id = upload_job(source_client).json()["id"]
    approve_job(source_client, source_job_id)
    source_client.put(
        f"/api/jobs/{source_job_id}/benchmark",
        json={"included": True},
    )
    archive = source_client.get("/api/benchmarks/export").content
    with ZipFile(BytesIO(archive)) as dataset:
        manifest = json.loads(dataset.read("manifest.json"))
    manifest[field_name] = value
    modified = rebuild_zip_archive(
        archive,
        {
            "manifest.json": (
                json.dumps(manifest, indent=2) + "\n"
            ).encode(),
        },
    )
    target_dir = tmp_path / "target"
    target_client = make_client(target_dir)

    response = import_benchmark_dataset(target_client, modified)

    assert response.status_code == 400
    assert f"invalid at {field_name}" in response.json()["detail"]
    assert FileJobStore(target_dir).list() == []


def test_benchmark_dataset_import_persists_request_receipt_for_recovery(
    tmp_path: Path,
) -> None:
    source_client = make_client(tmp_path / "source")
    source_job_id = upload_job(source_client, filename="recoverable.png").json()["id"]
    approve_job(source_client, source_job_id)
    source_client.put(
        f"/api/jobs/{source_job_id}/benchmark",
        json={"included": True},
    )
    archive = source_client.get("/api/benchmarks/export").content
    target_dir = tmp_path / "target"
    target_client = make_client(target_dir)
    request_id = "benchmark-import-request-123"

    imported = import_benchmark_dataset(target_client, archive, request_id=request_id)
    recovered = target_client.get(f"/api/benchmarks/imports/{request_id}")
    repeated = import_benchmark_dataset(target_client, archive, request_id=request_id)
    missing = target_client.get("/api/benchmarks/imports/unknown-request")

    assert imported.status_code == 200
    assert imported.json() == {
        "imported_cases": 1,
        "reused_cases": 0,
        "included_cases": 1,
        "included_cases_by_layout": {"generic": 1},
        "job_ids": [source_job_id],
    }
    assert recovered.status_code == 200
    assert recovered.json() == {
        "request_id": request_id,
        "archive_sha256": sha256(archive).hexdigest(),
        "status": "completed",
        "result": imported.json(),
        "error": None,
        "error_status": None,
    }
    assert repeated.status_code == 200
    assert repeated.json() == imported.json()
    imported_job = FileJobStore(target_dir).get(source_job_id)
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Benchmark dataset import not found"


@pytest.mark.parametrize("request_id", [".", ".."])
def test_benchmark_dataset_import_rejects_dot_segment_request_ids(
    tmp_path: Path,
    request_id: str,
) -> None:
    client = make_client(tmp_path)

    response = import_benchmark_dataset(client, b"not a zip", request_id=request_id)
    benchmark_store = FileBenchmarkStore(tmp_path)

    assert response.status_code == 422
    assert list(benchmark_store.imports_dir.iterdir()) == []
    with pytest.raises(BenchmarkImportNotFoundError):
        benchmark_store.begin_import(request_id, b"dataset")


def test_benchmark_dataset_import_blocks_runs_until_partial_case_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_client = make_client(tmp_path / "source")
    source_job_id = upload_job(source_client, filename="interrupted.png").json()["id"]
    approve_job(source_client, source_job_id)
    source_client.put(
        f"/api/jobs/{source_job_id}/benchmark",
        json={"included": True},
    )
    archive = source_client.get("/api/benchmarks/export").content
    target_dir = tmp_path / "target"
    target_client = make_client(target_dir)
    request_id = "interrupted-import-request"
    original_write_image = FileJobStore.write_image
    interrupted = False

    def interrupt_first_import_image(
        self: FileJobStore,
        job,
        image_bytes: bytes,
    ) -> None:
        nonlocal interrupted
        if (
            not interrupted
            and job.benchmark_import_request_id == request_id
        ):
            interrupted = True
            raise OSError("simulated process interruption")
        original_write_image(self, job, image_bytes)

    monkeypatch.setattr(FileJobStore, "write_image", interrupt_first_import_image)
    with pytest.raises(OSError, match="simulated process interruption"):
        import_benchmark_dataset(target_client, archive, request_id=request_id)

    interrupted_store = FileJobStore(target_dir)
    partial_job = interrupted_store.get(source_job_id)
    assert partial_job.benchmark_import_request_id == request_id
    assert not interrupted_store.image_path(partial_job).exists()
    assert FileBenchmarkStore(target_dir).get_import(request_id).status == "pending"

    monkeypatch.setattr(FileJobStore, "write_image", original_write_image)
    recovery_client = make_client(target_dir)
    blocked_run = recovery_client.post("/api/benchmarks/run")
    blocked_export = recovery_client.get("/api/benchmarks/export")
    blocked_inclusion = recovery_client.put(
        f"/api/jobs/{source_job_id}/benchmark",
        json={"included": False},
    )
    blocked_import = import_benchmark_dataset(
        recovery_client,
        archive,
        request_id="second-pending-import",
    )

    assert blocked_run.status_code == 409
    assert blocked_run.json()["detail"] == "A benchmark dataset import is still pending"
    assert blocked_export.status_code == 409
    assert blocked_export.json()["detail"] == "A benchmark dataset import is still pending"
    assert blocked_inclusion.status_code == 409
    assert blocked_inclusion.json()["detail"] == (
        "A benchmark dataset import is still pending"
    )
    assert blocked_import.status_code == 409
    assert blocked_import.json()["detail"] == (
        "A benchmark dataset import is still pending"
    )
    with pytest.raises(BenchmarkImportNotFoundError):
        FileBenchmarkStore(target_dir).get_import("second-pending-import")
    assert FileBenchmarkStore(target_dir).get_latest() is None

    pending = recovery_client.get(f"/api/benchmarks/imports/{request_id}")
    completed = recovery_client.get(f"/api/benchmarks/imports/{request_id}")
    recovered_run = recovery_client.post("/api/benchmarks/run")

    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["result"] == {
        "imported_cases": 1,
        "reused_cases": 0,
        "included_cases": 1,
        "included_cases_by_layout": {"generic": 1},
        "job_ids": [source_job_id],
    }
    assert recovered_run.status_code == 200
    assert recovered_run.json()["total_cases"] == 1
    assert recovered_run.json()["cases"][0]["job_id"] == source_job_id
    recovered_job = FileJobStore(target_dir).get(source_job_id)
    assert FileJobStore(target_dir).image_path(recovered_job).read_bytes() == VALID_PNG


def test_benchmark_dataset_import_journals_before_parsing_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_client = make_client(tmp_path / "source")
    source_job_id = upload_job(source_client, filename="parse-interrupted.png").json()[
        "id"
    ]
    approve_job(source_client, source_job_id)
    source_client.put(
        f"/api/jobs/{source_job_id}/benchmark",
        json={"included": True},
    )
    archive = source_client.get("/api/benchmarks/export").content
    target_dir = tmp_path / "target"
    target_client = make_client(target_dir)
    request_id = "parse-interrupted-import"
    parse_entered = Event()
    release_parse = Event()
    import_errors: list[Exception] = []
    original_parse = bootstrap_module.parse_parser_dataset_archive

    def interrupt_parse(*args: object, **kwargs: object):
        parse_entered.set()
        assert release_parse.wait(timeout=2)
        raise OSError("simulated interruption during dataset parsing")

    monkeypatch.setattr(bootstrap_module, "parse_parser_dataset_archive", interrupt_parse)

    def run_import() -> None:
        try:
            import_benchmark_dataset(target_client, archive, request_id=request_id)
        except Exception as exc:
            import_errors.append(exc)

    import_thread = Thread(target=run_import)
    import_thread.start()
    assert parse_entered.wait(timeout=2)

    benchmark_store = FileBenchmarkStore(target_dir)
    assert benchmark_store.get_import(request_id).status == "pending"
    assert benchmark_store.get_import_archive(request_id) == archive

    release_parse.set()
    import_thread.join(timeout=2)
    assert not import_thread.is_alive()
    assert len(import_errors) == 1
    assert isinstance(import_errors[0], OSError)

    monkeypatch.setattr(
        bootstrap_module,
        "parse_parser_dataset_archive",
        original_parse,
    )
    recovery_client = make_client(target_dir)
    pending = recovery_client.get(f"/api/benchmarks/imports/{request_id}")
    completed = recovery_client.get(f"/api/benchmarks/imports/{request_id}")

    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["result"]["job_ids"] == [source_job_id]


def test_benchmark_dataset_import_persists_validation_failure_receipt(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    request_id = "invalid-archive-import"

    response = import_benchmark_dataset(client, b"not a zip", request_id=request_id)
    receipt = client.get(f"/api/benchmarks/imports/{request_id}")
    repeated = import_benchmark_dataset(client, b"not a zip", request_id=request_id)

    assert response.status_code == 400
    assert response.json()["detail"] == "Upload must be a valid dataset ZIP"
    assert receipt.status_code == 200
    assert receipt.json() == {
        "request_id": request_id,
        "archive_sha256": sha256(b"not a zip").hexdigest(),
        "status": "failed",
        "result": None,
        "error": "Upload must be a valid dataset ZIP",
        "error_status": 400,
    }
    assert repeated.status_code == 400
    assert repeated.json()["detail"] == "Upload must be a valid dataset ZIP"


def test_benchmark_dataset_import_rejects_unsupported_compression(
    tmp_path: Path,
) -> None:
    source_client = make_client(tmp_path / "source")
    source_job_id = upload_job(source_client).json()["id"]
    approve_job(source_client, source_job_id)
    source_client.put(
        f"/api/jobs/{source_job_id}/benchmark",
        json={"included": True},
    )
    archive = source_client.get("/api/benchmarks/export").content
    unsupported_archive = archive_with_unsupported_compression(archive)

    response = import_benchmark_dataset(
        make_client(tmp_path / "target"),
        unsupported_archive,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Dataset ZIP uses an unsupported compression method"
    )


def test_benchmark_import_recovery_fails_unsupported_compression_receipt(
    tmp_path: Path,
) -> None:
    source_client = make_client(tmp_path / "source")
    source_job_id = upload_job(source_client).json()["id"]
    approve_job(source_client, source_job_id)
    source_client.put(
        f"/api/jobs/{source_job_id}/benchmark",
        json={"included": True},
    )
    archive = source_client.get("/api/benchmarks/export").content
    unsupported_archive = archive_with_unsupported_compression(archive)

    target_dir = tmp_path / "target"
    target_client = make_client(target_dir)
    existing_job_id = upload_job(target_client).json()["id"]
    approve_job(target_client, existing_job_id)
    target_client.put(
        f"/api/jobs/{existing_job_id}/benchmark",
        json={"included": True},
    )
    request_id = "unsupported-compression-import"
    benchmark_store = FileBenchmarkStore(target_dir)
    benchmark_store.begin_import(request_id, unsupported_archive)

    recovery_client = make_client(target_dir)
    pending = recovery_client.get(f"/api/benchmarks/imports/{request_id}")
    failed = recovery_client.get(f"/api/benchmarks/imports/{request_id}")
    recovered_run = recovery_client.post("/api/benchmarks/run")

    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["error"] == (
        "Dataset ZIP uses an unsupported compression method"
    )
    assert failed.json()["error_status"] == 400
    with pytest.raises(BenchmarkImportNotFoundError):
        benchmark_store.get_import_archive(request_id)
    assert recovered_run.status_code == 200
    assert recovered_run.json()["total_cases"] == 1
    assert recovered_run.json()["cases"][0]["job_id"] == existing_job_id


def test_benchmark_dataset_import_rejects_conflicts_without_overwriting(
    tmp_path: Path,
) -> None:
    source_client = make_client(tmp_path / "source")
    job_id = upload_job(source_client, filename="conflict.png").json()["id"]
    approve_job(source_client, job_id)
    source_client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    archive = source_client.get("/api/benchmarks/export").content
    target_dir = tmp_path / "target"
    target_client = make_client(target_dir)
    import_benchmark_dataset(target_client, archive)
    changed_state = {**APPROVED_STATE, "pot_size": 20.0}
    approve_job(target_client, job_id, changed_state)

    response = import_benchmark_dataset(target_client, archive)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"Imported case {job_id} conflicts with an existing job"
    )
    existing = FileJobStore(target_dir).get(job_id)
    assert existing.approved_state is not None
    assert existing.approved_state.pot_size == 20


def test_benchmark_dataset_import_enforces_resulting_corpus_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_client = make_client(tmp_path / "source")
    source_job_id = upload_job(source_client, filename="source.png").json()["id"]
    approve_job(source_client, source_job_id)
    source_client.put(
        f"/api/jobs/{source_job_id}/benchmark",
        json={"included": True},
    )
    archive = source_client.get("/api/benchmarks/export").content

    target_client = make_client(tmp_path / "target")
    target_job_id = upload_job(target_client, filename="target.png").json()["id"]
    approve_job(target_client, target_job_id)
    target_client.put(
        f"/api/jobs/{target_job_id}/benchmark",
        json={"included": True},
    )
    monkeypatch.setattr(dataset_import_module, "MAX_DATASET_CASES", 1)

    response = import_benchmark_dataset(target_client, archive)

    assert response.status_code == 409
    assert response.json()["detail"] == "Parser datasets support at most 1 case"
    assert FileJobStore(tmp_path / "target").get(target_job_id).benchmark_included is True


def test_benchmark_dataset_import_serializes_reuse_with_corrections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client, filename="concurrent.png").json()["id"]
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    archive = client.get("/api/benchmarks/export").content
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": False})

    import_entered = Event()
    release_import = Event()
    approval_started = Event()
    approval_finished = Event()
    responses: dict[str, object] = {}
    original_import = bootstrap_module.import_parser_dataset

    def paused_import(*args: object, **kwargs: object):
        import_entered.set()
        assert release_import.wait(timeout=2)
        return original_import(*args, **kwargs)

    monkeypatch.setattr(bootstrap_module, "import_parser_dataset", paused_import)

    def run_import() -> None:
        responses["import"] = import_benchmark_dataset(client, archive)

    corrected_state = {**APPROVED_STATE, "pot_size": 21.0}

    def run_approval() -> None:
        approval_started.set()
        responses["approval"] = approve_job(client, job_id, corrected_state)
        approval_finished.set()

    import_thread = Thread(target=run_import)
    import_thread.start()
    assert import_entered.wait(timeout=2)

    approval_thread = Thread(target=run_approval)
    approval_thread.start()
    assert approval_started.wait(timeout=2)
    assert not approval_finished.wait(timeout=0.1)

    release_import.set()
    import_thread.join(timeout=2)
    approval_thread.join(timeout=2)

    assert not import_thread.is_alive()
    assert not approval_thread.is_alive()
    assert responses["import"].status_code == 200
    assert responses["approval"].status_code == 200
    current = FileJobStore(tmp_path).get(job_id)
    assert current.approved_state is not None
    assert current.approved_state.pot_size == 21
    assert current.benchmark_included is True


def test_benchmark_run_waits_for_dataset_import_corpus_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_client = make_client(tmp_path / "source")
    source_job_id = upload_job(
        source_client,
        filename="imported-during-run.png",
    ).json()["id"]
    approve_job(source_client, source_job_id)
    source_client.put(
        f"/api/jobs/{source_job_id}/benchmark",
        json={"included": True},
    )
    archive = source_client.get("/api/benchmarks/export").content

    target_client = make_client(tmp_path / "target")
    target_job_id = upload_job(
        target_client,
        filename="existing-before-run.png",
    ).json()["id"]
    approve_job(target_client, target_job_id)
    target_client.put(
        f"/api/jobs/{target_job_id}/benchmark",
        json={"included": True},
    )

    import_entered = Event()
    release_import = Event()
    benchmark_started = Event()
    benchmark_finished = Event()
    responses: dict[str, object] = {}
    original_import = bootstrap_module.import_parser_dataset

    def paused_import(*args: object, **kwargs: object):
        import_entered.set()
        assert release_import.wait(timeout=2)
        return original_import(*args, **kwargs)

    monkeypatch.setattr(bootstrap_module, "import_parser_dataset", paused_import)

    import_thread = Thread(
        target=lambda: responses.update(
            imported=import_benchmark_dataset(target_client, archive),
        ),
    )

    def run_benchmark_request() -> None:
        benchmark_started.set()
        responses["benchmark"] = target_client.post("/api/benchmarks/run")
        benchmark_finished.set()

    benchmark_thread = Thread(target=run_benchmark_request)
    import_thread.start()
    try:
        assert import_entered.wait(timeout=2)
        benchmark_thread.start()
        assert benchmark_started.wait(timeout=2)
        assert not benchmark_finished.wait(timeout=0.1)
    finally:
        release_import.set()
        import_thread.join(timeout=2)
        benchmark_thread.join(timeout=2)

    assert not import_thread.is_alive()
    assert not benchmark_thread.is_alive()
    assert responses["imported"].status_code == 200
    assert responses["benchmark"].status_code == 200
    assert responses["benchmark"].json()["total_cases"] == 2
    assert {
        case["job_id"] for case in responses["benchmark"].json()["cases"]
    } == {target_job_id, source_job_id}


def test_unrelated_approval_does_not_wait_for_benchmark_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path)
    benchmark_job_id = upload_job(client, filename="benchmark.png").json()["id"]
    approve_job(client, benchmark_job_id)
    client.put(
        f"/api/jobs/{benchmark_job_id}/benchmark",
        json={"included": True},
    )
    unrelated_job_id = upload_job(client, filename="unrelated.png").json()["id"]
    approve_job(client, unrelated_job_id)

    benchmark_entered = Event()
    release_benchmark = Event()
    approval_finished = Event()
    responses: dict[str, object] = {}
    original_run = bootstrap_module.run_benchmark

    def paused_run(*args: object, **kwargs: object):
        benchmark_entered.set()
        assert release_benchmark.wait(timeout=2)
        return original_run(*args, **kwargs)

    monkeypatch.setattr(bootstrap_module, "run_benchmark", paused_run)

    benchmark_thread = Thread(
        target=lambda: responses.update(
            benchmark=client.post("/api/benchmarks/run"),
        ),
    )

    def run_approval() -> None:
        responses["approval"] = approve_job(
            client,
            unrelated_job_id,
            {**APPROVED_STATE, "pot_size": 21.0},
        )
        approval_finished.set()

    approval_thread = Thread(target=run_approval)
    benchmark_thread.start()
    try:
        assert benchmark_entered.wait(timeout=2)
        approval_thread.start()
        assert approval_finished.wait(timeout=1)
    finally:
        release_benchmark.set()
        benchmark_thread.join(timeout=2)
        approval_thread.join(timeout=2)

    assert not benchmark_thread.is_alive()
    assert not approval_thread.is_alive()
    assert responses["benchmark"].status_code == 200
    assert responses["approval"].status_code == 200
    approved_state = FileJobStore(tmp_path).get(unrelated_job_id).approved_state
    assert approved_state is not None
    assert approved_state.pot_size == 21


def test_benchmark_dataset_import_rejects_invalid_and_oversized_archives(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path / "invalid")
    invalid = import_benchmark_dataset(client, b"not a zip")

    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "Upload must be a valid dataset ZIP"

    source_client = make_client(tmp_path / "source")
    job_id = upload_job(source_client).json()["id"]
    approve_job(source_client, job_id)
    source_client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    archive = source_client.get("/api/benchmarks/export").content
    limited_client = make_client(
        tmp_path / "limited",
        max_dataset_upload_bytes=len(archive) - 1,
    )

    oversized = import_benchmark_dataset(limited_client, archive)

    assert oversized.status_code == 413
    assert oversized.json()["detail"] == "Dataset ZIP exceeds maximum size"


def test_benchmark_dataset_import_rejects_a_combined_corpus_over_archive_limit(
    tmp_path: Path,
) -> None:
    source_client = make_client(tmp_path / "source")
    imported_id = upload_job(
        source_client,
        content=VALID_PNG + os.urandom(9_000),
        filename="imported.png",
    ).json()["id"]
    approve_job(source_client, imported_id)
    source_client.put(
        f"/api/jobs/{imported_id}/benchmark",
        json={"included": True},
    )
    archive = source_client.get("/api/benchmarks/export").content
    archive_limit = len(archive) * 3 // 2

    target_dir = tmp_path / "target"
    target_client = make_client(
        target_dir,
        max_dataset_upload_bytes=archive_limit,
    )
    existing_id = upload_job(
        target_client,
        content=VALID_PNG + os.urandom(9_000),
        filename="existing.png",
    ).json()["id"]
    approve_job(target_client, existing_id)
    inclusion = target_client.put(
        f"/api/jobs/{existing_id}/benchmark",
        json={"included": True},
    )
    assert inclusion.status_code == 200

    imported = import_benchmark_dataset(target_client, archive)

    assert imported.status_code == 409
    assert imported.json()["detail"] == (
        f"Parser dataset exceeds the configured {archive_limit}-byte archive limit"
    )
    target_store = FileJobStore(target_dir)
    assert target_store.get(existing_id).benchmark_included is True
    with pytest.raises(JobNotFoundError):
        target_store.get(imported_id)


def test_benchmark_dataset_import_rejects_unsafe_image_paths(tmp_path: Path) -> None:
    source_client = make_client(tmp_path / "source")
    job_id = upload_job(source_client).json()["id"]
    approve_job(source_client, job_id)
    source_client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    exported = source_client.get("/api/benchmarks/export").content
    with ZipFile(BytesIO(exported)) as source_archive:
        manifest = json.loads(source_archive.read("manifest.json"))
        image_name = manifest["cases"][0]["image_file"]
        image_bytes = source_archive.read(image_name)
    manifest["cases"][0]["image_file"] = f"../{job_id}.png"
    unsafe_buffer = BytesIO()
    with ZipFile(unsafe_buffer, mode="w") as unsafe_archive:
        unsafe_archive.writestr("manifest.json", json.dumps(manifest))
        unsafe_archive.writestr(f"../{job_id}.png", image_bytes)

    response = import_benchmark_dataset(
        make_client(tmp_path / "target"),
        unsafe_buffer.getvalue(),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Dataset image path is invalid for table.png"


def test_benchmark_scores_active_parser_and_persists_latest_report(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    inclusion = client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    report_response = client.post("/api/benchmarks/run")

    assert inclusion.status_code == 200
    assert inclusion.json()["benchmark_included"] is True
    assert report_response.status_code == 200
    report = report_response.json()
    assert report["parser_provider"] == "mock"
    assert report["total_cases"] == 1
    assert report["successful_cases"] == 1
    assert report["failed_cases"] == 0
    assert report["accuracy"] == 1
    assert len(report["corpus_fingerprint"]) == 64
    assert report["correct_fields"] == report["evaluated_fields"]
    assert {metric["field"] for metric in report["field_metrics"]} == set(APPROVED_STATE) - {
        "user_approved"
    }
    assert FileBenchmarkStore(tmp_path).get_latest().id == report["id"]
    summary_path = tmp_path / "benchmarks" / f"{report['id']}.summary.json"
    assert summary_path.exists()
    summary_path.write_text("not valid JSON")
    overview = client.get("/api/benchmarks").json()
    assert overview["latest_report"]["id"] == report["id"]
    assert overview["corpus_fingerprint"] == report["corpus_fingerprint"]
    assert json.loads(summary_path.read_text())["id"] == report["id"]
    mismatched_summary = json.loads(summary_path.read_text())
    mismatched_summary["id"] = "f" * 32
    summary_path.write_text(json.dumps(mismatched_summary))
    overview = client.get("/api/benchmarks").json()
    assert overview["latest_report"]["id"] == report["id"]
    assert json.loads(summary_path.read_text())["id"] == report["id"]
    summary_path.unlink()
    overview = client.get("/api/benchmarks").json()
    assert summary_path.exists()
    assert overview["latest_report"]["id"] == report["id"]

    assert overview["recent_reports"] == [
        {
            "id": report["id"],
            "parser_provider": "mock",
            "layout_profile": "generic",
            "created_at": report["created_at"],
            "total_cases": 1,
            "failed_cases": 0,
            "accuracy": 1.0,
            "field_metrics": report["field_metrics"],
            "corpus_fingerprint": report["corpus_fingerprint"],
        }
    ]

    correction = approve_job(
        client,
        job_id,
        {**APPROVED_STATE, "pot_size": 18.0},
    )
    assert correction.status_code == 200
    changed_overview = client.get("/api/benchmarks").json()
    assert changed_overview["corpus_fingerprint"] != report["corpus_fingerprint"]
    assert (
        changed_overview["latest_report"]["corpus_fingerprint"]
        == report["corpus_fingerprint"]
    )


def test_benchmark_overview_reads_legacy_report_without_corpus_fingerprint(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    report = client.post("/api/benchmarks/run").json()
    report_path = tmp_path / "benchmarks" / f"{report['id']}.json"
    summary_path = tmp_path / "benchmarks" / f"{report['id']}.summary.json"
    legacy_payload = json.loads(report_path.read_text())
    legacy_payload.pop("corpus_fingerprint")
    report_path.write_text(json.dumps(legacy_payload))
    summary_path.unlink()

    overview = client.get("/api/benchmarks")

    assert overview.status_code == 200
    assert overview.json()["corpus_fingerprint"] == report["corpus_fingerprint"]
    assert overview.json()["latest_report"]["corpus_fingerprint"] is None
    assert overview.json()["recent_reports"][0]["corpus_fingerprint"] is None
    assert json.loads(summary_path.read_text())["corpus_fingerprint"] is None


def test_benchmark_overview_streams_legacy_summary_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(
        tmp_path,
        api_rate_limit_benchmarks_per_minute=20,
    )
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    for _ in range(12):
        assert client.post("/api/benchmarks/run").status_code == 200

    for summary_path in (tmp_path / "benchmarks").glob("*.summary.json"):
        summary_path.unlink()
    original_read_text = Path.read_text
    full_report_reads: list[str] = []

    def track_benchmark_reads(path: Path, *args, **kwargs) -> str:
        if (
            path.parent == tmp_path / "benchmarks"
            and path.suffix == ".json"
            and len(path.stem) == 32
        ):
            full_report_reads.append(path.stem)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", track_benchmark_reads)

    first_overview = client.get("/api/benchmarks")

    assert first_overview.status_code == 200
    assert len(first_overview.json()["recent_reports"]) == 10
    assert len(list((tmp_path / "benchmarks").glob("*.summary.json"))) == 10
    assert len(full_report_reads) == 1

    full_report_reads.clear()
    second_overview = client.get("/api/benchmarks")

    assert second_overview.status_code == 200
    assert len(second_overview.json()["recent_reports"]) == 10
    assert len(list((tmp_path / "benchmarks").glob("*.summary.json"))) == 10
    assert len(full_report_reads) == 1


def test_benchmark_overview_rescans_after_a_concurrent_legacy_backfill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    report = client.post("/api/benchmarks/run").json()
    summary_path = tmp_path / "benchmarks" / f"{report['id']}.summary.json"
    summary_path.unlink()
    requesting_store = FileBenchmarkStore(tmp_path)
    concurrent_store = FileBenchmarkStore(tmp_path)

    def run_concurrent_backfill(**_kwargs) -> None:
        concurrent_store.list_summaries(
            parser_provider="mock",
            layout_profile="generic",
        )

    monkeypatch.setattr(
        requesting_store,
        "_backfill_report_summaries",
        run_concurrent_backfill,
    )

    summaries = requesting_store.list_summaries(
        parser_provider="mock",
        layout_profile="generic",
    )

    assert [summary.id for summary in summaries] == [report["id"]]
    assert summary_path.exists()


def test_benchmark_overview_recovers_only_unindexed_reports_newer_than_history(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        api_rate_limit_benchmarks_per_minute=20,
    )
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    reports = [client.post("/api/benchmarks/run").json() for _ in range(12)]
    reports.sort(key=lambda report: (report["created_at"], report["id"]))
    oldest_summary_path = (
        tmp_path / "benchmarks" / f"{reports[0]['id']}.summary.json"
    )
    newest_summary_path = (
        tmp_path / "benchmarks" / f"{reports[-1]['id']}.summary.json"
    )
    oldest_summary_path.unlink()
    newest_summary_path.unlink()

    overview = client.get("/api/benchmarks")

    assert overview.status_code == 200
    assert overview.json()["recent_reports"][0]["id"] == reports[-1]["id"]
    assert len(overview.json()["recent_reports"]) == 10
    assert newest_summary_path.exists()
    assert not oldest_summary_path.exists()


def test_benchmark_overview_compares_compatible_parser_plugins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(
        tmp_path,
        parser_enabled_providers=["llm_vision", "ocr_cv"],
        parser_enabled_layout_profiles=["fortuna_nations"],
        external_parser_url="https://parser.example/api",
    )
    monkeypatch.setattr(bootstrap_module, "build_parser", lambda _settings: MockParser())
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    mock_report = client.post("/api/benchmarks/run").json()
    vision_report = client.post(
        "/api/benchmarks/run",
        json={
            "parser_provider": "llm_vision",
            "parser_layout_profile": "generic",
        },
    ).json()

    generic_overview = client.get("/api/benchmarks").json()
    fortuna_overview = client.get(
        "/api/benchmarks",
        params={
            "parser_provider": "mock",
            "parser_layout_profile": "fortuna_nations",
        },
    ).json()

    assert [
        pipeline["parser"]["id"]
        for pipeline in generic_overview["parser_pipelines"]
    ] == ["mock", "llm_vision", "ocr_cv"]
    assert [
        pipeline["latest_report"]["id"]
        if pipeline["latest_report"] is not None
        else None
        for pipeline in generic_overview["parser_pipelines"]
    ] == [mock_report["id"], vision_report["id"], None]
    assert [
        pipeline["parser"]["id"]
        for pipeline in fortuna_overview["parser_pipelines"]
    ] == ["mock", "llm_vision", "ocr_cv"]
    assert all(
        pipeline["latest_report"] is None
        for pipeline in fortuna_overview["parser_pipelines"]
    )


def test_benchmark_pipeline_compares_only_same_corpus_runs(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        api_rate_limit_benchmarks_per_minute=20,
    )
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})

    first_report = client.post("/api/benchmarks/run").json()
    second_report = client.post("/api/benchmarks/run").json()
    pipeline = client.get("/api/benchmarks").json()["parser_pipelines"][0]

    assert pipeline["latest_report"]["id"] == second_report["id"]
    assert pipeline["previous_report"]["id"] == first_report["id"]

    approve_job(
        client,
        job_id,
        {**APPROVED_STATE, "pot_size": 18.0},
    )
    changed_report = client.post("/api/benchmarks/run").json()
    changed_pipeline = client.get("/api/benchmarks").json()[
        "parser_pipelines"
    ][0]

    assert changed_pipeline["latest_report"]["id"] == changed_report["id"]
    assert changed_pipeline["previous_report"] is None


def test_benchmark_pipeline_finds_same_corpus_run_beyond_recent_history(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        api_rate_limit_benchmarks_per_minute=40,
    )
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    first_report = client.post("/api/benchmarks/run").json()

    for pot_size in range(20, 30):
        approve_job(
            client,
            job_id,
            {**APPROVED_STATE, "pot_size": float(pot_size)},
        )
        assert client.post("/api/benchmarks/run").status_code == 200

    first_summary_path = (
        tmp_path / "benchmarks" / f"{first_report['id']}.summary.json"
    )
    first_summary_path.unlink()
    approve_job(client, job_id)
    latest_report = client.post("/api/benchmarks/run").json()
    overview = client.get("/api/benchmarks").json()
    pipeline = overview["parser_pipelines"][0]

    assert len(overview["recent_reports"]) == 10
    assert first_report["id"] not in {
        report["id"] for report in overview["recent_reports"]
    }
    assert pipeline["latest_report"]["id"] == latest_report["id"]
    assert pipeline["previous_report"]["id"] == first_report["id"]
    assert not first_summary_path.exists()


def test_benchmark_scores_an_enabled_selected_parser_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(
        tmp_path,
        parser_enabled_providers=["ocr_cv"],
        parser_enabled_layout_profiles=["fortuna_nations"],
    )
    job_id = upload_job(client).json()["id"]
    store = FileJobStore(tmp_path)
    labeled_job = store.get(job_id)
    labeled_job.parser_layout_profile = "fortuna_nations"
    store.save(labeled_job)
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    parser_settings: list[Settings] = []

    def build_selected_parser(settings: Settings) -> MockParser:
        parser_settings.append(settings)
        return MockParser()

    monkeypatch.setattr(bootstrap_module, "build_parser", build_selected_parser)

    response = client.post(
        "/api/benchmarks/run",
        json={
            "parser_provider": "ocr_cv",
            "parser_layout_profile": "fortuna_nations",
        },
    )

    assert response.status_code == 200
    report = response.json()
    assert report["parser_provider"] == "ocr_cv"
    assert report["layout_profile"] == "fortuna_nations"
    assert report["accuracy"] == 1
    assert len(parser_settings) == 1
    assert parser_settings[0].parser_provider == "ocr_cv"
    assert parser_settings[0].parser_layout_profile == "fortuna_nations"


def test_benchmark_runs_and_exports_layout_corpora_independently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(
        tmp_path,
        parser_enabled_providers=["ocr_cv"],
        parser_enabled_layout_profiles=["pokerstars"],
    )
    monkeypatch.setattr(bootstrap_module, "build_parser", lambda _settings: MockParser())
    generic_id = upload_job(client, filename="generic.png").json()["id"]
    store = FileJobStore(tmp_path)
    legacy_generic = store.get(generic_id)
    legacy_generic.parser_layout_profile = None
    store.save(legacy_generic)
    pokerstars_id = upload_job_with_pipeline(
        client,
        parser_provider="mock",
        parser_layout_profile="pokerstars",
    ).json()["id"]
    for job_id in (generic_id, pokerstars_id):
        approve_job(client, job_id)
        client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})

    overview = client.get("/api/benchmarks").json()
    generic_report = client.post("/api/benchmarks/run").json()
    pokerstars_report = client.post(
        "/api/benchmarks/run",
        json={
            "parser_provider": "mock",
            "parser_layout_profile": "pokerstars",
        },
    ).json()
    ocr_generic_report = client.post(
        "/api/benchmarks/run",
        json={
            "parser_provider": "ocr_cv",
            "parser_layout_profile": "generic",
        },
    ).json()
    for summary_path in (tmp_path / "benchmarks").glob("*.summary.json"):
        summary_path.unlink()
    original_read_text = Path.read_text
    full_report_reads: list[str] = []

    def track_benchmark_reads(path: Path, *args, **kwargs) -> str:
        if (
            path.parent == tmp_path / "benchmarks"
            and path.suffix == ".json"
            and len(path.stem) == 32
        ):
            full_report_reads.append(path.stem)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", track_benchmark_reads)
    default_history = client.get("/api/benchmarks").json()
    pokerstars_history = client.get(
        "/api/benchmarks",
        params={
            "parser_provider": "mock",
            "parser_layout_profile": "pokerstars",
        },
    ).json()
    ocr_history = client.get(
        "/api/benchmarks",
        params={
            "parser_provider": "ocr_cv",
            "parser_layout_profile": "generic",
        },
    ).json()
    pokerstars_export = client.get(
        "/api/benchmarks/export",
        params={
            "parser_provider": "mock",
            "parser_layout_profile": "pokerstars",
        },
    )

    assert overview["included_cases"] == 2
    assert overview["included_cases_by_layout"] == {
        "generic": 1,
        "pokerstars": 1,
    }
    assert overview["default_layout_profile"] == "generic"
    assert [case["job_id"] for case in generic_report["cases"]] == [generic_id]
    assert generic_report["layout_profile"] == "generic"
    assert [case["job_id"] for case in pokerstars_report["cases"]] == [
        pokerstars_id
    ]
    assert pokerstars_report["layout_profile"] == "pokerstars"
    assert default_history["latest_report"]["id"] == generic_report["id"]
    assert [report["id"] for report in default_history["recent_reports"]] == [
        generic_report["id"]
    ]
    assert pokerstars_history["latest_report"]["id"] == pokerstars_report["id"]
    assert [report["id"] for report in pokerstars_history["recent_reports"]] == [
        pokerstars_report["id"]
    ]
    assert ocr_history["latest_report"]["id"] == ocr_generic_report["id"]
    assert [report["id"] for report in ocr_history["recent_reports"]] == [
        ocr_generic_report["id"]
    ]
    for history in (default_history, pokerstars_history, ocr_history):
        assert history["included_cases"] == 2
        assert history["included_cases_by_layout"] == {
            "generic": 1,
            "pokerstars": 1,
        }
    incompatible_history = client.get(
        "/api/benchmarks",
        params={
            "parser_provider": "ocr_cv",
            "parser_layout_profile": "pokerstars",
        },
    )
    assert incompatible_history.status_code == 400
    assert incompatible_history.json()["detail"] == (
        "Layout profile 'pokerstars' is not supported by parser provider 'ocr_cv'"
    )
    assert full_report_reads == [
        generic_report["id"],
        pokerstars_report["id"],
        ocr_generic_report["id"],
    ]
    assert len(list((tmp_path / "benchmarks").glob("*.summary.json"))) == 3
    with ZipFile(BytesIO(pokerstars_export.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert set(archive.namelist()) == {
            "manifest.json",
            f"images/{pokerstars_id}.png",
        }
    assert manifest["parser_provider"] == "mock"
    assert manifest["layout_profile"] == "pokerstars"
    assert [case["job_id"] for case in manifest["cases"]] == [pokerstars_id]


def test_benchmark_rejects_a_parser_not_enabled_for_the_deployment(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})

    response = client.post(
        "/api/benchmarks/run",
        json={
            "parser_provider": "ocr_cv",
            "parser_layout_profile": "generic",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Parser provider 'ocr_cv' is not enabled for this deployment"
    )
    assert client.get("/api/benchmarks").json()["latest_report"] is None


def test_benchmark_exposes_recent_summaries_and_historical_report_detail(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    first_report = client.post("/api/benchmarks/run").json()
    approve_job(client, job_id, {**APPROVED_STATE, "pot_size": 18.0})
    second_report = client.post("/api/benchmarks/run").json()

    overview = client.get("/api/benchmarks").json()
    historical = client.get(f"/api/benchmarks/{first_report['id']}")
    missing = client.get("/api/benchmarks/not-a-report")

    assert [summary["id"] for summary in overview["recent_reports"]] == [
        second_report["id"],
        first_report["id"],
    ]
    assert all(
        "cases" not in summary and summary["field_metrics"]
        for summary in overview["recent_reports"]
    )
    assert historical.status_code == 200
    assert historical.json() == first_report
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Benchmark report not found"

    stale_report_path = tmp_path / "benchmarks" / f"{'0' * 32}.json"
    stale_report_path.write_text("not valid JSON")
    os.utime(stale_report_path, ns=(0, 0))
    bounded_history = FileBenchmarkStore(tmp_path).list(limit=2)

    assert [report.id for report in bounded_history] == [
        second_report["id"],
        first_report["id"],
    ]


def test_benchmark_uses_corrections_without_mutating_original_parse(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    original_parser_result = FileJobStore(tmp_path).get(job_id).parser_result
    approve_job(client, job_id, {**APPROVED_STATE, "pot_size": 18.0})
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})

    report = client.post("/api/benchmarks/run").json()

    pot_metric = next(metric for metric in report["field_metrics"] if metric["field"] == "pot_size")
    assert pot_metric == {"field": "pot_size", "correct": 0, "total": 1, "accuracy": 0.0}
    assert report["accuracy"] < 1
    assert FileJobStore(tmp_path).get(job_id).parser_result == original_parser_result


def test_benchmark_treats_board_card_order_as_equivalent(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(
        client,
        job_id,
        {**APPROVED_STATE, "board_cards": list(reversed(APPROVED_STATE["board_cards"]))},
    )
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})

    report = client.post("/api/benchmarks/run").json()

    board_metric = next(
        metric for metric in report["field_metrics"] if metric["field"] == "board_cards"
    )
    assert board_metric == {"field": "board_cards", "correct": 1, "total": 1, "accuracy": 1.0}


def test_benchmark_continues_after_an_individual_parser_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client(tmp_path)
    first_id = upload_job(client, filename="first.png").json()["id"]
    second_id = upload_job(client, filename="second.png").json()["id"]
    for job_id in (first_id, second_id):
        approve_job(client, job_id)
        client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})

    class PartiallyFailingParser:
        name = "partially_failing"

        def parse(self, image_path: Path):
            if image_path.parent.name == second_id:
                raise ParserError("case failed")
            return MockParser().parse(image_path)

    monkeypatch.setattr("app.bootstrap.build_parser", lambda settings: PartiallyFailingParser())

    response = client.post("/api/benchmarks/run")

    assert response.status_code == 200
    report = response.json()
    assert report["total_cases"] == 2
    assert report["successful_cases"] == 1
    assert report["failed_cases"] == 1
    failed_case = next(case for case in report["cases"] if case["status"] == "error")
    assert failed_case["job_id"] == second_id
    assert failed_case["error"] == "case failed"
    assert failed_case["evaluated_fields"] > 0


def test_benchmark_continues_after_an_individual_image_path_failure(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    valid_id = upload_job(client, filename="valid.png").json()["id"]
    invalid_id = upload_job(client, filename="invalid.png").json()["id"]
    for job_id in (valid_id, invalid_id):
        approve_job(client, job_id)
        client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})

    store = FileJobStore(tmp_path)
    invalid_job = store.get(invalid_id)
    invalid_job.image_filename = "../outside.png"
    store.save(invalid_job)

    response = client.post("/api/benchmarks/run")

    assert response.status_code == 200
    report = response.json()
    assert report["total_cases"] == 2
    assert report["successful_cases"] == 1
    assert report["failed_cases"] == 1
    failed_case = next(case for case in report["cases"] if case["status"] == "error")
    assert failed_case["job_id"] == invalid_id
    assert "outside.png" in failed_case["error"]


def test_benchmark_parser_configuration_error_does_not_replace_latest_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(f"/api/jobs/{job_id}/benchmark", json={"included": True})
    previous_report = client.post("/api/benchmarks/run").json()

    class MisconfiguredParser:
        name = "misconfigured"

        def parse(self, image_path: Path):
            raise ParserConfigurationError("external parser URL is missing")

    monkeypatch.setattr("app.bootstrap.build_parser", lambda settings: MisconfiguredParser())

    response = client.post("/api/benchmarks/run")

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Parser configuration error: external parser URL is missing"
    )
    assert FileBenchmarkStore(tmp_path).get_latest().id == previous_report["id"]
