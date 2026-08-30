from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from unittest import mock

import pytest
from pydantic import ValidationError

from app.application.imported_hand_ports import ImportedHandRecoveryReport
from app.data_lock import DATA_LOCK_FILENAME
from app.domain.imported_hands import (
    CanonicalHandRevision,
    DeletionReceipt,
    DetectedImportedHand,
    ImportProvenance,
    ImportedHandLifecycle,
    ImportedHandRecord,
    ImportedHandState,
    ImportedSeat,
    RawHandHistory,
    SourceChronology,
    StableHandIdentity,
    UserCorrection,
    imported_hand_state_sha256,
)
from app.storage.cascade_journal import CascadeJournal, CascadeStaging
from app.storage.imported_hand_store import (
    FileImportedHandStore,
    ImportedHandNotFoundError,
    imported_hand_record_key,
)
from app.workspace import WorkspaceCoordinator

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
RAW_TEXT = "PokerStars Hand #123456789\n"


def sample_identity(*, hand_ordinal: int = 1) -> StableHandIdentity:
    """A distinct stable identity per ordinal.

    StableHandIdentity carries no ordinal of its own -- it is site plus
    source hand id -- so the ordinal varies the source hand id, which is
    what actually distinguishes two hands from one file.
    """
    return StableHandIdentity(
        site="pokerstars",
        source_hand_id=f"1234567{hand_ordinal:02d}",
    )


def chronology() -> SourceChronology:
    return SourceChronology(
        played_at=None,
        source_timezone=None,
        source_session_id="session-1",
        source_file_id="file-1",
        hand_ordinal=1,
    )


def raw_source(identity: StableHandIdentity) -> RawHandHistory:
    return RawHandHistory(
        raw_source_id="file-1",
        identity=identity,
        chronology=chronology(),
        provenance=ImportProvenance(
            import_id="import-file-1",
            imported_at=NOW,
            adapter_id="pokerstars",
            adapter_version="1.0.0",
            format_revision="pokerstars-text/v1",
            source_filename="HH20260830.txt",
        ),
        content_sha256=sha256(RAW_TEXT.encode()).hexdigest(),
        raw_text=RAW_TEXT,
    )


def hand_state(
    identity: StableHandIdentity,
    *,
    hero_player_id: str | None = None,
) -> ImportedHandState:
    return ImportedHandState(
        identity=identity,
        chronology=chronology(),
        game={
            "betting_limit": "no_limit",
            "table_size": 2,
            "blinds": {
                "small_blind": Decimal("0.50"),
                "big_blind": Decimal("1.00"),
                "ante": None,
            },
            "economics": {"kind": "unknown", "reason": "not supplied"},
        },
        button_seat=None,
        seats=[
            ImportedSeat(
                seat_number=1,
                player_id="hero",
                starting_stack=Decimal("100"),
                participation="dealt_in",
            ),
            ImportedSeat(
                seat_number=2,
                player_id="villain",
                starting_stack=Decimal("100"),
                participation="dealt_in",
            ),
        ],
        hero_player_id=hero_player_id,
        hero_cards=[],
        streets=[{"street": "preflop", "actions": []}],
    )


def detected(identity: StableHandIdentity) -> DetectedImportedHand:
    state = hand_state(identity)
    return DetectedImportedHand(
        detection_id="detection-1",
        raw_source_id="file-1",
        detector_id="pokerstars",
        detector_version="1.0.0",
        detected_at=NOW,
        state=state,
        field_evidence={
            "/hero_player_id": {
                "confidence": Decimal("0.40"),
                "evidence": [
                    {
                        "raw_source_id": "file-1",
                        "line_start": 1,
                        "excerpt": "PokerStars Hand #123456789",
                    }
                ],
                "warnings": ["Hero line was absent"],
            }
        },
        warnings=["Review hero identity"],
        content_sha256=imported_hand_state_sha256(state),
    )


def revision(identity: StableHandIdentity) -> CanonicalHandRevision:
    return CanonicalHandRevision(
        revision=1,
        detection_id="detection-1",
        approved_at=NOW,
        state=hand_state(identity, hero_player_id="hero"),
        corrections=[
            UserCorrection(
                field_pointer="/hero_player_id",
                detected_value=None,
                approved_value="hero",
                corrected_at=NOW,
                reason="Confirmed from the dealt-to line",
            )
        ],
    )


def pending_review_record(
    identity: StableHandIdentity | None = None,
) -> ImportedHandRecord:
    hand_identity = identity or sample_identity()
    return ImportedHandRecord(
        identity=hand_identity,
        raw_sources=[raw_source(hand_identity)],
        detections=[detected(hand_identity)],
        lifecycle=ImportedHandLifecycle(status="pending_review", changed_at=NOW),
    )


def approved_record(
    identity: StableHandIdentity | None = None,
) -> ImportedHandRecord:
    hand_identity = identity or sample_identity()
    return ImportedHandRecord(
        identity=hand_identity,
        raw_sources=[raw_source(hand_identity)],
        detections=[detected(hand_identity)],
        canonical_revisions=[revision(hand_identity)],
        lifecycle=ImportedHandLifecycle(
            status="active",
            active_canonical_revision=1,
            changed_at=NOW,
        ),
    )


def tombstone_record(*, generation: int) -> ImportedHandRecord:
    return ImportedHandRecord(
        identity=None,
        lifecycle=ImportedHandLifecycle(
            status="deleted",
            deletion_generation=generation,
            changed_at=NOW,
            reason="purged",
        ),
        deletion_receipt=DeletionReceipt(
            receipt_id=f"deletion-{generation}",
            generation=generation,
            deleted_at=NOW,
            tombstone_sha256="b" * 64,
        ),
    )


def test_record_key_is_stable_and_identity_derived() -> None:
    identity = sample_identity()
    assert imported_hand_record_key(identity) == imported_hand_record_key(identity)
    assert len(imported_hand_record_key(identity)) == 64
    other = sample_identity(hand_ordinal=2)
    assert imported_hand_record_key(identity) != imported_hand_record_key(other)


def test_record_key_uses_the_domains_own_canonical_json_form() -> None:
    """One canonical form, not two that can silently drift apart."""
    identity = sample_identity()

    expected = sha256(
        json.dumps(
            identity.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    assert imported_hand_record_key(identity) == expected


def test_save_and_get_round_trip(tmp_path: Path) -> None:
    store = FileImportedHandStore(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)

    store.save(key, record)

    assert store.get(key) == record
    assert store.list_keys() == [key]


def test_find_resolves_by_identity(tmp_path: Path) -> None:
    store = FileImportedHandStore(tmp_path)
    record = pending_review_record()
    store.save(imported_hand_record_key(record.identity), record)

    assert store.find(record.identity) == record
    assert store.find(sample_identity(hand_ordinal=99)) is None


def test_a_tombstone_is_retrievable_by_its_original_key(tmp_path: Path) -> None:
    """A purged record has identity=None, so only the store's own key can find it."""
    store = FileImportedHandStore(tmp_path)
    live = approved_record()
    key = imported_hand_record_key(live.identity)
    store.save(key, live)

    store.save(key, tombstone_record(generation=1))

    recovered = store.get(key)
    assert recovered.lifecycle.status == "deleted"
    assert recovered.identity is None
    assert recovered.deletion_receipt is not None
    assert store.list_keys() == [key]


def test_a_reimport_finds_the_tombstone_of_the_hand_it_replaces(
    tmp_path: Path,
) -> None:
    """The key is derived from the identity being re-imported, not from disk.

    This is the case a scan-and-compare implementation of find() would
    silently miss: the tombstone retains no identity to compare against,
    so only the derived key reaches it -- and reaching it is what lets a
    re-import see the previous deletion generation instead of resurrecting
    the hand as if it had never existed.
    """
    store = FileImportedHandStore(tmp_path)
    identity = sample_identity()
    key = imported_hand_record_key(identity)
    store.save(key, approved_record(identity))
    store.save(key, tombstone_record(generation=1))

    found = store.find(identity)

    assert found is not None
    assert found.identity is None
    assert found.lifecycle.deletion_generation == 1


def test_get_raises_for_an_unknown_key(tmp_path: Path) -> None:
    with pytest.raises(ImportedHandNotFoundError):
        FileImportedHandStore(tmp_path).get("0" * 64)


def test_a_partially_written_record_never_becomes_visible(tmp_path: Path) -> None:
    """save() must publish through the journal, so an interrupted save leaves nothing."""
    store = FileImportedHandStore(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)

    with mock.patch.object(CascadeStaging, "stage", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            store.save(key, record)

    assert store.list_keys() == []
    with pytest.raises(ImportedHandNotFoundError):
        store.get(key)


def test_an_interrupted_save_leaves_the_previous_record_intact(
    tmp_path: Path,
) -> None:
    """A failed rewrite must not be able to half-replace what was there."""
    store = FileImportedHandStore(tmp_path)
    first = pending_review_record()
    key = imported_hand_record_key(first.identity)
    store.save(key, first)

    with mock.patch.object(CascadeStaging, "stage", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            store.save(key, approved_record())

    assert store.get(key) == first


def test_stored_records_are_revalidated_on_load(tmp_path: Path) -> None:
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    # Corrupt the file behind the store's back.
    payload = json.loads((tmp_path / "imported-hands" / key / "record.json").read_text())
    payload["lifecycle"]["active_canonical_revision"] = 99
    (tmp_path / "imported-hands" / key / "record.json").write_text(json.dumps(payload))

    with pytest.raises(ValidationError):
        store.get(key)


def test_list_keys_ignores_the_journals_own_scratch_area(tmp_path: Path) -> None:
    """.cascade lives beside the records and is not one of them."""
    store = FileImportedHandStore(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)

    assert (tmp_path / "imported-hands" / ".cascade").is_dir()
    assert store.list_keys() == [key]


def test_save_refuses_a_key_that_is_not_a_derived_digest(tmp_path: Path) -> None:
    store = FileImportedHandStore(tmp_path)

    with pytest.raises(ValueError, match="lowercase hex sha256"):
        store.save("../escape", pending_review_record())

    assert not (tmp_path / "imported-hands" / ".cascade").exists()


def test_save_refuses_to_file_a_retained_record_under_a_foreign_key(
    tmp_path: Path,
) -> None:
    """Otherwise find() would report an imported hand as never imported."""
    store = FileImportedHandStore(tmp_path)
    foreign_key = imported_hand_record_key(sample_identity(hand_ordinal=2))

    with pytest.raises(ValueError, match="own stable identity"):
        store.save(foreign_key, pending_review_record())

    assert store.list_keys() == []


def test_save_accepts_a_tombstone_under_the_key_of_the_hand_it_replaces(
    tmp_path: Path,
) -> None:
    """The tombstone has no identity to derive from; that is the point."""
    store = FileImportedHandStore(tmp_path)
    identity = sample_identity()
    key = imported_hand_record_key(identity)
    store.save(key, approved_record(identity))

    store.save(key, tombstone_record(generation=3))

    assert store.get(key).lifecycle.deletion_generation == 3


def test_recover_reports_a_completed_cascade_without_calling_it_corrupt(
    tmp_path: Path,
) -> None:
    """A finished-on-replay write is 'completed', never 'quarantined'."""
    store = FileImportedHandStore(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    journal = CascadeJournal(store.records_dir)
    cascade_id = journal._prepare(operation="save", record_keys=[key])  # test seam
    staged = (
        store.records_dir
        / ".cascade"
        / cascade_id
        / "staged"
        / key
        / "content"
    )
    staged.mkdir(parents=True)
    (staged / "record.json").write_bytes(
        record.model_dump_json(indent=2).encode("utf-8")
    )
    journal._mark_ready(cascade_id)  # test seam

    report = store.recover()

    assert report == ImportedHandRecoveryReport(completed=(cascade_id,))
    assert store.get(key) == record


def test_recover_reports_nothing_when_there_is_nothing_to_recover(
    tmp_path: Path,
) -> None:
    report = FileImportedHandStore(tmp_path).recover()

    assert report == ImportedHandRecoveryReport()
    assert not report


def test_recover_keeps_the_three_outcomes_apart(tmp_path: Path) -> None:
    """completed, quarantined and failed mean different things.

    Collapsing them into one list of ids would let a boot report success
    over a directory nobody has looked at, or set aside one that only
    needed retrying.
    """
    store = FileImportedHandStore(tmp_path)
    journal = CascadeJournal(store.records_dir)
    cascade_root = store.records_dir / ".cascade"

    healthy_key = imported_hand_record_key(sample_identity())
    healthy = journal._prepare(operation="save", record_keys=[healthy_key])
    healthy_content = (
        cascade_root / healthy / "staged" / healthy_key / "content"
    )
    healthy_content.mkdir(parents=True)
    (healthy_content / "record.json").write_bytes(
        pending_review_record().model_dump_json(indent=2).encode("utf-8")
    )
    journal._mark_ready(healthy)

    corrupt = journal._prepare(operation="save", record_keys=[healthy_key])
    journal._mark_ready(corrupt)
    (cascade_root / corrupt / "staged").rmdir()

    report = store.recover()

    assert report.completed == (healthy,)
    assert report.quarantined == (corrupt,)
    assert report.failed == ()
    assert (cascade_root / "corrupt" / corrupt).is_dir()
    assert store.list_keys() == [healthy_key]


def test_the_repository_protocol_is_satisfied_structurally(tmp_path: Path) -> None:
    from app.application.imported_hand_ports import ImportedHandRepository

    repository: ImportedHandRepository = FileImportedHandStore(tmp_path)

    assert repository.list_keys() == []


def shared_data_lock_is_blocked(data_dir: Path) -> bool:
    """True when something already holds the data lock exclusively.

    flock() locks belong to the open file description, so a second open()
    of the same file conflicts even inside the process holding it -- which
    is what makes the exclusivity of WorkspaceCoordinator.open observable
    from a call it makes.
    """
    descriptor = os.open(data_dir / DATA_LOCK_FILENAME, os.O_RDONLY | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)


def test_workspace_recovers_records_under_an_exclusive_interprocess_lock(
    tmp_path: Path,
) -> None:
    """A shared hold would let another process sweep away a live cascade.

    The journal only serialises begin() against recover() inside one
    process; across processes it enforces nothing, so the sweep has to
    exclude every other holder of the data lock while it runs.
    """
    observed: list[bool] = []
    real_recover = FileImportedHandStore.recover

    def recording_recover(self: FileImportedHandStore) -> ImportedHandRecoveryReport:
        observed.append(shared_data_lock_is_blocked(tmp_path))
        return real_recover(self)

    with mock.patch.object(FileImportedHandStore, "recover", recording_recover):
        workspace = WorkspaceCoordinator.open(tmp_path)

    assert observed == [True]
    assert workspace.imported_hand_recovery == ImportedHandRecoveryReport()
    # The hold is released once open() returns, so ordinary shared use
    # of the data lock still works afterwards.
    assert not shared_data_lock_is_blocked(tmp_path)


def test_workspace_still_recovers_interrupted_jobs_under_the_exclusive_hold(
    tmp_path: Path,
) -> None:
    """The stronger hold must not drop the recovery that already ran there."""
    from app.storage.file_job_store import FileJobStore
    from app.workspace import INTERRUPTED_PARSER_ERROR

    job = FileJobStore(tmp_path).create_job(
        original_filename="parsing.png",
        image_bytes=b"image",
        parser_provider="mock",
    )

    workspace = WorkspaceCoordinator.open(tmp_path)

    recovered = workspace.jobs.get(job.id)
    assert recovered.status == "error"
    assert recovered.error == INTERRUPTED_PARSER_ERROR


def test_record_locks_are_held_before_the_journal_lock(tmp_path: Path) -> None:
    """Record stripes outside, journal inside -- never the reverse.

    The journal's lock is held for the whole of a save and is a leaf lock.
    A workspace stripe taken from inside an open cascade would invert the
    ordering workspace.py establishes and deadlock two callers whose
    record sets overlap.
    """
    workspace = WorkspaceCoordinator.open(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    stripe_held_at_begin: list[bool] = []
    real_begin = CascadeJournal.begin

    @contextmanager
    def observing_begin(
        journal: CascadeJournal,
        *,
        operation: str,
        record_keys: Sequence[str],
    ) -> Iterator[CascadeStaging]:
        stripe_held_at_begin.append(
            all(
                workspace.imported_hand_lock_for(record_key).locked()
                for record_key in record_keys
            )
        )
        with real_begin(
            journal, operation=operation, record_keys=record_keys
        ) as staging:
            yield staging

    with mock.patch.object(CascadeJournal, "begin", observing_begin):
        with workspace.hold_imported_hands([key]):
            workspace.imported_hands.save(key, record)

    assert stripe_held_at_begin == [True]
    assert not workspace.imported_hand_lock_for(key).locked()
    assert workspace.imported_hands.get(key) == record


def test_hold_imported_hands_enters_stripes_in_sorted_index_order(
    tmp_path: Path,
) -> None:
    """Two callers naming overlapping sets must agree on acquisition order."""
    entered: list[int] = []

    class RecordingLock:
        def __init__(self, index: int) -> None:
            self.index = index

        def __enter__(self) -> "RecordingLock":
            entered.append(self.index)
            return self

        def __exit__(self, *exception: object) -> None:
            return None

    stripes = iter(range(4))

    workspace = WorkspaceCoordinator.open(
        tmp_path,
        imported_hand_lock_stripes=4,
        imported_hand_lock_factory=lambda: RecordingLock(next(stripes)),
    )
    keys_by_index: dict[int, str] = {}
    for ordinal in range(1, 60):
        key = imported_hand_record_key(sample_identity(hand_ordinal=ordinal))
        keys_by_index.setdefault(workspace.imported_hand_lock_index(key), key)
        if len(keys_by_index) == 4:
            break
    assert len(keys_by_index) == 4, "expected four distinct stripes to be reachable"

    with workspace.hold_imported_hands(
        [keys_by_index[3], keys_by_index[0], keys_by_index[2], keys_by_index[1]]
    ):
        pass

    assert entered == [0, 1, 2, 3]


def test_coordinator_rejects_an_empty_imported_hand_lock_pool(tmp_path: Path) -> None:
    workspace = WorkspaceCoordinator.open(tmp_path)

    with pytest.raises(ValueError, match="imported_hand_lock_stripes must be positive"):
        WorkspaceCoordinator(
            jobs=workspace.jobs,
            benchmarks=workspace.benchmarks,
            imported_hands=workspace.imported_hands,
            data_lock=workspace.data_lock,
            imported_hand_lock_stripes=0,
        )
