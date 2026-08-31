"""Player-only persistence composition for the local V2 runtime."""

from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
from stat import S_ISDIR
import sys

from app.application.imported_hand_ports import ImportedHandRecoveryReport
from app.data_lock import (
    DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
    DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
    DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    InterprocessDataLock,
)
from app.player_hands import (
    PlayerHandDetail,
    PlayerHandList,
    get_player_hand,
    list_player_hands,
)
from app.storage.imported_hand_store import (
    IMPORTED_HANDS_DIRNAME,
    FileImportedHandStore,
)


class PlayerDataDirectoryError(RuntimeError):
    """The configured player data directory is not private local storage."""


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


def _reject_macos_extended_acl(path: Path) -> None:
    if sys.platform != "darwin":
        return
    if _macos_extended_acl_has_entries(path):
        raise PlayerDataDirectoryError(
            f"{path} must not grant access through an extended ACL"
        )


def _private_player_data_dir(data_dir: Path) -> Path:
    try:
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        resolved = data_dir.resolve(strict=True)
        directory_stat = resolved.stat()
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
    _reject_macos_extended_acl(resolved)
    return resolved


def _prepare_imported_hands_dir(data_dir: Path) -> None:
    records_dir = data_dir / IMPORTED_HANDS_DIRNAME
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
    _reject_macos_extended_acl(records_dir)


@dataclass(frozen=True)
class PlayerWorkspace:
    """The stores the local player runtime may open.

    This composition intentionally excludes the V1 job and benchmark stores.
    Future player routes receive this object rather than the hosted workspace,
    so adding a route cannot make administrative screenshot state reachable by
    accident.
    """

    data_dir: Path
    data_lock: InterprocessDataLock
    imported_hands: FileImportedHandStore
    imported_hand_recovery: ImportedHandRecoveryReport

    @classmethod
    def open(
        cls,
        data_dir: Path,
        *,
        recovery_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
        startup_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
        write_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    ) -> "PlayerWorkspace":
        private_data_dir = _private_player_data_dir(Path(data_dir))
        _prepare_imported_hands_dir(private_data_dir)
        data_lock = InterprocessDataLock(private_data_dir)
        imported_hands = FileImportedHandStore(
            private_data_dir,
            write_lock_timeout_seconds=write_lock_timeout_seconds,
        )
        recovery = ImportedHandRecoveryReport()
        if imported_hands.has_interrupted_writes():
            with data_lock.hold(
                exclusive=True,
                timeout_seconds=recovery_lock_timeout_seconds,
            ):
                recovery = imported_hands.recover()

        # Do not declare the player store ready while an exclusive backup or
        # recovery operation owns the volume. Like the hosted startup path,
        # this bounded shared hold waits for legitimate exclusive work to
        # drain and turns a genuinely wedged volume into an explicit failure.
        with data_lock.hold(
            exclusive=False,
            timeout_seconds=startup_lock_timeout_seconds,
        ):
            pass
        return cls(
            data_dir=private_data_dir,
            data_lock=data_lock,
            imported_hands=imported_hands,
            imported_hand_recovery=recovery,
        )

    def status_payload(
        self,
        *,
        lock_timeout_seconds: int = DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
    ) -> dict[str, object]:
        # A restore publishes several files under an exclusive hold. Status
        # must take the shared side so it can never report an intermediate
        # filesystem view from another process.
        with self.data_lock.hold(
            exclusive=False,
            timeout_seconds=lock_timeout_seconds,
        ):
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
            return list_player_hands(
                self.imported_hands,
                limit=limit,
                cursor=cursor,
            )

    def get_hand_record(
        self,
        record_key: str,
        *,
        lock_timeout_seconds: int = DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS,
    ) -> PlayerHandDetail:
        """Read one validated record projection under the shared volume lock."""

        with self.data_lock.hold(
            exclusive=False,
            timeout_seconds=lock_timeout_seconds,
        ):
            return get_player_hand(self.imported_hands, record_key)
