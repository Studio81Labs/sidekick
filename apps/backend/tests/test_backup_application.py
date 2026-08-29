"""Focused coverage for the application backup service boundary."""

import asyncio
from dataclasses import replace

from app.api.dependencies import (
    ApplicationBackupExport as CompatibilityApplicationBackupExport,
)
from app.api.dependencies import BackupsRuntime
from app.application.admin_ocr_test import AdminOcrTestAccessDecision
from app.application.backups import ApplicationBackupExport, BackupService
from app.domain.backups import ApplicationBackupRestoreResult


def restore_result() -> ApplicationBackupRestoreResult:
    return ApplicationBackupRestoreResult(
        imported_jobs=2,
        reused_jobs=3,
        imported_benchmark_reports=4,
        reused_benchmark_reports=5,
        total_jobs=6,
        total_benchmark_reports=7,
    )


def test_backup_compatibility_exports_preserve_object_identity() -> None:
    assert CompatibilityApplicationBackupExport is ApplicationBackupExport
    assert BackupsRuntime is BackupService


def test_backup_service_preserves_callbacks_and_dataclass_replacement() -> None:
    export = ApplicationBackupExport(
        content=iter([b"backup"]),
        filename="backup.zip",
    )
    restored = restore_result()
    restore_calls: list[bytes] = []
    authorization_headers: list[str | None] = []

    async def export_backup() -> ApplicationBackupExport:
        return export

    def restore_backup(archive_bytes: bytes) -> ApplicationBackupRestoreResult:
        restore_calls.append(archive_bytes)
        return restored

    def authorize_administrator(
        authorization_header: str | None,
    ) -> AdminOcrTestAccessDecision:
        authorization_headers.append(authorization_header)
        return "authorized"

    service = BackupService(
        max_upload_bytes=1024,
        export_backup=export_backup,
        restore_backup=restore_backup,
        authorize_administrator=authorize_administrator,
    )

    assert asyncio.run(service.export_backup()) is export
    assert service.restore_backup(b"archive") is restored
    assert service.authorize_administrator("Bearer token") == "authorized"
    assert restore_calls == [b"archive"]
    assert authorization_headers == ["Bearer token"]
    assert replace(service, max_upload_bytes=2048).max_upload_bytes == 2048
