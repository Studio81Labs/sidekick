from __future__ import annotations

import fcntl
import inspect
import json
import os
import threading
import time
from contextlib import contextmanager
from threading import Lock
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from unittest import mock

import pytest
from pydantic import ValidationError

from app.application.imported_hand_ports import (
    ImportedHandRecoveryReport,
    ImportedHandRepository,
    ReimportResolution,
)
from app.data_lock import (
    DATA_LOCK_FILENAME,
    DataLockTimeoutError,
    InterprocessDataLock,
)
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
    imported_hand_canonical_json,
    imported_hand_state_sha256,
)
from app.storage.cascade_journal import CascadeJournal, CascadeStaging
from app.storage.imported_hand_store import (
    FileImportedHandStore,
    ImportedHandNotFoundError,
    imported_hand_record_key,
    resolve_reimport,
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


def conflicting_raw_source(identity: StableHandIdentity) -> RawHandHistory:
    """Same identity as ``raw_source``, but bytes that do not match it.

    ``classify_reimport`` treats a same-identity candidate whose content
    matches no existing raw source as a conflict to be reported, never as
    grounds to overwrite anything silently.
    """
    text = RAW_TEXT + "Table 'x' 2-max Seat #1 is the button\n"
    return RawHandHistory(
        raw_source_id="file-2",
        identity=identity,
        chronology=SourceChronology(
            played_at=None,
            source_timezone=None,
            source_session_id="session-1",
            source_file_id="file-2",
            hand_ordinal=1,
        ),
        provenance=ImportProvenance(
            import_id="import-file-2",
            imported_at=NOW,
            adapter_id="pokerstars",
            adapter_version="1.0.0",
            format_revision="pokerstars-text/v1",
            source_filename="HH20260830-conflict.txt",
        ),
        content_sha256=sha256(text.encode()).hexdigest(),
        raw_text=text,
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
    """One canonical form, not a second copy of the formula.

    Two assertions, because either alone is satisfiable by a divergent
    copy: the first pins the record key to imported_hand_canonical_json's
    actual output, the second pins the domain's own state digest to that
    same helper. Changing the serialization now changes both together or
    fails here.
    """
    identity = sample_identity()

    assert (
        imported_hand_record_key(identity)
        == sha256(
            imported_hand_canonical_json(identity.model_dump(mode="json"))
        ).hexdigest()
    )

    canonicalised: list[bytes] = []

    def recording(payload: object) -> bytes:
        result = imported_hand_canonical_json(payload)
        canonicalised.append(result)
        return result

    with mock.patch(
        "app.domain.imported_hands.models.imported_hand_canonical_json",
        recording,
    ):
        imported_hand_state_sha256(hand_state(identity))

    assert len(canonicalised) == 1, (
        "imported_hand_state_sha256 no longer routes through the shared "
        "canonical form"
    )


def _signature_without_self(function: object) -> inspect.Signature:
    signature = inspect.signature(function)
    return signature.replace(parameters=list(signature.parameters.values())[1:])


def _assert_accepts_the_declared_call_shape(
    name: str,
    declared_member: object,
    implementation: object,
) -> None:
    """Assert the implementation accepts every call the Protocol permits.

    Deliberately not Signature equality, which is stricter than structural
    conformance in two ways that both produce false positives: it rejects
    an extra *optional* parameter, which a Protocol permits and which a
    later task may well want to add; and because annotations are strings
    under `from __future__ import annotations`, it compares `str` against
    `'str'` for any module that omits that import, so the test would
    silently depend on both files keeping it.

    What conformance actually requires is that the declared call goes
    through, and that a caller may still pass the declared parameters by
    name. Both are checked; annotations are not.
    """
    declared = list(_signature_without_self(declared_member).parameters.values())
    actual = _signature_without_self(implementation)

    positional: list[object] = []
    keyword: dict[str, object] = {}
    for parameter in declared:
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            keyword[parameter.name] = _ANY_ARGUMENT
        else:
            positional.append(_ANY_ARGUMENT)
    try:
        actual.bind(*positional, **keyword)
    except TypeError as exc:
        raise AssertionError(
            f"{name} does not accept the call shape the Protocol declares: {exc}"
        ) from exc

    for parameter in declared:
        implemented = actual.parameters.get(parameter.name)
        assert implemented is not None, (
            f"{name} has no parameter named {parameter.name!r}; a caller "
            "typed against the Protocol may pass it by keyword"
        )
        assert implemented.kind is parameter.kind, (
            f"{name}'s {parameter.name!r} is {implemented.kind}, but the "
            f"Protocol declares {parameter.kind}"
        )


_ANY_ARGUMENT = object()


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


def test_resolve_reimport_reports_new_identity_when_nothing_is_stored(
    tmp_path: Path,
) -> None:
    """No record at all is the ordinary case: classify against no sources."""
    store = FileImportedHandStore(tmp_path)
    identity = sample_identity()

    resolution = resolve_reimport(store, identity, raw_source(identity))

    assert isinstance(resolution, ReimportResolution)
    assert resolution.record_key == imported_hand_record_key(identity)
    assert resolution.disposition == "new_identity"
    assert resolution.existing_raw_source_id is None
    assert resolution.found_tombstone is False


def test_resolve_reimport_reports_exact_reimport_for_byte_identical_content(
    tmp_path: Path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    identity = sample_identity()
    key = imported_hand_record_key(identity)
    store.save(key, pending_review_record(identity))

    resolution = resolve_reimport(store, identity, raw_source(identity))

    assert resolution.record_key == key
    assert resolution.disposition == "exact_reimport"
    assert resolution.existing_raw_source_id == "file-1"
    assert resolution.found_tombstone is False


def test_resolve_reimport_reports_identity_conflict_for_differing_content(
    tmp_path: Path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    identity = sample_identity()
    key = imported_hand_record_key(identity)
    store.save(key, pending_review_record(identity))

    resolution = resolve_reimport(store, identity, conflicting_raw_source(identity))

    assert resolution.record_key == key
    assert resolution.disposition == "identity_conflict"
    assert resolution.existing_raw_source_id is None
    assert resolution.found_tombstone is False


def test_reimport_onto_a_tombstone_is_reported_not_resurrected(
    tmp_path: Path,
) -> None:
    """A purged record has no identity or audit trail left to classify against.

    resolve_reimport must still surface the tombstone it found rather than
    silently treating this as an ordinary new import: found_tombstone is
    what lets a caller tell "never imported" apart from "was imported, then
    deleted". Bumping the deletion generation to actually restore it is
    Task 6's lifecycle boundary, not this call, so the stored tombstone
    must come back byte-for-byte unchanged -- not merely "no exception".
    """
    store = FileImportedHandStore(tmp_path)
    identity = sample_identity()
    key = imported_hand_record_key(identity)
    store.save(key, tombstone_record(generation=1))
    before = store.get(key)

    resolution = resolve_reimport(store, identity, raw_source(identity))

    assert resolution.record_key == key
    assert resolution.found_tombstone is True
    assert resolution.disposition == "new_identity"
    assert store.get(key) == before
    assert store.get(key).lifecycle.status == "deleted"


def test_resolve_reimport_rejects_a_raw_source_whose_identity_does_not_match(
    tmp_path: Path,
) -> None:
    """The key is derived from ``identity``; a mismatched raw would silently
    stop matching whatever is already stored under that key instead of
    raising, which is worse than either disposition it might paper over.
    """
    store = FileImportedHandStore(tmp_path)
    identity = sample_identity()
    key = imported_hand_record_key(identity)
    store.save(key, pending_review_record(identity))
    mismatched = raw_source(sample_identity(hand_ordinal=2))

    with pytest.raises(ValueError, match="identity"):
        resolve_reimport(store, identity, mismatched)

    assert store.get(key) == pending_review_record(identity)


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


def test_list_keys_returns_every_record_sorted_and_nothing_else(
    tmp_path: Path,
) -> None:
    """Sorted, and filtered: .cascade and stray directories are not records."""
    store = FileImportedHandStore(tmp_path)
    keys: list[str] = []
    for ordinal in range(1, 6):
        identity = sample_identity(hand_ordinal=ordinal)
        key = imported_hand_record_key(identity)
        store.save(key, pending_review_record(identity))
        keys.append(key)
    assert len(set(keys)) == 5
    assert keys != sorted(keys), "fixture must not already be in sorted order"

    # Neighbours that are not records: the journal's own scratch area, a
    # directory whose name is not a digest, and a digest-shaped directory
    # with no record.json in it.
    assert (tmp_path / "imported-hands" / ".cascade").is_dir()
    (tmp_path / "imported-hands" / "not-a-record-key").mkdir()
    (tmp_path / "imported-hands" / ("f" * 64)).mkdir()

    assert store.list_keys() == sorted(keys)


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

    Collapsing them would let a boot report success over a directory
    nobody has looked at, set aside one that only needed retrying, or --
    the case this covers -- drop the one bucket that says "retry me next
    boot" and lose a half-applied write silently. All three are produced
    in a single sweep, and each is checked physically as well as in the
    report: quarantined moves aside, failed stays exactly where it is.
    """
    store = FileImportedHandStore(tmp_path)
    journal = CascadeJournal(store.records_dir)
    cascade_root = store.records_dir / ".cascade"

    def stage_ready_cascade(record_key: str, record: ImportedHandRecord) -> str:
        cascade_id = journal._prepare(  # test seam
            operation="save", record_keys=[record_key]
        )
        content = cascade_root / cascade_id / "staged" / record_key / "content"
        content.mkdir(parents=True)
        (content / "record.json").write_bytes(
            record.model_dump_json(indent=2).encode("utf-8")
        )
        journal._mark_ready(cascade_id)  # test seam
        return cascade_id

    healthy_key = imported_hand_record_key(sample_identity())
    healthy = stage_ready_cascade(healthy_key, pending_review_record())

    # Structurally unusable: ready, but with no staged/ to replay from.
    corrupt = journal._prepare(operation="save", record_keys=[healthy_key])
    journal._mark_ready(corrupt)
    (cascade_root / corrupt / "staged").rmdir()

    # Perfectly formed, but commit cannot land it: a regular file sits
    # where the record's own directory has to be created, so mkdir raises.
    # Nothing about the cascade is wrong, so it must be retried, not moved.
    failing_identity = sample_identity(hand_ordinal=7)
    failing_key = imported_hand_record_key(failing_identity)
    failing = stage_ready_cascade(
        failing_key, pending_review_record(failing_identity)
    )
    (store.records_dir / failing_key).write_bytes(b"not a directory")

    report = store.recover()

    assert report.completed == (healthy,)
    assert report.quarantined == (corrupt,)
    assert report.failed == (failing,)

    # Quarantine moved the corrupt one aside, with its evidence.
    assert sorted(path.name for path in (cascade_root / "corrupt").iterdir()) == [
        corrupt
    ]
    # The failing one was left untouched, staged tree and all, so the next
    # sweep can retry it once the cause is cleared.
    assert (cascade_root / failing / "ready").is_file()
    assert (
        cascade_root / failing / "staged" / failing_key / "content" / "record.json"
    ).is_file()
    assert store.list_keys() == [healthy_key]


def test_a_failed_cascade_is_retried_and_completed_by_the_next_sweep(
    tmp_path: Path,
) -> None:
    """That is the whole point of `failed`: it is not terminal."""
    store = FileImportedHandStore(tmp_path)
    journal = CascadeJournal(store.records_dir)
    identity = sample_identity()
    record = pending_review_record(identity)
    key = imported_hand_record_key(identity)
    cascade_id = journal._prepare(operation="save", record_keys=[key])  # test seam
    content = store.records_dir / ".cascade" / cascade_id / "staged" / key / "content"
    content.mkdir(parents=True)
    (content / "record.json").write_bytes(
        record.model_dump_json(indent=2).encode("utf-8")
    )
    journal._mark_ready(cascade_id)  # test seam
    blocker = store.records_dir / key
    blocker.write_bytes(b"not a directory")

    assert store.recover() == ImportedHandRecoveryReport(failed=(cascade_id,))

    blocker.unlink()

    assert store.recover() == ImportedHandRecoveryReport(completed=(cascade_id,))
    assert store.get(key) == record


def test_the_file_store_satisfies_every_call_the_repository_protocol_declares() -> None:
    """A bare annotation checks nothing: no mypy or ruff runs in this repo.

    So check conformance directly - every declared member exists, and each
    accepts the call the Protocol declares - without over-constraining it
    into rejecting implementations the Protocol allows.
    """
    declared = sorted(
        name for name in vars(ImportedHandRepository) if not name.startswith("_")
    )
    assert declared == ["find", "get", "list_keys", "recover", "save"]

    for name in declared:
        implementation = getattr(FileImportedHandStore, name, None)
        assert implementation is not None, f"{name} is not implemented"
        _assert_accepts_the_declared_call_shape(
            name,
            getattr(ImportedHandRepository, name),
            implementation,
        )


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


def exclusive_data_lock_is_blocked(data_dir: Path) -> bool:
    """True when something holds the data lock at all, shared or exclusive."""
    descriptor = os.open(data_dir / DATA_LOCK_FILENAME, os.O_RDONLY | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
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


def test_workspace_still_recovers_interrupted_jobs(tmp_path: Path) -> None:
    """Narrowing the exclusive hold must not drop the recovery beside it."""
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


def test_job_recovery_runs_under_the_shared_hold_not_the_exclusive_one(
    tmp_path: Path,
) -> None:
    """Two halves, and both need pinning.

    recover_interrupted_jobs() reads and validates every job record on
    disk. That scan is the dominant cost of startup and must not be what
    other processes are blocked behind, so it must not be inside the
    exclusive hold. But it must still be inside the *shared* hold it has
    always had - asserting only "not exclusive" is equally satisfied by
    "under no lock at all", which is a different regression entirely.

    So both probes run: an exclusive acquire must fail (something holds
    the lock) while a shared acquire must succeed (that something is not
    holding it exclusively). Together those mean exactly "shared".
    """
    from app.storage.file_job_store import FileJobStore

    FileJobStore(tmp_path).create_job(
        original_filename="parsing.png",
        image_bytes=b"image",
        parser_provider="mock",
    )
    observed: list[tuple[bool, bool]] = []
    real_recover_jobs = WorkspaceCoordinator.recover_interrupted_jobs

    def recording_recover_jobs(self: WorkspaceCoordinator) -> None:
        observed.append(
            (
                exclusive_data_lock_is_blocked(tmp_path),
                shared_data_lock_is_blocked(tmp_path),
            )
        )
        real_recover_jobs(self)

    with mock.patch.object(
        WorkspaceCoordinator, "recover_interrupted_jobs", recording_recover_jobs
    ):
        WorkspaceCoordinator.open(tmp_path)

    assert observed == [(True, False)], (
        "job recovery must run under a shared hold: held, but not exclusively"
    )


def test_startup_gives_up_loudly_rather_than_hanging_on_its_exclusive_acquire(
    tmp_path: Path,
) -> None:
    """flock has no writer preference, so the wait must be bounded.

    open() runs at import time, before uvicorn binds and before
    /api/health can answer. An unbounded exclusive acquire there means a
    container that hangs silently and never turns healthy, so a deploy
    wedges instead of failing. The error must name the lock file, and the
    sweep must not be skipped to get past it.
    """
    data_lock = InterprocessDataLock(tmp_path)
    descriptor = data_lock.acquire(exclusive=True)
    try:
        with pytest.raises(DataLockTimeoutError) as failure:
            WorkspaceCoordinator.open(tmp_path, recovery_lock_timeout_seconds=0)
    finally:
        data_lock.release(descriptor)

    message = str(failure.value)
    assert DATA_LOCK_FILENAME in message
    assert "exclusive" in message


def test_startup_gives_up_loudly_rather_than_hanging_on_its_shared_acquire(
    tmp_path: Path,
) -> None:
    """open() makes two separate acquires, so both need their own bound.

    The exclusive one is released before the shared one is taken, so an
    exclusive holder arriving in that window blocks the shared acquire on
    its own - a backup export building a large archive, or another
    instance's sweep. A test that only holds the lock up front never
    reaches this acquire, because the first one fails first, so this one
    lets the exclusive acquire succeed and injects the blocker into the
    window between them.
    """
    blocker = InterprocessDataLock(tmp_path)
    real_acquire = InterprocessDataLock.acquire
    acquires: list[bool] = []
    blocking_descriptor: list[int] = []

    def blocking_acquire(
        lock: InterprocessDataLock,
        *,
        exclusive: bool,
        timeout_seconds: int | None = None,
    ) -> int:
        acquires.append(exclusive)
        if len(acquires) == 2:
            assert not exclusive, "the second startup acquire should be shared"
            # Hold it exclusively from "another process" for the duration.
            blocking_descriptor.append(real_acquire(blocker, exclusive=True))
        return real_acquire(
            lock, exclusive=exclusive, timeout_seconds=timeout_seconds
        )

    with mock.patch.object(InterprocessDataLock, "acquire", blocking_acquire):
        try:
            with pytest.raises(DataLockTimeoutError) as failure:
                WorkspaceCoordinator.open(tmp_path, recovery_lock_timeout_seconds=0)
        finally:
            for descriptor in blocking_descriptor:
                InterprocessDataLock.release(descriptor)

    assert acquires == [True, False], "the sweep's own acquire must have succeeded"
    message = str(failure.value)
    assert DATA_LOCK_FILENAME in message
    assert "shared" in message


def test_startup_waits_for_a_lock_that_is_released_in_time(tmp_path: Path) -> None:
    """The bound is a deadline, not a single attempt."""
    data_lock = InterprocessDataLock(tmp_path)
    descriptor = data_lock.acquire(exclusive=True)
    released = threading.Event()

    def release_shortly() -> None:
        time.sleep(0.2)
        data_lock.release(descriptor)
        released.set()

    releaser = threading.Thread(target=release_shortly)
    releaser.start()
    try:
        workspace = WorkspaceCoordinator.open(tmp_path, recovery_lock_timeout_seconds=10)
    finally:
        releaser.join()

    assert released.is_set(), "open() returned before the lock was released"
    assert workspace.imported_hand_recovery == ImportedHandRecoveryReport()


def test_save_holds_the_data_lock_shared_for_its_whole_cascade(
    tmp_path: Path,
) -> None:
    """Exclusivity for the sweep is meaningless unless writers lock too.

    /mcp is exempt from the middleware's data lock entirely and already
    carries mutating tools; a background thread or a non-mutating GET is
    exempt as well. A cascade opened with no interprocess lock is
    invisible to a recover() sweeping in another process, which would
    delete its staged files mid-flight. So save() takes the shared hold
    itself instead of inheriting one by accident.
    """
    store = FileImportedHandStore(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    held_during_cascade: list[bool] = []
    real_stage = CascadeStaging.stage

    def observing_stage(
        staging: CascadeStaging,
        record_key: str,
        relative_path: str,
        payload: bytes,
    ) -> None:
        held_during_cascade.append(exclusive_data_lock_is_blocked(tmp_path))
        real_stage(staging, record_key, relative_path, payload)

    with mock.patch.object(CascadeStaging, "stage", observing_stage):
        store.save(key, record)

    assert held_during_cascade == [True]
    # And the hold is released again once the write is done.
    assert not exclusive_data_lock_is_blocked(tmp_path)


def test_a_save_composes_with_a_shared_hold_the_caller_already_has(
    tmp_path: Path,
) -> None:
    """A mutating request already holds the lock shared; shared holds compose."""
    store = FileImportedHandStore(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)

    with InterprocessDataLock(tmp_path).hold(exclusive=False):
        store.save(key, record)

    assert store.get(key) == record


def test_save_publishes_through_the_journal(tmp_path: Path) -> None:
    """Named for what it pins: every record write opens a cascade.

    It does not pin the caller-side half of the lock ordering -- that
    obligation belongs to callers, and there are none yet. See
    test_save_acquires_no_workspace_lock_of_its_own for the half the
    store itself can violate.
    """
    store = FileImportedHandStore(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    opened: list[tuple[str, list[str]]] = []
    real_begin = CascadeJournal.begin

    @contextmanager
    def observing_begin(
        journal: CascadeJournal,
        *,
        operation: str,
        record_keys: Sequence[str],
    ) -> Iterator[CascadeStaging]:
        opened.append((operation, list(record_keys)))
        with real_begin(
            journal, operation=operation, record_keys=record_keys
        ) as staging:
            yield staging

    with mock.patch.object(CascadeJournal, "begin", observing_begin):
        store.save(key, record)

    assert opened == [("save", [key])]
    assert store.get(key) == record


def test_save_acquires_no_workspace_lock_of_its_own(tmp_path: Path) -> None:
    """The journal must stay the innermost lock.

    workspace.py orders benchmark_corpus_lock -> job_locks -> history_lock
    above the journal, and the journal's own lock is held for the whole of
    a save. If the store reached back for a workspace stripe from inside
    its open cascade, that order would invert into an ABBA deadlock
    against any caller holding the stripe first. So the store must take no
    workspace lock at all -- which is the half of the rule code here can
    break, and the half a test can therefore pin.

    Both arrangements are exercised: a save with no stripe held, and a
    save inside the stripe a caller is expected to hold, which must also
    not deadlock.
    """
    entered: list[int] = []

    class RecordingLock:
        def __init__(self, index: int) -> None:
            self.index = index
            self._lock = Lock()

        def locked(self) -> bool:
            return self._lock.locked()

        def __enter__(self) -> "RecordingLock":
            entered.append(self.index)
            self._lock.acquire()
            return self

        def __exit__(self, *exception: object) -> None:
            self._lock.release()

    stripes = iter(range(4))
    workspace = WorkspaceCoordinator.open(
        tmp_path,
        imported_hand_lock_stripes=4,
        imported_hand_lock_factory=lambda: RecordingLock(next(stripes)),
    )
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)

    workspace.imported_hands.save(key, record)

    assert entered == [], "save() reached for a workspace lock of its own"

    with workspace.hold_imported_hands([key]):
        workspace.imported_hands.save(key, approved_record())

    assert entered == [workspace.imported_hand_lock_index(key)]
    assert workspace.imported_hands.get(key).lifecycle.status == "active"


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
