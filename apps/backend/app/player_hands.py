"""Player-local imported-hand API projections and lifecycle input."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Literal, Self, cast

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    ValidationError,
    model_validator,
)

from app.domain.imported_hands import (
    DetectedImportedHand,
    DeletionReceipt,
    HandDecisionExtraction,
    ImportConflict,
    ImportedHandState,
    ImportedHandLifecycle,
    ImportedHandRecord,
    ImportProvenance,
    SourceChronology,
)
from app.storage.imported_hand_store import (
    FileImportedHandStore,
    ImportedHandNotFoundError,
)


DEFAULT_PLAYER_HAND_PAGE_SIZE = 25
MAX_PLAYER_HAND_PAGE_SIZE = 100
REDACTED_SOURCE_EXCERPT = "[redacted source excerpt]"
UNREADABLE_HAND_DETAIL = "Stored imported hand record could not be read safely"
RECOVERY_PENDING_HAND_DETAIL = (
    "Stored imported hand record is unavailable until lifecycle recovery finishes"
)


class PlayerHandProjection(BaseModel):
    """Strict local-API projection base."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PlayerHandIdentity(PlayerHandProjection):
    namespace: str
    site: str
    source_hand_id: str


class PlayerHandSummary(PlayerHandProjection):
    record_key: str
    record_version: str
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


class PlayerHandReadError(PlayerHandProjection):
    record_key: str
    detail: str = UNREADABLE_HAND_DETAIL


class PlayerHandList(PlayerHandProjection):
    items: list[PlayerHandSummary]
    unreadable: list[PlayerHandReadError]
    next_cursor: str | None


class PlayerRawReimportAudit(PlayerHandProjection):
    raw_source_id: str
    chronology: SourceChronology
    provenance: ImportProvenance
    detection_id: str
    detected_semantic_sha256: str


class PlayerRawSourceAudit(PlayerHandProjection):
    raw_source_id: str
    chronology: SourceChronology
    provenance: ImportProvenance
    content_sha256: str
    reimports: list[PlayerRawReimportAudit]


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
    state: dict[str, JsonValue]
    field_evidence: dict[str, PlayerDetectedFieldEvidenceAudit]
    warnings: list[str]
    content_sha256: str
    approval_eligible: bool


class PlayerUserCorrectionAudit(PlayerHandProjection):
    field_pointer: str
    detected_value: JsonValue
    approved_value: JsonValue
    corrected_at: datetime
    reason: str | None


class PlayerCanonicalRevisionAudit(PlayerHandProjection):
    approval_id: str | None
    revision: int
    detection_id: str
    approved_at: datetime
    state: dict[str, JsonValue]
    corrections: list[PlayerUserCorrectionAudit]


class PlayerHandDetail(PlayerHandProjection):
    summary: PlayerHandSummary
    lifecycle: ImportedHandLifecycle
    raw_sources: list[PlayerRawSourceAudit]
    detections: list[PlayerDetectionAudit]
    conflicts: list[ImportConflict]
    canonical_revisions: list[PlayerCanonicalRevisionAudit]
    deletion_receipt: DeletionReceipt | None


class PlayerActiveHandDecisions(PlayerHandProjection):
    """Sanitized current decision artifact for one retained player hand."""

    record_key: str
    record_version: str
    extraction: dict[str, JsonValue]


PlayerHandCloseAction = Literal["withdraw", "reject"]
PlayerHandConflictResolution = Literal["keep_active", "use_source"]
PlayerRequestId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        ),
        strict=True,
    ),
]
PlayerRecordVersion = Annotated[
    str,
    StringConstraints(pattern=r"^[a-f0-9]{64}$", strict=True),
]


class PlayerHandCloseRequest(PlayerHandProjection):
    """Stale-write precondition and player reason for one approval close."""

    reason: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=256,
            strict=True,
        ),
    ]
    expected_active_canonical_revision: int = Field(ge=1, strict=True)
    expected_deletion_generation: int = Field(ge=0, strict=True)
    expected_lifecycle_changed_at: AwareDatetime


class PlayerHandDeleteRequest(PlayerHandProjection):
    """Exact retained-record precondition for one permanent deletion."""

    request_id: PlayerRequestId
    reason: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=256,
            strict=True,
        ),
    ]
    expected_record_version: PlayerRecordVersion
    expected_lifecycle_status: Literal[
        "pending_review",
        "active",
        "withdrawn",
        "rejected",
        "deletion_pending",
    ]
    expected_active_canonical_revision: int | None = Field(
        default=None,
        ge=1,
        strict=True,
    )
    expected_deletion_generation: int = Field(ge=0, strict=True)
    expected_lifecycle_changed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_active_revision_precondition(self) -> Self:
        if (
            self.expected_lifecycle_status == "active"
            and self.expected_active_canonical_revision is None
        ):
            raise ValueError("active deletion precondition requires active revision")
        if (
            self.expected_lifecycle_status != "active"
            and self.expected_active_canonical_revision is not None
        ):
            raise ValueError(
                "inactive deletion precondition cannot select an active revision"
            )
        return self


class PlayerHandReimportRequest(PlayerHandProjection):
    """Exact deletion-incarnation precondition for an authorized reimport."""

    request_id: PlayerRequestId
    expected_record_version: PlayerRecordVersion
    expected_lifecycle_status: Literal["deleted", "deletion_pending"]
    expected_deletion_generation: int = Field(ge=1, strict=True)
    expected_lifecycle_changed_at: AwareDatetime


class PlayerHandApprovalRequest(PlayerHandProjection):
    """Explicit reviewed state and exact retained-record precondition."""

    request_id: PlayerRequestId
    detection_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=160,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]*$",
            strict=True,
        ),
    ]
    approved_state: dict[str, JsonValue]
    correction_reason: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=500,
            strict=True,
        ),
    ] | None = None
    expected_record_version: PlayerRecordVersion
    expected_lifecycle_status: Literal[
        "pending_review",
        "active",
        "withdrawn",
        "rejected",
    ]
    expected_active_canonical_revision: int | None = Field(
        default=None,
        ge=1,
        strict=True,
    )
    expected_canonical_revision_count: int = Field(ge=0, strict=True)
    expected_deletion_generation: int = Field(ge=0, strict=True)
    expected_lifecycle_changed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_revision_precondition(self) -> Self:
        active_revision = self.expected_active_canonical_revision
        revision_count = self.expected_canonical_revision_count
        if self.expected_lifecycle_status == "active":
            if active_revision is None or active_revision != revision_count:
                raise ValueError(
                    "active approval precondition requires the latest active revision"
                )
        elif active_revision is not None:
            raise ValueError(
                "inactive approval precondition cannot select an active revision"
            )
        if (
            self.expected_lifecycle_status in {"withdrawn", "rejected"}
            and revision_count == 0
        ):
            raise ValueError(
                "withdrawn or rejected approval precondition requires retained revisions"
            )
        return self


PlayerHandReviewPreviewErrorCode = Literal[
    "missing_value",
    "unexpected_field",
    "invalid_type",
    "invalid_value",
    "private_source_excerpt",
    "correction_reason_required",
]


class PlayerHandReviewPreviewRequest(PlayerHandApprovalRequest):
    """One stateless review validation request.

    This deliberately carries the same reviewed-state and exact-record
    precondition as approval. ``draft_revision`` is browser-local ordering
    information only: the workspace never retains it or creates an idempotency
    record for preview requests.
    """

    draft_revision: int = Field(ge=0, strict=True)


class PlayerHandReviewPreviewFieldError(PlayerHandProjection):
    """A safe, stable validation problem for one reviewed-state pointer."""

    pointer: str
    code: PlayerHandReviewPreviewErrorCode
    message: str


class PlayerHandReviewPreview(PlayerHandProjection):
    """Sanitized, non-persisted result of preparing a reviewed hand state."""

    schema_version: Literal["player-hand-review-preview/v1"] = (
        "player-hand-review-preview/v1"
    )
    request_id: PlayerRequestId
    draft_revision: int = Field(ge=0, strict=True)
    record_key: str
    record_version: PlayerRecordVersion
    detection_id: str
    valid: bool
    reviewed_state: dict[str, JsonValue] | None
    warnings: list[str]
    field_errors: list[PlayerHandReviewPreviewFieldError]

    @model_validator(mode="after")
    def validate_preview_result(self) -> Self:
        if self.valid:
            if self.reviewed_state is None or self.field_errors:
                raise ValueError(
                    "a valid review preview requires state and no field errors"
                )
        elif self.reviewed_state is not None or not self.field_errors:
            raise ValueError(
                "an invalid review preview requires field errors and no state"
            )
        return self


class PlayerHandConflictResolutionRequest(PlayerHandProjection):
    """Explicit source choice and exact retained-record precondition."""

    resolution: PlayerHandConflictResolution
    selected_raw_source_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=160,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]*$",
            strict=True,
        ),
    ]
    expected_record_version: PlayerRecordVersion
    expected_lifecycle_status: Literal[
        "pending_review",
        "active",
        "withdrawn",
        "rejected",
    ]
    expected_active_canonical_revision: int | None = Field(
        default=None,
        ge=1,
        strict=True,
    )
    expected_canonical_revision_count: int = Field(ge=0, strict=True)
    expected_deletion_generation: int = Field(ge=0, strict=True)
    expected_lifecycle_changed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_revision_precondition(self) -> Self:
        active_revision = self.expected_active_canonical_revision
        revision_count = self.expected_canonical_revision_count
        if self.expected_lifecycle_status == "active":
            if active_revision is None or active_revision != revision_count:
                raise ValueError(
                    "active conflict-resolution precondition requires the latest"
                    " active revision"
                )
        elif active_revision is not None:
            raise ValueError(
                "inactive conflict-resolution precondition cannot select an"
                " active revision"
            )
        if (
            self.expected_lifecycle_status in {"withdrawn", "rejected"}
            and revision_count == 0
        ):
            raise ValueError(
                "withdrawn or rejected conflict-resolution precondition requires"
                " retained revisions"
            )
        return self


def player_hand_record_version(record: ImportedHandRecord) -> str:
    """Return an opaque version over every retained field, including source."""

    return sha256(record.model_dump_json().encode("utf-8")).hexdigest()


def _summary(record_key: str, record: ImportedHandRecord) -> PlayerHandSummary:
    retained_revision = (
        record.canonical_revisions[-1] if record.canonical_revisions else None
    )
    played_at = (
        retained_revision.state.chronology.played_at
        if retained_revision is not None
        else max(
            (
                raw.chronology.played_at
                for raw in record.raw_sources
                if raw.chronology.played_at is not None
            ),
            default=None,
        )
    )
    warning_count = sum(
        len(detection.warnings)
        + sum(len(evidence.warnings) for evidence in detection.field_evidence.values())
        for detection in record.detections
    )
    identity = (
        PlayerHandIdentity(
            namespace=record.identity.namespace,
            site=record.identity.site,
            source_hand_id=record.identity.source_hand_id,
        )
        if record.identity is not None
        else None
    )
    return PlayerHandSummary(
        record_key=record_key,
        record_version=player_hand_record_version(record),
        identity=identity,
        played_at=played_at,
        lifecycle_status=record.lifecycle.status,
        lifecycle_changed_at=record.lifecycle.changed_at,
        active_canonical_revision=record.lifecycle.active_canonical_revision,
        learning_eligible=record.lifecycle.learning_eligible,
        deletion_generation=record.lifecycle.deletion_generation,
        raw_source_count=sum(1 + len(raw.reimports) for raw in record.raw_sources),
        detection_count=len(record.detections),
        warning_count=warning_count,
        unresolved_conflict_count=sum(
            conflict.status == "unresolved" for conflict in record.conflicts
        ),
        canonical_revision_count=len(record.canonical_revisions),
    )


def _without_evidence_excerpts(value: JsonValue) -> JsonValue:
    """Copy a validated JSON graph without raw source excerpt fields."""

    if isinstance(value, dict):
        return {
            key: _without_evidence_excerpts(item)
            for key, item in value.items()
            if key != "excerpt"
        }
    if isinstance(value, list):
        return [_without_evidence_excerpts(item) for item in value]
    return value


def sanitized_player_hand_state(
    state: ImportedHandState,
) -> dict[str, JsonValue]:
    """Return a player-visible state without retained raw-source excerpts."""

    sanitized = _without_evidence_excerpts(
        cast(JsonValue, state.model_dump(mode="json"))
    )
    if not isinstance(sanitized, dict):  # pragma: no cover - model invariant
        raise ValueError("imported hand state must serialize as an object")
    return cast(dict[str, JsonValue], sanitized)


def player_hand_review_warnings(detection: DetectedImportedHand) -> list[str]:
    """Keep the selected detection's existing review warnings visible.

    Warnings are already retained player-visible review metadata. We add their
    field pointer rather than a source excerpt so a preview can be reconciled
    with the audit detail without revealing raw hand text.
    """

    return [
        *detection.warnings,
        *(
            f"{pointer}: {warning}"
            for pointer, evidence in detection.field_evidence.items()
            for warning in evidence.warnings
        ),
    ]


def _sanitized_correction_value(
    field_pointer: str,
    value: JsonValue,
) -> JsonValue:
    """Redact a scalar correction when its validated pointer names an excerpt."""

    pointer_token = field_pointer.rsplit("/", 1)[-1]
    decoded_token = pointer_token.replace("~1", "/").replace("~0", "~")
    if decoded_token == "excerpt":
        return REDACTED_SOURCE_EXCERPT
    return _without_evidence_excerpts(value)


def list_player_hands(
    store: FileImportedHandStore,
    *,
    limit: int = DEFAULT_PLAYER_HAND_PAGE_SIZE,
    cursor: str | None = None,
    is_record_unavailable: Callable[[str], bool] | None = None,
) -> PlayerHandList:
    """Return one deterministic, bounded page without exposing raw histories."""

    keys = store.list_keys()
    start = bisect_right(keys, cursor) if cursor is not None else 0
    page_keys = keys[start : start + limit + 1]
    has_more = len(page_keys) > limit
    visible_keys = page_keys[:limit]
    items: list[PlayerHandSummary] = []
    unreadable: list[PlayerHandReadError] = []
    for record_key in visible_keys:
        if is_record_unavailable is not None and is_record_unavailable(record_key):
            unreadable.append(
                PlayerHandReadError(
                    record_key=record_key,
                    detail=RECOVERY_PENDING_HAND_DETAIL,
                )
            )
            continue
        try:
            summary = _summary(record_key, store.get(record_key))
        except (ImportedHandNotFoundError, OSError, ValidationError):
            unreadable.append(PlayerHandReadError(record_key=record_key))
            continue
        if is_record_unavailable is not None and is_record_unavailable(record_key):
            unreadable.append(
                PlayerHandReadError(
                    record_key=record_key,
                    detail=RECOVERY_PENDING_HAND_DETAIL,
                )
            )
        else:
            items.append(summary)
    return PlayerHandList(
        items=items,
        unreadable=unreadable,
        next_cursor=visible_keys[-1] if has_more else None,
    )


def get_player_hand(
    store: FileImportedHandStore,
    record_key: str,
) -> PlayerHandDetail:
    """Return review metadata for one record while keeping raw text private."""

    return project_player_hand(record_key, store.get(record_key))


def project_player_active_hand_decisions(
    record_key: str,
    record: ImportedHandRecord,
    extraction: HandDecisionExtraction,
) -> PlayerActiveHandDecisions:
    """Project current learning evidence without exposing source excerpts."""

    sanitized = _without_evidence_excerpts(extraction.model_dump(mode="json"))
    if not isinstance(sanitized, dict):  # pragma: no cover - model dump invariant
        raise ValueError("decision extraction must serialize as a JSON object")
    return PlayerActiveHandDecisions(
        record_key=record_key,
        record_version=player_hand_record_version(record),
        extraction=sanitized,
    )


def project_player_hand(
    record_key: str,
    record: ImportedHandRecord,
) -> PlayerHandDetail:
    """Project one already-serialized snapshot without rereading mutable storage."""

    approval_eligible_source_ids = {
        raw.raw_source_id for raw in record.raw_sources
    }
    return PlayerHandDetail(
        summary=_summary(record_key, record),
        lifecycle=record.lifecycle,
        raw_sources=[
            PlayerRawSourceAudit(
                raw_source_id=raw.raw_source_id,
                chronology=raw.chronology,
                provenance=raw.provenance,
                content_sha256=raw.content_sha256,
                reimports=[
                    PlayerRawReimportAudit(
                        raw_source_id=reimport.raw_source_id,
                        chronology=reimport.chronology,
                        provenance=reimport.provenance,
                        detection_id=reimport.detection_id,
                        detected_semantic_sha256=reimport.detected_semantic_sha256,
                    )
                    for reimport in raw.reimports
                ],
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
                state=cast(
                    dict[str, JsonValue],
                    _without_evidence_excerpts(
                        cast(JsonValue, detection.state.model_dump(mode="json"))
                    ),
                ),
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
                approval_eligible=detection.raw_source_id
                in approval_eligible_source_ids,
            )
            for detection in record.detections
        ],
        conflicts=record.conflicts,
        canonical_revisions=[
            PlayerCanonicalRevisionAudit(
                approval_id=revision.approval_id,
                revision=revision.revision,
                detection_id=revision.detection_id,
                approved_at=revision.approved_at,
                state=cast(
                    dict[str, JsonValue],
                    _without_evidence_excerpts(
                        cast(JsonValue, revision.state.model_dump(mode="json"))
                    ),
                ),
                corrections=[
                    PlayerUserCorrectionAudit(
                        field_pointer=correction.field_pointer,
                        detected_value=_sanitized_correction_value(
                            correction.field_pointer,
                            correction.detected_value,
                        ),
                        approved_value=_sanitized_correction_value(
                            correction.field_pointer,
                            correction.approved_value,
                        ),
                        corrected_at=correction.corrected_at,
                        reason=correction.reason,
                    )
                    for correction in revision.corrections
                ],
            )
            for revision in record.canonical_revisions
        ],
        deletion_receipt=record.deletion_receipt,
    )
