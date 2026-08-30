"""Durable cascade journal for multi-record writes.

Some player-local operations must touch more than one on-disk record at
once - for example, approving an imported hand rewrites both the hand's
own record and a derived index entry. Every other durable primitive in
this codebase makes exactly one os.replace durable per call, and none of
them record that a multi-record operation is in flight. CascadeJournal is
that missing primitive.

The design is roll-forward, never rollback. begin() durably writes an
intent.json naming every record key the cascade will touch before it lets
the caller stage anything. Staged bytes live under a scratch
.cascade/<cascade_id>/staged/ tree until the with block exits cleanly. At
that point, and before any staged file is published to its live location,
a ready marker is written and made durable - the marker's own file
descriptor is fsynced, then the cascade directory is fsynced so the
marker's directory entry survives a crash too. Only once that marker is
durable does commit start renaming staged files into their live
locations.

That marker is what makes staging all-or-nothing. If the process is
killed at any point before the marker exists, no live file has been
touched, and recover() finds a cascade directory with no ready marker and
simply discards it - indistinguishable from a crash before begin() ever
ran. If the process is killed after the marker exists (mid-commit, or
before the cascade directory is removed), recover() finds the marker,
trusts it, and finishes the job by replaying the same commit - which is
why commit must be idempotent, and why stage() refuses any record key the
intent did not name up front.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from app.storage.persistence import _fsync_directory

CASCADE_SCHEMA_VERSION = "imported-hand-cascade/v1"

_CASCADE_DIRNAME = ".cascade"
_STAGED_DIRNAME = "staged"
_INTENT_FILENAME = "intent.json"
_READY_FILENAME = "ready"
_UNLINK_SUFFIX = ".unlink"


class CascadeIntent(BaseModel):
    """The durable, up-front record of what a cascade will touch.

    Once this is on disk, the cascade is committed to touching exactly
    these record keys; recover() trusts nothing it has not named here.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["imported-hand-cascade/v1"]
    cascade_id: str
    operation: Literal[
        "approve",
        "reapprove",
        "withdraw",
        "reject",
        "request_deletion",
        "purge",
        "restore",
    ]
    record_keys: list[str] = Field(min_length=1)
    started_at: AwareDatetime

    @field_validator("record_keys")
    @classmethod
    def _record_keys_are_unique_and_sorted(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("record_keys must be unique")
        if value != sorted(value):
            raise ValueError("record_keys must be sorted")
        return value


class CascadeStaging:
    """The write surface handed to callers inside a begin() block.

    Every path staged here is scratch space under the cascade's own
    staged/ directory; nothing here is visible at its live location until
    commit runs.
    """

    def __init__(self, record_keys: frozenset[str], staged_dir: Path) -> None:
        self._record_keys = record_keys
        self._staged_dir = staged_dir

    def stage(self, record_key: str, relative_path: str, payload: bytes) -> None:
        target = self._resolve(record_key, relative_path)
        _durable_replace(target, payload)

    def stage_delete(self, record_key: str, relative_path: str) -> None:
        target = self._resolve(record_key, relative_path + _UNLINK_SUFFIX)
        _durable_replace(target, b"")

    def _resolve(self, record_key: str, relative_path: str) -> Path:
        if record_key not in self._record_keys:
            raise ValueError(
                f"record key {record_key!r} is not named by this cascade"
            )
        record_dir = self._staged_dir / record_key
        candidate = record_dir / relative_path
        return _resolve_under(record_dir, candidate)


class CascadeJournal:
    """Makes a multi-record write crash-safe by journaling it before it runs.

    root is the directory the cascade's record keys are relative to (for
    the imported-hand store, <data>/imported-hands); the journal keeps its
    own scratch state under root/.cascade.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._cascade_root = self._root / _CASCADE_DIRNAME

    @contextmanager
    def begin(
        self, *, operation: str, record_keys: Sequence[str]
    ) -> Iterator["CascadeStaging"]:
        cascade_id = self._prepare(operation=operation, record_keys=record_keys)
        cascade_dir = self._cascade_root / cascade_id
        intent = self._read_intent(cascade_dir)
        staging = CascadeStaging(
            record_keys=frozenset(intent.record_keys),
            staged_dir=cascade_dir / _STAGED_DIRNAME,
        )
        try:
            yield staging
        except BaseException:
            shutil.rmtree(cascade_dir, ignore_errors=True)
            raise
        else:
            # Staging is only all-or-nothing once this marker is durable:
            # nothing below this line may touch a live path before it is.
            self._mark_ready(cascade_id)
            self._commit(cascade_dir)

    def recover(self) -> list[str]:
        if not self._cascade_root.is_dir():
            return []
        completed: list[str] = []
        cascade_dirs = sorted(
            (path for path in self._cascade_root.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
        for cascade_dir in cascade_dirs:
            if not (cascade_dir / _READY_FILENAME).is_file():
                # No ready marker proves commit never began: staging may be
                # complete, partial, or empty, but no live file has been
                # touched either way, so discarding is always safe.
                shutil.rmtree(cascade_dir, ignore_errors=True)
                continue
            try:
                self._read_intent(cascade_dir)
            except (FileNotFoundError, ValidationError, json.JSONDecodeError):
                shutil.rmtree(cascade_dir, ignore_errors=True)
                continue
            self._commit(cascade_dir)
            completed.append(cascade_dir.name)
        return completed

    def _prepare(self, *, operation: str, record_keys: Sequence[str]) -> str:
        cascade_id = uuid4().hex
        intent = CascadeIntent(
            schema_version=CASCADE_SCHEMA_VERSION,
            cascade_id=cascade_id,
            operation=operation,
            record_keys=sorted(record_keys),
            started_at=datetime.now(timezone.utc),
        )
        cascade_dir = self._cascade_root / cascade_id
        (cascade_dir / _STAGED_DIRNAME).mkdir(parents=True)
        _durable_replace(
            cascade_dir / _INTENT_FILENAME,
            intent.model_dump_json().encode("utf-8"),
        )
        return cascade_id

    def _mark_ready(self, cascade_id: str) -> None:
        cascade_dir = self._cascade_root / cascade_id
        _durable_replace(cascade_dir / _READY_FILENAME, b"")

    def _read_intent(self, cascade_dir: Path) -> CascadeIntent:
        payload = (cascade_dir / _INTENT_FILENAME).read_bytes()
        return CascadeIntent.model_validate_json(payload)

    def _commit(self, cascade_dir: Path) -> None:
        staged_dir = cascade_dir / _STAGED_DIRNAME
        if staged_dir.is_dir():
            record_dirs = sorted(
                (path for path in staged_dir.iterdir() if path.is_dir()),
                key=lambda path: path.name,
            )
            for record_dir in record_dirs:
                self._commit_record(record_dir)
        shutil.rmtree(cascade_dir)
        _fsync_directory(self._cascade_root)

    def _commit_record(self, record_dir: Path) -> None:
        record_key = record_dir.name
        staged_files = sorted(
            (path for path in record_dir.rglob("*") if path.is_file()),
            key=lambda path: path.as_posix(),
        )
        for staged_file in staged_files:
            relative = staged_file.relative_to(record_dir)
            if relative.suffix == _UNLINK_SUFFIX:
                self._commit_delete(record_key, relative)
            else:
                self._commit_replace(record_key, relative, staged_file)

    def _commit_replace(
        self, record_key: str, relative: Path, staged_file: Path
    ) -> None:
        target = self._root / record_key / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_file, target)
        _fsync_directory(target.parent)

    def _commit_delete(self, record_key: str, relative: Path) -> None:
        target = self._root / record_key / relative.with_suffix("")
        target.unlink(missing_ok=True)
        if target.parent.is_dir():
            _fsync_directory(target.parent)


def _resolve_under(base_dir: Path, candidate: Path) -> Path:
    base = base_dir.resolve()
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"{candidate} must stay inside {base_dir}") from exc
    return resolved


def _durable_replace(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=target.parent,
            prefix=".cascade-journal.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    _fsync_directory(target.parent)
