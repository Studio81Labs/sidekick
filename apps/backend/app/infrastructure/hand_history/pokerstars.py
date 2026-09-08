"""Evidence-preserving parser for a bounded PokerStars text-history subset."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Literal

from pydantic import ValidationError

from app.application.imported_hand_ingestion import ParsedImportedHandCandidate
from app.domain.imported_hands import (
    ActionOrigin,
    BlindStructure,
    CashEconomics,
    DetectedFieldEvidence,
    DetectedImportedHand,
    GameContext,
    HandResults,
    ImportedAction,
    ImportedHandState,
    ImportedSeat,
    ImportedStreet,
    ImportProvenance,
    PotAward,
    PotReconciliationResult,
    RawHandHistory,
    ShowdownEntry,
    SourceChronology,
    SourceEvidence,
    StableHandIdentity,
    StatedPotSummary,
    TournamentEconomics,
    TournamentStack,
    derive_structural_positions,
    imported_hand_state_sha256,
    reconcile_pot,
)
from app.domain.poker import Card


POKERSTARS_ADAPTER_ID = "pokerstars"
POKERSTARS_ADAPTER_VERSION = "0.2.0"
POKERSTARS_FORMAT_REVISION = "pokerstars-text/v2"

_MONEY = (
    r"[$€£]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?"
)
_CHIPS = r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?"
_HEADER_START_RE = re.compile(r"^\ufeff?PokerStars Hand #(?P<hand_id>[^:]+):")
_CASH_HEADER_RE = re.compile(
    rf"^\ufeff?PokerStars Hand #(?P<hand_id>[0-9]+): +"
    rf"Hold'em No Limit \((?P<small>{_MONEY})/(?P<big>{_MONEY}) "
    r"(?P<currency>[A-Z]{3})\) - "
    r"(?P<played_at>[0-9]{4}/[0-9]{2}/[0-9]{2} "
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}) (?P<timezone>ET|UTC|GMT)$"
)
_HISTORICAL_TOURNAMENT_HEADER_RE = re.compile(
    rf"^\ufeff?PokerStars Hand #(?P<hand_id>[0-9]+): +"
    rf"Tournament #(?P<tournament_id>[0-9]+), +"
    rf"(?P<entry_buy_in>{_MONEY})\+(?P<entry_fee>{_MONEY}) "
    r"(?P<currency>[A-Z]{3}) Hold'em No Limit - "
    r"Level (?P<blind_level>[A-Za-z0-9]+) "
    rf"\((?P<small>{_CHIPS})/(?P<big>{_CHIPS})\) - "
    r"(?P<primary_time>[0-9]{4}/[0-9]{2}/[0-9]{2} "
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}) CET "
    r"\[(?P<bracketed_time>[0-9]{4}/[0-9]{2}/[0-9]{2} "
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}) ET\]$"
)
_TABLE_RE = re.compile(
    r"^Table '(?P<table>.*)' (?P<table_size>[2-9]|10)-max "
    r"Seat #(?P<button>[1-9][0-9]*) is the button$"
)
_SEAT_RE = re.compile(
    rf"^Seat (?P<seat>[1-9][0-9]*): (?P<name>.+) "
    rf"\((?P<stack>{_MONEY}) in chips\)"
    r"(?P<sitting_out> is sitting out)?$"
)
_DEALT_RE = re.compile(
    r"^Dealt to (?P<name>.+) \[(?P<cards>[^\]]+)\]$"
)
_STREET_RE = re.compile(
    r"^\*\*\* (?P<street>FLOP|TURN|RIVER) \*\*\* (?P<boards>.+)$"
)
_TOTAL_POT_RE = re.compile(
    rf"^Total pot (?P<gross>{_MONEY}) \| Rake (?P<rake>{_MONEY})$"
)
_HISTORICAL_TOURNAMENT_TOTAL_POT_RE = re.compile(
    rf"^Total pot (?P<gross>{_MONEY}) Main pot (?P<main>{_MONEY})\. "
    rf"Side pot (?P<side>{_MONEY})\. \| Rake (?P<rake>{_MONEY})$"
)
_UNCALLED_RE = re.compile(
    rf"^Uncalled bet \((?P<amount>{_MONEY})\) returned to (?P<name>.+)$"
)
_COLLECTED_RE = re.compile(
    rf"^(?P<name>.+) collected (?P<amount>{_MONEY}) from "
    r"(?P<pot>pot|main pot|side pot(?:-[1-9][0-9]*)?)$"
)
_ACTOR_LINE_RE = re.compile(r"^(?P<name>.+): (?P<body>.+)$")
_POST_RE = re.compile(
    rf"^posts (?P<post>small blind|big blind|the ante|straddle) "
    rf"(?P<amount>{_MONEY})(?P<all_in> and is all-in)?$"
)
_CALL_RE = re.compile(
    rf"^calls (?P<amount>{_MONEY})(?P<all_in> and is all-in)?$"
)
_BET_RE = re.compile(
    rf"^bets (?P<amount>{_MONEY})(?P<all_in> and is all-in)?$"
)
_RAISE_RE = re.compile(
    rf"^raises (?P<raise_by>{_MONEY}) to (?P<target>{_MONEY})"
    r"(?P<all_in> and is all-in)?$"
)
_SHOW_RE = re.compile(r"^shows \[(?P<cards>[^\]]+)\]$")
_HISTORICAL_TOURNAMENT_SHOW_RE = re.compile(
    r"^shows \[(?P<cards>[^\]]+)\](?: \(.+\))?$"
)
_SUMMARY_SEAT_RE = re.compile(
    r"^Seat (?P<seat>[1-9][0-9]*): (?P<rest>.+)$"
)
_SUMMARY_FOLD_RE = re.compile(
    r"^ folded (?P<where>before Flop|on the Flop|on the Turn|on the River)$"
)
_HISTORICAL_TOURNAMENT_SUMMARY_FOLD_RE = re.compile(
    r"^ folded (?P<where>before Flop|on the Flop|on the Turn|on the River)"
    r"(?: \(didn't bet\))?$"
)
_SUMMARY_COLLECTED_RE = re.compile(
    rf"^ collected \((?P<amount>{_MONEY})\)$"
)
_SUMMARY_SHOWDOWN_RESULT_RE = re.compile(
    rf"^ showed \[(?P<cards>[^\]]+)\] and "
    rf"(?:(?P<lost>lost)|won \((?P<amount>{_MONEY})\)) with .+$"
)
_SUMMARY_BOARD_RE = re.compile(r"^Board \[(?P<cards>[^\]]+)\]$")
_TOURNAMENT_FINISH_RE = re.compile(
    r"^(?P<name>.+) finished the tournament in "
    r"(?P<place>[1-9][0-9]*)(?P<ordinal>st|nd|rd|th) place$"
)

_UNRESOLVED_HISTORICAL_TIME_WARNING = (
    "Source time is unresolved: historical dual-zone timestamp semantics are "
    "unverified."
)
_UNMODELED_TOURNAMENT_FINISH_WARNING = (
    "Tournament finish positions are retained as source evidence only; field size "
    "and payouts remain unknown."
)

_STREET_NAME: dict[str, Literal["flop", "turn", "river"]] = {
    "FLOP": "flop",
    "TURN": "turn",
    "RIVER": "river",
}
_POST_TYPE: dict[
    str,
    Literal["post_small_blind", "post_big_blind", "post_ante", "post_straddle"],
] = {
    "small blind": "post_small_blind",
    "big blind": "post_big_blind",
    "the ante": "post_ante",
    "straddle": "post_straddle",
}
_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}


@dataclass(frozen=True)
class PokerStarsImportContext:
    """Caller-owned occurrence context shared by every hand in one file."""

    import_id: str
    imported_at: datetime
    source_filename: str | None = None


@dataclass(frozen=True)
class PokerStarsHandDiagnostic:
    """One file- or hand-scoped rejection without source-content logging."""

    code: str
    message: str
    hand_ordinal: int | None
    source_hand_id: str | None = None
    line_start: int | None = None
    line_end: int | None = None


@dataclass(frozen=True)
class PokerStarsParsedHand:
    """An unapproved candidate plus its independent amount reconciliation."""

    hand_ordinal: int
    candidate: ParsedImportedHandCandidate
    reconciliation: PotReconciliationResult

    @property
    def disposition(
        self,
    ) -> Literal[
        "clean",
        "reconciliation_failed",
        "reconciliation_indeterminate",
    ]:
        if self.reconciliation.status == "pass":
            return "clean"
        if self.reconciliation.status == "fail":
            return "reconciliation_failed"
        return "reconciliation_indeterminate"


@dataclass(frozen=True)
class PokerStarsFileParseResult:
    """Source-ordered successes and isolated rejections for one text file."""

    hands: tuple[PokerStarsParsedHand, ...]
    diagnostics: tuple[PokerStarsHandDiagnostic, ...]

    @property
    def candidates(self) -> tuple[ParsedImportedHandCandidate, ...]:
        return tuple(hand.candidate for hand in self.hands)


class _HandParseError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        line_start: int | None = None,
        line_end: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.line_start = line_start
        self.line_end = line_end


@dataclass(frozen=True)
class _SourceLine:
    number: int
    text: str


@dataclass(frozen=True)
class _HandBlock:
    ordinal: int
    file_line_start: int
    raw_text: str


@dataclass(frozen=True)
class _ParsedSeats:
    seats: list[ImportedSeat]
    player_id_by_name: dict[str, str]
    table_size: int
    button_seat: int
    table_evidence: SourceEvidence
    seat_evidence: list[SourceEvidence]


@dataclass(frozen=True)
class _ParsedHeader:
    hand_id: str
    currency: str
    small_blind: Decimal
    big_blind: Decimal
    played_at: datetime | None
    source_timezone: str | None
    tournament_id: str | None = None
    entry_buy_in: Decimal | None = None
    entry_fee: Decimal | None = None
    blind_level: str | None = None

    @property
    def is_historical_tournament(self) -> bool:
        return self.tournament_id is not None


def parse_pokerstars_text(
    raw_text: str,
    *,
    context: PokerStarsImportContext,
) -> PokerStarsFileParseResult:
    """Parse supported hands independently; never guess unsupported syntax."""

    _validate_context(context)
    blocks, file_diagnostics = _split_hands(raw_text)
    if any(
        diagnostic.code == "unsupported_preamble"
        for diagnostic in file_diagnostics
    ):
        return PokerStarsFileParseResult(
            hands=(),
            diagnostics=tuple(file_diagnostics),
        )
    parsed: list[PokerStarsParsedHand] = []
    diagnostics = list(file_diagnostics)
    for block in blocks:
        header_match = _HEADER_START_RE.match(
            block.raw_text.splitlines()[0] if block.raw_text.splitlines() else ""
        )
        source_hand_id = header_match.group("hand_id") if header_match else None
        try:
            parsed.append(_parse_hand(block, context=context))
        except _HandParseError as exc:
            diagnostics.append(
                PokerStarsHandDiagnostic(
                    code=exc.code,
                    message=exc.message,
                    hand_ordinal=block.ordinal,
                    source_hand_id=source_hand_id,
                    line_start=(
                        block.file_line_start + exc.line_start - 1
                        if exc.line_start is not None
                        else block.file_line_start
                    ),
                    line_end=(
                        block.file_line_start + exc.line_end - 1
                        if exc.line_end is not None
                        else None
                    ),
                )
            )
        except ValidationError as exc:
            diagnostics.append(
                PokerStarsHandDiagnostic(
                    code="schema_validation",
                    message=_contract_validation_message(exc),
                    hand_ordinal=block.ordinal,
                    source_hand_id=source_hand_id,
                    line_start=block.file_line_start,
                )
            )
        except (InvalidOperation, ValueError):
            diagnostics.append(
                PokerStarsHandDiagnostic(
                    code="schema_validation",
                    message="Parsed hand does not satisfy the imported-hand contract.",
                    hand_ordinal=block.ordinal,
                    source_hand_id=source_hand_id,
                    line_start=block.file_line_start,
                )
            )
    return PokerStarsFileParseResult(
        hands=tuple(parsed),
        diagnostics=tuple(diagnostics),
    )


def _validate_context(context: PokerStarsImportContext) -> None:
    if not context.import_id.strip():
        raise ValueError("PokerStars import context requires a non-empty import_id")
    if context.imported_at.tzinfo is None or context.imported_at.utcoffset() is None:
        raise ValueError("PokerStars import context imported_at must be timezone-aware")
    if context.source_filename is not None:
        invalid_filename = (
            not context.source_filename.strip()
            or len(context.source_filename) > 255
            or "/" in context.source_filename
            or "\\" in context.source_filename
            or "\x00" in context.source_filename
            or re.match(r"^[A-Za-z]:", context.source_filename) is not None
        )
        if invalid_filename:
            raise ValueError(
                "PokerStars source_filename must be a non-empty basename without path separators"
            )


def _split_hands(
    raw_text: str,
) -> tuple[list[_HandBlock], list[PokerStarsHandDiagnostic]]:
    lines = raw_text.splitlines(keepends=True)
    starts = [
        index
        for index, line in enumerate(lines)
        if _HEADER_START_RE.match(line.rstrip("\r\n"))
    ]
    if not starts:
        return [], [
            PokerStarsHandDiagnostic(
                code="no_hand_headers",
                message="No PokerStars hand header was found.",
                hand_ordinal=None,
                line_start=1 if lines else None,
            )
        ]

    diagnostics: list[PokerStarsHandDiagnostic] = []
    if any(line.strip().lstrip("\ufeff") for line in lines[: starts[0]]):
        diagnostics.append(
            PokerStarsHandDiagnostic(
                code="unsupported_preamble",
                message=(
                    "Non-empty content before the first hand header is unsupported;"
                    " the file was rejected."
                ),
                hand_ordinal=None,
                line_start=1,
                line_end=starts[0],
            )
        )

    blocks = [
        _HandBlock(
            ordinal=ordinal,
            file_line_start=start + 1,
            raw_text=_hand_block_text(lines, start=start, end=end),
        )
        for ordinal, (start, end) in enumerate(
            zip(starts, [*starts[1:], len(lines)], strict=True),
            start=1,
        )
    ]
    return blocks, diagnostics


def _hand_block_text(lines: list[str], *, start: int, end: int) -> str:
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "".join(lines[start:end])


def _contract_validation_message(exc: ValidationError) -> str:
    messages = []
    for error in exc.errors(include_url=False, include_context=False, include_input=False):
        message = error["msg"]
        if message not in messages:
            messages.append(message)
        if len(messages) == 2:
            break
    detail = "; ".join(messages)
    return (
        f"Parsed hand does not satisfy the imported-hand contract: {detail}"
        if detail
        else "Parsed hand does not satisfy the imported-hand contract."
    )


def _parse_header(line: _SourceLine) -> _ParsedHeader:
    cash = _CASH_HEADER_RE.fullmatch(line.text)
    if cash is not None:
        currency = cash.group("currency")
        return _ParsedHeader(
            hand_id=cash.group("hand_id"),
            currency=currency,
            small_blind=_parse_positive_money(
                cash.group("small"),
                currency,
                line=line.number,
                code="invalid_blind_amount",
            ),
            big_blind=_parse_positive_money(
                cash.group("big"),
                currency,
                line=line.number,
                code="invalid_blind_amount",
            ),
            played_at=_parse_played_at(
                cash.group("played_at"),
                cash.group("timezone"),
                line=line.number,
            ),
            source_timezone=cash.group("timezone"),
        )

    tournament = _HISTORICAL_TOURNAMENT_HEADER_RE.fullmatch(line.text)
    if tournament is None:
        raise _HandParseError(
            "unsupported_header",
            (
                "Only English PokerStars no-limit cash headers and the reviewed "
                "historical tournament header are supported."
            ),
            line_start=line.number,
        )
    for source_time in (
        tournament.group("primary_time"),
        tournament.group("bracketed_time"),
    ):
        try:
            datetime.strptime(source_time, "%Y/%m/%d %H:%M:%S")
        except ValueError as exc:
            raise _HandParseError(
                "invalid_source_time",
                "A historical dual-zone source time is invalid.",
                line_start=line.number,
            ) from exc

    currency = tournament.group("currency")
    return _ParsedHeader(
        hand_id=tournament.group("hand_id"),
        currency=currency,
        small_blind=_parse_positive_money(
            tournament.group("small"),
            currency,
            line=line.number,
            code="invalid_blind_amount",
        ),
        big_blind=_parse_positive_money(
            tournament.group("big"),
            currency,
            line=line.number,
            code="invalid_blind_amount",
        ),
        played_at=None,
        source_timezone=None,
        tournament_id=tournament.group("tournament_id"),
        entry_buy_in=_parse_money(
            tournament.group("entry_buy_in"),
            currency,
            line=line.number,
        ),
        entry_fee=_parse_money(
            tournament.group("entry_fee"),
            currency,
            line=line.number,
        ),
        blind_level=tournament.group("blind_level"),
    )


def _game_context(
    *,
    header: _ParsedHeader,
    parsed_seats: _ParsedSeats,
    ante: Decimal | None,
    ante_mode: str,
    straddle: Decimal | None,
) -> GameContext:
    economics: CashEconomics | TournamentEconomics
    if header.is_historical_tournament:
        assert header.tournament_id is not None
        assert header.entry_buy_in is not None
        assert header.entry_fee is not None
        assert header.blind_level is not None
        economics = TournamentEconomics(
            tournament_id=header.tournament_id,
            entry_buy_in=header.entry_buy_in,
            entry_fee=header.entry_fee,
            blind_level=header.blind_level,
            currency=header.currency,
            remaining_stacks=[
                TournamentStack(player_id=seat.player_id, stack=seat.starting_stack)
                for seat in parsed_seats.seats
            ],
        )
    else:
        economics = CashEconomics(currency=header.currency)
    return GameContext(
        betting_limit="no_limit",
        table_size=parsed_seats.table_size,
        blinds=BlindStructure(
            small_blind=header.small_blind,
            big_blind=header.big_blind,
            ante=ante,
            ante_mode=ante_mode,
            straddle=straddle,
        ),
        economics=economics,
    )


def _parse_hand(
    block: _HandBlock,
    *,
    context: PokerStarsImportContext,
) -> PokerStarsParsedHand:
    lines = [
        _SourceLine(number=index, text=line.rstrip("\r\n"))
        for index, line in enumerate(block.raw_text.splitlines(), start=1)
    ]
    if not lines:
        raise _HandParseError("empty_hand", "Hand block is empty.")
    header = _parse_header(lines[0])
    amount_currency = (
        None if header.is_historical_tournament else header.currency
    )
    occurrence_digest = sha256(
        f"{context.import_id}\0{block.ordinal}".encode("utf-8")
    ).hexdigest()
    raw_source_id = f"ps-source-{occurrence_digest[:32]}"
    import_id = f"ps-import-{occurrence_digest[:32]}"
    detection_id = f"ps-detection-{occurrence_digest[:32]}"

    parsed_seats = _parse_seats(
        lines,
        raw_source_id=raw_source_id,
        currency=amount_currency,
    )
    positions = derive_structural_positions(
        parsed_seats.seats,
        parsed_seats.button_seat,
    )
    seats = [
        ImportedSeat.model_validate(
            {
                **seat.model_dump(mode="python"),
                "position": positions.get(seat.seat_number),
            }
        )
        for seat in parsed_seats.seats
    ]

    chronology = SourceChronology(
        played_at=header.played_at,
        source_timezone=header.source_timezone,
        source_file_id=raw_source_id,
        hand_ordinal=block.ordinal,
    )
    identity = StableHandIdentity(
        site="pokerstars",
        source_hand_id=header.hand_id,
    )
    raw = RawHandHistory(
        raw_source_id=raw_source_id,
        identity=identity,
        chronology=chronology,
        provenance=ImportProvenance(
            import_id=import_id,
            imported_at=context.imported_at,
            adapter_id=POKERSTARS_ADAPTER_ID,
            adapter_version=POKERSTARS_ADAPTER_VERSION,
            format_revision=POKERSTARS_FORMAT_REVISION,
            source_filename=context.source_filename,
        ),
        content_sha256=sha256(block.raw_text.encode("utf-8")).hexdigest(),
        raw_text=block.raw_text,
    )

    parsed_body = _parse_body(
        lines,
        raw_source_id=raw_source_id,
        currency=amount_currency,
        nominal_preflop_bring_in=header.big_blind,
        player_id_by_name=parsed_seats.player_id_by_name,
        sitting_out_player_ids={
            seat.player_id
            for seat in parsed_seats.seats
            if seat.participation == "sitting_out"
        },
        expected_position_tags_by_player={
            seat.player_id: _summary_position_tags(seat)
            for seat in seats
        },
        allow_historical_tournament_results=header.is_historical_tournament,
    )
    _validate_structural_blind_posts(
        parsed_body,
        seats,
        small_blind=header.small_blind,
        big_blind=header.big_blind,
    )
    _validate_known_cards(parsed_body)
    ante, ante_mode = _ante_structure(parsed_body.streets, seats)
    straddle = _straddle_amount(parsed_body.streets)
    game = _game_context(
        header=header,
        parsed_seats=parsed_seats,
        ante=ante,
        ante_mode=ante_mode,
        straddle=straddle,
    )
    try:
        state = ImportedHandState(
            identity=identity,
            chronology=chronology,
            game=game,
            button_seat=parsed_seats.button_seat,
            seats=seats,
            hero_player_id=parsed_body.hero_player_id,
            hero_cards=parsed_body.hero_cards,
            streets=parsed_body.streets,
            results=parsed_body.results,
        )
    except ValidationError as exc:
        action_diagnostic = _state_action_diagnostic(
            exc,
            identity=identity,
            chronology=chronology,
            game=game,
            button_seat=parsed_seats.button_seat,
            seats=seats,
            parsed_body=parsed_body,
        )
        if action_diagnostic is None:
            raise
        code, message, evidence = action_diagnostic
        raise _HandParseError(
            code,
            message,
            line_start=evidence.line_start,
            line_end=evidence.line_end,
        ) from exc
    reconciliation = reconcile_pot(state)
    warnings = list(parsed_body.warnings)
    if header.is_historical_tournament:
        warnings.append(_UNRESOLVED_HISTORICAL_TIME_WARNING)
    if parsed_body.finish_evidence:
        warnings.append(_UNMODELED_TOURNAMENT_FINISH_WARNING)
    if reconciliation.status == "fail":
        warnings.append(
            "Pot reconciliation failed; review action amounts and source totals."
        )
    elif reconciliation.status == "indeterminate":
        warnings.append(
            "Pot reconciliation is indeterminate; review incomplete amount evidence."
        )

    field_evidence = _field_evidence(
        header=_evidence(raw_source_id, lines[0]),
        parsed_header=header,
        parsed_seats=parsed_seats,
        parsed_body=parsed_body,
    )
    detection = DetectedImportedHand(
        detection_id=detection_id,
        raw_source_id=raw_source_id,
        detector_id=POKERSTARS_ADAPTER_ID,
        detector_version=POKERSTARS_ADAPTER_VERSION,
        detected_at=context.imported_at,
        state=state,
        field_evidence=field_evidence,
        warnings=warnings,
        content_sha256=imported_hand_state_sha256(state),
    )
    return PokerStarsParsedHand(
        hand_ordinal=block.ordinal,
        candidate=ParsedImportedHandCandidate(raw=raw, detection=detection),
        reconciliation=reconciliation,
    )


@dataclass(frozen=True)
class _ParsedBody:
    hero_player_id: str | None
    hero_cards: list[Card]
    streets: list[ImportedStreet]
    results: HandResults | None
    warnings: tuple[str, ...]
    hero_evidence: SourceEvidence | None
    hole_evidence: SourceEvidence
    board_evidence: list[SourceEvidence | None]
    action_evidence: list[list[SourceEvidence]]
    results_evidence: SourceEvidence | None
    finish_evidence: list[SourceEvidence]


def _parse_seats(
    lines: list[_SourceLine],
    *,
    raw_source_id: str,
    currency: str | None,
) -> _ParsedSeats:
    table_line = next((line for line in lines[1:] if _TABLE_RE.fullmatch(line.text)), None)
    if table_line is None:
        raise _HandParseError(
            "missing_table",
            "A supported max-seat table/button line is required.",
        )
    table = _TABLE_RE.fullmatch(table_line.text)
    assert table is not None
    hole_index = next(
        (index for index, line in enumerate(lines) if line.text == "*** HOLE CARDS ***"),
        len(lines),
    )
    seat_matches = [
        (line, match)
        for line in lines[1:hole_index]
        if (match := _SEAT_RE.fullmatch(line.text)) is not None
    ]
    if len(seat_matches) < 2:
        raise _HandParseError(
            "missing_seats",
            "At least two supported seat declarations are required.",
        )

    seats: list[ImportedSeat] = []
    player_id_by_name: dict[str, str] = {}
    seat_numbers: set[int] = set()
    seat_evidence: list[SourceEvidence] = []
    for line, match in seat_matches:
        name = match.group("name")
        if name in player_id_by_name:
            raise _HandParseError(
                "duplicate_player_name",
                "A player name appears in more than one seat.",
                line_start=line.number,
            )
        seat_number = int(match.group("seat"))
        if seat_number in seat_numbers:
            raise _HandParseError(
                "duplicate_seat_number",
                "A seat number appears in more than one declaration.",
                line_start=line.number,
            )
        seat_numbers.add(seat_number)
        player_id = f"seat-{seat_number}"
        player_id_by_name[name] = player_id
        stack = _parse_money(
            match.group("stack"),
            currency,
            line=line.number,
        )
        if stack <= 0 and not match.group("sitting_out"):
            raise _HandParseError(
                "invalid_starting_stack",
                "A dealt-in seat must have a positive starting stack.",
                line_start=line.number,
            )
        seats.append(
            ImportedSeat(
                seat_number=seat_number,
                player_id=player_id,
                display_name=name,
                starting_stack=stack,
                participation=(
                    "sitting_out" if match.group("sitting_out") else "dealt_in"
                ),
            )
        )
        seat_evidence.append(_evidence(raw_source_id, line))

    table_size = int(table.group("table_size"))
    button_seat = int(table.group("button"))
    for seat, evidence in zip(seats, seat_evidence, strict=True):
        if seat.seat_number > table_size:
            raise _HandParseError(
                "seat_outside_table",
                "A seat number exceeds the declared table size.",
                line_start=evidence.line_start,
                line_end=evidence.line_end,
            )
    button = next(
        (seat for seat in seats if seat.seat_number == button_seat),
        None,
    )
    if button is None or button.participation != "dealt_in":
        raise _HandParseError(
            "unsupported_button_seat",
            "The button must identify a declared dealt-in seat.",
            line_start=table_line.number,
            line_end=table_line.number,
        )
    if sum(seat.participation == "dealt_in" for seat in seats) < 2:
        raise _HandParseError(
            "insufficient_dealt_in_seats",
            "At least two declared seats must be dealt in.",
            line_start=min(source.line_start for source in seat_evidence),
            line_end=max(source.line_end for source in seat_evidence),
        )
    return _ParsedSeats(
        seats=seats,
        player_id_by_name=player_id_by_name,
        table_size=table_size,
        button_seat=button_seat,
        table_evidence=_evidence(raw_source_id, table_line),
        seat_evidence=seat_evidence,
    )


def _parse_body(
    lines: list[_SourceLine],
    *,
    raw_source_id: str,
    currency: str | None,
    nominal_preflop_bring_in: Decimal,
    player_id_by_name: dict[str, str],
    sitting_out_player_ids: set[str],
    expected_position_tags_by_player: dict[str, frozenset[str]],
    allow_historical_tournament_results: bool,
) -> _ParsedBody:
    street_names: list[Literal["preflop", "flop", "turn", "river"]] = ["preflop"]
    boards: list[list[Card]] = [[]]
    board_evidence: list[SourceEvidence | None] = [None]
    actions: list[list[ImportedAction]] = [[]]
    action_evidence: list[list[SourceEvidence]] = [[]]
    commitments: dict[str, Decimal] = {
        player_id: Decimal(0) for player_id in player_id_by_name.values()
    }
    live_commitments: dict[str, Decimal] = {
        player_id: Decimal(0) for player_id in player_id_by_name.values()
    }
    current_wager = Decimal(0)
    nominal_bring_in = nominal_preflop_bring_in
    hero_player_id: str | None = None
    hero_cards: list[Card] = []
    hero_evidence: SourceEvidence | None = None
    hole_evidence: SourceEvidence | None = None
    awards: list[PotAward] = []
    showdown: list[ShowdownEntry] = []
    stated_pot: StatedPotSummary | None = None
    results_evidence: SourceEvidence | None = None
    summary_board_seen = False
    summary_seat_numbers: set[int] = set()
    table_seen = False
    seat_declaration_count = 0
    forced_post_seen = False
    hole_seen = False
    showdown_seen = False
    award_seen = False
    non_forced_action_seen = False
    in_summary = False
    summary_seen = False
    unresolved_decisions = 0
    uncalled_return_seen = False
    folded_player_ids: set[str] = set()
    showdown_player_ids: set[str] = set()
    finish_player_ids: set[str] = set()
    finish_evidence: list[SourceEvidence] = []

    for line in lines[1:]:
        text = line.text
        if not text:
            continue
        if _TABLE_RE.fullmatch(text):
            if table_seen or seat_declaration_count or forced_post_seen or hole_seen:
                raise _HandParseError(
                    "declaration_order",
                    "The table declaration must precede seats and action evidence.",
                    line_start=line.number,
                )
            table_seen = True
            continue
        if _SEAT_RE.fullmatch(text):
            if not table_seen or forced_post_seen or hole_seen:
                raise _HandParseError(
                    "declaration_order",
                    "Seat declarations must follow the table and precede action evidence.",
                    line_start=line.number,
                )
            seat_declaration_count += 1
            continue
        if text == "*** HOLE CARDS ***":
            if (
                not table_seen
                or seat_declaration_count < 2
                or hole_seen
                or in_summary
                or showdown_seen
                or len(street_names) != 1
            ):
                raise _HandParseError(
                    "hole_cards_order",
                    "The hole-card section must appear exactly once before later sections.",
                    line_start=line.number,
                )
            hole_seen = True
            hole_evidence = _evidence(raw_source_id, line)
            continue
        if text == "*** SHOW DOWN ***":
            if not hole_seen or showdown_seen or award_seen or in_summary:
                raise _HandParseError(
                    "showdown_order",
                    "The showdown marker must follow play, precede awards, and appear at most once.",
                    line_start=line.number,
                )
            showdown_seen = True
            continue
        if text == "*** SUMMARY ***":
            if not hole_seen or summary_seen:
                raise _HandParseError(
                    "summary_order",
                    "The summary must follow hole cards and appear at most once.",
                    line_start=line.number,
                )
            summary_seen = True
            in_summary = True
            continue

        finish = _TOURNAMENT_FINISH_RE.fullmatch(text)
        if finish is not None:
            if (
                not allow_historical_tournament_results
                or not hole_seen
                or not award_seen
                or in_summary
            ):
                raise _HandParseError(
                    "tournament_finish_order",
                    "A tournament finish statement must follow awards and precede the summary.",
                    line_start=line.number,
                )
            player_id = _player_id(
                finish.group("name"),
                player_id_by_name,
                line=line.number,
            )
            if finish.group("ordinal") != _ordinal_suffix(int(finish.group("place"))):
                raise _HandParseError(
                    "invalid_tournament_finish",
                    "A tournament finish statement has an invalid ordinal suffix.",
                    line_start=line.number,
                    line_end=line.number,
                )
            if player_id in finish_player_ids:
                raise _HandParseError(
                    "duplicate_tournament_finish",
                    "A tournament finish statement cannot repeat a player.",
                    line_start=line.number,
                    line_end=line.number,
                )
            finish_player_ids.add(player_id)
            finish_evidence.append(_evidence(raw_source_id, line))
            continue

        if in_summary:
            total_pot_match = (
                None
                if allow_historical_tournament_results
                else _TOTAL_POT_RE.fullmatch(text)
            )
            tournament_total_pot_match = (
                _HISTORICAL_TOURNAMENT_TOTAL_POT_RE.fullmatch(text)
                if allow_historical_tournament_results
                else None
            )
            if total_pot_match is not None or tournament_total_pot_match is not None:
                if stated_pot is not None:
                    raise _HandParseError(
                        "duplicate_total_pot",
                        "A hand cannot contain more than one total-pot line.",
                        line_start=line.number,
                    )
                pot_match = tournament_total_pot_match or total_pot_match
                assert pot_match is not None
                gross = _parse_money(
                    pot_match.group("gross"),
                    currency,
                    line=line.number,
                )
                rake = _parse_money(
                    pot_match.group("rake"),
                    currency,
                    line=line.number,
                )
                if tournament_total_pot_match is not None and rake != 0:
                    raise _HandParseError(
                        "invalid_total_pot",
                        "The reviewed historical tournament form requires zero rake.",
                        line_start=line.number,
                        line_end=line.number,
                    )
                if rake > gross:
                    raise _HandParseError(
                        "invalid_total_pot",
                        "Rake cannot exceed the total pot.",
                        line_start=line.number,
                        line_end=line.number,
                    )
                gross_pots: list[Decimal] = []
                if tournament_total_pot_match is not None:
                    main_pot = _parse_money(
                        tournament_total_pot_match.group("main"),
                        currency,
                        line=line.number,
                    )
                    side_pot = _parse_money(
                        tournament_total_pot_match.group("side"),
                        currency,
                        line=line.number,
                    )
                    if main_pot + side_pot != gross:
                        raise _HandParseError(
                            "invalid_total_pot",
                            "Tournament pot components must equal the total pot.",
                            line_start=line.number,
                            line_end=line.number,
                        )
                    gross_pots = [main_pot, side_pot]
                stated_pot = StatedPotSummary(
                    gross_total=gross,
                    rake=rake,
                    net_total=gross - rake,
                    gross_pots=gross_pots,
                )
                results_evidence = _evidence(raw_source_id, line)
                continue
            if text.startswith("Board ["):
                summary_board = _SUMMARY_BOARD_RE.fullmatch(text)
                if summary_board is None:
                    raise _HandParseError(
                        "unsupported_summary_board",
                        "This PokerStars summary board syntax is unsupported.",
                        line_start=line.number,
                    )
                if summary_board_seen:
                    raise _HandParseError(
                        "duplicate_summary_board",
                        "A hand cannot contain more than one summary-board line.",
                        line_start=line.number,
                        line_end=line.number,
                    )
                summary_cards = _parse_cards(
                    summary_board.group("cards"),
                    line=line.number,
                )
                if not boards[-1] or summary_cards != boards[-1]:
                    raise _HandParseError(
                        "summary_board_mismatch",
                        "The summary board does not match the parsed street board.",
                        line_start=line.number,
                    )
                summary_board_seen = True
                continue
            if text.startswith("Seat "):
                _validate_summary_seat_line(
                    text,
                    line=line.number,
                    currency=currency,
                    player_id_by_name=player_id_by_name,
                    sitting_out_player_ids=sitting_out_player_ids,
                    expected_position_tags_by_player=(
                        expected_position_tags_by_player
                    ),
                    street_names=street_names,
                    actions=actions,
                    showdown=showdown,
                    awards=awards,
                    allow_historical_tournament_results=(
                        allow_historical_tournament_results
                    ),
                    summary_seat_numbers=summary_seat_numbers,
                )
                continue
            raise _HandParseError(
                "unsupported_summary_line",
                "This PokerStars summary line is not supported.",
                line_start=line.number,
            )

        street_match = _STREET_RE.fullmatch(text)
        if street_match is not None:
            if not hole_seen or showdown_seen or award_seen:
                raise _HandParseError(
                    "street_order",
                    "A board street must follow hole cards and precede showdown and awards.",
                    line_start=line.number,
                )
            street_name = _STREET_NAME[street_match.group("street")]
            if len(street_names) >= 4:
                raise _HandParseError(
                    "street_order",
                    "No street marker can follow the river.",
                    line_start=line.number,
                )
            expected = ("flop", "turn", "river")[len(street_names) - 1]
            if street_name != expected:
                raise _HandParseError(
                    "street_order",
                    f"Expected {expected} before {street_name}.",
                    line_start=line.number,
                )
            board = _parse_board(
                street_match.group("boards"),
                expected_count={"flop": 3, "turn": 4, "river": 5}[street_name],
                line=line.number,
            )
            street_names.append(street_name)
            boards.append(board)
            board_evidence.append(_evidence(raw_source_id, line))
            actions.append([])
            action_evidence.append([])
            commitments = {
                player_id: Decimal(0) for player_id in player_id_by_name.values()
            }
            live_commitments = {
                player_id: Decimal(0) for player_id in player_id_by_name.values()
            }
            current_wager = Decimal(0)
            nominal_bring_in = Decimal(0)
            uncalled_return_seen = False
            continue
        if text.startswith("*** "):
            raise _HandParseError(
                "unsupported_section",
                "This PokerStars section marker is not supported.",
                line_start=line.number,
            )

        dealt = _DEALT_RE.fullmatch(text)
        if dealt is not None:
            if (
                not hole_seen
                or showdown_seen
                or len(street_names) != 1
                or hero_player_id is not None
                or award_seen
                or non_forced_action_seen
            ):
                raise _HandParseError(
                    "hero_cards_order",
                    "The dealt-to-hero line must appear once in the hole-card section.",
                    line_start=line.number,
                )
            dealt_player_id = _dealt_in_player_id(
                dealt.group("name"),
                player_id_by_name,
                sitting_out_player_ids=sitting_out_player_ids,
                line=line.number,
                code="hero_not_dealt_in",
                message="The dealt-to-hero line must identify a dealt-in seat.",
            )
            hero_player_id = dealt_player_id
            hero_cards = _parse_cards(dealt.group("cards"), line=line.number)
            if len(hero_cards) != 2:
                raise _HandParseError(
                    "hero_card_count",
                    "The dealt-to-hero line must contain exactly two cards.",
                    line_start=line.number,
                )
            hero_evidence = _evidence(raw_source_id, line)
            continue

        uncalled = _UNCALLED_RE.fullmatch(text)
        if uncalled is not None:
            if not hole_seen or showdown_seen or award_seen:
                raise _HandParseError(
                    "uncalled_return_order",
                    "An uncalled return must follow hole cards and precede showdown and awards.",
                    line_start=line.number,
                )
            if uncalled_return_seen:
                raise _HandParseError(
                    "action_after_uncalled_return",
                    "A street cannot contain more than one uncalled return.",
                    line_start=line.number,
                    line_end=line.number,
                )
            player_id = _dealt_in_player_id(
                uncalled.group("name"),
                player_id_by_name,
                sitting_out_player_ids=sitting_out_player_ids,
                line=line.number,
            )
            amount = _parse_positive_money(
                uncalled.group("amount"),
                currency,
                line=line.number,
                code="invalid_action_amount",
            )
            prior = commitments[player_id]
            prior_live = live_commitments[player_id]
            if amount <= 0 or amount > prior_live:
                raise _HandParseError(
                    "invalid_uncalled_return",
                    "An uncalled return must be positive and not exceed the prior commitment.",
                    line_start=line.number,
                )
            commitments[player_id] = prior - amount
            live_commitments[player_id] = prior_live - amount
            current_wager = max(live_commitments.values(), default=Decimal(0))
            evidence = _evidence(raw_source_id, line)
            actions[-1].append(
                _action(
                    sequence=len(actions[-1]),
                    actor_id=player_id,
                    action_type="uncalled_return",
                    amount=amount,
                    total_committed=commitments[player_id],
                    all_in=False,
                    evidence=evidence,
                    forced=True,
                )
            )
            action_evidence[-1].append(evidence)
            uncalled_return_seen = True
            continue

        collected = _COLLECTED_RE.fullmatch(text)
        if collected is not None:
            if not hole_seen:
                raise _HandParseError(
                    "award_order",
                    "A pot award must follow the hole-card section.",
                    line_start=line.number,
                )
            player_id = _dealt_in_player_id(
                collected.group("name"),
                player_id_by_name,
                sitting_out_player_ids=sitting_out_player_ids,
                line=line.number,
            )
            if player_id in folded_player_ids:
                raise _HandParseError(
                    "invalid_award_recipient",
                    "A player who folded cannot receive a pot award.",
                    line_start=line.number,
                    line_end=line.number,
                )
            evidence = _evidence(raw_source_id, line)
            pot_label = collected.group("pot")
            if pot_label == "pot":
                pot_index = None
            elif pot_label == "main pot":
                pot_index = 0
            elif pot_label == "side pot":
                pot_index = 1
            else:
                pot_index = int(pot_label.rsplit("-", 1)[1])
            awards.append(
                PotAward(
                    player_id=player_id,
                    amount=_parse_positive_money(
                        collected.group("amount"),
                        currency,
                        line=line.number,
                        code="invalid_award_amount",
                    ),
                    pot_index=pot_index,
                    evidence=[evidence],
                )
            )
            award_seen = True
            continue

        actor_line = _ACTOR_LINE_RE.fullmatch(text)
        if actor_line is not None:
            player_id = _dealt_in_player_id(
                actor_line.group("name"),
                player_id_by_name,
                sitting_out_player_ids=sitting_out_player_ids,
                line=line.number,
            )
            body = actor_line.group("body")
            evidence = _evidence(raw_source_id, line)
            if award_seen and not allow_historical_tournament_results:
                raise _HandParseError(
                    "award_order",
                    "Table actions and showdown evidence cannot follow a pot award.",
                    line_start=line.number,
                )
            showdown_entry = _showdown_entry(
                player_id,
                body,
                evidence,
                allow_rank_description=allow_historical_tournament_results,
                line=line.number,
            )
            if showdown_entry is not None:
                if not showdown_seen:
                    raise _HandParseError(
                        "showdown_order",
                        "Shown or mucked cards require an explicit showdown section.",
                        line_start=line.number,
                    )
                if player_id in folded_player_ids:
                    raise _HandParseError(
                        "invalid_showdown_participant",
                        "A player who folded cannot appear at showdown.",
                        line_start=line.number,
                        line_end=line.number,
                    )
                if player_id in showdown_player_ids:
                    raise _HandParseError(
                        "duplicate_showdown_entry",
                        "A player may appear at showdown at most once.",
                        line_start=line.number,
                        line_end=line.number,
                    )
                showdown_player_ids.add(player_id)
                showdown.append(showdown_entry)
                continue
            if award_seen:
                raise _HandParseError(
                    "award_order",
                    "Table actions cannot follow a pot award.",
                    line_start=line.number,
                )
            parsed_action = _parse_action_line(
                body,
                currency=currency,
                line=line.number,
                sequence=len(actions[-1]),
                actor_id=player_id,
                prior_total=commitments[player_id],
                prior_live=live_commitments[player_id],
                current_wager=max(current_wager, nominal_bring_in),
                evidence=evidence,
            )
            if parsed_action is None:
                raise _HandParseError(
                    "unsupported_action",
                    "This PokerStars player action is not supported.",
                    line_start=line.number,
                )
            if uncalled_return_seen:
                raise _HandParseError(
                    "action_after_uncalled_return",
                    "A table action cannot follow an uncalled return on the same street.",
                    line_start=line.number,
                    line_end=line.number,
                )
            action, total_committed, live_committed = parsed_action
            is_forced_post = action.action_type.startswith("post_")
            if showdown_seen or (is_forced_post and hole_seen) or (
                not is_forced_post and not hole_seen
            ):
                raise _HandParseError(
                    "action_section_order",
                    "Forced posts must precede hole cards and table actions must follow them.",
                    line_start=line.number,
                )
            if player_id in folded_player_ids:
                raise _HandParseError(
                    "terminal_actor_action",
                    "A player cannot act after folding.",
                    line_start=line.number,
                    line_end=line.number,
                )
            if is_forced_post:
                if not table_seen or seat_declaration_count < 2:
                    raise _HandParseError(
                        "action_section_order",
                        "Forced posts require preceding table and seat declarations.",
                        line_start=line.number,
                    )
                forced_post_seen = True
            commitments[player_id] = total_committed
            live_commitments[player_id] = live_committed
            if action.action_type in {
                "post_small_blind",
                "post_big_blind",
                "post_straddle",
                "bet",
                "call",
                "raise",
            }:
                current_wager = max(current_wager, live_committed)
            actions[-1].append(action)
            action_evidence[-1].append(evidence)
            if not is_forced_post:
                non_forced_action_seen = True
            if action.action_type == "fold":
                folded_player_ids.add(player_id)
            if action.origin.kind == "unknown":
                unresolved_decisions += 1
            continue

        raise _HandParseError(
            "unsupported_line",
            "This PokerStars hand line is not supported.",
            line_start=line.number,
        )

    if not hole_seen:
        raise _HandParseError(
            "missing_hole_cards",
            "A supported hand requires an explicit hole-card section marker.",
        )
    assert hole_evidence is not None

    streets = [
        ImportedStreet(street=name, board_cards=board, actions=street_actions)
        for name, board, street_actions in zip(
            street_names,
            boards,
            actions,
            strict=True,
        )
    ]
    results = (
        HandResults(stated_pot=stated_pot, showdown=showdown, awards=awards)
        if stated_pot is not None or showdown or awards
        else None
    )
    warnings = (
        (
            f"Action origin is unresolved for {unresolved_decisions} player "
            "decision(s); review is required."
        ),
    ) if unresolved_decisions else ()
    return _ParsedBody(
        hero_player_id=hero_player_id,
        hero_cards=hero_cards,
        streets=streets,
        results=results,
        warnings=warnings,
        hero_evidence=hero_evidence,
        hole_evidence=hole_evidence,
        board_evidence=board_evidence,
        action_evidence=action_evidence,
        results_evidence=results_evidence,
        finish_evidence=finish_evidence,
    )


def _validate_summary_seat_line(
    text: str,
    *,
    line: int,
    currency: str | None,
    player_id_by_name: dict[str, str],
    sitting_out_player_ids: set[str],
    expected_position_tags_by_player: dict[str, frozenset[str]],
    street_names: list[Literal["preflop", "flop", "turn", "river"]],
    actions: list[list[ImportedAction]],
    showdown: list[ShowdownEntry],
    awards: list[PotAward],
    allow_historical_tournament_results: bool,
    summary_seat_numbers: set[int],
) -> None:
    summary = _SUMMARY_SEAT_RE.fullmatch(text)
    if summary is None:
        raise _HandParseError(
            "unsupported_summary_line",
            "This PokerStars seat-summary syntax is unsupported.",
            line_start=line,
        )
    seat_number = int(summary.group("seat"))
    if seat_number in summary_seat_numbers:
        raise _HandParseError(
            "duplicate_summary_seat",
            "A hand summary cannot repeat a seat record.",
            line_start=line,
            line_end=line,
        )
    summary_seat_numbers.add(seat_number)
    rest = summary.group("rest")
    matching_names = [
        name
        for name in player_id_by_name
        if rest == name or rest.startswith(f"{name} ")
    ]
    if not matching_names:
        raise _HandParseError(
            "unknown_summary_player",
            "A seat summary references a player without a declaration.",
            line_start=line,
        )
    name = max(matching_names, key=len)
    player_id = player_id_by_name[name]
    if player_id != f"seat-{summary.group('seat')}":
        raise _HandParseError(
            "summary_seat_mismatch",
            "A seat summary does not match the player's declared seat.",
            line_start=line,
        )
    suffix = rest[len(name) :]
    position_tags = {
        " (button)": "button",
        " (small blind)": "small blind",
        " (big blind)": "big blind",
    }
    observed_tags: list[str] = []
    while any(suffix.startswith(tag) for tag in position_tags):
        tag = next(tag for tag in position_tags if suffix.startswith(tag))
        observed_tags.append(position_tags[tag])
        suffix = suffix[len(tag) :]
    if len(observed_tags) != len(set(observed_tags)) or frozenset(
        observed_tags
    ) != expected_position_tags_by_player[player_id]:
        raise _HandParseError(
            "summary_position_mismatch",
            "Summary position tags contradict the derived dealt-in seat ring.",
            line_start=line,
        )

    if suffix == " is sitting out":
        if player_id not in sitting_out_player_ids:
            raise _HandParseError(
                "summary_participation_mismatch",
                "The summary sitting-out status contradicts the seat declaration.",
                line_start=line,
            )
        return

    folded_pattern = (
        _HISTORICAL_TOURNAMENT_SUMMARY_FOLD_RE
        if allow_historical_tournament_results
        else _SUMMARY_FOLD_RE
    )
    folded = folded_pattern.fullmatch(suffix)
    if folded is not None:
        expected_street = {
            "before Flop": "preflop",
            "on the Flop": "flop",
            "on the Turn": "turn",
            "on the River": "river",
        }[folded.group("where")]
        matching_actions = [
            action
            for street_name, street_actions in zip(
                street_names,
                actions,
                strict=True,
            )
            for action in street_actions
            if street_name == expected_street
            and action.actor_id == player_id
            and action.action_type == "fold"
        ]
        if not matching_actions:
            raise _HandParseError(
                "summary_fold_mismatch",
                "The summary fold does not match the parsed action stream.",
                line_start=line,
            )
        return

    collected = _SUMMARY_COLLECTED_RE.fullmatch(suffix)
    if collected is not None:
        amount = _parse_positive_money(
            collected.group("amount"),
            currency,
            line=line,
            code="invalid_award_amount",
        )
        awarded = sum(
            (
                award.amount
                for award in awards
                if award.player_id == player_id and award.amount is not None
            ),
            Decimal(0),
        )
        if amount != awarded:
            raise _HandParseError(
                "summary_award_mismatch",
                "The summary collection does not match parsed pot awards.",
                line_start=line,
            )
        return

    showdown_result = (
        _SUMMARY_SHOWDOWN_RESULT_RE.fullmatch(suffix)
        if allow_historical_tournament_results
        else None
    )
    if showdown_result is not None:
        cards = _parse_cards(showdown_result.group("cards"), line=line)
        matching_showdown = next(
            (entry for entry in showdown if entry.player_id == player_id),
            None,
        )
        if (
            matching_showdown is None
            or matching_showdown.disposition != "shown"
            or matching_showdown.cards != cards
        ):
            raise _HandParseError(
                "summary_showdown_mismatch",
                "The summary shown cards do not match the parsed showdown.",
                line_start=line,
            )
        awarded = sum(
            (
                award.amount
                for award in awards
                if award.player_id == player_id and award.amount is not None
            ),
            Decimal(0),
        )
        if showdown_result.group("lost") is not None:
            if awarded != 0:
                raise _HandParseError(
                    "summary_award_mismatch",
                    "A summary loser cannot have collected a pot award.",
                    line_start=line,
                )
        else:
            amount = _parse_positive_money(
                showdown_result.group("amount"),
                currency,
                line=line,
                code="invalid_award_amount",
            )
            if amount != awarded:
                raise _HandParseError(
                    "summary_award_mismatch",
                    "The summary collection does not match parsed pot awards.",
                    line_start=line,
                )
        return

    raise _HandParseError(
        "unsupported_summary_result",
        "This seat summary carries result or action-origin syntax not supported"
        " by this adapter revision.",
        line_start=line,
    )


def _summary_position_tags(seat: ImportedSeat) -> frozenset[str]:
    if seat.position is None:
        return frozenset()
    return {
        "BTN/SB": frozenset({"button", "small blind"}),
        "BTN": frozenset({"button"}),
        "SB": frozenset({"small blind"}),
        "BB": frozenset({"big blind"}),
    }.get(seat.position.display_label, frozenset())


def _ordinal_suffix(value: int) -> Literal["st", "nd", "rd", "th"]:
    if 10 < value % 100 < 14:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")


def _parse_action_line(
    body: str,
    *,
    currency: str | None,
    line: int,
    sequence: int,
    actor_id: str,
    prior_total: Decimal,
    prior_live: Decimal,
    current_wager: Decimal,
    evidence: SourceEvidence,
) -> tuple[ImportedAction, Decimal, Decimal] | None:
    post = _POST_RE.fullmatch(body)
    if post is not None:
        amount = _parse_positive_money(
            post.group("amount"),
            currency,
            line=line,
            code="invalid_action_amount",
        )
        total = prior_total + amount
        live_total = (
            prior_live
            if post.group("post") == "the ante"
            else prior_live + amount
        )
        return (
            _action(
                sequence=sequence,
                actor_id=actor_id,
                action_type=_POST_TYPE[post.group("post")],
                amount=amount,
                total_committed=total,
                all_in=post.group("all_in") is not None,
                evidence=evidence,
                forced=True,
            ),
            total,
            live_total,
        )
    if body in {"folds", "checks"}:
        action_type: Literal["fold", "check"] = "fold" if body == "folds" else "check"
        return (
            _action(
                sequence=sequence,
                actor_id=actor_id,
                action_type=action_type,
                amount=None,
                total_committed=prior_total,
                all_in=False,
                evidence=evidence,
                forced=False,
            ),
            prior_total,
            prior_live,
        )
    call = _CALL_RE.fullmatch(body)
    if call is not None:
        amount = _parse_positive_money(
            call.group("amount"),
            currency,
            line=line,
            code="invalid_action_amount",
        )
        total = prior_total + amount
        live_total = prior_live + amount
        return (
            _action(
                sequence=sequence,
                actor_id=actor_id,
                action_type="call",
                amount=amount,
                total_committed=total,
                all_in=call.group("all_in") is not None,
                evidence=evidence,
                forced=False,
            ),
            total,
            live_total,
        )
    bet = _BET_RE.fullmatch(body)
    if bet is not None:
        amount = _parse_positive_money(
            bet.group("amount"),
            currency,
            line=line,
            code="invalid_action_amount",
        )
        total = prior_total + amount
        live_total = prior_live + amount
        return (
            _action(
                sequence=sequence,
                actor_id=actor_id,
                action_type="bet",
                amount=amount,
                total_committed=total,
                all_in=bet.group("all_in") is not None,
                evidence=evidence,
                forced=False,
            ),
            total,
            live_total,
        )
    raise_match = _RAISE_RE.fullmatch(body)
    if raise_match is not None:
        raise_by = _parse_positive_money(
            raise_match.group("raise_by"),
            currency,
            line=line,
            code="invalid_action_amount",
        )
        target = _parse_positive_money(
            raise_match.group("target"),
            currency,
            line=line,
            code="invalid_action_amount",
        )
        if target <= prior_live or target - current_wager != raise_by:
            raise _HandParseError(
                "inconsistent_raise",
                "The stated raise increment does not match the prior wager and target.",
                line_start=line,
            )
        return (
            _action(
                sequence=sequence,
                actor_id=actor_id,
                action_type="raise",
                amount=target - prior_live,
                total_committed=prior_total + target - prior_live,
                all_in=raise_match.group("all_in") is not None,
                evidence=evidence,
                forced=False,
            ),
            prior_total + target - prior_live,
            target,
        )
    return None


def _action(
    *,
    sequence: int,
    actor_id: str,
    action_type: str,
    amount: Decimal | None,
    total_committed: Decimal,
    all_in: bool,
    evidence: SourceEvidence,
    forced: bool,
) -> ImportedAction:
    origin = ActionOrigin(
        kind="forced_system" if forced else "unknown",
        basis="explicit_marker" if forced else "unresolved",
        confidence=Decimal("1") if forced else None,
        evidence=[evidence],
    )
    return ImportedAction(
        sequence=sequence,
        actor_id=actor_id,
        action_type=action_type,
        amount=amount,
        total_committed=total_committed,
        all_in=all_in,
        origin=origin,
        evidence=[evidence],
    )


def _showdown_entry(
    player_id: str,
    body: str,
    evidence: SourceEvidence,
    *,
    allow_rank_description: bool,
    line: int,
) -> ShowdownEntry | None:
    show = (
        _HISTORICAL_TOURNAMENT_SHOW_RE.fullmatch(body)
        if allow_rank_description
        else _SHOW_RE.fullmatch(body)
    )
    if show is not None:
        cards = _parse_cards(show.group("cards"), line=line)
        if len(cards) != 2:
            raise _HandParseError(
                "showdown_card_count",
                "A shown hand must contain exactly two cards.",
                line_start=line,
            )
        return ShowdownEntry(
            player_id=player_id,
            cards=cards,
            disposition="shown",
            evidence=[evidence],
        )
    if body.startswith("shows "):
        raise _HandParseError(
            "unsupported_showdown",
            "This PokerStars shown-hand syntax is unsupported.",
            line_start=line,
        )
    if body == "mucks hand":
        return ShowdownEntry(
            player_id=player_id,
            disposition="mucked",
            evidence=[evidence],
        )
    if body == "doesn't show hand":
        return ShowdownEntry(
            player_id=player_id,
            disposition="not_shown",
            evidence=[evidence],
        )
    return None


def _parse_board(value: str, *, expected_count: int, line: int) -> list[Card]:
    groups = re.findall(r"\[([^\]]+)\]", value)
    compact_groups = "".join(
        f"[{re.sub(r'\s+', '', group)}]" for group in groups
    )
    if not groups or compact_groups != re.sub(r"\s+", "", value):
        raise _HandParseError(
            "invalid_board",
            "A street marker contains unsupported board syntax.",
            line_start=line,
        )
    cards = [card for group in groups for card in _parse_cards(group, line=line)]
    if len(cards) != expected_count:
        raise _HandParseError(
            "board_card_count",
            f"This street requires exactly {expected_count} board cards.",
            line_start=line,
        )
    return cards


def _parse_cards(value: str, *, line: int) -> list[Card]:
    try:
        return [Card.from_code(card) for card in value.split()]
    except ValueError as exc:
        raise _HandParseError(
            "invalid_card",
            "A card code is invalid.",
            line_start=line,
        ) from exc


def _parse_money(value: str, currency: str | None, *, line: int) -> Decimal:
    symbol = value[0] if value and value[0] in _CURRENCY_SYMBOLS else None
    if symbol is not None:
        if currency is None:
            raise _HandParseError(
                "currency_mismatch",
                "Tournament chip amounts cannot carry a currency marker.",
                line_start=line,
            )
        if _CURRENCY_SYMBOLS[symbol] != currency:
            raise _HandParseError(
                "currency_mismatch",
                "A money symbol does not match the header currency.",
                line_start=line,
            )
    try:
        amount = Decimal(value.lstrip("$€£").replace(",", ""))
    except InvalidOperation as exc:
        raise _HandParseError(
            "invalid_amount",
            "A chip amount is invalid.",
            line_start=line,
        ) from exc
    if amount < 0:
        raise _HandParseError(
            "invalid_amount",
            "A chip amount cannot be negative.",
            line_start=line,
        )
    return amount


def _parse_positive_money(
    value: str,
    currency: str | None,
    *,
    line: int,
    code: str,
) -> Decimal:
    amount = _parse_money(value, currency, line=line)
    if amount <= 0:
        raise _HandParseError(
            code,
            "This source field requires a positive chip amount.",
            line_start=line,
        )
    return amount


def _parse_played_at(value: str, source_timezone: str, *, line: int) -> datetime:
    naive = datetime.strptime(value, "%Y/%m/%d %H:%M:%S")
    if source_timezone in {"UTC", "GMT"}:
        return naive.replace(tzinfo=timezone.utc)
    if naive.year < 2007:
        raise _HandParseError(
            "unsupported_source_time",
            "ET timestamps before the current US daylight-saving rules are unsupported.",
            line_start=line,
        )
    march_first = datetime(naive.year, 3, 1)
    march_first_sunday = 1 + (6 - march_first.weekday()) % 7
    dst_start = datetime(naive.year, 3, march_first_sunday + 7, 2)
    november_first = datetime(naive.year, 11, 1)
    november_first_sunday = 1 + (6 - november_first.weekday()) % 7
    dst_end = datetime(naive.year, 11, november_first_sunday, 2)
    if dst_start <= naive < dst_start + timedelta(hours=1) or (
        dst_end - timedelta(hours=1) <= naive < dst_end
    ):
        raise _HandParseError(
            "ambiguous_source_time",
            "The ET source time is ambiguous or nonexistent at a DST transition.",
            line_start=line,
        )
    is_daylight = dst_start + timedelta(hours=1) <= naive < (
        dst_end - timedelta(hours=1)
    )
    offset = timedelta(hours=-4 if is_daylight else -5)
    return naive.replace(tzinfo=timezone(offset, "EDT" if is_daylight else "EST"))


def _player_id(
    name: str,
    player_id_by_name: dict[str, str],
    *,
    line: int,
) -> str:
    try:
        return player_id_by_name[name]
    except KeyError as exc:
        raise _HandParseError(
            "unknown_player",
            "An action references a player without a seat declaration.",
            line_start=line,
        ) from exc


def _dealt_in_player_id(
    name: str,
    player_id_by_name: dict[str, str],
    *,
    sitting_out_player_ids: set[str],
    line: int,
    code: str = "actor_not_dealt_in",
    message: str = "A table action, showdown, or award must identify a dealt-in seat.",
) -> str:
    player_id = _player_id(name, player_id_by_name, line=line)
    if player_id in sitting_out_player_ids:
        raise _HandParseError(
            code,
            message,
            line_start=line,
            line_end=line,
        )
    return player_id


def _evidence(raw_source_id: str, line: _SourceLine) -> SourceEvidence:
    return SourceEvidence(
        raw_source_id=raw_source_id,
        line_start=line.number,
        line_end=line.number,
        excerpt=line.text[:1000],
    )


def _validate_known_cards(parsed_body: _ParsedBody) -> None:
    seen_codes: set[str] = set()
    for card in parsed_body.hero_cards:
        if card.code in seen_codes:
            assert parsed_body.hero_evidence is not None
            raise _HandParseError(
                "duplicate_known_card",
                "The hero holding cannot contain the same card twice.",
                line_start=parsed_body.hero_evidence.line_start,
                line_end=parsed_body.hero_evidence.line_end,
            )
        seen_codes.add(card.code)

    previous_board: list[Card] = []
    for street, evidence in zip(
        parsed_body.streets,
        parsed_body.board_evidence,
        strict=True,
    ):
        if not street.board_cards:
            continue
        assert evidence is not None
        if previous_board and (
            street.board_cards[: len(previous_board)] != previous_board
        ):
            raise _HandParseError(
                "board_prefix_mismatch",
                "A street board must preserve every card from the prior street.",
                line_start=evidence.line_start,
                line_end=evidence.line_end,
            )
        new_cards = street.board_cards[len(previous_board) :]
        for card in new_cards:
            if card.code in seen_codes:
                raise _HandParseError(
                    "duplicate_known_card",
                    "Hero and board cards must identify unique physical cards.",
                    line_start=evidence.line_start,
                    line_end=evidence.line_end,
                )
            seen_codes.add(card.code)
        previous_board = street.board_cards

    if parsed_body.results is None:
        return
    hero_entry = next(
        (
            entry
            for entry in parsed_body.results.showdown
            if entry.player_id == parsed_body.hero_player_id
        ),
        None,
    )
    if hero_entry is not None and hero_entry.cards:
        hero_codes = [card.code for card in hero_entry.cards]
        evidence = hero_entry.evidence[0]
        if len(hero_codes) != len(set(hero_codes)):
            raise _HandParseError(
                "duplicate_showdown_card",
                "A shown holding cannot contain the same card twice.",
                line_start=evidence.line_start,
                line_end=evidence.line_end,
            )
        if parsed_body.hero_cards:
            if set(hero_codes) != {
                card.code for card in parsed_body.hero_cards
            }:
                raise _HandParseError(
                    "hero_showdown_mismatch",
                    "The hero's shown cards must match the dealt holding.",
                    line_start=evidence.line_start,
                    line_end=evidence.line_end,
                )
        elif seen_codes.intersection(hero_codes):
            raise _HandParseError(
                "showdown_card_collision",
                "Shown cards cannot duplicate known board cards.",
                line_start=evidence.line_start,
                line_end=evidence.line_end,
            )
        seen_codes.update(hero_codes)

    for entry in parsed_body.results.showdown:
        if entry is hero_entry or not entry.cards:
            continue
        entry_codes = [card.code for card in entry.cards]
        evidence = entry.evidence[0]
        if len(entry_codes) != len(set(entry_codes)):
            raise _HandParseError(
                "duplicate_showdown_card",
                "A shown holding cannot contain the same card twice.",
                line_start=evidence.line_start,
                line_end=evidence.line_end,
            )
        if seen_codes.intersection(entry_codes):
            raise _HandParseError(
                "showdown_card_collision",
                "Shown holdings cannot duplicate any known card.",
                line_start=evidence.line_start,
                line_end=evidence.line_end,
            )
        seen_codes.update(entry_codes)


def _state_action_diagnostic(
    validation_error: ValidationError,
    *,
    identity: StableHandIdentity,
    chronology: SourceChronology,
    game: GameContext,
    button_seat: int,
    seats: list[ImportedSeat],
    parsed_body: _ParsedBody,
) -> tuple[str, str, SourceEvidence] | None:
    target = _recognized_state_action_issue(validation_error)
    if target is None:
        return None

    completed_streets: list[ImportedStreet] = []
    for street_index, street in enumerate(parsed_body.streets):
        if street_index > 0:
            boundary_street = ImportedStreet(
                street=street.street,
                board_cards=street.board_cards,
                actions=[],
            )
            try:
                ImportedHandState(
                    identity=identity,
                    chronology=chronology,
                    game=game,
                    button_seat=button_seat,
                    seats=seats,
                    hero_player_id=parsed_body.hero_player_id,
                    hero_cards=parsed_body.hero_cards,
                    streets=[*completed_streets, boundary_street],
                    results=None,
                )
            except ValidationError as boundary_error:
                if _recognized_state_action_issue(boundary_error) == target:
                    evidence = parsed_body.board_evidence[street_index]
                    assert evidence is not None
                    return (*target, evidence)
        for action_index, action in enumerate(street.actions):
            prefix_street = ImportedStreet(
                street=street.street,
                board_cards=street.board_cards,
                actions=street.actions[: action_index + 1],
            )
            try:
                ImportedHandState(
                    identity=identity,
                    chronology=chronology,
                    game=game,
                    button_seat=button_seat,
                    seats=seats,
                    hero_player_id=parsed_body.hero_player_id,
                    hero_cards=parsed_body.hero_cards,
                    streets=[*completed_streets, prefix_street],
                    results=None,
                )
            except ValidationError as prefix_error:
                if _recognized_state_action_issue(prefix_error) == target:
                    evidence = action.evidence[0]
                    return (*target, evidence)
        completed_streets.append(street)
    result_evidence = parsed_body.results_evidence
    if result_evidence is None and parsed_body.results is not None:
        result_sources = [
            source
            for item in [
                *parsed_body.results.showdown,
                *parsed_body.results.awards,
            ]
            for source in item.evidence
        ]
        if result_sources:
            result_evidence = min(
                result_sources,
                key=lambda source: (source.line_start, source.line_end),
            )
    if (
        result_evidence is not None
        and target[0]
        in {
            "incomplete_street",
            "missing_uncalled_return",
            "premature_results",
            "premature_street_transition",
        }
    ):
        return (*target, result_evidence)
    return None


def _recognized_state_action_issue(
    validation_error: ValidationError,
) -> tuple[str, str] | None:
    messages = [
        str(error["msg"])
        for error in validation_error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
    ]
    if any("an action is out of turn" in message for message in messages):
        return (
            "action_out_of_turn",
            "A player action is out of turn for the derived dealt-in seat ring.",
        )
    if any(
        "a call must match the outstanding wager" in message
        or "a call requires an outstanding wager" in message
        for message in messages
    ):
        return (
            "invalid_call",
            "A call requires an outstanding wager and must match it unless all-in.",
        )
    if any(
        "an actor cannot check while facing an outstanding wager" in message
        for message in messages
    ):
        return (
            "invalid_check",
            "A player cannot check while facing an outstanding wager.",
        )
    if any(
        "a bet requires no outstanding wager" in message for message in messages
    ):
        return (
            "invalid_bet",
            "A bet cannot be made while facing an outstanding wager.",
        )
    if any(
        "a bet must add chips above the prior commitment" in message
        or "a non-all-in bet must be at least the minimum full wager increment"
        in message
        for message in messages
    ):
        return (
            "invalid_bet",
            "A bet must add chips and meet the minimum full-wager increment unless all-in.",
        )
    if any(
        "a raise requires an outstanding wager" in message
        or "a raise must increase the outstanding wager" in message
        or "a raise is not allowed because short all-ins have not reopened betting"
        in message
        or "a non-all-in raise must be at least the last full bet or raise increment"
        in message
        for message in messages
    ):
        return (
            "invalid_raise",
            "A non-all-in raise must meet the minimum full-raise increment.",
        )
    if any(
        "an uncalled return must exactly settle the actor's unique unmatched live commitment"
        in message
        or "an uncalled return cannot occur while an opponent response remains pending"
        in message
        or "only the sole winner's same-street uncalled return is allowed after folds end the hand"
        in message
        for message in messages
    ):
        return (
            "invalid_uncalled_return",
            "An uncalled return must exactly settle the unique unmatched wager after responses end.",
        )
    if any(
        "a table decision is not allowed after every pot-eligible opponent is all-in"
        in message
        or "a bet or raise is not allowed when no opponent can respond" in message
        or "a table decision is not allowed after the known action round is complete"
        in message
        for message in messages
    ):
        return (
            "terminal_table_action",
            "A table decision is not allowed after actionable opposition has ended.",
        )
    if any(
        "a street cannot end before the known action round is complete" in message
        for message in messages
    ):
        return (
            "premature_street_transition",
            "A street cannot advance before the known action round is complete.",
        )
    if any(
        "a street cannot end while a non-folded, non-all-in player has not matched"
        in message
        for message in messages
    ):
        return (
            "incomplete_street",
            "A street cannot advance while an actionable player has not matched the wager.",
        )
    if any(
        "a street cannot end with a unique unmatched top wager" in message
        for message in messages
    ):
        return (
            "missing_uncalled_return",
            "A street with a unique unmatched top wager requires an uncalled return.",
        )
    if any(
        "a later street is not allowed after folds end the hand" in message
        for message in messages
    ):
        return (
            "street_after_hand_end",
            "A later street is not allowed after folds end the hand.",
        )
    if any(
        "results require the hand to reach a completed river or end by folds"
        in message
        or "results require completed river betting or a fold-ended terminal hand"
        in message
        for message in messages
    ):
        return (
            "premature_results",
            "Results require a completed river or a fold-ended terminal hand.",
        )
    if any(
        "all-in marker has cumulative commitment" in message
        for message in messages
    ):
        return (
            "invalid_all_in",
            "An all-in marker must exhaust the player's known starting stack.",
        )
    if any(
        "an actor cannot act after folding or going all-in" in message
        for message in messages
    ):
        return (
            "terminal_actor_action",
            "A player cannot act after folding or going all-in.",
        )
    if any(
        "exceeds known starting stack" in message
        for message in messages
    ):
        return (
            "action_exceeds_stack",
            "A chip action cannot exceed the player's known starting stack.",
        )
    return None


def _ante_structure(
    streets: list[ImportedStreet],
    seats: list[ImportedSeat],
) -> tuple[Decimal | None, Literal["per_player", "big_blind", "unknown"]]:
    posts = [
        action
        for action in streets[0].actions
        if action.action_type == "post_ante"
    ]
    if not posts:
        return Decimal(0), "unknown"
    post_evidence = [
        source
        for action in posts
        for source in action.evidence
    ]
    line_start = min(source.line_start for source in post_evidence)
    line_end = max(source.line_end for source in post_evidence)
    nominal_amounts = {
        action.amount for action in posts if not action.all_in
    }
    if len(nominal_amounts) != 1 or None in nominal_amounts:
        raise _HandParseError(
            "unsupported_ante_structure",
            "Ante posts require one known non-all-in amount to establish the nominal ante.",
            line_start=line_start,
            line_end=line_end,
        )
    amount = next(iter(nominal_amounts))
    assert amount is not None
    if any(
        action.amount is None
        or (action.all_in and action.amount > amount)
        or (not action.all_in and action.amount != amount)
        for action in posts
    ):
        raise _HandParseError(
            "unsupported_ante_structure",
            "Ante posts must match the nominal amount unless a shorter post is all-in.",
            line_start=line_start,
            line_end=line_end,
        )
    dealt_ids = {seat.player_id for seat in seats if seat.participation == "dealt_in"}
    poster_ids = {action.actor_id for action in posts}
    if len(poster_ids) != len(posts):
        raise _HandParseError(
            "unsupported_ante_structure",
            "Each dealt-in seat may post the configured ante at most once.",
            line_start=line_start,
            line_end=line_end,
        )
    big_blind = next(
        (
            action.actor_id
            for action in streets[0].actions
            if action.action_type == "post_big_blind"
        ),
        None,
    )
    if poster_ids == dealt_ids:
        return amount, "per_player"
    if poster_ids == {big_blind}:
        return amount, "big_blind"
    raise _HandParseError(
        "unsupported_ante_structure",
        "Ante posters do not match per-player or big-blind ante semantics.",
        line_start=line_start,
        line_end=line_end,
    )


def _validate_structural_blind_posts(
    parsed_body: _ParsedBody,
    seats: list[ImportedSeat],
    *,
    small_blind: Decimal,
    big_blind: Decimal,
) -> None:
    small_blind_actor = next(
        (
            seat.player_id
            for seat in seats
            if seat.position is not None
            and seat.position.display_label in {"BTN/SB", "SB"}
        ),
        None,
    )
    big_blind_actor = next(
        (
            seat.player_id
            for seat in seats
            if seat.position is not None
            and seat.position.display_label == "BB"
        ),
        None,
    )
    if small_blind_actor is None or big_blind_actor is None:
        line = parsed_body.hole_evidence.line_start
        raise _HandParseError(
            "unsupported_blind_structure",
            "The dealt-in seat ring does not establish both structural blinds.",
            line_start=line,
            line_end=line,
        )
    expected_actors = {
        "post_small_blind": small_blind_actor,
        "post_big_blind": big_blind_actor,
    }
    configured_amounts = {
        "post_small_blind": small_blind,
        "post_big_blind": big_blind,
    }
    seats_by_player = {seat.player_id: seat for seat in seats}
    seen: set[str] = set()
    forced_stack_exhausted: set[str] = set()

    for action in parsed_body.streets[0].actions:
        actor = seats_by_player[action.actor_id]
        if (
            action.action_type == "post_ante"
            and actor.starting_stack is not None
            and action.total_committed == actor.starting_stack
        ):
            forced_stack_exhausted.add(action.actor_id)
        if action.action_type not in configured_amounts:
            continue

        sources = action.evidence
        line_start = min(source.line_start for source in sources)
        line_end = max(source.line_end for source in sources)
        expected_actor = expected_actors[action.action_type]
        if action.actor_id != expected_actor:
            raise _HandParseError(
                "invalid_structural_blind",
                "A structural blind post must come from its derived dealt-in seat.",
                line_start=line_start,
                line_end=line_end,
            )
        if action.action_type in seen:
            raise _HandParseError(
                "invalid_structural_blind",
                "Each structural blind may be posted at most once.",
                line_start=line_start,
                line_end=line_end,
            )
        seen.add(action.action_type)

        configured_amount = configured_amounts[action.action_type]
        amount = action.amount
        stack_exceeded = (
            actor.starting_stack is not None
            and action.total_committed is not None
            and action.total_committed > actor.starting_stack
        )
        short_stack_exhausted = (
            amount is not None
            and amount < configured_amount
            and (
                (
                    actor.starting_stack is not None
                    and action.total_committed == actor.starting_stack
                )
                or (actor.starting_stack is None and action.all_in)
            )
        )
        if stack_exceeded or (
            amount != configured_amount and not short_stack_exhausted
        ):
            raise _HandParseError(
                "invalid_structural_blind",
                "A structural blind must match the header amount or exhaust a shorter stack.",
                line_start=line_start,
                line_end=line_end,
            )

    for action_type, expected_actor in expected_actors.items():
        if action_type in seen or expected_actor in forced_stack_exhausted:
            continue
        line = parsed_body.hole_evidence.line_start
        raise _HandParseError(
            "missing_structural_blind",
            "The forced-post section ended before every required structural blind was posted.",
            line_start=line,
            line_end=line,
        )


def _straddle_amount(streets: list[ImportedStreet]) -> Decimal | None:
    posts = [
        action
        for action in streets[0].actions
        if action.action_type == "post_straddle"
    ]
    if not posts:
        return None
    post_evidence = [
        source
        for action in posts
        for source in action.evidence
    ]
    if len(posts) != 1 or posts[0].amount is None or posts[0].all_in:
        raise _HandParseError(
            "unsupported_straddle_structure",
            "Exactly one non-all-in straddle is required to establish its nominal amount.",
            line_start=min(source.line_start for source in post_evidence),
            line_end=max(source.line_end for source in post_evidence),
        )
    return posts[0].amount


def _field_evidence(
    *,
    header: SourceEvidence,
    parsed_header: _ParsedHeader,
    parsed_seats: _ParsedSeats,
    parsed_body: _ParsedBody,
) -> dict[str, DetectedFieldEvidence]:
    evidence: dict[str, DetectedFieldEvidence] = {
        "/identity/site": _exact_field(header),
        "/identity/source_hand_id": _exact_field(header),
        "/game/variant": _exact_field(header),
        "/game/blinds/small_blind": _exact_field(header),
        "/game/blinds/big_blind": _exact_field(header),
        "/game/economics/kind": _exact_field(header),
        "/game/economics/currency": _exact_field(header),
        "/game/betting_limit": _exact_field(header),
        "/game/table_size": _exact_field(parsed_seats.table_evidence),
        "/button_seat": _exact_field(parsed_seats.table_evidence),
    }
    if parsed_header.is_historical_tournament:
        unresolved_time = DetectedFieldEvidence(
            confidence=Decimal(0),
            evidence=[header],
            warnings=[_UNRESOLVED_HISTORICAL_TIME_WARNING],
        )
        evidence["/chronology/played_at"] = unresolved_time
        evidence["/chronology/source_timezone"] = unresolved_time
        for pointer in (
            "/game/economics/tournament_id",
            "/game/economics/entry_buy_in",
            "/game/economics/entry_fee",
            "/game/economics/blind_level",
        ):
            evidence[pointer] = _exact_field(header)
        for index, seat_evidence in enumerate(parsed_seats.seat_evidence):
            evidence[f"/game/economics/remaining_stacks/{index}"] = _exact_field(
                seat_evidence
            )
    else:
        evidence["/chronology/played_at"] = _exact_field(header)
        evidence["/chronology/source_timezone"] = _exact_field(header)
    position_sources = [
        parsed_seats.table_evidence,
        *parsed_seats.seat_evidence,
    ]
    for index, seat_evidence in enumerate(parsed_seats.seat_evidence):
        evidence[f"/seats/{index}"] = _exact_field(seat_evidence)
        evidence[f"/seats/{index}/position"] = _exact_field(*position_sources)
    ante_sources = [
        source
        for action in parsed_body.streets[0].actions
        if action.action_type == "post_ante"
        for source in action.evidence
    ]
    if ante_sources:
        evidence["/game/blinds/ante"] = _exact_field(*ante_sources)
        evidence["/game/blinds/ante_mode"] = _exact_field(*ante_sources)
    else:
        evidence["/game/blinds/ante"] = _exact_field(parsed_body.hole_evidence)
        evidence["/game/blinds/ante_mode"] = _exact_field(
            parsed_body.hole_evidence
        )
    straddle_sources = [
        source
        for action in parsed_body.streets[0].actions
        if action.action_type == "post_straddle"
        for source in action.evidence
    ]
    if straddle_sources:
        evidence["/game/blinds/straddle"] = _exact_field(*straddle_sources)
    else:
        evidence["/game/blinds/straddle"] = _exact_field(
            parsed_body.hole_evidence
        )
    if parsed_body.hero_evidence is not None:
        evidence["/hero_player_id"] = _exact_field(parsed_body.hero_evidence)
        evidence["/hero_cards"] = _exact_field(parsed_body.hero_evidence)
    for street_index, board_source in enumerate(parsed_body.board_evidence):
        if board_source is not None:
            evidence[f"/streets/{street_index}/board_cards"] = _exact_field(
                board_source
            )
    for street_index, street_evidence in enumerate(parsed_body.action_evidence):
        for action_index, action_source in enumerate(street_evidence):
            evidence[
                f"/streets/{street_index}/actions/{action_index}"
            ] = _exact_field(action_source)
    if parsed_body.results is not None:
        for showdown_index, showdown_entry in enumerate(
            parsed_body.results.showdown
        ):
            evidence[f"/results/showdown/{showdown_index}"] = _exact_field(
                *showdown_entry.evidence
            )
        for award_index, award in enumerate(parsed_body.results.awards):
            evidence[f"/results/awards/{award_index}"] = _exact_field(
                *award.evidence
            )
    if parsed_body.results_evidence is not None:
        evidence["/results/stated_pot"] = _exact_field(
            parsed_body.results_evidence
        )
    if parsed_body.finish_evidence:
        evidence["/results"] = DetectedFieldEvidence(
            evidence=parsed_body.finish_evidence,
            warnings=[_UNMODELED_TOURNAMENT_FINISH_WARNING],
        )
    return evidence


def _exact_field(*sources: SourceEvidence) -> DetectedFieldEvidence:
    return DetectedFieldEvidence(
        confidence=Decimal("1"),
        evidence=list(sources),
    )
