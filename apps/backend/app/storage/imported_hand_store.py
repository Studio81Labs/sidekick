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
named for the exact ``(canonical_revision, deletion_generation)`` pair it was
extracted from, ``r<revision>-g<generation>.json``, so whether one is stale is
decidable **from the filename alone**: it is active only while both numbers
still match the record's current ``lifecycle``, and nothing here may open a
file just to find that out. A superseded artifact is never deleted here --
issue #432 requires it stay retained for audit -- only Task 6's purge may
remove one. A ``not_extractable`` verdict binds no canonical revision at all,
so it is filed under the reserved ``NO_CANONICAL_REVISION`` sentinel instead;
it is still generation-stamped, which is what lets a caller tell "still not
extractable at generation 2" apart from a stale verdict computed at
generation 1, but a sentinel revision can never equal a record's real active
revision, so a rejection can never be mistaken for an active canonical
artifact.

Every write goes through :class:`app.storage.cascade_journal.CascadeJournal`
rather than a bare atomic file write, even though a record write touches
one file today. A later lifecycle transition has to move a record and its
derived decision artifacts together, and only a cascade can make that
one durable unit; routing single-record writes through the same primitive
now means those calls join an existing cascade instead of inventing a
second, weaker write path beside it.

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
``recover`` cannot, because the hold it needs is wider than the call --
it has to span store construction and the sweep together, so that no
cascade can be opened in the window between them -- and an exclusive
self-acquire nested inside the caller's own exclusive hold would block on
that hold, deadlocking on some platforms. So ``recover`` requires its
caller to hold the lock exclusively and cannot check that it did. This is
the more dangerous direction to get wrong: a sweep run without the hold
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
own, so the journal stays innermost. ``save``, ``save_decisions``, and
``recover`` all block, so none of them may be called on the event-loop
thread of the FastAPI process.
"""

from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path

from app.application.imported_hand_ports import (
    ImportedHandRecoveryReport,
    ImportedHandRepository,
    ReimportResolution,
)
from app.data_lock import (
    DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
    InterprocessDataLock,
)
from app.domain.imported_hands import (
    DetectedImportedHand,
    HandDecisionExtraction,
    ImportedHandRecord,
    RawHandHistory,
    StableHandIdentity,
    classify_reimport,
    imported_hand_canonical_json,
)
from app.storage.cascade_journal import CascadeJournal

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
        write_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
    ) -> None:
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
                operation="save", record_keys=[record_key]
            ) as staging:
                staging.stage(record_key, RECORD_FILENAME, payload)
        return record

    def save_decisions(self, record_key: str, extraction: HandDecisionExtraction) -> None:
        """Durably persist one decision-extraction artifact for ``record_key``.

        Keyed by the extraction's own ``canonical_revision`` and
        ``deletion_generation`` -- see the module docstring for the exact
        filename and why it, not the record's current lifecycle, is what
        drives it: the filename must describe what is actually inside the
        file, or "decidable from the filename alone" would not be
        trustworthy. A ``not_extractable`` extraction has no canonical
        revision to describe, so it is filed under the reserved
        ``NO_CANONICAL_REVISION`` sentinel instead, keyed by generation only.

        Never removes a sibling artifact: a superseded revision's file is
        left exactly where it is, retained for audit per issue #432. Only
        Task 6's purge may remove one.

        Goes through the same journal ``save`` does, and takes the same
        shared interprocess hold the same way and for the same reason --
        see the module docstring -- so this composes into the same kind of
        cascade a future lifecycle transition will open to move a record
        and its derived artifacts together. Opened under the journal's own
        ``"save"`` operation label, not a bespoke one: ``CascadeIntent``
        reserves that label for exactly this -- the record store's own
        plain write, undescribed by any lifecycle verb -- and this is one.
        """
        self._require_well_formed_key(record_key)
        if (
            extraction.identity is not None
            and imported_hand_record_key(extraction.identity) != record_key
        ):
            # Mirrors save()'s own guard, and for the same reason: an
            # extraction filed under a key not derived from its own
            # identity would need a store-wide scan to find. A
            # not_extractable extraction for a hand with no stable
            # identity is exempt, because there is no identity left to
            # check against -- it is filed under the key of the record it
            # was extracted from, which is the point.
            raise ValueError(
                f"record key {record_key!r} was not derived from this "
                "extraction's own stable identity"
            )
        revision = (
            NO_CANONICAL_REVISION
            if extraction.canonical_revision is None
            else extraction.canonical_revision
        )
        relative_path = (
            f"{DECISIONS_DIRNAME}/r{revision}-g{extraction.deletion_generation}.json"
        )
        payload = extraction.model_dump_json(indent=2).encode("utf-8")
        with self._data_lock.hold(
            exclusive=False,
            timeout_seconds=self._write_lock_timeout_seconds,
        ):
            with self._journal.begin(
                operation="save", record_keys=[record_key]
            ) as staging:
                staging.stage(record_key, relative_path, payload)

    def get_decisions(
        self, record_key: str, *, revision: int, generation: int
    ) -> HandDecisionExtraction | None:
        """Return the artifact stored at exactly this revision and generation.

        ``None`` means only that nothing was ever staged there -- it says
        nothing about whether ``revision``/``generation`` are current for
        ``record_key``. A caller that wants the current artifact, and only
        the current one, wants ``active_decisions`` instead.
        """
        path = self._decision_artifact_path(record_key, revision, generation)
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
        """
        try:
            record = self.get(record_key)
        except ImportedHandNotFoundError:
            return None
        if not record.lifecycle.learning_eligible:
            return None
        active_revision = record.lifecycle.active_canonical_revision
        assert active_revision is not None  # guaranteed by learning_eligible
        return self.get_decisions(
            record_key,
            revision=active_revision,
            generation=record.lifecycle.deletion_generation,
        )

    def list_decision_artifacts(self, record_key: str) -> list[tuple[int, int]]:
        """Return every retained ``(revision, generation)`` pair, sorted.

        Filename-only, like every staleness decision this store makes: no
        artifact is opened or parsed to build this list. Includes
        artifacts that are no longer active, retained for audit per issue
        #432, and the ``NO_CANONICAL_REVISION`` slot a rejected extraction
        is filed under.
        """
        try:
            entries = list(self._decisions_dir(record_key).iterdir())
        except (FileNotFoundError, ImportedHandNotFoundError):
            return []
        artifacts: list[tuple[int, int]] = []
        for path in entries:
            match = DECISION_ARTIFACT_PATTERN.fullmatch(path.name)
            if match is not None and path.is_file():
                artifacts.append(
                    (int(match.group("revision")), int(match.group("generation")))
                )
        return sorted(artifacts)

    def recover(self) -> ImportedHandRecoveryReport:
        """Finish or set aside writes interrupted by an earlier crash.

        **The caller must already hold the data lock exclusively**, and
        must have held it since before this store was constructed. Unlike
        ``save``, this does not and cannot take the hold itself: the hold
        has to be wider than this call, and an exclusive self-acquire
        inside the caller's own exclusive hold would block on it. Nothing
        here verifies the caller complied -- see the module docstring for
        why the two methods differ, and for what a new caller owes.

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
