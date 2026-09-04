from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path

import pytest

import app.player_workspace as player_workspace_module
from app.player_workspace import (
    PLAYER_WORKSPACE_LAYOUT_VERSION,
    PLAYER_WORKSPACE_MANIFEST_FILENAME,
    PLAYER_WORKSPACE_SCHEMA,
    PlayerDataDirectoryError,
    PlayerWorkspace,
)
from app.storage.imported_hand_store import (
    FileImportedHandStore,
    imported_hand_record_key,
)
from app.storage.remote_reference_consent_store import (
    FileRemoteReferenceConsentStore,
    REMOTE_REFERENCE_CONSENT_FILENAME,
    RemoteReferenceConsentStorageError,
)
from test_imported_hand_store import pending_review_record, seed_interrupted_cascade


def _manifest_path(data_dir: Path) -> Path:
    return data_dir / PLAYER_WORKSPACE_MANIFEST_FILENAME


def _legacy_store(data_dir: Path) -> tuple[FileImportedHandStore, str]:
    store = FileImportedHandStore(data_dir)
    store.records_dir.chmod(0o700)
    record = pending_review_record()
    record_key = imported_hand_record_key(record.identity)
    store.save(record_key, record)
    return store, record_key


def _stored_payloads(records_dir: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(records_dir)): path.read_bytes()
        for path in records_dir.rglob("*")
        if path.is_file()
    }


def test_fresh_workspace_publishes_private_layout_v2_manifest(
    tmp_path: Path,
) -> None:
    workspace = PlayerWorkspace.open(tmp_path)
    manifest_path = _manifest_path(tmp_path)

    assert workspace.layout_version == PLAYER_WORKSPACE_LAYOUT_VERSION
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == {
        "layout_version": PLAYER_WORKSPACE_LAYOUT_VERSION,
        "schema": PLAYER_WORKSPACE_SCHEMA,
    }
    assert manifest_path.stat().st_mode & 0o077 == 0
    consent_path = tmp_path / REMOTE_REFERENCE_CONSENT_FILENAME
    assert json.loads(consent_path.read_text(encoding="utf-8")) == {
        "consent": None,
        "schema": "poker-hero-remote-reference-consent",
        "schema_version": 1,
    }
    assert consent_path.stat().st_mode & 0o077 == 0
    assert workspace.status_payload()["layout_version"] == (
        PLAYER_WORKSPACE_LAYOUT_VERSION
    )


def test_manifestless_store_adoption_preserves_every_retained_payload(
    tmp_path: Path,
) -> None:
    legacy_store, record_key = _legacy_store(tmp_path)
    before = _stored_payloads(legacy_store.records_dir)

    workspace = PlayerWorkspace.open(tmp_path)

    assert workspace.imported_hands.get(record_key) == legacy_store.get(record_key)
    assert _stored_payloads(workspace.imported_hands.records_dir) == before
    assert _manifest_path(tmp_path).is_file()


def test_workspace_manifest_is_not_rewritten_after_adoption(tmp_path: Path) -> None:
    first = PlayerWorkspace.open(tmp_path)
    manifest_path = _manifest_path(tmp_path)
    first_stat = manifest_path.stat()
    first_payload = manifest_path.read_bytes()

    second = PlayerWorkspace.open(tmp_path)

    second_stat = manifest_path.stat()
    assert first.layout_version == second.layout_version
    assert second_stat.st_ino == first_stat.st_ino
    assert second_stat.st_mtime_ns == first_stat.st_mtime_ns
    assert manifest_path.read_bytes() == first_payload


def test_concurrent_workspace_adoption_publishes_one_valid_manifest(
    tmp_path: Path,
) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        workspaces = list(executor.map(PlayerWorkspace.open, [tmp_path, tmp_path]))

    assert {workspace.layout_version for workspace in workspaces} == {
        PLAYER_WORKSPACE_LAYOUT_VERSION
    }
    assert json.loads(_manifest_path(tmp_path).read_text(encoding="utf-8")) == {
        "layout_version": PLAYER_WORKSPACE_LAYOUT_VERSION,
        "schema": PLAYER_WORKSPACE_SCHEMA,
    }


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b'{"layout_version":3,"schema":"poker-hero-player-workspace"}\n',
        b'{"layout_version":true,"schema":"poker-hero-player-workspace"}\n',
        b'{"extra":1,"layout_version":1,"schema":"poker-hero-player-workspace"}\n',
    ],
)
def test_workspace_rejects_malformed_or_unsupported_manifest(
    tmp_path: Path,
    payload: bytes,
) -> None:
    (tmp_path / "imported-hands").mkdir(mode=0o700)
    manifest_path = _manifest_path(tmp_path)
    manifest_path.write_bytes(payload)
    manifest_path.chmod(0o600)

    with pytest.raises(
        PlayerDataDirectoryError,
        match="malformed or uses an unsupported layout version",
    ):
        PlayerWorkspace.open(tmp_path)


def test_workspace_rejects_symlinked_or_shared_manifest(tmp_path: Path) -> None:
    (tmp_path / "imported-hands").mkdir(mode=0o700)
    target = tmp_path / "outside-manifest"
    target.write_bytes(player_workspace_module._player_workspace_manifest_payload())
    target.chmod(0o600)
    _manifest_path(tmp_path).symlink_to(target)

    with pytest.raises(PlayerDataDirectoryError, match="safely open"):
        PlayerWorkspace.open(tmp_path)

    _manifest_path(tmp_path).unlink()
    _manifest_path(tmp_path).write_bytes(
        player_workspace_module._player_workspace_manifest_payload()
    )
    _manifest_path(tmp_path).chmod(0o644)
    with pytest.raises(PlayerDataDirectoryError, match="readable only by its owner"):
        PlayerWorkspace.open(tmp_path)


def test_layout_v1_migrates_to_v2_without_touching_imported_hands(
    tmp_path: Path,
) -> None:
    legacy_store, record_key = _legacy_store(tmp_path)
    retained_before = _stored_payloads(legacy_store.records_dir)
    manifest_path = _manifest_path(tmp_path)
    manifest_path.write_bytes(
        player_workspace_module._player_workspace_manifest_payload(1)
    )
    manifest_path.chmod(0o600)

    workspace = PlayerWorkspace.open(tmp_path)

    assert workspace.layout_version == PLAYER_WORKSPACE_LAYOUT_VERSION
    assert workspace.imported_hands.get(record_key) == legacy_store.get(record_key)
    assert _stored_payloads(workspace.imported_hands.records_dir) == retained_before
    assert json.loads(manifest_path.read_text(encoding="utf-8"))[
        "layout_version"
    ] == PLAYER_WORKSPACE_LAYOUT_VERSION
    assert workspace.remote_reference_consent.load().consent is None


def test_layout_v1_consent_initialization_failure_keeps_v1_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "imported-hands").mkdir(mode=0o700)
    manifest_path = _manifest_path(tmp_path)
    manifest_path.write_bytes(
        player_workspace_module._player_workspace_manifest_payload(1)
    )
    manifest_path.chmod(0o600)

    def fail_initialization(_store: FileRemoteReferenceConsentStore):
        raise RemoteReferenceConsentStorageError("injected consent failure")

    monkeypatch.setattr(
        FileRemoteReferenceConsentStore,
        "initialize_empty",
        fail_initialization,
    )

    with pytest.raises(PlayerDataDirectoryError, match="injected consent failure"):
        PlayerWorkspace.open(tmp_path)
    assert json.loads(manifest_path.read_text(encoding="utf-8"))[
        "layout_version"
    ] == 1


def test_layout_v1_manifest_upgrade_failure_is_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "imported-hands").mkdir(mode=0o700)
    manifest_path = _manifest_path(tmp_path)
    manifest_path.write_bytes(
        player_workspace_module._player_workspace_manifest_payload(1)
    )
    manifest_path.chmod(0o600)
    real_replace = player_workspace_module._replace_player_workspace_manifest

    def fail_upgrade(_data_dir: Path) -> None:
        raise PlayerDataDirectoryError("injected manifest upgrade failure")

    monkeypatch.setattr(
        player_workspace_module,
        "_replace_player_workspace_manifest",
        fail_upgrade,
    )
    with pytest.raises(PlayerDataDirectoryError, match="injected manifest"):
        PlayerWorkspace.open(tmp_path)
    assert json.loads(manifest_path.read_text(encoding="utf-8"))[
        "layout_version"
    ] == 1
    assert (tmp_path / REMOTE_REFERENCE_CONSENT_FILENAME).is_file()

    monkeypatch.setattr(
        player_workspace_module,
        "_replace_player_workspace_manifest",
        real_replace,
    )
    workspace = PlayerWorkspace.open(tmp_path)
    assert workspace.layout_version == PLAYER_WORKSPACE_LAYOUT_VERSION
    assert workspace.remote_reference_consent.load().consent is None


def test_layout_v2_requires_valid_private_consent_state(tmp_path: Path) -> None:
    PlayerWorkspace.open(tmp_path)
    consent_path = tmp_path / REMOTE_REFERENCE_CONSENT_FILENAME

    consent_path.unlink()
    with pytest.raises(PlayerDataDirectoryError, match="Cannot safely open"):
        PlayerWorkspace.open(tmp_path)

    consent_path.write_text("not-json", encoding="utf-8")
    consent_path.chmod(0o600)
    with pytest.raises(PlayerDataDirectoryError, match="malformed or unsupported"):
        PlayerWorkspace.open(tmp_path)

    consent_path.write_text(
        '{"consent":null,"schema":"poker-hero-remote-reference-consent",'
        '"schema_version":1}\n',
        encoding="utf-8",
    )
    consent_path.chmod(0o644)
    with pytest.raises(PlayerDataDirectoryError, match="readable only by its owner"):
        PlayerWorkspace.open(tmp_path)


def test_layout_v2_rejects_a_symlinked_consent_state(tmp_path: Path) -> None:
    PlayerWorkspace.open(tmp_path)
    consent_path = tmp_path / REMOTE_REFERENCE_CONSENT_FILENAME
    target = tmp_path / "outside-consent"
    target.write_bytes(consent_path.read_bytes())
    target.chmod(0o600)
    consent_path.unlink()
    consent_path.symlink_to(target)

    with pytest.raises(PlayerDataDirectoryError, match="Cannot safely open"):
        PlayerWorkspace.open(tmp_path)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFOs")
def test_workspace_rejects_a_fifo_manifest_without_blocking(tmp_path: Path) -> None:
    (tmp_path / "imported-hands").mkdir(mode=0o700)
    os.mkfifo(_manifest_path(tmp_path), mode=0o600)

    with pytest.raises(PlayerDataDirectoryError, match="regular file"):
        PlayerWorkspace.open(tmp_path)


def test_versioned_workspace_does_not_recreate_a_missing_store(
    tmp_path: Path,
) -> None:
    PlayerWorkspace.open(tmp_path)
    (tmp_path / "imported-hands").rmdir()

    with pytest.raises(PlayerDataDirectoryError, match="missing its imported-hand store"):
        PlayerWorkspace.open(tmp_path)


def test_failed_manifest_publication_can_be_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_link = os.link

    def fail_manifest_link(source, target, *args, **kwargs):
        if Path(target).name == PLAYER_WORKSPACE_MANIFEST_FILENAME:
            raise OSError("injected manifest link failure")
        return real_link(source, target, *args, **kwargs)

    monkeypatch.setattr(player_workspace_module.os, "link", fail_manifest_link)
    with pytest.raises(PlayerDataDirectoryError, match="durably create"):
        PlayerWorkspace.open(tmp_path)
    assert not _manifest_path(tmp_path).exists()

    monkeypatch.setattr(player_workspace_module.os, "link", real_link)
    assert PlayerWorkspace.open(tmp_path).layout_version == (
        PLAYER_WORKSPACE_LAYOUT_VERSION
    )


def test_manifest_published_before_directory_fsync_is_adopted_on_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_fsync = player_workspace_module._fsync_player_data_dir

    def fail_directory_fsync(_data_dir: Path) -> None:
        raise OSError("injected directory fsync failure")

    monkeypatch.setattr(
        player_workspace_module,
        "_fsync_player_data_dir",
        fail_directory_fsync,
    )
    with pytest.raises(PlayerDataDirectoryError, match="durably create"):
        PlayerWorkspace.open(tmp_path)
    assert _manifest_path(tmp_path).is_file()

    monkeypatch.setattr(
        player_workspace_module,
        "_fsync_player_data_dir",
        real_fsync,
    )
    assert PlayerWorkspace.open(tmp_path).layout_version == (
        PLAYER_WORKSPACE_LAYOUT_VERSION
    )


def test_versioned_workspace_is_reread_beneath_the_startup_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    PlayerWorkspace.open(tmp_path)
    real_read = player_workspace_module._read_player_workspace_manifest
    read_count = 0

    def replace_with_future_manifest(data_dir: Path):
        nonlocal read_count
        read_count += 1
        if read_count == 2:
            _manifest_path(data_dir).write_text(
                '{"layout_version":3,"schema":"poker-hero-player-workspace"}\n',
                encoding="utf-8",
            )
            _manifest_path(data_dir).chmod(0o600)
        return real_read(data_dir)

    monkeypatch.setattr(
        player_workspace_module,
        "_read_player_workspace_manifest",
        replace_with_future_manifest,
    )

    with pytest.raises(
        PlayerDataDirectoryError,
        match="malformed or uses an unsupported layout version",
    ):
        PlayerWorkspace.open(tmp_path)


def test_current_workspace_rejects_a_downgrade_during_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    PlayerWorkspace.open(tmp_path)
    real_read = player_workspace_module._read_player_workspace_manifest
    read_count = 0

    def replace_with_v1_manifest(data_dir: Path):
        nonlocal read_count
        read_count += 1
        if read_count == 2:
            _manifest_path(data_dir).write_bytes(
                player_workspace_module._player_workspace_manifest_payload(1)
            )
            _manifest_path(data_dir).chmod(0o600)
        return real_read(data_dir)

    monkeypatch.setattr(
        player_workspace_module,
        "_read_player_workspace_manifest",
        replace_with_v1_manifest,
    )

    with pytest.raises(PlayerDataDirectoryError, match="changed during startup"):
        PlayerWorkspace.open(tmp_path)


def test_open_runtime_rejects_a_layout_changed_between_operations(
    tmp_path: Path,
) -> None:
    workspace = PlayerWorkspace.open(tmp_path)
    _manifest_path(tmp_path).write_text(
        '{"layout_version":3,"schema":"poker-hero-player-workspace"}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        PlayerDataDirectoryError,
        match="layout changed while this runtime was open",
    ):
        workspace.list_hand_records(limit=10, cursor=None)


def test_legacy_adoption_publishes_manifest_before_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = pending_review_record()
    record_key = imported_hand_record_key(record.identity)
    cascade_id = seed_interrupted_cascade(tmp_path, record)
    (tmp_path / "imported-hands").chmod(0o700)
    retained_before_recovery = _stored_payloads(tmp_path / "imported-hands")
    real_recover = FileImportedHandStore.recover

    def assert_manifest_then_recover(
        store: FileImportedHandStore,
    ) -> player_workspace_module.ImportedHandRecoveryReport:
        assert _manifest_path(tmp_path).is_file()
        assert _stored_payloads(store.records_dir) == retained_before_recovery
        return real_recover(store)

    monkeypatch.setattr(FileImportedHandStore, "recover", assert_manifest_then_recover)

    workspace = PlayerWorkspace.open(tmp_path)

    assert workspace.imported_hand_recovery.completed == (cascade_id,)
    assert workspace.imported_hands.get(record_key) == record
