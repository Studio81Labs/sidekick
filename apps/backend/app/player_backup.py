"""Checksummed V2 backup and conflict-safe restore for the local player store."""

from __future__ import annotations

import json
import lzma
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Iterator, Literal, Self
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.application.reference_activation import ReferenceActivatedGrade

from app.domain.imported_hands import (
    HandDecisionExtraction,
    ImportedHandRecord,
    classify_restore,
    extract_hero_decision_points,
    extract_hero_decision_points_for_revision,
)
from app.player_workspace import PlayerWorkspace
from app.storage.cascade_journal import (
    CascadeCorruptionError,
    PendingCascadeError,
)
from app.storage.imported_hand_store import (
    DECISION_ARTIFACT_PATTERN,
    GRADE_ARTIFACT_PATTERN,
    MAX_PORTABLE_IMPORTED_HAND_ARTIFACT_BYTES,
    NO_CANONICAL_REVISION,
    FileImportedHandStore,
    ImportedHandGradeSnapshotArtifact,
    ImportedHandNotFoundError,
    ImportedHandRestoreWrite,
    ImportedHandSnapshotArtifact,
    ImportedHandSnapshotError,
    ImportedHandSnapshotLimitError,
    ImportedHandStoredSnapshot,
    imported_hand_record_key,
    reference_activated_grade_artifact_filename,
)


PLAYER_BACKUP_SCHEMA = "poker-hero-player-backup"
PLAYER_BACKUP_SCHEMA_VERSION = 4
DEFAULT_MAX_PLAYER_BACKUP_BYTES = 100 * 1024 * 1024
PLAYER_BACKUP_MEMORY_LIMIT = 8 * 1024 * 1024
PLAYER_BACKUP_STREAM_CHUNK_SIZE = 1024 * 1024
MAX_PLAYER_BACKUP_RECORDS = 10_000
MAX_PLAYER_BACKUP_ARTIFACTS_PER_RECORD = 1_000
MAX_PLAYER_BACKUP_ENTRIES = 50_000
MAX_PLAYER_BACKUP_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_PLAYER_BACKUP_RECORD_BYTES = 8 * 1024 * 1024
MAX_PLAYER_BACKUP_ARTIFACT_BYTES = MAX_PORTABLE_IMPORTED_HAND_ARTIFACT_BYTES
MAX_PLAYER_BACKUP_EXPANSION_RATIO = 4


class PlayerBackupError(RuntimeError):
    status_code = 400


class PlayerBackupConflictError(PlayerBackupError):
    status_code = 409


class PlayerBackupExportError(PlayerBackupError):
    status_code = 409


class PlayerBackupStorageError(PlayerBackupError):
    status_code = 503


class PlayerBackupRecoveryRequiredError(PlayerBackupError):
    status_code = 503


class _ArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    filename: str = Field(min_length=1, max_length=128)
    file: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=1)


class _RecordManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    record_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_file: str = Field(min_length=1, max_length=512)
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_size: int = Field(ge=1)
    decision_artifacts: list[_ArtifactManifest] = Field(
        max_length=MAX_PLAYER_BACKUP_ARTIFACTS_PER_RECORD
    )
    grade_artifacts: list[_ArtifactManifest] = Field(
        default_factory=list,
        max_length=MAX_PLAYER_BACKUP_ARTIFACTS_PER_RECORD,
    )

    @model_validator(mode="after")
    def validate_artifacts(self) -> Self:
        for label, artifacts in (
            ("decision", self.decision_artifacts),
            ("grade", self.grade_artifacts),
        ):
            filenames = [artifact.filename for artifact in artifacts]
            if len(filenames) != len(set(filenames)):
                raise ValueError(f"{label} artifact filenames must be unique")
            if filenames != sorted(filenames):
                raise ValueError(f"{label} artifacts must be sorted by filename")
        return self


class _PlayerBackupManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_name: Literal[PLAYER_BACKUP_SCHEMA] = Field(alias="schema")
    schema_version: Literal[PLAYER_BACKUP_SCHEMA_VERSION]
    exported_at: AwareDatetime
    record_count: int = Field(ge=0, le=MAX_PLAYER_BACKUP_RECORDS)
    records: list[_RecordManifest] = Field(max_length=MAX_PLAYER_BACKUP_RECORDS)

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version_type(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("schema version must be a JSON integer")
        return value

    @model_validator(mode="after")
    def validate_records(self) -> Self:
        if self.record_count != len(self.records):
            raise ValueError("record_count does not match records")
        keys = [record.record_key for record in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("record keys must be unique")
        if keys != sorted(keys):
            raise ValueError("records must be sorted by record key")
        for record in self.records:
            has_grade_field = "grade_artifacts" in record.model_fields_set
            if not has_grade_field:
                raise ValueError(
                    "schema version 4 records must declare grade artifacts"
                )
        paths = [
            *(record.record_file for record in self.records),
            *(
                artifact.file
                for record in self.records
                for artifact in record.decision_artifacts
            ),
            *(
                artifact.file
                for record in self.records
                for artifact in record.grade_artifacts
            ),
        ]
        if len(paths) != len(set(paths)):
            raise ValueError("archive member paths must be unique")
        return self


@dataclass(frozen=True)
class ParsedPlayerBackup:
    exported_at: datetime
    records: tuple[ImportedHandStoredSnapshot, ...]


class PlayerBackupRestoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    imported_records: int = Field(ge=0)
    reused_records: int = Field(ge=0)
    skipped_stale_records: int = Field(ge=0)
    imported_decision_artifacts: int = Field(ge=0)
    reused_decision_artifacts: int = Field(ge=0)
    removed_decision_artifacts: int = Field(ge=0)
    imported_grade_artifacts: int = Field(ge=0)
    reused_grade_artifacts: int = Field(ge=0)
    removed_grade_artifacts: int = Field(ge=0)
    total_records: int = Field(ge=0)


def build_player_backup_archive(
    workspace: PlayerWorkspace,
    *,
    max_archive_bytes: int = DEFAULT_MAX_PLAYER_BACKUP_BYTES,
    lock_timeout_seconds: int,
) -> BinaryIO:
    if max_archive_bytes <= 0:
        raise PlayerBackupExportError("Player backup size limit must be positive")
    try:
        with workspace.data_lock.hold(
            exclusive=True,
            timeout_seconds=lock_timeout_seconds,
        ):
            return _build_player_backup_archive_from_locked_workspace(
                workspace,
                max_archive_bytes=max_archive_bytes,
            )
    except ImportedHandSnapshotLimitError as exc:
        raise PlayerBackupExportError(str(exc)) from exc
    except (ImportedHandSnapshotError, OSError, ValidationError, ValueError) as exc:
        raise PlayerBackupExportError(
            "The player store cannot be exported until its invalid data is repaired"
        ) from exc


def _build_player_backup_archive_from_locked_workspace(
    workspace: PlayerWorkspace,
    *,
    max_archive_bytes: int,
) -> BinaryIO:
    """Build a snapshot while the caller owns the exclusive data-volume lock."""

    try:
        workspace.require_current_layout()
        if workspace.imported_hands.has_pending_recovery():
            raise PlayerBackupRecoveryRequiredError(
                "Player backup is unavailable while an interrupted lifecycle write"
                " awaits startup recovery; restart the local player runtime first"
            )
        snapshots = workspace.imported_hands.backup_snapshot(
            max_record_bytes=MAX_PLAYER_BACKUP_RECORD_BYTES,
            max_artifact_bytes=MAX_PLAYER_BACKUP_ARTIFACT_BYTES,
            max_total_bytes=(max_archive_bytes * MAX_PLAYER_BACKUP_EXPANSION_RATIO),
        )
        return _build_archive(
            snapshots,
            max_archive_bytes=max_archive_bytes,
        )
    except ImportedHandSnapshotLimitError as exc:
        raise PlayerBackupExportError(str(exc)) from exc
    except (ImportedHandSnapshotError, OSError, ValidationError, ValueError) as exc:
        raise PlayerBackupExportError(
            "The player store cannot be exported until its invalid data is repaired"
        ) from exc


def parse_player_backup_archive(
    archive_bytes: bytes,
    *,
    max_archive_bytes: int = DEFAULT_MAX_PLAYER_BACKUP_BYTES,
) -> ParsedPlayerBackup:
    if not archive_bytes:
        raise PlayerBackupError("Player backup ZIP is empty")
    if len(archive_bytes) > max_archive_bytes:
        raise PlayerBackupError(
            f"Player backup exceeds the configured {max_archive_bytes}-byte limit"
        )
    try:
        with ZipFile(BytesIO(archive_bytes)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_PLAYER_BACKUP_ENTRIES:
                raise PlayerBackupError("Player backup contains too many files")
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise PlayerBackupError("Player backup contains duplicate paths")
            if any(info.is_dir() for info in infos):
                raise PlayerBackupError(
                    "Player backup must not contain directory entries"
                )
            if any(info.flag_bits & 0x1 for info in infos):
                raise PlayerBackupError("Encrypted player backups are not supported")
            if any(
                info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}
                for info in infos
            ):
                raise PlayerBackupError(
                    "Player backup uses an unsupported compression method"
                )
            if sum(info.file_size for info in infos) > (
                max_archive_bytes * MAX_PLAYER_BACKUP_EXPANSION_RATIO
            ):
                raise PlayerBackupError(
                    "Player backup expands beyond the allowed size"
                )
            try:
                manifest_info = archive.getinfo("manifest.json")
            except KeyError as exc:
                raise PlayerBackupError(
                    "Player backup is missing manifest.json"
                ) from exc
            if manifest_info.file_size > MAX_PLAYER_BACKUP_MANIFEST_BYTES:
                raise PlayerBackupError(
                    "Player backup manifest exceeds the allowed size"
                )
            try:
                manifest = _PlayerBackupManifest.model_validate_json(
                    _read_member(archive, manifest_info)
                )
            except ValidationError as exc:
                first_error = exc.errors(include_url=False)[0]
                location = ".".join(str(part) for part in first_error["loc"])
                raise PlayerBackupError(
                    "Player backup manifest is invalid at "
                    f"{location}: {first_error['msg']}"
                ) from exc

            expected_paths = {
                "manifest.json",
                *(record.record_file for record in manifest.records),
                *(
                    artifact.file
                    for record in manifest.records
                    for artifact in record.decision_artifacts
                ),
                *(
                    artifact.file
                    for record in manifest.records
                    for artifact in record.grade_artifacts
                ),
            }
            if set(names) != expected_paths:
                raise PlayerBackupError(
                    "Player backup contains missing or unexpected files"
                )
            records = tuple(
                _read_record(archive, record) for record in manifest.records
            )
            return ParsedPlayerBackup(
                exported_at=manifest.exported_at,
                records=records,
            )
    except BadZipFile as exc:
        raise PlayerBackupError("Upload must be a valid player backup ZIP") from exc


def restore_player_backup(
    workspace: PlayerWorkspace,
    archive_bytes: bytes,
    *,
    max_archive_bytes: int = DEFAULT_MAX_PLAYER_BACKUP_BYTES,
    lock_timeout_seconds: int,
) -> PlayerBackupRestoreResult:
    backup = parse_player_backup_archive(
        archive_bytes,
        max_archive_bytes=max_archive_bytes,
    )
    try:
        with workspace.data_lock.hold(
            exclusive=True,
            timeout_seconds=lock_timeout_seconds,
        ):
            workspace.require_current_layout()
            if workspace.imported_hands.has_pending_recovery():
                raise PlayerBackupRecoveryRequiredError(
                    "Player backup restore is unavailable while an interrupted "
                    "lifecycle write awaits startup recovery; restart the "
                    "local player runtime first"
                )
            return _restore_parsed_backup(backup, workspace.imported_hands)
    except (ImportedHandSnapshotError, ValidationError, ValueError) as exc:
        raise PlayerBackupConflictError(
            "Player backup conflicts with the retained local audit data"
        ) from exc


def stream_player_backup(archive_file: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := archive_file.read(PLAYER_BACKUP_STREAM_CHUNK_SIZE):
            yield chunk
    finally:
        archive_file.close()


def _build_archive(
    snapshots: tuple[ImportedHandStoredSnapshot, ...],
    *,
    max_archive_bytes: int,
) -> BinaryIO:
    if len(snapshots) > MAX_PLAYER_BACKUP_RECORDS:
        raise PlayerBackupExportError(
            f"Player backups support at most {MAX_PLAYER_BACKUP_RECORDS} records"
        )
    record_entries: list[
        tuple[ImportedHandStoredSnapshot, _RecordManifest]
    ] = []
    uncompressed_size = 0
    archive_entry_count = 1  # manifest.json
    for snapshot in snapshots:
        if len(snapshot.record_payload) > MAX_PLAYER_BACKUP_RECORD_BYTES:
            raise PlayerBackupExportError(
                f"Player record {snapshot.record_key} is too large"
            )
        if (
            len(snapshot.decision_artifacts)
            > MAX_PLAYER_BACKUP_ARTIFACTS_PER_RECORD
        ):
            raise PlayerBackupExportError(
                f"Player record {snapshot.record_key} has too many decision artifacts"
            )
        if len(snapshot.grade_artifacts) > MAX_PLAYER_BACKUP_ARTIFACTS_PER_RECORD:
            raise PlayerBackupExportError(
                f"Player record {snapshot.record_key} has too many grade artifacts"
            )
        artifacts: list[_ArtifactManifest] = []
        sorted_artifacts = sorted(
            snapshot.decision_artifacts,
            key=lambda artifact: artifact.filename,
        )
        for artifact in sorted_artifacts:
            if len(artifact.payload) > MAX_PLAYER_BACKUP_ARTIFACT_BYTES:
                raise PlayerBackupExportError(
                    "Decision artifact "
                    f"{snapshot.record_key}/{artifact.filename} is too large"
                )
            artifacts.append(
                _ArtifactManifest(
                    filename=artifact.filename,
                    file=(
                        f"hands/{snapshot.record_key}/decisions/"
                        f"{artifact.filename}"
                    ),
                    sha256=sha256(artifact.payload).hexdigest(),
                    size=len(artifact.payload),
                )
            )
            uncompressed_size += len(artifact.payload)
            archive_entry_count += 1
            if archive_entry_count > MAX_PLAYER_BACKUP_ENTRIES:
                raise PlayerBackupExportError(
                    "Player backup contains too many files"
                )
        grade_artifacts: list[_ArtifactManifest] = []
        sorted_grades = sorted(
            snapshot.grade_artifacts,
            key=lambda artifact: artifact.filename,
        )
        for artifact in sorted_grades:
            if len(artifact.payload) > MAX_PLAYER_BACKUP_ARTIFACT_BYTES:
                raise PlayerBackupExportError(
                    "Grade artifact "
                    f"{snapshot.record_key}/{artifact.filename} is too large"
                )
            grade_artifacts.append(
                _ArtifactManifest(
                    filename=artifact.filename,
                    file=f"hands/{snapshot.record_key}/grades/{artifact.filename}",
                    sha256=sha256(artifact.payload).hexdigest(),
                    size=len(artifact.payload),
                )
            )
            uncompressed_size += len(artifact.payload)
            archive_entry_count += 1
            if archive_entry_count > MAX_PLAYER_BACKUP_ENTRIES:
                raise PlayerBackupExportError(
                    "Player backup contains too many files"
                )
        record_entry = _RecordManifest(
            record_key=snapshot.record_key,
            record_file=f"hands/{snapshot.record_key}/record.json",
            record_sha256=sha256(snapshot.record_payload).hexdigest(),
            record_size=len(snapshot.record_payload),
            decision_artifacts=artifacts,
            grade_artifacts=grade_artifacts,
        )
        uncompressed_size += len(snapshot.record_payload)
        archive_entry_count += 1
        if archive_entry_count > MAX_PLAYER_BACKUP_ENTRIES:
            raise PlayerBackupExportError("Player backup contains too many files")
        record_entries.append((snapshot, record_entry))

    manifest = {
        "schema": PLAYER_BACKUP_SCHEMA,
        "schema_version": PLAYER_BACKUP_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(record_entries),
        "records": [
            entry.model_dump(mode="json") for _snapshot, entry in record_entries
        ],
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    if len(manifest_bytes) > MAX_PLAYER_BACKUP_MANIFEST_BYTES:
        raise PlayerBackupExportError(
            "Player backup manifest exceeds the allowed size"
        )
    uncompressed_size += len(manifest_bytes)
    if uncompressed_size > max_archive_bytes * MAX_PLAYER_BACKUP_EXPANSION_RATIO:
        raise PlayerBackupExportError(
            f"Player backup exceeds the configured {max_archive_bytes}-byte limit"
        )

    archive_file = SpooledTemporaryFile(
        max_size=PLAYER_BACKUP_MEMORY_LIMIT,
        mode="w+b",
    )
    try:
        with ZipFile(archive_file, mode="w", compression=ZIP_DEFLATED) as archive:
            for snapshot, entry in record_entries:
                archive.writestr(entry.record_file, snapshot.record_payload)
                _ensure_archive_size(archive_file, max_archive_bytes)
                artifacts_by_name = {
                    artifact.filename: artifact
                    for artifact in snapshot.decision_artifacts
                }
                for artifact_entry in entry.decision_artifacts:
                    archive.writestr(
                        artifact_entry.file,
                        artifacts_by_name[artifact_entry.filename].payload,
                    )
                    _ensure_archive_size(archive_file, max_archive_bytes)
                grades_by_name = {
                    artifact.filename: artifact
                    for artifact in snapshot.grade_artifacts
                }
                for artifact_entry in entry.grade_artifacts:
                    archive.writestr(
                        artifact_entry.file,
                        grades_by_name[artifact_entry.filename].payload,
                    )
                    _ensure_archive_size(archive_file, max_archive_bytes)
            archive.writestr("manifest.json", manifest_bytes)
        _ensure_archive_size(archive_file, max_archive_bytes)
        archive_file.seek(0)
        return archive_file
    except Exception:
        archive_file.close()
        raise


def _read_record(
    archive: ZipFile,
    entry: _RecordManifest,
) -> ImportedHandStoredSnapshot:
    expected_record_file = f"hands/{entry.record_key}/record.json"
    if entry.record_file != expected_record_file:
        raise PlayerBackupError(
            f"Player backup record path is invalid for {entry.record_key}"
        )
    record_info = _member_info(
        archive,
        entry.record_file,
        MAX_PLAYER_BACKUP_RECORD_BYTES,
        "record",
    )
    if record_info.file_size != entry.record_size:
        raise PlayerBackupError(
            f"Player backup record size does not match for {entry.record_key}"
        )
    record_payload = _read_member(archive, record_info)
    if sha256(record_payload).hexdigest() != entry.record_sha256:
        raise PlayerBackupError(
            f"Player backup checksum failed for record {entry.record_key}"
        )
    try:
        record = ImportedHandRecord.model_validate_json(record_payload)
    except ValidationError as exc:
        raise PlayerBackupError(
            f"Player backup record {entry.record_key} is invalid"
        ) from exc
    if (
        record.identity is not None
        and imported_hand_record_key(record.identity) != entry.record_key
    ):
        raise PlayerBackupError(
            f"Player backup record identity does not match {entry.record_key}"
        )

    artifacts = tuple(
        _read_artifact(archive, entry.record_key, artifact, record=record)
        for artifact in entry.decision_artifacts
    )
    grade_artifacts = tuple(
        _read_grade_artifact(archive, entry.record_key, artifact, record=record)
        for artifact in entry.grade_artifacts
    )
    if record.lifecycle.status == "deleted" and (artifacts or grade_artifacts):
        raise PlayerBackupError(
            f"Deleted player record {entry.record_key} contains derived artifacts"
        )
    _validate_active_artifact(entry.record_key, record, artifacts)
    return ImportedHandStoredSnapshot(
        record_key=entry.record_key,
        record_payload=record_payload,
        record=record,
        decision_artifacts=artifacts,
        grade_artifacts=grade_artifacts,
    )


def _read_artifact(
    archive: ZipFile,
    record_key: str,
    entry: _ArtifactManifest,
    *,
    record: ImportedHandRecord,
) -> ImportedHandSnapshotArtifact:
    match = DECISION_ARTIFACT_PATTERN.fullmatch(entry.filename)
    if match is None:
        raise PlayerBackupError(
            f"Player backup decision filename is invalid for {record_key}"
        )
    expected_file = f"hands/{record_key}/decisions/{entry.filename}"
    if entry.file != expected_file:
        raise PlayerBackupError(
            f"Player backup decision path is invalid for {record_key}"
        )
    info = _member_info(
        archive,
        entry.file,
        MAX_PLAYER_BACKUP_ARTIFACT_BYTES,
        "decision artifact",
    )
    if info.file_size != entry.size:
        raise PlayerBackupError(
            f"Player backup decision size does not match for {record_key}"
        )
    payload = _read_member(archive, info)
    if sha256(payload).hexdigest() != entry.sha256:
        raise PlayerBackupError(
            f"Player backup checksum failed for decision {record_key}/{entry.filename}"
        )
    try:
        extraction = HandDecisionExtraction.model_validate_json(payload)
    except ValidationError as exc:
        raise PlayerBackupError(
            f"Player backup decision {record_key}/{entry.filename} is invalid"
        ) from exc
    if (
        extraction.identity is not None
        and imported_hand_record_key(extraction.identity) != record_key
    ):
        raise PlayerBackupError(
            f"Player backup decision identity does not match {record_key}"
        )
    if extraction.identity != record.identity:
        raise PlayerBackupError(
            f"Player backup decision {entry.filename} does not match its record"
        )
    revision = int(match.group("revision"))
    generation = int(match.group("generation"))
    if generation != extraction.deletion_generation:
        raise PlayerBackupError(
            f"Player backup decision generation does not match {entry.filename}"
        )
    if generation > record.lifecycle.deletion_generation:
        raise PlayerBackupError(
            f"Player backup decision {entry.filename} is from a future generation"
        )
    if (
        extraction.canonical_revision is not None
        and revision != extraction.canonical_revision
    ):
        raise PlayerBackupError(
            f"Player backup decision revision does not match {entry.filename}"
        )
    if (
        extraction.rejection == "not_active"
        and revision != NO_CANONICAL_REVISION
    ):
        raise PlayerBackupError(
            f"Player backup decision {entry.filename} must use revision 0"
        )
    if extraction.identity is not None and record.identity is None:
        raise PlayerBackupError(
            f"Player backup decision {entry.filename} has no retained record identity"
        )
    retained_revisions = {
        retained.revision for retained in record.canonical_revisions
    }
    if (
        revision != NO_CANONICAL_REVISION
        and revision not in retained_revisions
    ):
        raise PlayerBackupError(
            f"Player backup decision {entry.filename} names an unknown revision"
        )
    return ImportedHandSnapshotArtifact(
        filename=entry.filename,
        payload=payload,
        extraction=extraction,
    )


def _read_grade_artifact(
    archive: ZipFile,
    record_key: str,
    entry: _ArtifactManifest,
    *,
    record: ImportedHandRecord,
) -> ImportedHandGradeSnapshotArtifact:
    if GRADE_ARTIFACT_PATTERN.fullmatch(entry.filename) is None:
        raise PlayerBackupError(
            f"Player backup grade filename is invalid for {record_key}"
        )
    expected_file = f"hands/{record_key}/grades/{entry.filename}"
    if entry.file != expected_file:
        raise PlayerBackupError(
            f"Player backup grade path is invalid for {record_key}"
        )
    info = _member_info(
        archive,
        entry.file,
        MAX_PLAYER_BACKUP_ARTIFACT_BYTES,
        "grade artifact",
    )
    if info.file_size != entry.size:
        raise PlayerBackupError(
            f"Player backup grade size does not match for {record_key}"
        )
    payload = _read_member(archive, info)
    if sha256(payload).hexdigest() != entry.sha256:
        raise PlayerBackupError(
            f"Player backup checksum failed for grade {record_key}/{entry.filename}"
        )
    try:
        grade = ReferenceActivatedGrade.model_validate_json(payload)
        expected_filename = reference_activated_grade_artifact_filename(grade)
    except (ValidationError, ValueError) as exc:
        raise PlayerBackupError(
            f"Player backup grade {record_key}/{entry.filename} is invalid"
        ) from exc
    if entry.filename != expected_filename:
        raise PlayerBackupError(
            f"Player backup grade identity does not match {entry.filename}"
        )
    decision = grade.readiness.decision_snapshot.restore()
    if imported_hand_record_key(decision.identity) != record_key:
        raise PlayerBackupError(
            f"Player backup grade hand identity does not match {record_key}"
        )
    if decision.identity != record.identity:
        raise PlayerBackupError(
            f"Player backup grade {entry.filename} does not match its record"
        )
    if decision.deletion_generation > record.lifecycle.deletion_generation:
        raise PlayerBackupError(
            f"Player backup grade {entry.filename} is from a future generation"
        )
    if decision.canonical_revision not in {
        retained.revision for retained in record.canonical_revisions
    }:
        raise PlayerBackupError(
            f"Player backup grade {entry.filename} names an unknown revision"
        )
    try:
        expected = extract_hero_decision_points_for_revision(
            record,
            canonical_revision=decision.canonical_revision,
            deletion_generation=decision.deletion_generation,
        )
    except (ValidationError, ValueError) as exc:
        raise PlayerBackupError(
            f"Player backup grade {entry.filename} cannot be re-derived"
        ) from exc
    if (
        expected.outcome != "decisions"
        or decision.decision_index >= len(expected.decision_points)
        or expected.decision_points[decision.decision_index] != decision
    ):
        raise PlayerBackupError(
            f"Player backup grade {entry.filename} does not match its canonical revision"
        )
    return ImportedHandGradeSnapshotArtifact(
        filename=entry.filename,
        payload=payload,
        grade=grade,
    )


def _restore_parsed_backup(
    backup: ParsedPlayerBackup,
    store: FileImportedHandStore,
) -> PlayerBackupRestoreResult:
    resulting_record_keys = set(store.list_keys()) | {
        snapshot.record_key for snapshot in backup.records
    }
    if len(resulting_record_keys) > MAX_PLAYER_BACKUP_RECORDS:
        raise PlayerBackupConflictError(
            "Restoring this player backup would exceed the "
            f"{MAX_PLAYER_BACKUP_RECORDS}-record limit"
        )
    writes: list[ImportedHandRestoreWrite] = []
    imported_records = 0
    reused_records = 0
    skipped_stale_records = 0
    imported_artifacts = 0
    reused_artifacts = 0
    removed_artifacts = 0
    imported_grade_artifacts = 0
    reused_grade_artifacts = 0
    removed_grade_artifacts = 0

    for snapshot in backup.records:
        try:
            current = store.get(snapshot.record_key)
        except ImportedHandNotFoundError:
            current = None

        if current is None:
            write_record = True
            imported_records += 1
        elif current == snapshot.record:
            write_record = False
            reused_records += 1
        else:
            disposition = classify_restore(current, snapshot.record)
            if disposition.kind in {"stale_record", "stale_deletion_generation"}:
                skipped_stale_records += 1
                continue
            if disposition.kind != "allow":
                raise PlayerBackupConflictError(
                    "Player backup record "
                    f"{snapshot.record_key} requires an explicit merge or reimport"
                )
            if (
                snapshot.record.lifecycle.status == "deleted"
                and not (
                    current.lifecycle.status == "deleted"
                    or (
                        current.lifecycle.status == "deletion_pending"
                        and current.lifecycle.deletion_generation
                        == snapshot.record.lifecycle.deletion_generation
                    )
                )
            ):
                raise PlayerBackupConflictError(
                    "Player backup tombstone "
                    f"{snapshot.record_key} is not bound to a matching "
                    "deletion-pending record"
                )
            write_record = True
            imported_records += 1

        artifacts_to_write: list[ImportedHandSnapshotArtifact] = []
        for artifact in snapshot.decision_artifacts:
            existing = store.existing_decision_artifact_payload(
                snapshot.record_key,
                artifact.filename,
            )
            if existing is None:
                artifacts_to_write.append(artifact)
                imported_artifacts += 1
            elif existing == artifact.payload:
                reused_artifacts += 1
            else:
                raise PlayerBackupConflictError(
                    "Player backup decision artifact "
                    f"{snapshot.record_key}/{artifact.filename} conflicts with retained data"
                )

        grades_to_write: list[ImportedHandGradeSnapshotArtifact] = []
        for artifact in snapshot.grade_artifacts:
            existing = store.existing_grade_artifact_payload(
                snapshot.record_key,
                artifact.filename,
            )
            if existing is None:
                grades_to_write.append(artifact)
                imported_grade_artifacts += 1
            elif existing == artifact.payload:
                reused_grade_artifacts += 1
            else:
                raise PlayerBackupConflictError(
                    "Player backup grade artifact "
                    f"{snapshot.record_key}/{artifact.filename} conflicts with retained data"
                )

        delete_artifacts: tuple[str, ...] = ()
        delete_grades: tuple[str, ...] = ()
        if snapshot.record.lifecycle.status == "deleted":
            delete_artifacts = tuple(
                filename
                for _revision, _generation, filename in (
                    store.list_decision_artifacts(snapshot.record_key)
                )
            )
            if current is None and delete_artifacts:
                raise PlayerBackupConflictError(
                    "Player backup tombstone "
                    f"{snapshot.record_key} cannot delete unbound local artifacts"
                )
            removed_artifacts += len(delete_artifacts)
            delete_grades = tuple(
                filename
                for _revision, _generation, _index, filename in (
                    store.list_reference_activated_grade_artifacts(
                        snapshot.record_key
                    )
                )
            )
            if current is None and delete_grades:
                raise PlayerBackupConflictError(
                    "Player backup tombstone "
                    f"{snapshot.record_key} cannot delete unbound local grades"
                )
            removed_grade_artifacts += len(delete_grades)

        if (
            write_record
            or artifacts_to_write
            or grades_to_write
            or delete_artifacts
            or delete_grades
        ):
            writes.append(
                ImportedHandRestoreWrite(
                    snapshot=snapshot,
                    write_record=write_record,
                    decision_artifacts=tuple(artifacts_to_write),
                    delete_decision_artifacts=delete_artifacts,
                    grade_artifacts=tuple(grades_to_write),
                    delete_grade_artifacts=delete_grades,
                )
            )

    try:
        store.apply_backup_restore(writes)
    except (CascadeCorruptionError, OSError, PendingCascadeError) as exc:
        raise PlayerBackupStorageError(
            "Player backup restore did not complete; restart the local runtime "
            "before retrying so journal recovery can finish"
        ) from exc
    return PlayerBackupRestoreResult(
        imported_records=imported_records,
        reused_records=reused_records,
        skipped_stale_records=skipped_stale_records,
        imported_decision_artifacts=imported_artifacts,
        reused_decision_artifacts=reused_artifacts,
        removed_decision_artifacts=removed_artifacts,
        imported_grade_artifacts=imported_grade_artifacts,
        reused_grade_artifacts=reused_grade_artifacts,
        removed_grade_artifacts=removed_grade_artifacts,
        total_records=len(store.list_keys()),
    )


def _validate_active_artifact(
    record_key: str,
    record: ImportedHandRecord,
    artifacts: tuple[ImportedHandSnapshotArtifact, ...],
) -> None:
    if not record.lifecycle.learning_eligible:
        return
    active_revision = record.lifecycle.active_canonical_revision
    assert active_revision is not None
    active_filename = (
        f"r{active_revision}-g{record.lifecycle.deletion_generation}.json"
    )
    active = next(
        (
            artifact.extraction
            for artifact in artifacts
            if artifact.filename == active_filename
        ),
        None,
    )
    if active is None:
        raise PlayerBackupError(
            f"Active player record {record_key} is missing {active_filename}"
        )
    expected = extract_hero_decision_points(record)
    if active != expected:
        raise PlayerBackupError(
            f"Active player decision {record_key}/{active_filename} "
            "does not match its canonical record"
        )


def _member_info(
    archive: ZipFile,
    filename: str,
    max_size: int,
    subject: str,
) -> ZipInfo:
    try:
        info = archive.getinfo(filename)
    except KeyError as exc:
        raise PlayerBackupError(f"Player backup is missing {subject}") from exc
    if info.file_size <= 0 or info.file_size > max_size:
        raise PlayerBackupError(f"Player backup {subject} has an invalid size")
    return info


def _read_member(archive: ZipFile, info: ZipInfo) -> bytes:
    try:
        payload = archive.read(info)
    except (NotImplementedError, RuntimeError) as exc:
        raise PlayerBackupError(
            "Player backup uses an unsupported compression method"
        ) from exc
    except (
        BadZipFile,
        EOFError,
        OSError,
        lzma.LZMAError,
        zlib.error,
    ) as exc:
        raise PlayerBackupError(
            f"Player backup member could not be read: {info.filename}"
        ) from exc
    if len(payload) != info.file_size:
        raise PlayerBackupError(
            f"Player backup member {info.filename} did not match its declared size"
        )
    return payload


def _ensure_archive_size(archive_file: BinaryIO, max_archive_bytes: int) -> None:
    if archive_file.tell() > max_archive_bytes:
        raise PlayerBackupExportError(
            f"Player backup exceeds the configured {max_archive_bytes}-byte limit"
        )
