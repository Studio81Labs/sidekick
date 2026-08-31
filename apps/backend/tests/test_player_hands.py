from app.player_hands import get_player_hand, list_player_hands
from app.storage.imported_hand_store import (
    FileImportedHandStore,
    imported_hand_record_key,
)
from test_imported_hand_store import (
    RAW_TEXT,
    approved_record,
    pending_review_record,
    sample_identity,
    tombstone_record,
)


def test_player_hand_pages_are_bounded_sorted_and_omit_raw_text(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    records = [
        pending_review_record(sample_identity(hand_ordinal=index))
        for index in (1, 2)
    ]
    keys = sorted(imported_hand_record_key(record.identity) for record in records)
    for record in records:
        store.save(imported_hand_record_key(record.identity), record)

    first = list_player_hands(store, limit=1)
    second = list_player_hands(store, limit=1, cursor=first.next_cursor)

    assert [item.record_key for item in first.items] == keys[:1]
    assert first.next_cursor == keys[0]
    assert [item.record_key for item in second.items] == keys[1:]
    assert second.next_cursor is None
    assert RAW_TEXT not in first.model_dump_json()
    assert "raw_text" not in first.model_dump_json()


def test_player_hand_detail_preserves_review_metadata_without_raw_text(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)

    detail = get_player_hand(store, key)
    serialized = detail.model_dump_json()

    assert detail.summary.lifecycle_status == "pending_review"
    assert detail.summary.learning_eligible is False
    assert detail.summary.warning_count == 2
    assert detail.raw_sources[0].provenance.adapter_id == "pokerstars"
    assert (
        detail.detections[0].field_evidence["/hero_player_id"].confidence
        is not None
    )
    assert detail.detections[0].warnings == ["Review hero identity"]
    assert RAW_TEXT not in serialized
    assert "raw_text" not in serialized
    assert "PokerStars Hand #123456789" not in serialized
    assert "excerpt" not in serialized


def test_player_hand_detail_represents_a_tombstone_without_identity_or_evidence(
    tmp_path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    key = "f" * 64
    store.save(key, tombstone_record(generation=3))

    detail = get_player_hand(store, key)

    assert detail.summary.identity is None
    assert detail.summary.lifecycle_status == "deleted"
    assert detail.summary.deletion_generation == 3
    assert detail.summary.learning_eligible is False
    assert detail.raw_sources == []
    assert detail.detections == []
    assert detail.conflicts == []
    assert detail.canonical_revisions == []
    assert detail.deletion_receipt is not None
    assert detail.deletion_receipt.generation == 3


def test_player_hand_detail_identifies_the_active_approved_revision(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    store.save(key, record)

    detail = get_player_hand(store, key)

    assert detail.summary.lifecycle_status == "active"
    assert detail.summary.active_canonical_revision == 1
    assert detail.summary.learning_eligible is True
    assert detail.summary.canonical_revision_count == 1
    assert [revision.revision for revision in detail.canonical_revisions] == [1]
