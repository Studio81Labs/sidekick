from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from threading import Event

import pytest

import app.player_workspace as player_workspace_module
from app.data_lock import DATA_LOCK_FILENAME
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
from app.storage.learning_content_catalog_store import (
    LEARNING_CONTENT_CATALOG_FILENAME,
    LEARNING_CONTENT_CATALOG_ID,
)
from app.storage.remote_reference_consent_store import REMOTE_REFERENCE_CONSENT_FILENAME
from app.storage.reference_activation_catalog_store import (
    REFERENCE_ACTIVATION_CATALOG_FILENAME,
    REFERENCE_ACTIVATION_CATALOG_ID,
)
from test_imported_hand_store import pending_review_record, seed_interrupted_cascade


def _manifest_path(data_dir: Path) -> Path:
    return data_dir / PLAYER_WORKSPACE_MANIFEST_FILENAME


def _stored_payloads(records_dir: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(records_dir)): path.read_bytes()
        for path in records_dir.rglob("*")
        if path.is_file()
    }


def test_fresh_workspace_publishes_private_layout_v6_manifest(
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
    catalog_path = tmp_path / REFERENCE_ACTIVATION_CATALOG_FILENAME
    catalog_payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog_payload["catalog"]["catalog_id"] == (
        REFERENCE_ACTIVATION_CATALOG_ID
    )
    assert catalog_payload["catalog"]["catalog_revision"] == 0
    assert catalog_payload["catalog_sha256"] == (
        workspace.reference_activation_catalog.load().catalog_sha256
    )
    assert catalog_path.stat().st_mode & 0o077 == 0
    content_path = tmp_path / LEARNING_CONTENT_CATALOG_FILENAME
    content_payload = json.loads(content_path.read_text(encoding="utf-8"))
    assert content_payload["catalog"]["catalog_id"] == LEARNING_CONTENT_CATALOG_ID
    assert content_payload["catalog"]["catalog_revision"] == 0
    assert content_payload["catalog_sha256"] == (
        workspace.learning_content_catalog.load().catalog_sha256
    )
    assert content_path.stat().st_mode & 0o077 == 0
    assert workspace.status_payload()["layout_version"] == (
        PLAYER_WORKSPACE_LAYOUT_VERSION
    )


def test_nonempty_manifestless_directory_is_rejected_without_mutation(
    tmp_path: Path,
) -> None:
    retained_path = tmp_path / "retained-pre-current-data"
    retained_payload = b"do not adopt or mutate"
    retained_path.write_bytes(retained_payload)
    entries_before = {entry.name for entry in tmp_path.iterdir()}

    with pytest.raises(
        PlayerDataDirectoryError,
        match="nonempty but has no supported current workspace manifest",
    ):
        PlayerWorkspace.open(tmp_path)

    assert retained_path.read_bytes() == retained_payload
    assert {
        entry.name
        for entry in tmp_path.iterdir()
        if entry.name != DATA_LOCK_FILENAME
    } == entries_before


def test_open_existing_rejects_an_empty_manifestless_directory(tmp_path: Path) -> None:
    with pytest.raises(
        PlayerDataDirectoryError,
        match="missing its current workspace",
    ):
        PlayerWorkspace.open_existing(tmp_path)


def test_current_workspace_manifest_is_not_rewritten(tmp_path: Path) -> None:
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


def test_concurrent_empty_workspace_initialization_publishes_one_manifest(
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


def test_concurrent_opener_waits_for_current_manifest_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish_started = Event()
    partial_layout_seen = Event()
    allow_publication = Event()
    real_publish = player_workspace_module._publish_player_workspace_manifest
    real_has_retained_entries = (
        player_workspace_module._workspace_has_retained_entries
    )

    def pause_before_publication(data_dir: Path) -> None:
        publish_started.set()
        assert allow_publication.wait(timeout=5)
        real_publish(data_dir)

    def observe_partial_layout(data_dir: Path) -> bool:
        has_retained_entries = real_has_retained_entries(data_dir)
        if publish_started.is_set() and has_retained_entries:
            partial_layout_seen.set()
        return has_retained_entries

    monkeypatch.setattr(
        player_workspace_module,
        "_publish_player_workspace_manifest",
        pause_before_publication,
    )
    monkeypatch.setattr(
        player_workspace_module,
        "_workspace_has_retained_entries",
        observe_partial_layout,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        initializer = executor.submit(PlayerWorkspace.open, tmp_path)
        assert publish_started.wait(timeout=5)
        concurrent_opener = executor.submit(PlayerWorkspace.open, tmp_path)
        assert partial_layout_seen.wait(timeout=5)
        allow_publication.set()
        workspaces = (
            initializer.result(timeout=5),
            concurrent_opener.result(timeout=5),
        )

    assert {workspace.layout_version for workspace in workspaces} == {
        PLAYER_WORKSPACE_LAYOUT_VERSION
    }


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        *(
            player_workspace_module._player_workspace_manifest_payload(version)
            for version in (1, 2, 3, 4, 5, 7)
        ),
        b'{"layout_version":true,"schema":"poker-hero-player-workspace"}\n',
        b'{"extra":1,"layout_version":6,"schema":"poker-hero-player-workspace"}\n',
    ],
)
def test_workspace_rejects_malformed_or_unsupported_manifest_before_mutation(
    tmp_path: Path,
    payload: bytes,
) -> None:
    retained_path = tmp_path / "retained-pre-current-data"
    retained_payload = b"do not mutate incompatible workspace"
    retained_path.write_bytes(retained_payload)
    manifest_path = _manifest_path(tmp_path)
    manifest_path.write_bytes(payload)
    manifest_path.chmod(0o600)
    entries_before = {
        entry.name: entry.read_bytes()
        for entry in tmp_path.iterdir()
        if entry.is_file() and not entry.is_symlink()
    }

    with pytest.raises(
        PlayerDataDirectoryError,
        match="malformed or uses an unsupported layout version",
    ):
        PlayerWorkspace.open(tmp_path)

    assert {
        entry.name: entry.read_bytes()
        for entry in tmp_path.iterdir()
        if entry.is_file() and not entry.is_symlink()
    } == entries_before


def test_workspace_rejects_symlinked_or_shared_manifest(tmp_path: Path) -> None:
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


def test_current_layout_requires_valid_private_consent_state(tmp_path: Path) -> None:
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


def test_current_layout_rejects_a_symlinked_consent_state(tmp_path: Path) -> None:
    PlayerWorkspace.open(tmp_path)
    consent_path = tmp_path / REMOTE_REFERENCE_CONSENT_FILENAME
    target = tmp_path / "outside-consent"
    target.write_bytes(consent_path.read_bytes())
    target.chmod(0o600)
    consent_path.unlink()
    consent_path.symlink_to(target)

    with pytest.raises(PlayerDataDirectoryError, match="Cannot safely open"):
        PlayerWorkspace.open(tmp_path)


def test_current_layout_requires_valid_private_reference_catalog(tmp_path: Path) -> None:
    PlayerWorkspace.open(tmp_path)
    catalog_path = tmp_path / REFERENCE_ACTIVATION_CATALOG_FILENAME
    canonical_payload = catalog_path.read_bytes()

    catalog_path.unlink()
    with pytest.raises(PlayerDataDirectoryError, match="Cannot safely open"):
        PlayerWorkspace.open(tmp_path)

    catalog_path.write_text("not-json", encoding="utf-8")
    catalog_path.chmod(0o600)
    with pytest.raises(PlayerDataDirectoryError, match="malformed or unsupported"):
        PlayerWorkspace.open(tmp_path)

    catalog_path.write_bytes(canonical_payload)
    catalog_path.chmod(0o644)
    with pytest.raises(PlayerDataDirectoryError, match="only by its owner"):
        PlayerWorkspace.open(tmp_path)


def test_current_layout_rejects_a_symlinked_reference_catalog(tmp_path: Path) -> None:
    PlayerWorkspace.open(tmp_path)
    catalog_path = tmp_path / REFERENCE_ACTIVATION_CATALOG_FILENAME
    target = tmp_path / "outside-reference-catalog"
    target.write_bytes(catalog_path.read_bytes())
    target.chmod(0o600)
    catalog_path.unlink()
    catalog_path.symlink_to(target)

    with pytest.raises(PlayerDataDirectoryError, match="Cannot safely open"):
        PlayerWorkspace.open(tmp_path)


def test_current_layout_requires_valid_private_learning_content_catalog(
    tmp_path: Path,
) -> None:
    PlayerWorkspace.open(tmp_path)
    catalog_path = tmp_path / LEARNING_CONTENT_CATALOG_FILENAME
    canonical_payload = catalog_path.read_bytes()

    catalog_path.unlink()
    with pytest.raises(PlayerDataDirectoryError, match="Cannot safely open"):
        PlayerWorkspace.open(tmp_path)

    catalog_path.write_text("not-json", encoding="utf-8")
    catalog_path.chmod(0o600)
    with pytest.raises(PlayerDataDirectoryError, match="malformed or unsupported"):
        PlayerWorkspace.open(tmp_path)

    catalog_path.write_bytes(canonical_payload)
    catalog_path.chmod(0o644)
    with pytest.raises(PlayerDataDirectoryError, match="only by its owner"):
        PlayerWorkspace.open(tmp_path)


def test_current_layout_rejects_a_symlinked_learning_content_catalog(
    tmp_path: Path,
) -> None:
    PlayerWorkspace.open(tmp_path)
    catalog_path = tmp_path / LEARNING_CONTENT_CATALOG_FILENAME
    target = tmp_path / "outside-learning-content-catalog"
    target.write_bytes(catalog_path.read_bytes())
    target.chmod(0o600)
    catalog_path.unlink()
    catalog_path.symlink_to(target)

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


def test_failed_initialization_is_not_adopted_or_retried(
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
    entries_after_failure = {entry.name for entry in tmp_path.iterdir()}

    monkeypatch.setattr(player_workspace_module.os, "link", real_link)
    with pytest.raises(
        PlayerDataDirectoryError,
        match="nonempty but has no supported current workspace manifest",
    ):
        PlayerWorkspace.open(tmp_path)
    assert {entry.name for entry in tmp_path.iterdir()} == entries_after_failure


def test_manifest_published_before_directory_fsync_opens_as_current_on_retry(
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
                '{"layout_version":7,"schema":"poker-hero-player-workspace"}\n',
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

    with pytest.raises(
        PlayerDataDirectoryError,
        match="malformed or uses an unsupported layout version",
    ):
        PlayerWorkspace.open(tmp_path)


def test_open_runtime_rejects_a_layout_changed_between_operations(
    tmp_path: Path,
) -> None:
    workspace = PlayerWorkspace.open(tmp_path)
    _manifest_path(tmp_path).write_text(
        '{"layout_version":7,"schema":"poker-hero-player-workspace"}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        PlayerDataDirectoryError,
        match="layout changed while this runtime was open",
    ):
        workspace.list_hand_records(limit=10, cursor=None)


def test_current_workspace_recovers_interrupted_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    PlayerWorkspace.open(tmp_path)
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
