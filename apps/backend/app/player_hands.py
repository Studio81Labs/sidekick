"""Read-only projections for player-local imported-hand records."""

from __future__ import annotations

from bisect import bisect_right
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.domain.imported_hands import (
    DeletionReceipt,
    ImportConflict,
    ImportedHandLifecycle,
    ImportedHandRecord,
    ImportProvenance,
    SourceChronology,
    UserCorrection,
)
from app.storage.imported_hand_store import FileImportedHandStore


DEFAULT_PLAYER_HAND_PAGE_SIZE = 25
MAX_PLAYER_HAND_PAGE_SIZE = 100


class PlayerHandProjection(BaseModel):
    """Strict local-API projection base."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PlayerHandIdentity(PlayerHandProjection):
    site: str
    source_hand_id: str


class PlayerHandSummary(PlayerHandProjection):
    record_key: str
    identity: PlayerHandIdentity | None
    played_at: datetime | None
    lifecycle_status: str
    lifecycle_changed_at: datetime
    active_canonical_revision: int | None
    learning_eligible: bool
    deletion_generation: int
    raw_source_count: int
    detection_count: int
    warning_count: int
    unresolved_conflict_count: int
    canonical_revision_count: int


class PlayerHandList(PlayerHandProjection):
    items: list[PlayerHandSummary]
    next_cursor: str | None


class PlayerRawSourceAudit(PlayerHandProjection):
    raw_source_id: str
    chronology: SourceChronology
    provenance: ImportProvenance
    content_sha256: str


class PlayerSourceEvidenceAudit(PlayerHandProjection):
    raw_source_id: str
    line_start: int | None
    line_end: int | None
    marker: str | None


class PlayerDetectedFieldEvidenceAudit(PlayerHandProjection):
    confidence: Decimal | None
    evidence: list[PlayerSourceEvidenceAudit]
    warnings: list[str]


class PlayerDetectionAudit(PlayerHandProjection):
    detection_id: str
    raw_source_id: str
    detector_id: str
    detector_version: str
    detected_at: datetime
    field_evidence: dict[str, PlayerDetectedFieldEvidenceAudit]
    warnings: list[str]
    content_sha256: str


class PlayerCanonicalRevisionAudit(PlayerHandProjection):
    revision: int
    detection_id: str
    approved_at: datetime
    corrections: list[UserCorrection]


class PlayerHandDetail(PlayerHandProjection):
    summary: PlayerHandSummary
    lifecycle: ImportedHandLifecycle
    raw_sources: list[PlayerRawSourceAudit]
    detections: list[PlayerDetectionAudit]
    conflicts: list[ImportConflict]
    canonical_revisions: list[PlayerCanonicalRevisionAudit]
    deletion_receipt: DeletionReceipt | None


def _summary(record_key: str, record: ImportedHandRecord) -> PlayerHandSummary:
    played_at = max(
        (
            raw.chronology.played_at
            for raw in record.raw_sources
            if raw.chronology.played_at is not None
        ),
        default=None,
    )
    warning_count = sum(
        len(detection.warnings)
        + sum(len(evidence.warnings) for evidence in detection.field_evidence.values())
        for detection in record.detections
    )
    identity = (
        PlayerHandIdentity(
            site=record.identity.site,
            source_hand_id=record.identity.source_hand_id,
        )
        if record.identity is not None
        else None
    )
    return PlayerHandSummary(
        record_key=record_key,
        identity=identity,
        played_at=played_at,
        lifecycle_status=record.lifecycle.status,
        lifecycle_changed_at=record.lifecycle.changed_at,
        active_canonical_revision=record.lifecycle.active_canonical_revision,
        learning_eligible=record.lifecycle.learning_eligible,
        deletion_generation=record.lifecycle.deletion_generation,
        raw_source_count=len(record.raw_sources),
        detection_count=len(record.detections),
        warning_count=warning_count,
        unresolved_conflict_count=sum(
            conflict.status == "unresolved" for conflict in record.conflicts
        ),
        canonical_revision_count=len(record.canonical_revisions),
    )


def list_player_hands(
    store: FileImportedHandStore,
    *,
    limit: int = DEFAULT_PLAYER_HAND_PAGE_SIZE,
    cursor: str | None = None,
) -> PlayerHandList:
    """Return one deterministic, bounded page without exposing raw histories."""

    keys = store.list_keys()
    start = bisect_right(keys, cursor) if cursor is not None else 0
    page_keys = keys[start : start + limit + 1]
    has_more = len(page_keys) > limit
    visible_keys = page_keys[:limit]
    items = [_summary(record_key, store.get(record_key)) for record_key in visible_keys]
    return PlayerHandList(
        items=items,
        next_cursor=visible_keys[-1] if has_more else None,
    )


def get_player_hand(
    store: FileImportedHandStore,
    record_key: str,
) -> PlayerHandDetail:
    """Return review metadata for one record while keeping raw text private."""

    record = store.get(record_key)
    return PlayerHandDetail(
        summary=_summary(record_key, record),
        lifecycle=record.lifecycle,
        raw_sources=[
            PlayerRawSourceAudit(
                raw_source_id=raw.raw_source_id,
                chronology=raw.chronology,
                provenance=raw.provenance,
                content_sha256=raw.content_sha256,
            )
            for raw in record.raw_sources
        ],
        detections=[
            PlayerDetectionAudit(
                detection_id=detection.detection_id,
                raw_source_id=detection.raw_source_id,
                detector_id=detection.detector_id,
                detector_version=detection.detector_version,
                detected_at=detection.detected_at,
                field_evidence={
                    pointer: PlayerDetectedFieldEvidenceAudit(
                        confidence=field.confidence,
                        evidence=[
                            PlayerSourceEvidenceAudit(
                                raw_source_id=evidence.raw_source_id,
                                line_start=evidence.line_start,
                                line_end=evidence.line_end,
                                marker=evidence.marker,
                            )
                            for evidence in field.evidence
                        ],
                        warnings=field.warnings,
                    )
                    for pointer, field in detection.field_evidence.items()
                },
                warnings=detection.warnings,
                content_sha256=detection.content_sha256,
            )
            for detection in record.detections
        ],
        conflicts=record.conflicts,
        canonical_revisions=[
            PlayerCanonicalRevisionAudit(
                revision=revision.revision,
                detection_id=revision.detection_id,
                approved_at=revision.approved_at,
                corrections=revision.corrections,
            )
            for revision in record.canonical_revisions
        ],
        deletion_receipt=record.deletion_receipt,
    )
