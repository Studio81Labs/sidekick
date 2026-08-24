import argparse
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import re
import shutil
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import BinaryIO
from uuid import uuid4

from pydantic import ValidationError

from app.application_backup import (
    MAX_BACKUP_EXPANSION_RATIO,
    ApplicationBackupError,
    ParsedApplicationBackup,
    application_backup_limit_message,
    build_application_backup_archive,
    parse_application_backup_archive,
    restore_application_backup,
)
from app.config import Settings, get_settings
from app.data_lock import DataLockError, InterprocessDataLock
from app.storage.file_benchmark_store import FileBenchmarkStore
from app.storage.file_job_store import FileJobStore
from app.storage.persistence import (
    DataVolumeError,
    initialize_data_volume,
    require_initialized_data_stores,
    require_initialized_data_volume,
)


BACKUP_FILENAME_PATTERN = re.compile(
    r"^poker-hero-backup-\d{8}T\d{6}\.\d{6}Z-[0-9a-f]{8}\.zip$"
)
BACKUP_LOCK_FILENAME = ".poker-hero-backup.lock"


class BackupCliError(RuntimeError):
    pass


def export_application_backup(
    destination: Path,
    settings: Settings,
    *,
    retain: int | None = None,
    exported_at: datetime | None = None,
) -> Path:
    if retain is not None and retain <= 0:
        raise BackupCliError("Backup retention must be a positive integer")
    timestamp = exported_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise BackupCliError("Backup export time must include a timezone")
    timestamp = timestamp.astimezone(timezone.utc)
    volume_id = _required_data_volume_id(settings)
    require_initialized_data_volume(settings.data_dir, volume_id)
    data_lock = InterprocessDataLock(settings.data_dir)
    with data_lock.hold(exclusive=True):
        require_initialized_data_volume(settings.data_dir, volume_id)
        require_initialized_data_stores(settings.data_dir)
        job_store = FileJobStore(settings.data_dir)
        benchmark_store = FileBenchmarkStore(settings.data_dir)
        if benchmark_store.has_pending_import():
            raise BackupCliError(
                "Wait for the pending benchmark dataset import before "
                "exporting a backup"
            )
        archive = build_application_backup_archive(
            jobs=job_store.list(),
            benchmark_reports=benchmark_store.list(limit=None),
            image_path_for=job_store.image_path,
            max_archive_bytes=settings.max_backup_upload_bytes,
            max_image_bytes=settings.max_upload_bytes,
        )
    try:
        _ensure_backup_destination(destination)
        filename = (
            f"poker-hero-backup-{timestamp.strftime('%Y%m%dT%H%M%S.%fZ')}-"
            f"{uuid4().hex[:8]}.zip"
        )
        output_path = destination / filename
        with _backup_destination_lock(destination):
            _publish_backup_archive(
                archive,
                output_path=output_path,
                destination=destination,
                settings=settings,
            )
            if retain is not None:
                _prune_backups(destination, retain, preserve=output_path)
                _fsync_directory(destination)
    finally:
        archive.close()
    return output_path


def load_application_backup(path: Path, settings: Settings) -> ParsedApplicationBackup:
    try:
        archive_size = path.stat().st_size
    except OSError as exc:
        raise BackupCliError(f"Could not read application backup: {path}") from exc
    if archive_size > settings.max_backup_upload_bytes:
        raise BackupCliError(
            application_backup_limit_message(settings.max_backup_upload_bytes)
        )
    try:
        archive_bytes = path.read_bytes()
    except OSError as exc:
        raise BackupCliError(f"Could not read application backup: {path}") from exc
    return parse_application_backup_archive(
        archive_bytes,
        max_image_bytes=settings.max_upload_bytes,
        max_uncompressed_bytes=(
            settings.max_backup_upload_bytes * MAX_BACKUP_EXPANSION_RATIO
        ),
    )


def run_restore_drill(
    path: Path,
    settings: Settings,
) -> ParsedApplicationBackup:
    backup = load_application_backup(path, settings)
    with TemporaryDirectory(prefix="poker-hero-restore-drill-") as temp_dir:
        job_store = FileJobStore(Path(temp_dir))
        benchmark_store = FileBenchmarkStore(Path(temp_dir))
        first_restore = restore_application_backup(
            backup,
            job_store=job_store,
            benchmark_store=benchmark_store,
        )
        if (
            first_restore.imported_jobs != len(backup.jobs)
            or first_restore.imported_benchmark_reports
            != len(backup.benchmark_reports)
        ):
            raise BackupCliError("Restore drill did not import every backup entry")

        second_restore = restore_application_backup(
            backup,
            job_store=job_store,
            benchmark_store=benchmark_store,
        )
        if (
            second_restore.imported_jobs != 0
            or second_restore.imported_benchmark_reports != 0
            or second_restore.reused_jobs != len(backup.jobs)
            or second_restore.reused_benchmark_reports
            != len(backup.benchmark_reports)
        ):
            raise BackupCliError("Restore drill idempotency check failed")

        rebuilt_archive = build_application_backup_archive(
            jobs=job_store.list(),
            benchmark_reports=benchmark_store.list(limit=None),
            image_path_for=job_store.image_path,
            max_archive_bytes=settings.max_backup_upload_bytes,
            max_image_bytes=settings.max_upload_bytes,
        )
        try:
            rebuilt = parse_application_backup_archive(
                rebuilt_archive.read(),
                max_image_bytes=settings.max_upload_bytes,
                max_uncompressed_bytes=(
                    settings.max_backup_upload_bytes * MAX_BACKUP_EXPANSION_RATIO
                ),
            )
        finally:
            rebuilt_archive.close()
        if not _backup_contents_match(backup, rebuilt):
            raise BackupCliError(
                "Restore drill re-export does not match the source backup"
            )
    return backup


def _backup_contents_match(
    left: ParsedApplicationBackup,
    right: ParsedApplicationBackup,
) -> bool:
    left_jobs = {job.id: (job, image) for job, image in left.jobs}
    right_jobs = {job.id: (job, image) for job, image in right.jobs}
    left_reports = {report.id: report for report in left.benchmark_reports}
    right_reports = {report.id: report for report in right.benchmark_reports}
    return left_jobs == right_jobs and left_reports == right_reports


def _ensure_backup_destination(destination: Path) -> None:
    missing_directories: list[Path] = []
    current = destination
    while not current.exists():
        missing_directories.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupCliError(
            f"Could not create backup destination: {destination}"
        ) from exc
    if not destination.is_dir():
        raise BackupCliError(
            f"Backup destination is not a directory: {destination}"
        )
    for created_directory in missing_directories:
        _fsync_directory(created_directory.parent)


@contextmanager
def _backup_destination_lock(destination: Path) -> Iterator[None]:
    lock_path = destination / BACKUP_LOCK_FILENAME
    try:
        descriptor = os.open(lock_path, os.O_RDONLY | os.O_CREAT, 0o644)
    except OSError as exc:
        raise BackupCliError(f"Could not open backup lock in {destination}") from exc
    locked = False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
        except OSError as exc:
            raise BackupCliError(
                f"Could not acquire backup lock in {destination}"
            ) from exc
        yield
    finally:
        try:
            if locked:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _publish_backup_archive(
    archive: BinaryIO,
    *,
    output_path: Path,
    destination: Path,
    settings: Settings,
) -> None:
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            "wb",
            dir=destination,
            prefix=".poker-hero-backup.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temp_path = Path(output.name)
            shutil.copyfileobj(archive, output)
            output.flush()
            os.fsync(output.fileno())
        load_application_backup(temp_path, settings)
        os.link(temp_path, output_path)
        _remove_temporary_file(temp_path)
        temp_path = None
        _fsync_directory(destination)
    except OSError as exc:
        raise BackupCliError(f"Could not write backup to {destination}") from exc
    finally:
        if temp_path is not None:
            _remove_temporary_file(temp_path)


def _prune_backups(destination: Path, retain: int, *, preserve: Path) -> None:
    try:
        backups = sorted(
            (
                path
                for path in destination.iterdir()
                if path.is_file() and BACKUP_FILENAME_PATTERN.fullmatch(path.name)
            ),
            key=lambda path: path.name,
            reverse=True,
        )
        kept = {preserve}
        for path in backups:
            if path in kept:
                continue
            if len(kept) < retain:
                kept.add(path)
                continue
            path.unlink()
    except OSError as exc:
        raise BackupCliError("Backup was created but retention cleanup failed") from exc


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise BackupCliError(
            f"Could not make backup directory changes durable: {directory}"
        ) from exc


def _remove_temporary_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # A published hard link is already durable. A hidden cleanup file is
        # preferable to turning a successful backup into a failed operation.
        pass


def _positive_integer(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if result <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def _required_data_volume_id(settings: Settings) -> str:
    if settings.data_volume_id is None:
        raise BackupCliError(
            "POKER_DATA_VOLUME_ID is required for operational backup export"
        )
    return settings.data_volume_id


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export, verify, and restore-drill Poker Hero backups.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Override POKER_DATA_DIR for init-volume and export",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "init-volume",
        help="Enroll the configured data volume for operational backups",
    )

    export_parser = commands.add_parser(
        "export",
        help="Create a timestamped application backup",
    )
    export_parser.add_argument("destination", type=Path)
    export_parser.add_argument(
        "--retain",
        type=_positive_integer,
        help="Keep only the newest matching backup files",
    )

    verify_parser = commands.add_parser(
        "verify",
        help="Validate an application backup without restoring it",
    )
    verify_parser.add_argument("archive", type=Path)

    drill_parser = commands.add_parser(
        "drill",
        help="Restore and re-export a backup in isolated temporary storage",
    )
    drill_parser.add_argument("archive", type=Path)
    return parser


def main(
    argv: Sequence[str] | None = None,
    settings: Settings | None = None,
) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        active_settings = settings or get_settings()
    except ValidationError as exc:
        first_error = exc.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first_error["loc"])
        print(
            f"Settings configuration is invalid at {location}: {first_error['msg']}",
            file=sys.stderr,
        )
        return 2
    if args.data_dir is not None:
        active_settings = active_settings.model_copy(
            update={"data_dir": args.data_dir}
        )

    try:
        if args.command == "init-volume":
            volume_id = _required_data_volume_id(active_settings)
            initialize_data_volume(active_settings.data_dir, volume_id)
            print(f"Initialized data volume: {active_settings.data_dir.resolve()}")
        elif args.command == "export":
            output_path = export_application_backup(
                args.destination,
                active_settings,
                retain=args.retain,
            )
            print(output_path.resolve())
        elif args.command == "verify":
            backup = load_application_backup(args.archive, active_settings)
            print(_success_message("Backup verified", backup))
        else:
            backup = run_restore_drill(args.archive, active_settings)
            print(_success_message("Restore drill passed", backup))
    except (
        ApplicationBackupError,
        BackupCliError,
        DataLockError,
        DataVolumeError,
        OSError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def _success_message(label: str, backup: ParsedApplicationBackup) -> str:
    return (
        f"{label}: {len(backup.jobs)} job(s), "
        f"{len(backup.benchmark_reports)} benchmark report(s)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
