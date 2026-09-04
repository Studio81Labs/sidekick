"""Sanitized coordination for one explicit local PokerStars hand reimport."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.application.imported_hand_ingestion import AuthorizedReimportDisposition
from app.infrastructure.hand_history.pokerstars import (
    PokerStarsImportContext,
    parse_pokerstars_text,
)
from app.player_hands import (
    PlayerHandDetail,
    PlayerHandReimportRequest,
    project_player_hand,
)
from app.player_imports import PlayerImportFile
from app.player_workspace import (
    PlayerHandReimportInvalid,
    PlayerWorkspace,
)
from app.storage.imported_hand_store import imported_hand_record_key


class PlayerHandReimportOutcome(BaseModel):
    """Confirmed result without raw hand-history text or evidence excerpts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    disposition: AuthorizedReimportDisposition
    parser_disposition: Literal[
        "clean",
        "reconciliation_failed",
        "reconciliation_indeterminate",
    ]
    reconciliation_status: Literal["pass", "fail", "indeterminate"]
    hand: PlayerHandDetail


def reimport_pokerstars_hand(
    workspace: PlayerWorkspace,
    record_key: str,
    *,
    request: PlayerHandReimportRequest,
    imported_at: datetime,
    source: PlayerImportFile,
    lock_timeout_seconds: int,
) -> PlayerHandReimportOutcome:
    """Parse one file and replace only its uniquely matching deleted hand."""

    parsed = parse_pokerstars_text(
        source.raw_text,
        context=PokerStarsImportContext(
            import_id=f"authorized-reimport:{request.request_id}:{record_key}",
            imported_at=imported_at,
            source_filename=source.filename,
        ),
    )
    matches = [
        hand
        for hand in parsed.hands
        if imported_hand_record_key(hand.candidate.raw.identity) == record_key
    ]
    if len(matches) != 1:
        raise PlayerHandReimportInvalid(
            "The selected file must contain exactly one parsed PokerStars hand"
            " matching this deleted record"
        )
    matched = matches[0]
    result = workspace.reimport_deleted_hand(
        record_key,
        matched.candidate,
        request=request,
        at=imported_at,
        lock_timeout_seconds=lock_timeout_seconds,
    )
    return PlayerHandReimportOutcome(
        request_id=request.request_id,
        disposition=result.disposition,
        parser_disposition=matched.disposition,
        reconciliation_status=matched.reconciliation.status,
        hand=project_player_hand(record_key, result.record),
    )
