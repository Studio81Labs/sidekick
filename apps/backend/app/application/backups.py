"""Application-owned backup service contracts."""

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass

from app.domain.backups import ApplicationBackupRestoreResult


@dataclass(frozen=True)
class ApplicationBackupExport:
    """A prepared full application backup ready for an HTTP response."""

    content: Iterator[bytes]
    filename: str


@dataclass(frozen=True)
class BackupService:
    """Application operations required by backup transport adapters."""

    max_upload_bytes: int
    export_backup: Callable[[], Awaitable[ApplicationBackupExport]]
    restore_backup: Callable[[bytes], ApplicationBackupRestoreResult]


__all__ = ["ApplicationBackupExport", "BackupService"]
