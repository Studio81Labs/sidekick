"""File-backed store for player-local imported-hand records.

Layout, relative to the data directory::

    imported-hands/<record_key>/record.json
    imported-hands/<record_key>/decisions/r<revision>-g<generation>.json
    imported-hands/.cascade/...            (the write journal's scratch area)

``<record_key>`` is a sha256 of the hand's stable identity, computed once
when the record is first written. That is deliberately the *only* handle
on a record: a purged hand keeps its directory but its tombstone drops
the identity and every audit list it was derived from
(``ImportedHandRecord.validate_aggregate``), so the key cannot be
recomputed from anything stored. Deriving it from the identity a caller
already holds is what lets a later re-import of the same hand find the
tombstone and bump its deletion generation. Nothing here may fall back to
scanning records and comparing ``identity`` fields -- that fallback reads
as harmless and fails silently for exactly the case it exists to serve.

Decision artifacts are the hero decision points ``extract_hero_decision_points``
derives from an approved hand -- a later, separate concern from the record
above, so they get their own file rather than growing record.json. Each is
named ``r<revision>-g<generation>.json``, so whether one is stale is decidable
**from the filename alone**: it is active only while both numbers still match
the record's current ``lifecycle``, and nothing here may open a file just to
find that out. A superseded artifact is never deleted here -- issue #432
requires it stay retained for audit -- only the lifecycle's permanent purge,
through ``ImportedHandCascade.stage_decisions_delete``, may remove one. Nor is
one ever silently replaced: staging a *different* artifact under a name
already occupied raises ``DecisionArtifactRetentionError`` rather than
``os.replace``-ing the retained one out of existence, which is the same
loss by another route and one no caller above this layer can even see
coming (see that class).

The revision component is *not* simply the extraction's own
``canonical_revision``: a rejected extraction (``outcome="not_extractable"``)
is forbidden from binding one at all, by decisions.py's own validation, even
when the record producing it is otherwise active -- a rejection for
``incomplete_economics`` on an active revision-1 record carries
``canonical_revision=None`` exactly like a rejection for ``not_active`` on a
withdrawn one. Filing every rejection at generation ``g`` under one name
would collapse them onto each other: reapproving a still-broken hand at
revision 2 would silently ``os.replace`` its revision-1 predecessor's
retained verdict out of existence, which is exactly the deletion-outside-Task-6
this module forbids. So a rejection is instead filed under the *record's*
current ``active_canonical_revision`` when it has one, preserving the
revision dimension across reapprovals that keep failing -- except a
``not_active`` rejection, which proves from its own content that the record
was not learning eligible at the moment it was computed and so must never
borrow whatever revision the record has since been reactivated to (see
``FileImportedHandStore._decision_revision_for``). Only when no revision
survives to offer does it fall to the reserved ``NO_CANONICAL_REVISION``
sentinel, which can never equal a real revision and so can never be mistaken
for an active canonical artifact. Either way, a rejection is still
generation-stamped, which is what lets a caller tell "still not extractable
at generation 2" apart from a stale verdict computed at generation 1.

Every write goes through :class:`app.storage.cascade_journal.CascadeJournal`
rather than a bare atomic file write, even though a record write touches
one file today. A later lifecycle transition has to move a record and its
derived decision artifacts together, and only a cascade can make that one
durable unit. ``begin_cascade`` is that composition primitive: it opens one
cascade over a record key and hands back an ``ImportedHandCascade`` through
which a caller stages a record, decision artifacts, or an artifact deletion
-- any mix, in one unit, committed or discarded together. ``save`` and
``save_decisions`` are single-operation convenience wrappers built on top of
it, each opening its own cascade for exactly the one thing it stages; a
caller that must move more than one thing together (an approval, a
reapproval, a purge) uses ``begin_cascade`` directly instead of calling
either of them, since the journal lock they take is the same non-reentrant
leaf lock described below and calling one from inside an already-open
cascade raises ``CascadeReentryError`` rather than deadlocking.

Locking, both halves of it. ``recover`` needs an **exclusive**
interprocess hold of the data lock, because the journal serialises a
sweep against a live cascade only within one process. That is only half
a contract: exclusivity means nothing unless every writer is holding the
same lock **shared** while its cascade is open. Inheriting that from the
HTTP middleware would be an accident -- ``/mcp`` is exempt from the data
lock entirely (``bootstrap.py:511-513``) and already carries mutating
tools, and a background thread or a non-mutating GET is exempt too -- so
``save`` takes the shared hold itself rather than trusting its caller.
Shared holds compose, so a caller that already holds one (an in-flight
mutating request) is unaffected. The one rule this creates: never call
``save`` while holding the data lock *exclusively*, which would block on
your own hold; the acquire is bounded so that mistake surfaces as a named
``DataLockTimeoutError`` rather than a hang.

The two methods are therefore deliberately asymmetric, and the asymmetry
is a decision rather than an oversight. ``save`` self-locks because it is
self-contained: the hold it needs starts and ends inside the call.
``recover`` cannot, because an exclusive self-acquire nested inside the
caller's own exclusive hold would block on that hold, deadlocking on some
platforms. So ``recover`` requires its caller to hold the lock
exclusively, and cannot check that it did. What the hold must cover is
the sweep itself, from before it starts until after it returns -- and
only that. Construction caches nothing about ``.cascade`` (it creates the
record directory and builds a journal object; every directory read
happens inside ``recover``), so it does not need to be inside the hold,
and ``has_interrupted_writes`` is deliberately outside it. This is the
more dangerous direction to get wrong: a sweep run without the hold
deletes another process's live cascade, where an unlocked write merely
exposes its own. ``WorkspaceCoordinator.open`` is the only caller today;
anything else that calls it -- a maintenance CLI, say -- must take
``InterprocessDataLock(data_dir).hold(exclusive=True)`` around store
construction and the sweep together.

Within the process, the journal holds its own lock for the whole of a
``save`` and the whole of a ``recover``, and treats it as a **leaf lock**:
a caller that also needs the workspace's striped record locks must take
those *first* (``WorkspaceCoordinator.hold_imported_hands``), because
taking a workspace lock inside an open cascade inverts the established
order into an ABBA deadlock. This store takes no workspace lock of its
own, so the journal stays innermost. ``save``, ``save_decisions``,
``begin_cascade``, and ``recover`` all block, so none of them may be
called on the event-loop thread of the FastAPI process.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from stat import S_ISREG
from typing import Sequence

from pydantic import ValidationError

from app.application.imported_hand_ports import (
    ImportedHandRecoveryReport,
    ImportedHandRepository,
    ReimportResolution,
)
from app.data_lock import (
    DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    InterprocessDataLock,
)
from app.domain.imported_hands import (
    DetectedImportedHand,
    HandDecisionExtraction,
    ImportedHandRecord,
    RawHandHistory,
    StableHandIdentity,
    classify_reimport,
    extract_hero_decision_points,
    imported_hand_canonical_json,
)
from app.storage.cascade_journal import CascadeJournal, CascadeStaging

IMPORTED_HANDS_DIRNAME = "imported-hands"
RECORD_FILENAME = "record.json"
RECORD_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DECISIONS_DIRNAME = "decisions"
DECISION_ARTIFACT_PATTERN = re.compile(r"^r(?P<revision>\d+)-g(?P<generation>\d+)\.json$")
# HandDecisionExtraction.canonical_revision is a PositiveInteger whenever it
# is set, so 0 is never a real revision: reserved as the filename's revision
# component for a not_extractable extraction, which binds no canonical
# revision at all (see the module docstring).
NO_CANONICAL_REVISION = 0


class ImportedHandNotFoundError(LookupError):
    """No record is stored under the requested key.

    Absence only. A permanently deleted hand is *not* absent -- its
    tombstone is a stored record and ``get`` returns it -- so callers
    must not read this as "deleted".
    """


class DecisionArtifactRetentionError(RuntimeError):
    """Staging an artifact would have replaced a different one already
    filed under the same ``(revision, generation)`` name.

    Issue #432 retains a superseded artifact for audit, and every path
    that could remove one is closed except this one, which removes it by
    writing over its name: ``_commit_replace`` ends in ``os.replace``,
    which is silent, and ``list_decision_artifacts`` reports the same
    triple before and after, so nothing downstream can tell the artifact
    changed identity. A caller whose transition leaves a record's
    revision and generation exactly where they are -- recording a
    conflict against an already-approved hand is the reachable case --
    resolves to a name the approved verdict already occupies.

    Refused here rather than above this layer because the artifact
    namespace is this store's, and nothing holding only the repository
    port can see it. Identical bytes are not a replacement and still
    succeed, so a retried cascade recomputing the same verdict is
    unaffected; the comparison is on the serialized payload, so an
    artifact written by an older model version can compare unequal to a
    semantically identical one and be refused. That is the safe
    direction: it fails loudly rather than losing the older bytes.
    """


class DecisionArtifactIntegrityError(RuntimeError):
    """An active artifact no longer matches its canonical hand record.

    Persisted decisions are derived learning state, never an independent source
    of truth. A payload can satisfy its own schema while still carrying a legal
    but different action size, betting line, or provenance from the canonical
    record. Active reads therefore re-extract the expected artifact and refuse
    a mismatch instead of serving contradictory learning evidence. Historical
    artifacts remain schema-validated audit snapshots because the current
    aggregate extractor deliberately targets only the active revision.
    """


class ClosedCascadeError(RuntimeError):
    """A ``stage_*`` call reached an ``ImportedHandCascade`` after its
    ``with`` block already exited.

    Neither the cascade handle nor its underlying ``CascadeStaging`` is
    otherwise invalidated on exit -- ``CascadeStaging`` was always shaped
    that way, harmlessly, while it stayed internal to this module.
    ``begin_cascade`` hands one to callers now, including future
    application-layer code where "compute the extraction in a helper that
    returns the cascade" is an ordinary mistake to make. A call on an
    escaped handle would otherwise succeed locally while writing nothing
    durable: the scratch directory it recreates has no ready marker, and
    the next ``recover()`` sweep discards a marker-less directory
    silently -- reported in none of its three buckets, because pre-marker
    discard is not surfaced. This exists so that mistake is loud instead.
    """


class ImportedHandSnapshotError(RuntimeError):
    """The store cannot produce or apply a trustworthy backup snapshot."""


class ImportedHandSnapshotLimitError(ImportedHandSnapshotError):
    """A snapshot cannot be buffered within the caller's explicit limits."""


@dataclass(frozen=True)
class ImportedHandSnapshotArtifact:
    filename: str
    payload: bytes
    extraction: HandDecisionExtraction


@dataclass(frozen=True)
class ImportedHandStoredSnapshot:
    record_key: str
    record_payload: bytes
    record: ImportedHandRecord
    decision_artifacts: tuple[ImportedHandSnapshotArtifact, ...]


@dataclass(frozen=True)
class ImportedHandRestoreWrite:
    snapshot: ImportedHandStoredSnapshot
    write_record: bool
    decision_artifacts: tuple[ImportedHandSnapshotArtifact, ...]
    delete_decision_artifacts: tuple[str, ...]


def imported_hand_record_key(identity: StableHandIdentity) -> str:
    """Return the durable store key for a hand's stable identity.

    Canonicalised through ``imported_hand_canonical_json``, the same
    domain helper ``imported_hand_state_sha256`` uses, so there is one
    canonical form in the codebase rather than two copies of a formula
    that can drift apart.

    The digest is lowercase hex, which also satisfies the journal's
    record-key rules: a single path segment, no separators, no ``..``,
    no leading dot.
    """
    if identity is None:
        # Reachable only by passing a tombstone's identity, which is
        # always None. Failing loudly beats an AttributeError here,
        # because the caller's real bug is that they tried to re-derive a
        # key that can only come from the directory a record already
        # lives in.
        raise ValueError(
            "a record key cannot be derived without a stable hand identity; "
            "a deletion tombstone has none, so its key is only recoverable "
            "from the identity of the hand being re-imported"
        )
    return sha256(
        imported_hand_canonical_json(identity.model_dump(mode="json"))
    ).hexdigest()


class FileImportedHandStore:
    """``ImportedHandRepository`` implemented over the local data volume."""

    def __init__(
        self,
        data_dir: Path,
        *,
        write_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS,
    ) -> None:
        """Open the store rooted at ``data_dir``.

        ``write_lock_timeout_seconds`` bounds the shared interprocess hold
        every write takes (see the module docstring on why writes lock at
        all). What it protects against is a caller holding the data lock
        *exclusively* while a write wants in: a backup export building an
        archive, another instance's startup recovery sweep, or -- the bug
        case -- this process itself, since a write nested inside an
        exclusive hold would block on that hold forever.

        Failing fast is deliberate here, and it is the opposite of what
        startup wants. A write runs on a request path, where giving up
        with a named ``DataLockTimeoutError`` beats stalling a client for
        the length of an archive build; startup has nowhere to return an
        error to and so waits an export out instead. The two therefore
        have separate settings, and the fact that this default currently
        equals the startup *exclusive* bound is a coincidence, not a link
        -- either may move without the other.
        """
        self.data_dir = Path(data_dir)
        self.records_dir = (self.data_dir / IMPORTED_HANDS_DIRNAME).resolve()
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self._journal = CascadeJournal(self.records_dir)
        self._data_lock = InterprocessDataLock(self.data_dir)
        self._write_lock_timeout_seconds = write_lock_timeout_seconds

    def get(self, record_key: str) -> ImportedHandRecord:
        path = self._record_path(record_key)
        try:
            payload = path.read_bytes()
        except FileNotFoundError as exc:
            raise ImportedHandNotFoundError(record_key) from exc
        # Deliberately unguarded: a stored aggregate that no longer
        # validates is a corrupted file, not a missing record, and the
        # ValidationError has to reach the caller rather than be reshaped
        # into an absence they would silently overwrite.
        return ImportedHandRecord.model_validate_json(payload)

    def find(self, identity: StableHandIdentity) -> ImportedHandRecord | None:
        try:
            return self.get(imported_hand_record_key(identity))
        except ImportedHandNotFoundError:
            return None

    def list_keys(self) -> list[str]:
        try:
            entries = list(self.records_dir.iterdir())
        except FileNotFoundError:
            return []
        return sorted(
            path.name
            for path in entries
            if RECORD_KEY_PATTERN.fullmatch(path.name) is not None
            and (path / RECORD_FILENAME).is_file()
        )

    def save(self, record_key: str, record: ImportedHandRecord) -> ImportedHandRecord:
        """Durably publish ``record`` under ``record_key``, alone.

        A single-operation convenience wrapper around ``begin_cascade``:
        opens its own cascade, stages only this record, and commits. A
        caller that must move this record and a decision artifact together
        in one unit wants ``begin_cascade`` directly instead.
        """
        with self.begin_cascade(record_key, operation="save") as cascade:
            cascade.stage_record(record)
        return record

    def save_decisions(self, record_key: str, extraction: HandDecisionExtraction) -> None:
        """Durably persist one decision-extraction artifact, alone.

        A single-operation convenience wrapper around ``begin_cascade``:
        opens its own cascade, stages only this artifact, and commits. See
        the module docstring for how its filename is derived and why, and
        ``ImportedHandCascade.stage_decisions`` for the exact rule. A caller
        that must move this artifact and its record together in one unit
        (a fresh approval, a reapproval) wants ``begin_cascade`` directly
        instead, so the artifact is filed against the revision the cascade
        is about to publish rather than whatever is still live until commit.

        Persisting a rejection this way is coupled to ``record_key``'s
        stored record still parsing: when the extraction itself carries no
        canonical revision, resolving its filename rereads that record,
        and a corrupted one makes this raise rather than silently losing
        the revision dimension by falling back to a sentinel it cannot
        justify (see ``FileImportedHandStore._decision_revision_for``).
        """
        with self.begin_cascade(record_key, operation="save") as cascade:
            cascade.stage_decisions(extraction)

    @contextmanager
    def begin_cascade(
        self, record_key: str, *, operation: str
    ) -> Iterator[ImportedHandCascade]:
        """Open one cascade over ``record_key`` for a caller composing a write.

        Yields an ``ImportedHandCascade`` through which the caller stages
        any mix of the record itself, one or more decision artifacts, and a
        decision-artifact deletion (the lifecycle purge only -- see
        ``ImportedHandCascade.stage_decisions_delete``); everything staged
        commits together when the ``with`` block exits normally, or nothing
        does if it raises. ``save`` and ``save_decisions`` are
        single-operation convenience wrappers built on this same primitive,
        each opening and closing its own cascade around one stage; a caller
        moving more than one thing together -- an approval, a reapproval, a
        purge -- must call this directly instead of composing calls to
        those wrappers, none of which this store implements itself.

        A decision artifact staged through the returned handle is not
        written until the ``with`` block finishes: which revision it
        resolves to can depend on a record staged *later* in the same
        cascade, so resolution happens once, at the end, against whatever
        record the cascade ends up staging -- never against call order.
        The handle is invalidated the instant the block exits, success or
        failure alike; a ``stage_*`` call afterward raises
        ``ClosedCascadeError`` rather than writing into scratch space
        nothing will ever commit.

        Takes the same shared interprocess hold ``save`` always has, for
        the same reason (see the module docstring), for the whole cascade
        rather than per stage. The journal lock underneath is a
        non-reentrant leaf lock: calling ``save``, ``save_decisions``, or
        this method again from inside an already-open cascade raises
        ``CascadeReentryError`` rather than deadlocking, so a caller
        composing a write must stage everything through the one handle
        this yields, never by nesting another call to open a second one.

        ``operation`` must be one of the labels ``CascadeIntent`` declares
        (``cascade_journal.py``); an invalid one fails with a validation
        error before anything is staged, not silently.

        Blocking. Never call it on the event-loop thread.
        """
        self._require_well_formed_key(record_key)
        # The shared interprocess hold is what gives the startup sweep's
        # exclusive hold any meaning: a cascade opened without it is
        # invisible to a recover() running in another process, which would
        # then sweep it away mid-flight. Taken here rather than left to the
        # caller because several real entry points (/mcp, background
        # threads, non-mutating GETs) hold no data lock at all. Data lock
        # outside, journal inside - the journal is the leaf lock.
        with self._data_lock.hold(
            exclusive=False,
            timeout_seconds=self._write_lock_timeout_seconds,
        ):
            with self._journal.begin(
                operation=operation, record_keys=[record_key]
            ) as staging:
                cascade = ImportedHandCascade(self, record_key, staging)
                # _finalize runs whether the caller's block raised or not:
                # on success it resolves and writes every buffered decision
                # artifact before the journal's own context manager decides
                # to commit; on failure whatever it writes lands in the
                # same scratch tree the journal's exception handling
                # discards wholesale, so it never becomes visible either
                # way. Either way the cascade is closed once this returns.
                #
                # The two calls differ in one way only: when the caller's
                # block is already unwinding, _finalize must not raise. It
                # runs in the unwinding path, so its own error would
                # REPLACE the caller's - leaving the original alive only as
                # __context__ - and its errors are the least useful of the
                # two. Staging decisions before the record is the natural
                # order the API encourages, so a stage_record
                # ValidationError would routinely surface as a retention
                # error resolved against the stale on-disk record: a
                # diagnostic about a name that was never going to be
                # written, hiding the reason nothing was.
                try:
                    yield cascade
                except BaseException:
                    cascade._finalize(unwinding=True)
                    raise
                else:
                    cascade._finalize()

    def get_decisions(
        self, record_key: str, *, revision: int, generation: int
    ) -> HandDecisionExtraction | None:
        """Return the artifact stored at exactly this revision and generation.

        ``None`` means only that nothing was ever staged there -- it says
        nothing about whether ``revision``/``generation`` are current for
        ``record_key``. A caller that wants the current artifact, and only
        the current one, wants ``active_decisions`` instead.

        ``None`` also covers a malformed ``record_key``, matching
        ``active_decisions`` and ``list_decision_artifacts``: every reader
        of decision artifacts treats "nothing found" the same way,
        regardless of why. A malformed key is a caller bug worth failing
        loudly for, but that belongs to the write methods
        (``_require_well_formed_key``), not to this one.
        """
        try:
            path = self._decision_artifact_path(record_key, revision, generation)
        except ImportedHandNotFoundError:
            return None
        try:
            payload = path.read_bytes()
        except FileNotFoundError:
            return None
        return HandDecisionExtraction.model_validate_json(payload)

    def active_decisions(self, record_key: str) -> HandDecisionExtraction | None:
        """Return the one artifact current for ``record_key``, or ``None``.

        "Current" is decided against the record's live lifecycle, read
        fresh on every call, never against whatever the caller last saw:
        its present ``active_canonical_revision`` and
        ``deletion_generation``. A record that is not ``learning_eligible``
        has no active revision to bind an artifact to and so has no active
        decisions at all, even while a prior revision's artifact is still
        sitting on disk, retained for audit.

        The filename is only the first currentness gate. A stored artifact is
        derived state and can be internally valid while still disagreeing with
        the canonical record, so an active read re-extracts the expected value
        through the domain boundary and compares the complete result. This also
        closes the case where a record gains an unresolved conflict without a
        revision or generation change: the old artifact is refused rather than
        served as current learning evidence. No poker rule is duplicated here;
        the store delegates the derivation to ``extract_hero_decision_points``.

        ``get_decisions`` remains the historical audit reader. It schema-checks
        retained bytes but does not claim that an inactive revision can be
        re-derived by the active-revision extractor.
        """
        try:
            record = self.get(record_key)
        except ImportedHandNotFoundError:
            return None
        if not record.lifecycle.learning_eligible:
            return None
        active_revision = record.lifecycle.active_canonical_revision
        assert active_revision is not None  # guaranteed by learning_eligible
        stored = self.get_decisions(
            record_key,
            revision=active_revision,
            generation=record.lifecycle.deletion_generation,
        )
        if stored is None:
            return None
        expected = extract_hero_decision_points(record)
        if stored != expected:
            raise DecisionArtifactIntegrityError(
                f"active decision artifact for record {record_key} does not"
                " match the freshly derived canonical decision state"
            )
        return stored

    def list_decision_artifacts(self, record_key: str) -> list[tuple[int, int, str]]:
        """Return every retained ``(revision, generation, filename)`` triple.

        Sorted, filename-only like every staleness decision this store
        makes: no artifact is opened or parsed to build this list. Includes
        artifacts that are no longer active, retained for audit per issue
        #432, and the ``NO_CANONICAL_REVISION`` slot a rejected extraction
        is filed under.

        The filename is the exact name matched on disk, not a name
        reconstructed from the parsed pair -- ``r01-g0.json`` parses to
        ``(1, 0)`` under this method's own pattern, but is not the name
        ``_decision_artifact_path`` would build from that pair. That is
        exactly why ``ImportedHandCascade.stage_decisions_delete`` (Task
        6's purge) takes this filename directly rather than a
        ``(revision, generation)`` pair to reconstruct from: a
        reconstructed name that silently does not match leaves the real
        file behind -- ``_commit_delete`` unlinks with ``missing_ok=True``,
        so a purge would report success while the artifact survives it.
        """
        try:
            entries = list(self._decisions_dir(record_key).iterdir())
        except (FileNotFoundError, ImportedHandNotFoundError):
            return []
        artifacts: list[tuple[int, int, str]] = []
        for path in entries:
            match = DECISION_ARTIFACT_PATTERN.fullmatch(path.name)
            if match is not None and path.is_file():
                artifacts.append(
                    (
                        int(match.group("revision")),
                        int(match.group("generation")),
                        path.name,
                    )
                )
        return sorted(artifacts)

    def backup_snapshot(
        self,
        *,
        max_record_bytes: int | None = None,
        max_artifact_bytes: int | None = None,
        max_total_bytes: int | None = None,
    ) -> tuple[ImportedHandStoredSnapshot, ...]:
        """Read a validated, byte-preserving snapshot for player backup.

        The caller must hold the data lock exclusively for the entire read and
        archive build. Exact bytes are retained so a restore can distinguish an
        idempotent artifact from a same-name replacement without normalising
        older serialisation formats. Optional byte limits are enforced while
        each file is read, before its payload is retained in the snapshot.
        """

        byte_limits = (max_record_bytes, max_artifact_bytes, max_total_bytes)
        if any(limit is not None and limit <= 0 for limit in byte_limits):
            raise ValueError("Snapshot byte limits must be positive")

        snapshots: list[ImportedHandStoredSnapshot] = []
        total_bytes = 0
        for record_key in self.list_keys():
            record_payload = self._read_bounded_snapshot_file(
                self._record_path(record_key),
                subject=f"record {record_key}",
                max_file_bytes=max_record_bytes,
                max_total_bytes=max_total_bytes,
                total_bytes=total_bytes,
            )
            total_bytes += len(record_payload)
            try:
                record = ImportedHandRecord.model_validate_json(record_payload)
            except ValidationError as exc:
                raise ImportedHandSnapshotError(
                    f"Stored record {record_key} is invalid"
                ) from exc
            try:
                self._require_matching_identity(
                    record_key,
                    record.identity,
                    subject="record",
                )
            except ValueError as exc:
                raise ImportedHandSnapshotError(
                    f"Stored record {record_key} has a mismatched identity"
                ) from exc
            artifacts: list[ImportedHandSnapshotArtifact] = []
            for _revision, _generation, filename in self.list_decision_artifacts(
                record_key
            ):
                payload = self._read_bounded_snapshot_file(
                    self._decisions_dir(record_key) / filename,
                    subject=f"decision artifact {record_key}/{filename}",
                    max_file_bytes=max_artifact_bytes,
                    max_total_bytes=max_total_bytes,
                    total_bytes=total_bytes,
                )
                total_bytes += len(payload)
                try:
                    extraction = HandDecisionExtraction.model_validate_json(payload)
                except ValidationError as exc:
                    raise ImportedHandSnapshotError(
                        f"Stored decision artifact {record_key}/{filename} is invalid"
                    ) from exc
                self._validate_snapshot_artifact(
                    record_key,
                    filename,
                    extraction,
                    record=record,
                )
                artifacts.append(
                    ImportedHandSnapshotArtifact(
                        filename=filename,
                        payload=payload,
                        extraction=extraction,
                    )
                )
            if record.lifecycle.status == "deleted" and artifacts:
                raise ImportedHandSnapshotError(
                    f"Deleted record {record_key} still has decision artifacts"
                )
            self._validate_active_snapshot_artifact(
                record_key,
                record,
                artifacts,
            )
            snapshots.append(
                ImportedHandStoredSnapshot(
                    record_key=record_key,
                    record_payload=record_payload,
                    record=record,
                    decision_artifacts=tuple(artifacts),
                )
            )
        return tuple(snapshots)

    @classmethod
    def _read_bounded_snapshot_file(
        cls,
        path: Path,
        *,
        subject: str,
        max_file_bytes: int | None,
        max_total_bytes: int | None,
        total_bytes: int,
    ) -> bytes:
        remaining_total = (
            None
            if max_total_bytes is None
            else max(max_total_bytes - total_bytes, 0)
        )
        limits = tuple(
            limit
            for limit in (max_file_bytes, remaining_total)
            if limit is not None
        )
        read_limit = min(limits) if limits else None
        try:
            return cls._read_snapshot_file(
                path,
                subject=subject,
                max_bytes=read_limit,
            )
        except ImportedHandSnapshotLimitError as exc:
            if remaining_total is not None and (
                max_file_bytes is None or remaining_total < max_file_bytes
            ):
                raise ImportedHandSnapshotLimitError(
                    "Backup snapshot exceeds the allowed total size"
                ) from exc
            raise

    def apply_backup_restore(
        self,
        writes: Sequence[ImportedHandRestoreWrite],
    ) -> None:
        """Atomically publish pre-classified backup writes.

        The caller must hold the data lock exclusively and must classify every
        candidate against the current store while holding that same lock. This
        primitive deliberately does not acquire the store's ordinary shared
        write hold, which would self-block under the exclusive restore hold.
        """

        if not writes:
            return
        record_keys = [write.snapshot.record_key for write in writes]
        if record_keys != sorted(set(record_keys)):
            raise ImportedHandSnapshotError(
                "Backup restore record keys must be unique and sorted"
            )
        for write in writes:
            snapshot = write.snapshot
            self._require_well_formed_key(snapshot.record_key)
            try:
                self._require_matching_identity(
                    snapshot.record_key,
                    snapshot.record.identity,
                    subject="record",
                )
            except ValueError as exc:
                raise ImportedHandSnapshotError(
                    f"Backup record {snapshot.record_key} has a mismatched identity"
                ) from exc
            try:
                parsed_record = ImportedHandRecord.model_validate_json(
                    snapshot.record_payload
                )
            except ValidationError as exc:
                raise ImportedHandSnapshotError(
                    f"Backup record {snapshot.record_key} is invalid"
                ) from exc
            if parsed_record != snapshot.record:
                raise ImportedHandSnapshotError(
                    f"Backup record {snapshot.record_key} changed after validation"
                )
            self._validate_active_snapshot_artifact(
                snapshot.record_key,
                snapshot.record,
                snapshot.decision_artifacts,
            )
            for artifact in write.decision_artifacts:
                self._validate_snapshot_artifact(
                    snapshot.record_key,
                    artifact.filename,
                    artifact.extraction,
                    record=snapshot.record,
                )
                try:
                    parsed_extraction = HandDecisionExtraction.model_validate_json(
                        artifact.payload
                    )
                except ValidationError as exc:
                    raise ImportedHandSnapshotError(
                        "Backup decision artifact "
                        f"{snapshot.record_key}/{artifact.filename} is invalid"
                    ) from exc
                if parsed_extraction != artifact.extraction:
                    raise ImportedHandSnapshotError(
                        "Backup decision artifact "
                        f"{snapshot.record_key}/{artifact.filename} changed after validation"
                    )
            delete_filenames = write.delete_decision_artifacts
            if len(delete_filenames) != len(set(delete_filenames)):
                raise ImportedHandSnapshotError(
                    "Backup restore decision-artifact deletions must be unique"
                )
            staged_filenames = {
                artifact.filename for artifact in write.decision_artifacts
            }
            for filename in delete_filenames:
                if DECISION_ARTIFACT_PATTERN.fullmatch(filename) is None:
                    raise ImportedHandSnapshotError(
                        f"{filename!r} is not a decision artifact filename"
                    )
                if filename in staged_filenames:
                    raise ImportedHandSnapshotError(
                        f"Backup restore cannot write and delete {filename!r}"
                    )

        with self._journal.begin(
            operation="restore",
            record_keys=record_keys,
        ) as staging:
            for write in writes:
                snapshot = write.snapshot
                if write.write_record:
                    staging.stage(
                        snapshot.record_key,
                        RECORD_FILENAME,
                        snapshot.record_payload,
                    )
                for artifact in write.decision_artifacts:
                    staging.stage(
                        snapshot.record_key,
                        f"{DECISIONS_DIRNAME}/{artifact.filename}",
                        artifact.payload,
                    )
                for filename in write.delete_decision_artifacts:
                    staging.stage_delete(
                        snapshot.record_key,
                        f"{DECISIONS_DIRNAME}/{filename}",
                    )

    def existing_decision_artifact_payload(
        self,
        record_key: str,
        filename: str,
    ) -> bytes | None:
        if DECISION_ARTIFACT_PATTERN.fullmatch(filename) is None:
            raise ImportedHandSnapshotError(
                f"{filename!r} is not a decision artifact filename"
            )
        path = self._decisions_dir(record_key) / filename
        try:
            return self._read_snapshot_file(
                path,
                subject=f"decision artifact {record_key}/{filename}",
            )
        except FileNotFoundError:
            return None

    @staticmethod
    def _read_snapshot_file(
        path: Path,
        *,
        subject: str,
        max_bytes: int | None = None,
    ) -> bytes:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise ImportedHandSnapshotError(
                f"Cannot safely read {subject}"
            ) from exc
        try:
            file_stat = os.fstat(descriptor)
            if not S_ISREG(file_stat.st_mode):
                raise ImportedHandSnapshotError(f"{subject} is not a regular file")
            if max_bytes is not None and file_stat.st_size > max_bytes:
                raise ImportedHandSnapshotLimitError(
                    f"{subject} exceeds the allowed snapshot size"
                )
            chunks: list[bytes] = []
            bytes_read = 0
            while True:
                read_size = 1024 * 1024
                if max_bytes is not None:
                    read_size = min(read_size, max_bytes - bytes_read + 1)
                chunk = os.read(descriptor, read_size)
                if not chunk:
                    break
                bytes_read += len(chunk)
                if max_bytes is not None and bytes_read > max_bytes:
                    raise ImportedHandSnapshotLimitError(
                        f"{subject} exceeds the allowed snapshot size"
                    )
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def _validate_snapshot_artifact(
        self,
        record_key: str,
        filename: str,
        extraction: HandDecisionExtraction,
        *,
        record: ImportedHandRecord,
    ) -> None:
        match = DECISION_ARTIFACT_PATTERN.fullmatch(filename)
        if match is None:
            raise ImportedHandSnapshotError(
                f"{filename!r} is not a decision artifact filename"
            )
        try:
            self._require_matching_identity(
                record_key,
                extraction.identity,
                subject="extraction",
            )
        except ValueError as exc:
            raise ImportedHandSnapshotError(
                f"Decision artifact {record_key}/{filename} has a mismatched identity"
            ) from exc
        if extraction.identity != record.identity:
            raise ImportedHandSnapshotError(
                f"Decision artifact {record_key}/{filename} does not match its record"
            )
        revision = int(match.group("revision"))
        generation = int(match.group("generation"))
        if generation != extraction.deletion_generation:
            raise ImportedHandSnapshotError(
                f"Decision artifact {record_key}/{filename} has a mismatched generation"
            )
        if generation > record.lifecycle.deletion_generation:
            raise ImportedHandSnapshotError(
                f"Decision artifact {record_key}/{filename} is from a future generation"
            )
        if (
            extraction.canonical_revision is not None
            and revision != extraction.canonical_revision
        ):
            raise ImportedHandSnapshotError(
                f"Decision artifact {record_key}/{filename} has a mismatched revision"
            )
        if extraction.rejection == "not_active" and revision != NO_CANONICAL_REVISION:
            raise ImportedHandSnapshotError(
                f"Decision artifact {record_key}/{filename} must use revision 0"
            )
        retained_revisions = {
            retained.revision for retained in record.canonical_revisions
        }
        if (
            revision != NO_CANONICAL_REVISION
            and revision not in retained_revisions
        ):
            raise ImportedHandSnapshotError(
                f"Decision artifact {record_key}/{filename} names an unknown revision"
            )
        if record.lifecycle.status == "deleted":
            raise ImportedHandSnapshotError(
                f"Deleted record {record_key} cannot retain decision artifacts"
            )

    @staticmethod
    def _validate_active_snapshot_artifact(
        record_key: str,
        record: ImportedHandRecord,
        artifacts: Sequence[ImportedHandSnapshotArtifact],
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
            raise ImportedHandSnapshotError(
                f"Active record {record_key} is missing {active_filename}"
            )
        expected = extract_hero_decision_points(record)
        if active != expected:
            raise ImportedHandSnapshotError(
                f"Active decision artifact {record_key}/{active_filename} "
                "does not match its canonical record"
            )

    def has_interrupted_writes(self) -> bool:
        """Whether ``recover`` would find anything to finish or set aside.

        Cheap, lock-free, and safe to call before deciding whether to take
        the exclusive hold ``recover`` requires: a false answer means the
        journal holds no cascade directory a sweep would act on, so there
        is nothing for exclusivity to protect. A cascade that appears
        after a false answer belongs to another process and is *live*,
        which a sweep must not touch in any case.
        """
        return self._journal.has_pending_cascades()

    def list_quarantined_cascades(self) -> tuple[str, ...]:
        """Return retained recovery evidence that still needs human review."""
        return self._journal.quarantined_cascades()

    def recover(self) -> ImportedHandRecoveryReport:
        """Finish or set aside writes interrupted by an earlier crash.

        **The caller must hold the data lock exclusively across this
        call.** Unlike ``save``, this does not and cannot take the hold
        itself: an exclusive self-acquire inside the caller's own
        exclusive hold would block on it. Nothing here verifies the caller
        complied -- see the module docstring for why the two methods
        differ, and for what a new caller owes.

        Ask ``has_interrupted_writes`` first: it needs no hold, and a
        false answer means this call has nothing to do, so the exclusive
        acquire can be skipped entirely rather than paid for on a volume
        where no write was ever interrupted.

        Blocking. Never call it on the event-loop thread.
        """
        report = self._journal.recover()
        return ImportedHandRecoveryReport(
            completed=report.completed,
            quarantined=report.quarantined,
            failed=report.failed,
        )

    def _record_path(self, record_key: str) -> Path:
        return self._record_dir(record_key) / RECORD_FILENAME

    def _record_dir(self, record_key: str) -> Path:
        if RECORD_KEY_PATTERN.fullmatch(record_key) is None:
            # A malformed key names no record, and a read must not try to
            # resolve it as a path first.
            raise ImportedHandNotFoundError(record_key)
        return self.records_dir / record_key

    def _decisions_dir(self, record_key: str) -> Path:
        return self._record_dir(record_key) / DECISIONS_DIRNAME

    def _decision_artifact_path(
        self, record_key: str, revision: int, generation: int
    ) -> Path:
        return self._decisions_dir(record_key) / f"r{revision}-g{generation}.json"

    @staticmethod
    def _require_well_formed_key(record_key: str) -> None:
        if RECORD_KEY_PATTERN.fullmatch(record_key) is None:
            raise ValueError(
                f"record key {record_key!r} must be a lowercase hex sha256 "
                "digest produced by imported_hand_record_key"
            )

    @staticmethod
    def _require_matching_identity(
        record_key: str, identity: StableHandIdentity | None, *, subject: str
    ) -> None:
        """Shared guard behind both ``stage_record`` and ``stage_decisions``.

        A record or extraction filed under a key not derived from its own
        identity is findable only by listing every record: ``find`` would
        derive the other key and report the hand as never imported. A
        tombstone, or a rejection for a hand with no stable identity, is
        exempt because there is no identity left to check against -- it is
        filed under the key of the hand it replaced or was extracted from,
        which is the point.
        """
        if identity is not None and imported_hand_record_key(identity) != record_key:
            raise ValueError(
                f"record key {record_key!r} was not derived from this "
                f"{subject}'s own stable identity"
            )

    def _decision_revision_for(
        self,
        record_key: str,
        extraction: HandDecisionExtraction,
        *,
        record: ImportedHandRecord | None,
    ) -> int:
        """Resolve one extraction's filename revision component.

        Prefers the extraction's own ``canonical_revision``. A rejection
        never carries one -- decisions.py's ``validate_outcome`` forbids
        binding a canonical revision to a ``not_extractable`` outcome even
        when the record producing it *is* learning eligible, so this is
        the common path for any rejection on an active record, not a rare
        corner case. Falling back to the record's current
        ``active_canonical_revision`` preserves the revision dimension for
        exactly that case: reapproving a still-broken hand at a new
        revision must not collide with its predecessor's retained
        rejection (see the module docstring). This is key derivation, not
        a domain rule -- it does not re-derive *why* the hand was
        rejected, only *where* to file the verdict.

        Two cases never take that fallback, both because trusting the
        record's *current* state would describe a different moment than
        the one the extraction actually describes:

        - ``rejection == "not_active"`` proves, from the extraction's own
          content alone, that the record was not learning eligible at the
          moment it was computed. If the hand has since been reactivated,
          the record's current ``active_canonical_revision`` belongs to
          that reactivation, not to this rejection -- filing it there
          would produce an artifact whose filename claims "this is the
          hand's current active revision" while its content says "this
          hand was not active", and ``active_decisions`` would then serve
          a not-active verdict as the hand's live decisions. This is
          decidable from the extraction alone, so it always takes the
          sentinel, never the fallback.
        - A generation mismatch between ``record`` and ``extraction``
          means the record has moved on to a different incarnation (a
          purge and reimport) since this extraction was computed. Its
          ``active_canonical_revision`` belongs to that different
          incarnation; pairing it with the extraction's own, older
          ``deletion_generation`` would file a name whose two halves
          describe two different snapshots in time.

        Both fall to the reserved sentinel instead of guessing, which is
        never wrong here: a record with no active revision to offer, or
        whose generation has already moved past this extraction, has only
        one meaningful rejection slot for this generation, so a collision
        there is harmless.

        ``record``, when given, is preferred over rereading the store: a
        caller composing this into a cascade that also stages a new
        revision of the record itself (``ImportedHandCascade.stage_record``
        in the same cascade) needs the revision *about to be* published,
        not whatever is still live on disk until commit. Rereading the
        store when ``record`` is ``None`` couples persisting a rejection
        to ``record.json`` still parsing: a corrupted record now makes
        this raise rather than silently falling back to a sentinel that
        would have lost the revision dimension without a trace. That
        coupling is deliberate, not an oversight -- see
        ``save_decisions``'s own docstring.
        """
        if extraction.canonical_revision is not None:
            return extraction.canonical_revision
        if extraction.rejection == "not_active":
            return NO_CANONICAL_REVISION
        if record is None:
            try:
                record = self.get(record_key)
            except ImportedHandNotFoundError:
                return NO_CANONICAL_REVISION
        if record.lifecycle.deletion_generation != extraction.deletion_generation:
            return NO_CANONICAL_REVISION
        active_revision = record.lifecycle.active_canonical_revision
        return NO_CANONICAL_REVISION if active_revision is None else active_revision


class ImportedHandCascade:
    """The write surface for one open cascade over a single record key.

    Yielded by ``FileImportedHandStore.begin_cascade``; never constructed
    directly. Every ``stage_*`` call here stages into the same underlying
    ``CascadeStaging``, so everything staged through one instance commits
    or is discarded as a single unit -- see ``begin_cascade``'s docstring.

    A decision artifact staged here is buffered, not written immediately:
    which revision it resolves to can depend on a record staged *later* in
    the same cascade (``stage_record``), so every buffered artifact is
    resolved once, at cascade exit, against whichever record this cascade
    ends up staging -- never against the order the caller happened to call
    these methods in. Invalidated the instant the caller's ``with`` block
    exits, success or failure alike: a ``stage_*`` call afterward raises
    ``ClosedCascadeError`` rather than writing into scratch space nothing
    will ever commit.
    """

    def __init__(
        self,
        store: FileImportedHandStore,
        record_key: str,
        staging: CascadeStaging,
    ) -> None:
        self._store = store
        self._record_key = record_key
        self._staging = staging
        self._staged_record: ImportedHandRecord | None = None
        self._pending_extractions: list[HandDecisionExtraction] = []
        self._closed = False

    def stage_record(self, record: ImportedHandRecord) -> None:
        """Stage ``record`` as this cascade's ``record.json``.

        Same identity/key rule ``FileImportedHandStore.save`` enforces.
        Written immediately, unlike a decision artifact: ``record.json``'s
        name never depends on anything else staged in this cascade.
        Remembers ``record`` so a ``stage_decisions`` call anywhere in the
        same cascade -- before this call or after -- resolves against
        *this* record's active revision at cascade exit, rather than
        whatever is still live on disk until commit.
        """
        self._require_open()
        self._store._require_matching_identity(
            self._record_key, record.identity, subject="record"
        )
        # model_dump_json revalidates the whole aggregate on the way out
        # (ImportedHandRecord.serialize_revalidated), so a record that no
        # longer holds together never reaches the disk.
        payload = record.model_dump_json(indent=2).encode("utf-8")
        self._staging.stage(self._record_key, RECORD_FILENAME, payload)
        self._staged_record = record

    def stage_decisions(self, extraction: HandDecisionExtraction) -> None:
        """Stage ``extraction`` as one decision artifact in this cascade.

        Identity is checked immediately, so a caller learns of a foreign
        extraction right away; the filename itself
        (``FileImportedHandStore._decision_revision_for`` -- see the
        module docstring for the rule) is resolved later, at cascade exit,
        against whichever record this cascade ends up staging -- not
        against whatever ``stage_record`` has been called with *so far*.
        Computing the extraction before building the record it came from
        is the natural order, and that order must not silently change
        which revision it lands under. Never removes a sibling artifact:
        a superseded revision's file is left exactly where it is, retained
        for audit per issue #432.

        Nor does it replace one. If the resolved name already holds a
        different artifact -- on disk, or staged earlier in this same
        cascade -- ``_finalize`` raises
        ``DecisionArtifactRetentionError`` and nothing commits. Staging
        the identical payload again is not a replacement and succeeds,
        so a retried cascade is unaffected.
        """
        self._require_open()
        self._store._require_matching_identity(
            self._record_key, extraction.identity, subject="extraction"
        )
        self._pending_extractions.append(extraction)

    def stage_decisions_delete(self, filename: str) -> None:
        """Stage the removal of one decision artifact in this cascade.

        ``filename`` must be the exact name ``list_decision_artifacts``
        reported, never one reconstructed from a ``(revision, generation)``
        pair: ``r01-g0.json`` parses to ``(1, 0)`` under that method's own
        pattern but is not the name a reconstruction from that pair would
        build, and staging a delete for the wrong name leaves the real
        file behind silently -- ``_commit_delete`` unlinks with
        ``missing_ok=True``, so a purge built that way would report
        success while the artifact survives it.

        For permanent purge only: a decision artifact is otherwise retained
        forever (see the module docstring). Staging a delete outside a
        cascade that also writes the tombstone in the same unit would let
        a crash strand an artifact deleted with no tombstone to show for
        it, or a tombstone with an artifact that survived it -- exactly
        what this primitive exists to prevent, so this method is
        deliberately only reachable through an open cascade, never as a
        standalone call.
        """
        self._require_open()
        if DECISION_ARTIFACT_PATTERN.fullmatch(filename) is None:
            raise ValueError(
                f"{filename!r} is not a decision artifact filename; pass "
                "the exact name list_decision_artifacts reported, never "
                "one reconstructed from a (revision, generation) pair"
            )
        self._staging.stage_delete(
            self._record_key, f"{DECISIONS_DIRNAME}/{filename}"
        )

    def _require_open(self) -> None:
        if self._closed:
            raise ClosedCascadeError(
                "this ImportedHandCascade's `with` block has already "
                "exited; every stage_* call must happen before it does, "
                "never after"
            )

    def _finalize(self, *, unwinding: bool = False) -> None:
        """Resolve and write every buffered decision artifact, then close.

        Called exactly once, by ``begin_cascade``, in a ``finally`` after
        the caller's block has finished, whether it raised or not -- so a
        decision artifact's revision is always resolved against this
        cascade's *final* staged record, regardless of ``stage_record`` /
        ``stage_decisions`` call order. Safe to run even when the caller's
        block raised: whatever this stages lands in the same scratch tree
        the journal's own exception handling discards wholesale, so it
        never reaches a live path either way.

        This is also where retention is enforced, because a name is only
        known once it is resolved: an artifact that would replace a
        different one already filed under it raises
        ``DecisionArtifactRetentionError`` and the whole cascade is
        discarded. Two buffered extractions resolving to one name are
        refused on the same rule, before either reaches scratch -- there
        the loss would happen before the commit rather than at it, and
        would never be visible on a live path at all.

        Closes the cascade on the way out whether or not any of that
        raised: a refusal must not leave a live handle behind, which
        would be exactly the escaped-cascade hole ``ClosedCascadeError``
        exists to make loud.

        ``unwinding`` says the caller's block is already failing. Then
        this reports nothing of its own: it still stages what it can and
        still closes, but swallows its own error rather than replacing an
        in-flight exception with a worse one. Nothing is lost by that --
        the whole cascade is discarded either way, so this method's
        errors only ever describe a write that was never going to happen
        -- and the caller keeps the exception that says why.
        """
        try:
            staged: dict[str, bytes] = {}
            for extraction in self._pending_extractions:
                revision = self._store._decision_revision_for(
                    self._record_key, extraction, record=self._staged_record
                )
                relative_path = (
                    f"{DECISIONS_DIRNAME}/"
                    f"r{revision}-g{extraction.deletion_generation}.json"
                )
                payload = extraction.model_dump_json(indent=2).encode("utf-8")
                self._require_retention_preserved(relative_path, payload, staged)
                self._staging.stage(self._record_key, relative_path, payload)
                staged[relative_path] = payload
        except Exception:
            if not unwinding:
                raise
            # Deliberately swallowed: see `unwinding` above. KeyboardInterrupt
            # and SystemExit are not caught here - they are not statements
            # about this cascade and must keep propagating.
        finally:
            self._closed = True

    def _require_retention_preserved(
        self, relative_path: str, payload: bytes, staged: dict[str, bytes]
    ) -> None:
        """Refuse ``payload`` if a different artifact already holds its name.

        Checks what this cascade has already staged first, then what is
        live on disk -- the live file is still the retained artifact,
        since nothing this cascade staged has been committed yet.
        """
        previous = staged.get(relative_path)
        if previous is None:
            try:
                previous = (
                    self._store._record_dir(self._record_key) / relative_path
                ).read_bytes()
            except FileNotFoundError:
                return
        if previous == payload:
            return
        raise DecisionArtifactRetentionError(
            f"staging {relative_path!r} for record {self._record_key} would "
            "replace a different artifact already retained under that name; "
            "issue #432 retains a superseded artifact for audit, and only a "
            "purge may remove one"
        )


def resolve_reimport(
    store: ImportedHandRepository,
    identity: StableHandIdentity,
    raw: RawHandHistory,
    candidate_detection: DetectedImportedHand | None = None,
) -> ReimportResolution:
    """Resolve a candidate raw import against whatever already sits at its key.

    ``classify_reimport`` is the domain's sole authority on what
    ``new_identity`` / ``exact_reimport`` / ``identity_conflict`` means; it
    is called here, not reimplemented. This function only supplies what
    that classifier has no way to know by itself: which store key
    ``identity`` maps to, and whether that key currently holds a deletion
    tombstone rather than a live or pending record.

    ``store.find`` is what makes the tombstone case reachable at all -- it
    resolves through the same key derivation ``save`` used, so a purged
    record (identity=None, every audit list empty) is still found by the
    identity of the hand being re-imported. Classifying against a
    tombstone's empty ``raw_sources`` always yields ``new_identity``
    from the domain's own rule (no existing source shares any identity),
    so ``found_tombstone`` is the only thing that lets a caller tell "never
    imported" apart from "was imported, then deleted". This function does
    not act on that difference -- it neither mutates nor even re-reads the
    stored tombstone after finding it. Bumping the deletion generation to
    turn a hit into a real restoration is the lifecycle boundary's job,
    not this one's.
    """
    if raw.identity != identity:
        # The key below is derived from `identity` alone; if `raw` names a
        # different one, classify_reimport would silently compare it
        # against the wrong record's sources (or none at all) instead of
        # the ones this key actually holds. Failing loudly beats guessing
        # which of the two the caller meant.
        raise ValueError(
            "resolve_reimport's identity and raw.identity must match: the "
            "store key is derived from identity, and a mismatch would "
            "silently stop the candidate from being classified against "
            "its own stored raw sources"
        )
    record_key = imported_hand_record_key(identity)
    existing = store.find(identity)
    found_tombstone = existing is not None and existing.identity is None
    disposition = classify_reimport(
        existing.raw_sources if existing is not None else [],
        raw,
        existing_detections=existing.detections if existing is not None else None,
        candidate_detection=candidate_detection,
    )
    return ReimportResolution(
        disposition=disposition.kind,
        existing_raw_source_id=disposition.existing_raw_source_id,
        record_key=record_key,
        found_tombstone=found_tombstone,
    )
