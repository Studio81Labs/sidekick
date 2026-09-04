"""Conflict-safe ingestion of already-parsed local hand-history candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Literal
from uuid import uuid4

from app.application.imported_hand_ports import ImportedHandRepository
from app.domain.imported_hands import (
    DetectedImportedHand,
    ImportConflict,
    ImportProvenance,
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


class AuthorizedHandReimportConflict(ImportedHandIngestionError):
    """A candidate cannot cross the retained deletion boundary as requested."""


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


AuthorizedReimportDisposition = Literal[
    "restored_pending_review",
    "duplicate_request",
]


@dataclass(frozen=True)
class AuthorizedHandReimportResult:
    """One explicit deletion-boundary replacement or its exact retry."""

    record_key: str
    disposition: AuthorizedReimportDisposition
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
            if any(
                item.detection_id == detection.detection_id
                for item in existing.detections
            ):
                raise ImportedHandIngestionError(
                    "a detection id is already retained for another import"
                )
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


class AuthorizedHandReimportService:
    """Replace one deleted incarnation with fresh, unapproved parser evidence.

    Callers must hold the same identity-exclusive thread, process, and data
    locks as ordinary ingestion for the complete retry/precondition/cascade
    sequence. The candidate provenance is the durable authorization-attempt
    binding: exact retries keep the first server timestamps, while another
    candidate reusing that import ID fails closed.
    """

    def __init__(self, *, store: ImportedHandRepository) -> None:
        self._store = store

    def retry(
        self,
        record_key: str,
        candidate: ParsedImportedHandCandidate,
        *,
        expected_deletion_generation: int,
    ) -> AuthorizedHandReimportResult | None:
        """Recognize only the fresh successor produced by this exact request."""

        raw, detection = _validated_candidate(candidate)
        resolution = self._store.resolve_reimport(
            raw.identity,
            raw,
            candidate_detection=detection,
        )
        if resolution.record_key != record_key:
            raise AuthorizedHandReimportConflict(
                "the parsed hand identity does not match the selected tombstone"
            )
        current = self._store.get(record_key)
        duplicate = _duplicate_import_result(
            record_key,
            current,
            raw,
            detection,
        )
        if duplicate is None:
            return None
        if not _is_authorized_reimport_successor(
            current,
            expected_deletion_generation=expected_deletion_generation,
        ):
            raise AuthorizedHandReimportConflict(
                "this reimport request ID is already bound outside the expected"
                " deletion generation"
            )
        return AuthorizedHandReimportResult(
            record_key=record_key,
            disposition="duplicate_request",
            record=current,
        )

    def reimport(
        self,
        record_key: str,
        candidate: ParsedImportedHandCandidate,
        *,
        expected: ImportedHandRecord,
        changed_at: datetime,
    ) -> AuthorizedHandReimportResult:
        """Publish a new pending-review incarnation and purge old artifacts."""

        raw, detection = _validated_candidate(candidate)
        resolution = self._store.resolve_reimport(
            raw.identity,
            raw,
            candidate_detection=detection,
        )
        if resolution.record_key != record_key:
            raise AuthorizedHandReimportConflict(
                "the parsed hand identity does not match the selected tombstone"
            )
        if expected.lifecycle.status not in {"deleted", "deletion_pending"}:
            raise AuthorizedHandReimportConflict(
                "only a deleted or deletion-pending hand can be explicitly reimported"
            )

        bound_raw = _bind_initial_detection(raw, detection)
        successor_changed_at = max(
            changed_at,
            raw.provenance.imported_at,
            detection.detected_at,
        )
        if successor_changed_at <= expected.lifecycle.changed_at:
            try:
                successor_changed_at = expected.lifecycle.changed_at + timedelta(
                    microseconds=1
                )
            except OverflowError as exc:
                raise AuthorizedHandReimportConflict(
                    "the hand lifecycle timestamp cannot advance beyond its stored value"
                ) from exc
        successor = ImportedHandRecord(
            identity=raw.identity,
            raw_sources=[bound_raw],
            detections=[detection],
            lifecycle=ImportedHandLifecycle(
                status="pending_review",
                deletion_generation=(
                    expected.lifecycle.deletion_generation + 1
                ),
                changed_at=successor_changed_at,
                reason="authorized reimport",
            ),
        )

        with self._store.begin_cascade(
            record_key,
            operation="authorized_reimport",
        ) as cascade:
            if self._store.get(record_key) != expected:
                raise AuthorizedHandReimportConflict(
                    "the retained hand changed before reimport publication"
                )
            artifacts = self._store.list_decision_artifacts(record_key)
            cascade.stage_record(successor)
            for _revision, _generation, filename in artifacts:
                cascade.stage_decisions_delete(filename)
        return AuthorizedHandReimportResult(
            record_key=record_key,
            disposition="restored_pending_review",
            record=successor,
        )


def _is_authorized_reimport_successor(
    record: ImportedHandRecord,
    *,
    expected_deletion_generation: int,
) -> bool:
    return (
        record.lifecycle.status == "pending_review"
        and record.lifecycle.reason == "authorized reimport"
        and record.lifecycle.deletion_generation
        == expected_deletion_generation + 1
        and len(record.raw_sources) == 1
        and len(record.detections) == 1
        and not record.conflicts
        and not record.canonical_revisions
        and record.deletion_receipt is None
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
    if detection.detected_at < raw.provenance.imported_at:
        raise ImportedHandIngestionError(
            "candidate detection cannot precede its raw source import"
        )
    if raw.reimports:
        raise ImportedHandIngestionError(
            "an adapter candidate cannot pre-author retained reimport audit"
        )
    if (
        raw.initial_detection_id is not None
        or raw.initial_detected_semantic_sha256 is not None
    ):
        raise ImportedHandIngestionError(
            "an adapter candidate cannot pre-author a retained detection binding"
        )
    return raw, detection


def _duplicate_import_result(
    record_key: str,
    record: ImportedHandRecord,
    candidate: RawHandHistory,
    candidate_detection: DetectedImportedHand,
) -> ImportedHandIngestionResult | None:
    import_id = candidate.provenance.import_id
    for raw in record.raw_sources:
        if raw.provenance.import_id == import_id:
            if (
                raw.raw_source_id != candidate.raw_source_id
                or raw.chronology != candidate.chronology
                or not _same_retry_provenance(
                    raw.provenance,
                    candidate.provenance,
                )
                or raw.content_sha256 != candidate.content_sha256
            ):
                raise ImportedHandImportIdConflict(
                    "an import id is already bound to different source evidence"
                )
            if not _same_retry_detection(
                _initial_detection(record, raw),
                candidate_detection,
            ):
                raise ImportedHandImportIdConflict(
                    "an import retry changed the detected hand meaning or audit evidence"
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
                or not _same_retry_provenance(
                    reimport.provenance,
                    candidate.provenance,
                )
                or raw.content_sha256 != candidate.content_sha256
            ):
                raise ImportedHandImportIdConflict(
                    "an import id is already bound to different source evidence"
                )
            retained_detection = _retained_detection(
                record,
                reimport.detection_id,
            )
            comparable_candidate = (
                candidate_detection
                if retained_detection.raw_source_id == candidate.raw_source_id
                else _remap_detection_raw_source(
                    candidate_detection,
                    target_raw_source_id=retained_detection.raw_source_id,
                )
            )
            if not _same_retry_detection(
                retained_detection,
                comparable_candidate,
            ):
                raise ImportedHandImportIdConflict(
                    "an import retry changed the detected hand meaning or audit evidence"
                )
            return ImportedHandIngestionResult(
                record_key=record_key,
                disposition="duplicate_request",
                record=record,
            )
    return None


def _same_retry_provenance(
    retained: ImportProvenance,
    candidate: ImportProvenance,
) -> bool:
    """Keep the first server observation time authoritative on request replay."""

    return retained == candidate.model_copy(
        update={"imported_at": retained.imported_at}
    )


def _same_retry_detection(
    retained: DetectedImportedHand,
    candidate: DetectedImportedHand,
) -> bool:
    """Compare deterministic recognition while retaining its first timestamp."""

    return retained == candidate.model_copy(
        update={"detected_at": retained.detected_at}
    )


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


def _retained_detection(
    record: ImportedHandRecord,
    detection_id: str,
) -> DetectedImportedHand:
    matches = [
        detection
        for detection in record.detections
        if detection.detection_id == detection_id
    ]
    if len(matches) != 1:
        raise ImportedHandIngestionError(
            "retained import has no unique detection audit binding"
        )
    return matches[0]


def _initial_detection(
    record: ImportedHandRecord,
    raw: RawHandHistory,
) -> DetectedImportedHand:
    if raw.initial_detection_id is not None:
        return _retained_detection(record, raw.initial_detection_id)
    matches = [
        detection
        for detection in record.detections
        if detection.raw_source_id == raw.raw_source_id
        and (
            raw.initial_detected_semantic_sha256 is None
            or detected_imported_hand_semantic_sha256(detection.state)
            == raw.initial_detected_semantic_sha256
        )
    ]
    if len(matches) != 1:
        raise ImportedHandIngestionError(
            "legacy raw source has no unambiguous initial detection binding"
        )
    return matches[0]


def _bind_initial_detection(
    raw: RawHandHistory,
    detection: DetectedImportedHand,
) -> RawHandHistory:
    return RawHandHistory.model_validate(
        {
            **raw.model_dump(mode="python"),
            "initial_detection_id": detection.detection_id,
            "initial_detected_semantic_sha256": (
                detected_imported_hand_semantic_sha256(detection.state)
            ),
        }
    )


def _new_or_empty_record(
    existing: ImportedHandRecord | None,
    raw: RawHandHistory,
    detection: DetectedImportedHand,
) -> ImportedHandRecord:
    raw = _bind_initial_detection(raw, detection)
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
        detection_id=candidate_detection.detection_id,
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
            if raw.initial_detection_id is not None
            else _bind_initial_detection(
                raw,
                _initial_detection(existing, raw),
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
        detections=[*existing.detections, candidate_detection],
        changed_at=max(
            candidate.provenance.imported_at,
            candidate_detection.detected_at,
        ),
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
            _bind_initial_detection(
                candidate_raw,
                candidate_detection,
            )
        )
        conflict_raw_source_ids = [raw.raw_source_id for raw in raw_sources]
    else:
        raw_sources = _append_occurrence_to_sources(
            raw_sources,
            candidate_raw,
            candidate_detection,
            target_raw_source_id=matching_raw.raw_source_id,
            target_initial_detection=_initial_detection(
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
    target_initial_detection: DetectedImportedHand,
) -> list[RawHandHistory]:
    candidate_semantic_sha256 = detected_imported_hand_semantic_sha256(
        candidate_detection.state
    )
    occurrence = RawHandReimport(
        raw_source_id=candidate.raw_source_id,
        chronology=candidate.chronology,
        provenance=candidate.provenance,
        detection_id=candidate_detection.detection_id,
        detected_semantic_sha256=candidate_semantic_sha256,
    )
    updated_sources: list[RawHandHistory] = []
    for raw in sources:
        if raw.raw_source_id != target_raw_source_id:
            updated_sources.append(raw)
            continue
        retained_raw = (
            raw
            if raw.initial_detection_id is not None
            else _bind_initial_detection(
                raw,
                target_initial_detection,
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
    if changed_at > record.lifecycle.changed_at:
        lifecycle_payload["changed_at"] = changed_at
    else:
        try:
            lifecycle_payload["changed_at"] = (
                record.lifecycle.changed_at + timedelta(microseconds=1)
            )
        except OverflowError as exc:
            raise ImportedHandIngestionError(
                "the imported hand lifecycle timestamp cannot advance"
            ) from exc
    return ImportedHandRecord(
        identity=record.identity,
        raw_sources=raw_sources if raw_sources is not None else record.raw_sources,
        detections=detections if detections is not None else record.detections,
        conflicts=conflicts if conflicts is not None else record.conflicts,
        canonical_revisions=record.canonical_revisions,
        lifecycle=ImportedHandLifecycle.model_validate(lifecycle_payload),
        deletion_receipt=record.deletion_receipt,
    )
