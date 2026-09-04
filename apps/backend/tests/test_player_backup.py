from __future__ import annotations

import json
import zlib
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

import app.player_backup as player_backup_module
from app.application.imported_hand_lifecycle import ImportedHandLifecycleService
from app.application.reference_activation import (
    ReferenceActivationCatalog,
    bind_grade_to_active_reference,
)
from app.domain.imported_hands import ImportedHandRecord, extract_hero_decision_points
from app.player_backup import (
    PlayerBackupConflictError,
    PlayerBackupError,
    PlayerBackupExportError,
    PlayerBackupRestoreResult,
    PlayerBackupStorageError,
    build_player_backup_archive,
    parse_player_backup_archive,
    restore_player_backup,
)
from app.player_runtime import PLAYER_ORIGIN, PlayerCredentialError
from app.player_remote_references import PlayerRemoteReferenceConsentRequest
from app.player_workspace import (
    PLAYER_WORKSPACE_MANIFEST_FILENAME,
    PlayerDataDirectoryError,
    PlayerWorkspace,
)
from app.storage.cascade_journal import CascadeJournal
from app.storage.imported_hand_store import (
    ImportedHandNotFoundError,
    imported_hand_record_key,
    reference_activated_grade_artifact_filename,
)
from app.storage.learning_content_catalog_store import (
    LEARNING_CONTENT_CATALOG_FILENAME,
)
from app.storage.remote_reference_consent_store import (
    REMOTE_REFERENCE_CONSENT_FILENAME,
)
from app.storage.reference_activation_catalog_store import (
    REFERENCE_ACTIVATION_CATALOG_FILENAME,
)
from test_current_learning_revalidation import configured_workspace
from test_imported_hand_decisions import hero_fold_decision_record
from test_imported_hand_store import (
    approved_record,
    extraction_for,
    sample_identity,
    tombstone_record,
    withdrawn_record,
)
from test_learning_content_catalog_store import initial_catalog
from test_player_runtime import exchange_session, player_client
from test_reference_activation import activate, solved_readiness
from test_remote_references import provider_policy


def workspace_at(path: Path) -> PlayerWorkspace:
    return PlayerWorkspace.open(path)


def archive_bytes(workspace: PlayerWorkspace) -> bytes:
    archive = build_player_backup_archive(
        workspace,
        max_archive_bytes=10 * 1024 * 1024,
        lock_timeout_seconds=1,
    )
    try:
        return archive.read()
    finally:
        archive.close()


def save_record(
    workspace: PlayerWorkspace,
    record_key: str,
    record: ImportedHandRecord,
) -> None:
    workspace.imported_hands.save(record_key, record)
    if record.lifecycle.learning_eligible:
        workspace.imported_hands.save_decisions(
            record_key,
            extract_hero_decision_points(record),
        )


def restore(
    workspace: PlayerWorkspace,
    payload: bytes,
) -> PlayerBackupRestoreResult:
    return restore_player_backup(
        workspace,
        payload,
        max_archive_bytes=10 * 1024 * 1024,
        lock_timeout_seconds=1,
    )


def write_future_workspace_manifest(workspace: PlayerWorkspace) -> None:
    (workspace.data_dir / PLAYER_WORKSPACE_MANIFEST_FILENAME).write_text(
        '{"layout_version":5,"schema":"poker-hero-player-workspace"}\n',
        encoding="utf-8",
    )


def test_empty_player_backup_round_trips(tmp_path: Path) -> None:
    source = workspace_at(tmp_path / "source")
    payload = archive_bytes(source)
    with ZipFile(BytesIO(payload)) as archive:
        assert PLAYER_WORKSPACE_MANIFEST_FILENAME not in archive.namelist()
        assert REMOTE_REFERENCE_CONSENT_FILENAME not in archive.namelist()
        assert REFERENCE_ACTIVATION_CATALOG_FILENAME not in archive.namelist()
        assert LEARNING_CONTENT_CATALOG_FILENAME not in archive.namelist()

    parsed = parse_player_backup_archive(
        payload,
        max_archive_bytes=10 * 1024 * 1024,
    )
    target = workspace_at(tmp_path / "target")
    result = restore(target, payload)

    assert parsed.records == ()
    assert result.model_dump() == {
        "imported_records": 0,
        "reused_records": 0,
        "skipped_stale_records": 0,
        "imported_decision_artifacts": 0,
        "reused_decision_artifacts": 0,
        "removed_decision_artifacts": 0,
        "imported_grade_artifacts": 0,
        "reused_grade_artifacts": 0,
        "removed_grade_artifacts": 0,
        "total_records": 0,
    }


def test_backup_restore_never_copies_install_local_authorities(
    tmp_path: Path,
) -> None:
    policy = provider_policy()
    source = workspace_at(tmp_path / "source")
    source.accept_remote_reference_consent(
        policy=policy,
        request=PlayerRemoteReferenceConsentRequest(
            expected_consent_generation=0,
            expected_provider_policy_revision=policy.provider_policy_revision,
            expected_provider_policy_sha256=policy.semantic_digest(),
            expected_disclosure_revision=policy.disclosure.disclosure_revision,
            disclosure_accepted=True,
            network_dependency_accepted=True,
            retention_and_use_accepted=True,
        ),
        at=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc),
    )
    current_content = source.current_learning_content_catalog()
    source.publish_learning_content_catalog(
        initial_catalog(current_content.catalog),
        expected_catalog_revision=current_content.catalog.catalog_revision,
        expected_catalog_sha256=current_content.catalog_sha256,
    )

    payload = archive_bytes(source)
    with ZipFile(BytesIO(payload)) as archive:
        assert REMOTE_REFERENCE_CONSENT_FILENAME not in archive.namelist()
        assert LEARNING_CONTENT_CATALOG_FILENAME not in archive.namelist()

    target = workspace_at(tmp_path / "target")
    restore(target, payload)

    assert target.remote_reference_consent.load().consent is None
    assert target.learning_content_catalog.load().catalog.catalog_revision == 0


def test_player_backup_export_rejects_a_changed_workspace_layout(
    tmp_path: Path,
) -> None:
    workspace = workspace_at(tmp_path)
    write_future_workspace_manifest(workspace)

    with pytest.raises(
        PlayerDataDirectoryError,
        match="layout changed while this runtime was open",
    ):
        archive_bytes(workspace)


def test_player_backup_restore_rejects_a_changed_workspace_layout(
    tmp_path: Path,
) -> None:
    source = workspace_at(tmp_path / "source")
    payload = archive_bytes(source)
    target = workspace_at(tmp_path / "target")
    write_future_workspace_manifest(target)

    with pytest.raises(
        PlayerDataDirectoryError,
        match="layout changed while this runtime was open",
    ):
        restore(target, payload)


def test_player_backup_preserves_records_and_retained_decisions(
    tmp_path: Path,
) -> None:
    source = workspace_at(tmp_path / "source")
    identity = sample_identity(hand_ordinal=2)
    record = approved_record(identity)
    record_key = imported_hand_record_key(identity)
    save_record(source, record_key, record)
    expected_snapshot = source.imported_hands.backup_snapshot()

    payload = archive_bytes(source)
    target = workspace_at(tmp_path / "target")
    first = restore(target, payload)
    second = restore(target, payload)

    assert first.imported_records == 1
    assert first.imported_decision_artifacts == 1
    assert second.reused_records == 1
    assert second.reused_decision_artifacts == 1
    assert target.imported_hands.backup_snapshot() == expected_snapshot


def test_player_backup_preserves_historical_grade_artifacts(
    tmp_path: Path,
) -> None:
    source, record_key, retained, _ = configured_workspace(tmp_path / "source")
    source.persist_current_reference_activated_grade(record_key, retained)
    expected_snapshot = source.imported_hands.backup_snapshot()

    payload = archive_bytes(source)
    with ZipFile(BytesIO(payload)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == 2
        assert len(manifest["records"][0]["grade_artifacts"]) == 1

    target = workspace_at(tmp_path / "target")
    first = restore(target, payload)
    second = restore(target, payload)

    assert first.imported_grade_artifacts == 1
    assert second.reused_grade_artifacts == 1
    assert target.imported_hands.backup_snapshot() == expected_snapshot


def test_player_backup_rejects_grade_from_different_canonical_decision(
    tmp_path: Path,
) -> None:
    source, record_key, retained, _ = configured_workspace(tmp_path / "source")
    source.persist_current_reference_activated_grade(record_key, retained)
    payload = archive_bytes(source)
    alternate_decision = extract_hero_decision_points(
        hero_fold_decision_record()
    ).decision_points[0]
    alternate_readiness = solved_readiness(alternate_decision)
    alternate_catalog = activate(
        ReferenceActivationCatalog.empty(retained.catalog.catalog_id),
        alternate_readiness,
    )
    alternate = bind_grade_to_active_reference(
        alternate_catalog,
        alternate_readiness,
        coverage_band_id="cash.preflop.bb-defense.100bb",
    )
    alternate_payload = alternate.model_dump_json(indent=2).encode("utf-8")
    alternate_filename = reference_activated_grade_artifact_filename(alternate)
    changed_payload = BytesIO()

    with ZipFile(BytesIO(payload)) as original:
        manifest = json.loads(original.read("manifest.json"))
        artifact = manifest["records"][0]["grade_artifacts"][0]
        original_file = artifact["file"]
        artifact.update(
            {
                "filename": alternate_filename,
                "file": f"hands/{record_key}/grades/{alternate_filename}",
                "sha256": sha256(alternate_payload).hexdigest(),
                "size": len(alternate_payload),
            }
        )
        with ZipFile(changed_payload, mode="w", compression=ZIP_DEFLATED) as changed:
            for info in original.infolist():
                if info.filename in {"manifest.json", original_file}:
                    continue
                changed.writestr(info.filename, original.read(info))
            changed.writestr(artifact["file"], alternate_payload)
            changed.writestr(
                "manifest.json",
                (json.dumps(manifest, indent=2) + "\n").encode(),
            )

    with pytest.raises(PlayerBackupError, match="does not match its canonical"):
        parse_player_backup_archive(
            changed_payload.getvalue(),
            max_archive_bytes=10 * 1024 * 1024,
        )


def test_player_backup_decodes_legacy_schema_without_grades(
    tmp_path: Path,
) -> None:
    source = workspace_at(tmp_path / "source")
    identity = sample_identity(hand_ordinal=31)
    record_key = imported_hand_record_key(identity)
    save_record(source, record_key, approved_record(identity))
    payload = archive_bytes(source)
    legacy_payload = BytesIO()

    with ZipFile(BytesIO(payload)) as original:
        manifest = json.loads(original.read("manifest.json"))
        manifest["schema_version"] = 1
        for record in manifest["records"]:
            record.pop("grade_artifacts")
        with ZipFile(legacy_payload, mode="w", compression=ZIP_DEFLATED) as changed:
            for info in original.infolist():
                if info.filename == "manifest.json":
                    continue
                changed.writestr(info.filename, original.read(info))
            changed.writestr(
                "manifest.json",
                (json.dumps(manifest, indent=2) + "\n").encode(),
            )

    target = workspace_at(tmp_path / "target")
    result = restore(target, legacy_payload.getvalue())

    assert result.imported_records == 1
    assert result.imported_decision_artifacts == 1
    assert result.imported_grade_artifacts == 0


def test_player_backup_bounds_record_before_building_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = workspace_at(tmp_path / "source")
    identity = sample_identity(hand_ordinal=22)
    record_key = imported_hand_record_key(identity)
    save_record(source, record_key, approved_record(identity))
    record_size = len(source.imported_hands.backup_snapshot()[0].record_payload)
    monkeypatch.setattr(
        player_backup_module,
        "MAX_PLAYER_BACKUP_RECORD_BYTES",
        record_size - 1,
    )

    def unexpected_archive_build(*_args: object, **_kwargs: object) -> None:
        pytest.fail("oversized snapshot reached the archive builder")

    monkeypatch.setattr(
        player_backup_module,
        "_build_archive",
        unexpected_archive_build,
    )

    with pytest.raises(PlayerBackupExportError, match="allowed snapshot size"):
        build_player_backup_archive(
            source,
            max_archive_bytes=10 * 1024 * 1024,
            lock_timeout_seconds=1,
        )


def test_player_backup_bounds_aggregate_before_building_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = workspace_at(tmp_path / "source")
    identity = sample_identity(hand_ordinal=23)
    record_key = imported_hand_record_key(identity)
    save_record(source, record_key, approved_record(identity))
    snapshot = source.imported_hands.backup_snapshot()[0]
    payload_sizes = [
        len(snapshot.record_payload),
        *(len(artifact.payload) for artifact in snapshot.decision_artifacts),
    ]
    max_archive_bytes = max(payload_sizes)
    assert sum(payload_sizes) > max_archive_bytes
    monkeypatch.setattr(
        player_backup_module,
        "MAX_PLAYER_BACKUP_EXPANSION_RATIO",
        1,
    )

    def unexpected_archive_build(*_args: object, **_kwargs: object) -> None:
        pytest.fail("oversized snapshot reached the archive builder")

    monkeypatch.setattr(
        player_backup_module,
        "_build_archive",
        unexpected_archive_build,
    )

    with pytest.raises(PlayerBackupExportError, match="allowed total size"):
        build_player_backup_archive(
            source,
            max_archive_bytes=max_archive_bytes,
            lock_timeout_seconds=1,
        )


def test_restore_skips_an_older_deletion_generation(tmp_path: Path) -> None:
    identity = sample_identity(hand_ordinal=3)
    record_key = imported_hand_record_key(identity)
    source = workspace_at(tmp_path / "source")
    save_record(
        source,
        record_key,
        approved_record(identity, deletion_generation=1),
    )
    payload = archive_bytes(source)

    target = workspace_at(tmp_path / "target")
    tombstone = tombstone_record(generation=2)
    target.imported_hands.save(record_key, tombstone)
    result = restore(target, payload)

    assert result.skipped_stale_records == 1
    assert result.imported_records == 0
    assert target.imported_hands.get(record_key) == tombstone


def test_restore_refuses_to_reactivate_a_tombstone(tmp_path: Path) -> None:
    identity = sample_identity(hand_ordinal=4)
    record_key = imported_hand_record_key(identity)
    source = workspace_at(tmp_path / "source")
    save_record(
        source,
        record_key,
        approved_record(identity, deletion_generation=1),
    )
    payload = archive_bytes(source)

    target = workspace_at(tmp_path / "target")
    tombstone = tombstone_record(generation=1)
    target.imported_hands.save(record_key, tombstone)

    with pytest.raises(PlayerBackupConflictError, match="explicit merge or reimport"):
        restore(target, payload)
    assert target.imported_hands.get(record_key) == tombstone


def test_restore_refuses_an_unbound_newer_tombstone(tmp_path: Path) -> None:
    identity = sample_identity(hand_ordinal=14)
    record_key = imported_hand_record_key(identity)
    source = workspace_at(tmp_path / "source")
    source.imported_hands.save(record_key, tombstone_record(generation=1))
    payload = archive_bytes(source)

    target = workspace_at(tmp_path / "target")
    active = approved_record(identity)
    save_record(target, record_key, active)

    with pytest.raises(PlayerBackupConflictError, match="not bound"):
        restore(target, payload)
    assert target.imported_hands.get(record_key) == active
    assert target.imported_hands.list_decision_artifacts(record_key)


def test_restore_of_a_bound_tombstone_purges_decisions_atomically(
    tmp_path: Path,
) -> None:
    identity = sample_identity(hand_ordinal=15)
    record_key = imported_hand_record_key(identity)
    source = workspace_at(tmp_path / "source")
    tombstone = tombstone_record(generation=1)
    source.imported_hands.save(record_key, tombstone)
    payload = archive_bytes(source)

    target = workspace_at(tmp_path / "target")
    active = approved_record(identity)
    save_record(target, record_key, active)
    deletion_at = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    lifecycle = ImportedHandLifecycleService(
        store=target.imported_hands,
        extract=extract_hero_decision_points,
        now=lambda: deletion_at,
    )
    lifecycle.request_deletion(
        record_key,
        reason="player requested deletion",
        at=deletion_at,
    )

    result = restore(target, payload)

    assert result.removed_decision_artifacts == 1
    assert target.imported_hands.get(record_key) == tombstone
    assert target.imported_hands.list_decision_artifacts(record_key) == []


def test_restore_classifies_every_record_before_writing(tmp_path: Path) -> None:
    new_identity = sample_identity(hand_ordinal=5)
    conflict_identity = sample_identity(hand_ordinal=6)
    new_key = imported_hand_record_key(new_identity)
    conflict_key = imported_hand_record_key(conflict_identity)
    source = workspace_at(tmp_path / "source")
    save_record(source, new_key, approved_record(new_identity))
    save_record(source, conflict_key, approved_record(conflict_identity))
    payload = archive_bytes(source)

    target = workspace_at(tmp_path / "target")
    retained = withdrawn_record(conflict_identity)
    target.imported_hands.save(conflict_key, retained)

    with pytest.raises(PlayerBackupConflictError, match="explicit merge or reimport"):
        restore(target, payload)
    with pytest.raises(ImportedHandNotFoundError):
        target.imported_hands.get(new_key)
    assert target.imported_hands.get(conflict_key) == retained


def test_restore_rejects_a_merged_store_over_the_export_record_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_identity = sample_identity(hand_ordinal=18)
    source_key = imported_hand_record_key(source_identity)
    source = workspace_at(tmp_path / "source")
    source.imported_hands.save(source_key, withdrawn_record(source_identity))
    payload = archive_bytes(source)

    target_identity = sample_identity(hand_ordinal=19)
    target_key = imported_hand_record_key(target_identity)
    target_record = withdrawn_record(target_identity)
    target = workspace_at(tmp_path / "target")
    target.imported_hands.save(target_key, target_record)
    monkeypatch.setattr(player_backup_module, "MAX_PLAYER_BACKUP_RECORDS", 1)

    with pytest.raises(PlayerBackupConflictError, match="1-record limit"):
        restore(target, payload)
    with pytest.raises(ImportedHandNotFoundError):
        target.imported_hands.get(source_key)
    assert target.imported_hands.get(target_key) == target_record


def test_restore_preserves_local_artifacts_missing_from_the_archive(
    tmp_path: Path,
) -> None:
    identity = sample_identity(hand_ordinal=9)
    record = withdrawn_record(identity)
    record_key = imported_hand_record_key(identity)
    source = workspace_at(tmp_path / "source")
    source.imported_hands.save(record_key, record)
    payload = archive_bytes(source)

    target = workspace_at(tmp_path / "target")
    active = approved_record(identity)
    save_record(target, record_key, active)
    target.imported_hands.save(record_key, record)
    retained = target.imported_hands.backup_snapshot()[0].decision_artifacts

    result = restore(target, payload)

    assert result.reused_records == 1
    assert result.imported_decision_artifacts == 0
    assert result.reused_decision_artifacts == 0
    assert target.imported_hands.backup_snapshot()[0].decision_artifacts == retained


def test_restore_skips_an_older_tombstone_over_a_newer_active_generation(
    tmp_path: Path,
) -> None:
    identity = sample_identity(hand_ordinal=10)
    record_key = imported_hand_record_key(identity)
    source = workspace_at(tmp_path / "source")
    source.imported_hands.save(record_key, tombstone_record(generation=1))
    payload = archive_bytes(source)

    target = workspace_at(tmp_path / "target")
    active = approved_record(identity, deletion_generation=2)
    save_record(target, record_key, active)
    expected = target.imported_hands.backup_snapshot()

    result = restore(target, payload)

    assert result.skipped_stale_records == 1
    assert target.imported_hands.backup_snapshot() == expected


def test_multi_record_restore_recovers_after_a_partial_journal_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = workspace_at(tmp_path / "source")
    for ordinal in (11, 12):
        identity = sample_identity(hand_ordinal=ordinal)
        record = approved_record(identity)
        record_key = imported_hand_record_key(identity)
        save_record(source, record_key, record)
    expected = source.imported_hands.backup_snapshot()
    payload = archive_bytes(source)
    target_path = tmp_path / "target"
    target = workspace_at(target_path)

    original_commit_replace = CascadeJournal._commit_replace
    published = 0

    def fail_after_first_publish(self, record_key, relative, staged_file):
        nonlocal published
        published += 1
        if published == 2:
            raise OSError("simulated interrupted restore")
        return original_commit_replace(self, record_key, relative, staged_file)

    monkeypatch.setattr(CascadeJournal, "_commit_replace", fail_after_first_publish)
    with pytest.raises(PlayerBackupStorageError, match="journal recovery"):
        restore(target, payload)
    assert target.imported_hands.has_interrupted_writes()

    monkeypatch.setattr(CascadeJournal, "_commit_replace", original_commit_replace)
    recovered = workspace_at(target_path)
    assert recovered.imported_hand_recovery.completed
    assert recovered.imported_hands.backup_snapshot() == expected


def test_player_backup_rejects_duplicate_archive_paths(tmp_path: Path) -> None:
    source = workspace_at(tmp_path / "source")
    payload = archive_bytes(source)
    duplicate = BytesIO()
    with ZipFile(BytesIO(payload)) as original, ZipFile(
        duplicate,
        mode="w",
        compression=ZIP_DEFLATED,
    ) as changed:
        manifest = original.read("manifest.json")
        changed.writestr("manifest.json", manifest)
        with pytest.warns(UserWarning, match="Duplicate name"):
            changed.writestr("manifest.json", manifest)

    with pytest.raises(PlayerBackupError, match="duplicate paths"):
        parse_player_backup_archive(
            duplicate.getvalue(),
            max_archive_bytes=10 * 1024 * 1024,
        )


def test_player_backup_translates_corrupt_member_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = archive_bytes(workspace_at(tmp_path / "source"))

    def corrupt_read(_archive, _member, *_args, **_kwargs):
        raise zlib.error("corrupt deflate stream")

    monkeypatch.setattr(ZipFile, "read", corrupt_read)
    with pytest.raises(PlayerBackupError, match="member could not be read"):
        parse_player_backup_archive(
            payload,
            max_archive_bytes=10 * 1024 * 1024,
        )


def test_player_backup_rejects_checksum_tampering(tmp_path: Path) -> None:
    source = workspace_at(tmp_path / "source")
    identity = sample_identity(hand_ordinal=7)
    record_key = imported_hand_record_key(identity)
    save_record(source, record_key, approved_record(identity))
    payload = archive_bytes(source)
    changed_payload = BytesIO()
    record_path = f"hands/{record_key}/record.json"
    with ZipFile(BytesIO(payload)) as original, ZipFile(
        changed_payload,
        mode="w",
        compression=ZIP_DEFLATED,
    ) as changed:
        for info in original.infolist():
            member = original.read(info)
            if info.filename == record_path:
                member += b" "
            changed.writestr(info.filename, member)

    with pytest.raises(PlayerBackupError, match="record size does not match"):
        parse_player_backup_archive(
            changed_payload.getvalue(),
            max_archive_bytes=10 * 1024 * 1024,
        )


def test_player_backup_rejects_an_active_record_without_its_artifact(
    tmp_path: Path,
) -> None:
    source = workspace_at(tmp_path / "source")
    identity = sample_identity(hand_ordinal=16)
    record = approved_record(identity)
    record_key = imported_hand_record_key(identity)
    save_record(source, record_key, record)
    payload = archive_bytes(source)
    changed_payload = BytesIO()
    with ZipFile(BytesIO(payload)) as original:
        manifest = json.loads(original.read("manifest.json"))
        artifact_path = manifest["records"][0]["decision_artifacts"][0]["file"]
        manifest["records"][0]["decision_artifacts"] = []
        with ZipFile(changed_payload, mode="w", compression=ZIP_DEFLATED) as changed:
            for info in original.infolist():
                if info.filename in {"manifest.json", artifact_path}:
                    continue
                changed.writestr(info.filename, original.read(info))
            changed.writestr(
                "manifest.json",
                (json.dumps(manifest, indent=2) + "\n").encode(),
            )

    with pytest.raises(PlayerBackupError, match="is missing r1-g0.json"):
        parse_player_backup_archive(
            changed_payload.getvalue(),
            max_archive_bytes=10 * 1024 * 1024,
        )


def test_player_backup_rederives_the_active_decision_artifact(
    tmp_path: Path,
) -> None:
    source = workspace_at(tmp_path / "source")
    identity = sample_identity(hand_ordinal=17)
    record = approved_record(identity)
    record_key = imported_hand_record_key(identity)
    save_record(source, record_key, record)
    payload = archive_bytes(source)
    changed_payload = BytesIO()
    replacement = extraction_for(record).model_dump_json(indent=2).encode()
    with ZipFile(BytesIO(payload)) as original:
        manifest = json.loads(original.read("manifest.json"))
        artifact = manifest["records"][0]["decision_artifacts"][0]
        artifact["sha256"] = sha256(replacement).hexdigest()
        artifact["size"] = len(replacement)
        with ZipFile(changed_payload, mode="w", compression=ZIP_DEFLATED) as changed:
            for info in original.infolist():
                if info.filename == "manifest.json":
                    continue
                member = (
                    replacement
                    if info.filename == artifact["file"]
                    else original.read(info)
                )
                changed.writestr(info.filename, member)
            changed.writestr(
                "manifest.json",
                (json.dumps(manifest, indent=2) + "\n").encode(),
            )

    with pytest.raises(PlayerBackupError, match="does not match its canonical"):
        parse_player_backup_archive(
            changed_payload.getvalue(),
            max_archive_bytes=10 * 1024 * 1024,
        )


def test_player_backup_routes_require_session_and_csrf_and_round_trip(
    tmp_path: Path,
) -> None:
    source_client, source_runtime = player_client(tmp_path / "source")
    identity = sample_identity(hand_ordinal=8)
    record_key = imported_hand_record_key(identity)
    save_record(
        source_runtime.workspace,
        record_key,
        approved_record(identity),
    )

    assert source_client.get("/api/player/backups/export").status_code == 401
    source_session = exchange_session(source_client, source_runtime)
    exported = source_client.get(
        "/api/player/backups/export",
        headers={
            "Authorization": f"Bearer {source_session['session_token']}",
        },
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    assert "poker-hero-player-backup-" in exported.headers["content-disposition"]

    target_client, target_runtime = player_client(tmp_path / "target")
    target_session = exchange_session(target_client, target_runtime)
    authorization = {
        "Authorization": f"Bearer {target_session['session_token']}",
        "Origin": PLAYER_ORIGIN,
        "Content-Type": "application/zip",
    }
    missing_csrf = target_client.post(
        "/api/player/backups/restore",
        content=exported.content,
        headers=authorization,
    )
    assert missing_csrf.status_code == 403

    restored = target_client.post(
        "/api/player/backups/restore",
        content=exported.content,
        headers={
            **authorization,
            "X-Poker-CSRF-Token": str(target_session["csrf_token"]),
        },
    )
    assert restored.status_code == 200
    assert restored.json()["imported_records"] == 1
    assert target_runtime.workspace.imported_hands.get(record_key) == approved_record(
        identity
    )


def test_player_restore_route_enforces_the_streaming_size_limit(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path, max_player_backup_bytes=64)
    session = exchange_session(client, runtime)
    response = client.post(
        "/api/player/backups/restore",
        content=b"x" * 65,
        headers={
            "Authorization": f"Bearer {session['session_token']}",
            "Origin": PLAYER_ORIGIN,
            "X-Poker-CSRF-Token": str(session["csrf_token"]),
            "Content-Type": "application/zip",
        },
    )

    assert response.status_code == 400
    assert "64-byte limit" in response.json()["detail"]


def test_player_restore_route_rejects_malformed_zip_without_writes(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    identity = sample_identity(hand_ordinal=13)
    record = approved_record(identity)
    record_key = imported_hand_record_key(identity)
    save_record(runtime.workspace, record_key, record)
    expected = runtime.workspace.imported_hands.backup_snapshot()
    session = exchange_session(client, runtime)

    response = client.post(
        "/api/player/backups/restore",
        content=b"not a zip",
        headers={
            "Authorization": f"Bearer {session['session_token']}",
            "Origin": PLAYER_ORIGIN,
            "X-Poker-CSRF-Token": str(session["csrf_token"]),
            "Content-Type": "application/zip",
        },
    )

    assert response.status_code == 400
    assert runtime.workspace.imported_hands.backup_snapshot() == expected


def test_player_restore_storage_failure_disables_every_session_until_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runtime = player_client(tmp_path)
    session = exchange_session(client, runtime)
    other_session = exchange_session(client, runtime)
    pending_ticket = runtime.issue_launch_url().split("#ticket=", 1)[1]

    def fail_after_partial_publication(*_args: object, **_kwargs: object) -> None:
        raise PlayerBackupStorageError(
            "Player backup restore did not complete; restart the local runtime "
            "before retrying so journal recovery can finish"
        )

    monkeypatch.setattr(
        "app.player_runtime.restore_player_backup",
        fail_after_partial_publication,
    )
    authorization = f"Bearer {session['session_token']}"

    response = client.post(
        "/api/player/backups/restore",
        content=b"player backup archive",
        headers={
            "Authorization": authorization,
            "Origin": PLAYER_ORIGIN,
            "X-Poker-CSRF-Token": str(session["csrf_token"]),
            "Content-Type": "application/zip",
        },
    )

    assert response.status_code == 503
    assert "restart the local runtime" in response.json()["detail"]
    assert client.get(
        "/api/player/storage",
        headers={"Authorization": authorization},
    ).status_code == 401
    other_authorization = f"Bearer {other_session['session_token']}"
    assert client.get(
        "/api/player/backups/export",
        headers={"Authorization": other_authorization},
    ).status_code == 401
    assert client.post(
        "/api/player/backups/restore",
        content=b"another player backup archive",
        headers={
            "Authorization": other_authorization,
            "Origin": PLAYER_ORIGIN,
            "X-Poker-CSRF-Token": str(other_session["csrf_token"]),
            "Content-Type": "application/zip",
        },
    ).status_code == 401
    assert client.post(
        "/api/player/session",
        headers={
            "Authorization": f"Bearer {pending_ticket}",
            "Origin": PLAYER_ORIGIN,
        },
    ).status_code == 401
    with pytest.raises(PlayerCredentialError, match="requires a local runtime restart"):
        runtime.issue_launch_url()


def test_player_backup_export_reports_an_exclusive_lock_timeout(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path, backup_lock_timeout_seconds=1)
    session = exchange_session(client, runtime)
    descriptor = runtime.workspace.data_lock.acquire(exclusive=False)
    try:
        response = client.get(
            "/api/player/backups/export",
            headers={
                "Authorization": f"Bearer {session['session_token']}",
            },
        )
    finally:
        runtime.workspace.data_lock.release(descriptor)

    assert response.status_code == 409
    assert "waiting for an exclusive hold" in response.json()["detail"]
