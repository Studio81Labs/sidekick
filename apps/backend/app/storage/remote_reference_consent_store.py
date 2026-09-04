"""Private atomic storage for the current remote-reference consent snapshot."""

from __future__ import annotations

import json
import os
from pathlib import Path
from stat import S_ISREG
import tempfile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.remote_references import RemoteReferenceConsent


REMOTE_REFERENCE_CONSENT_FILENAME = ".poker-hero-remote-reference-consent.json"
REMOTE_REFERENCE_CONSENT_SCHEMA = "poker-hero-remote-reference-consent"
REMOTE_REFERENCE_CONSENT_SCHEMA_VERSION = 1
MAX_REMOTE_REFERENCE_CONSENT_BYTES = 32 * 1024


class RemoteReferenceConsentStorageError(RuntimeError):
    """The install-local consent state cannot be trusted or persisted."""


class RemoteReferenceConsentState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_name: Literal[REMOTE_REFERENCE_CONSENT_SCHEMA] = Field(alias="schema")
    schema_version: Literal[REMOTE_REFERENCE_CONSENT_SCHEMA_VERSION]
    consent: RemoteReferenceConsent | None


def empty_remote_reference_consent_state() -> RemoteReferenceConsentState:
    return RemoteReferenceConsentState(
        schema=REMOTE_REFERENCE_CONSENT_SCHEMA,
        schema_version=REMOTE_REFERENCE_CONSENT_SCHEMA_VERSION,
        consent=None,
    )


def _payload(state: RemoteReferenceConsentState) -> bytes:
    return (
        json.dumps(
            state.model_dump(mode="json", by_alias=True),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class FileRemoteReferenceConsentStore:
    """One authoritative, install-local consent state guarded by the volume lock."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / REMOTE_REFERENCE_CONSENT_FILENAME

    def initialize_empty(self) -> RemoteReferenceConsentState:
        """Create the empty state without replacing an interrupted predecessor."""

        temporary_path: Path | None = None
        publication_error: OSError | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=self.data_dir,
                prefix=".poker-hero-remote-reference-consent.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                os.fchmod(temporary.fileno(), 0o600)
                temporary.write(_payload(empty_remote_reference_consent_state()))
                temporary.flush()
                os.fsync(temporary.fileno())
            try:
                os.link(temporary_path, self.path)
            except FileExistsError:
                pass
        except OSError as exc:
            publication_error = exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError as exc:
                    if publication_error is None:
                        publication_error = exc
        if publication_error is not None:
            raise RemoteReferenceConsentStorageError(
                "Cannot durably initialize remote-reference consent state:"
                f" {publication_error}"
            ) from publication_error
        state = self.load()
        try:
            _fsync_directory(self.data_dir)
        except OSError as exc:
            raise RemoteReferenceConsentStorageError(
                f"Cannot make remote-reference consent state durable: {exc}"
            ) from exc
        return state

    def load(self) -> RemoteReferenceConsentState:
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags)
        except OSError as exc:
            raise RemoteReferenceConsentStorageError(
                f"Cannot safely open remote-reference consent state: {exc}"
            ) from exc
        try:
            file_stat = os.fstat(descriptor)
            if not S_ISREG(file_stat.st_mode):
                raise RemoteReferenceConsentStorageError(
                    "Remote-reference consent state must be a regular file"
                )
            if file_stat.st_mode & 0o077:
                raise RemoteReferenceConsentStorageError(
                    "Remote-reference consent state must be readable only by its owner"
                )
            if hasattr(os, "getuid") and file_stat.st_uid != os.getuid():
                raise RemoteReferenceConsentStorageError(
                    "Remote-reference consent state must be owned by the current user"
                )
            chunks: list[bytes] = []
            total_bytes = 0
            while True:
                chunk = os.read(
                    descriptor,
                    MAX_REMOTE_REFERENCE_CONSENT_BYTES + 1 - total_bytes,
                )
                if not chunk:
                    break
                chunks.append(chunk)
                total_bytes += len(chunk)
                if total_bytes > MAX_REMOTE_REFERENCE_CONSENT_BYTES:
                    raise RemoteReferenceConsentStorageError(
                        "Remote-reference consent state exceeds its size limit"
                    )
            payload = b"".join(chunks)
        except OSError as exc:
            raise RemoteReferenceConsentStorageError(
                f"Cannot safely read remote-reference consent state: {exc}"
            ) from exc
        finally:
            os.close(descriptor)
        try:
            return RemoteReferenceConsentState.model_validate_json(payload)
        except ValidationError as exc:
            raise RemoteReferenceConsentStorageError(
                "Remote-reference consent state is malformed or unsupported"
            ) from exc

    def save(self, state: RemoteReferenceConsentState) -> None:
        validated = RemoteReferenceConsentState.model_validate(
            state.model_dump(mode="python", by_alias=True)
        )
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=self.data_dir,
                prefix=".poker-hero-remote-reference-consent.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                os.fchmod(temporary.fileno(), 0o600)
                temporary.write(_payload(validated))
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
            _fsync_directory(self.data_dir)
        except OSError as exc:
            raise RemoteReferenceConsentStorageError(
                f"Cannot durably write remote-reference consent state: {exc}"
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
