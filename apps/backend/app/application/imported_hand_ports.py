"""Persistence port for player-local imported-hand records.

The adapter behind this port is file-backed, but nothing in these
signatures may say so. Records are addressed by an opaque string record
key and exchanged as domain aggregates -- never as paths, handles, or
anything else that would drag the filesystem into the application layer.
tests/test_source_architecture.py enforces that direction: this layer may
import only ``application`` and ``domain``, and neither ``pathlib`` nor
``app.storage``.

The key itself is derived once, when a record is first written, and the
adapter's own directory naming is thereafter the only way to find that
record again. A purged record keeps its key but loses everything it was
derived from, so nothing here may offer a "look it up by identity"
fallback that walks stored records: see ``find`` below.

``begin_cascade`` is the one composition primitive here, and it is what
keeps a lifecycle transition honest without naming a mechanism: a caller
stages a record and its derived artifacts through the handle it yields
and gets them published together. Expressing that as a port method
rather than as an ordered pair of writes is deliberate -- ordering two
independent writes cannot close the window between them, and only the
adapter knows how to make one unit of both.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal, Protocol

from app.domain.imported_hands import (
    HandDecisionExtraction,
    ImportedHandRecord,
    StableHandIdentity,
)


@dataclass(frozen=True)
class ReimportResolution:
    """What a freshly parsed raw hand means relative to the local store.

    ``classify_reimport`` (``app.domain.imported_hands``) is the sole
    authority for ``disposition`` and ``existing_raw_source_id`` -- both
    are carried through unchanged. This adds only what that classifier has
    no way to know without a store: the ``record_key`` the candidate's
    identity maps to, and whether that key currently holds a deletion
    tombstone rather than a live or pending record.

    A tombstone keeps no raw sources or detections at all
    (``ImportedHandRecord.validate_aggregate`` forbids a deleted record
    from retaining any), so classifying against one always yields
    ``new_identity`` -- ``found_tombstone`` is what lets a caller tell that
    apart from a hand that was never imported before. Seeing it true is
    not license to resurrect anything: the generation bump that turns this
    into a real restoration belongs to the lifecycle boundary that
    consumes this resolution, never to whatever produced it.
    """

    disposition: Literal["new_identity", "exact_reimport", "identity_conflict"]
    existing_raw_source_id: str | None
    record_key: str
    found_tombstone: bool


@dataclass(frozen=True)
class ImportedHandRecoveryReport:
    """What one startup sweep of the record store's write journal did.

    The three buckets mean genuinely different things and must not be
    collapsed into one list of ids:

    - ``completed`` -- an interrupted multi-record write was finished and
      its scratch directory removed. Nothing to do.
    - ``quarantined`` -- a scratch directory was structurally unusable, so
      it was moved aside for a human rather than deleted. **A quarantined
      id is not by itself evidence that any record is wrong**: a write
      that fully landed and was then killed during its final cleanup is
      indistinguishable on disk from a genuinely torn one, and lands here
      too. Anything surfaced from this bucket must say "someone should
      look", never "this record is corrupt".
    - ``failed`` -- the write could not be finished this time and was left
      exactly where it is, to be retried by the next sweep. A transient
      cause self-heals; a persistent one keeps reappearing here.

    Nothing yet escalates a repeatedly-``failed`` id or prunes the
    quarantine area. Callers must not write code that assumes either is
    handled.
    """

    completed: tuple[str, ...] = ()
    quarantined: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        """False when the sweep had nothing to report.

        The dataclass defaults would otherwise make every report truthy,
        so ``if report:`` would fire on every clean start.
        """
        return bool(self.completed or self.quarantined or self.failed)


class ImportedHandCascadeHandle(Protocol):
    """The write surface of one open cascade over a single record key.

    Everything staged through one handle commits together or not at all.
    That is the only thing this layer may assume about how the adapter
    achieves it, and the only thing it needs: a lifecycle transition has
    to publish a record's new state and the derived artifacts of the
    revision it supersedes as one unit, so that no reader can observe a
    record at revision 2 while an artifact still claims revision 1 is
    current.

    The handle lives exactly as long as the ``with`` block that yielded
    it. Holding one past that -- returning it from a helper, keeping it
    on ``self`` -- is a bug the adapter is entitled to raise on rather
    than silently accept, so a caller must stage everything before the
    block ends.

    Staging order carries no meaning. An artifact's identity may depend
    on the record staged beside it, and resolving that is the adapter's
    job at commit time, not the caller's to arrange by calling these in
    a particular sequence.
    """

    def stage_record(self, record: ImportedHandRecord) -> None:
        """Stage ``record`` as this cascade's new stored aggregate."""
        ...

    def stage_decisions(self, extraction: HandDecisionExtraction) -> None:
        """Stage one derived decision artifact in this cascade.

        Never removes the artifact it supersedes: issue #432 retains
        superseded artifacts for audit, and a superseded artifact stops
        being *served* because the record's lifecycle moved, not because
        anything deleted it.
        """
        ...


class ImportedHandRepository(Protocol):
    """Durable storage for imported-hand aggregates, keyed by record key."""

    def get(self, record_key: str) -> ImportedHandRecord:
        """Return the record stored under ``record_key``.

        A permanently deleted hand is still a record: its tombstone is
        returned like any other. Absence raises ``LookupError`` -- stated
        as the builtin so this layer need not import the adapter's own
        subclass to catch it.
        """
        ...

    def find(self, identity: StableHandIdentity) -> ImportedHandRecord | None:
        """Return the record for ``identity``, or None if there is none.

        Resolves through the same key derivation ``save`` used, so it
        finds a tombstone for a hand that was purged and can be
        re-imported. It must never be reimplemented as a scan comparing
        stored ``identity`` fields: a tombstone has none, so such a scan
        would silently miss exactly the case that matters.
        """
        ...

    def list_keys(self) -> list[str]:
        """Return every stored record key, sorted."""
        ...

    def save(self, record_key: str, record: ImportedHandRecord) -> ImportedHandRecord:
        """Durably publish ``record`` under ``record_key``.

        All-or-nothing: an interrupted save leaves no partially written
        record visible. It publishes the record and nothing else, so a
        transition that also has to move derived artifacts must not be
        assembled from this plus a second write -- see ``begin_cascade``.
        """
        ...

    def begin_cascade(
        self, record_key: str, *, operation: str
    ) -> AbstractContextManager[ImportedHandCascadeHandle]:
        """Open one durable unit over ``record_key``.

        Everything staged through the yielded handle becomes visible
        together when the block exits normally, and nothing does if it
        raises. This is what a lifecycle transition composes with: the
        record's new state and the derived artifacts of the revision it
        supersedes are one change, and publishing them as two would leave
        a window in which a record's active revision has no artifact
        matching it.

        ``operation`` names the transition for whoever later reads a
        write interrupted by a crash, so it must describe what was
        actually in flight. The adapter decides which labels it accepts
        and rejects an unknown one before anything is staged.

        Blocking, and not reentrant: neither this nor ``save`` may be
        called again from inside an open cascade.
        """
        ...

    def recover(self) -> ImportedHandRecoveryReport:
        """Finish or set aside writes interrupted by an earlier crash.

        Safe only when no other process can be writing to the same store.
        An implementation may therefore require the caller to have taken
        an exclusive interprocess lock *before constructing it*, and
        cannot check that the caller did -- unlike ``save``, which is
        self-contained and locks itself. Getting this wrong destroys
        another process's in-flight write rather than merely exposing
        your own, so a new call site must read the adapter's own contract
        instead of assuming it is guarded. Blocking: never call it from an
        event-loop thread.
        """
        ...
