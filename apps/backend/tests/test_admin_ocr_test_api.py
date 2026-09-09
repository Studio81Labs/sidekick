from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.application.admin_ocr_test import AdminOcrTestAccessPolicy
from app.bootstrap import create_app
from app.config import Settings
from app.storage.file_benchmark_store import FileBenchmarkStore
from app.storage.file_job_store import FileJobStore
from api_test_support import (
    ADMIN_OCR_TEST_HEADERS,
    ADMIN_OCR_TEST_TOKEN,
    VALID_PNG,
    approve_job,
    import_benchmark_dataset,
    make_client,
    restore_application_backup,
    upload_job,
)


def _post_upload(client: TestClient, headers: dict[str, str] | None = None):
    return client.post(
        "/api/jobs",
        files={"file": ("table.png", VALID_PNG, "image/png")},
        headers=headers,
    )


def test_upload_is_forbidden_when_administrative_mode_is_disabled(tmp_path: Path) -> None:
    client = make_client(tmp_path, admin_ocr_test_enabled=False, admin_ocr_test_token=None)

    without_credential = _post_upload(client)
    with_credential = _post_upload(client, ADMIN_OCR_TEST_HEADERS)

    assert without_credential.status_code == 403
    assert without_credential.json()["detail"] == "Administrative OCR test mode is disabled"
    assert with_credential.status_code == 403
    assert not (tmp_path / "jobs").exists() or not any((tmp_path / "jobs").iterdir())


def test_upload_requires_a_valid_administrator_bearer(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    missing = _post_upload(client)
    wrong_scheme = _post_upload(client, {"Authorization": f"Basic {ADMIN_OCR_TEST_TOKEN}"})
    wrong_token = _post_upload(client, {"Authorization": f"Bearer {ADMIN_OCR_TEST_TOKEN}x"})

    for response in (missing, wrong_scheme, wrong_token):
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.json()["detail"] == "Administrative OCR test authorization is required"
    assert not (tmp_path / "jobs").exists() or not any((tmp_path / "jobs").iterdir())


def test_authorized_upload_persists_a_parsed_ocr_test_job(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = _post_upload(client, ADMIN_OCR_TEST_HEADERS)

    assert response.status_code == 201
    job = response.json()
    assert job["status"] == "parsed"
    assert job["original_filename"] == "table.png"
    assert job["parser_provider"] == "mock"

    persisted = FileJobStore(tmp_path).get(job["id"])
    assert persisted.status == "parsed"
    assert persisted.original_filename == "table.png"
    assert persisted.parser_provider == "mock"
    assert persisted.parser_result is not None


def test_disabled_deployment_ignores_configured_token(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            data_dir=tmp_path,
            parser_provider="mock",
            admin_ocr_test_enabled=False,
            admin_ocr_test_token=ADMIN_OCR_TEST_TOKEN,
        )
    )

    response = _post_upload(TestClient(app), ADMIN_OCR_TEST_HEADERS)

    assert response.status_code == 403


def test_upload_fails_closed_on_an_unexpected_authorization_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only an explicit "authorized" decision may proceed: a future decision member
    # must deny rather than fall through and open the upload surface. The policy is
    # patched before the app is built because bootstrap binds `authorize` once.
    monkeypatch.setattr(
        AdminOcrTestAccessPolicy,
        "authorize",
        lambda _self, _authorization_header: "expired",
    )
    client = make_client(tmp_path)

    response = _post_upload(client, ADMIN_OCR_TEST_HEADERS)

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Administrative OCR test authorization was refused"
    )
    assert not (tmp_path / "jobs").exists() or not any((tmp_path / "jobs").iterdir())


def _session(client: TestClient, headers: dict[str, str] | None = None):
    return client.get("/api/admin/ocr-test/session", headers=headers)


def test_session_confirms_a_valid_administrator_bearer(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = _session(client, ADMIN_OCR_TEST_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"enabled": True, "authorized": True}
    # The PWA unlocks capture on this answer, so no cache may replay it.
    assert response.headers["Cache-Control"] == "no-store"


def test_session_requires_a_valid_administrator_bearer(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    missing = _session(client)
    wrong_scheme = _session(client, {"Authorization": f"Basic {ADMIN_OCR_TEST_TOKEN}"})
    wrong_token = _session(client, {"Authorization": f"Bearer {ADMIN_OCR_TEST_TOKEN}x"})

    for response in (missing, wrong_scheme, wrong_token):
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.json()["detail"] == (
            "Administrative OCR test authorization is required"
        )


def test_session_is_forbidden_when_administrative_mode_is_disabled(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        admin_ocr_test_enabled=False,
        admin_ocr_test_token=None,
    )
    configured = TestClient(
        create_app(
            Settings(
                data_dir=tmp_path / "configured",
                parser_provider="mock",
                admin_ocr_test_enabled=False,
                admin_ocr_test_token=ADMIN_OCR_TEST_TOKEN,
            )
        )
    )

    disabled = _session(client, ADMIN_OCR_TEST_HEADERS)
    ignored_token = _session(configured, ADMIN_OCR_TEST_HEADERS)

    for response in (disabled, ignored_token):
        assert response.status_code == 403
        assert response.json()["detail"] == (
            "Administrative OCR test mode is disabled"
        )


def test_session_fails_closed_on_an_unexpected_authorization_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        AdminOcrTestAccessPolicy,
        "authorize",
        lambda _self, _authorization_header: "expired",
    )
    client = make_client(tmp_path)

    response = _session(client, ADMIN_OCR_TEST_HEADERS)

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Administrative OCR test authorization was refused"
    )


def _dataset_archive(tmp_path: Path) -> bytes:
    source = make_client(tmp_path / "dataset-source")
    job_id = upload_job(source).json()["id"]
    assert approve_job(source, job_id).status_code == 200
    assert source.put(
        f"/api/jobs/{job_id}/benchmark",
        json={"included": True},
    ).status_code == 200
    export = source.get("/api/benchmarks/export")
    assert export.status_code == 200
    return export.content


def _backup_archive(tmp_path: Path) -> tuple[bytes, str]:
    source = make_client(tmp_path / "backup-source")
    job_id = upload_job(source).json()["id"]
    assert approve_job(source, job_id).status_code == 200
    assert source.put("/api/history", json={"job_ids": [job_id]}).status_code == 200
    export = source.get("/api/backups/export")
    assert export.status_code == 200
    return export.content, job_id


def _import_receipts(data_dir: Path) -> list[Path]:
    return list(FileBenchmarkStore(data_dir).imports_dir.iterdir())


def test_dataset_import_is_forbidden_when_administrative_mode_is_disabled(
    tmp_path: Path,
) -> None:
    archive = _dataset_archive(tmp_path)
    target_dir = tmp_path / "target"
    client = make_client(
        target_dir,
        admin_ocr_test_enabled=False,
        admin_ocr_test_token=None,
    )

    without_credential = import_benchmark_dataset(client, archive, headers={})
    with_credential = import_benchmark_dataset(
        client,
        archive,
        request_id="denied-import",
    )

    assert without_credential.status_code == 403
    assert without_credential.json()["detail"] == (
        "Administrative OCR test mode is disabled"
    )
    assert with_credential.status_code == 403
    assert FileJobStore(target_dir).list() == []
    assert _import_receipts(target_dir) == []


def test_dataset_import_requires_a_valid_administrator_bearer(tmp_path: Path) -> None:
    archive = _dataset_archive(tmp_path)
    target_dir = tmp_path / "target"
    client = make_client(target_dir)

    missing = import_benchmark_dataset(client, archive, headers={})
    wrong_scheme = import_benchmark_dataset(
        client,
        archive,
        headers={"Authorization": f"Basic {ADMIN_OCR_TEST_TOKEN}"},
    )
    wrong_token = import_benchmark_dataset(
        client,
        archive,
        request_id="denied-import",
        headers={"Authorization": f"Bearer {ADMIN_OCR_TEST_TOKEN}x"},
    )

    for response in (missing, wrong_scheme, wrong_token):
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.json()["detail"] == (
            "Administrative OCR test authorization is required"
        )
    assert FileJobStore(target_dir).list() == []
    assert _import_receipts(target_dir) == []


def test_authorized_dataset_import_still_loads_the_archive(tmp_path: Path) -> None:
    archive = _dataset_archive(tmp_path)
    target_dir = tmp_path / "target"
    client = make_client(target_dir)

    response = import_benchmark_dataset(client, archive)

    assert response.status_code == 200
    assert response.json()["imported_cases"] == 1
    assert len(FileJobStore(target_dir).list()) == 1


def test_dataset_import_fails_closed_on_an_unexpected_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = _dataset_archive(tmp_path)
    # The policy is patched after the archive is built because bootstrap binds
    # `authorize` once, and only an explicit "authorized" decision may proceed.
    monkeypatch.setattr(
        AdminOcrTestAccessPolicy,
        "authorize",
        lambda _self, _authorization_header: "expired",
    )
    target_dir = tmp_path / "target"
    client = make_client(target_dir)

    response = import_benchmark_dataset(client, archive)

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Administrative OCR test authorization was refused"
    )
    assert FileJobStore(target_dir).list() == []
    assert _import_receipts(target_dir) == []


def test_backup_restore_is_forbidden_when_administrative_mode_is_disabled(
    tmp_path: Path,
) -> None:
    archive, job_id = _backup_archive(tmp_path)
    target_dir = tmp_path / "target"
    client = make_client(
        target_dir,
        admin_ocr_test_enabled=False,
        admin_ocr_test_token=None,
    )

    without_credential = restore_application_backup(client, archive, headers={})
    with_credential = restore_application_backup(client, archive)

    assert without_credential.status_code == 403
    assert without_credential.json()["detail"] == (
        "Administrative OCR test mode is disabled"
    )
    assert with_credential.status_code == 403
    assert FileJobStore(target_dir).list() == []
    assert not (target_dir / "jobs" / job_id).exists()


def test_backup_restore_requires_a_valid_administrator_bearer(tmp_path: Path) -> None:
    archive, job_id = _backup_archive(tmp_path)
    target_dir = tmp_path / "target"
    client = make_client(target_dir)

    missing = restore_application_backup(client, archive, headers={})
    wrong_scheme = restore_application_backup(
        client,
        archive,
        headers={"Authorization": f"Basic {ADMIN_OCR_TEST_TOKEN}"},
    )
    wrong_token = restore_application_backup(
        client,
        archive,
        headers={"Authorization": f"Bearer {ADMIN_OCR_TEST_TOKEN}x"},
    )

    for response in (missing, wrong_scheme, wrong_token):
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.json()["detail"] == (
            "Administrative OCR test authorization is required"
        )
    assert FileJobStore(target_dir).list() == []
    assert not (target_dir / "jobs" / job_id).exists()


def test_authorized_backup_restore_still_imports_the_archive(tmp_path: Path) -> None:
    archive, job_id = _backup_archive(tmp_path)
    target_dir = tmp_path / "target"
    client = make_client(target_dir)

    response = restore_application_backup(client, archive)

    assert response.status_code == 200
    assert response.json()["imported_jobs"] == 1
    assert FileJobStore(target_dir).get(job_id).id == job_id


def test_backup_restore_fails_closed_on_an_unexpected_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive, job_id = _backup_archive(tmp_path)
    monkeypatch.setattr(
        AdminOcrTestAccessPolicy,
        "authorize",
        lambda _self, _authorization_header: "expired",
    )
    target_dir = tmp_path / "target"
    client = make_client(target_dir)

    response = restore_application_backup(client, archive)

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Administrative OCR test authorization was refused"
    )
    assert not (target_dir / "jobs" / job_id).exists()


def test_administrative_denials_precede_archive_reads(tmp_path: Path) -> None:
    # A denial that ran after the size guard would answer 413 instead of 401,
    # which would mean the router had already read the uploaded archive.
    client = make_client(
        tmp_path,
        max_dataset_upload_bytes=8,
        max_backup_upload_bytes=8,
    )

    imported = import_benchmark_dataset(client, b"x" * 64, headers={})
    restored = restore_application_backup(client, b"x" * 64, headers={})

    assert imported.status_code == 401
    assert restored.status_code == 401
