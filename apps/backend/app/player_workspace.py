"""Player-only persistence composition for the local V2 runtime."""

from __future__ import annotations

from _thread import LockType
from dataclasses import dataclass
from datetime import datetime, timedelta
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
from stat import S_ISDIR, S_ISREG
import sys
import tempfile
from threading import Lock
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from app.application.imported_hand_ingestion import (
    AuthorizedHandReimportConflict,
    AuthorizedHandReimportResult,
    AuthorizedHandReimportService,
    ImportedHandImportIdConflict,
    ImportedHandIngestionResult,
    ImportedHandIngestionService,
    ParsedImportedHandCandidate,
)
from app.application.imported_hand_lifecycle import ImportedHandLifecycleService
from app.application.imported_hand_ports import ImportedHandRecoveryReport
from app.data_lock import (
    DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
    DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
    DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    DataLockError,
    InterprocessDataLock,
    InterprocessFileLock,
)
from app.domain.imported_hands import (
    CanonicalHandRevision,
    DeletionReceipt,
    ImportConflict,
    ImportedHandLifecycle,
    ImportedHandRecord,
    canonical_revision_from_review,
    extract_hero_decision_points,
)
from app.player_hands import (
    PlayerHandApprovalRequest,
    PlayerHandCloseAction,
    PlayerHandCloseRequest,
    PlayerHandConflictResolutionRequest,
    PlayerHandDeleteRequest,
    PlayerHandDetail,
    PlayerHandList,
    PlayerHandReimportRequest,
    get_player_hand,
    list_player_hands,
    player_hand_record_version,
)
from app.storage.imported_hand_store import (
    IMPORTED_HANDS_DIRNAME,
    FileImportedHandStore,
    imported_hand_record_key,
)


class PlayerDataDirectoryError(RuntimeError):
    """The configured player data directory is not private local storage."""


class PlayerHandTransitionConflict(RuntimeError):
    """A local lifecycle request no longer describes the stored record."""


class PlayerHandApprovalInvalid(ValueError):
    """A reviewed state cannot form an auditable canonical revision."""


class PlayerHandConflictResolutionInvalid(ValueError):
    """A requested source choice cannot resolve the retained conflict."""


class PlayerHandReimportInvalid(ValueError):
    """A parsed source cannot replace the selected deleted incarnation."""


class PlayerHandRecoveryRequired(RuntimeError):
    """A ready lifecycle cascade must be replayed before this hand is read."""


class PlayerStorageRecoveryRequired(RuntimeError):
    """A volume-wide view is unsafe until ready cascades are replayed."""


DEFAULT_PLAYER_HAND_LOCK_STRIPES = 64
PLAYER_HAND_LOCK_PREFIX = ".poker-hero-player-hand-lifecycle"
PLAYER_WORKSPACE_MANIFEST_FILENAME = ".poker-hero-player-workspace.json"
PLAYER_WORKSPACE_SCHEMA = "poker-hero-player-workspace"
PLAYER_WORKSPACE_LAYOUT_VERSION = 1
MAX_PLAYER_WORKSPACE_MANIFEST_BYTES = 4096


class _PlayerWorkspaceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_name: Literal[PLAYER_WORKSPACE_SCHEMA] = Field(alias="schema")
    layout_version: Literal[PLAYER_WORKSPACE_LAYOUT_VERSION]

    @field_validator("layout_version", mode="before")
    @classmethod
    def validate_layout_version_type(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("layout version must be a JSON integer")
        return value


def _advanced_lifecycle_time(observed_at: datetime, current: datetime) -> datetime:
    if observed_at > current:
        return observed_at
    try:
        return current + timedelta(microseconds=1)
    except OverflowError as exc:
        raise PlayerHandTransitionConflict(
            "The hand lifecycle timestamp cannot advance beyond its stored value"
        ) from exc


def _preserved_conflict_source_id(
    record: ImportedHandRecord,
    conflict: ImportConflict,
) -> str | None:
    preserved_revision = conflict.active_canonical_revision_at_creation
    if preserved_revision is None:
        return None
    preserved_detection_id = record.canonical_revisions[
        preserved_revision - 1
    ].detection_id
    return next(
        detection.raw_source_id
        for detection in record.detections
        if detection.detection_id == preserved_detection_id
    )


def _projected_resolution(
    conflict: ImportConflict,
    *,
    selected_raw_source_id: str,
    resolved_at: datetime,
    status: Literal["resolved_keep_active", "resolved_use_source"],
) -> ImportConflict:
    """Resolve one conflict for a no-write lineage-satisfiability projection."""

    return ImportConflict(
        conflict_id=conflict.conflict_id,
        raw_source_ids=conflict.raw_source_ids,
        detected_ids=conflict.detected_ids,
        active_canonical_revision_at_creation=(
            conflict.active_canonical_revision_at_creation
        ),
        status=status,
        selected_raw_source_id=selected_raw_source_id,
        resolved_at=resolved_at,
    )


def _resolution_preserves_an_approvable_source(
    record: ImportedHandRecord,
    *,
    conflict_id: str,
    status: Literal["resolved_keep_active", "resolved_use_source"],
    selected_raw_source_id: str,
    resolved_at: datetime,
) -> bool:
    """Check whether some future explicit review can still activate the hand.

    Conflict choices are immutable, while source-lineage validation combines
    every applicable conflict scope. Project the requested choice plus a
    compatible completion of every still-unresolved conflict, then ask the
    aggregate validator whether any retained detection source could be the next
    player-approved canonical revision. This is existential: a broader later
    conflict may legitimately select a source outside an older scope, and a
    later conflict with the same scope may supersede that scope's older choice.
    """

    try:
        future_resolution_at = _advanced_lifecycle_time(
            resolved_at,
            resolved_at,
        )
        approval_at = _advanced_lifecycle_time(
            future_resolution_at,
            future_resolution_at,
        )
    except PlayerHandTransitionConflict:
        return False

    target = next(
        item for item in record.conflicts if item.conflict_id == conflict_id
    )
    fixed_target = _projected_resolution(
        target,
        selected_raw_source_id=selected_raw_source_id,
        resolved_at=resolved_at,
        status=status,
    )
    retained_source_ids = {raw.raw_source_id for raw in record.raw_sources}
    reviewable_detections = [
        detection
        for detection in record.detections
        if detection.raw_source_id in retained_source_ids
    ]
    for detection in reviewable_detections:
        candidate_source_id = detection.raw_source_id
        projected_conflicts: list[ImportConflict] = []
        try:
            for conflict in record.conflicts:
                if conflict.conflict_id == conflict_id:
                    projected_conflicts.append(fixed_target)
                    continue
                if conflict.status != "unresolved":
                    projected_conflicts.append(conflict)
                    continue
                preserved_source_id = _preserved_conflict_source_id(
                    record,
                    conflict,
                )
                if candidate_source_id in conflict.raw_source_ids:
                    projected_source_id = candidate_source_id
                elif preserved_source_id is not None:
                    projected_source_id = preserved_source_id
                else:
                    projected_source_id = conflict.raw_source_ids[0]
                projected_conflicts.append(
                    _projected_resolution(
                        conflict,
                        selected_raw_source_id=projected_source_id,
                        resolved_at=future_resolution_at,
                        status=(
                            "resolved_keep_active"
                            if preserved_source_id == projected_source_id
                            else "resolved_use_source"
                        ),
                    )
                )
        except (IndexError, StopIteration):
            continue

        revision_number = len(record.canonical_revisions) + 1
        try:
            ImportedHandRecord(
                identity=record.identity,
                raw_sources=record.raw_sources,
                detections=record.detections,
                conflicts=projected_conflicts,
                canonical_revisions=[
                    *record.canonical_revisions,
                    CanonicalHandRevision(
                        revision=revision_number,
                        detection_id=detection.detection_id,
                        approved_at=approval_at,
                        state=detection.state,
                    ),
                ],
                lifecycle=ImportedHandLifecycle(
                    status="active",
                    active_canonical_revision=revision_number,
                    deletion_generation=record.lifecycle.deletion_generation,
                    changed_at=approval_at,
                ),
            )
        except (ValidationError, ValueError):
            continue
        return True
    return False


def _deletion_target_generation(request: PlayerHandDeleteRequest) -> int:
    if request.expected_lifecycle_status == "deletion_pending":
        return request.expected_deletion_generation
    return request.expected_deletion_generation + 1


def _deletion_receipt(
    record_key: str,
    request: PlayerHandDeleteRequest,
    *,
    deleted_at: datetime,
) -> DeletionReceipt:
    generation = _deletion_target_generation(request)
    payload = json.dumps(
        {
            "schema": "player-hand-deletion-intent/v1",
            "record_key": record_key,
            "request_id": request.request_id,
            "reason": request.reason,
            "record_version": request.expected_record_version,
            "source_lifecycle_status": request.expected_lifecycle_status,
            "source_deletion_generation": request.expected_deletion_generation,
            "target_deletion_generation": generation,
            "deleted_at": deleted_at.isoformat(),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return DeletionReceipt(
        receipt_id=request.request_id,
        generation=generation,
        deleted_at=deleted_at,
        tombstone_sha256=sha256(payload).hexdigest(),
    )


def _macos_extended_acl_has_entries(path: Path, *, library=None) -> bool:
    # Darwin ACLs can grant access that is not reflected in POSIX mode bits.
    # Python exposes no ACL API, so query libc directly and fail closed on any
    # extended entry. ACL_TYPE_EXTENDED is the public Darwin sys/acl.h value.
    import ctypes

    libc = library or ctypes.CDLL(None, use_errno=True)
    libc.acl_get_file.argtypes = (ctypes.c_char_p, ctypes.c_int)
    libc.acl_get_file.restype = ctypes.c_void_p
    libc.acl_get_entry.argtypes = (
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
    )
    libc.acl_get_entry.restype = ctypes.c_int
    libc.acl_free.argtypes = (ctypes.c_void_p,)
    libc.acl_free.restype = ctypes.c_int
    acl = libc.acl_get_file(os.fsencode(path), 0x00000100)
    if not acl:
        acl_errno = ctypes.get_errno()
        if acl_errno == errno.ENOENT:
            return False
        raise PlayerDataDirectoryError(
            f"Cannot verify the extended ACL on {path}: errno {acl_errno}"
        )

    try:
        entry = ctypes.c_void_p()
        ctypes.set_errno(0)
        entry_result = libc.acl_get_entry(acl, 0, ctypes.byref(entry))
        if entry_result == 0:
            return True
        entry_errno = ctypes.get_errno()
        if entry_errno == errno.EINVAL:
            # Some filesystems allocate an empty extended ACL rather than
            # returning ENOENT from acl_get_file. A valid first-entry request
            # reporting no entry is still an ordinary private directory.
            return False
        raise PlayerDataDirectoryError(
            f"Cannot inspect the extended ACL on {path}: errno {entry_errno}"
        )
    finally:
        libc.acl_free(acl)


def reject_macos_extended_acl(path: Path) -> None:
    if sys.platform != "darwin":
        return
    if _macos_extended_acl_has_entries(path):
        raise PlayerDataDirectoryError(
            f"{path} must not grant access through an extended ACL"
        )


def _private_player_data_dir(
    data_dir: Path,
    *,
    create_if_missing: bool = True,
) -> Path:
    try:
        if create_if_missing:
            data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        else:
            configured_stat = data_dir.stat(follow_symlinks=False)
            if not S_ISDIR(configured_stat.st_mode):
                raise PlayerDataDirectoryError(
                    "The existing player data path must be a directory, not a"
                    " symlink or other filesystem object"
                )
        resolved = data_dir.resolve(strict=True)
        directory_stat = resolved.stat()
    except PlayerDataDirectoryError:
        raise
    except OSError as exc:
        raise PlayerDataDirectoryError(
            f"Cannot safely open the player data directory: {exc}"
        ) from exc
    if not S_ISDIR(directory_stat.st_mode):
        raise PlayerDataDirectoryError("The player data path must be a directory")
    if directory_stat.st_mode & 0o077:
        raise PlayerDataDirectoryError(
            "The player data directory must be accessible only by its owner"
        )
    if hasattr(os, "getuid") and directory_stat.st_uid != os.getuid():
        raise PlayerDataDirectoryError(
            "The player data directory must be owned by the current user"
        )
    reject_macos_extended_acl(resolved)
    return resolved


def prepare_player_data_directory(
    data_dir: Path,
    *,
    create_if_missing: bool,
) -> Path:
    """Validate (and optionally create) the private player data root."""

    return _private_player_data_dir(
        Path(data_dir),
        create_if_missing=create_if_missing,
    )


def require_private_player_data_parent(data_dir: Path) -> Path:
    """Validate the stable parent used for runtime/removal coordination."""

    parent = Path(data_dir).parent
    try:
        parent_stat = parent.stat(follow_symlinks=False)
    except OSError as exc:
        raise PlayerDataDirectoryError(
            "Cannot safely inspect the player data parent directory"
        ) from exc
    if not S_ISDIR(parent_stat.st_mode):
        raise PlayerDataDirectoryError(
            "The player data parent path must be a directory"
        )
    if parent_stat.st_mode & 0o022:
        raise PlayerDataDirectoryError(
            "The player data parent must not be writable by other users"
        )
    if hasattr(os, "getuid") and parent_stat.st_uid != os.getuid():
        raise PlayerDataDirectoryError(
            "The player data parent must be owned by the current user"
        )
    reject_macos_extended_acl(parent)
    return parent


def _require_imported_hands_dir(
    data_dir: Path,
    *,
    create_if_missing: bool,
) -> None:
    records_dir = data_dir / IMPORTED_HANDS_DIRNAME
    if create_if_missing:
        try:
            os.mkdir(records_dir, mode=0o700)
        except FileExistsError:
            pass
        except OSError as exc:
            raise PlayerDataDirectoryError(
                f"Cannot safely open the imported-hand store: {exc}"
            ) from exc
    try:
        records_stat = records_dir.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        raise PlayerDataDirectoryError(
            "The versioned player workspace is missing its imported-hand store"
        ) from exc
    except OSError as exc:
        raise PlayerDataDirectoryError(
            f"Cannot safely inspect the imported-hand store: {exc}"
        ) from exc
    if not S_ISDIR(records_stat.st_mode):
        raise PlayerDataDirectoryError(
            "The imported-hand store must be a directory inside the player data directory"
        )
    if records_stat.st_mode & 0o077:
        raise PlayerDataDirectoryError(
            "The imported-hand store must be accessible only by its owner"
        )
    if hasattr(os, "getuid") and records_stat.st_uid != os.getuid():
        raise PlayerDataDirectoryError(
            "The imported-hand store must be owned by the current user"
        )
    reject_macos_extended_acl(records_dir)


def _read_player_workspace_manifest(
    data_dir: Path,
) -> _PlayerWorkspaceManifest | None:
    manifest_path = data_dir / PLAYER_WORKSPACE_MANIFEST_FILENAME
    # A hostile FIFO must not be able to wedge startup before fstat() rejects
    # it. O_NONBLOCK is inert for regular files and makes that type check safe.
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(manifest_path, flags)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise PlayerDataDirectoryError(
            f"Cannot safely open the player workspace manifest: {exc}"
        ) from exc

    try:
        manifest_stat = os.fstat(descriptor)
        if not S_ISREG(manifest_stat.st_mode):
            raise PlayerDataDirectoryError(
                "The player workspace manifest must be a regular file"
            )
        if manifest_stat.st_mode & 0o077:
            raise PlayerDataDirectoryError(
                "The player workspace manifest must be readable only by its owner"
            )
        if hasattr(os, "getuid") and manifest_stat.st_uid != os.getuid():
            raise PlayerDataDirectoryError(
                "The player workspace manifest must be owned by the current user"
            )
        chunks: list[bytes] = []
        total_bytes = 0
        while True:
            chunk = os.read(
                descriptor,
                MAX_PLAYER_WORKSPACE_MANIFEST_BYTES + 1 - total_bytes,
            )
            if not chunk:
                break
            chunks.append(chunk)
            total_bytes += len(chunk)
            if total_bytes > MAX_PLAYER_WORKSPACE_MANIFEST_BYTES:
                raise PlayerDataDirectoryError(
                    "The player workspace manifest exceeds its size limit"
                )
        payload = b"".join(chunks)
    except OSError as exc:
        raise PlayerDataDirectoryError(
            f"Cannot safely inspect the player workspace manifest: {exc}"
        ) from exc
    finally:
        os.close(descriptor)

    try:
        return _PlayerWorkspaceManifest.model_validate_json(payload)
    except ValidationError as exc:
        raise PlayerDataDirectoryError(
            "The player workspace manifest is malformed or uses an unsupported"
            " layout version"
        ) from exc


def _player_workspace_manifest_payload() -> bytes:
    return (
        json.dumps(
            {
                "layout_version": PLAYER_WORKSPACE_LAYOUT_VERSION,
                "schema": PLAYER_WORKSPACE_SCHEMA,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _fsync_player_data_dir(data_dir: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(data_dir, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_durable_player_workspace_manifest(data_dir: Path) -> None:
    try:
        _fsync_player_data_dir(data_dir)
    except OSError as exc:
        raise PlayerDataDirectoryError(
            "Cannot make the player workspace manifest durable"
        ) from exc


def _publish_player_workspace_manifest(data_dir: Path) -> None:
    manifest_path = data_dir / PLAYER_WORKSPACE_MANIFEST_FILENAME
    temp_path: Path | None = None
    publication_error: OSError | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=data_dir,
            prefix=".poker-hero-player-workspace.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            os.fchmod(temp_file.fileno(), 0o600)
            temp_file.write(_player_workspace_manifest_payload())
            temp_file.flush()
            os.fsync(temp_file.fileno())
        try:
            os.link(temp_path, manifest_path)
        except FileExistsError:
            pass
    except OSError as exc:
        publication_error = exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as exc:
                if publication_error is None:
                    publication_error = exc

    if publication_error is not None:
        raise PlayerDataDirectoryError(
            "Cannot durably create the player workspace manifest:"
            f" {publication_error}"
        ) from publication_error

    if _read_player_workspace_manifest(data_dir) is None:
        raise PlayerDataDirectoryError(
            "The player workspace manifest was not durably created"
        )
    try:
        # Sync after removing the hard-link source so publication and normal
        # temporary-file cleanup share one durable directory boundary.
        _fsync_player_data_dir(data_dir)
    except OSError as exc:
        raise PlayerDataDirectoryError(
            f"Cannot durably create the player workspace manifest: {exc}"
        ) from exc


@dataclass(frozen=True)
class PlayerWorkspace:
    """The stores the local player runtime may open.

    This composition intentionally excludes the V1 job and benchmark stores.
    Future player routes receive this object rather than the hosted workspace,
    so adding a route cannot make administrative screenshot state reachable by
    accident.
    """

    data_dir: Path
    layout_version: int
    data_lock: InterprocessDataLock
    imported_hands: FileImportedHandStore
    imported_hand_recovery: ImportedHandRecoveryReport
    imported_hand_locks: tuple[LockType, ...]
    imported_hand_process_locks: tuple[InterprocessFileLock, ...]

    @classmethod
    def open(
        cls,
        data_dir: Path,
        *,
        recovery_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
        startup_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
        write_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    ) -> "PlayerWorkspace":
        return cls._open(
            data_dir,
            recovery_lock_timeout_seconds=recovery_lock_timeout_seconds,
            startup_lock_timeout_seconds=startup_lock_timeout_seconds,
            write_lock_timeout_seconds=write_lock_timeout_seconds,
            create_if_missing=True,
            adopt_manifestless=True,
        )

    @classmethod
    def open_existing(
        cls,
        data_dir: Path,
        *,
        recovery_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
        startup_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
        write_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    ) -> "PlayerWorkspace":
        """Open only an already-versioned workspace without creating or adopting."""

        return cls._open(
            data_dir,
            recovery_lock_timeout_seconds=recovery_lock_timeout_seconds,
            startup_lock_timeout_seconds=startup_lock_timeout_seconds,
            write_lock_timeout_seconds=write_lock_timeout_seconds,
            create_if_missing=False,
            adopt_manifestless=False,
        )

    @classmethod
    def _open(
        cls,
        data_dir: Path,
        *,
        recovery_lock_timeout_seconds: int,
        startup_lock_timeout_seconds: int,
        write_lock_timeout_seconds: int,
        create_if_missing: bool,
        adopt_manifestless: bool,
    ) -> "PlayerWorkspace":
        private_data_dir = prepare_player_data_directory(
            data_dir,
            create_if_missing=create_if_missing,
        )
        data_lock = InterprocessDataLock(private_data_dir)
        recovery = ImportedHandRecoveryReport()
        manifest_hint = _read_player_workspace_manifest(private_data_dir)
        if manifest_hint is None and not adopt_manifestless:
            raise PlayerDataDirectoryError(
                "The existing player data directory is missing its versioned"
                " workspace manifest"
            )
        if manifest_hint is not None:
            # Re-read and construct beneath the shared hold. A future layout
            # migration must take the exclusive side, so it cannot publish a
            # new layout between validation and store construction.
            with data_lock.hold(
                exclusive=False,
                timeout_seconds=startup_lock_timeout_seconds,
            ):
                manifest = _read_player_workspace_manifest(private_data_dir)
                if manifest is None:
                    raise PlayerDataDirectoryError(
                        "The player workspace manifest changed during startup"
                    )
                _require_durable_player_workspace_manifest(private_data_dir)
                _require_imported_hands_dir(
                    private_data_dir,
                    create_if_missing=False,
                )
                imported_hands = FileImportedHandStore(
                    private_data_dir,
                    write_lock_timeout_seconds=write_lock_timeout_seconds,
                )
                if not imported_hands.has_interrupted_writes():
                    return cls._from_opened_store(
                        data_dir=private_data_dir,
                        manifest=manifest,
                        data_lock=data_lock,
                        imported_hands=imported_hands,
                        recovery=recovery,
                    )

        # A missing legacy marker or an interrupted store requires the
        # exclusive side. Re-read everything after acquiring it so a future
        # migration or another adopter cannot leave this process with stale
        # layout assumptions.
        with data_lock.hold(
            exclusive=True,
            timeout_seconds=recovery_lock_timeout_seconds,
        ):
            manifest = _read_player_workspace_manifest(private_data_dir)
            if manifest is None:
                if manifest_hint is not None or not adopt_manifestless:
                    raise PlayerDataDirectoryError(
                        "The player workspace manifest changed during startup"
                    )
                _require_imported_hands_dir(
                    private_data_dir,
                    create_if_missing=True,
                )
                _publish_player_workspace_manifest(private_data_dir)
                manifest = _read_player_workspace_manifest(private_data_dir)
                if manifest is None:
                    raise PlayerDataDirectoryError(
                        "The player workspace manifest is missing after migration"
                    )
            else:
                _require_durable_player_workspace_manifest(private_data_dir)
                _require_imported_hands_dir(
                    private_data_dir,
                    create_if_missing=False,
                )
            imported_hands = FileImportedHandStore(
                private_data_dir,
                write_lock_timeout_seconds=write_lock_timeout_seconds,
            )
            if imported_hands.has_interrupted_writes():
                recovery = imported_hands.recover()
            return cls._from_opened_store(
                data_dir=private_data_dir,
                manifest=manifest,
                data_lock=data_lock,
                imported_hands=imported_hands,
                recovery=recovery,
            )

    @classmethod
    def _from_opened_store(
        cls,
        *,
        data_dir: Path,
        manifest: _PlayerWorkspaceManifest,
        data_lock: InterprocessDataLock,
        imported_hands: FileImportedHandStore,
        recovery: ImportedHandRecoveryReport,
    ) -> "PlayerWorkspace":
        return cls(
            data_dir=data_dir,
            layout_version=manifest.layout_version,
            data_lock=data_lock,
            imported_hands=imported_hands,
            imported_hand_recovery=recovery,
            imported_hand_locks=tuple(
                Lock() for _ in range(DEFAULT_PLAYER_HAND_LOCK_STRIPES)
            ),
            imported_hand_process_locks=tuple(
                InterprocessFileLock(
                    data_dir
                    / f"{PLAYER_HAND_LOCK_PREFIX}-{index:02d}.lock",
                    subject="player hand lifecycle lock",
                    contention_hint=(
                        "another local player process is changing a record in "
                        "the same lifecycle lock stripe"
                    ),
                )
                for index in range(DEFAULT_PLAYER_HAND_LOCK_STRIPES)
            ),
        )

    def imported_hand_lock_index(self, record_key: str) -> int:
        """Return a process-stable stripe for this identity-derived key."""

        try:
            prefix = int(record_key[:16], 16)
        except ValueError:
            prefix = 0
        return prefix % len(self.imported_hand_locks)

    def require_current_layout(self) -> None:
        try:
            manifest = _read_player_workspace_manifest(self.data_dir)
        except PlayerDataDirectoryError as exc:
            raise PlayerDataDirectoryError(
                "The player workspace layout changed while this runtime was open;"
                " restart with a compatible version"
            ) from exc
        if manifest is None or manifest.layout_version != self.layout_version:
            raise PlayerDataDirectoryError(
                "The player workspace layout changed while this runtime was open;"
                " restart with a compatible version"
            )

    def status_payload(
        self,
        *,
        lock_timeout_seconds: int = DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
    ) -> dict[str, object]:
        # Status is volume-wide, so wait for every shared writer as well as an
        # exclusive restore. Once isolated, a durable ready cascade means the
        # live files are not a final snapshot and must not be reported as one.
        with self.data_lock.hold(
            exclusive=True,
            timeout_seconds=lock_timeout_seconds,
        ):
            self.require_current_layout()
            if self.imported_hands.has_pending_recovery():
                raise PlayerStorageRecoveryRequired(
                    "Player storage has an interrupted lifecycle write; "
                    "restart the local player runtime so recovery can finish"
                )
            recovery = self.imported_hand_recovery
            quarantined = tuple(
                sorted(
                    set(recovery.quarantined)
                    | set(self.imported_hands.list_quarantined_cascades())
                )
            )
            return {
                "status": (
                    "attention_required"
                    if quarantined or recovery.failed
                    else "ready"
                ),
                "storage": "player-local-file",
                "layout_version": self.layout_version,
                "data_directory": str(self.data_dir),
                "imported_hand_record_count": len(self.imported_hands.list_keys()),
                "recovery": {
                    "completed": list(recovery.completed),
                    "quarantined": list(quarantined),
                    "failed": list(recovery.failed),
                },
            }

    def list_hand_records(
        self,
        *,
        limit: int,
        cursor: str | None,
        lock_timeout_seconds: int = DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
    ) -> PlayerHandList:
        """Read one stable page while backup or recovery publication is excluded."""

        with self.data_lock.hold(
            exclusive=False,
            timeout_seconds=lock_timeout_seconds,
        ):
            self.require_current_layout()
            return list_player_hands(
                self.imported_hands,
                limit=limit,
                cursor=cursor,
                is_record_unavailable=self.imported_hands.has_interrupted_write,
            )

    def get_hand_record(
        self,
        record_key: str,
        *,
        lock_timeout_seconds: int = DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
    ) -> PlayerHandDetail:
        """Read one final record projection, refusing a pending replay."""

        lock_index = self.imported_hand_lock_index(record_key)
        with self.imported_hand_locks[lock_index]:
            with self.imported_hand_process_locks[lock_index].hold(
                exclusive=False,
                timeout_seconds=lock_timeout_seconds,
            ):
                with self.data_lock.hold(
                    exclusive=False,
                    timeout_seconds=lock_timeout_seconds,
                ):
                    self.require_current_layout()
                    self._require_final_hand_record(record_key)
                    return get_player_hand(self.imported_hands, record_key)

    def ingest_detected_hand(
        self,
        candidate: ParsedImportedHandCandidate,
        *,
        lock_timeout_seconds: int = DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    ) -> ImportedHandIngestionResult:
        """Serialize one adapter candidate through its full resolve/find/save."""

        record_key = imported_hand_record_key(candidate.raw.identity)
        lock_index = self.imported_hand_lock_index(record_key)
        with self.imported_hand_locks[lock_index]:
            with self.imported_hand_process_locks[lock_index].hold(
                exclusive=True,
                timeout_seconds=lock_timeout_seconds,
            ):
                with self.data_lock.hold(
                    exclusive=False,
                    timeout_seconds=lock_timeout_seconds,
                ):
                    self.require_current_layout()
                    self._require_final_hand_record(record_key)
                    return ImportedHandIngestionService(
                        store=self.imported_hands,
                    ).ingest(candidate)

    def reimport_deleted_hand(
        self,
        record_key: str,
        candidate: ParsedImportedHandCandidate,
        *,
        request: PlayerHandReimportRequest,
        at: datetime,
        lock_timeout_seconds: int = DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    ) -> AuthorizedHandReimportResult:
        """Explicitly replace one exact deletion incarnation for fresh review."""

        candidate_key = imported_hand_record_key(candidate.raw.identity)
        if candidate_key != record_key:
            raise PlayerHandReimportInvalid(
                "The selected file does not contain the deleted hand being reimported"
            )
        lock_index = self.imported_hand_lock_index(record_key)
        with self.imported_hand_locks[lock_index]:
            with self.imported_hand_process_locks[lock_index].hold(
                exclusive=True,
                timeout_seconds=lock_timeout_seconds,
            ):
                with self.data_lock.hold(
                    exclusive=False,
                    timeout_seconds=lock_timeout_seconds,
                ):
                    self.require_current_layout()
                    self._require_final_hand_record(record_key)
                    service = AuthorizedHandReimportService(
                        store=self.imported_hands,
                    )
                    try:
                        retry = service.retry(
                            record_key,
                            candidate,
                            expected_deletion_generation=(
                                request.expected_deletion_generation
                            ),
                        )
                    except ImportedHandImportIdConflict as exc:
                        raise PlayerHandTransitionConflict(str(exc)) from exc
                    except AuthorizedHandReimportConflict as exc:
                        raise PlayerHandReimportInvalid(str(exc)) from exc
                    if retry is not None:
                        return retry

                    record = self.imported_hands.get(record_key)
                    lifecycle = record.lifecycle
                    if (
                        player_hand_record_version(record)
                        != request.expected_record_version
                        or lifecycle.status != request.expected_lifecycle_status
                        or lifecycle.deletion_generation
                        != request.expected_deletion_generation
                        or lifecycle.changed_at
                        != request.expected_lifecycle_changed_at
                    ):
                        raise PlayerHandTransitionConflict(
                            "The retained deletion incarnation changed after this"
                            " audit detail was loaded; refresh it before reimporting"
                        )
                    changed_at = _advanced_lifecycle_time(
                        at,
                        lifecycle.changed_at,
                    )
                    try:
                        result = service.reimport(
                            record_key,
                            candidate,
                            expected=record,
                            changed_at=changed_at,
                        )
                    except AuthorizedHandReimportConflict as exc:
                        raise PlayerHandReimportInvalid(str(exc)) from exc
                    except (DataLockError, OSError) as exc:
                        if self.imported_hands.has_interrupted_write(record_key):
                            raise PlayerHandRecoveryRequired(
                                "This hand has an interrupted authorized reimport;"
                                " restart the local player runtime so recovery can"
                                " finish"
                            ) from exc
                        raise
                    self._require_final_hand_record(record_key)
                    return result

    def close_hand_record(
        self,
        record_key: str,
        *,
        action: PlayerHandCloseAction,
        request: PlayerHandCloseRequest,
        at: datetime,
        lock_timeout_seconds: int = DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    ) -> PlayerHandDetail:
        """Withdraw or reject one active revision without losing audit state.

        The in-process stripe orders request threads. The matching named flock
        uses the same stable stripe in every local-runtime process, closing the
        cross-process gap. The outer shared volume hold keeps backup/restore
        publication from replacing the record between the request precondition
        read and the service's cascade; the store then takes its own nested
        shared hold before the leaf journal lock.
        """

        lock_index = self.imported_hand_lock_index(record_key)
        with self.imported_hand_locks[lock_index]:
            with self.imported_hand_process_locks[lock_index].hold(
                exclusive=True,
                timeout_seconds=lock_timeout_seconds,
            ):
                with self.data_lock.hold(
                    exclusive=False,
                    timeout_seconds=lock_timeout_seconds,
                ):
                    self.require_current_layout()
                    self._require_final_hand_record(record_key)
                    record = self.imported_hands.get(record_key)
                    latest_revision = (
                        record.canonical_revisions[-1].revision
                        if record.canonical_revisions
                        else None
                    )
                    lifecycle = record.lifecycle
                    same_target = (
                        lifecycle.status
                        == ("withdrawn" if action == "withdraw" else "rejected")
                        and lifecycle.reason == request.reason
                        and lifecycle.deletion_generation
                        == request.expected_deletion_generation
                        and latest_revision
                        == request.expected_active_canonical_revision
                        and lifecycle.changed_at
                        >= request.expected_lifecycle_changed_at
                    )
                    if same_target:
                        return get_player_hand(self.imported_hands, record_key)

                    if (
                        lifecycle.status != "active"
                        or lifecycle.active_canonical_revision
                        != request.expected_active_canonical_revision
                        or lifecycle.deletion_generation
                        != request.expected_deletion_generation
                        or lifecycle.changed_at
                        != request.expected_lifecycle_changed_at
                    ):
                        raise PlayerHandTransitionConflict(
                            "The hand lifecycle changed after this audit detail "
                            "was loaded; refresh it before changing approval state"
                        )

                    lifecycle_service = ImportedHandLifecycleService(
                        store=self.imported_hands,
                        extract=extract_hero_decision_points,
                        now=lambda: at,
                    )
                    transition = (
                        lifecycle_service.withdraw
                        if action == "withdraw"
                        else lifecycle_service.reject
                    )
                    try:
                        transition(
                            record_key,
                            reason=request.reason,
                            at=_advanced_lifecycle_time(at, lifecycle.changed_at),
                        )
                    except (DataLockError, OSError) as exc:
                        if self.imported_hands.has_interrupted_write(record_key):
                            raise PlayerHandRecoveryRequired(
                                "This hand has an interrupted lifecycle write; "
                                "restart the local player runtime so recovery "
                                "can finish"
                            ) from exc
                        raise
                    self._require_final_hand_record(record_key)
                    return get_player_hand(self.imported_hands, record_key)

    def approve_hand_record(
        self,
        record_key: str,
        *,
        request: PlayerHandApprovalRequest,
        at: datetime,
        lock_timeout_seconds: int = DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    ) -> PlayerHandDetail:
        """Publish one exact reviewed state and its derived decisions."""

        lock_index = self.imported_hand_lock_index(record_key)
        with self.imported_hand_locks[lock_index]:
            with self.imported_hand_process_locks[lock_index].hold(
                exclusive=True,
                timeout_seconds=lock_timeout_seconds,
            ):
                with self.data_lock.hold(
                    exclusive=False,
                    timeout_seconds=lock_timeout_seconds,
                ):
                    self.require_current_layout()
                    self._require_final_hand_record(record_key)
                    record = self.imported_hands.get(record_key)
                    lifecycle = record.lifecycle
                    latest = (
                        record.canonical_revisions[-1]
                        if record.canonical_revisions
                        else None
                    )
                    if latest is not None and latest.approval_id == request.request_id:
                        detection = next(
                            (
                                item
                                for item in record.detections
                                if item.detection_id == request.detection_id
                            ),
                            None,
                        )
                        try:
                            expected = (
                                canonical_revision_from_review(
                                    detection,
                                    approval_id=request.request_id,
                                    revision=latest.revision,
                                    approved_at=latest.approved_at,
                                    approved_state=request.approved_state,
                                    correction_reason=request.correction_reason,
                                )
                                if detection is not None
                                else None
                            )
                        except ValueError:
                            expected = None
                        if (
                            expected == latest
                            and lifecycle.status == "active"
                            and lifecycle.active_canonical_revision == latest.revision
                        ):
                            return get_player_hand(self.imported_hands, record_key)
                        raise PlayerHandTransitionConflict(
                            "This approval request id is already bound to a "
                            "different or no-longer-active review"
                        )
                    if any(
                        revision.approval_id == request.request_id
                        for revision in record.canonical_revisions
                    ):
                        raise PlayerHandTransitionConflict(
                            "This approval request id was already used by an "
                            "earlier canonical revision"
                        )

                    if (
                        player_hand_record_version(record)
                        != request.expected_record_version
                        or lifecycle.status != request.expected_lifecycle_status
                        or lifecycle.active_canonical_revision
                        != request.expected_active_canonical_revision
                        or len(record.canonical_revisions)
                        != request.expected_canonical_revision_count
                        or lifecycle.deletion_generation
                        != request.expected_deletion_generation
                        or lifecycle.changed_at
                        != request.expected_lifecycle_changed_at
                    ):
                        raise PlayerHandTransitionConflict(
                            "The retained hand changed after this audit detail was "
                            "loaded; refresh it before approving reviewed state"
                        )

                    detection = next(
                        (
                            item
                            for item in record.detections
                            if item.detection_id == request.detection_id
                        ),
                        None,
                    )
                    if detection is None:
                        raise PlayerHandTransitionConflict(
                            "The selected detection is not retained by this hand"
                        )
                    if detection.raw_source_id not in {
                        raw.raw_source_id for raw in record.raw_sources
                    }:
                        raise PlayerHandApprovalInvalid(
                            "A reimport audit-only detection cannot be approved"
                        )
                    approved_at = _advanced_lifecycle_time(at, lifecycle.changed_at)
                    try:
                        revision = canonical_revision_from_review(
                            detection,
                            approval_id=request.request_id,
                            revision=len(record.canonical_revisions) + 1,
                            approved_at=approved_at,
                            approved_state=request.approved_state,
                            correction_reason=request.correction_reason,
                        )
                    except ValidationError as exc:
                        raise PlayerHandApprovalInvalid(
                            "Reviewed canonical state is invalid"
                        ) from exc
                    except ValueError as exc:
                        raise PlayerHandApprovalInvalid(str(exc)) from exc

                    lifecycle_service = ImportedHandLifecycleService(
                        store=self.imported_hands,
                        extract=extract_hero_decision_points,
                        now=lambda: approved_at,
                    )
                    transition = (
                        lifecycle_service.reapprove
                        if record.canonical_revisions
                        else lifecycle_service.approve
                    )
                    try:
                        transition(record_key, revision)
                    except (DataLockError, OSError) as exc:
                        if self.imported_hands.has_interrupted_write(record_key):
                            raise PlayerHandRecoveryRequired(
                                "This hand has an interrupted lifecycle write; "
                                "restart the local player runtime so recovery "
                                "can finish"
                            ) from exc
                        raise
                    self._require_final_hand_record(record_key)
                    return get_player_hand(self.imported_hands, record_key)

    def delete_hand_record(
        self,
        record_key: str,
        *,
        request: PlayerHandDeleteRequest,
        at: datetime,
        lock_timeout_seconds: int = DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    ) -> PlayerHandDetail:
        """Deactivate, purge, and receipt-bind one exact retained snapshot."""

        lock_index = self.imported_hand_lock_index(record_key)
        with self.imported_hand_locks[lock_index]:
            with self.imported_hand_process_locks[lock_index].hold(
                exclusive=True,
                timeout_seconds=lock_timeout_seconds,
            ):
                with self.data_lock.hold(
                    exclusive=False,
                    timeout_seconds=lock_timeout_seconds,
                ):
                    self.require_current_layout()
                    self._require_final_hand_record(record_key)
                    record = self.imported_hands.get(record_key)
                    lifecycle = record.lifecycle
                    if lifecycle.status == "deleted":
                        receipt = record.deletion_receipt
                        if receipt is not None and receipt == _deletion_receipt(
                            record_key,
                            request,
                            deleted_at=receipt.deleted_at,
                        ):
                            return get_player_hand(self.imported_hands, record_key)
                        raise PlayerHandTransitionConflict(
                            "This hand was permanently deleted by another request"
                        )

                    if (
                        player_hand_record_version(record)
                        != request.expected_record_version
                        or lifecycle.status != request.expected_lifecycle_status
                        or lifecycle.active_canonical_revision
                        != request.expected_active_canonical_revision
                        or lifecycle.deletion_generation
                        != request.expected_deletion_generation
                        or lifecycle.changed_at
                        != request.expected_lifecycle_changed_at
                    ):
                        raise PlayerHandTransitionConflict(
                            "The retained hand changed after this audit detail was "
                            "loaded; refresh it before permanently deleting it"
                        )
                    if (
                        lifecycle.status == "deletion_pending"
                        and lifecycle.reason != request.reason
                    ):
                        raise PlayerHandTransitionConflict(
                            "A deletion cleanup retry must use the retained request reason"
                        )

                    lifecycle_service = ImportedHandLifecycleService(
                        store=self.imported_hands,
                        extract=extract_hero_decision_points,
                        now=lambda: at,
                    )
                    try:
                        pending = record
                        if lifecycle.status != "deletion_pending":
                            pending = lifecycle_service.request_deletion(
                                record_key,
                                reason=request.reason,
                                at=_advanced_lifecycle_time(
                                    at,
                                    lifecycle.changed_at,
                                ),
                            )
                        deleted_at = _advanced_lifecycle_time(
                            at,
                            pending.lifecycle.changed_at,
                        )
                        lifecycle_service.purge(
                            record_key,
                            receipt=_deletion_receipt(
                                record_key,
                                request,
                                deleted_at=deleted_at,
                            ),
                        )
                    except (DataLockError, OSError) as exc:
                        if self.imported_hands.has_interrupted_write(record_key):
                            raise PlayerHandRecoveryRequired(
                                "This hand has an interrupted lifecycle write; "
                                "restart the local player runtime so recovery "
                                "can finish"
                            ) from exc
                        raise
                    self._require_final_hand_record(record_key)
                    return get_player_hand(self.imported_hands, record_key)

    def resolve_hand_conflict(
        self,
        record_key: str,
        *,
        conflict_id: str,
        request: PlayerHandConflictResolutionRequest,
        at: datetime,
        lock_timeout_seconds: int = DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    ) -> PlayerHandDetail:
        """Persist one explicit conflict choice against an exact snapshot."""

        lock_index = self.imported_hand_lock_index(record_key)
        with self.imported_hand_locks[lock_index]:
            with self.imported_hand_process_locks[lock_index].hold(
                exclusive=True,
                timeout_seconds=lock_timeout_seconds,
            ):
                with self.data_lock.hold(
                    exclusive=False,
                    timeout_seconds=lock_timeout_seconds,
                ):
                    self.require_current_layout()
                    self._require_final_hand_record(record_key)
                    record = self.imported_hands.get(record_key)
                    lifecycle = record.lifecycle
                    conflict = next(
                        (
                            item
                            for item in record.conflicts
                            if item.conflict_id == conflict_id
                        ),
                        None,
                    )
                    if conflict is None:
                        raise PlayerHandTransitionConflict(
                            "The selected conflict is not retained by this hand"
                        )
                    target_status = (
                        "resolved_keep_active"
                        if request.resolution == "keep_active"
                        else "resolved_use_source"
                    )
                    if conflict.status != "unresolved":
                        if (
                            conflict.status == target_status
                            and conflict.selected_raw_source_id
                            == request.selected_raw_source_id
                        ):
                            return get_player_hand(self.imported_hands, record_key)
                        raise PlayerHandTransitionConflict(
                            "This conflict was already resolved with a different"
                            " source choice"
                        )

                    if (
                        player_hand_record_version(record)
                        != request.expected_record_version
                        or lifecycle.status != request.expected_lifecycle_status
                        or lifecycle.active_canonical_revision
                        != request.expected_active_canonical_revision
                        or len(record.canonical_revisions)
                        != request.expected_canonical_revision_count
                        or lifecycle.deletion_generation
                        != request.expected_deletion_generation
                        or lifecycle.changed_at
                        != request.expected_lifecycle_changed_at
                    ):
                        raise PlayerHandTransitionConflict(
                            "The retained hand changed after this audit detail was"
                            " loaded; refresh it before resolving the conflict"
                        )
                    if request.selected_raw_source_id not in conflict.raw_source_ids:
                        raise PlayerHandConflictResolutionInvalid(
                            "The selected source does not belong to this conflict"
                        )
                    if request.resolution == "keep_active":
                        preserved_revision = (
                            conflict.active_canonical_revision_at_creation
                        )
                        if preserved_revision is None:
                            raise PlayerHandConflictResolutionInvalid(
                                "This conflict has no preserved canonical source to"
                                " keep"
                            )
                        preserved = record.canonical_revisions[
                            preserved_revision - 1
                        ]
                        preserved_detection = next(
                            item
                            for item in record.detections
                            if item.detection_id == preserved.detection_id
                        )
                        if (
                            request.selected_raw_source_id
                            != preserved_detection.raw_source_id
                        ):
                            raise PlayerHandConflictResolutionInvalid(
                                "Keeping the preserved canonical state requires its"
                                " retained source"
                            )

                    resolved_at = _advanced_lifecycle_time(
                        at,
                        lifecycle.changed_at,
                    )
                    if not _resolution_preserves_an_approvable_source(
                        record,
                        conflict_id=conflict_id,
                        status=target_status,
                        selected_raw_source_id=request.selected_raw_source_id,
                        resolved_at=resolved_at,
                    ):
                        raise PlayerHandConflictResolutionInvalid(
                            "This source choice conflicts with earlier retained"
                            " resolutions and would leave no source available for"
                            " explicit approval"
                        )
                    lifecycle_service = ImportedHandLifecycleService(
                        store=self.imported_hands,
                        extract=extract_hero_decision_points,
                        now=lambda: resolved_at,
                    )
                    try:
                        lifecycle_service.resolve_conflict(
                            record_key,
                            conflict_id=conflict_id,
                            status=target_status,
                            selected_raw_source_id=(
                                request.selected_raw_source_id
                            ),
                            at=resolved_at,
                        )
                    except (DataLockError, OSError) as exc:
                        if self.imported_hands.has_interrupted_write(record_key):
                            raise PlayerHandRecoveryRequired(
                                "This hand has an interrupted lifecycle write;"
                                " restart the local player runtime so recovery can"
                                " finish"
                            ) from exc
                        raise
                    self._require_final_hand_record(record_key)
                    return get_player_hand(self.imported_hands, record_key)

    def _require_final_hand_record(self, record_key: str) -> None:
        if self.imported_hands.has_interrupted_write(record_key):
            raise PlayerHandRecoveryRequired(
                "This hand has an interrupted lifecycle write; restart the "
                "local player runtime so recovery can finish"
            )
