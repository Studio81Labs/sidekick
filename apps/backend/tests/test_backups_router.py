from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import (
    ApplicationBackupExport,
    ApplicationBackupTransportError,
    BackupsRuntime,
)
from app.api.routers.backups import create_backups_router
from app.application.admin_ocr_test import AdminOcrTestAccessPolicy
from app.domain.backups import ApplicationBackupRestoreResult
from api_test_support import ADMIN_OCR_TEST_HEADERS, ADMIN_OCR_TEST_TOKEN


ADMIN_OCR_TEST_POLICY = AdminOcrTestAccessPolicy.for_token(ADMIN_OCR_TEST_TOKEN)


def restore_result() -> ApplicationBackupRestoreResult:
    return ApplicationBackupRestoreResult(
        imported_jobs=2,
        reused_jobs=3,
        imported_benchmark_reports=4,
        reused_benchmark_reports=5,
        total_jobs=6,
        total_benchmark_reports=7,
    )


async def export_backup() -> ApplicationBackupExport:
    return ApplicationBackupExport(
        content=iter([b"application backup"]),
        filename="poker-hero-backup-20260821T000000Z.zip",
    )


def restore_backup(_archive_bytes: bytes) -> ApplicationBackupRestoreResult:
    return restore_result()


def default_runtime() -> BackupsRuntime:
    return BackupsRuntime(
        max_upload_bytes=1024,
        export_backup=export_backup,
        restore_backup=restore_backup,
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )


def make_client(runtime: BackupsRuntime | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(create_backups_router(runtime or default_runtime()))
    return TestClient(app)


def test_backups_router_streams_export_and_restores_uploaded_bytes() -> None:
    restore_calls: list[bytes] = []

    async def export() -> ApplicationBackupExport:
        return ApplicationBackupExport(
            content=iter([b"backup", b" archive"]),
            filename="poker-hero-backup-20260821T000000Z.zip",
        )

    def restore(archive_bytes: bytes) -> ApplicationBackupRestoreResult:
        restore_calls.append(archive_bytes)
        return restore_result()

    runtime = BackupsRuntime(
        max_upload_bytes=1024,
        export_backup=export,
        restore_backup=restore,
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )
    with make_client(runtime) as client:
        exported = client.get("/api/backups/export")
        restored = client.post(
            "/api/backups/restore",
            files={"file": ("backup.zip", b"restore archive", "application/zip")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )

    assert exported.status_code == 200
    assert exported.content == b"backup archive"
    assert exported.headers["content-type"] == "application/zip"
    assert exported.headers["content-disposition"] == (
        'attachment; filename="poker-hero-backup-20260821T000000Z.zip"'
    )
    assert restored.status_code == 200
    assert restored.json() == restore_result().model_dump()
    assert restore_calls == [b"restore archive"]


def test_backups_router_rejects_oversize_upload_without_restoring() -> None:
    restore_calls: list[bytes] = []

    def should_not_restore(archive_bytes: bytes) -> ApplicationBackupRestoreResult:
        restore_calls.append(archive_bytes)
        return restore_result()

    runtime = BackupsRuntime(
        max_upload_bytes=3,
        export_backup=export_backup,
        restore_backup=should_not_restore,
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )

    with make_client(runtime) as client:
        response = client.post(
            "/api/backups/restore",
            files={"file": ("backup.zip", b"four", "application/zip")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )

    assert (response.status_code, response.json()) == (
        413,
        {"detail": "Application backup ZIP exceeds maximum size"},
    )
    assert restore_calls == []


def test_backups_router_accepts_upload_at_exact_size_limit() -> None:
    restore_calls: list[bytes] = []

    def restore(archive_bytes: bytes) -> ApplicationBackupRestoreResult:
        restore_calls.append(archive_bytes)
        return restore_result()

    runtime = BackupsRuntime(
        max_upload_bytes=4,
        export_backup=export_backup,
        restore_backup=restore,
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )

    with make_client(runtime) as client:
        response = client.post(
            "/api/backups/restore",
            files={"file": ("backup.zip", b"four", "application/zip")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )

    assert response.status_code == 200
    assert restore_calls == [b"four"]


def test_backups_router_maps_typed_transport_errors() -> None:
    async def unavailable_export() -> ApplicationBackupExport:
        raise ApplicationBackupTransportError("Backup is busy", 409)

    def invalid_restore(_archive_bytes: bytes) -> ApplicationBackupRestoreResult:
        raise ApplicationBackupTransportError("Backup archive is invalid", 400)

    runtime = BackupsRuntime(
        max_upload_bytes=1024,
        export_backup=unavailable_export,
        restore_backup=invalid_restore,
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )
    with make_client(runtime) as client:
        export_response = client.get("/api/backups/export")
        restore_response = client.post(
            "/api/backups/restore",
            files={"file": ("backup.zip", b"invalid", "application/zip")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )

    assert (export_response.status_code, export_response.json()) == (
        409,
        {"detail": "Backup is busy"},
    )
    assert (restore_response.status_code, restore_response.json()) == (
        400,
        {"detail": "Backup archive is invalid"},
    )


def test_backups_router_refuses_restore_without_the_administrator_credential() -> None:
    restore_calls: list[bytes] = []

    def should_not_restore(archive_bytes: bytes) -> ApplicationBackupRestoreResult:
        restore_calls.append(archive_bytes)
        return restore_result()

    def runtime_deciding(decision: str) -> BackupsRuntime:
        return BackupsRuntime(
            max_upload_bytes=1024,
            export_backup=export_backup,
            restore_backup=should_not_restore,
            authorize_administrator=lambda _authorization_header: decision,
        )

    with make_client(runtime_deciding("disabled")) as client:
        disabled = client.post(
            "/api/backups/restore",
            files={"file": ("backup.zip", b"restore archive", "application/zip")},
            headers=ADMIN_OCR_TEST_HEADERS,
        )
    with make_client() as client:
        missing = client.post(
            "/api/backups/restore",
            files={"file": ("backup.zip", b"restore archive", "application/zip")},
        )
    with make_client(runtime_deciding("expired")) as client:
        unexpected = client.post(
            "/api/backups/restore",
            files={"file": ("backup.zip", b"restore archive", "application/zip")},
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
    assert restore_calls == []


def test_backups_router_denies_before_reading_an_oversize_archive() -> None:
    runtime = BackupsRuntime(
        max_upload_bytes=4,
        export_backup=export_backup,
        restore_backup=restore_backup,
        authorize_administrator=ADMIN_OCR_TEST_POLICY.authorize,
    )

    with make_client(runtime) as client:
        response = client.post(
            "/api/backups/restore",
            files={"file": ("backup.zip", b"far too large", "application/zip")},
        )

    assert response.status_code == 401


def test_backups_router_preserves_public_openapi_contract() -> None:
    with make_client() as client:
        document = client.app.openapi()

    export_operation = document["paths"]["/api/backups/export"]["get"]
    restore_operation = document["paths"]["/api/backups/restore"]["post"]

    assert export_operation["operationId"] == "backups_export"
    assert export_operation["responses"]["200"]["content"] == {
        "application/zip": {"schema": {"type": "string", "format": "binary"}}
    }
    assert restore_operation["operationId"] == "backups_restore"
    assert restore_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ApplicationBackupRestoreResult"}
