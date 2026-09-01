"""Conflict-safe ingestion of already-parsed local hand-history candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal
from uuid import uuid4

from app.application.imported_hand_ports import ImportedHandRepository
from app.domain.imported_hands import (
    DetectedImportedHand,
    ImportConflict,
    ImportedHandLifecycle,
    ImportedHandRecord,
    ImportedHandState,
    RawHandHistory,
    RawHandReimport,
    detected_imported_hand_semantic_sha256,
    imported_hand_state_sha256,
)


class ImportedHandIngestionError(ValueError):
    """A parsed candidate cannot be safely appended to the local aggregate."""


class ImportedHandIngestionBlocked(ImportedHandIngestionError):
    """The retained lifecycle forbids an import mutation."""


class ImportedHandImportIdConflict(ImportedHandIngestionError):
    """One import id was reused for different source evidence."""


@dataclass(frozen=True)
class ParsedImportedHandCandidate:
    """One adapter-produced raw source and its detected, unapproved state."""

    raw: RawHandHistory
    detection: DetectedImportedHand


IngestionDisposition = Literal[
    "created_pending_review",
    "recorded_exact_reimport",
    "recorded_identity_conflict",
    "duplicate_request",
]


@dataclass(frozen=True)
class ImportedHandIngestionResult:
    record_key: str
    disposition: IngestionDisposition
    record: ImportedHandRecord


class ImportedHandIngestionService:
    """Append parsed candidates without overwriting approved or audit state.

    The repository operation is a read-classify-write transaction. Callers must
    hold identity-exclusive serialization for its entire duration; the local
    production composition does so through ``PlayerWorkspace`` record locks.
    """

    def __init__(
        self,
        *,
        store: ImportedHandRepository,
        conflict_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._conflict_id_factory = conflict_id_factory or (
            lambda: f"conflict-{uuid4()}"
        )

    def ingest(
        self,
        candidate: ParsedImportedHandCandidate,
    ) -> ImportedHandIngestionResult:
        raw, detection = _validated_candidate(candidate)
        identity = raw.identity
        resolution = self._store.resolve_reimport(
            identity,
            raw,
            candidate_detection=detection,
        )
        existing = self._store.find(identity)
        if existing is not None and existing.lifecycle.status in {
            "deleted",
            "deletion_pending",
        }:
            raise ImportedHandIngestionBlocked(
                "a deleted or deletion-pending hand requires an explicit"
                " lifecycle reimport operation"
            )
        if existing is not None:
            duplicate = _duplicate_import_result(
                resolution.record_key,
                existing,
                raw,
                detection,
            )
            if duplicate is not None:
                return duplicate
            _require_append_chronology(existing, raw)

        if resolution.disposition == "new_identity":
            record = _new_or_empty_record(existing, raw, detection)
            self._store.save(resolution.record_key, record)
            return ImportedHandIngestionResult(
                record_key=resolution.record_key,
                disposition="created_pending_review",
                record=record,
            )

        assert existing is not None
        if resolution.disposition == "exact_reimport":
            assert resolution.existing_raw_source_id is not None
            record = _append_exact_reimport(
                existing,
                raw,
                detection,
                target_raw_source_id=resolution.existing_raw_source_id,
            )
            disposition: IngestionDisposition = "recorded_exact_reimport"
        else:
            record = _append_identity_conflict(
                existing,
                raw,
                detection,
                conflict_id=self._conflict_id_factory(),
            )
            disposition = "recorded_identity_conflict"
        self._store.save(resolution.record_key, record)
        return ImportedHandIngestionResult(
            record_key=resolution.record_key,
            disposition=disposition,
            record=record,
        )


def _validated_candidate(
    candidate: ParsedImportedHandCandidate,
) -> tuple[RawHandHistory, DetectedImportedHand]:
    raw = RawHandHistory.model_validate(candidate.raw.model_dump(mode="python"))
    detection = DetectedImportedHand.model_validate(
        candidate.detection.model_dump(mode="python")
    )
    if detection.raw_source_id != raw.raw_source_id:
        raise ImportedHandIngestionError(
            "candidate detection must reference its candidate raw source"
        )
    if detection.state.identity != raw.identity:
        raise ImportedHandIngestionError(
            "candidate raw and detected state must share one stable identity"
        )
    if detection.state.chronology != raw.chronology:
        raise ImportedHandIngestionError(
            "candidate raw and detected state must share source chronology"
        )
    if raw.reimports:
        raise ImportedHandIngestionError(
            "an adapter candidate cannot pre-author retained reimport audit"
        )
    if raw.initial_detected_semantic_sha256 is not None:
        raise ImportedHandIngestionError(
            "an adapter candidate cannot pre-author a retained semantic binding"
        )
    return raw, detection


def _duplicate_import_result(
    record_key: str,
    record: ImportedHandRecord,
    candidate: RawHandHistory,
    candidate_detection: DetectedImportedHand,
) -> ImportedHandIngestionResult | None:
    import_id = candidate.provenance.import_id
    candidate_semantic_sha256 = detected_imported_hand_semantic_sha256(
        candidate_detection.state
    )
    for raw in record.raw_sources:
        if raw.provenance.import_id == import_id:
            if (
                raw.raw_source_id != candidate.raw_source_id
                or raw.chronology != candidate.chronology
                or raw.provenance != candidate.provenance
                or raw.content_sha256 != candidate.content_sha256
            ):
                raise ImportedHandImportIdConflict(
                    "an import id is already bound to different source evidence"
                )
            if (
                _initial_semantic_fingerprint(record, raw)
                != candidate_semantic_sha256
            ):
                raise ImportedHandImportIdConflict(
                    "an import retry changed the detected hand meaning"
                )
            return ImportedHandIngestionResult(
                record_key=record_key,
                disposition="duplicate_request",
                record=record,
            )
        for reimport in raw.reimports:
            if reimport.provenance.import_id != import_id:
                continue
            if (
                reimport.raw_source_id != candidate.raw_source_id
                or reimport.chronology != candidate.chronology
                or reimport.provenance != candidate.provenance
                or raw.content_sha256 != candidate.content_sha256
            ):
                raise ImportedHandImportIdConflict(
                    "an import id is already bound to different source evidence"
                )
            if (
                reimport.detected_semantic_sha256
                != candidate_semantic_sha256
            ):
                raise ImportedHandImportIdConflict(
                    "an import retry changed the detected hand meaning"
                )
            return ImportedHandIngestionResult(
                record_key=record_key,
                disposition="duplicate_request",
                record=record,
            )
    return None


def _require_append_chronology(
    record: ImportedHandRecord,
    candidate: RawHandHistory,
) -> None:
    if not record.raw_sources:
        return
    latest_imported_at = max(
        occurrence.provenance.imported_at
        for raw in record.raw_sources
        for occurrence in (raw, *raw.reimports)
    )
    if candidate.provenance.imported_at < latest_imported_at:
        raise ImportedHandIngestionError(
            "a new import occurrence cannot precede the latest retained import"
        )


def _initial_semantic_fingerprint(
    record: ImportedHandRecord,
    raw: RawHandHistory,
) -> str:
    if raw.initial_detected_semantic_sha256 is not None:
        return raw.initial_detected_semantic_sha256
    retained_fingerprints = {
        detected_imported_hand_semantic_sha256(detection.state)
        for detection in record.detections
        if detection.raw_source_id == raw.raw_source_id
    }
    if len(retained_fingerprints) != 1:
        raise ImportedHandIngestionError(
            "legacy raw source has no unambiguous initial semantic binding"
        )
    return next(iter(retained_fingerprints))


def _bind_initial_semantic_fingerprint(
    raw: RawHandHistory,
    semantic_sha256: str,
) -> RawHandHistory:
    return RawHandHistory.model_validate(
        {
            **raw.model_dump(mode="python"),
            "initial_detected_semantic_sha256": semantic_sha256,
        }
    )


def _new_or_empty_record(
    existing: ImportedHandRecord | None,
    raw: RawHandHistory,
    detection: DetectedImportedHand,
) -> ImportedHandRecord:
    raw = _bind_initial_semantic_fingerprint(
        raw,
        detected_imported_hand_semantic_sha256(detection.state),
    )
    changed_at = max(raw.provenance.imported_at, detection.detected_at)
    if existing is None:
        return ImportedHandRecord(
            identity=raw.identity,
            raw_sources=[raw],
            detections=[detection],
            lifecycle=ImportedHandLifecycle(
                status="pending_review",
                changed_at=changed_at,
            ),
        )
    if existing.raw_sources or existing.detections:
        raise ImportedHandIngestionError(
            "new-identity classification cannot replace retained source evidence"
        )
    return _updated_record(
        existing,
        raw_sources=[raw],
        detections=[detection],
        changed_at=changed_at,
    )


def _append_exact_reimport(
    existing: ImportedHandRecord,
    candidate: RawHandHistory,
    candidate_detection: DetectedImportedHand,
    *,
    target_raw_source_id: str,
) -> ImportedHandRecord:
    candidate_semantic_sha256 = detected_imported_hand_semantic_sha256(
        candidate_detection.state
    )
    occurrence = RawHandReimport(
        raw_source_id=candidate.raw_source_id,
        chronology=candidate.chronology,
        provenance=candidate.provenance,
        detected_semantic_sha256=candidate_semantic_sha256,
    )
    updated_sources: list[RawHandHistory] = []
    found = False
    for raw in existing.raw_sources:
        if raw.raw_source_id != target_raw_source_id:
            updated_sources.append(raw)
            continue
        found = True
        retained_raw = (
            raw
            if raw.initial_detected_semantic_sha256 is not None
            else _bind_initial_semantic_fingerprint(
                raw,
                _initial_semantic_fingerprint(existing, raw),
            )
        )
        updated_sources.append(
            RawHandHistory.model_validate(
                {
                    **retained_raw.model_dump(mode="python"),
                    "reimports": [*retained_raw.reimports, occurrence],
                }
            )
        )
    if not found:
        raise ImportedHandIngestionError(
            "exact reimport target is not retained by the imported hand"
        )
    return _updated_record(
        existing,
        raw_sources=updated_sources,
        changed_at=candidate.provenance.imported_at,
    )


def _append_identity_conflict(
    existing: ImportedHandRecord,
    candidate_raw: RawHandHistory,
    candidate_detection: DetectedImportedHand,
    *,
    conflict_id: str,
) -> ImportedHandRecord:
    matching_raw = next(
        (
            raw
            for raw in existing.raw_sources
            if raw.content_sha256 == candidate_raw.content_sha256
        ),
        None,
    )
    raw_sources = list(existing.raw_sources)
    detection = candidate_detection
    if matching_raw is None:
        raw_sources.append(
            _bind_initial_semantic_fingerprint(
                candidate_raw,
                detected_imported_hand_semantic_sha256(
                    candidate_detection.state
                ),
            )
        )
        conflict_raw_source_ids = [raw.raw_source_id for raw in raw_sources]
    else:
        raw_sources = _append_occurrence_to_sources(
            raw_sources,
            candidate_raw,
            candidate_detection,
            target_raw_source_id=matching_raw.raw_source_id,
            target_initial_semantic_sha256=_initial_semantic_fingerprint(
                existing,
                matching_raw,
            ),
        )
        detection = _remap_detection_raw_source(
            candidate_detection,
            target_raw_source_id=matching_raw.raw_source_id,
        )
        conflict_raw_source_ids = [matching_raw.raw_source_id]

    detections = [*existing.detections, detection]
    conflict_detection_ids = [
        item.detection_id
        for item in detections
        if item.raw_source_id in conflict_raw_source_ids
    ]
    conflict = ImportConflict(
        conflict_id=conflict_id,
        raw_source_ids=conflict_raw_source_ids,
        detected_ids=conflict_detection_ids,
        active_canonical_revision_at_creation=(
            existing.lifecycle.active_canonical_revision
        ),
    )
    return _updated_record(
        existing,
        raw_sources=raw_sources,
        detections=detections,
        conflicts=[*existing.conflicts, conflict],
        changed_at=max(
            candidate_raw.provenance.imported_at,
            candidate_detection.detected_at,
        ),
    )


def _append_occurrence_to_sources(
    sources: list[RawHandHistory],
    candidate: RawHandHistory,
    candidate_detection: DetectedImportedHand,
    *,
    target_raw_source_id: str,
    target_initial_semantic_sha256: str,
) -> list[RawHandHistory]:
    candidate_semantic_sha256 = detected_imported_hand_semantic_sha256(
        candidate_detection.state
    )
    occurrence = RawHandReimport(
        raw_source_id=candidate.raw_source_id,
        chronology=candidate.chronology,
        provenance=candidate.provenance,
        detected_semantic_sha256=candidate_semantic_sha256,
    )
    updated_sources: list[RawHandHistory] = []
    for raw in sources:
        if raw.raw_source_id != target_raw_source_id:
            updated_sources.append(raw)
            continue
        retained_raw = (
            raw
            if raw.initial_detected_semantic_sha256 is not None
            else _bind_initial_semantic_fingerprint(
                raw,
                target_initial_semantic_sha256,
            )
        )
        updated_sources.append(
            RawHandHistory.model_validate(
                {
                    **retained_raw.model_dump(mode="python"),
                    "reimports": [*retained_raw.reimports, occurrence],
                }
            )
        )
    return updated_sources


def _remap_detection_raw_source(
    detection: DetectedImportedHand,
    *,
    target_raw_source_id: str,
) -> DetectedImportedHand:
    payload = detection.model_dump(mode="python")
    source_raw_source_id = detection.raw_source_id

    def remap(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: (
                    target_raw_source_id
                    if key == "raw_source_id" and item == source_raw_source_id
                    else remap(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [remap(item) for item in value]
        return value

    remapped = remap(payload)
    assert isinstance(remapped, dict)
    remapped["raw_source_id"] = target_raw_source_id
    state = remapped["state"]
    assert isinstance(state, dict)
    chronology = state["chronology"]
    assert isinstance(chronology, dict)
    chronology["source_file_id"] = target_raw_source_id
    remapped["content_sha256"] = imported_hand_state_sha256(
        ImportedHandState.model_validate(state)
    )
    return DetectedImportedHand.model_validate(remapped)


def _updated_record(
    record: ImportedHandRecord,
    *,
    raw_sources: list[RawHandHistory] | None = None,
    detections: list[DetectedImportedHand] | None = None,
    conflicts: list[ImportConflict] | None = None,
    changed_at: datetime,
) -> ImportedHandRecord:
    lifecycle_payload = record.lifecycle.model_dump(mode="python")
    lifecycle_payload["changed_at"] = max(
        record.lifecycle.changed_at,
        changed_at,
    )
    return ImportedHandRecord(
        identity=record.identity,
        raw_sources=raw_sources if raw_sources is not None else record.raw_sources,
        detections=detections if detections is not None else record.detections,
        conflicts=conflicts if conflicts is not None else record.conflicts,
        canonical_revisions=record.canonical_revisions,
        lifecycle=ImportedHandLifecycle.model_validate(lifecycle_payload),
        deletion_receipt=record.deletion_receipt,
    )
