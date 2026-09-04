"""Verified export-and-remove transaction for local player data."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
from stat import S_ISDIR, S_ISREG
import shutil
import sys
from tempfile import NamedTemporaryFile
from typing import BinaryIO
from uuid import uuid4

from pydantic import ValidationError

from app.config import Settings, get_settings
from app.data_lock import (
    DATA_LOCK_FILENAME,
    DataLockError,
    player_runtime_lease,
)
from app.player_backup import (
    DEFAULT_MAX_PLAYER_BACKUP_BYTES,
    PLAYER_BACKUP_STREAM_CHUNK_SIZE,
    PlayerBackupError,
    _build_player_backup_archive_from_locked_workspace,
    parse_player_backup_archive,
)
from app.player_workspace import (
    DEFAULT_PLAYER_HAND_LOCK_STRIPES,
    PLAYER_HAND_LOCK_PREFIX,
    PLAYER_WORKSPACE_MANIFEST_FILENAME,
    PlayerDataDirectoryError,
    PlayerWorkspace,
    prepare_player_data_directory,
    reject_macos_extended_acl,
)
from app.storage.imported_hand_store import (
    DECISIONS_DIRNAME,
    DECISION_ARTIFACT_PATTERN,
    GRADES_DIRNAME,
    GRADE_ARTIFACT_PATTERN,
    IMPORTED_HANDS_DIRNAME,
    RECORD_FILENAME,
    RECORD_KEY_PATTERN,
)
from app.storage.learning_content_catalog_store import (
    LEARNING_CONTENT_CATALOG_FILENAME,
)
from app.storage.reference_activation_catalog_store import (
    REFERENCE_ACTIVATION_CATALOG_FILENAME,
)
from app.storage.remote_reference_consent_store import (
    REMOTE_REFERENCE_CONSENT_FILENAME,
)


PLAYER_REMOVAL_DIRECTORY_PREFIX = ".poker-hero-player-removed-"
PLAYER_INSTALLATION_SECRET_FILENAME = ".player-runtime-key"


class PlayerUninstallError(RuntimeError):
    """The local data removal transaction could not complete safely."""


@dataclass(frozen=True)
class PlayerUninstallResult:
    archive_path: Path
    retained_data_path: Path | None = None
    warning: str | None = None

    @property
    def completed(self) -> bool:
        return self.warning is None


def export_and_remove_player_data(
    data_dir: Path,
    archive_path: Path,
    *,
    max_archive_bytes: int = DEFAULT_MAX_PLAYER_BACKUP_BYTES,
    lock_timeout_seconds: int,
) -> PlayerUninstallResult:
    """Publish a verified backup before removing one exact player workspace."""

    if max_archive_bytes <= 0:
        raise PlayerUninstallError("Player backup size limit must be positive")
    try:
        candidate = Path(data_dir).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise PlayerUninstallError(
            "Cannot safely resolve the player data directory"
        ) from exc
    _require_safe_removal_source(candidate)
    retained_paths = _retained_removal_paths(candidate)
    if retained_paths:
        retained = ", ".join(str(path) for path in retained_paths)
        raise PlayerUninstallError(
            "A previous player-data removal requires attention before retrying:"
            f" {retained}"
        )
    _require_safe_archive_output(candidate, archive_path)
    lease = player_runtime_lease(candidate)
    lease_descriptor = lease.acquire(
        exclusive=True,
        timeout_seconds=lock_timeout_seconds,
    )
    try:
        retained_paths = _retained_removal_paths(candidate)
        if retained_paths:
            retained = ", ".join(str(path) for path in retained_paths)
            raise PlayerUninstallError(
                "A previous player-data removal requires attention before retrying:"
                f" {retained}"
            )
        source = prepare_player_data_directory(
            data_dir,
            create_if_missing=False,
        )
        _require_safe_removal_source(source)
        output_path = _require_safe_archive_output(source, archive_path)
        workspace = PlayerWorkspace.open_existing(
            source,
            recovery_lock_timeout_seconds=lock_timeout_seconds,
            startup_lock_timeout_seconds=lock_timeout_seconds,
        )
        source = workspace.data_dir
        removal_path = _new_removal_path(source)
        source_stat = source.stat(follow_symlinks=False)

        with workspace.data_lock.hold(
            exclusive=True,
            timeout_seconds=lock_timeout_seconds,
        ):
            recovery = workspace.imported_hand_recovery
            quarantined = tuple(
                sorted(
                    set(recovery.quarantined)
                    | set(workspace.imported_hands.list_quarantined_cascades())
                )
            )
            if quarantined or recovery.failed:
                raise PlayerUninstallError(
                    "Player data has recovery evidence requiring attention; repair"
                    " or preserve the workspace before removal"
                )
            _require_portable_workspace_inventory(workspace)
            archive = _build_player_backup_archive_from_locked_workspace(
                workspace,
                max_archive_bytes=max_archive_bytes,
            )
            try:
                _publish_verified_backup(
                    archive,
                    output_path=output_path,
                    max_archive_bytes=max_archive_bytes,
                )
            finally:
                archive.close()

            renamed = False
            try:
                try:
                    os.rename(source, removal_path)
                except OSError as exc:
                    raise PlayerUninstallError(
                        f"Backup was created at {output_path}, but player data"
                        f" remains at {source} because it could not be moved for"
                        " removal"
                    ) from exc
                renamed = True
                return _finish_moved_workspace_removal(
                    source=source,
                    removal_path=removal_path,
                    source_stat=source_stat,
                    output_path=output_path,
                )
            except KeyboardInterrupt:
                if not renamed:
                    raise
                return PlayerUninstallResult(
                    archive_path=output_path,
                    retained_data_path=removal_path,
                    warning=(
                        "Player data removal was interrupted after the verified"
                        " backup was created; inspect the retained removal path"
                    ),
                )
            except Exception as exc:
                if not renamed:
                    raise
                return PlayerUninstallResult(
                    archive_path=output_path,
                    retained_data_path=removal_path,
                    warning=(
                        "Player data was moved out of service, but cleanup failed"
                        f" unexpectedly: {exc}"
                    ),
                )
    finally:
        lease.release(lease_descriptor)


def _finish_moved_workspace_removal(
    *,
    source: Path,
    removal_path: Path,
    source_stat: os.stat_result,
    output_path: Path,
) -> PlayerUninstallResult:
    try:
        moved_stat = removal_path.stat(follow_symlinks=False)
    except OSError as exc:
        return PlayerUninstallResult(
            archive_path=output_path,
            retained_data_path=removal_path,
            warning=(
                "Player data was moved out of service, but the retained removal"
                f" path could not be inspected: {exc}"
            ),
        )
    if (
        not S_ISDIR(moved_stat.st_mode)
        or moved_stat.st_dev != source_stat.st_dev
        or moved_stat.st_ino != source_stat.st_ino
    ):
        return PlayerUninstallResult(
            archive_path=output_path,
            retained_data_path=removal_path,
            warning=(
                "Player data was moved out of service, but the removal target"
                " could not be verified for cleanup"
            ),
        )

    try:
        _fsync_directory(source.parent)
    except PlayerUninstallError as exc:
        return PlayerUninstallResult(
            archive_path=output_path,
            retained_data_path=removal_path,
            warning=str(exc),
        )

    try:
        shutil.rmtree(removal_path)
    except OSError as exc:
        return PlayerUninstallResult(
            archive_path=output_path,
            retained_data_path=removal_path,
            warning=(
                "The verified backup is safe, but removed player data requires"
                f" manual cleanup: {exc}"
            ),
        )
    try:
        _fsync_directory(source.parent)
    except PlayerUninstallError as exc:
        return PlayerUninstallResult(
            archive_path=output_path,
            retained_data_path=(
                removal_path if os.path.lexists(removal_path) else None
            ),
            warning=str(exc),
        )

    if os.path.lexists(source):
        return PlayerUninstallResult(
            archive_path=output_path,
            retained_data_path=source,
            warning=(
                "The original player data was removed, but another process"
                " recreated the active data path; stop the local runtime before"
                " retrying"
            ),
        )

    return PlayerUninstallResult(archive_path=output_path)


def _workspace_path_identity(source: Path) -> str:
    return sha256(os.fsencode(str(source))).hexdigest()[:24]


def _removal_path_prefix(source: Path) -> str:
    return f"{PLAYER_REMOVAL_DIRECTORY_PREFIX}{_workspace_path_identity(source)}-"


def _retained_removal_paths(source: Path) -> tuple[Path, ...]:
    prefix = _removal_path_prefix(source)
    try:
        with os.scandir(source.parent) as entries:
            return tuple(
                sorted(
                    (
                        source.parent / entry.name
                        for entry in entries
                        if entry.name.startswith(prefix)
                    ),
                    key=str,
                )
            )
    except OSError as exc:
        raise PlayerUninstallError(
            "Cannot inspect the player data parent for an interrupted removal"
        ) from exc


def _require_portable_workspace_inventory(workspace: PlayerWorkspace) -> None:
    """Refuse to delete bytes the portable player backup does not enumerate."""

    allowed_root_files = {
        DATA_LOCK_FILENAME,
        PLAYER_INSTALLATION_SECRET_FILENAME,
        PLAYER_WORKSPACE_MANIFEST_FILENAME,
        LEARNING_CONTENT_CATALOG_FILENAME,
        REFERENCE_ACTIVATION_CATALOG_FILENAME,
        REMOTE_REFERENCE_CONSENT_FILENAME,
        *(
            f"{PLAYER_HAND_LOCK_PREFIX}-{index:02d}.lock"
            for index in range(DEFAULT_PLAYER_HAND_LOCK_STRIPES)
        ),
    }
    try:
        with os.scandir(workspace.data_dir) as entries:
            root_entries = list(entries)
    except OSError as exc:
        raise PlayerUninstallError(
            "Cannot inventory the player workspace before removal"
        ) from exc

    saw_imported_hands = False
    for entry in root_entries:
        if entry.name == IMPORTED_HANDS_DIRNAME:
            if not entry.is_dir(follow_symlinks=False):
                raise PlayerUninstallError(
                    "The imported-hand store changed during removal inventory"
                )
            saw_imported_hands = True
            continue
        if entry.name not in allowed_root_files or not entry.is_file(
            follow_symlinks=False
        ):
            raise PlayerUninstallError(
                f"Player workspace entry {entry.name!r} is not covered by the"
                " portable backup; preserve or repair it before removal"
            )
    if not saw_imported_hands:
        raise PlayerUninstallError(
            "The imported-hand store disappeared during removal inventory"
        )

    records_dir = workspace.imported_hands.records_dir
    try:
        with os.scandir(records_dir) as entries:
            record_entries = list(entries)
    except OSError as exc:
        raise PlayerUninstallError(
            "Cannot inventory the imported-hand store before removal"
        ) from exc

    for entry in record_entries:
        if entry.name == ".cascade":
            if not entry.is_dir(follow_symlinks=False):
                raise PlayerUninstallError(
                    "Lifecycle recovery data changed during removal inventory"
                )
            _require_empty_recovery_inventory(Path(entry.path))
            continue
        if RECORD_KEY_PATTERN.fullmatch(entry.name) is None or not entry.is_dir(
            follow_symlinks=False
        ):
            raise PlayerUninstallError(
                f"Imported-hand entry {entry.name!r} is not covered by the portable"
                " backup; preserve or repair it before removal"
            )
        _require_record_inventory(Path(entry.path), entry.name)


def _require_empty_recovery_inventory(cascade_root: Path) -> None:
    try:
        with os.scandir(cascade_root) as entries:
            cascade_entries = list(entries)
    except OSError as exc:
        raise PlayerUninstallError(
            "Cannot inventory lifecycle recovery data before removal"
        ) from exc
    for entry in cascade_entries:
        if entry.name != "corrupt" or not entry.is_dir(follow_symlinks=False):
            raise PlayerUninstallError(
                "Lifecycle recovery data is not covered by the portable backup;"
                " restart and repair the workspace before removal"
            )
        try:
            with os.scandir(entry.path) as quarantined:
                if next(quarantined, None) is not None:
                    raise PlayerUninstallError(
                        "Quarantined lifecycle recovery evidence must be preserved"
                        " or repaired before removal"
                    )
        except OSError as exc:
            raise PlayerUninstallError(
                "Cannot inventory quarantined lifecycle recovery evidence"
            ) from exc


def _require_record_inventory(record_dir: Path, record_key: str) -> None:
    try:
        with os.scandir(record_dir) as entries:
            record_entries = list(entries)
    except OSError as exc:
        raise PlayerUninstallError(
            f"Cannot inventory imported-hand record {record_key}"
        ) from exc

    saw_record = False
    for entry in record_entries:
        if entry.name == RECORD_FILENAME and entry.is_file(follow_symlinks=False):
            saw_record = True
            continue
        if entry.name == DECISIONS_DIRNAME and entry.is_dir(follow_symlinks=False):
            _require_decision_inventory(Path(entry.path), record_key)
            continue
        if entry.name == GRADES_DIRNAME and entry.is_dir(follow_symlinks=False):
            _require_grade_inventory(Path(entry.path), record_key)
            continue
        raise PlayerUninstallError(
            f"Imported-hand record entry {record_key}/{entry.name} is not covered"
            " by the portable backup; preserve or repair it before removal"
        )
    if not saw_record:
        raise PlayerUninstallError(
            f"Imported-hand record {record_key} has no portable record payload;"
            " preserve or repair it before removal"
        )


def _require_decision_inventory(decisions_dir: Path, record_key: str) -> None:
    try:
        with os.scandir(decisions_dir) as entries:
            decision_entries = list(entries)
    except OSError as exc:
        raise PlayerUninstallError(
            f"Cannot inventory decision artifacts for {record_key}"
        ) from exc
    for entry in decision_entries:
        if DECISION_ARTIFACT_PATTERN.fullmatch(entry.name) is None or not entry.is_file(
            follow_symlinks=False
        ):
            raise PlayerUninstallError(
                f"Decision entry {record_key}/{entry.name} is not covered by the"
                " portable backup; preserve or repair it before removal"
            )


def _require_grade_inventory(grades_dir: Path, record_key: str) -> None:
    try:
        with os.scandir(grades_dir) as entries:
            grade_entries = list(entries)
    except OSError as exc:
        raise PlayerUninstallError(
            f"Cannot inventory grade artifacts for {record_key}"
        ) from exc
    for entry in grade_entries:
        if GRADE_ARTIFACT_PATTERN.fullmatch(entry.name) is None or not entry.is_file(
            follow_symlinks=False
        ):
            raise PlayerUninstallError(
                f"Grade entry {record_key}/{entry.name} is not covered by the"
                " portable backup; preserve or repair it before removal"
            )


def _require_safe_removal_source(source: Path) -> None:
    if source == source.parent:
        raise PlayerUninstallError("Refusing to remove a filesystem root")
    try:
        home = Path.home().resolve(strict=True)
    except OSError:
        home = None
    if home is not None and source == home:
        raise PlayerUninstallError("Refusing to remove the current user home directory")
    try:
        current_directory = Path.cwd().resolve(strict=True)
    except OSError as exc:
        raise PlayerUninstallError(
            "Cannot verify the current directory before removing player data"
        ) from exc
    if current_directory == source or source in current_directory.parents:
        raise PlayerUninstallError(
            "Refusing to remove a player workspace containing the current directory"
        )

    try:
        parent_stat = source.parent.stat(follow_symlinks=False)
    except OSError as exc:
        raise PlayerUninstallError(
            "Cannot safely inspect the player data parent directory"
        ) from exc
    if not S_ISDIR(parent_stat.st_mode):
        raise PlayerUninstallError("The player data parent must be a directory")
    if parent_stat.st_mode & 0o022:
        raise PlayerUninstallError(
            "The player data parent must not be writable by other users"
        )
    if hasattr(os, "getuid") and parent_stat.st_uid != os.getuid():
        raise PlayerUninstallError(
            "The player data parent must be owned by the current user"
        )
    reject_macos_extended_acl(source.parent)


def _require_safe_archive_output(source: Path, archive_path: Path) -> Path:
    requested = Path(archive_path)
    if requested.suffix.lower() != ".zip":
        raise PlayerUninstallError("The player backup output must use a .zip suffix")
    try:
        destination = requested.parent.resolve(strict=True)
        destination_stat = destination.stat(follow_symlinks=False)
    except OSError as exc:
        raise PlayerUninstallError(
            "The player backup output directory must already exist"
        ) from exc
    if not S_ISDIR(destination_stat.st_mode):
        raise PlayerUninstallError("The player backup output parent is not a directory")
    if destination_stat.st_mode & 0o022:
        raise PlayerUninstallError(
            "The player backup output directory must not be writable by other users"
        )
    if hasattr(os, "getuid") and destination_stat.st_uid != os.getuid():
        raise PlayerUninstallError(
            "The player backup output directory must be owned by the current user"
        )
    reject_macos_extended_acl(destination)
    if destination == source or source in destination.parents:
        raise PlayerUninstallError(
            "The player backup output must be outside the player data directory"
        )

    output_path = destination / requested.name
    try:
        os.lstat(output_path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise PlayerUninstallError(
            "Cannot safely inspect the player backup output path"
        ) from exc
    else:
        raise PlayerUninstallError(
            "The player backup output already exists and will not be overwritten"
        )
    return output_path


def _new_removal_path(source: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return source.parent / (
        f"{_removal_path_prefix(source)}{timestamp}-{uuid4().hex[:12]}"
    )


def _publish_verified_backup(
    archive: BinaryIO,
    *,
    output_path: Path,
    max_archive_bytes: int,
) -> None:
    temp_path: Path | None = None
    publication_error: Exception | None = None
    try:
        archive.seek(0)
        digest = sha256()
        with NamedTemporaryFile(
            "wb",
            dir=output_path.parent,
            prefix=".poker-hero-player-removal-backup.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temp_path = Path(output.name)
            os.fchmod(output.fileno(), 0o600)
            while chunk := archive.read(PLAYER_BACKUP_STREAM_CHUNK_SIZE):
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())

        temp_payload = _read_private_backup(temp_path, max_archive_bytes)
        if sha256(temp_payload).digest() != digest.digest():
            raise PlayerUninstallError(
                "The staged player backup does not match the exported snapshot"
            )
        parse_player_backup_archive(
            temp_payload,
            max_archive_bytes=max_archive_bytes,
        )
        os.link(temp_path, output_path)
    except (
        OSError,
        PlayerBackupError,
        PlayerDataDirectoryError,
        PlayerUninstallError,
    ) as exc:
        publication_error = exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as exc:
                if publication_error is None:
                    publication_error = exc

    if publication_error is not None:
        raise PlayerUninstallError(
            "Could not publish and verify the player backup; player data was not"
            " removed"
        ) from publication_error

    try:
        _fsync_directory(output_path.parent)
        published_payload = _read_private_backup(output_path, max_archive_bytes)
        if sha256(published_payload).digest() != digest.digest():
            raise PlayerUninstallError(
                "The published player backup changed before removal"
            )
        parse_player_backup_archive(
            published_payload,
            max_archive_bytes=max_archive_bytes,
        )
    except (
        OSError,
        PlayerBackupError,
        PlayerDataDirectoryError,
        PlayerUninstallError,
    ) as exc:
        raise PlayerUninstallError(
            f"Backup publication at {output_path} could not be made durable and"
            " verified; player data was not removed"
        ) from exc


def _read_private_backup(path: Path, max_bytes: int) -> bytes:
    reject_macos_extended_acl(path)
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not S_ISREG(file_stat.st_mode):
            raise PlayerUninstallError("The player backup must be a regular file")
        if file_stat.st_mode & 0o077:
            raise PlayerUninstallError(
                "The player backup must be accessible only by its owner"
            )
        if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
            raise PlayerUninstallError(
                "The player backup must be owned by the current user"
            )
        if file_stat.st_size > max_bytes:
            raise PlayerUninstallError("The player backup exceeds its size limit")
        chunks: list[bytes] = []
        total_bytes = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total_bytes))
            if not chunk:
                break
            chunks.append(chunk)
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise PlayerUninstallError(
                    "The player backup exceeds its size limit"
                )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise PlayerUninstallError(
            f"Could not make player data removal durable in {directory}"
        ) from exc


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export a verified local player backup, then remove the active data"
            " workspace. This does not uninstall application files."
        ),
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Override POKER_DATA_DIR",
    )
    parser.add_argument(
        "--confirm-remove-data",
        action="store_true",
        help="Confirm permanent removal after the backup is verified",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    settings: Settings | None = None,
) -> int:
    args = _argument_parser().parse_args(argv)
    if not args.confirm_remove_data:
        print(
            "Refusing to remove player data without --confirm-remove-data",
            file=sys.stderr,
        )
        return 2
    try:
        active_settings = settings or get_settings()
    except ValidationError as exc:
        first_error = exc.errors(include_url=False)[0]
        location = ".".join(str(part) for part in first_error["loc"])
        print(
            f"Settings configuration is invalid at {location}:"
            f" {first_error['msg']}",
            file=sys.stderr,
        )
        return 2
    if active_settings.deployment_environment != "local":
        print(
            "Player data removal is available only in the local deployment"
            " environment",
            file=sys.stderr,
        )
        return 2
    if args.data_dir is not None:
        active_settings = active_settings.model_copy(
            update={"data_dir": args.data_dir}
        )

    try:
        result = export_and_remove_player_data(
            active_settings.data_dir,
            args.archive,
            max_archive_bytes=active_settings.max_backup_upload_bytes,
            lock_timeout_seconds=active_settings.data_lock_export_timeout_seconds,
        )
    except (
        DataLockError,
        PlayerBackupError,
        PlayerDataDirectoryError,
        PlayerUninstallError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(f"Verified backup: {result.archive_path}")
    if result.completed:
        print("Player data removal completed")
        return 0
    print(result.warning, file=sys.stderr)
    if result.retained_data_path is not None:
        print(
            f"Retained data requiring attention: {result.retained_data_path}",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
