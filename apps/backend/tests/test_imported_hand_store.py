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
    ImportedHandCascadeHandle,
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
    HandDecisionExtraction,
    ImportProvenance,
    ImportedHandLifecycle,
    ImportedHandRecord,
    ImportedHandState,
    ImportedSeat,
    RawHandHistory,
    SourceChronology,
    StableHandIdentity,
    UserCorrection,
    extract_hero_decision_points,
    imported_hand_canonical_json,
    imported_hand_state_sha256,
)
from app.storage.cascade_journal import (
    CascadeJournal,
    CascadeReentryError,
    CascadeStaging,
)
from app.storage.imported_hand_store import (
    NO_CANONICAL_REVISION,
    ClosedCascadeError,
    DecisionArtifactRetentionError,
    FileImportedHandStore,
    ImportedHandCascade,
    ImportedHandNotFoundError,
    imported_hand_record_key,
    resolve_reimport,
)
from app.workspace import WorkspaceCoordinator
from test_imported_hand_decisions import hero_fold_decision_record

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


def conflicting_detection(identity: StableHandIdentity) -> DetectedImportedHand:
    """Same raw source as ``detected``, but a state that disagrees on hero.

    ``_detected_state_semantic_sha256`` normalizes away source-evidence
    locations and, under a zero ante, ``ante_mode`` -- but nothing else,
    and certainly not ``hero_player_id``. Flipping only that field is
    therefore a semantic disagreement on the *same bytes*: exactly the
    shape of mistake a detector or adapter upgrade could introduce by
    reinterpreting an unchanged raw hand history, which is what the
    identity_conflict escalation in ``classify_reimport`` exists to catch.
    """
    state = hand_state(identity, hero_player_id="hero")
    return DetectedImportedHand(
        detection_id="detection-2",
        raw_source_id="file-1",
        detector_id="pokerstars",
        detector_version="1.1.0",
        detected_at=NOW,
        state=state,
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
    *,
    deletion_generation: int = 0,
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
            deletion_generation=deletion_generation,
            changed_at=NOW,
        ),
    )


def reapproved_record(identity: StableHandIdentity | None = None) -> ImportedHandRecord:
    """The same hand approved a second time, superseding revision 1 with 2.

    The second revision reuses ``conflicting_detection``'s state, which
    already carries the corrected hero seat, so it needs no corrections of
    its own -- a canonical revision's state may differ from its detection
    only through recorded corrections, and here there is none to record.
    """
    hand_identity = identity or sample_identity()
    second_revision = CanonicalHandRevision(
        revision=2,
        detection_id="detection-2",
        approved_at=NOW,
        state=hand_state(hand_identity, hero_player_id="hero"),
    )
    return ImportedHandRecord(
        identity=hand_identity,
        raw_sources=[raw_source(hand_identity)],
        detections=[detected(hand_identity), conflicting_detection(hand_identity)],
        canonical_revisions=[revision(hand_identity), second_revision],
        lifecycle=ImportedHandLifecycle(
            status="active",
            active_canonical_revision=2,
            changed_at=NOW,
        ),
    )


def withdrawn_record(identity: StableHandIdentity | None = None) -> ImportedHandRecord:
    """The same hand's approval withdrawn: retained, but no longer active.

    The canonical revision stays on the record for audit -- only
    ``lifecycle`` changes -- so this is not learning eligible even though
    revision 1 is still sitting right there.
    """
    hand_identity = identity or sample_identity()
    return ImportedHandRecord(
        identity=hand_identity,
        raw_sources=[raw_source(hand_identity)],
        detections=[detected(hand_identity)],
        canonical_revisions=[revision(hand_identity)],
        lifecycle=ImportedHandLifecycle(status="withdrawn", changed_at=NOW),
    )


def extraction_for(record: ImportedHandRecord) -> HandDecisionExtraction:
    """The smallest legal extraction bound to ``record``'s current revision.

    These store tests exercise filename derivation and staleness, not the
    domain extraction algorithm itself -- that is
    test_imported_hand_decisions.py's job -- so this is a ``no_decision``
    outcome rather than a fully played hand.
    """
    assert record.identity is not None
    active_revision = record.lifecycle.active_canonical_revision
    assert active_revision is not None
    return HandDecisionExtraction(
        identity=record.identity,
        chronology=chronology(),
        provenance=raw_source(record.identity).provenance,
        canonical_revision=active_revision,
        deletion_generation=record.lifecycle.deletion_generation,
        outcome="no_decision",
        rejection=None,
        decision_points=[],
        excluded_actions=[],
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


def test_resolve_reimport_escalates_to_identity_conflict_on_semantic_detection_mismatch(
    tmp_path: Path,
) -> None:
    """Byte-identical content is not exact_reimport if its meaning changed.

    classify_reimport escalates exact_reimport to identity_conflict when
    candidate_detection's state disagrees semantically with every existing
    detection of the matching raw source -- the guard against a detector
    or adapter upgrade reinterpreting unchanged bytes, a real risk while
    adapters here are still being written. That branch is only reachable
    through resolve_reimport if candidate_detection is actually forwarded
    to classify_reimport: none of the other tests in this file pass a
    non-default candidate_detection, so this is the only one that would
    notice a refactor that dropped or misforwarded it.
    """
    store = FileImportedHandStore(tmp_path)
    identity = sample_identity()
    key = imported_hand_record_key(identity)
    store.save(key, pending_review_record(identity))

    resolution = resolve_reimport(
        store,
        identity,
        raw_source(identity),
        candidate_detection=conflicting_detection(identity),
    )

    assert resolution.record_key == key
    assert resolution.disposition == "identity_conflict"
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
    assert declared == ["begin_cascade", "find", "get", "list_keys", "recover", "save"]

    for name in declared:
        implementation = getattr(FileImportedHandStore, name, None)
        assert implementation is not None, f"{name} is not implemented"
        _assert_accepts_the_declared_call_shape(
            name,
            getattr(ImportedHandRepository, name),
            implementation,
        )


def test_the_cascade_satisfies_every_call_the_handle_protocol_declares() -> None:
    """The handle crosses the port too, so it needs its own conformance check.

    ``begin_cascade`` is only usable from the application layer if what
    it yields is declared as well: an undeclared ``stage_*`` method would
    be reached through an annotation that never mentioned it. The
    Protocol deliberately declares less than ``ImportedHandCascade``
    offers -- ``stage_decisions_delete`` belongs to a purge no
    application-layer caller performs yet -- so this checks that every
    declared member exists, not that the two sets are equal.
    """
    declared = sorted(
        name for name in vars(ImportedHandCascadeHandle) if not name.startswith("_")
    )
    assert declared == ["stage_decisions", "stage_record"]

    for name in declared:
        implementation = getattr(ImportedHandCascade, name, None)
        assert implementation is not None, f"{name} is not implemented"
        _assert_accepts_the_declared_call_shape(
            name,
            getattr(ImportedHandCascadeHandle, name),
            implementation,
        )


def test_begin_cascade_yields_the_handle_the_port_promises(tmp_path: Path) -> None:
    """A Protocol member list proves nothing about what is actually yielded."""
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)

    with store.begin_cascade(key, operation="approve") as cascade:
        assert isinstance(cascade, ImportedHandCascade)
        cascade.stage_record(record)

    assert store.get(key) == record


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


def test_active_decisions_ignores_a_superseded_revision(tmp_path: Path) -> None:
    store = FileImportedHandStore(tmp_path)
    record = approved_record()  # active revision 1, generation 0
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    extraction = extraction_for(record)
    store.save_decisions(key, extraction)

    active = store.active_decisions(key)
    assert active is not None
    # Full equality, not just presence: a round trip that silently dropped
    # or altered a field would still pass an `is not None` check.
    assert active == extraction

    store.save(key, reapproved_record())  # active revision 2
    assert store.active_decisions(key) is None  # r1 artifact is stale
    assert store.list_decision_artifacts(key) == [
        (1, 0, "r1-g0.json")
    ]  # retained for audit
    # Retention is a claim about content, not just a filename entry: a
    # truncated or corrupted "retained" artifact must not go unnoticed.
    assert store.get_decisions(key, revision=1, generation=0) == extraction


def test_active_decisions_returns_nothing_when_the_hand_is_not_learning_eligible(
    tmp_path: Path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    store.save_decisions(key, extraction_for(record))

    store.save(key, withdrawn_record())
    assert store.active_decisions(key) is None
    # Withdrawing is not purging: the artifact stays on disk for audit.
    assert store.list_decision_artifacts(key) == [(1, 0, "r1-g0.json")]


def test_active_decisions_never_serves_a_planted_artifact_when_not_learning_eligible(
    tmp_path: Path,
) -> None:
    """The ineligibility gate must mean "never served", not "never called".

    A withdrawn record's ``active_canonical_revision`` is always ``None``
    (the domain forbids an inactive lifecycle from retaining one). Code
    that forgot the ``learning_eligible`` gate would compute exactly
    ``f"r{None}-g{generation}.json"`` = ``"rNone-g0.json"`` and look it up
    unconditionally. Planting a genuinely valid, parseable extraction at
    that literal path and asserting it is never returned proves the gate
    black-box, without depending on mocking ``get_decisions`` to observe
    that it was never called.
    """
    store = FileImportedHandStore(tmp_path)
    record = withdrawn_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)

    planted = extraction_for(approved_record(identity=record.identity))
    decisions_dir = store.records_dir / key / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / "rNone-g0.json").write_bytes(
        planted.model_dump_json(indent=2).encode("utf-8")
    )

    assert store.active_decisions(key) is None


def test_decision_artifacts_are_keyed_by_revision_and_generation(
    tmp_path: Path,
) -> None:
    """r1-g0 and r1-g1 coexist and are independently retrievable."""
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    extraction_g0 = extraction_for(record)
    store.save_decisions(key, extraction_g0)

    record_g1 = approved_record(deletion_generation=1)
    store.save(key, record_g1)
    extraction_g1 = extraction_for(record_g1)
    store.save_decisions(key, extraction_g1)

    at_g0 = store.get_decisions(key, revision=1, generation=0)
    at_g1 = store.get_decisions(key, revision=1, generation=1)
    assert at_g0 == extraction_g0
    assert at_g1 == extraction_g1
    assert store.list_decision_artifacts(key) == [
        (1, 0, "r1-g0.json"),
        (1, 1, "r1-g1.json"),
    ]
    # The record is now at generation 1, so that's the one that's active.
    assert store.active_decisions(key) == at_g1


def test_get_decisions_returns_none_for_an_artifact_that_was_never_saved(
    tmp_path: Path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)

    assert store.get_decisions(key, revision=1, generation=0) is None
    assert store.get_decisions("0" * 64, revision=1, generation=0) is None


def test_get_decisions_returns_none_for_a_malformed_key(tmp_path: Path) -> None:
    """Matches active_decisions/list_decision_artifacts: every reader of
    decision artifacts treats a malformed key as "nothing found" the same
    way, leaving the eager ValueError to the write methods, where a
    malformed key is actually a caller bug worth failing loudly for.
    """
    store = FileImportedHandStore(tmp_path)
    assert store.get_decisions("../escape", revision=1, generation=0) is None


def test_list_decision_artifacts_is_empty_for_a_record_with_no_decisions(
    tmp_path: Path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)

    assert store.list_decision_artifacts(key) == []
    assert store.list_decision_artifacts("0" * 64) == []


def test_a_not_extractable_verdict_is_persisted_and_generation_stamped(
    tmp_path: Path,
) -> None:
    """A rejection binds no canonical revision but is still generation-stamped.

    ``extract_hero_decision_points`` reports ``not_active`` for a hand that
    is not learning eligible, and stamps it with whatever deletion
    generation the record is currently at even though it binds no
    canonical revision -- so a caller can tell "still not extractable at
    generation 1" apart from a verdict computed at generation 0, exactly
    as the rejection outcome is designed to allow. This hand is never
    learning eligible at either generation, so both land on the
    ``NO_CANONICAL_REVISION`` sentinel; see
    ``test_a_rejection_on_an_active_record_preserves_the_revision_dimension``
    for the (more common) case where the record producing the rejection
    *is* learning eligible.
    """
    store = FileImportedHandStore(tmp_path)
    record = withdrawn_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)

    rejection_g0 = extract_hero_decision_points(record)
    assert rejection_g0.outcome == "not_extractable"
    assert rejection_g0.rejection == "not_active"
    assert rejection_g0.canonical_revision is None
    store.save_decisions(key, rejection_g0)

    record_g1 = withdrawn_record().model_copy(
        update={
            "lifecycle": ImportedHandLifecycle(
                status="withdrawn",
                deletion_generation=1,
                changed_at=NOW,
            )
        }
    )
    store.save(key, record_g1)
    rejection_g1 = extract_hero_decision_points(record_g1)
    store.save_decisions(key, rejection_g1)

    stored_g0 = store.get_decisions(key, revision=NO_CANONICAL_REVISION, generation=0)
    stored_g1 = store.get_decisions(key, revision=NO_CANONICAL_REVISION, generation=1)
    assert stored_g0 == rejection_g0
    assert stored_g1 == rejection_g1
    assert stored_g0.deletion_generation == 0
    assert stored_g1.deletion_generation == 1
    assert store.list_decision_artifacts(key) == [
        (NO_CANONICAL_REVISION, 0, f"r{NO_CANONICAL_REVISION}-g0.json"),
        (NO_CANONICAL_REVISION, 1, f"r{NO_CANONICAL_REVISION}-g1.json"),
    ]
    # This hand's rejection is always "not_active", which always takes the
    # sentinel (see _decision_revision_for) and so can never be "active"
    # here -- not a general property of every rejection. The other five
    # reasons can accurately BE the current artifact while their revision
    # and generation stay current; see
    # test_a_not_active_rejection_never_takes_the_sentinel_fallback and
    # test_a_rejection_on_an_active_record_preserves_the_revision_dimension.
    assert store.active_decisions(key) is None


def test_a_rejection_on_an_active_record_preserves_the_revision_dimension(
    tmp_path: Path,
) -> None:
    """The common case ``NO_CANONICAL_REVISION`` alone cannot cover.

    ``canonical_revision`` is null for *every* rejection -- decisions.py's
    ``validate_outcome`` forbids binding one to a ``not_extractable``
    outcome even when the record producing it is otherwise active (an
    ``incomplete_hand_state`` rejection on an active revision-1 record is
    exactly as unbound as a ``not_active`` rejection on a withdrawn one).
    Filing solely by the extraction's own field would collapse every
    rejection at one generation onto a single name: reapproving a
    still-broken hand at revision 2 would silently ``os.replace`` its
    revision-1 predecessor's retained verdict out of existence. Falling
    back to the record's current ``active_canonical_revision`` keeps them
    apart.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()  # revision 1, still not extraction-ready
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    rejection_r1 = extract_hero_decision_points(record)
    assert rejection_r1.outcome == "not_extractable"
    assert rejection_r1.canonical_revision is None
    store.save_decisions(key, rejection_r1)

    record_r2 = reapproved_record()  # revision 2, still not extraction-ready
    store.save(key, record_r2)
    rejection_r2 = extract_hero_decision_points(record_r2)
    assert rejection_r2.outcome == "not_extractable"
    assert rejection_r2.canonical_revision is None
    store.save_decisions(key, rejection_r2)

    at_r1 = store.get_decisions(key, revision=1, generation=0)
    at_r2 = store.get_decisions(key, revision=2, generation=0)
    assert at_r1 == rejection_r1
    assert at_r2 == rejection_r2
    assert [
        (revision, generation)
        for revision, generation, _ in store.list_decision_artifacts(key)
    ] == [(1, 0), (2, 0)]


def test_a_not_active_rejection_never_takes_the_sentinel_fallback(
    tmp_path: Path,
) -> None:
    """The one rejection reason the record-read fallback must never use.

    A ``not_active`` rejection proves, from its own content, that the
    record was not learning eligible when it was computed. If the hand is
    reactivated before the rejection is ever saved, the fallback would
    otherwise file it under the record's newly-current revision: an
    artifact whose filename claims "this is the hand's current active
    revision" while its content says "this hand was not active", served
    by ``active_decisions`` as the hand's live decisions.
    """
    store = FileImportedHandStore(tmp_path)
    record = withdrawn_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    rejection = extract_hero_decision_points(record)
    assert rejection.rejection == "not_active"

    # Reactivate at revision 1 -- the same revision the record-read
    # fallback would otherwise hand back -- before the stale rejection is
    # ever persisted.
    store.save(key, approved_record(identity=record.identity))
    store.save_decisions(key, rejection)

    assert store.get_decisions(key, revision=1, generation=0) is None
    assert store.active_decisions(key) is None
    assert (
        store.get_decisions(key, revision=NO_CANONICAL_REVISION, generation=0)
        == rejection
    )


def test_a_rejection_never_borrows_a_revision_from_a_different_generation(
    tmp_path: Path,
) -> None:
    """The record's active_canonical_revision belongs to whichever
    incarnation it is CURRENTLY at. Pairing it with an extraction stamped
    at an older generation (a purge-and-reimport cycle happened between
    extraction and save) would file a name whose revision and generation
    describe two different snapshots in time. The fallback trusts the
    record only when both agree.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()  # revision 1, generation 0
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    stale_rejection = extract_hero_decision_points(record)  # generation 0
    assert stale_rejection.canonical_revision is None
    assert stale_rejection.rejection != "not_active"
    assert stale_rejection.deletion_generation == 0

    # The record moves on to a new generation before the stale rejection
    # is ever persisted.
    record_g1 = approved_record(deletion_generation=1)  # revision 1, generation 1
    store.save(key, record_g1)

    store.save_decisions(key, stale_rejection)

    # Never borrows record_g1's revision for a generation it does not
    # belong to.
    assert store.get_decisions(key, revision=1, generation=0) is None
    assert (
        store.get_decisions(key, revision=NO_CANONICAL_REVISION, generation=0)
        == stale_rejection
    )


def test_save_decisions_round_trips_a_real_decisions_outcome_losslessly(
    tmp_path: Path,
) -> None:
    """The shape this feature exists for, not the store tests' own
    bare-bones ``no_decision`` stand-in: real decision points carrying
    ``Decimal`` chip state and nested action history.

    Exercises the actual extraction algorithm
    (``hero_fold_decision_record``, from test_imported_hand_decisions.py)
    so a ``Decimal`` or strict-mode regression in the JSON round trip
    would be caught here, through this store, not only in the domain's
    own tests, which never go through it.
    """
    store = FileImportedHandStore(tmp_path)
    record = hero_fold_decision_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)

    extraction = extract_hero_decision_points(record)
    assert extraction.outcome == "decisions"
    assert len(extraction.decision_points) == 1
    store.save_decisions(key, extraction)

    assert store.get_decisions(key, revision=1, generation=0) == extraction
    assert store.active_decisions(key) == extraction


def test_begin_cascade_stages_a_record_and_its_decisions_as_one_unit(
    tmp_path: Path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    extraction = extraction_for(record)

    with store.begin_cascade(key, operation="approve") as cascade:
        cascade.stage_record(record)
        cascade.stage_decisions(extraction)

    assert store.get(key) == record
    assert store.active_decisions(key) == extraction


def test_begin_cascade_is_all_or_nothing_when_a_later_stage_fails(
    tmp_path: Path,
) -> None:
    """A record staged successfully must not become visible if a later
    stage in the same cascade fails -- the reason begin_cascade exists
    over two separate save()/save_decisions() calls.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    foreign_extraction = extraction_for(approved_record(sample_identity(hand_ordinal=2)))

    with pytest.raises(ValueError, match="not derived from this extraction"):
        with store.begin_cascade(key, operation="approve") as cascade:
            cascade.stage_record(record)
            cascade.stage_decisions(foreign_extraction)

    with pytest.raises(ImportedHandNotFoundError):
        store.get(key)
    assert store.list_decision_artifacts(key) == []


def test_stage_decisions_in_a_composed_cascade_prefers_the_cascades_own_record(
    tmp_path: Path,
) -> None:
    """The reason begin_cascade exists: a rejection computed against the
    record a cascade is about to publish must be filed under that
    record's new revision, not the stale one still live on disk until
    commit. Rereading the store instead of preferring the cascade's own
    staged record would silently misfile this under revision 1.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()  # revision 1
    key = imported_hand_record_key(record.identity)
    store.save(key, record)

    record_r2 = reapproved_record()  # revision 2, still not extraction-ready
    rejection = extract_hero_decision_points(record_r2)
    assert rejection.canonical_revision is None

    with store.begin_cascade(key, operation="reapprove") as cascade:
        cascade.stage_record(record_r2)
        cascade.stage_decisions(rejection)

    assert store.get(key) == record_r2
    assert store.get_decisions(key, revision=2, generation=0) == rejection
    assert store.get_decisions(key, revision=1, generation=0) is None


def test_stage_decisions_delete_removes_an_artifact_when_the_cascade_commits(
    tmp_path: Path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    extraction = extraction_for(record)
    store.save_decisions(key, extraction)
    assert store.get_decisions(key, revision=1, generation=0) is not None

    with store.begin_cascade(key, operation="purge") as cascade:
        cascade.stage_decisions_delete("r1-g0.json")

    assert store.get_decisions(key, revision=1, generation=0) is None


def test_stage_decisions_delete_removes_exactly_the_listed_filename(
    tmp_path: Path,
) -> None:
    """Proves the fix: a delete keyed by revision/generation alone can
    silently miss a filename that does not exactly match what
    reconstruction would build (``r01-g0.json`` parses to ``(1, 0)`` but
    is not ``r1-g0.json``). Deleting by the exact filename
    ``list_decision_artifacts`` returned cannot have this gap, because it
    targets what was actually seen, not a guess.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    extraction = extraction_for(record)
    # A weird-but-legal-looking filename a reconstruction from (1, 0)
    # would never produce.
    decisions_dir = store.records_dir / key / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / "r01-g0.json").write_bytes(
        extraction.model_dump_json(indent=2).encode("utf-8")
    )

    artifacts = store.list_decision_artifacts(key)
    assert artifacts == [(1, 0, "r01-g0.json")]
    [(_, _, filename)] = artifacts

    with store.begin_cascade(key, operation="purge") as cascade:
        cascade.stage_decisions_delete(filename)

    assert store.list_decision_artifacts(key) == []
    assert not (decisions_dir / "r01-g0.json").exists()


def test_stage_decisions_delete_refuses_a_non_artifact_filename(
    tmp_path: Path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)

    with pytest.raises(ValueError, match="not a decision artifact filename"):
        with store.begin_cascade(key, operation="purge") as cascade:
            cascade.stage_decisions_delete("record.json")


def test_stage_decisions_before_stage_record_still_resolves_to_the_new_revision(
    tmp_path: Path,
) -> None:
    """Proves the fix: computing the extraction before building the
    record it came from -- the natural order -- must not misfile the
    artifact under whatever revision is still live on disk at the moment
    ``stage_decisions`` is called. Resolution happens once, at cascade
    exit, against the cascade's *final* staged record.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()  # revision 1
    key = imported_hand_record_key(record.identity)
    store.save(key, record)

    record_r2 = reapproved_record()  # revision 2, still not extraction-ready
    rejection = extract_hero_decision_points(record_r2)
    assert rejection.canonical_revision is None

    with store.begin_cascade(key, operation="reapprove") as cascade:
        cascade.stage_decisions(rejection)  # decisions staged FIRST
        cascade.stage_record(record_r2)  # record staged second

    assert store.get(key) == record_r2
    assert store.get_decisions(key, revision=2, generation=0) == rejection
    assert store.get_decisions(key, revision=1, generation=0) is None


def test_stage_methods_raise_on_a_closed_cascade(tmp_path: Path) -> None:
    """A handle that escapes its ``with`` block must fail loudly on reuse.

    Neither ``ImportedHandCascade`` nor its underlying ``CascadeStaging``
    is otherwise invalidated on exit -- a call on an escaped handle would
    succeed locally while writing into a scratch directory the next
    recover() sweep discards silently, in no reported bucket.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    extraction = extraction_for(record)

    with store.begin_cascade(key, operation="approve") as cascade:
        pass

    with pytest.raises(ClosedCascadeError):
        cascade.stage_record(record)
    with pytest.raises(ClosedCascadeError):
        cascade.stage_decisions(extraction)
    with pytest.raises(ClosedCascadeError):
        cascade.stage_decisions_delete("r1-g0.json")


def test_calling_save_inside_an_open_cascade_raises_reentrantly(
    tmp_path: Path,
) -> None:
    """The journal lock is a leaf lock: a caller composing a write must
    stage everything through begin_cascade's own handle, never by calling
    save()/save_decisions() again from inside one.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)

    with pytest.raises(CascadeReentryError):
        with store.begin_cascade(key, operation="approve") as cascade:
            store.save(key, record)


def test_save_decisions_publishes_through_the_journal(tmp_path: Path) -> None:
    """Named for what it pins: every decisions write opens its own cascade.

    Mirrors test_save_publishes_through_the_journal for the record path.
    Uses the journal's own "save" operation label, not a bespoke one:
    CascadeIntent reserves "save" for exactly this -- a plain write
    undescribed by any lifecycle verb -- and there is no "save_decisions"
    literal to spend.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    extraction = extraction_for(record)
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
        store.save_decisions(key, extraction)

    assert opened == [("save", [key])]
    assert store.active_decisions(key) == extraction


def test_save_decisions_holds_the_data_lock_shared_for_its_whole_cascade(
    tmp_path: Path,
) -> None:
    """Mirrors test_save_holds_the_data_lock_shared_for_its_whole_cascade.

    A decisions write left uncovered by the shared hold would be just as
    invisible to a concurrent exclusive recovery sweep as an unlocked
    record write.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    extraction = extraction_for(record)
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
        store.save_decisions(key, extraction)

    assert held_during_cascade == [True]
    assert not exclusive_data_lock_is_blocked(tmp_path)


def test_save_decisions_refuses_a_key_foreign_to_the_extractions_identity(
    tmp_path: Path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    extraction = extraction_for(record)
    other_key = imported_hand_record_key(sample_identity(hand_ordinal=2))

    with pytest.raises(ValueError, match="not derived from this extraction"):
        store.save_decisions(other_key, extraction)


def unbound_rejection(record: ImportedHandRecord) -> HandDecisionExtraction:
    """A rejection that resolves to the same name as ``extraction_for``.

    Carries no canonical revision of its own (decisions.py forbids one on
    a ``not_extractable`` outcome), so the record-read fallback files it
    under the record's own active revision -- the very name a successful
    extraction of that same revision already occupies.
    """
    return HandDecisionExtraction(
        identity=record.identity,
        chronology=None,
        provenance=None,
        canonical_revision=None,
        deletion_generation=record.lifecycle.deletion_generation,
        outcome="not_extractable",
        rejection="incomplete_hand_state",
        decision_points=[],
        excluded_actions=[],
    )


def test_stage_decisions_refuses_to_publish_over_a_retained_artifact(
    tmp_path: Path,
) -> None:
    """Retention is not only about deletion; an overwrite destroys too.

    Issue #432 retains a superseded artifact for audit, and every path
    that could remove one was closed in Task 4 -- except this one, which
    removes it by writing a different artifact over its name. A
    transition that leaves a record's revision and generation exactly
    where they are (recording a conflict against an already-approved
    hand) resolves to the name the approved artifact already occupies,
    and ``os.replace`` takes it out with no trace in
    ``list_decision_artifacts``.

    The application layer cannot see this namespace, so the refusal has
    to live here: it is a storage invariant about names this store owns,
    and it protects every caller rather than one service.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    retained = extraction_for(record)
    store.save_decisions(key, retained)

    with pytest.raises(DecisionArtifactRetentionError):
        store.save_decisions(key, unbound_rejection(record))

    assert store.get_decisions(key, revision=1, generation=0) == retained
    assert store.list_decision_artifacts(key) == [(1, 0, "r1-g0.json")]


def test_stage_decisions_accepts_an_identical_republish(tmp_path: Path) -> None:
    """Idempotent replay is not an overwrite: nothing is lost.

    A retried cascade recomputes the same verdict for the same revision
    and generation, and refusing that would turn a harmless replay into a
    failure the caller has no way to distinguish from real corruption.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    extraction = extraction_for(record)

    store.save_decisions(key, extraction)
    store.save_decisions(key, extraction)

    assert store.get_decisions(key, revision=1, generation=0) == extraction
    assert store.list_decision_artifacts(key) == [(1, 0, "r1-g0.json")]


def test_one_cascade_cannot_stage_two_artifacts_over_each_other(
    tmp_path: Path,
) -> None:
    """The same hazard with no file on disk to compare against yet.

    Both extractions resolve to one name, so the second would replace the
    first inside the scratch tree and only one would ever be published --
    the loss happening before commit rather than at it.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)

    with pytest.raises(DecisionArtifactRetentionError):
        with store.begin_cascade(key, operation="save") as cascade:
            cascade.stage_decisions(extraction_for(record))
            cascade.stage_decisions(unbound_rejection(record))

    assert store.list_decision_artifacts(key) == []


def test_a_cascade_refused_for_retention_is_still_closed(tmp_path: Path) -> None:
    """The handle must not survive the failure that closed its cascade.

    ``_finalize`` now has a reason of its own to raise, and the flag that
    invalidates an escaped handle is set there. Set on the way out or
    not at all, a retention refusal would leave a live handle behind and
    quietly undo Task 4's escaped-cascade protection.
    """
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    escaped: list[ImportedHandCascade] = []

    with pytest.raises(DecisionArtifactRetentionError):
        with store.begin_cascade(key, operation="save") as cascade:
            escaped.append(cascade)
            cascade.stage_decisions(extraction_for(record))
            cascade.stage_decisions(unbound_rejection(record))

    with pytest.raises(ClosedCascadeError):
        escaped[0].stage_record(record)
