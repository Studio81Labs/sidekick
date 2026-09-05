"""Offline, privacy-safe assessment of the PokerStars hand-history adapter."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Sequence, cast, get_args

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from app.domain.imported_hands import (
    GameContext,
    StatedPotSummary,
    StructuralPosition,
)
from app.domain.imported_hands.models import (
    ActionType,
    Identifier,
    OriginBasis,
    OriginKind,
    ParticipationStatus,
    StreetName,
)
from app.domain.poker import Card
from app.infrastructure.hand_history.pokerstars import (
    POKERSTARS_ADAPTER_ID,
    POKERSTARS_ADAPTER_VERSION,
    POKERSTARS_FORMAT_REVISION,
    PokerStarsHandDiagnostic,
    PokerStarsImportContext,
    PokerStarsParsedHand,
    parse_pokerstars_text,
)


MAX_CORPUS_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_CORPUS_SOURCE_BYTES = 16 * 1024 * 1024
MAX_CORPUS_BYTES = 512 * 1024 * 1024
MAX_CORPUS_CASES = 10_000
_ASSESSMENT_IMPORTED_AT = datetime(2000, 1, 1, tzinfo=timezone.utc)

CorpusTag = Literal[
    "ante",
    "automatic_action",
    "cash",
    "disconnect",
    "forced_system_action",
    "full_ring",
    "heads_up",
    "incomplete_hand",
    "player_selected_action",
    "rake",
    "showdown",
    "side_pot",
    "sit_out",
    "six_max",
    "timeout",
    "tournament",
    "uncalled_bet",
    "unknown_action",
]
LabeledCoverageTag = Literal["incomplete_hand"]
ExpectedDisposition = Literal[
    "clean",
    "reconciliation_failed",
    "reconciliation_indeterminate",
]
CaseActualOutcome = Literal["parsed", "rejected", "file_rejected", "missing"]
CaseIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        strict=True,
    ),
]
DiagnosticCode = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z][a-z0-9_]*$",
        strict=True,
    ),
]
Sha256 = Annotated[
    str,
    StringConstraints(pattern=r"^[a-f0-9]{64}$", strict=True),
]
PositiveInteger = Annotated[int, Field(ge=1, strict=True)]
NonNegativeInteger = Annotated[int, Field(ge=0, strict=True)]
NonNegativeDecimal = Annotated[
    Decimal,
    Field(ge=0, allow_inf_nan=False, strict=True),
]
PositiveDecimal = Annotated[
    Decimal,
    Field(gt=0, allow_inf_nan=False, strict=True),
]
FiniteDecimal = Annotated[
    Decimal,
    Field(allow_inf_nan=False, strict=True),
]


class CorpusAssessmentError(RuntimeError):
    """The corpus or its independent labels cannot be assessed safely."""


def _path_from_invocation(path: Path) -> Path:
    if path.is_absolute():
        return path
    invocation_root = os.environ.get("POKER_CORPUS_BASE_DIR")
    return Path(invocation_root) / path if invocation_root else path


def _same_source_timestamp(
    expected: datetime | None,
    actual: datetime | None,
) -> bool:
    if expected is None or actual is None:
        return expected is actual
    return (
        expected.replace(tzinfo=None) == actual.replace(tzinfo=None)
        and expected.utcoffset() == actual.utcoffset()
    )


class _AssessmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class PokerStarsExpectedSeat(_AssessmentModel):
    seat_number: PositiveInteger
    starting_stack: NonNegativeDecimal | None
    participation: ParticipationStatus
    position: StructuralPosition | None


class PokerStarsExpectedActionOrigin(_AssessmentModel):
    kind: OriginKind
    basis: OriginBasis
    confidence: Annotated[
        Decimal,
        Field(ge=0, le=1, allow_inf_nan=False, strict=True),
    ] | None
    semantics_revision: str | None = Field(
        min_length=1,
        max_length=160,
        strict=True,
    )
    automatic_reason: Literal[
        "timeout",
        "disconnect",
        "automation",
        "other",
        "unknown",
    ] | None
    evidence_lines: list[PositiveInteger] = Field(min_length=1)

    @field_validator("evidence_lines")
    @classmethod
    def validate_evidence_lines(cls, value: list[int]) -> list[int]:
        if value != sorted(set(value)):
            raise ValueError("expected origin evidence lines must be unique and sorted")
        return value

    @model_validator(mode="after")
    def validate_origin(self) -> PokerStarsExpectedActionOrigin:
        if self.basis == "user_confirmed":
            raise ValueError(
                "parser ground truth cannot contain user-confirmed action origins"
            )
        if (
            self.basis == "versioned_absence_semantics"
            and self.semantics_revision is None
        ):
            raise ValueError(
                "versioned absence semantics require a semantics revision"
            )
        if self.kind == "player_selected" and self.basis not in {
            "explicit_marker",
            "versioned_absence_semantics",
        }:
            raise ValueError("player-selected origins require affirmative evidence")
        if (self.kind == "unknown") != (self.basis == "unresolved"):
            raise ValueError("unknown and unresolved origin fields must agree")
        if (self.kind == "client_automatic") != (
            self.automatic_reason is not None
        ):
            raise ValueError(
                "client-automatic origins and automatic reasons must agree"
            )
        return self


class PokerStarsExpectedAction(_AssessmentModel):
    sequence: NonNegativeInteger
    actor_seat_number: PositiveInteger
    action_type: ActionType
    amount: PositiveDecimal | None
    total_committed: NonNegativeDecimal | None
    all_in: bool = Field(strict=True)
    origin: PokerStarsExpectedActionOrigin
    evidence_lines: list[PositiveInteger] = Field(min_length=1)

    @field_validator("evidence_lines")
    @classmethod
    def validate_evidence_lines(cls, value: list[int]) -> list[int]:
        if value != sorted(set(value)):
            raise ValueError("expected action evidence lines must be unique and sorted")
        return value

    @model_validator(mode="after")
    def validate_action(self) -> PokerStarsExpectedAction:
        forced_actions = {
            "post_ante",
            "post_small_blind",
            "post_big_blind",
            "post_straddle",
            "uncalled_return",
        }
        if self.action_type in {"fold", "check"} and self.amount is not None:
            raise ValueError("expected fold and check actions cannot have an amount")
        if self.all_in and self.action_type in {
            "fold",
            "check",
            "uncalled_return",
        }:
            raise ValueError(
                "expected fold, check, and return actions cannot be all-in"
            )
        if self.action_type in forced_actions and self.origin.kind != "forced_system":
            raise ValueError("expected forced actions require forced-system origin")
        if self.action_type not in forced_actions and self.origin.kind == "forced_system":
            raise ValueError("expected table actions cannot be forced-system actions")
        return self


class PokerStarsExpectedStreet(_AssessmentModel):
    street: StreetName
    board_cards: list[Card]
    actions: list[PokerStarsExpectedAction]

    @model_validator(mode="after")
    def validate_action_order(self) -> PokerStarsExpectedStreet:
        sequences = [action.sequence for action in self.actions]
        if sequences != list(range(len(sequences))):
            raise ValueError(
                "expected street action sequences must be contiguous from zero"
            )
        return self


class PokerStarsExpectedShowdown(_AssessmentModel):
    seat_number: PositiveInteger
    cards: list[Card] = Field(max_length=2)
    disposition: Literal["shown", "mucked", "not_shown", "unknown"]
    evidence_lines: list[PositiveInteger] = Field(min_length=1)

    @field_validator("evidence_lines")
    @classmethod
    def validate_evidence_lines(cls, value: list[int]) -> list[int]:
        if value != sorted(set(value)):
            raise ValueError("expected showdown evidence lines must be unique and sorted")
        return value


class PokerStarsExpectedAward(_AssessmentModel):
    seat_number: PositiveInteger
    amount: PositiveDecimal | None
    pot_index: NonNegativeInteger | None
    evidence_lines: list[PositiveInteger] = Field(min_length=1)

    @field_validator("evidence_lines")
    @classmethod
    def validate_evidence_lines(cls, value: list[int]) -> list[int]:
        if value != sorted(set(value)):
            raise ValueError("expected award evidence lines must be unique and sorted")
        return value


class PokerStarsExpectedPlayerResult(_AssessmentModel):
    seat_number: PositiveInteger
    net_result: FiniteDecimal | None
    total_collected: NonNegativeDecimal | None


class PokerStarsExpectedResults(_AssessmentModel):
    stated_pot: StatedPotSummary | None
    showdown: list[PokerStarsExpectedShowdown]
    awards: list[PokerStarsExpectedAward]
    players: list[PokerStarsExpectedPlayerResult]

    @model_validator(mode="after")
    def validate_unique_players(self) -> PokerStarsExpectedResults:
        showdown_seats = [item.seat_number for item in self.showdown]
        player_seats = [item.seat_number for item in self.players]
        if len(showdown_seats) != len(set(showdown_seats)):
            raise ValueError("expected showdown seats must be unique")
        if len(player_seats) != len(set(player_seats)):
            raise ValueError("expected player-result seats must be unique")
        return self


class PokerStarsExpectedParsedHand(_AssessmentModel):
    outcome: Literal["parsed"] = "parsed"
    disposition: ExpectedDisposition
    source_hand_id: Identifier
    played_at: AwareDatetime | None
    source_timezone: str | None = Field(
        min_length=1,
        max_length=80,
        strict=True,
    )
    source_session_id: str | None = Field(
        min_length=1,
        max_length=160,
        strict=True,
    )
    game: GameContext
    button_seat: PositiveInteger | None
    seats: list[PokerStarsExpectedSeat] = Field(min_length=2, max_length=10)
    hero_seat_number: PositiveInteger | None
    hero_cards: list[Card] = Field(max_length=2)
    streets: list[PokerStarsExpectedStreet] = Field(min_length=1, max_length=4)
    results: PokerStarsExpectedResults | None
    warnings: list[str]

    @model_validator(mode="after")
    def validate_complete_projection(self) -> PokerStarsExpectedParsedHand:
        seat_numbers = [seat.seat_number for seat in self.seats]
        if len(seat_numbers) != len(set(seat_numbers)):
            raise ValueError("expected seat numbers must be unique")
        if (
            self.button_seat is not None
            and self.button_seat not in seat_numbers
        ):
            raise ValueError("expected button seat must identify an expected seat")
        if (
            self.hero_seat_number is not None
            and self.hero_seat_number not in seat_numbers
        ):
            raise ValueError("expected hero seat must identify an expected seat")
        if self.hero_cards and self.hero_seat_number is None:
            raise ValueError("expected hero cards require an expected hero seat")
        if self.source_timezone is not None and self.played_at is None:
            raise ValueError("expected source timezone requires a played time")
        street_order = [
            {"preflop": 0, "flop": 1, "turn": 2, "river": 3}[street.street]
            for street in self.streets
        ]
        if street_order != list(range(len(street_order))):
            raise ValueError("expected streets must be unique and ordered from preflop")
        if any(
            action.actor_seat_number not in seat_numbers
            for street in self.streets
            for action in street.actions
        ):
            raise ValueError("expected actions must identify an expected seat")
        if self.results is not None and any(
            seat_number not in seat_numbers
            for seat_number in (
                *(
                    showdown.seat_number
                    for showdown in self.results.showdown
                ),
                *(award.seat_number for award in self.results.awards),
                *(player.seat_number for player in self.results.players),
            )
        ):
            raise ValueError("expected results must identify an expected seat")
        if self.results is not None and self.results.stated_pot is not None:
            if self.results.stated_pot.model_fields_set != set(
                type(self.results.stated_pot).model_fields
            ):
                raise ValueError("expected stated pot must label every field")
        if self.game.model_fields_set != set(type(self.game).model_fields):
            raise ValueError("expected game context must label every field")
        if self.game.blinds.model_fields_set != set(
            type(self.game.blinds).model_fields
        ):
            raise ValueError("expected blind structure must label every field")
        if self.game.economics.model_fields_set != set(
            type(self.game.economics).model_fields
        ):
            raise ValueError("expected economics must label every field")
        return self


class PokerStarsExpectedRejectedHand(_AssessmentModel):
    outcome: Literal["rejected"] = "rejected"
    source_hand_id: Identifier | None
    diagnostic_code: DiagnosticCode


ExpectedHand = Annotated[
    PokerStarsExpectedParsedHand | PokerStarsExpectedRejectedHand,
    Field(discriminator="outcome"),
]


class PokerStarsCorpusCase(_AssessmentModel):
    case_id: CaseIdentifier
    source_path: str = Field(min_length=1, max_length=255, strict=True)
    hand_ordinal: PositiveInteger
    tags: list[CorpusTag] = Field(min_length=1)
    expected: ExpectedHand

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        if "\\" in value or "\x00" in value:
            raise ValueError("corpus source_path must use a safe relative POSIX path")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("corpus source_path must use a safe relative POSIX path")
        return value

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[CorpusTag]) -> list[CorpusTag]:
        if value != sorted(set(value)):
            raise ValueError("corpus tags must be unique and sorted")
        return value

    @model_validator(mode="after")
    def validate_inferable_tags(self) -> PokerStarsCorpusCase:
        if self.expected.outcome == "rejected":
            return self
        expected = self.expected
        actions = [
            action
            for street in expected.streets
            for action in street.actions
        ]
        inferable = {
            "cash": expected.game.economics.kind == "cash",
            "tournament": expected.game.economics.kind == "tournament",
            "heads_up": expected.game.table_size == 2,
            "six_max": expected.game.table_size == 6,
            "full_ring": expected.game.table_size >= 7,
            "sit_out": any(
                seat.participation == "sitting_out" for seat in expected.seats
            ),
            "ante": (
                expected.game.blinds.ante is not None
                and expected.game.blinds.ante > 0
            ),
            "uncalled_bet": any(
                action.action_type == "uncalled_return" for action in actions
            ),
            "automatic_action": any(
                action.origin.kind == "client_automatic" for action in actions
            ),
            "player_selected_action": any(
                action.origin.kind == "player_selected" for action in actions
            ),
            "forced_system_action": any(
                action.origin.kind == "forced_system" for action in actions
            ),
            "unknown_action": any(
                action.origin.kind == "unknown" for action in actions
            ),
            "timeout": any(
                action.origin.automatic_reason == "timeout" for action in actions
            ),
            "disconnect": any(
                action.origin.automatic_reason == "disconnect" for action in actions
            ),
            "rake": (
                expected.results is not None
                and expected.results.stated_pot is not None
                and expected.results.stated_pot.rake is not None
                and expected.results.stated_pot.rake > 0
            ),
            "showdown": (
                expected.results is not None
                and bool(expected.results.showdown)
            ),
            "side_pot": (
                expected.results is not None
                and any(
                    award.pot_index is not None and award.pot_index > 0
                    for award in expected.results.awards
                )
            ),
        }
        tags = set(self.tags)
        if any((tag in tags) != applies for tag, applies in inferable.items()):
            raise ValueError(
                "corpus tags must exactly match every inferable ground-truth feature"
            )
        return self


class PokerStarsCorpusManifest(_AssessmentModel):
    schema_version: Literal["pokerstars-corpus-manifest/v1"]
    cases: list[PokerStarsCorpusCase] = Field(
        min_length=1,
        max_length=MAX_CORPUS_CASES,
    )

    @model_validator(mode="after")
    def validate_complete_case_index(self) -> PokerStarsCorpusManifest:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("corpus case_id values must be unique")
        source_hand_ids = [
            case.expected.source_hand_id
            for case in self.cases
            if case.expected.source_hand_id is not None
        ]
        if len(source_hand_ids) != len(set(source_hand_ids)):
            raise ValueError("corpus source hand IDs must be unique")
        ordered = [
            (case.source_path, case.hand_ordinal)
            for case in self.cases
        ]
        if ordered != sorted(ordered) or len(ordered) != len(set(ordered)):
            raise ValueError(
                "corpus cases must be unique and ordered by source_path then hand_ordinal"
            )
        ordinals_by_source: dict[str, list[int]] = {}
        for case in self.cases:
            ordinals_by_source.setdefault(case.source_path, []).append(
                case.hand_ordinal
            )
        if any(
            ordinals != list(range(1, len(ordinals) + 1))
            for ordinals in ordinals_by_source.values()
        ):
            raise ValueError(
                "every corpus source must label contiguous hand ordinals from one"
            )
        return self


class PokerStarsCorpusCaseResult(_AssessmentModel):
    case_ordinal: PositiveInteger
    expected_outcome: Literal["parsed", "rejected"]
    actual_outcome: CaseActualOutcome
    passed: bool = Field(strict=True)
    diagnostic_code: DiagnosticCode | None = None
    failure_codes: list[DiagnosticCode] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result(self) -> PokerStarsCorpusCaseResult:
        if self.passed == bool(self.failure_codes):
            raise ValueError(
                "a passing case has no failures and a failing case has at least one"
            )
        if (self.actual_outcome in {"rejected", "file_rejected"}) != (
            self.diagnostic_code is not None
        ):
            raise ValueError(
                "only parser and file rejections carry a diagnostic code"
            )
        return self


class PokerStarsCorpusAssessmentReport(_AssessmentModel):
    schema_version: Literal["pokerstars-corpus-assessment/v1"] = (
        "pokerstars-corpus-assessment/v1"
    )
    adapter_id: Literal["pokerstars"]
    adapter_version: str
    format_revision: str
    corpus_fingerprint: Sha256
    total_cases: PositiveInteger
    expected_parse_cases: NonNegativeInteger
    clean_cases: NonNegativeInteger
    clean_parse_rate: Annotated[
        float,
        Field(ge=0, le=1, allow_inf_nan=False, strict=True),
    ]
    expected_rejection_cases: NonNegativeInteger
    correctly_rejected_cases: NonNegativeInteger
    passed_cases: NonNegativeInteger
    failed_cases: NonNegativeInteger
    reconciliation_counts: dict[str, NonNegativeInteger]
    diagnostic_counts: dict[str, NonNegativeInteger]
    labeled_tag_counts: dict[str, PositiveInteger]
    verified_parse_tag_counts: dict[str, PositiveInteger]
    economics_counts: dict[str, PositiveInteger]
    table_size_counts: dict[str, PositiveInteger]
    cases: list[PokerStarsCorpusCaseResult]

    @model_validator(mode="after")
    def validate_counts(self) -> PokerStarsCorpusAssessmentReport:
        if self.expected_parse_cases + self.expected_rejection_cases != self.total_cases:
            raise ValueError("assessment case classes must sum to total_cases")
        if self.passed_cases + self.failed_cases != self.total_cases:
            raise ValueError("assessment outcomes must sum to total_cases")
        if self.clean_cases > self.expected_parse_cases:
            raise ValueError("clean cases cannot exceed expected parse cases")
        if self.correctly_rejected_cases > self.expected_rejection_cases:
            raise ValueError(
                "correctly rejected cases cannot exceed expected rejection cases"
            )
        expected_rate = self.clean_cases / self.total_cases
        if abs(self.clean_parse_rate - expected_rate) > 1e-12:
            raise ValueError("clean_parse_rate must match its counts")
        if len(self.cases) != self.total_cases:
            raise ValueError("assessment must include one redacted result per case")
        if [case.case_ordinal for case in self.cases] != list(
            range(1, self.total_cases + 1)
        ):
            raise ValueError("assessment case ordinals must be contiguous from one")
        actual_passed = sum(case.passed for case in self.cases)
        if actual_passed != self.passed_cases:
            raise ValueError("assessment case results must match passed_cases")
        if any(
            count > self.labeled_tag_counts.get(tag, 0)
            for tag, count in self.verified_parse_tag_counts.items()
        ):
            raise ValueError(
                "verified parsed tag counts cannot exceed labeled tag counts"
            )
        return self


def load_pokerstars_corpus_manifest(
    manifest_path: Path,
    *,
    max_manifest_bytes: int = MAX_CORPUS_MANIFEST_BYTES,
) -> PokerStarsCorpusManifest:
    try:
        size = manifest_path.stat().st_size
        if size > max_manifest_bytes:
            raise CorpusAssessmentError("PokerStars corpus manifest is too large")
        payload = manifest_path.read_bytes()
    except OSError as exc:
        raise CorpusAssessmentError(
            "Could not read PokerStars corpus manifest"
        ) from exc
    if len(payload) > max_manifest_bytes:
        raise CorpusAssessmentError("PokerStars corpus manifest is too large")
    try:
        return PokerStarsCorpusManifest.model_validate_json(payload)
    except ValidationError as exc:
        raise CorpusAssessmentError("PokerStars corpus manifest is invalid") from exc


def assess_pokerstars_corpus(
    manifest_path: Path,
    *,
    corpus_root: Path | None = None,
    max_source_bytes: int = MAX_CORPUS_SOURCE_BYTES,
    max_corpus_bytes: int = MAX_CORPUS_BYTES,
) -> PokerStarsCorpusAssessmentReport:
    manifest = load_pokerstars_corpus_manifest(manifest_path)
    root = (corpus_root or manifest_path.parent).resolve()
    sources: dict[str, str] = {}
    source_digests: set[str] = set()
    total_bytes = 0
    for source_ordinal, source_path in enumerate(
        sorted({case.source_path for case in manifest.cases}),
        start=1,
    ):
        candidate = (root / source_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise CorpusAssessmentError(
                f"Corpus source {source_ordinal} escapes the corpus root"
            ) from exc
        try:
            size = candidate.stat().st_size
            if size > max_source_bytes:
                raise CorpusAssessmentError(
                    f"Corpus source {source_ordinal} is too large"
                )
            payload = candidate.read_bytes()
        except OSError as exc:
            raise CorpusAssessmentError(
                f"Could not read corpus source {source_ordinal}"
            ) from exc
        if len(payload) > max_source_bytes:
            raise CorpusAssessmentError(
                f"Corpus source {source_ordinal} is too large"
            )
        source_digest = sha256(payload).hexdigest()
        if source_digest in source_digests:
            raise CorpusAssessmentError(
                f"Corpus source {source_ordinal} duplicates another source"
            )
        source_digests.add(source_digest)
        total_bytes += len(payload)
        if total_bytes > max_corpus_bytes:
            raise CorpusAssessmentError("PokerStars corpus is too large")
        try:
            sources[source_path] = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CorpusAssessmentError(
                f"Corpus source {source_ordinal} is not valid UTF-8"
            ) from exc

    corpus_fingerprint = _corpus_fingerprint(manifest, sources)
    cases_by_source: dict[str, list[tuple[int, PokerStarsCorpusCase]]] = {}
    for case_ordinal, case in enumerate(manifest.cases, start=1):
        cases_by_source.setdefault(case.source_path, []).append(
            (case_ordinal, case)
        )

    case_results: list[PokerStarsCorpusCaseResult] = []
    reconciliation_counts: Counter[str] = Counter()
    diagnostic_counts: Counter[str] = Counter()
    for source_ordinal, source_path in enumerate(sorted(cases_by_source), start=1):
        parsed = parse_pokerstars_text(
            sources[source_path],
            context=PokerStarsImportContext(
                import_id=f"corpus-assessment:{source_ordinal}",
                imported_at=_ASSESSMENT_IMPORTED_AT,
                source_filename=None,
            ),
        )
        hands = {hand.hand_ordinal: hand for hand in parsed.hands}
        if len(hands) != len(parsed.hands):
            raise CorpusAssessmentError(
                f"Corpus source {source_ordinal} produced duplicate parsed hand ordinals"
            )
        diagnostics_by_ordinal: dict[int, PokerStarsHandDiagnostic] = {}
        file_diagnostics: list[str] = []
        for diagnostic in parsed.diagnostics:
            diagnostic_counts[diagnostic.code] += 1
            if diagnostic.hand_ordinal is None:
                file_diagnostics.append(diagnostic.code)
            elif diagnostic.hand_ordinal in diagnostics_by_ordinal:
                raise CorpusAssessmentError(
                    f"Corpus source {source_ordinal} produced duplicate diagnostics"
                )
            else:
                diagnostics_by_ordinal[diagnostic.hand_ordinal] = diagnostic
        if set(hands).intersection(diagnostics_by_ordinal):
            raise CorpusAssessmentError(
                f"Corpus source {source_ordinal} produced conflicting hand outcomes"
            )
        for hand in parsed.hands:
            reconciliation_counts[hand.reconciliation.status] += 1

        expected_ordinals = {
            case.hand_ordinal for _, case in cases_by_source[source_path]
        }
        actual_ordinals = set(hands) | set(diagnostics_by_ordinal)
        if not actual_ordinals.issubset(expected_ordinals):
            raise CorpusAssessmentError(
                f"Corpus source {source_ordinal} contains an unlabeled hand ordinal"
            )

        for case_ordinal, case in cases_by_source[source_path]:
            case_results.append(
                _assess_case(
                    case_ordinal,
                    case,
                    hand=hands.get(case.hand_ordinal),
                    diagnostic=diagnostics_by_ordinal.get(case.hand_ordinal),
                    file_diagnostic_code=(
                        sorted(file_diagnostics)[0] if file_diagnostics else None
                    ),
                )
            )

    expected_parse_cases = sum(
        case.expected.outcome == "parsed" for case in manifest.cases
    )
    expected_rejection_cases = len(manifest.cases) - expected_parse_cases
    passed_cases = sum(result.passed for result in case_results)
    clean_cases = sum(
        result.passed
        and case.expected.outcome == "parsed"
        and case.expected.disposition == "clean"
        for case, result in zip(manifest.cases, case_results, strict=True)
    )
    correctly_rejected_cases = sum(
        result.passed and case.expected.outcome == "rejected"
        for case, result in zip(manifest.cases, case_results, strict=True)
    )
    labeled_tag_counts = Counter(
        tag for case in manifest.cases for tag in case.tags
    )
    verified_parse_tag_counts = Counter(
        tag
        for case, result in zip(manifest.cases, case_results, strict=True)
        if case.expected.outcome == "parsed" and result.passed
        for tag in case.tags
    )
    economics_counts = Counter(
        case.expected.game.economics.kind
        for case in manifest.cases
        if case.expected.outcome == "parsed"
    )
    table_size_counts = Counter(
        str(case.expected.game.table_size)
        for case in manifest.cases
        if case.expected.outcome == "parsed"
    )
    return PokerStarsCorpusAssessmentReport(
        adapter_id=POKERSTARS_ADAPTER_ID,
        adapter_version=POKERSTARS_ADAPTER_VERSION,
        format_revision=POKERSTARS_FORMAT_REVISION,
        corpus_fingerprint=corpus_fingerprint,
        total_cases=len(manifest.cases),
        expected_parse_cases=expected_parse_cases,
        clean_cases=clean_cases,
        clean_parse_rate=clean_cases / len(manifest.cases),
        expected_rejection_cases=expected_rejection_cases,
        correctly_rejected_cases=correctly_rejected_cases,
        passed_cases=passed_cases,
        failed_cases=len(manifest.cases) - passed_cases,
        reconciliation_counts=_sorted_counts(reconciliation_counts),
        diagnostic_counts=_sorted_counts(diagnostic_counts),
        labeled_tag_counts=_sorted_counts(labeled_tag_counts),
        verified_parse_tag_counts=_sorted_counts(verified_parse_tag_counts),
        economics_counts=_sorted_counts(economics_counts),
        table_size_counts=_sorted_counts(table_size_counts),
        cases=case_results,
    )


def _corpus_fingerprint(
    manifest: PokerStarsCorpusManifest,
    sources: dict[str, str],
) -> str:
    digest = sha256()
    manifest_payload = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest.update(len(manifest_payload).to_bytes(8, "big"))
    digest.update(manifest_payload)
    for source_path in sorted(sources):
        path_payload = source_path.encode("utf-8")
        source_payload = sources[source_path].encode("utf-8")
        digest.update(len(path_payload).to_bytes(8, "big"))
        digest.update(path_payload)
        digest.update(len(source_payload).to_bytes(8, "big"))
        digest.update(source_payload)
    return digest.hexdigest()


def _assess_case(
    case_ordinal: int,
    case: PokerStarsCorpusCase,
    *,
    hand: PokerStarsParsedHand | None,
    diagnostic: PokerStarsHandDiagnostic | None,
    file_diagnostic_code: str | None,
) -> PokerStarsCorpusCaseResult:
    expected_outcome = case.expected.outcome
    if file_diagnostic_code is not None:
        return PokerStarsCorpusCaseResult(
            case_ordinal=case_ordinal,
            expected_outcome=expected_outcome,
            actual_outcome="file_rejected",
            passed=False,
            diagnostic_code=file_diagnostic_code,
            failure_codes=["file_rejection"],
        )
    if hand is not None:
        if expected_outcome == "rejected":
            return PokerStarsCorpusCaseResult(
                case_ordinal=case_ordinal,
                expected_outcome=expected_outcome,
                actual_outcome="parsed",
                passed=False,
                failure_codes=["unexpected_parse"],
            )
        failures = _parsed_hand_failure_codes(case, hand)
        return PokerStarsCorpusCaseResult(
            case_ordinal=case_ordinal,
            expected_outcome=expected_outcome,
            actual_outcome="parsed",
            passed=not failures,
            failure_codes=failures,
        )
    if diagnostic is not None:
        if expected_outcome == "rejected" and (
            case.expected.diagnostic_code == diagnostic.code
            and case.expected.source_hand_id == diagnostic.source_hand_id
        ):
            return PokerStarsCorpusCaseResult(
                case_ordinal=case_ordinal,
                expected_outcome=expected_outcome,
                actual_outcome="rejected",
                passed=True,
                diagnostic_code=diagnostic.code,
            )
        return PokerStarsCorpusCaseResult(
            case_ordinal=case_ordinal,
            expected_outcome=expected_outcome,
            actual_outcome="rejected",
            passed=False,
            diagnostic_code=diagnostic.code,
            failure_codes=[
                "unexpected_rejection"
                if expected_outcome == "parsed"
                else (
                    "diagnostic_mismatch"
                    if case.expected.diagnostic_code != diagnostic.code
                    else "rejection_identity_mismatch"
                )
            ],
        )
    return PokerStarsCorpusCaseResult(
        case_ordinal=case_ordinal,
        expected_outcome=expected_outcome,
        actual_outcome="missing",
        passed=False,
        failure_codes=["missing_result"],
    )


def _parsed_hand_failure_codes(
    case: PokerStarsCorpusCase,
    hand: PokerStarsParsedHand,
) -> list[DiagnosticCode]:
    assert isinstance(case.expected, PokerStarsExpectedParsedHand)
    expected = case.expected
    state = hand.candidate.detection.state
    detection = hand.candidate.detection
    raw = hand.candidate.raw
    failures: list[DiagnosticCode] = []
    if expected.disposition != hand.disposition:
        failures.append("disposition_mismatch")
    if (
        not _same_source_timestamp(
            expected.played_at,
            state.chronology.played_at,
        )
        or expected.source_timezone != state.chronology.source_timezone
        or expected.source_session_id != state.chronology.source_session_id
    ):
        failures.append("chronology_mismatch")
    if (
        hand.hand_ordinal != case.hand_ordinal
        or state.chronology.hand_ordinal != case.hand_ordinal
        or raw.chronology.hand_ordinal != case.hand_ordinal
        or raw.chronology != state.chronology
        or raw.identity != state.identity
        or state.identity.site != "pokerstars"
        or expected.source_hand_id != state.identity.source_hand_id
        or raw.provenance.source_kind != "hand_history"
        or raw.provenance.adapter_id != POKERSTARS_ADAPTER_ID
        or raw.provenance.adapter_version != POKERSTARS_ADAPTER_VERSION
        or raw.provenance.format_revision != POKERSTARS_FORMAT_REVISION
        or raw.provenance.source_filename is not None
        or raw.provenance.imported_at != _ASSESSMENT_IMPORTED_AT
        or detection.raw_source_id != raw.raw_source_id
        or detection.detector_id != POKERSTARS_ADAPTER_ID
        or detection.detector_version != POKERSTARS_ADAPTER_VERSION
        or detection.detected_at != _ASSESSMENT_IMPORTED_AT
    ):
        failures.append("provenance_mismatch")
    if expected.game != state.game:
        failures.append("game_mismatch")
    if expected.button_seat != state.button_seat:
        failures.append("button_mismatch")

    actual_seats = [
        PokerStarsExpectedSeat(
            seat_number=seat.seat_number,
            starting_stack=seat.starting_stack,
            participation=seat.participation,
            position=seat.position,
        )
        for seat in state.seats
    ]
    if expected.seats != actual_seats:
        failures.append("seats_mismatch")

    seat_by_player = {
        seat.player_id: seat.seat_number for seat in state.seats
    }
    actual_hero_seat = (
        seat_by_player.get(state.hero_player_id)
        if state.hero_player_id is not None
        else None
    )
    if (
        expected.hero_seat_number != actual_hero_seat
        or expected.hero_cards != state.hero_cards
    ):
        failures.append("hero_mismatch")

    expected_street_headers = [
        (street.street, street.board_cards) for street in expected.streets
    ]
    actual_street_headers = [
        (street.street, street.board_cards) for street in state.streets
    ]
    if expected_street_headers != actual_street_headers:
        failures.append("streets_mismatch")

    expected_actions = [
        (
            street.street,
            action.sequence,
            action.actor_seat_number,
            action.action_type,
            action.amount,
            action.total_committed,
            action.all_in,
        )
        for street in expected.streets
        for action in street.actions
    ]
    actual_actions = [
        (
            street.street,
            action.sequence,
            seat_by_player.get(action.actor_id),
            action.action_type,
            action.amount,
            action.total_committed,
            action.all_in,
        )
        for street in state.streets
        for action in street.actions
    ]
    if expected_actions != actual_actions:
        failures.append("actions_mismatch")

    expected_origins = [
        (
            action.origin.kind,
            action.origin.basis,
            action.origin.confidence,
            action.origin.semantics_revision,
            action.origin.automatic_reason,
        )
        for street in expected.streets
        for action in street.actions
    ]
    actual_origins = [
        (
            action.origin.kind,
            action.origin.basis,
            action.origin.confidence,
            action.origin.semantics_revision,
            action.origin.automatic_reason,
        )
        for street in state.streets
        for action in street.actions
    ]
    if expected_origins != actual_origins:
        failures.append("action_origins_mismatch")

    expected_evidence = [
        (action.evidence_lines, action.origin.evidence_lines)
        for street in expected.streets
        for action in street.actions
    ]
    actual_evidence = [
        (
            [item.line_start for item in action.evidence],
            [item.line_start for item in action.origin.evidence],
        )
        for street in state.streets
        for action in street.actions
    ]
    if expected_evidence != actual_evidence:
        failures.append("action_evidence_mismatch")

    actual_results = None
    if state.results is not None:
        actual_results = PokerStarsExpectedResults(
            stated_pot=state.results.stated_pot,
            showdown=[
                PokerStarsExpectedShowdown(
                    seat_number=seat_by_player[item.player_id],
                    cards=item.cards,
                    disposition=item.disposition,
                    evidence_lines=[
                        evidence.line_start for evidence in item.evidence
                    ],
                )
                for item in state.results.showdown
            ],
            awards=[
                PokerStarsExpectedAward(
                    seat_number=seat_by_player[item.player_id],
                    amount=item.amount,
                    pot_index=item.pot_index,
                    evidence_lines=[
                        evidence.line_start for evidence in item.evidence
                    ],
                )
                for item in state.results.awards
            ],
            players=[
                PokerStarsExpectedPlayerResult(
                    seat_number=seat_by_player[item.player_id],
                    net_result=item.net_result,
                    total_collected=item.total_collected,
                )
                for item in state.results.players
            ],
        )
    if expected.results != actual_results:
        failures.append("results_mismatch")
    if expected.warnings != hand.candidate.detection.warnings:
        failures.append("warnings_mismatch")
    return failures


def _sorted_counts(counts: Counter[str]) -> dict[str, int]:
    return {key: counts[key] for key in sorted(counts)}


def format_pokerstars_corpus_report(
    report: PokerStarsCorpusAssessmentReport,
) -> str:
    lines = [
        "PokerStars corpus assessment",
        f"Adapter: {report.adapter_id} {report.adapter_version}",
        f"Format: {report.format_revision}",
        f"Corpus fingerprint: {report.corpus_fingerprint}",
        f"Cases: {report.passed_cases}/{report.total_cases} matched ground truth",
        (
            "Clean corpus parses:"
            f" {report.clean_cases}/{report.total_cases}"
            f" ({report.clean_parse_rate:.1%})"
        ),
        (
            "Expected rejections:"
            f" {report.correctly_rejected_cases}/{report.expected_rejection_cases}"
        ),
        "Labeled composition tags:",
    ]
    lines.extend(
        f"  {tag}: {count}"
        for tag, count in report.labeled_tag_counts.items()
    )
    lines.append("Verified parsed coverage tags:")
    lines.extend(
        f"  {tag}: {count}"
        for tag, count in report.verified_parse_tag_counts.items()
    )
    if report.diagnostic_counts:
        lines.append("Parser diagnostics:")
        lines.extend(
            f"  {code}: {count}"
            for code, count in report.diagnostic_counts.items()
        )
    failed = [case for case in report.cases if not case.passed]
    if failed:
        lines.append("Cases needing review:")
        lines.extend(
            f"  case {case.case_ordinal}: {', '.join(case.failure_codes)}"
            for case in failed
        )
    return "\n".join(lines)


def _accuracy_threshold(value: str) -> float:
    try:
        threshold = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number between 0 and 1") from exc
    if not 0 <= threshold <= 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return threshold


def _positive_integer(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if count <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return count


def _tag_count_requirement(value: str) -> tuple[CorpusTag, int]:
    raw_tag, separator, raw_count = value.partition("=")
    if not separator or not raw_tag or not raw_count:
        raise argparse.ArgumentTypeError("must use TAG=COUNT")
    allowed = set(get_args(CorpusTag))
    if raw_tag not in allowed:
        raise argparse.ArgumentTypeError(f"unknown corpus tag: {raw_tag}")
    return cast(CorpusTag, raw_tag), _positive_integer(raw_count)


def _labeled_tag_count_requirement(
    value: str,
) -> tuple[LabeledCoverageTag, int]:
    tag, count = _tag_count_requirement(value)
    if tag not in get_args(LabeledCoverageTag):
        raise argparse.ArgumentTypeError(
            "labeled-only coverage gates support incomplete_hand"
        )
    return cast(LabeledCoverageTag, tag), count


def _sha256(value: str) -> str:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise argparse.ArgumentTypeError("must be a lowercase SHA-256 digest")
    return value


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Assess the PokerStars adapter against a locally held, independently "
            "labeled corpus without emitting source identifiers or content."
        ),
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--corpus-root",
        type=Path,
        help="Root for manifest source_path values (defaults to the manifest directory)",
    )
    parser.add_argument(
        "--minimum-cases",
        type=_positive_integer,
        help="Fail when the manifest has fewer labeled cases",
    )
    parser.add_argument(
        "--minimum-clean-parse-rate",
        type=_accuracy_threshold,
        help="Fail when clean parses across all labeled hands are below this ratio",
    )
    parser.add_argument(
        "--minimum-tag-count",
        action="append",
        type=_tag_count_requirement,
        default=[],
        metavar="TAG=COUNT",
        help="Repeat to require a minimum verified parsed count for a coverage tag",
    )
    parser.add_argument(
        "--minimum-labeled-tag-count",
        action="append",
        type=_labeled_tag_count_requirement,
        default=[],
        metavar="INCOMPLETE_HAND=COUNT",
        help=(
            "Repeat to require independently reviewed incomplete-hand labels,"
            " including expected rejections"
        ),
    )
    parser.add_argument(
        "--expected-corpus-fingerprint",
        type=_sha256,
        help="Fail if source bytes or ground-truth labels changed",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write the complete privacy-safe report as JSON",
    )
    return parser


def _requirements(
    values: list[tuple[CorpusTag, int]],
    *,
    option_name: str,
) -> dict[CorpusTag, int]:
    requirements: dict[CorpusTag, int] = {}
    for tag, count in values:
        if tag in requirements:
            raise CorpusAssessmentError(
                f"{option_name} repeats tag {tag}"
            )
        requirements[tag] = count
    return requirements


def _threshold_failures(
    report: PokerStarsCorpusAssessmentReport,
    *,
    minimum_cases: int | None,
    minimum_clean_parse_rate: float | None,
    minimum_tag_counts: dict[CorpusTag, int],
    minimum_labeled_tag_counts: dict[CorpusTag, int],
    expected_corpus_fingerprint: str | None,
) -> list[str]:
    failures: list[str] = []
    if report.failed_cases:
        failures.append(
            f"Assessment has {report.failed_cases} ground-truth mismatch(es)"
        )
    if minimum_cases is not None and report.total_cases < minimum_cases:
        failures.append(
            f"Corpus has {report.total_cases} case(s), below the minimum {minimum_cases}"
        )
    if (
        minimum_clean_parse_rate is not None
        and report.clean_parse_rate < minimum_clean_parse_rate
    ):
        failures.append(
            f"Clean parse rate {report.clean_parse_rate:.1%} is below the minimum"
            f" {minimum_clean_parse_rate:.1%}"
        )
    for tag, minimum in minimum_tag_counts.items():
        count = report.verified_parse_tag_counts.get(tag, 0)
        if count < minimum:
            failures.append(
                f"Verified parsed corpus tag {tag} has {count} case(s),"
                f" below the minimum {minimum}"
            )
    for tag, minimum in minimum_labeled_tag_counts.items():
        count = report.labeled_tag_counts.get(tag, 0)
        if count < minimum:
            failures.append(
                f"Labeled corpus tag {tag} has {count} case(s),"
                f" below the minimum {minimum}"
            )
    if (
        expected_corpus_fingerprint is not None
        and report.corpus_fingerprint != expected_corpus_fingerprint
    ):
        failures.append("Corpus fingerprint does not match the expected digest")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    try:
        minimum_tag_counts = _requirements(
            args.minimum_tag_count,
            option_name="--minimum-tag-count",
        )
        minimum_labeled_tag_counts = _requirements(
            args.minimum_labeled_tag_count,
            option_name="--minimum-labeled-tag-count",
        )
        report = assess_pokerstars_corpus(
            _path_from_invocation(args.manifest),
            corpus_root=(
                _path_from_invocation(args.corpus_root)
                if args.corpus_root is not None
                else None
            ),
        )
    except CorpusAssessmentError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(format_pokerstars_corpus_report(report))
    failures = _threshold_failures(
        report,
        minimum_cases=args.minimum_cases,
        minimum_clean_parse_rate=args.minimum_clean_parse_rate,
        minimum_tag_counts=minimum_tag_counts,
        minimum_labeled_tag_counts=minimum_labeled_tag_counts,
        expected_corpus_fingerprint=args.expected_corpus_fingerprint,
    )
    for failure in failures:
        print(failure, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
