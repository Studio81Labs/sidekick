"""File-backed store for player-local imported-hand records.

Layout, relative to the data directory::

    imported-hands/<record_key>/record.json
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

Every write goes through :class:`app.storage.cascade_journal.CascadeJournal`
rather than a bare atomic file write, even though a record write touches
one file today. A later lifecycle transition has to move a record and its
derived decision artifacts together, and only a cascade can make that
one durable unit; routing single-record writes through the same primitive
now means those calls join an existing cascade instead of inventing a
second, weaker write path beside it.

Locking. The journal holds its own lock for the whole of a ``save`` and
the whole of a ``recover``, and treats it as a leaf lock: any caller that
also needs the workspace's striped record locks must take those *first*
(``WorkspaceCoordinator.hold_imported_hands``), because taking a
workspace lock inside an open cascade inverts the established order and
deadlocks. ``recover`` additionally needs an exclusive interprocess hold
of the data lock -- the journal serialises against a live cascade only
within one process -- and both it and ``save`` block, so neither may be
called on the event-loop thread of the FastAPI process.
"""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path

from app.application.imported_hand_ports import ImportedHandRecoveryReport
from app.domain.imported_hands import ImportedHandRecord, StableHandIdentity
from app.storage.cascade_journal import CascadeJournal

IMPORTED_HANDS_DIRNAME = "imported-hands"
RECORD_FILENAME = "record.json"
RECORD_KEY_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ImportedHandNotFoundError(LookupError):
    """No record is stored under the requested key.

    Absence only. A permanently deleted hand is *not* absent -- its
    tombstone is a stored record and ``get`` returns it -- so callers
    must not read this as "deleted".
    """


def imported_hand_record_key(identity: StableHandIdentity) -> str:
    """Return the durable store key for a hand's stable identity.

    Canonicalised exactly the way ``imported_hand_state_sha256`` already
    canonicalises detected state (json.dumps with sorted keys, compact
    separators, no ASCII escaping, utf-8) so this codebase has one
    canonical form rather than two that drift apart.

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
    payload = json.dumps(
        identity.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


class FileImportedHandStore:
    """``ImportedHandRepository`` implemented over the local data volume."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.records_dir = (self.data_dir / IMPORTED_HANDS_DIRNAME).resolve()
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self._journal = CascadeJournal(self.records_dir)

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
        self._require_well_formed_key(record_key)
        if (
            record.identity is not None
            and imported_hand_record_key(record.identity) != record_key
        ):
            # A retained record filed under a key not derived from its own
            # identity is findable only by listing every record: find()
            # would derive the other key and report the hand as never
            # imported. A tombstone is exempt because it has no identity
            # left to check against - it keeps the key of the hand it
            # replaced, which is the point.
            raise ValueError(
                f"record key {record_key!r} was not derived from this "
                "record's own stable identity"
            )
        # model_dump_json revalidates the whole aggregate on the way out
        # (ImportedHandRecord.serialize_revalidated), so a record that no
        # longer holds together never reaches the disk.
        payload = record.model_dump_json(indent=2).encode("utf-8")
        with self._journal.begin(
            operation="save", record_keys=[record_key]
        ) as staging:
            staging.stage(record_key, RECORD_FILENAME, payload)
        return record

    def recover(self) -> ImportedHandRecoveryReport:
        """Finish or set aside writes interrupted by an earlier crash.

        Must run under an exclusive interprocess hold of the data lock
        and never on the event-loop thread; see the module docstring.
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

    @staticmethod
    def _require_well_formed_key(record_key: str) -> None:
        if RECORD_KEY_PATTERN.fullmatch(record_key) is None:
            raise ValueError(
                f"record key {record_key!r} must be a lowercase hex sha256 "
                "digest produced by imported_hand_record_key"
            )
