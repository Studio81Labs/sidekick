from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from time import sleep

import pytest

from app.application.imported_hand_ingestion import (
    ImportedHandImportIdConflict,
    ImportedHandIngestionBlocked,
    ImportedHandIngestionError,
    ImportedHandIngestionService,
    ParsedImportedHandCandidate,
)
from app.domain.imported_hands import (
    DetectedImportedHand,
    ImportedHandLifecycle,
    ImportedHandRecord,
    RawHandHistory,
    RawHandReimport,
    SourceChronology,
    canonical_revision_from_review,
    classify_restore,
    detected_imported_hand_semantic_sha256,
    extract_hero_decision_points,
    imported_hand_state_sha256,
)
from app.player_hands import (
    PlayerHandApprovalRequest,
    get_player_hand,
    player_hand_record_version,
)
from app.player_workspace import PlayerHandApprovalInvalid, PlayerWorkspace
from app.storage.imported_hand_store import (
    FileImportedHandStore,
    imported_hand_record_key,
)
from test_imported_hand_store import (
    NOW,
    RAW_TEXT,
    approved_record,
    hand_state,
    sample_identity,
    tombstone_record,
)


def parsed_candidate(
    occurrence: int,
    *,
    raw_text: str = RAW_TEXT,
    hero_player_id: str | None = None,
) -> ParsedImportedHandCandidate:
    identity = sample_identity()
    raw_source_id = f"source-{occurrence}"
    imported_at = NOW + timedelta(minutes=occurrence)
    chronology = SourceChronology(
        played_at=None,
        source_timezone=None,
        source_session_id=f"session-{occurrence}",
        source_file_id=raw_source_id,
        hand_ordinal=occurrence,
    )
    raw = RawHandHistory(
        raw_source_id=raw_source_id,
        identity=identity,
        chronology=chronology,
        provenance={
            "import_id": f"import-{occurrence}",
            "imported_at": imported_at,
            "adapter_id": "pokerstars",
            "adapter_version": "1.0.0",
            "format_revision": "pokerstars-text/v1",
            "source_filename": f"history-{occurrence}.txt",
        },
        content_sha256=sha256(raw_text.encode("utf-8")).hexdigest(),
        raw_text=raw_text,
    )
    state_payload = hand_state(
        identity,
        hero_player_id=hero_player_id,
    ).model_dump(mode="python")
    state_payload["chronology"] = chronology.model_dump(mode="python")
    state = type(hand_state(identity)).model_validate(state_payload)
    detection = DetectedImportedHand(
        detection_id=f"detection-{occurrence}",
        raw_source_id=raw_source_id,
        detector_id="pokerstars",
        detector_version="1.0.0",
        detected_at=imported_at,
        state=state,
        content_sha256=imported_hand_state_sha256(state),
    )
    return ParsedImportedHandCandidate(raw=raw, detection=detection)


def test_ingestion_creates_a_pending_review_record(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)

    result = service.ingest(parsed_candidate(1))

    assert result.disposition == "created_pending_review"
    assert result.record.lifecycle.status == "pending_review"
    assert result.record.canonical_revisions == []
    assert result.record.raw_sources[0].initial_detection_id == "detection-1"
    assert (
        result.record.raw_sources[0].initial_detected_semantic_sha256
        == detected_imported_hand_semantic_sha256(result.record.detections[0].state)
    )
    assert store.get(result.record_key) == result.record


def test_exact_reimport_appends_occurrence_without_duplicate_learning_data(
    tmp_path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)
    first = service.ingest(parsed_candidate(1))

    result = service.ingest(parsed_candidate(2))

    assert result.disposition == "recorded_exact_reimport"
    assert len(result.record.raw_sources) == 1
    assert len(result.record.raw_sources[0].reimports) == 1
    assert result.record.raw_sources[0].reimports[0].raw_source_id == "source-2"
    assert (
        result.record.raw_sources[0].reimports[0].detected_semantic_sha256
        == result.record.raw_sources[0].initial_detected_semantic_sha256
    )
    assert len(result.record.detections) == 2
    assert result.record.detections[-1].raw_source_id == "source-2"
    assert result.record.canonical_revisions == first.record.canonical_revisions
    detail = get_player_hand(store, result.record_key)
    assert detail.summary.raw_source_count == 2
    assert len(detail.raw_sources) == 1
    projected_reimport = detail.raw_sources[0].reimports[0]
    retained_reimport = result.record.raw_sources[0].reimports[0]
    assert projected_reimport.raw_source_id == "source-2"
    assert projected_reimport.chronology == retained_reimport.chronology
    assert projected_reimport.provenance == retained_reimport.provenance
    assert projected_reimport.detection_id == "detection-2"
    assert (
        projected_reimport.detected_semantic_sha256
        == retained_reimport.detected_semantic_sha256
    )


def test_same_import_request_is_idempotent(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)
    service.ingest(parsed_candidate(1))
    candidate = parsed_candidate(2)
    first = service.ingest(candidate)

    replay = service.ingest(candidate)

    assert replay.disposition == "duplicate_request"
    assert replay.record == first.record
    assert len(replay.record.raw_sources[0].reimports) == 1


def test_exact_reimport_retains_changed_recognition_audit(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)
    service.ingest(parsed_candidate(1))
    candidate = parsed_candidate(2)
    detection_payload = candidate.detection.model_dump(mode="python")
    detection_payload["field_evidence"] = {
        "/hero_player_id": {
            "confidence": Decimal("0.7"),
            "evidence": [
                {
                    "raw_source_id": "source-2",
                    "line_start": 1,
                    "line_end": 1,
                    "marker": "reimport-hero-line",
                }
            ],
            "warnings": ["Reimport hero evidence changed"],
        }
    }
    detection_payload["warnings"] = ["Review reimport hero evidence"]
    candidate = ParsedImportedHandCandidate(
        raw=candidate.raw,
        detection=DetectedImportedHand.model_validate(detection_payload),
    )

    result = service.ingest(candidate)

    assert result.disposition == "recorded_exact_reimport"
    assert len(result.record.detections) == 2
    retained = result.record.detections[-1]
    assert retained.raw_source_id == "source-2"
    assert retained.detector_version == "1.0.0"
    assert retained.warnings == ["Review reimport hero evidence"]
    assert retained.field_evidence["/hero_player_id"].warnings == [
        "Reimport hero evidence changed"
    ]
    detail = get_player_hand(store, result.record_key)
    assert detail.detections[-1].approval_eligible is False
    assert detail.detections[-1].warnings == ["Review reimport hero evidence"]


def test_reimport_audit_detection_cannot_become_canonical(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)
    service.ingest(parsed_candidate(1))
    record = service.ingest(parsed_candidate(2)).record
    audit_detection = record.detections[-1]
    approved_at = NOW + timedelta(minutes=3)
    revision = canonical_revision_from_review(
        audit_detection,
        approval_id="33333333-3333-4333-8333-333333333333",
        revision=1,
        approved_at=approved_at,
        approved_state=audit_detection.state.model_dump(mode="json"),
        correction_reason=None,
    )
    payload = record.model_dump(mode="python")
    payload["canonical_revisions"] = [revision]
    payload["lifecycle"] = {
        "status": "active",
        "active_canonical_revision": 1,
        "changed_at": approved_at,
    }

    with pytest.raises(ValueError, match="audit-only reimport detection"):
        ImportedHandRecord.model_validate(payload)


def test_player_workspace_rejects_reimport_audit_detection_approval(
    tmp_path,
) -> None:
    workspace = PlayerWorkspace.open(tmp_path)
    workspace.ingest_detected_hand(parsed_candidate(1))
    result = workspace.ingest_detected_hand(parsed_candidate(2))
    record = result.record
    detection = record.detections[-1]
    request = PlayerHandApprovalRequest(
        request_id="33333333-3333-4333-8333-333333333333",
        detection_id=detection.detection_id,
        approved_state=detection.state.model_dump(mode="json"),
        correction_reason=None,
        expected_record_version=player_hand_record_version(record),
        expected_lifecycle_status=record.lifecycle.status,
        expected_active_canonical_revision=None,
        expected_canonical_revision_count=0,
        expected_deletion_generation=record.lifecycle.deletion_generation,
        expected_lifecycle_changed_at=record.lifecycle.changed_at,
    )

    with pytest.raises(PlayerHandApprovalInvalid, match="audit-only"):
        workspace.approve_hand_record(
            result.record_key,
            request=request,
            at=NOW + timedelta(minutes=3),
        )


def test_import_retry_cannot_change_recognition_audit(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)
    service.ingest(parsed_candidate(1))
    candidate = parsed_candidate(2)
    service.ingest(candidate)
    changed_payload = candidate.detection.model_dump(mode="python")
    changed_payload["warnings"] = ["New warning on retry"]
    changed = ParsedImportedHandCandidate(
        raw=candidate.raw,
        detection=DetectedImportedHand.model_validate(changed_payload),
    )

    with pytest.raises(ImportedHandImportIdConflict, match="audit evidence"):
        service.ingest(changed)


def test_exact_reimport_detection_cannot_precede_its_occurrence(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)
    service.ingest(parsed_candidate(1))
    candidate = parsed_candidate(2)
    detection_payload = candidate.detection.model_dump(mode="python")
    detection_payload["detected_at"] = NOW + timedelta(minutes=1)

    with pytest.raises(ValueError, match="precede referenced source occurrence"):
        service.ingest(
            ParsedImportedHandCandidate(
                raw=candidate.raw,
                detection=DetectedImportedHand.model_validate(detection_payload),
            )
        )


def test_source_occurrences_require_distinct_detection_bindings(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)
    service.ingest(parsed_candidate(1))
    record = service.ingest(parsed_candidate(2)).record
    payload = record.model_dump(mode="python")
    payload["raw_sources"][0]["reimports"][0]["detection_id"] = "detection-1"

    with pytest.raises(ValueError, match="detection bindings must be unique"):
        ImportedHandRecord.model_validate(payload)


def test_import_id_cannot_be_reused_for_different_source_evidence(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)
    first = parsed_candidate(1)
    service.ingest(first)
    changed = parsed_candidate(2)
    changed_raw_payload = changed.raw.model_dump(mode="python")
    changed_raw_payload["provenance"]["import_id"] = "import-1"
    changed = ParsedImportedHandCandidate(
        raw=RawHandHistory.model_validate(changed_raw_payload),
        detection=changed.detection,
    )

    with pytest.raises(ImportedHandImportIdConflict, match="different"):
        service.ingest(changed)

    stored = store.get(imported_hand_record_key(first.raw.identity))
    assert stored == service.ingest(first).record


def test_import_retry_cannot_change_detected_hand_meaning(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)
    first = parsed_candidate(1)
    service.ingest(first)
    changed_detection = parsed_candidate(1, hero_player_id="hero")

    with pytest.raises(ImportedHandImportIdConflict, match="detected hand meaning"):
        service.ingest(changed_detection)

    assert len(store.get(imported_hand_record_key(first.raw.identity)).detections) == 1


def test_initial_import_retry_stays_bound_after_a_semantic_conflict(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(
        store=store,
        conflict_id_factory=lambda: "conflict-semantic",
    )
    service.ingest(parsed_candidate(1))
    service.ingest(parsed_candidate(2, hero_player_id="hero"))

    with pytest.raises(ImportedHandImportIdConflict, match="detected hand meaning"):
        service.ingest(parsed_candidate(1, hero_player_id="hero"))

    stored = store.get(imported_hand_record_key(sample_identity()))
    assert len(stored.raw_sources[0].reimports) == 1
    assert len(stored.detections) == 2


def test_adapter_candidate_cannot_pre_author_reimport_audit(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    candidate = parsed_candidate(1)
    raw_payload = candidate.raw.model_dump(mode="python")
    raw_payload["reimports"] = [
        RawHandReimport(
            raw_source_id="source-preauthored",
            chronology=SourceChronology(
                source_file_id="source-preauthored",
                hand_ordinal=2,
            ),
            provenance={
                "import_id": "import-preauthored",
                "imported_at": NOW + timedelta(minutes=2),
                "adapter_id": "pokerstars",
                "adapter_version": "1.0.0",
                "format_revision": "pokerstars-text/v1",
            },
            detection_id="detection-1",
            detected_semantic_sha256=detected_imported_hand_semantic_sha256(
                candidate.detection.state
            ),
        )
    ]
    raw_payload["initial_detection_id"] = candidate.detection.detection_id
    raw_payload["initial_detected_semantic_sha256"] = (
        detected_imported_hand_semantic_sha256(candidate.detection.state)
    )
    candidate = ParsedImportedHandCandidate(
        raw=RawHandHistory.model_validate(raw_payload),
        detection=candidate.detection,
    )

    with pytest.raises(ImportedHandIngestionError, match="cannot pre-author"):
        ImportedHandIngestionService(store=store).ingest(candidate)

    assert store.list_keys() == []


def test_materially_different_reimport_is_retained_as_unresolved_conflict(
    tmp_path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(
        store=store,
        conflict_id_factory=lambda: "conflict-material",
    )
    service.ingest(parsed_candidate(1))

    result = service.ingest(
        parsed_candidate(2, raw_text=f"{RAW_TEXT}Total pot 2\n")
    )

    assert result.disposition == "recorded_identity_conflict"
    assert len(result.record.raw_sources) == 2
    assert len(result.record.detections) == 2
    assert result.record.conflicts[0].status == "unresolved"
    assert result.record.conflicts[0].raw_source_ids == ["source-1", "source-2"]


def test_changed_detection_of_same_bytes_is_retained_without_copying_raw_text(
    tmp_path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(
        store=store,
        conflict_id_factory=lambda: "conflict-semantic",
    )
    service.ingest(parsed_candidate(1))

    result = service.ingest(parsed_candidate(2, hero_player_id="hero"))

    assert result.disposition == "recorded_identity_conflict"
    assert len(result.record.raw_sources) == 1
    assert len(result.record.raw_sources[0].reimports) == 1
    assert len(result.record.detections) == 2
    assert result.record.detections[-1].raw_source_id == "source-1"
    assert result.record.conflicts[0].raw_source_ids == ["source-1"]
    assert result.record.conflicts[0].detected_ids == [
        "detection-1",
        "detection-2",
    ]
    assert (
        result.record.raw_sources[0].reimports[0].detected_semantic_sha256
        == detected_imported_hand_semantic_sha256(result.record.detections[-1].state)
    )


@pytest.mark.parametrize("raw_text", [RAW_TEXT, f"{RAW_TEXT}Total pot 2\n"])
def test_new_occurrence_cannot_precede_the_aggregate_import_history(
    tmp_path,
    raw_text: str,
) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)
    service.ingest(parsed_candidate(1))
    latest = service.ingest(parsed_candidate(3)).record

    with pytest.raises(ImportedHandIngestionError, match="latest retained import"):
        service.ingest(parsed_candidate(2, raw_text=raw_text))

    assert store.get(imported_hand_record_key(sample_identity())) == latest


def test_exact_retry_remains_idempotent_after_later_imports(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)
    candidate = parsed_candidate(2)
    service.ingest(parsed_candidate(1))
    service.ingest(candidate)
    latest = service.ingest(parsed_candidate(3)).record

    replay = service.ingest(candidate)

    assert replay.disposition == "duplicate_request"
    assert replay.record == latest


def test_semantic_fingerprints_must_bind_to_retained_detections(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    record = ImportedHandIngestionService(store=store).ingest(
        parsed_candidate(1)
    ).record
    payload = record.model_dump(mode="python")
    payload["raw_sources"][0]["initial_detected_semantic_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="initial detection binding"):
        ImportedHandRecord.model_validate(payload)


def test_unresolved_reimport_conflict_blocks_active_decision_extraction(
    tmp_path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    current = approved_record()
    key = imported_hand_record_key(current.identity)
    store.save(key, current)
    service = ImportedHandIngestionService(
        store=store,
        conflict_id_factory=lambda: "conflict-active",
    )
    candidate = parsed_candidate(2, raw_text=f"{RAW_TEXT}Total pot 2\n")

    result = service.ingest(candidate)

    assert result.record.lifecycle.status == "active"
    assert result.record.lifecycle.active_canonical_revision == 1
    extraction = extract_hero_decision_points(result.record)
    assert extraction.outcome == "not_extractable"
    assert extraction.rejection == "unresolved_conflict"


@pytest.mark.parametrize("status", ["deleted", "deletion_pending"])
def test_ingestion_fails_closed_for_deletion_lifecycle(tmp_path, status: str) -> None:
    store = FileImportedHandStore(tmp_path)
    identity = sample_identity()
    key = imported_hand_record_key(identity)
    if status == "deleted":
        record = tombstone_record(generation=1)
    else:
        active = approved_record()
        lifecycle = ImportedHandLifecycle(
            status="deletion_pending",
            deletion_generation=1,
            changed_at=NOW + timedelta(minutes=3),
            deletion_request={
                "generation": 1,
                "requested_at": NOW + timedelta(minutes=3),
            },
        )
        record = ImportedHandRecord(
            identity=active.identity,
            raw_sources=active.raw_sources,
            detections=active.detections,
            canonical_revisions=active.canonical_revisions,
            lifecycle=lifecycle,
        )
    store.save(key, record)

    with pytest.raises(ImportedHandIngestionBlocked, match="explicit"):
        ImportedHandIngestionService(store=store).ingest(parsed_candidate(4))

    assert store.get(key) == record


def test_exact_reimport_is_a_monotonic_restore_candidate(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    service = ImportedHandIngestionService(store=store)
    current = service.ingest(parsed_candidate(1)).record
    updated = service.ingest(parsed_candidate(2)).record

    assert classify_restore(current, updated).kind == "allow"
    assert classify_restore(updated, current).kind == "stale_record"


def test_exact_reimport_enriches_a_legacy_raw_semantic_binding(tmp_path) -> None:
    store = FileImportedHandStore(tmp_path)
    current = approved_record()
    assert current.raw_sources[0].initial_detected_semantic_sha256 is None
    key = imported_hand_record_key(current.identity)
    store.save(key, current)

    updated = ImportedHandIngestionService(store=store).ingest(
        parsed_candidate(2)
    ).record

    assert updated.raw_sources[0].initial_detected_semantic_sha256 is not None
    assert updated.raw_sources[0].initial_detection_id == "detection-1"
    assert len(updated.raw_sources[0].reimports) == 1
    assert classify_restore(current, updated).kind == "allow"


def test_player_workspace_composes_ingestion_under_local_record_locks(
    tmp_path,
) -> None:
    workspace = PlayerWorkspace.open(tmp_path)

    result = workspace.ingest_detected_hand(parsed_candidate(1))

    assert result.disposition == "created_pending_review"
    assert workspace.imported_hands.get(result.record_key) == result.record
    assert not workspace.imported_hands.has_interrupted_write(result.record_key)


def test_player_workspace_serializes_concurrent_ingestion_without_lost_appends(
    tmp_path,
    monkeypatch,
) -> None:
    workspace = PlayerWorkspace.open(tmp_path)
    workspace.ingest_detected_hand(parsed_candidate(1))
    candidates = []
    for occurrence in range(2, 10):
        candidate = parsed_candidate(occurrence)
        raw_payload = candidate.raw.model_dump(mode="python")
        raw_payload["provenance"]["imported_at"] = NOW + timedelta(minutes=2)
        detection_payload = candidate.detection.model_dump(mode="python")
        detection_payload["detected_at"] = NOW + timedelta(minutes=2)
        candidates.append(
            ParsedImportedHandCandidate(
                raw=RawHandHistory.model_validate(raw_payload),
                detection=DetectedImportedHand.model_validate(detection_payload),
            )
        )

    save = workspace.imported_hands.save

    def delayed_save(record_key, record) -> None:
        sleep(0.01)
        save(record_key, record)

    monkeypatch.setattr(workspace.imported_hands, "save", delayed_save)
    with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
        results = list(executor.map(workspace.ingest_detected_hand, candidates))

    stored = workspace.imported_hands.get(results[0].record_key)
    assert {result.disposition for result in results} == {
        "recorded_exact_reimport"
    }
    assert {item.raw_source_id for item in stored.raw_sources[0].reimports} == {
        f"source-{occurrence}" for occurrence in range(2, 10)
    }
