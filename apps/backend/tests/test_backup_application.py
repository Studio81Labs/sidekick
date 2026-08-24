"""Focused coverage for the application backup service boundary."""

import asyncio
from dataclasses import replace

from app.api.dependencies import (
    ApplicationBackupExport as CompatibilityApplicationBackupExport,
)
from app.api.dependencies import BackupsRuntime
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

    async def export_backup() -> ApplicationBackupExport:
        return export

    def restore_backup(archive_bytes: bytes) -> ApplicationBackupRestoreResult:
        restore_calls.append(archive_bytes)
        return restored

    service = BackupService(
        max_upload_bytes=1024,
        export_backup=export_backup,
        restore_backup=restore_backup,
    )

    assert asyncio.run(service.export_backup()) is export
    assert service.restore_backup(b"archive") is restored
    assert restore_calls == [b"archive"]
    assert replace(service, max_upload_bytes=2048).max_upload_bytes == 2048
