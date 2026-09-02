"""Sanitized projections and independent coordination for player imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.application.imported_hand_ingestion import (
    ImportedHandImportIdConflict,
    ImportedHandIngestionBlocked,
    ImportedHandIngestionError,
    IngestionDisposition,
)
from app.data_lock import DataLockError, DataLockTimeoutError
from app.infrastructure.hand_history.pokerstars import (
    PokerStarsHandDiagnostic,
    PokerStarsImportContext,
    parse_pokerstars_text,
)
from app.player_workspace import PlayerHandRecoveryRequired, PlayerWorkspace


MAX_PLAYER_IMPORT_FILES = 20
MAX_PLAYER_IMPORT_FILE_BYTES = 8 * 1024 * 1024
MAX_PLAYER_IMPORT_BATCH_BYTES = 32 * 1024 * 1024


class PlayerImportProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlayerImportDiagnostic(PlayerImportProjection):
    code: str
    message: str
    hand_ordinal: int | None = None
    source_hand_id: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class PlayerImportedHandOutcome(PlayerImportProjection):
    hand_ordinal: int
    source_hand_id: str
    record_key: str
    disposition: IngestionDisposition
    parser_disposition: Literal[
        "clean",
        "reconciliation_failed",
        "reconciliation_indeterminate",
    ]
    reconciliation_status: Literal["pass", "fail", "indeterminate"]
    lifecycle_status: str
    warning_count: int = Field(ge=0)


class PlayerImportFileOutcome(PlayerImportProjection):
    file_slot: int = Field(ge=1)
    filename: str
    status: Literal["processed", "partial", "rejected"]
    hands: list[PlayerImportedHandOutcome]
    diagnostics: list[PlayerImportDiagnostic]


class PlayerImportSummary(PlayerImportProjection):
    files_received: int = Field(ge=1)
    files_processed: int = Field(ge=0)
    hands_succeeded: int = Field(ge=0)
    diagnostic_count: int = Field(ge=0)
    duplicate_requests: int = Field(ge=0)
    retry_required: bool


class PlayerImportBatchOutcome(PlayerImportProjection):
    request_id: str
    files: list[PlayerImportFileOutcome]
    summary: PlayerImportSummary


@dataclass(frozen=True)
class PlayerImportFile:
    """One validated UTF-8 source file, ordered by its multipart slot."""

    slot: int
    filename: str
    content_sha256: str
    raw_text: str


def rejected_player_import_file(
    file_slot: int,
    filename: str,
    *,
    code: str,
    message: str,
) -> PlayerImportFileOutcome:
    return PlayerImportFileOutcome(
        file_slot=file_slot,
        filename=filename,
        status="rejected",
        hands=[],
        diagnostics=[PlayerImportDiagnostic(code=code, message=message)],
    )


def import_pokerstars_files(
    workspace: PlayerWorkspace,
    *,
    request_id: str,
    imported_at: datetime,
    files: list[PlayerImportFile | PlayerImportFileOutcome],
    lock_timeout_seconds: int,
) -> PlayerImportBatchOutcome:
    """Parse and store every valid hand without coupling sibling outcomes."""

    outcomes: list[PlayerImportFileOutcome] = []
    for source in files:
        if isinstance(source, PlayerImportFileOutcome):
            outcomes.append(source)
            continue
        parsed = parse_pokerstars_text(
            source.raw_text,
            context=PokerStarsImportContext(
                import_id=(
                    f"{request_id}:file:{source.slot}:"
                    f"{source.content_sha256}"
                ),
                imported_at=imported_at,
                source_filename=source.filename,
            ),
        )
        diagnostics = [
            _parser_diagnostic(diagnostic) for diagnostic in parsed.diagnostics
        ]
        hands: list[PlayerImportedHandOutcome] = []
        for hand in parsed.hands:
            try:
                ingestion = workspace.ingest_detected_hand(
                    hand.candidate,
                    lock_timeout_seconds=lock_timeout_seconds,
                )
            except ImportedHandIngestionBlocked:
                diagnostics.append(
                    _hand_diagnostic(
                        hand.hand_ordinal,
                        hand.candidate.raw.identity.source_hand_id,
                        code="lifecycle_blocked",
                        message=(
                            "This retained hand cannot be imported through the"
                            " ordinary workflow because its deletion lifecycle"
                            " requires explicit review."
                        ),
                    )
                )
            except ImportedHandImportIdConflict:
                diagnostics.append(
                    _hand_diagnostic(
                        hand.hand_ordinal,
                        hand.candidate.raw.identity.source_hand_id,
                        code="request_id_conflict",
                        message=(
                            "This request ID is already bound to different"
                            " source or recognition evidence. Select the files"
                            " again to start a new request."
                        ),
                    )
                )
            except ImportedHandIngestionError:
                diagnostics.append(
                    _hand_diagnostic(
                        hand.hand_ordinal,
                        hand.candidate.raw.identity.source_hand_id,
                        code="ingestion_rejected",
                        message=(
                            "The parsed hand could not be appended without"
                            " violating retained audit history."
                        ),
                    )
                )
            except PlayerHandRecoveryRequired:
                diagnostics.append(
                    _hand_diagnostic(
                        hand.hand_ordinal,
                        hand.candidate.raw.identity.source_hand_id,
                        code="recovery_required",
                        message=(
                            "This hand is unavailable until lifecycle recovery"
                            " finishes after the local runtime restarts."
                        ),
                    )
                )
            except DataLockTimeoutError:
                diagnostics.append(
                    _hand_diagnostic(
                        hand.hand_ordinal,
                        hand.candidate.raw.identity.source_hand_id,
                        code="storage_busy",
                        message=(
                            "Local player storage is busy. Retry the same"
                            " request after the active operation finishes."
                        ),
                    )
                )
            except (DataLockError, OSError, ValidationError):
                diagnostics.append(
                    _hand_diagnostic(
                        hand.hand_ordinal,
                        hand.candidate.raw.identity.source_hand_id,
                        code="storage_failure",
                        message=(
                            "The local store could not confirm this hand. Retry"
                            " the same request before starting a new import."
                        ),
                    )
                )
            else:
                hands.append(
                    PlayerImportedHandOutcome(
                        hand_ordinal=hand.hand_ordinal,
                        source_hand_id=(
                            hand.candidate.raw.identity.source_hand_id
                        ),
                        record_key=ingestion.record_key,
                        disposition=ingestion.disposition,
                        parser_disposition=hand.disposition,
                        reconciliation_status=hand.reconciliation.status,
                        lifecycle_status=ingestion.record.lifecycle.status,
                        warning_count=len(hand.candidate.detection.warnings),
                    )
                )
        status: Literal["processed", "partial", "rejected"]
        if hands and diagnostics:
            status = "partial"
        elif hands:
            status = "processed"
        else:
            status = "rejected"
        outcomes.append(
            PlayerImportFileOutcome(
                file_slot=source.slot,
                filename=source.filename,
                status=status,
                hands=hands,
                diagnostics=diagnostics,
            )
        )

    hands_succeeded = sum(len(outcome.hands) for outcome in outcomes)
    diagnostic_count = sum(len(outcome.diagnostics) for outcome in outcomes)
    return PlayerImportBatchOutcome(
        request_id=request_id,
        files=outcomes,
        summary=PlayerImportSummary(
            files_received=len(outcomes),
            files_processed=sum(
                outcome.status != "rejected" for outcome in outcomes
            ),
            hands_succeeded=hands_succeeded,
            diagnostic_count=diagnostic_count,
            duplicate_requests=sum(
                hand.disposition == "duplicate_request"
                for outcome in outcomes
                for hand in outcome.hands
            ),
            retry_required=any(
                diagnostic.code
                in {"recovery_required", "storage_busy", "storage_failure"}
                for outcome in outcomes
                for diagnostic in outcome.diagnostics
            ),
        ),
    )


def _parser_diagnostic(
    diagnostic: PokerStarsHandDiagnostic,
) -> PlayerImportDiagnostic:
    return PlayerImportDiagnostic(
        code=diagnostic.code,
        message=diagnostic.message,
        hand_ordinal=diagnostic.hand_ordinal,
        source_hand_id=diagnostic.source_hand_id,
        line_start=diagnostic.line_start,
        line_end=diagnostic.line_end,
    )


def _hand_diagnostic(
    hand_ordinal: int,
    source_hand_id: str,
    *,
    code: str,
    message: str,
) -> PlayerImportDiagnostic:
    return PlayerImportDiagnostic(
        code=code,
        message=message,
        hand_ordinal=hand_ordinal,
        source_hand_id=source_hand_id,
    )
