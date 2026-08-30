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
a ready marker is written and made durable - .cascade itself is fsynced
first so the marker's own directory entry cannot be lost either, then the
marker's file descriptor is fsynced, then the cascade directory is
fsynced. Only once that marker is durable does commit start renaming
staged files into their live locations.

That marker is what makes staging all-or-nothing. If the process is
killed at any point before the marker exists, no live file has been
touched, and recover() finds a cascade directory with no ready marker and
simply discards it - indistinguishable from a crash before begin() ever
ran. If the process is killed after the marker exists (mid-commit, or
before the cascade directory is removed), recover() finds the marker,
trusts it, and finishes the job by replaying the same commit - which is
why commit must be idempotent, and why stage() refuses any record key the
intent did not name up front.

Cross-process contract: this class only serialises begin() against
recover() *within one process*, using an internal lock held for the
lifetime of a cascade and for the whole of recover(). Across processes it
enforces nothing. Any deployment that opens more than one process against
the same root must run recover() to completion before any cascade is
opened against that root anywhere, under an exclusive interprocess lock -
a shared lock is not enough, because recover() must never run
concurrently with an open cascade. Violating this can delete a live
cascade's staged files out from under it: the cascade then durably marks
itself ready over an emptied directory and commits nothing, while its
caller sees no exception and believes the write landed.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
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
    field_validator,
)

from app.storage.persistence import _fsync_directory

CASCADE_SCHEMA_VERSION = "imported-hand-cascade/v1"

_CASCADE_DIRNAME = ".cascade"
_STAGED_DIRNAME = "staged"
_INTENT_FILENAME = "intent.json"
_READY_FILENAME = "ready"
_CONTENT_DIRNAME = "content"
_DELETES_DIRNAME = "deletes"


class CascadeCorruptionError(RuntimeError):
    """A cascade directory is not in a state commit can trust.

    Raised instead of silently discarding or silently no-oping, because
    once the ready marker exists, guessing wrong in either direction can
    strand a record that a caller believes was already applied.
    """


class CascadeIntent(BaseModel):
    """The durable, up-front record of what a cascade will touch.

    Once this is on disk, stage() will not accept a record key this does
    not name. recover() itself never reads this file at all once the
    ready marker exists (see CascadeJournal.recover), so this exists for
    diagnostics and for that write-time validation - it is not part of
    the recovery decision.
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

    @field_validator("record_keys")
    @classmethod
    def _record_keys_cannot_escape_their_directory(cls, value: list[str]) -> list[str]:
        for record_key in value:
            _ensure_record_key_is_safe(record_key)
        return value


class CascadeStaging:
    """The write surface handed to callers inside a begin() block.

    Every path staged here is scratch space under the cascade's own
    staged/<record_key>/ directory, split into a content/ subtree (files
    to publish as-is) and a sibling deletes/ subtree (markers for live
    files to remove). Keeping them in separate subtrees means a content
    file's own name can never be misread as a deletion marker for a
    different file, whatever it happens to be named. Nothing staged here
    is visible at its live location until commit runs.
    """

    def __init__(self, record_keys: frozenset[str], staged_dir: Path) -> None:
        self._record_keys = record_keys
        self._staged_dir = staged_dir

    def stage(self, record_key: str, relative_path: str, payload: bytes) -> None:
        _ensure_relative_path_is_safe(relative_path)
        target = self._resolve(record_key, _CONTENT_DIRNAME, relative_path)
        _durable_replace(target, payload)

    def stage_delete(self, record_key: str, relative_path: str) -> None:
        _ensure_relative_path_is_safe(relative_path)
        target = self._resolve(record_key, _DELETES_DIRNAME, relative_path)
        _durable_replace(target, b"")

    def _resolve(self, record_key: str, namespace: str, relative_path: str) -> Path:
        if record_key not in self._record_keys:
            raise ValueError(
                f"record key {record_key!r} is not named by this cascade"
            )
        namespace_dir = self._staged_dir / record_key / namespace
        candidate = namespace_dir / relative_path
        return _resolve_under(namespace_dir, candidate)


class CascadeJournal:
    """Makes a multi-record write crash-safe by journaling it before it runs.

    root is the directory the cascade's record keys are relative to (for
    the imported-hand store, <data>/imported-hands); the journal keeps its
    own scratch state under root/.cascade. See the module docstring for
    the cross-process locking contract this class depends on.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._cascade_root = self._root / _CASCADE_DIRNAME
        # Serialises begin() against recover() within this process - see
        # the module docstring for what this does and does not guarantee.
        self._lock = threading.Lock()

    @contextmanager
    def begin(
        self, *, operation: str, record_keys: Sequence[str]
    ) -> Iterator["CascadeStaging"]:
        with self._lock:
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
        with self._lock:
            if not self._cascade_root.is_dir():
                return []
            completed: list[str] = []
            cascade_dirs = sorted(
                (path for path in self._cascade_root.iterdir() if path.is_dir()),
                key=lambda path: path.name,
            )
            for cascade_dir in cascade_dirs:
                if not (cascade_dir / _READY_FILENAME).is_file():
                    # Before the marker: discard is always right. Commit
                    # never began, so staging may be complete, partial, or
                    # empty, but no live file has been touched either way -
                    # discarding is indistinguishable from a crash before
                    # begin() ever ran.
                    shutil.rmtree(cascade_dir, ignore_errors=True)
                    continue
                # After the marker: commit is always right. commit() may
                # already have renamed some staged files into live paths,
                # so finishing is the only safe action - stranding the
                # rest would permanently half-apply the cascade, which is
                # exactly what the marker exists to prevent. _commit()
                # replays from staged/ and never reads intent.json, so
                # intent.json's readability is irrelevant to finishing:
                # the intent exists for diagnostics and for the
                # record-key validation stage() does at write time, not
                # for recovery. Do not reintroduce an intent.json check
                # on this branch.
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
        # ready is only trustworthy after a crash if its own entry inside
        # .cascade survives too. fsync that *before* writing the marker,
        # so by the time the marker's own fsync (inside _durable_replace)
        # completes, the whole path down to it is already durable.
        _fsync_directory(self._cascade_root)
        cascade_dir = self._cascade_root / cascade_id
        _durable_replace(cascade_dir / _READY_FILENAME, b"")

    def _read_intent(self, cascade_dir: Path) -> CascadeIntent:
        payload = (cascade_dir / _INTENT_FILENAME).read_bytes()
        return CascadeIntent.model_validate_json(payload)

    def _commit(self, cascade_dir: Path) -> None:
        if not cascade_dir.is_dir():
            # Already committed and removed by an earlier call onto this
            # same cascade directory - finishing is idempotent, so a
            # repeat call has nothing left to do.
            return
        staged_dir = cascade_dir / _STAGED_DIRNAME
        if not staged_dir.is_dir():
            raise CascadeCorruptionError(
                f"{cascade_dir} exists without a {_STAGED_DIRNAME}/ "
                "directory; a legitimate cascade always has one, even when "
                "empty, so this state cannot be trusted enough to finish "
                "or to discard silently"
            )
        record_dirs = sorted(
            (path for path in staged_dir.iterdir() if path.is_dir()),
            key=lambda path: path.name,
        )
        for record_dir in record_dirs:
            self._commit_record(record_dir)
        shutil.rmtree(cascade_dir, ignore_errors=True)
        _fsync_directory(self._cascade_root)

    def _commit_record(self, record_dir: Path) -> None:
        record_key = record_dir.name
        content_dir = record_dir / _CONTENT_DIRNAME
        if content_dir.is_dir():
            for staged_file in sorted(
                (path for path in content_dir.rglob("*") if path.is_file()),
                key=lambda path: path.as_posix(),
            ):
                relative = staged_file.relative_to(content_dir)
                self._commit_replace(record_key, relative, staged_file)
        deletes_dir = record_dir / _DELETES_DIRNAME
        if deletes_dir.is_dir():
            for marker_file in sorted(
                (path for path in deletes_dir.rglob("*") if path.is_file()),
                key=lambda path: path.as_posix(),
            ):
                relative = marker_file.relative_to(deletes_dir)
                self._commit_delete(record_key, relative)

    def _commit_replace(
        self, record_key: str, relative: Path, staged_file: Path
    ) -> None:
        target = self._root / record_key / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_file, target)
        _fsync_directory_chain(target.parent, stop_at=self._root)

    def _commit_delete(self, record_key: str, relative: Path) -> None:
        target = self._root / record_key / relative
        target.unlink(missing_ok=True)
        if target.parent.is_dir():
            _fsync_directory(target.parent)


def _ensure_record_key_is_safe(record_key: str) -> None:
    if (
        not record_key
        or record_key in {".", ".."}
        or Path(record_key).name != record_key
    ):
        raise ValueError(
            f"record key {record_key!r} must be a single path segment: no "
            "separator, and not empty, '.', or '..'"
        )


def _ensure_relative_path_is_safe(relative_path: str) -> None:
    if relative_path in {"", ".", ".."}:
        raise ValueError(
            f"relative path {relative_path!r} must not be empty, '.', or '..'"
        )


def _resolve_under(base_dir: Path, candidate: Path) -> Path:
    base = base_dir.resolve()
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"{candidate} must stay inside {base_dir}") from exc
    return resolved


def _fsync_directory_chain(leaf: Path, *, stop_at: Path) -> None:
    """fsync leaf and every ancestor up to and including stop_at.

    A single mkdir(parents=True) call can create several new directory
    levels at once; fsyncing only the immediate parent makes the file's
    own directory entry durable but says nothing about whether the
    directories above it survive a crash. Walk the whole chain so a crash
    cannot lose an intermediate level - e.g. <root>/<record_key>/ itself -
    while a later fsync elsewhere (commit fsyncs .cascade once the whole
    cascade is done) durably records the cascade as finished regardless.
    """
    current = leaf
    while True:
        _fsync_directory(current)
        if current == stop_at:
            return
        current = current.parent


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
