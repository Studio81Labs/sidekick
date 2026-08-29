import base64
from datetime import datetime, timezone
from pathlib import Path
import shutil
import stat
from threading import Event, Lock, Thread

import pytest

import app.backup_cli as backup_cli_module
import app.storage.persistence as storage_module
from app.backup_cli import (
    BACKUP_FILENAME_PATTERN,
    BackupCliError,
    export_application_backup,
    main,
)
from app.config import Settings
from app.data_lock import InterprocessDataLock
from app.domain.benchmarks import BenchmarkReport
from app.storage.file_benchmark_store import FileBenchmarkStore
from app.storage.file_job_store import FileJobStore
from app.storage.persistence import initialize_data_volume


VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
)
TEST_VOLUME_ID = "test-data-volume-0001"


def backup_settings(data_dir: Path) -> Settings:
    return Settings(data_dir=data_dir, data_volume_id=TEST_VOLUME_ID)


def seed_backup_data(data_dir: Path) -> None:
    job_store = FileJobStore(data_dir)
    benchmark_store = FileBenchmarkStore(data_dir)
    initialize_data_volume(data_dir, TEST_VOLUME_ID)
    job = job_store.create_job(
        original_filename="table.png",
        image_bytes=VALID_PNG,
        parser_provider="mock",
        recommendation_provider="mock",
        input_context="legacy_player",
    )
    job.status = "parsed"
    job_store.save(job)
    benchmark_store.save(
        BenchmarkReport(
            parser_provider="mock",
            layout_profile="generic",
            total_cases=0,
            successful_cases=0,
            failed_cases=0,
            correct_fields=0,
            evaluated_fields=0,
            accuracy=0,
        )
    )


def test_cli_initializes_data_volume_idempotently(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "data"
    settings = backup_settings(data_dir)
    FileJobStore(data_dir)
    FileBenchmarkStore(data_dir)

    assert main(["init-volume"], settings=settings) == 0
    assert main(["init-volume"], settings=settings) == 0

    output = capsys.readouterr().out
    assert output.count("Initialized data volume:") == 2
    marker_mode = (data_dir / ".poker-hero-data-volume").stat().st_mode
    assert (marker_mode & 0o444) == 0o444


def test_cli_fsyncs_data_directory_after_marker_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    FileJobStore(data_dir)
    FileBenchmarkStore(data_dir)
    original_fsync = storage_module.os.fsync
    directory_fsyncs = 0

    def record_fsync(descriptor: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(storage_module.os.fstat(descriptor).st_mode):
            directory_fsyncs += 1
        original_fsync(descriptor)

    monkeypatch.setattr(storage_module.os, "fsync", record_fsync)

    assert main(["init-volume"], settings=backup_settings(data_dir)) == 0
    assert main(["init-volume"], settings=backup_settings(data_dir)) == 0

    assert directory_fsyncs == 2


def test_cli_refuses_to_initialize_bare_entrypoint_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    assert main(["init-volume"], settings=backup_settings(data_dir)) == 2

    assert "was not initialized by the backend" in capsys.readouterr().err
    assert list(data_dir.iterdir()) == []


def test_cli_exports_verifies_and_restore_drills_backup(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "data"
    destination = tmp_path / "backups"
    settings = backup_settings(data_dir)
    seed_backup_data(data_dir)

    assert main(["export", str(destination)], settings=settings) == 0
    archives = list(destination.glob("*.zip"))
    assert len(archives) == 1
    archive = archives[0]
    assert BACKUP_FILENAME_PATTERN.fullmatch(archive.name)
    assert Path(capsys.readouterr().out.strip()) == archive.resolve()

    assert main(["verify", str(archive)], settings=settings) == 0
    assert capsys.readouterr().out.strip() == (
        "Backup verified: 1 job(s), 1 benchmark report(s)"
    )

    assert main(["drill", str(archive)], settings=settings) == 0
    assert capsys.readouterr().out.strip() == (
        "Restore drill passed: 1 job(s), 1 benchmark report(s)"
    )


def test_export_retention_only_prunes_matching_backup_files(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    destination = tmp_path / "backups"
    seed_backup_data(data_dir)
    destination.mkdir()
    oldest = destination / "poker-hero-backup-20260101T000000.000000Z-aaaaaaaa.zip"
    future = destination / "poker-hero-backup-20400101T000000.000000Z-bbbbbbbb.zip"
    unrelated = destination / "manual-backup.zip"
    oldest.write_bytes(b"old")
    future.write_bytes(b"future")
    unrelated.write_bytes(b"manual")

    created = export_application_backup(
        destination,
        backup_settings(data_dir),
        retain=2,
        exported_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )

    assert created.exists()
    assert future.exists()
    assert not oldest.exists()
    assert unrelated.read_bytes() == b"manual"


def test_overlapping_exports_serialize_publication_and_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    destination = tmp_path / "backups"
    seed_backup_data(data_dir)
    settings = backup_settings(data_dir)
    first_retention_started = Event()
    release_first_retention = Event()
    second_retention_started = Event()
    call_guard = Lock()
    call_count = 0
    errors: list[BaseException] = []
    original_prune = backup_cli_module._prune_backups

    def paused_prune(
        prune_destination: Path,
        retain: int,
        *,
        preserve: Path,
    ) -> None:
        nonlocal call_count
        with call_guard:
            call_count += 1
            current_call = call_count
        if current_call == 1:
            first_retention_started.set()
            assert release_first_retention.wait(timeout=5)
        else:
            second_retention_started.set()
        original_prune(prune_destination, retain, preserve=preserve)

    monkeypatch.setattr(backup_cli_module, "_prune_backups", paused_prune)

    def run_export(exported_at: datetime) -> None:
        try:
            export_application_backup(
                destination,
                settings,
                retain=1,
                exported_at=exported_at,
            )
        except BaseException as exc:
            errors.append(exc)

    first = Thread(
        target=run_export,
        args=(datetime(2030, 1, 1, tzinfo=timezone.utc),),
    )
    second = Thread(
        target=run_export,
        args=(datetime(2030, 1, 2, tzinfo=timezone.utc),),
    )
    first.start()
    assert first_retention_started.wait(timeout=5)
    second.start()

    assert not second_retention_started.wait(timeout=0.2)
    release_first_retention.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert len(list(destination.glob("*.zip"))) == 1


def test_export_waits_for_active_data_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    destination = tmp_path / "backups"
    seed_backup_data(data_dir)
    lock_attempted = Event()
    export_finished = Event()
    errors: list[BaseException] = []
    original_acquire = InterprocessDataLock.acquire

    def observed_acquire(
        lock: InterprocessDataLock,
        *,
        exclusive: bool,
    ) -> int:
        lock_attempted.set()
        return original_acquire(lock, exclusive=exclusive)

    def run_export() -> None:
        try:
            export_application_backup(
                destination,
                backup_settings(data_dir),
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            export_finished.set()

    with InterprocessDataLock(data_dir).hold(exclusive=False):
        monkeypatch.setattr(InterprocessDataLock, "acquire", observed_acquire)
        export_thread = Thread(target=run_export)
        export_thread.start()
        assert lock_attempted.wait(timeout=5)
        assert not export_finished.wait(timeout=0.2)
        assert not destination.exists()

    export_thread.join(timeout=5)
    assert not export_thread.is_alive()
    assert errors == []
    assert len(list(destination.glob("*.zip"))) == 1


def test_export_fsyncs_publication_and_retention_directory_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    destination = tmp_path / "backups"
    seed_backup_data(data_dir)
    destination.mkdir()
    original_fsync = backup_cli_module.os.fsync
    directory_fsyncs = 0

    def record_fsync(descriptor: int) -> None:
        nonlocal directory_fsyncs
        if stat.S_ISDIR(backup_cli_module.os.fstat(descriptor).st_mode):
            directory_fsyncs += 1
        original_fsync(descriptor)

    monkeypatch.setattr(backup_cli_module.os, "fsync", record_fsync)

    export_application_backup(
        destination,
        backup_settings(data_dir),
        retain=1,
    )

    assert directory_fsyncs == 2


def test_export_fsyncs_new_destination_parent_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    destination = tmp_path / "nested" / "backups"
    seed_backup_data(data_dir)
    original_fsync_directory = backup_cli_module._fsync_directory
    synced_directories: list[Path] = []

    def record_fsync_directory(directory: Path) -> None:
        synced_directories.append(directory)
        original_fsync_directory(directory)

    monkeypatch.setattr(
        backup_cli_module,
        "_fsync_directory",
        record_fsync_directory,
    )

    created = export_application_backup(
        destination,
        backup_settings(data_dir),
    )

    assert created.exists()
    assert destination in synced_directories
    assert destination.parent in synced_directories
    assert tmp_path in synced_directories


def test_export_rejects_active_jobs_without_publishing_backup(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "data"
    job_store = FileJobStore(data_dir)
    FileBenchmarkStore(data_dir)
    initialize_data_volume(data_dir, TEST_VOLUME_ID)
    job_store.create_job(
        original_filename="table.png",
        image_bytes=VALID_PNG,
        parser_provider="mock",
        recommendation_provider="mock",
        input_context="legacy_player",
    )
    destination = tmp_path / "backups"

    assert main(
        ["export", str(destination)],
        settings=backup_settings(data_dir),
    ) == 2

    assert "Wait for active parsing" in capsys.readouterr().err
    assert list(destination.glob("*.zip")) == []


def test_export_rejects_pending_import_without_rotating_backups(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "data"
    destination = tmp_path / "backups"
    seed_backup_data(data_dir)
    FileBenchmarkStore(data_dir).begin_import(
        "pending-backup-import",
        b"dataset",
    )
    destination.mkdir()
    known_good = (
        destination / "poker-hero-backup-20260101T000000.000000Z-aaaaaaaa.zip"
    )
    known_good.write_bytes(b"known good")

    assert main(
        ["export", str(destination), "--retain", "1"],
        settings=backup_settings(data_dir),
    ) == 2

    assert "pending benchmark dataset import" in capsys.readouterr().err
    assert known_good.read_bytes() == b"known good"
    assert len(list(destination.glob("*.zip"))) == 1


def test_export_refuses_missing_data_volume_without_rotating_backups(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "missing-volume"
    destination = tmp_path / "backups"
    destination.mkdir()
    known_good = (
        destination / "poker-hero-backup-20260101T000000.000000Z-aaaaaaaa.zip"
    )
    known_good.write_bytes(b"known good")

    assert main(
        ["export", str(destination), "--retain", "1"],
        settings=backup_settings(data_dir),
    ) == 2

    assert "Data volume marker is missing" in capsys.readouterr().err
    assert known_good.read_bytes() == b"known good"
    assert not data_dir.exists()


def test_export_refuses_invalid_data_volume_marker(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "wrong-volume"
    FileJobStore(data_dir)
    FileBenchmarkStore(data_dir)
    initialize_data_volume(data_dir, "different-data-volume-0002")
    destination = tmp_path / "backups"

    assert main(
        ["export", str(destination)],
        settings=backup_settings(data_dir),
    ) == 2

    assert "Data volume marker does not match" in capsys.readouterr().err
    assert not destination.exists()


@pytest.mark.parametrize("missing_store", ["jobs", "benchmarks"])
def test_export_refuses_missing_store_without_rotating_backups(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing_store: str,
) -> None:
    data_dir = tmp_path / "data"
    destination = tmp_path / "backups"
    seed_backup_data(data_dir)
    shutil.rmtree(data_dir / missing_store)
    destination.mkdir()
    known_good = (
        destination / "poker-hero-backup-20260101T000000.000000Z-aaaaaaaa.zip"
    )
    known_good.write_bytes(b"known good")

    assert main(
        ["export", str(destination), "--retain", "1"],
        settings=backup_settings(data_dir),
    ) == 2

    assert "Required data store directories are missing" in capsys.readouterr().err
    assert known_good.read_bytes() == b"known good"
    assert not (data_dir / missing_store).exists()


def test_export_requires_configured_data_volume_identity(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "data"
    FileJobStore(data_dir)
    FileBenchmarkStore(data_dir)
    initialize_data_volume(data_dir, TEST_VOLUME_ID)

    assert main(
        ["export", str(tmp_path / "backups")],
        settings=Settings(data_dir=data_dir),
    ) == 2

    assert "POKER_DATA_VOLUME_ID is required" in capsys.readouterr().err
    assert not (tmp_path / "backups").exists()


def test_verify_reports_invalid_archive_without_touching_data_dir(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = tmp_path / "invalid.zip"
    archive.write_bytes(b"not a zip archive")
    data_dir = tmp_path / "production-data"

    assert main(
        ["verify", str(archive)],
        settings=Settings(data_dir=data_dir),
    ) == 2

    assert capsys.readouterr().err
    assert not data_dir.exists()


@pytest.mark.parametrize(
    ("retain", "exported_at", "message"),
    [
        (0, None, "retention must be a positive integer"),
        (1, datetime(2030, 1, 1), "time must include a timezone"),
    ],
)
def test_export_rejects_invalid_direct_arguments(
    tmp_path: Path,
    retain: int,
    exported_at: datetime | None,
    message: str,
) -> None:
    with pytest.raises(BackupCliError, match=message):
        export_application_backup(
            tmp_path / "backups",
            backup_settings(tmp_path / "data"),
            retain=retain,
            exported_at=exported_at,
        )
    assert not (tmp_path / "backups").exists()
    assert not (tmp_path / "data").exists()
