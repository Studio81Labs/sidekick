from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Event

import pytest

import app.player_uninstall as player_uninstall_module
from app.config import Settings
from app.data_lock import DataLockTimeoutError, player_runtime_lease
from app.player_backup import parse_player_backup_archive
from app.player_uninstall import (
    PLAYER_REMOVAL_DIRECTORY_PREFIX,
    PlayerUninstallError,
    export_and_remove_player_data,
    main,
)
from app.player_workspace import (
    PLAYER_WORKSPACE_LAYOUT_VERSION,
    PLAYER_WORKSPACE_MANIFEST_FILENAME,
    PlayerDataDirectoryError,
    PlayerWorkspace,
)
from app.storage.imported_hand_store import imported_hand_record_key
from test_current_learning_revalidation import configured_workspace
from test_imported_hand_store import pending_review_record, seed_interrupted_cascade


MAX_ARCHIVE_BYTES = 10 * 1024 * 1024


def _backup_path(tmp_path: Path, name: str = "player-backup.zip") -> Path:
    destination = tmp_path / "backups"
    destination.mkdir(mode=0o700, exist_ok=True)
    destination.chmod(0o700)
    return destination / name


def _remove(data_dir: Path, archive_path: Path, *, timeout: int = 1):
    return export_and_remove_player_data(
        data_dir,
        archive_path,
        max_archive_bytes=MAX_ARCHIVE_BYTES,
        lock_timeout_seconds=timeout,
    )


def _workspace_with_record(data_dir: Path) -> tuple[PlayerWorkspace, str]:
    workspace = PlayerWorkspace.open(data_dir)
    record = pending_review_record()
    record_key = imported_hand_record_key(record.identity)
    workspace.imported_hands.save(record_key, record)
    return workspace, record_key


def test_export_and_remove_publishes_verified_private_backup_first(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    _workspace, record_key = _workspace_with_record(data_dir)
    archive_path = _backup_path(tmp_path)

    result = _remove(data_dir, archive_path)

    assert result.completed is True
    assert result.archive_path == archive_path
    assert result.retained_data_path is None
    assert not data_dir.exists()
    assert archive_path.stat().st_mode & 0o077 == 0
    parsed = parse_player_backup_archive(
        archive_path.read_bytes(),
        max_archive_bytes=MAX_ARCHIVE_BYTES,
    )
    assert [snapshot.record_key for snapshot in parsed.records] == [record_key]
    assert not list(tmp_path.glob(f"{PLAYER_REMOVAL_DIRECTORY_PREFIX}*"))


def test_export_and_remove_includes_retained_grade_evidence(tmp_path: Path) -> None:
    data_dir = tmp_path / "player-data"
    workspace, record_key, retained, _ = configured_workspace(data_dir)
    workspace.persist_current_reference_activated_grade(record_key, retained)
    archive_path = _backup_path(tmp_path)

    result = _remove(data_dir, archive_path)

    assert result.completed is True
    assert not data_dir.exists()
    parsed = parse_player_backup_archive(
        archive_path.read_bytes(),
        max_archive_bytes=MAX_ARCHIVE_BYTES,
    )
    assert len(parsed.records[0].grade_artifacts) == 1
    assert parsed.records[0].grade_artifacts[0].grade == retained


def test_cli_requires_explicit_confirmation_before_opening_data(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "missing-player-data"

    assert (
        main(
            [str(_backup_path(tmp_path))],
            settings=Settings(data_dir=data_dir),
        )
        == 2
    )

    assert "--confirm-remove-data" in capsys.readouterr().err
    assert not data_dir.exists()


def test_cli_reports_successful_backup_and_removal(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data_dir = tmp_path / "player-data"
    PlayerWorkspace.open(data_dir)
    archive_path = _backup_path(tmp_path)

    assert (
        main(
            [str(archive_path), "--confirm-remove-data"],
            settings=Settings(
                data_dir=data_dir,
                max_backup_upload_bytes=MAX_ARCHIVE_BYTES,
            ),
        )
        == 0
    )

    output = capsys.readouterr()
    assert f"Verified backup: {archive_path}" in output.out
    assert "Player data removal completed" in output.out
    assert output.err == ""


@pytest.mark.parametrize("kind", ["missing", "manifestless", "symlink"])
def test_removal_requires_an_existing_non_symlinked_versioned_workspace(
    tmp_path: Path,
    kind: str,
) -> None:
    data_dir = tmp_path / "player-data"
    if kind == "manifestless":
        data_dir.mkdir(mode=0o700)
        (data_dir / "imported-hands").mkdir(mode=0o700)
    elif kind == "symlink":
        target = tmp_path / "real-player-data"
        PlayerWorkspace.open(target)
        data_dir.symlink_to(target, target_is_directory=True)
    archive_path = _backup_path(tmp_path)

    with pytest.raises(PlayerDataDirectoryError):
        _remove(data_dir, archive_path)

    assert not archive_path.exists()
    if kind == "missing":
        assert not data_dir.exists()
    elif kind == "manifestless":
        assert not (data_dir / PLAYER_WORKSPACE_MANIFEST_FILENAME).exists()
    else:
        assert data_dir.is_symlink()


def test_removal_rejects_output_inside_workspace(tmp_path: Path) -> None:
    data_dir = tmp_path / "player-data"
    PlayerWorkspace.open(data_dir)
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(mode=0o700)

    with pytest.raises(PlayerUninstallError, match="must be outside"):
        _remove(data_dir, backup_dir / "player-backup.zip")

    assert data_dir.is_dir()


def test_removal_rejects_existing_or_symlinked_output(tmp_path: Path) -> None:
    data_dir = tmp_path / "player-data"
    PlayerWorkspace.open(data_dir)
    archive_path = _backup_path(tmp_path)
    archive_path.write_bytes(b"existing")
    archive_path.chmod(0o600)

    with pytest.raises(PlayerUninstallError, match="already exists"):
        _remove(data_dir, archive_path)

    archive_path.unlink()
    archive_path.symlink_to(tmp_path / "missing-target")
    with pytest.raises(PlayerUninstallError, match="already exists"):
        _remove(data_dir, archive_path)
    assert data_dir.is_dir()


def test_removal_rejects_an_output_directory_writable_by_other_users(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    PlayerWorkspace.open(data_dir)
    destination = tmp_path / "shared-backups"
    destination.mkdir(mode=0o777)
    destination.chmod(0o777)

    with pytest.raises(PlayerUninstallError, match="writable by other users"):
        _remove(data_dir, destination / "player-backup.zip")

    assert data_dir.is_dir()


def test_removal_rejects_an_output_directory_with_an_extended_acl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "player-data"
    PlayerWorkspace.open(data_dir)
    archive_path = _backup_path(tmp_path)

    def reject_destination_acl(path: Path) -> None:
        if path == archive_path.parent:
            raise PlayerDataDirectoryError("injected extended ACL")

    monkeypatch.setattr(
        player_uninstall_module,
        "reject_macos_extended_acl",
        reject_destination_acl,
    )

    with pytest.raises(PlayerDataDirectoryError, match="extended ACL"):
        _remove(data_dir, archive_path)

    assert data_dir.is_dir()
    assert not archive_path.exists()


def test_removal_rejects_a_source_parent_writable_by_other_users(
    tmp_path: Path,
) -> None:
    shared_parent = tmp_path / "shared"
    shared_parent.mkdir(mode=0o777)
    shared_parent.chmod(0o777)
    data_dir = shared_parent / "player-data"
    PlayerWorkspace.open(data_dir)
    archive_path = _backup_path(tmp_path)

    with pytest.raises(PlayerUninstallError, match="writable by other users"):
        _remove(data_dir, archive_path)

    assert data_dir.is_dir()
    assert not archive_path.exists()


def test_removal_rejects_an_unknown_future_workspace_layout(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    PlayerWorkspace.open(data_dir)
    manifest_path = data_dir / PLAYER_WORKSPACE_MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(
            {
                "layout_version": PLAYER_WORKSPACE_LAYOUT_VERSION + 1,
                "schema": "poker-hero-player-workspace",
            }
        ),
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)
    archive_path = _backup_path(tmp_path)

    with pytest.raises(PlayerDataDirectoryError, match="unsupported layout"):
        _remove(data_dir, archive_path)

    assert data_dir.is_dir()
    assert not archive_path.exists()


def test_backup_publication_failure_leaves_source_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "player-data"
    _workspace_with_record(data_dir)
    archive_path = _backup_path(tmp_path)

    def fail_link(_source, _target, *args, **kwargs):
        raise OSError("injected backup publication failure")

    monkeypatch.setattr(player_uninstall_module.os, "link", fail_link)

    with pytest.raises(PlayerUninstallError, match="was not removed"):
        _remove(data_dir, archive_path)

    assert data_dir.is_dir()
    assert not archive_path.exists()
    assert not list(archive_path.parent.glob("*.tmp"))


@pytest.mark.parametrize("orphan_kind", ["record", "decision"])
def test_unexported_workspace_evidence_blocks_removal(
    tmp_path: Path,
    orphan_kind: str,
) -> None:
    data_dir = tmp_path / "player-data"
    workspace, record_key = _workspace_with_record(data_dir)
    if orphan_kind == "record":
        (workspace.imported_hands.records_dir / ("f" * 64)).mkdir(mode=0o700)
    else:
        decisions_dir = (
            workspace.imported_hands.records_dir / record_key / "decisions"
        )
        decisions_dir.mkdir(mode=0o700, exist_ok=True)
        orphan = decisions_dir / "unrecognized-audit.json"
        orphan.write_bytes(b"unexported evidence")
        orphan.chmod(0o600)
    archive_path = _backup_path(tmp_path)

    with pytest.raises(PlayerUninstallError, match="portable"):
        _remove(data_dir, archive_path)

    assert data_dir.is_dir()
    assert not archive_path.exists()


def test_rename_failure_keeps_source_and_verified_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "player-data"
    _workspace_with_record(data_dir)
    archive_path = _backup_path(tmp_path)

    def fail_rename(_source, _target):
        raise OSError("injected workspace rename failure")

    monkeypatch.setattr(player_uninstall_module.os, "rename", fail_rename)

    with pytest.raises(PlayerUninstallError, match="data remains"):
        _remove(data_dir, archive_path)

    assert data_dir.is_dir()
    assert parse_player_backup_archive(
        archive_path.read_bytes(),
        max_archive_bytes=MAX_ARCHIVE_BYTES,
    )


def test_interrupted_cascade_is_recovered_before_export_and_removal(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    PlayerWorkspace.open(data_dir)
    record = pending_review_record()
    record_key = imported_hand_record_key(record.identity)
    cascade_id = seed_interrupted_cascade(data_dir, record)
    archive_path = _backup_path(tmp_path)

    result = _remove(data_dir, archive_path)

    assert result.completed is True
    parsed = parse_player_backup_archive(
        archive_path.read_bytes(),
        max_archive_bytes=MAX_ARCHIVE_BYTES,
    )
    assert [snapshot.record_key for snapshot in parsed.records] == [record_key]
    assert cascade_id


def test_quarantined_recovery_evidence_blocks_removal(tmp_path: Path) -> None:
    data_dir = tmp_path / "player-data"
    workspace = PlayerWorkspace.open(data_dir)
    quarantine = (
        workspace.imported_hands.records_dir / ".cascade" / "corrupt" / "evidence"
    )
    quarantine.mkdir(parents=True)
    archive_path = _backup_path(tmp_path)

    with pytest.raises(PlayerUninstallError, match="recovery evidence"):
        _remove(data_dir, archive_path)

    assert quarantine.is_dir()
    assert not archive_path.exists()


def test_lock_contention_does_not_publish_or_remove(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    workspace = PlayerWorkspace.open(data_dir)
    archive_path = _backup_path(tmp_path)

    with workspace.data_lock.hold(exclusive=False):
        with pytest.raises(DataLockTimeoutError):
            _remove(data_dir, archive_path, timeout=0)

    assert data_dir.is_dir()
    assert not archive_path.exists()


def test_running_runtime_lifetime_lease_blocks_removal(tmp_path: Path) -> None:
    data_dir = tmp_path / "player-data"
    workspace = PlayerWorkspace.open(data_dir)
    archive_path = _backup_path(tmp_path)
    runtime_lease = player_runtime_lease(workspace.data_dir)
    descriptor = runtime_lease.acquire(exclusive=True)

    try:
        with pytest.raises(DataLockTimeoutError, match="runtime lifetime lease"):
            _remove(data_dir, archive_path, timeout=0)
    finally:
        runtime_lease.release(descriptor)

    assert data_dir.is_dir()
    assert not archive_path.exists()


def test_previous_interrupted_removal_is_reported_when_source_is_missing(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    PlayerWorkspace.open(data_dir)
    retained_path = player_uninstall_module._new_removal_path(data_dir)
    data_dir.rename(retained_path)
    archive_path = _backup_path(tmp_path)

    with pytest.raises(PlayerUninstallError, match=str(retained_path)):
        _remove(data_dir, archive_path)

    assert retained_path.is_dir()
    assert not archive_path.exists()


def test_waiting_removal_rescans_for_retained_data_under_the_lifetime_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "player-data"
    PlayerWorkspace.open(data_dir)
    archive_path = _backup_path(tmp_path)
    runtime_lease = player_runtime_lease(data_dir)
    descriptor = runtime_lease.acquire(exclusive=True)
    first_scan_completed = Event()
    real_scan = player_uninstall_module._retained_removal_paths

    def observe_scan(source: Path):
        paths = real_scan(source)
        first_scan_completed.set()
        return paths

    monkeypatch.setattr(
        player_uninstall_module,
        "_retained_removal_paths",
        observe_scan,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(_remove, data_dir, archive_path, timeout=2)
        try:
            assert first_scan_completed.wait(timeout=1)
            retained_path = player_uninstall_module._new_removal_path(data_dir)
            data_dir.rename(retained_path)
        finally:
            runtime_lease.release(descriptor)

        with pytest.raises(PlayerUninstallError, match=str(retained_path)):
            pending.result(timeout=2)

    assert retained_path.is_dir()
    assert not archive_path.exists()


def test_cleanup_failure_reports_the_recoverable_retained_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "player-data"
    _workspace_with_record(data_dir)
    archive_path = _backup_path(tmp_path)

    def fail_cleanup(_path: Path) -> None:
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(player_uninstall_module.shutil, "rmtree", fail_cleanup)

    result = _remove(data_dir, archive_path)

    assert result.completed is False
    assert result.retained_data_path is not None
    assert result.retained_data_path.is_dir()
    assert "manual cleanup" in str(result.warning)
    assert not data_dir.exists()
    assert parse_player_backup_archive(
        archive_path.read_bytes(),
        max_archive_bytes=MAX_ARCHIVE_BYTES,
    )


def test_post_rename_stat_failure_reports_the_retained_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "player-data"
    _workspace_with_record(data_dir)
    archive_path = _backup_path(tmp_path)
    real_stat = Path.stat

    def fail_removal_stat(path: Path, *args, **kwargs):
        if path.name.startswith(PLAYER_REMOVAL_DIRECTORY_PREFIX):
            raise OSError("injected removal stat failure")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_removal_stat)

    result = _remove(data_dir, archive_path)

    assert result.completed is False
    assert result.retained_data_path is not None
    assert "could not be inspected" in str(result.warning)
    assert not data_dir.exists()


def test_keyboard_interrupt_after_rename_reports_the_retained_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "player-data"
    _workspace_with_record(data_dir)
    archive_path = _backup_path(tmp_path)

    def interrupt_cleanup(_path: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(player_uninstall_module.shutil, "rmtree", interrupt_cleanup)

    result = _remove(data_dir, archive_path)

    assert result.completed is False
    assert result.retained_data_path is not None
    assert result.retained_data_path.is_dir()
    assert "interrupted" in str(result.warning)


def test_post_cleanup_fsync_failure_does_not_report_a_nonexistent_retained_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "player-data"
    _workspace_with_record(data_dir)
    archive_path = _backup_path(tmp_path)
    real_fsync = player_uninstall_module._fsync_directory
    calls = 0

    def fail_third_fsync(directory: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise PlayerUninstallError("injected final directory fsync failure")
        real_fsync(directory)

    monkeypatch.setattr(
        player_uninstall_module,
        "_fsync_directory",
        fail_third_fsync,
    )

    result = _remove(data_dir, archive_path)

    assert result.completed is False
    assert result.retained_data_path is None
    assert "injected final directory fsync failure" in str(result.warning)
    assert not data_dir.exists()
    assert not list(tmp_path.glob(f"{PLAYER_REMOVAL_DIRECTORY_PREFIX}*"))
