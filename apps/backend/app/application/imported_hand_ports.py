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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.domain.imported_hands import ImportedHandRecord, StableHandIdentity


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
        record visible.
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
