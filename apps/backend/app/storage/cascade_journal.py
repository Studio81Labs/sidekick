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
a ready marker is written and made durable. Everything the post-marker
replay will later *read* is fsynced first, deepest directory outwards -
every directory of the staged tree, then the cascade directory, then
.cascade, then root - and only then is the marker itself written and
fsynced. Only once that marker is durable does commit start renaming
staged files into their live locations.

The ordering there is the whole point, and it is easy to get wrong: the
marker is a promise that the staged tree can be replayed, so the staged
tree has to be durable *before* the promise is, not merely before the
replay runs. A marker made durable independently of the tree it describes
can survive a crash that the tree does not, after which recover() commits
an empty or partial staged tree and reports success - and _commit cannot
detect it, because an empty staged/ is a legitimate cascade.

That marker is what makes staging all-or-nothing. If the process is
killed at any point before the marker exists, no live file has been
touched, and recover() finds a cascade directory with no ready marker and
simply discards it - indistinguishable from a crash before begin() ever
ran. If the process is killed after the marker exists (mid-commit, or
before the cascade directory is removed), recover() finds the marker,
trusts it, and finishes the job by replaying the same commit - which is
why commit must be idempotent, and why stage() refuses any record key the
intent did not name up front.

recover() is a startup path, so no single cascade directory may stop it,
whatever goes wrong there. Every cascade is swept under its own exception
boundary that catches anything short of a BaseException, and lands in one
of three buckets:

- completed - committed and its directory removed.
- quarantined - proven structurally unusable (CascadeCorruptionError), so
  renamed aside into .cascade/corrupt/<cascade_id> rather than deleted:
  the evidence is the only record of what went wrong.
- failed - commit raised something else. The directory is left exactly
  where it is so the next sweep retries it.

The split between the last two is the important one. Quarantine moves a
directory out of the replay path, which is right only when that directory
is proven unusable; a cascade that merely failed to commit may be
half-applied, and moving it aside would strand it forever. Anything not
proven structurally corrupt is therefore left in place to be retried. The
quarantine attempt is itself wrapped, so a failure to move a directory
aside lands in failed rather than escaping the sweep - otherwise the one
condition most likely to produce a torn cascade in the first place (a full
disk) would also be the one that stops recovery from running.

Locking. This class holds an internal lock for the lifetime of a cascade
and for the whole of recover(), which has three consequences callers must
respect:

- It is **non-reentrant by design**. Calling begin() or recover() from a
  thread already inside a begin() block raises CascadeReentryError rather
  than deadlocking on an untimed acquire.
- Treat it as a **leaf lock**. workspace.py:87-95 establishes the order
  benchmark_corpus_lock -> job_locks -> history_lock; because the journal
  lock is held across the caller's entire block, taking any workspace lock
  *inside* a begin() block inverts that order and creates an ABBA
  deadlock. Acquire every workspace lock you need before begin(), never
  within it.
- This runs in a FastAPI process. The acquire is blocking and untimed, so
  calling begin() or recover() directly on the event-loop thread stalls
  the whole loop for as long as another cascade is open. Callers must go
  through a worker thread (run_in_threadpool / asyncio.to_thread).

Cross-process contract: this class only serialises begin() against
recover() *within one process*. Across processes it enforces nothing. Any
deployment that opens more than one process against the same root must run
recover() to completion before any cascade is opened against that root
anywhere, under an exclusive interprocess lock - a shared lock is not
enough, because recover() must never run concurrently with an open
cascade. Violating this can delete a live cascade's staged files out from
under it: the cascade then durably marks itself ready over an emptied
directory and commits nothing, while its caller sees no exception and
believes the write landed.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
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
_QUARANTINE_DIRNAME = "corrupt"
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

    Out of begin(), this reaches the caller: their write did not land and
    they must know. Out of recover(), it does not - recover() contains it
    per cascade and quarantines the directory, because a startup sweep
    that aborts on one bad directory strands every other half-applied
    cascade and fails identically on every subsequent boot. It is also the
    one error that licenses *moving* a cascade aside: it is a statement
    about the directory's contents, where any other exception says only
    that this attempt failed.
    """


class PendingCascadeError(RuntimeError):
    """A record key already has a cascade waiting to be replayed onto it.

    Roll-forward recovery finishes a ready cascade by replaying its staged
    files over the live ones. That is only correct if nothing newer was
    written in between -- and nothing enforces that on its own. A cascade
    whose commit raised part-way through is left in place to be retried,
    the journal lock is then released, and without this refusal a later
    cascade could commit cleanly over the half-applied state, only for the
    next startup sweep to replay the older staged files on top of it and
    silently erase the newer write.

    So a key stays closed to new cascades from the moment one of its
    cascades is left pending until recovery finishes or sets that cascade
    aside. The remedy is a restart, not repair: recovery runs at startup
    under an exclusive interprocess hold, which a request path must not
    take.
    """


class CascadeReentryError(RuntimeError):
    """A cascade journal call was made from inside another one.

    The journal's lock is held for the caller's whole begin() block and is
    not reentrant, so a nested begin() - or a recover() called from within
    a block - would otherwise block forever on an untimed acquire. Raising
    turns a silent hang into a stack trace pointing at the nesting.
    """


@dataclass(frozen=True)
class CascadeRecoveryReport:
    """What one recover() sweep did.

    The three buckets are deliberately distinct, because they call for
    different things from the caller:

    - completed - finished and its directory removed. Nothing to do.
    - quarantined - proven structurally unusable and moved to
      <root>/.cascade/corrupt/<name>, where the name is the *directory*
      the evidence actually landed in, not necessarily the cascade id
      (see CascadeJournal._quarantine on collisions). Needs a human; will
      not be retried.
    - failed - commit raised, and the directory was left in place. The
      next sweep retries it, so a transient cause self-heals, but a
      persistent one will keep reappearing here.

    Conflating any two of these would let a boot report success over a
    cascade nobody has looked at, or strand one that only needed a retry.
    """

    completed: tuple[str, ...] = ()
    quarantined: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        """False when the sweep had nothing to report.

        The dataclass default would make every report truthy, so a caller
        writing `if journal.recover():` would warn on every clean boot and
        `if not report:` would never fire.
        """
        return bool(self.completed or self.quarantined or self.failed)


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
    # "save" is the record store's own plain write, which no lifecycle
    # verb below describes - a first import lands as pending_review, and
    # naming that "approve" would put a false operation in the one field
    # an operator reading a stranded cascade directory has to go on.
    operation: Literal[
        "save",
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
        # the module docstring for what this does and does not guarantee,
        # and for why it is a non-reentrant leaf lock.
        self._lock = threading.Lock()
        self._lock_owner: int | None = None

    @contextmanager
    def _exclusive(self, call: str) -> Iterator[None]:
        """Hold the journal lock, refusing re-entry instead of deadlocking.

        Reading _lock_owner outside the lock is safe: it is only ever
        non-None while its owning thread is alive and inside this block, so
        a thread can never see its own ident there unless it really is
        re-entering, and never misses its own ident when it is.
        """
        this_thread = threading.get_ident()
        if self._lock_owner == this_thread:
            raise CascadeReentryError(
                f"{call}() was called from a thread that is already inside a "
                "cascade journal block; the journal lock is held for the whole "
                "of that block and is not reentrant. Finish the open cascade "
                "first - see the module docstring on treating this as a leaf "
                "lock."
            )
        with self._lock:
            self._lock_owner = this_thread
            try:
                yield
            finally:
                self._lock_owner = None

    @contextmanager
    def begin(
        self, *, operation: str, record_keys: Sequence[str]
    ) -> Iterator["CascadeStaging"]:
        with self._exclusive("begin"):
            # Checked under the journal lock, so it cannot race another
            # cascade in this process, and before _prepare so a refusal
            # creates nothing on disk.
            self._require_no_pending_cascade(record_keys)
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

    def _require_no_pending_cascade(self, record_keys: Sequence[str]) -> None:
        """Refuse a cascade over a key whose last one is waiting to replay."""
        for record_key in record_keys:
            pending = self.pending_cascade_for(record_key)
            if pending is not None:
                raise PendingCascadeError(
                    f"record {record_key!r} has a cascade ({pending}) that was "
                    "left ready to replay after its commit failed part-way "
                    "through, so this key is closed to new writes: committing "
                    "one now would be silently overwritten when startup "
                    "recovery replays the older staged files on top of it. "
                    "Recovery finishes or sets aside that cascade, and it runs "
                    "at startup under an exclusive lock, so the remedy is to "
                    "restart the backend - not to repair anything by hand."
                )

    def pending_cascade_for(self, record_key: str) -> str | None:
        """The id of a ready cascade recovery will replay over ``record_key``.

        "Ready" is the whole condition. A cascade without the marker is
        discarded by recovery rather than replayed, so it can overwrite
        nothing and does not close the key -- and within this process it
        cannot be observed at all, since the journal lock is held for a
        cascade's entire life. A quarantined cascade is likewise excluded
        (via _sweepable_cascade_dirs): it is never replayed, and counting
        it would close a key permanently.

        Membership is read from staged/<record_key>/, the same place
        _commit replays from, rather than from intent.json -- recovery
        never reads the intent, so a key that is *named* by an intent but
        has nothing staged for it is not a key anything will be written to.
        """
        for cascade_dir in self._sweepable_cascade_dirs():
            if not (cascade_dir / _READY_FILENAME).is_file():
                continue
            if (cascade_dir / _STAGED_DIRNAME / record_key).is_dir():
                return cascade_dir.name
        return None

    def has_pending_cascades(self) -> bool:
        """Whether a sweep would find anything at all to act on.

        Exists so a caller can decide whether recover() is worth an
        exclusive interprocess hold *before* paying for one. It reads the
        same directories recover() sweeps, through the same helper, so the
        two can never disagree about what counts as a cascade - in
        particular an empty .cascade, or one holding nothing but permanent
        quarantine evidence, is correctly "nothing to do" rather than
        "something to sweep forever".

        Takes no lock, and needs none in either direction. False cannot
        become stale in a harmful way: a cascade appearing afterwards is a
        *live* one belonging to another process, which a sweep must not
        touch regardless. True can become stale harmlessly: the cascade
        may finish before the sweep runs, which leaves the sweep with
        nothing to do and an empty report.
        """
        return bool(self._sweepable_cascade_dirs())

    def has_ready_cascades(self) -> bool:
        """Whether startup recovery has durable roll-forward work pending."""

        return any(
            (cascade_dir / _READY_FILENAME).is_file()
            for cascade_dir in self._sweepable_cascade_dirs()
        )

    def quarantined_cascades(self) -> tuple[str, ...]:
        """Return every retained quarantine evidence directory name.

        Quarantine is deliberately excluded from recovery sweeps, but it must
        remain visible to readiness and operator surfaces on every later
        process start. Names are returned without following directory symlinks.
        """
        quarantine_root = self._cascade_root / _QUARANTINE_DIRNAME
        try:
            with os.scandir(quarantine_root) as entries:
                return tuple(
                    sorted(
                        entry.name
                        for entry in entries
                        if entry.is_dir(follow_symlinks=False)
                    )
                )
        except FileNotFoundError:
            return ()

    def _sweepable_cascade_dirs(self) -> list[Path]:
        """Every directory under .cascade that a sweep would consider.

        The quarantine directory holds evidence, not cascades. Sweeping it
        would see a directory with no ready marker and rmtree exactly what
        quarantine exists to preserve.
        """
        if not self._cascade_root.is_dir():
            return []
        return sorted(
            (
                path
                for path in self._cascade_root.iterdir()
                if path.is_dir() and path.name != _QUARANTINE_DIRNAME
            ),
            key=lambda path: path.name,
        )

    def recover(self) -> CascadeRecoveryReport:
        with self._exclusive("recover"):
            completed: list[str] = []
            quarantined: list[str] = []
            failed: list[str] = []
            for cascade_dir in self._sweepable_cascade_dirs():
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
                # Everything below is contained to this one cascade.
                # Letting anything out of the loop would abort the sweep,
                # leave this directory in place to abort every future
                # sweep the same way, and strand the very half-applied
                # cascades recovery exists to finish.
                try:
                    self._commit(cascade_dir)
                except CascadeCorruptionError:
                    # Proven structurally unusable, so it is safe - and
                    # necessary - to move it out of the replay path.
                    try:
                        quarantined.append(self._quarantine(cascade_dir))
                    except Exception:
                        # Even moving it aside failed. Report it and move
                        # on rather than re-raising: a full disk is both a
                        # plausible cause of a torn cascade and a plausible
                        # cause of a failed rename, and it must not be able
                        # to stop the sweep on its way through.
                        failed.append(cascade_dir.name)
                    continue
                except Exception:
                    # Not proven corrupt - only proven to have failed this
                    # time. It may be half-applied, so leave the directory
                    # exactly where it is: quarantining it would strand it,
                    # and discarding it would lose it. The next sweep
                    # retries it, so a transient cause self-heals.
                    failed.append(cascade_dir.name)
                    continue
                completed.append(cascade_dir.name)
            return CascadeRecoveryReport(
                completed=tuple(completed),
                quarantined=tuple(quarantined),
                failed=tuple(failed),
            )

    def _quarantine(self, cascade_dir: Path) -> str:
        """Move an untrustworthy cascade aside, returning where it landed.

        Renamed rather than deleted: this directory is the only record of
        what went wrong, and unlike the pre-marker discard branch there is
        no proof here that commit never began, so its staged tree may be
        the only surviving copy of a half-applied write.

        A quarantined id is not by itself evidence that any data is wrong.
        A cascade that was fully applied and then killed during _commit's
        final rmtree - which can remove staged/ before ready, since scandir
        order is arbitrary - is indistinguishable from a genuinely corrupt
        one, and lands here too. Treat a quarantined id as "a human should
        look", not as "this record is broken".

        Returns the *name of the directory the evidence landed in*, which
        is the cascade id except when that name was already taken. Callers
        report this to operators, so returning the id regardless would
        point them at the previous sweep's evidence instead of this one's.
        """
        quarantine_root = self._cascade_root / _QUARANTINE_DIRNAME
        quarantine_root.mkdir(parents=True, exist_ok=True)
        destination = quarantine_root / cascade_dir.name
        if destination.exists():
            # Only reachable if an id was quarantined twice, which uuid4
            # makes vanishingly unlikely - but silently clobbering earlier
            # evidence would be the one thing quarantine must not do.
            destination = quarantine_root / f"{cascade_dir.name}.{uuid4().hex}"
        os.rename(cascade_dir, destination)
        _fsync_directory(quarantine_root)
        _fsync_directory(self._cascade_root)
        return destination.name

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
        # The marker promises that this cascade's staged tree will be
        # replayed, so everything that replay reads has to be durable
        # before the promise is. _durable_replace only ever fsyncs the one
        # directory holding the file it wrote, which leaves staged/<key>'s
        # entry in staged/, and content/ and deletes/'s entries in
        # staged/<key>, non-durable - yet all three are read *after* the
        # marker. A crash could then leave the marker durable over a
        # staged tree that is gone, and _commit cannot tell the difference
        # because an empty staged/ is a legitimate cascade. So fsync the
        # whole staged chain first, deepest first, then .cascade (so the
        # marker's own directory entry survives), then root (so .cascade's
        # entry survives the first live rename) - and only then write the
        # marker, whose own fsync inside _durable_replace closes the
        # sequence.
        cascade_dir = self._cascade_root / cascade_id
        _fsync_directory_tree(cascade_dir)
        _fsync_directory(self._cascade_root)
        _fsync_directory(self._root)
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
    # A leading dot is rejected outright, not just "." and "..". A record
    # key becomes a directory name directly under root, so a key of
    # ".cascade" writes into the journal's own scratch namespace: staging
    # ".cascade/<32 hex>/ready" publishes a marker for a cascade that never
    # existed and poisons every later recover().
    if (
        not record_key
        or record_key.startswith(".")
        or Path(record_key).name != record_key
    ):
        raise ValueError(
            f"record key {record_key!r} must be a single path segment that "
            "does not begin with '.': no separator, not empty, and never "
            f"'.', '..', or the journal's own {_CASCADE_DIRNAME!r} directory"
        )


def _ensure_relative_path_is_safe(relative_path: str) -> None:
    if relative_path in {"", ".", ".."}:
        raise ValueError(
            f"relative path {relative_path!r} must not be empty, '.', or '..'"
        )
    # Reject '..' anywhere, including paths that normalise back inside.
    # "x/.." resolves to the namespace directory itself, and staging it
    # renames a temp file *onto* staged/<key>/content - a file where a
    # directory belongs - after which _commit_record silently skips the
    # whole record and the cascade commits nothing while reporting success.
    if ".." in Path(relative_path).parts:
        raise ValueError(
            f"relative path {relative_path!r} must stay inside its record: "
            "'..' components are never allowed, not even ones that normalise "
            "back inside"
        )


def _resolve_under(base_dir: Path, candidate: Path) -> Path:
    base = base_dir.resolve()
    resolved = candidate.resolve(strict=False)
    if resolved == base:
        raise ValueError(
            f"{candidate} must stay inside {base_dir}: it normalises to that "
            "directory itself, which is not a file within it"
        )
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


def _fsync_directory_tree(root_dir: Path) -> None:
    """fsync every directory in root_dir's subtree, deepest first.

    _durable_replace fsyncs only the single directory holding the file it
    just wrote, so building staged/<key>/content/a/b.json leaves b.json's
    entry durable while content/'s entry in staged/<key>, and
    staged/<key>'s entry in staged/, are not. Walking bottom-up makes each
    directory durable before the parent whose entry names it.
    """
    if not root_dir.is_dir():
        return
    for parent, dirnames, _filenames in os.walk(root_dir, topdown=False):
        for dirname in dirnames:
            _fsync_directory(Path(parent) / dirname)
    _fsync_directory(root_dir)


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
