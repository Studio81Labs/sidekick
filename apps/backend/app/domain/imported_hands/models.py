"""Site-agnostic contracts for detected and player-approved imported hands.

These models deliberately do not reuse the V1 screenshot ``CanonicalState``.
An imported hand carries a lossless ordered action stream and has its own
revision/deletion lifecycle before it can become learning evidence.
"""

from __future__ import annotations

import json
from hashlib import sha256
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SerializerFunctionWrapHandler,
    StringConstraints,
    ValidationError,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic_core import PydanticSerializationError

from app.domain.poker import Card


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256, strict=True),
]
Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]*$",
        strict=True,
    ),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$", strict=True)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, allow_inf_nan=False, strict=True)]
PositiveDecimal = Annotated[Decimal, Field(gt=0, allow_inf_nan=False, strict=True)]
UnitIntervalDecimal = Annotated[
    Decimal,
    Field(ge=0, le=1, allow_inf_nan=False, strict=True),
]
PositiveInteger = Annotated[int, Field(ge=1, strict=True)]
NonNegativeInteger = Annotated[int, Field(ge=0, strict=True)]

ParticipationStatus = Literal["dealt_in", "sitting_out", "not_dealt", "unknown"]
AnteMode = Literal["per_player", "big_blind", "unknown"]
GameVariant = Literal["texas_holdem"]
BettingLimit = Literal["no_limit", "pot_limit", "fixed_limit", "unknown"]
TableSize = Annotated[int, Field(ge=2, le=10, strict=True)]
StreetName = Literal["preflop", "flop", "turn", "river"]
ActionType = Literal[
    "post_ante",
    "post_small_blind",
    "post_big_blind",
    "post_straddle",
    "fold",
    "check",
    "bet",
    "call",
    "raise",
    "uncalled_return",
]
OriginKind = Literal[
    "player_selected",
    "forced_system",
    "client_automatic",
    "unknown",
]
OriginBasis = Literal[
    "explicit_marker",
    "versioned_absence_semantics",
    "user_confirmed",
    "unresolved",
]
LifecycleStatus = Literal[
    "pending_review",
    "active",
    "withdrawn",
    "rejected",
    "deletion_pending",
    "deleted",
]
SeatDecisionStatus = Literal["live", "folded", "all_in"]

_STREET_ORDER: dict[StreetName, int] = {
    "preflop": 0,
    "flop": 1,
    "turn": 2,
    "river": 3,
}
_FORCED_ACTIONS = {
    "post_ante",
    "post_small_blind",
    "post_big_blind",
    "post_straddle",
    "uncalled_return",
}
_TABLE_ACTIONS = {"fold", "check", "bet", "call", "raise"}
_FORCED_POST_FIELDS = {
    "post_ante": "ante",
    "post_small_blind": "small_blind",
    "post_big_blind": "big_blind",
    "post_straddle": "straddle",
}
_CHIP_ACTIONS = _FORCED_ACTIONS | {"bet", "call", "raise"}


class ImportedHandModel(BaseModel):
    """Strict persisted-contract base used only by the V2 import boundary."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
    )


def _unvalidated_python_graph(
    value: Any,
    *,
    ancestors: set[int] | None = None,
) -> Any:
    """Read a mutable model graph without invoking any serializer hooks."""

    if ancestors is None:
        ancestors = set()
    if isinstance(value, BaseModel):
        identity = id(value)
        if identity in ancestors:
            raise ValueError("persisted model graphs cannot contain cycles")
        ancestors.add(identity)
        try:
            payload = {
                field_name: _unvalidated_python_graph(
                    getattr(value, field_name),
                    ancestors=ancestors,
                )
                for field_name in type(value).model_fields
            }
            extra = value.__pydantic_extra__
            if extra:
                payload.update(
                    {
                        field_name: _unvalidated_python_graph(
                            field_value,
                            ancestors=ancestors,
                        )
                        for field_name, field_value in extra.items()
                    }
                )
            return payload
        finally:
            ancestors.remove(identity)
    if isinstance(value, dict):
        identity = id(value)
        if identity in ancestors:
            raise ValueError("persisted model graphs cannot contain cycles")
        ancestors.add(identity)
        try:
            return {
                _unvalidated_python_graph(key, ancestors=ancestors): (
                    _unvalidated_python_graph(item, ancestors=ancestors)
                )
                for key, item in value.items()
            }
        finally:
            ancestors.remove(identity)
    if isinstance(value, (list, tuple, set, frozenset)):
        identity = id(value)
        if identity in ancestors:
            raise ValueError("persisted model graphs cannot contain cycles")
        ancestors.add(identity)
        try:
            items = [
                _unvalidated_python_graph(item, ancestors=ancestors)
                for item in value
            ]
        finally:
            ancestors.remove(identity)
        if isinstance(value, tuple):
            return tuple(items)
        if isinstance(value, set):
            return set(items)
        if isinstance(value, frozenset):
            return frozenset(items)
        return items
    return value


def _preserve_model_fields_set(source: Any, snapshot: Any) -> None:
    """Retain exclude_unset semantics after validating the complete graph."""

    if isinstance(source, BaseModel) and isinstance(snapshot, BaseModel):
        object.__setattr__(
            snapshot,
            "__pydantic_fields_set__",
            set(source.__pydantic_fields_set__),
        )
        for field_name in type(source).model_fields:
            _preserve_model_fields_set(
                getattr(source, field_name),
                getattr(snapshot, field_name),
            )
        return
    if isinstance(source, dict) and isinstance(snapshot, dict):
        for key in source.keys() & snapshot.keys():
            _preserve_model_fields_set(source[key], snapshot[key])
        return
    if isinstance(source, (list, tuple)) and isinstance(snapshot, (list, tuple)):
        for source_item, snapshot_item in zip(source, snapshot, strict=True):
            _preserve_model_fields_set(source_item, snapshot_item)


class StableHandIdentity(ImportedHandModel):
    """Adapter-defined stable identity; PokerStars uses site plus hand id."""

    site: Identifier
    source_hand_id: Identifier
    namespace: Identifier = "site-hand-id/v1"


class SourceEvidence(ImportedHandModel):
    """A reviewable location in one immutable raw source."""

    raw_source_id: Identifier
    line_start: PositiveInteger | None = None
    line_end: PositiveInteger | None = None
    excerpt: str | None = Field(default=None, max_length=1000, strict=True)
    marker: str | None = Field(default=None, max_length=160, strict=True)

    @field_validator("excerpt", "marker")
    @classmethod
    def validate_non_empty_locator(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("source evidence text locators cannot be empty")
        return value

    @model_validator(mode="after")
    def validate_line_range(self) -> Self:
        if self.line_end is not None and self.line_start is None:
            raise ValueError("line_end requires line_start")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end cannot precede line_start")
        if self.line_start is None and self.excerpt is None and self.marker is None:
            raise ValueError("source evidence requires a line, excerpt, or marker")
        return self


class SourceChronology(ImportedHandModel):
    """Source time and ordering, kept distinct from ingestion time."""

    played_at: AwareDatetime | None = None
    source_timezone: str | None = Field(default=None, min_length=1, max_length=80, strict=True)
    source_session_id: Identifier | None = None
    source_file_id: Identifier
    hand_ordinal: PositiveInteger | None = None

    @model_validator(mode="after")
    def validate_timezone_provenance(self) -> Self:
        if self.source_timezone is not None and self.played_at is None:
            raise ValueError("source_timezone requires played_at")
        return self


class ImportProvenance(ImportedHandModel):
    """How an immutable raw hand entered the local import boundary."""

    source_kind: Literal["hand_history"] = "hand_history"
    import_id: Identifier
    imported_at: AwareDatetime
    adapter_id: Identifier
    adapter_version: Identifier
    format_revision: Identifier
    source_filename: str | None = Field(default=None, max_length=255, strict=True)


class RawHandHistory(ImportedHandModel):
    schema_version: Literal["raw-hand-history/v1"] = "raw-hand-history/v1"
    raw_source_id: Identifier
    identity: StableHandIdentity
    chronology: SourceChronology
    provenance: ImportProvenance
    content_sha256: Sha256
    raw_text: Annotated[str, StringConstraints(min_length=1, strict=True)]

    @model_validator(mode="after")
    def validate_file_identity(self) -> Self:
        if self.chronology.source_file_id != self.raw_source_id:
            raise ValueError("chronology source_file_id must equal raw_source_id")
        actual_checksum = sha256(self.raw_text.encode("utf-8")).hexdigest()
        if self.content_sha256 != actual_checksum:
            raise ValueError("content_sha256 must match the UTF-8 raw history")
        return self


class BlindStructure(ImportedHandModel):
    small_blind: PositiveDecimal | None = None
    big_blind: PositiveDecimal | None = None
    ante: NonNegativeDecimal | None = None
    ante_mode: AnteMode = "unknown"
    straddle: PositiveDecimal | None = None

    @model_validator(mode="after")
    def validate_blind_order(self) -> Self:
        if (
            self.small_blind is not None
            and self.big_blind is not None
            and self.small_blind > self.big_blind
        ):
            raise ValueError("small_blind cannot exceed big_blind")
        return self


class RakeSchedule(ImportedHandModel):
    percentage: UnitIntervalDecimal | None = None
    cap: NonNegativeDecimal | None = None
    fixed_drop: NonNegativeDecimal | None = None
    description: str | None = Field(default=None, max_length=500, strict=True)


class CashEconomics(ImportedHandModel):
    kind: Literal["cash"] = "cash"
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        strict=True,
    )
    rake: RakeSchedule | None = None


class TournamentPayout(ImportedHandModel):
    place_from: PositiveInteger
    place_to: PositiveInteger
    amount: NonNegativeDecimal | None = None
    share: UnitIntervalDecimal | None = None

    @model_validator(mode="after")
    def validate_place_range(self) -> Self:
        if self.place_to < self.place_from:
            raise ValueError("place_to cannot precede place_from")
        return self


class TournamentStack(ImportedHandModel):
    player_id: Identifier
    stack: NonNegativeDecimal | None = None


class TournamentBounty(ImportedHandModel):
    player_id: Identifier
    value: NonNegativeDecimal | None = None


class TournamentEconomics(ImportedHandModel):
    kind: Literal["tournament"] = "tournament"
    tournament_id: Identifier | None = None
    tournament_type: NonEmptyText | None = None
    stage: NonEmptyText | None = None
    currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        strict=True,
    )
    paid_places: PositiveInteger | None = Field(
        default=None,
        description="Total paid places in the tournament, independent of field size",
    )
    players_remaining: PositiveInteger | None = None
    payouts: list[TournamentPayout] = Field(
        default_factory=list,
        description=(
            "Still-relevant payout vector from first place through the lower of "
            "paid_places and players_remaining"
        ),
    )
    remaining_stacks: list[TournamentStack] = Field(default_factory=list)
    bounty_format: NonEmptyText | None = None
    bounties: list[TournamentBounty] = Field(default_factory=list)
    icm_inputs_complete: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def validate_tournament_context(self) -> Self:
        _validate_unique(self.remaining_stacks, "player_id", "remaining stack player")
        _validate_unique(self.bounties, "player_id", "bounty player")
        if self.icm_inputs_complete:
            required = (
                self.paid_places,
                self.players_remaining,
                self.payouts,
                self.remaining_stacks,
            )
            if any(value is None or value == [] for value in required):
                raise ValueError("complete ICM inputs require places, players, payouts, and stacks")
            if len(self.remaining_stacks) != self.players_remaining:
                raise ValueError(
                    "complete ICM inputs require one remaining stack per player"
                )
            if any(
                player.stack is None or player.stack <= 0
                for player in self.remaining_stacks
            ):
                raise ValueError("complete ICM inputs require positive remaining stacks")

            ordered_payouts = sorted(self.payouts, key=lambda payout: payout.place_from)
            relevant_paid_places = min(self.paid_places, self.players_remaining)
            expected_place = 1
            payout_unit: Literal["amount", "share"] | None = None
            prior_value: Decimal | None = None
            share_total = Decimal(0)
            for payout in ordered_payouts:
                if payout.place_from != expected_place:
                    raise ValueError(
                        "complete ICM payout places must be contiguous from first place"
                    )
                expected_place = payout.place_to + 1
                has_amount = payout.amount is not None
                has_share = payout.share is not None
                if has_amount == has_share:
                    raise ValueError(
                        "complete ICM payouts require exactly one amount or share"
                    )
                current_unit: Literal["amount", "share"] = (
                    "amount" if has_amount else "share"
                )
                if payout_unit is not None and current_unit != payout_unit:
                    raise ValueError("complete ICM payouts must use one value unit")
                payout_unit = current_unit
                value = payout.amount if has_amount else payout.share
                if value is None or value <= 0:
                    raise ValueError("complete ICM payouts require positive values")
                if prior_value is not None and value > prior_value:
                    raise ValueError(
                        "complete ICM payout values cannot increase for lower places"
                    )
                prior_value = value
                if current_unit == "share":
                    places = payout.place_to - payout.place_from + 1
                    share_total += value * places
            if expected_place != relevant_paid_places + 1:
                raise ValueError(
                    "complete ICM payouts must cover every still-relevant paid place exactly"
                )
            if payout_unit == "share":
                if self.paid_places <= self.players_remaining and share_total != Decimal(1):
                    raise ValueError("complete ICM payout shares must sum to one")
                if share_total > Decimal(1):
                    raise ValueError("complete ICM payout shares cannot exceed one")

            if self.bounty_format is not None:
                if len(self.bounties) != self.players_remaining:
                    raise ValueError(
                        "complete bounty ICM inputs require one bounty per player"
                    )
                if any(bounty.value is None for bounty in self.bounties):
                    raise ValueError(
                        "complete bounty ICM inputs require concrete bounty values"
                    )
                if {bounty.player_id for bounty in self.bounties} != {
                    player.player_id for player in self.remaining_stacks
                }:
                    raise ValueError(
                        "complete bounty ICM inputs must cover the remaining players"
                    )
        return self


class UnknownEconomics(ImportedHandModel):
    kind: Literal["unknown"] = "unknown"
    reason: NonEmptyText | None = None


Economics = Annotated[
    CashEconomics | TournamentEconomics | UnknownEconomics,
    Field(discriminator="kind"),
]


class GameContext(ImportedHandModel):
    variant: GameVariant = "texas_holdem"
    betting_limit: BettingLimit
    table_size: TableSize
    blinds: BlindStructure
    economics: Economics


class StructuralPosition(ImportedHandModel):
    dealt_in_player_count: Annotated[int, Field(ge=2, le=10, strict=True)]
    action_index: NonNegativeInteger
    button_distance: NonNegativeInteger
    display_label: Literal[
        "BTN/SB",
        "BTN",
        "SB",
        "BB",
        "UTG",
        "UTG+1",
        "UTG+2",
        "UTG+3",
        "UTG+3/LJ",
        "UTG+2/LJ",
        "UTG+1/LJ",
        "LJ",
        "HJ",
        "CO",
    ]

    @model_validator(mode="after")
    def validate_indexes(self) -> Self:
        if self.action_index >= self.dealt_in_player_count:
            raise ValueError("action_index must be within the dealt-in action ring")
        if self.button_distance >= self.dealt_in_player_count:
            raise ValueError("button_distance must be within the dealt-in action ring")
        expected_label = structural_position_labels(self.dealt_in_player_count)[
            self.button_distance
        ]
        if self.display_label != expected_label:
            raise ValueError(
                "display_label must match dealt_in_player_count and button_distance"
            )
        expected_action_index = _structural_action_index(
            self.dealt_in_player_count,
            self.button_distance,
        )
        if self.action_index != expected_action_index:
            raise ValueError(
                "action_index must match dealt_in_player_count and button_distance"
            )
        return self


class ImportedSeat(ImportedHandModel):
    seat_number: PositiveInteger
    player_id: Identifier
    display_name: str | None = Field(default=None, min_length=1, max_length=80, strict=True)
    starting_stack: NonNegativeDecimal | None = None
    participation: ParticipationStatus
    position: StructuralPosition | None = None

    @model_validator(mode="after")
    def validate_position_participation(self) -> Self:
        if self.participation != "dealt_in" and self.position is not None:
            raise ValueError("only a dealt-in seat can have a structural position")
        if self.participation == "dealt_in" and self.starting_stack == 0:
            raise ValueError("a dealt-in seat must have a positive known starting stack")
        return self


class ActionOrigin(ImportedHandModel):
    kind: OriginKind
    basis: OriginBasis
    confidence: UnitIntervalDecimal | None = None
    evidence: list[SourceEvidence] = Field(min_length=1)
    semantics_revision: Identifier | None = None
    automatic_reason: Literal[
        "timeout",
        "disconnect",
        "automation",
        "other",
        "unknown",
    ] | None = None
    review_reference: Identifier | None = None

    @model_validator(mode="after")
    def validate_origin_basis(self) -> Self:
        if self.basis == "versioned_absence_semantics" and self.semantics_revision is None:
            raise ValueError("absence semantics require a versioned semantics revision")
        if self.kind == "player_selected" and self.basis not in {
            "explicit_marker",
            "versioned_absence_semantics",
            "user_confirmed",
        }:
            raise ValueError("player-selected origin requires affirmative evidence")
        if self.basis == "user_confirmed" and self.kind != "player_selected":
            raise ValueError("user-confirmed origin must be player-selected")
        if self.basis == "user_confirmed" and self.review_reference is None:
            raise ValueError("user-confirmed origin requires a review reference")
        if self.kind == "unknown" and self.basis != "unresolved":
            raise ValueError("unknown origin must remain unresolved")
        if self.basis == "unresolved" and self.kind != "unknown":
            raise ValueError("unresolved basis must use unknown origin")
        if self.kind == "client_automatic" and self.automatic_reason is None:
            raise ValueError("client-automatic origin requires an automatic reason")
        if self.kind != "client_automatic" and self.automatic_reason is not None:
            raise ValueError("automatic_reason is only valid for client-automatic actions")
        return self


class ImportedAction(ImportedHandModel):
    sequence: NonNegativeInteger
    actor_id: Identifier
    action_type: ActionType
    amount: PositiveDecimal | None = Field(
        default=None,
        description=(
            "Incremental chips added by this action, or chips returned for an "
            "uncalled_return"
        ),
    )
    total_committed: NonNegativeDecimal | None = Field(
        default=None,
        description="Actor's cumulative commitment on this street after the action",
    )
    all_in: bool = Field(default=False, strict=True)
    origin: ActionOrigin
    evidence: list[SourceEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_action_shape(self) -> Self:
        if self.action_type not in _CHIP_ACTIONS and self.amount is not None:
            raise ValueError("fold and check actions cannot carry an amount")
        if self.action_type in _FORCED_ACTIONS and self.origin.kind != "forced_system":
            raise ValueError("posts and uncalled returns must be forced/system actions")
        if self.action_type in {"fold", "check", "bet", "call", "raise"}:
            if self.origin.kind == "forced_system":
                raise ValueError("table decisions cannot be classified as forced/system")
        if self.all_in and self.action_type in {"fold", "check", "uncalled_return"}:
            raise ValueError("fold, check, and return actions cannot be all-in")
        return self

    @property
    def is_player_decision(self) -> bool:
        return (
            self.action_type in _TABLE_ACTIONS
            and self.origin.kind == "player_selected"
        )


class ImportedStreet(ImportedHandModel):
    street: StreetName
    board_cards: list[Card] = Field(default_factory=list)
    actions: list[ImportedAction] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_street(self) -> Self:
        expected = list(range(len(self.actions)))
        actual = [action.sequence for action in self.actions]
        if actual != expected:
            raise ValueError("street action sequence must be contiguous and ordered from zero")
        maximum_cards = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}[self.street]
        if len(self.board_cards) > maximum_cards:
            raise ValueError(f"{self.street} cannot contain more than {maximum_cards} board cards")
        return self


class ShowdownEntry(ImportedHandModel):
    player_id: Identifier
    cards: list[Card] = Field(default_factory=list, max_length=2)
    disposition: Literal["shown", "mucked", "not_shown", "unknown"]
    evidence: list[SourceEvidence] = Field(min_length=1)


class PotAward(ImportedHandModel):
    player_id: Identifier
    amount: PositiveDecimal | None = None
    pot_index: NonNegativeInteger | None = None
    evidence: list[SourceEvidence] = Field(min_length=1)


class PlayerResult(ImportedHandModel):
    player_id: Identifier
    net_result: Decimal | None = Field(default=None, allow_inf_nan=False, strict=True)
    total_collected: NonNegativeDecimal | None = None


class StatedPotSummary(ImportedHandModel):
    """Normalized source totals: components and gross are before rake."""

    gross_total: NonNegativeDecimal | None = None
    rake: NonNegativeDecimal | None = None
    net_total: NonNegativeDecimal | None = None
    gross_pots: list[NonNegativeDecimal] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_totals(self) -> Self:
        if self.gross_total is None and self.net_total is None and not self.gross_pots:
            raise ValueError("a stated pot summary requires at least one stated total")
        component_gross: Decimal | None = None
        if self.gross_pots and self.gross_total is not None:
            component_gross = sum(self.gross_pots, Decimal(0))
            if component_gross != self.gross_total:
                raise ValueError("stated gross pot components must sum to gross_total")
        elif self.gross_pots:
            component_gross = sum(self.gross_pots, Decimal(0))
        effective_gross = (
            self.gross_total if self.gross_total is not None else component_gross
        )
        if (
            effective_gross is not None
            and self.rake is not None
            and self.net_total is not None
        ):
            if effective_gross - self.rake != self.net_total:
                raise ValueError("net_total must equal gross_total minus rake")
        if (
            effective_gross is not None
            and self.net_total is not None
            and self.net_total > effective_gross
        ):
            raise ValueError("net_total cannot exceed gross_total")
        if (
            self.rake is not None
            and effective_gross is not None
            and self.rake > effective_gross
        ):
            raise ValueError("rake cannot exceed the gross pot")
        return self


class HandResults(ImportedHandModel):
    stated_pot: StatedPotSummary | None = None
    showdown: list[ShowdownEntry] = Field(default_factory=list)
    awards: list[PotAward] = Field(default_factory=list)
    players: list[PlayerResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_results(self) -> Self:
        _validate_unique(self.showdown, "player_id", "showdown player")
        _validate_unique(self.players, "player_id", "result player")
        return self


class ImportedHandState(ImportedHandModel):
    """Shared detected/approved, adapter-neutral hand state."""

    identity: StableHandIdentity
    chronology: SourceChronology
    game: GameContext
    button_seat: PositiveInteger | None = None
    seats: list[ImportedSeat] = Field(min_length=2, max_length=10)
    hero_player_id: Identifier | None = None
    hero_cards: list[Card] = Field(default_factory=list, max_length=2)
    streets: list[ImportedStreet] = Field(min_length=1, max_length=4)
    results: HandResults | None = None

    @model_validator(mode="after")
    def validate_hand(self) -> Self:
        _validate_unique(self.seats, "seat_number", "seat number")
        _validate_unique(self.seats, "player_id", "player")
        seat_numbers = {seat.seat_number for seat in self.seats}
        player_ids = {seat.player_id for seat in self.seats}
        if len(self.seats) > self.game.table_size:
            raise ValueError("seat count cannot exceed table_size")
        if self.button_seat is not None and self.button_seat not in seat_numbers:
            raise ValueError("button_seat must identify a known seat")
        if self.hero_player_id is not None and self.hero_player_id not in player_ids:
            raise ValueError("hero_player_id must identify a known seat")
        if self.hero_cards and self.hero_player_id is None:
            raise ValueError("hero_cards require a known hero_player_id")
        if self.hero_cards and self.hero_player_id is not None:
            hero = next(
                seat for seat in self.seats if seat.player_id == self.hero_player_id
            )
            if hero.participation != "dealt_in":
                raise ValueError("hero_cards require a dealt-in hero seat")

        street_indexes = [_STREET_ORDER[street.street] for street in self.streets]
        if street_indexes != list(range(len(self.streets))):
            raise ValueError("streets must be unique and ordered from preflop")
        terminal_actors: dict[str, tuple[Literal["folded", "all_in"], StreetName]] = {}
        live_players = {
            seat.player_id
            for seat in self.seats
            if seat.participation in {"dealt_in", "unknown"}
        }
        actionable_players = set(live_players)
        fold_end: tuple[StreetName, str] | None = None
        betting_closed_by_all_ins = False
        enforce_full_raise_increment = self.game.betting_limit in {
            "no_limit",
            "pot_limit",
        }
        cumulative_commitments: dict[str, Decimal | None] = {
            player_id: Decimal(0) for player_id in player_ids
        }
        cumulative_commitment_lower_bounds: dict[str, Decimal] = {
            player_id: Decimal(0) for player_id in player_ids
        }
        cumulative_unresolved_minimum_dead: dict[str, Decimal] = {
            player_id: Decimal(0) for player_id in player_ids
        }
        cumulative_unresolved_minimum_live: dict[str, Decimal] = {
            player_id: Decimal(0) for player_id in player_ids
        }
        cumulative_unresolved_positive_dead: dict[str, bool] = {
            player_id: False for player_id in player_ids
        }
        cumulative_unresolved_positive_live: dict[str, bool] = {
            player_id: False for player_id in player_ids
        }
        known_action_orders = _known_action_orders(self.seats, self.button_seat)
        if known_action_orders is None:
            clockwise_action_order = None
            preflop_action_order = None
            expected_blind_actors: dict[str, str] = {}
        else:
            clockwise_action_order, preflop_action_order = known_action_orders
            expected_blind_actors = {
                "post_small_blind": clockwise_action_order[
                    0 if len(clockwise_action_order) == 2 else 1
                ],
                "post_big_blind": clockwise_action_order[
                    1 if len(clockwise_action_order) == 2 else 2
                ],
            }
        required_structural_blind_posts = tuple(
            action_type
            for action_type in ("post_small_blind", "post_big_blind")
            if action_type in expected_blind_actors
            and getattr(self.game.blinds, _FORCED_POST_FIELDS[action_type]) is not None
        )
        configured_positive_ante = (
            self.game.blinds.ante is not None
            and self.game.blinds.ante > 0
        )
        if clockwise_action_order is None or not configured_positive_ante:
            required_ante_players: tuple[str, ...] = ()
        elif self.game.blinds.ante_mode == "per_player":
            required_ante_players = tuple(clockwise_action_order)
        elif self.game.blinds.ante_mode == "big_blind":
            required_ante_players = (
                expected_blind_actors["post_big_blind"],
            )
        else:
            required_ante_players = ()
        configured_straddle_required = (
            clockwise_action_order is not None
            and self.game.blinds.straddle is not None
        )
        seen_ante_posts: set[str] = set()
        seen_straddle_players: set[str] = set()
        seen_structural_blind_posts: set[str] = set()
        forced_stack_exhausted_players: set[str] = set()

        def missing_ante_posts() -> list[str]:
            return [
                f"post_ante for {player_id}"
                for player_id in required_ante_players
                if player_id not in seen_ante_posts
            ]

        def missing_structural_blind_posts() -> list[str]:
            return [
                action_type
                for action_type in required_structural_blind_posts
                if action_type not in seen_structural_blind_posts
                and expected_blind_actors[action_type]
                not in forced_stack_exhausted_players
            ]

        inferred_stack_exhausted_players: set[str] = set()
        committed_pot_before_street: Decimal | None = Decimal(0)
        final_street_betting_complete = False
        for street_index, street in enumerate(self.streets):
            if fold_end is not None:
                raise ValueError("a later street is not allowed after folds end the hand")
            cumulative_lower_bounds_before_street = dict(
                cumulative_commitment_lower_bounds
            )
            unresolved_minimum_dead_before_street = dict(
                cumulative_unresolved_minimum_dead
            )
            unresolved_minimum_live_before_street = dict(
                cumulative_unresolved_minimum_live
            )
            unresolved_positive_dead_before_street = dict(
                cumulative_unresolved_positive_dead
            )
            unresolved_positive_live_before_street = dict(
                cumulative_unresolved_positive_live
            )
            street_commitments: dict[str, Decimal | None] = {
                player_id: Decimal(0) for player_id in player_ids
            }
            street_commitment_lower_bounds: dict[str, Decimal] = {
                player_id: Decimal(0) for player_id in player_ids
            }
            street_unresolved_minimum_dead: dict[str, Decimal] = {
                player_id: Decimal(0) for player_id in player_ids
            }
            street_unresolved_minimum_live: dict[str, Decimal] = {
                player_id: Decimal(0) for player_id in player_ids
            }
            street_unresolved_positive_dead: dict[str, bool] = {
                player_id: False for player_id in player_ids
            }
            street_unresolved_positive_live: dict[str, bool] = {
                player_id: False for player_id in player_ids
            }
            live_commitments: dict[str, Decimal | None] = {
                player_id: Decimal(0) for player_id in player_ids
            }
            acted_wager_by_player: dict[str, Decimal | None] = {}
            reopen_increment_by_player: dict[str, Decimal | None] = {}
            current_wager: Decimal | None = Decimal(0)
            nominal_bring_in = Decimal(0)
            last_full_wager_increment = self.game.blinds.big_blind
            return_seen = False
            round_closed_by_return = False
            pending_action_players: set[str] | None = None
            next_action_player: str | None = None
            known_action_round_closed = False
            last_preflop_straddler: str | None = None
            table_decision_seen = False
            for action in street.actions:
                if return_seen:
                    raise ValueError(
                        "an action cannot follow an uncalled return on the same street"
                    )
                return_settles_round = False
                sole_actionable_player = (
                    _sole_actionable_player_with_only_all_in_opponents(
                        live_players,
                        actionable_players,
                    )
                )
                if (
                    not betting_closed_by_all_ins
                    and sole_actionable_player is not None
                    and current_wager is not None
                    and live_commitments[sole_actionable_player] is not None
                    and live_commitments[sole_actionable_player] >= current_wager
                ):
                    betting_closed_by_all_ins = True
                pot_before_action = (
                    committed_pot_before_street
                    + sum(
                        (
                            commitment
                            for commitment in street_commitments.values()
                            if commitment is not None
                        ),
                        Decimal(0),
                    )
                    if committed_pot_before_street is not None
                    and all(
                        commitment is not None
                        for commitment in street_commitments.values()
                    )
                    else None
                )
                if action.actor_id not in player_ids:
                    raise ValueError("every action actor must identify a known seat")
                actor_seat = next(
                    seat
                    for seat in self.seats
                    if seat.player_id == action.actor_id
                )
                participation = actor_seat.participation
                if participation in {"sitting_out", "not_dealt"}:
                    raise ValueError(
                        "an action actor cannot be explicitly sitting out or not dealt"
                    )
                if fold_end is not None:
                    final_fold_street, sole_winner = fold_end
                    valid_return = (
                        action.action_type == "uncalled_return"
                        and action.actor_id == sole_winner
                        and street.street == final_fold_street
                    )
                    if not valid_return:
                        raise ValueError(
                            "only the sole winner's same-street uncalled return is"
                            " allowed after folds end the hand"
                        )
                terminal = terminal_actors.get(action.actor_id)
                if terminal is not None:
                    reason, terminal_street = terminal
                    applicable_return = (
                        reason == "all_in"
                        and action.action_type == "uncalled_return"
                        and street.street == terminal_street
                    )
                    if not applicable_return:
                        raise ValueError(
                            "an actor cannot act after folding or going all-in"
                        )
                if (
                    betting_closed_by_all_ins
                    and action.action_type in _TABLE_ACTIONS
                ):
                    raise ValueError(
                        "a table decision is not allowed after every"
                        " pot-eligible opponent is all-in and action is complete"
                    )
                if (
                    sole_actionable_player == action.actor_id
                    and action.action_type in _TABLE_ACTIONS
                    and action.action_type in {"bet", "raise"}
                ):
                    raise ValueError(
                        "a bet or raise is not allowed when no"
                        " opponent can respond"
                    )
                if (
                    street.street == "preflop"
                    and action.action_type in _TABLE_ACTIONS
                ):
                    missing_antes = missing_ante_posts()
                    if missing_antes:
                        raise ValueError(
                            "a preflop table decision requires all configured"
                            " ante posts first; missing "
                            + ", ".join(missing_antes)
                        )
                    missing_blind_posts = missing_structural_blind_posts()
                    if missing_blind_posts:
                        raise ValueError(
                            "a preflop table decision requires all configured"
                            " structural blind posts first; missing "
                            + ", ".join(missing_blind_posts)
                        )
                    if configured_straddle_required and not seen_straddle_players:
                        raise ValueError(
                            "a preflop table decision requires a configured"
                            " post_straddle first"
                        )
                if (
                    clockwise_action_order is not None
                    and preflop_action_order is not None
                    and action.action_type in _TABLE_ACTIONS
                ):
                    if known_action_round_closed:
                        raise ValueError(
                            "a table decision is not allowed after the known action"
                            " round is complete"
                        )
                    if pending_action_players is None:
                        pending_action_players = set(actionable_players)
                        if street.street == "preflop":
                            if last_preflop_straddler is None:
                                next_action_player = next(
                                    (
                                        player_id
                                        for player_id in preflop_action_order
                                        if player_id in pending_action_players
                                    ),
                                    None,
                                )
                            else:
                                next_action_player = _next_clockwise_player(
                                    clockwise_action_order,
                                    last_preflop_straddler,
                                    pending_action_players,
                                )
                        else:
                            next_action_player = _next_clockwise_player(
                                clockwise_action_order,
                                clockwise_action_order[0],
                                pending_action_players,
                            )
                    if action.actor_id != next_action_player:
                        raise ValueError(
                            "an action is out of turn for the known dealt-in seat"
                            f" ring; expected {next_action_player}, got"
                            f" {action.actor_id}"
                        )
                actor_commitment = street_commitments[action.actor_id]
                actor_live_commitment = live_commitments[action.actor_id]
                resolved_commitment = _known_action_total(
                    action,
                    actor_commitment,
                )
                resolved_live_commitment = _known_live_action_total(
                    action,
                    actor_commitment,
                    resolved_commitment,
                    actor_live_commitment,
                )
                prior_cumulative_commitment = cumulative_commitments[
                    action.actor_id
                ]
                resolved_cumulative_commitment = (
                    prior_cumulative_commitment
                    + resolved_commitment
                    - actor_commitment
                    if prior_cumulative_commitment is not None
                    and resolved_commitment is not None
                    and actor_commitment is not None
                    else None
                )
                resolved_street_commitment_lower_bound = (
                    _action_street_commitment_lower_bound(
                        action,
                        street_commitment_lower_bounds[action.actor_id],
                    )
                )
                posted_amount: Decimal | None = None
                configured_post_amount: Decimal | None = None
                short_forced_post = False
                unresolved_configured_post_minimum = Decimal(0)
                unresolved_configured_post_strict_positive = False
                bet_increment, raise_increment = _wager_increments(
                    action,
                    current_wager=current_wager,
                    actor_live_commitment=actor_live_commitment,
                    resolved_live_commitment=resolved_live_commitment,
                )
                forced_post_field = _FORCED_POST_FIELDS.get(action.action_type)
                if forced_post_field is not None:
                    if street.street != "preflop":
                        raise ValueError("forced blind and ante posts must be preflop")
                    if table_decision_seen:
                        raise ValueError(
                            "a forced blind, ante, or straddle post cannot follow"
                            " a table decision"
                        )
                    expected_blind_actor = expected_blind_actors.get(
                        action.action_type
                    )
                    if (
                        expected_blind_actor is not None
                        and action.actor_id != expected_blind_actor
                    ):
                        blind_name = (
                            "small blind"
                            if action.action_type == "post_small_blind"
                            else "big blind"
                        )
                        raise ValueError(
                            f"{action.action_type} must come from the structural"
                            f" {blind_name} seat {expected_blind_actor}; got"
                            f" {action.actor_id}"
                        )
                    if expected_blind_actor is not None:
                        if action.action_type in seen_structural_blind_posts:
                            raise ValueError(
                                f"{action.action_type} may occur only once for the"
                                " known dealt-in seat ring"
                            )
                        seen_structural_blind_posts.add(action.action_type)
                    configured_post_amount = _configured_forced_post_amount(
                        action,
                        self.game.blinds,
                    )
                    if action.action_type == "post_ante" and required_ante_players:
                        if action.actor_id not in required_ante_players:
                            expected_posters = ", ".join(required_ante_players)
                            raise ValueError(
                                "post_ante actor must match the configured ante"
                                f" mode; expected one of {expected_posters}, got"
                                f" {action.actor_id}"
                            )
                        if action.actor_id in seen_ante_posts:
                            raise ValueError(
                                "post_ante may occur only once for each required"
                                " player in the known dealt-in seat ring"
                            )
                        seen_ante_posts.add(action.actor_id)
                    if (
                        action.action_type == "post_straddle"
                        and clockwise_action_order is not None
                    ):
                        if action.actor_id in seen_straddle_players:
                            raise ValueError(
                                "post_straddle may occur only once for each player"
                                " in the known dealt-in seat ring"
                            )
                        seen_straddle_players.add(action.actor_id)
                    posted_amount = _posted_forced_amount(
                        action,
                        prior_commitment=actor_commitment,
                        resolved_commitment=resolved_commitment,
                    )
                    if (
                        configured_post_amount is not None
                        and (
                            (
                                posted_amount is not None
                                and posted_amount != configured_post_amount
                            )
                            or (
                                posted_amount is None
                                and resolved_commitment is not None
                                and resolved_commitment < configured_post_amount
                            )
                        )
                    ):
                        starting_stack = actor_seat.starting_stack
                        observed_post_bound = (
                            posted_amount
                            if posted_amount is not None
                            else resolved_commitment
                        )
                        assert observed_post_bound is not None
                        short_stack_exhausted = (
                            Decimal(0)
                            < observed_post_bound
                            < configured_post_amount
                            and (
                                (
                                    starting_stack is not None
                                    and resolved_commitment is not None
                                    and resolved_commitment == starting_stack
                                )
                                or (
                                    starting_stack is None
                                    and action.all_in
                                )
                            )
                        )
                        short_forced_post = short_stack_exhausted
                        if not short_stack_exhausted:
                            observed_post_kind = (
                                "amount"
                                if posted_amount is not None
                                else "post-action total"
                            )
                            raise ValueError(
                                f"{action.action_type} {observed_post_kind}"
                                f" {observed_post_bound} does not"
                                f" match configured {forced_post_field}"
                                f" {configured_post_amount} or a short-stack all-in"
                            )
                    if (
                        configured_post_amount is not None
                        and configured_post_amount > 0
                        and action.amount is None
                    ):
                        prior_unresolved_minimum = sum(
                            (
                                street_commitment_lower_bounds[action.actor_id],
                                street_unresolved_minimum_dead[action.actor_id],
                                street_unresolved_minimum_live[action.actor_id],
                            ),
                            Decimal(0),
                        )
                        prior_unresolved_positive = any(
                            (
                                street_unresolved_positive_dead[action.actor_id],
                                street_unresolved_positive_live[action.actor_id],
                            )
                        )
                        full_configured_post_minimum = (
                            prior_unresolved_minimum + configured_post_amount
                        )
                        full_configured_post_fits = (
                            resolved_commitment is not None
                            and (
                                resolved_commitment
                                > full_configured_post_minimum
                                if prior_unresolved_positive
                                else resolved_commitment
                                >= full_configured_post_minimum
                            )
                        )
                        unresolved_short_stack_exhausted = (
                            actor_commitment is None
                            and resolved_commitment is not None
                            and not full_configured_post_fits
                            and (
                                (
                                    actor_seat.starting_stack is not None
                                    and resolved_commitment
                                    == actor_seat.starting_stack
                                )
                                or (
                                    actor_seat.starting_stack is None
                                    and action.all_in
                                )
                            )
                        )
                        if short_forced_post:
                            unresolved_configured_post_strict_positive = True
                        elif unresolved_short_stack_exhausted:
                            # An exact cumulative total can prove exhaustion while
                            # an unresolved prior post prevents deriving this
                            # forced post's delta. Preserve only the fact that the
                            # short post added chips; do not require the full
                            # configured amount.
                            unresolved_configured_post_strict_positive = True
                        elif resolved_commitment is not None:
                            unresolved_configured_post_minimum = (
                                configured_post_amount
                            )
                        elif (
                            actor_seat.starting_stack is not None
                            and prior_cumulative_commitment is not None
                        ):
                            remaining_stack = (
                                actor_seat.starting_stack
                                - prior_cumulative_commitment
                            )
                            if remaining_stack > 0:
                                unresolved_configured_post_minimum = min(
                                    configured_post_amount,
                                    remaining_stack,
                                )
                            else:
                                unresolved_configured_post_strict_positive = True
                        elif actor_seat.starting_stack is not None and not any(
                            (
                                unresolved_positive_dead_before_street[
                                    action.actor_id
                                ],
                                unresolved_positive_live_before_street[
                                    action.actor_id
                                ],
                                street_unresolved_positive_dead[action.actor_id],
                                street_unresolved_positive_live[action.actor_id],
                            )
                        ):
                            prior_proven_commitment = sum(
                                (
                                    cumulative_lower_bounds_before_street[
                                        action.actor_id
                                    ],
                                    street_commitment_lower_bounds[action.actor_id],
                                    unresolved_minimum_dead_before_street[
                                        action.actor_id
                                    ],
                                    unresolved_minimum_live_before_street[
                                        action.actor_id
                                    ],
                                    street_unresolved_minimum_dead[action.actor_id],
                                    street_unresolved_minimum_live[action.actor_id],
                                ),
                                Decimal(0),
                            )
                            remaining_stack = (
                                actor_seat.starting_stack
                                - prior_proven_commitment
                            )
                            if remaining_stack > 0:
                                unresolved_configured_post_minimum = min(
                                    configured_post_amount,
                                    remaining_stack,
                                )
                            else:
                                unresolved_configured_post_strict_positive = True
                        elif actor_seat.starting_stack is None and not action.all_in:
                            unresolved_configured_post_minimum = (
                                configured_post_amount
                            )
                        else:
                            unresolved_configured_post_strict_positive = True
                (
                    resolved_street_commitment_lower_bound,
                    resolved_street_unresolved_minimum_dead,
                    resolved_street_unresolved_minimum_live,
                    resolved_street_unresolved_positive_dead,
                    resolved_street_unresolved_positive_live,
                ) = _action_street_unresolved_positive_evidence(
                    action,
                    prior_lower_bound=street_commitment_lower_bounds[
                        action.actor_id
                    ],
                    resolved_lower_bound=resolved_street_commitment_lower_bound,
                    prior_minimum_dead=street_unresolved_minimum_dead[
                        action.actor_id
                    ],
                    prior_minimum_live=street_unresolved_minimum_live[
                        action.actor_id
                    ],
                    prior_positive_dead=street_unresolved_positive_dead[
                        action.actor_id
                    ],
                    prior_positive_live=street_unresolved_positive_live[
                        action.actor_id
                    ],
                    configured_post_minimum=(
                        unresolved_configured_post_minimum
                    ),
                    configured_post_strict_positive=(
                        unresolved_configured_post_strict_positive
                    ),
                )
                resolved_cumulative_commitment_lower_bound = (
                    cumulative_lower_bounds_before_street[action.actor_id]
                    + resolved_street_commitment_lower_bound
                )
                resolved_cumulative_unresolved_minimum = sum(
                    (
                        unresolved_minimum_dead_before_street[action.actor_id],
                        unresolved_minimum_live_before_street[action.actor_id],
                        resolved_street_unresolved_minimum_dead,
                        resolved_street_unresolved_minimum_live,
                    ),
                    Decimal(0),
                )
                resolved_cumulative_unresolved_positive = any(
                    (
                        unresolved_positive_dead_before_street[action.actor_id],
                        unresolved_positive_live_before_street[action.actor_id],
                        resolved_street_unresolved_positive_dead,
                        resolved_street_unresolved_positive_live,
                    )
                )
                resolved_cumulative_minimum = (
                    resolved_cumulative_commitment_lower_bound
                    + resolved_cumulative_unresolved_minimum
                )
                known_all_in_commitment = resolved_cumulative_commitment
                if (
                    known_all_in_commitment is None
                    and street.street == "preflop"
                ):
                    known_all_in_commitment = resolved_commitment
                known_stack_exhausted = (
                    _stack_is_exhausted(
                        actor_seat.starting_stack,
                        known_all_in_commitment,
                    )
                    or (
                        actor_seat.starting_stack is not None
                        and (
                            resolved_cumulative_minimum
                            == actor_seat.starting_stack
                            and not resolved_cumulative_unresolved_positive
                        )
                    )
                )
                if (
                    action.all_in
                    and actor_seat.starting_stack is not None
                    and known_all_in_commitment is not None
                    and not known_stack_exhausted
                ):
                    raise ValueError(
                        f"{action.actor_id} all-in marker has cumulative commitment"
                        f" {known_all_in_commitment}, which does not exhaust known"
                        f" starting stack {actor_seat.starting_stack}"
                    )
                # Keep unresolved markers in the reviewable action stream, but do
                # not let a known-stack marker waive betting rules or terminate
                # its actor until the commitment actually proves exhaustion.
                confirmed_all_in = action.all_in and (
                    actor_seat.starting_stack is None or known_stack_exhausted
                )
                if (
                    action.action_type == "check"
                    and resolved_live_commitment is not None
                    and current_wager is not None
                    and resolved_live_commitment < current_wager
                ):
                    raise ValueError(
                        "an actor cannot check while facing an outstanding wager"
                    )
                if action.action_type == "call" and current_wager is not None:
                    if current_wager == 0:
                        raise ValueError("a call requires an outstanding wager")
                    if resolved_live_commitment is not None:
                        if resolved_live_commitment > current_wager or (
                            resolved_live_commitment < current_wager
                            and not confirmed_all_in
                        ):
                            raise ValueError(
                                "a call must match the outstanding wager unless it is"
                                " an all-in under-call"
                            )
                        if (
                            actor_live_commitment is not None
                            and resolved_live_commitment <= actor_live_commitment
                        ):
                            raise ValueError("a call requires an outstanding wager")
                elif action.action_type == "bet" and current_wager is not None:
                    if current_wager > 0:
                        raise ValueError("a bet requires no outstanding wager")
                    if resolved_live_commitment is not None and (
                        resolved_live_commitment <= 0
                        or (
                            actor_live_commitment is not None
                            and resolved_live_commitment <= actor_live_commitment
                        )
                    ):
                        raise ValueError("a bet must add chips above the prior commitment")
                    if (
                        enforce_full_raise_increment
                        and bet_increment is not None
                        and last_full_wager_increment is not None
                        and bet_increment < last_full_wager_increment
                        and not confirmed_all_in
                    ):
                        raise ValueError(
                            "a non-all-in bet must be at least the minimum full"
                            " wager increment"
                        )
                elif action.action_type == "raise" and current_wager is not None:
                    if current_wager == 0:
                        raise ValueError("a raise requires an outstanding wager")
                    if resolved_live_commitment is not None:
                        if raise_increment is not None and raise_increment <= 0:
                            raise ValueError("a raise must increase the outstanding wager")
                        if not _raise_is_reopened(
                            action.actor_id,
                            enforce_full_raise_increment=enforce_full_raise_increment,
                            current_wager=current_wager,
                            acted_wager_by_player=acted_wager_by_player,
                            reopen_increment_by_player=reopen_increment_by_player,
                        ):
                            raise ValueError(
                                "a raise is not allowed because short all-ins have not"
                                " reopened betting for this actor"
                            )
                        if (
                            enforce_full_raise_increment
                            and last_full_wager_increment is not None
                            and raise_increment < last_full_wager_increment
                            and not confirmed_all_in
                        ):
                            raise ValueError(
                                "a non-all-in raise must be at least the last full"
                                " bet or raise increment"
                            )
                if (
                    self.game.betting_limit == "pot_limit"
                    and action.action_type in {"bet", "raise"}
                    and pot_before_action is not None
                    and current_wager is not None
                    and actor_live_commitment is not None
                    and resolved_live_commitment is not None
                ):
                    call_amount = max(
                        current_wager - actor_live_commitment,
                        Decimal(0),
                    )
                    # Calling adds `call_amount` to both the pot and the actor's
                    # commitment. The actor may then raise by that resulting pot,
                    # so the maximum chips added are pot + twice the call.
                    maximum_wager_addition = pot_before_action + call_amount * 2
                    wager_addition = (
                        resolved_live_commitment - actor_live_commitment
                    )
                    if wager_addition > maximum_wager_addition:
                        raise ValueError(
                            f"pot-limit wager adds {wager_addition}, exceeding the"
                            f" legal maximum {maximum_wager_addition} from pot"
                            f" {pot_before_action} and call {call_amount}"
                        )
                if action.action_type == "uncalled_return":
                    other_live_commitments = [
                        live_commitments[seat.player_id]
                        for seat in self.seats
                        if seat.player_id != action.actor_id
                        and seat.participation in {"dealt_in", "unknown"}
                    ]
                    if (
                        actor_live_commitment is not None
                        and resolved_live_commitment is not None
                        and all(
                            commitment is not None
                            for commitment in other_live_commitments
                        )
                    ):
                        matched_live_commitment = max(
                            (
                                commitment
                                for commitment in other_live_commitments
                                if commitment is not None
                            ),
                            default=Decimal(0),
                        )
                        if (
                            actor_live_commitment <= matched_live_commitment
                            or resolved_live_commitment != matched_live_commitment
                        ):
                            raise ValueError(
                                "an uncalled return must exactly settle the actor's"
                                " unique unmatched live commitment"
                            )
                        if actionable_players - {action.actor_id}:
                            raise ValueError(
                                "an uncalled return cannot occur while an opponent"
                                " response remains pending"
                            )
                        return_settles_round = True
                if (
                    actor_seat.starting_stack is not None
                    and resolved_cumulative_commitment is not None
                    and resolved_cumulative_commitment > actor_seat.starting_stack
                ):
                    raise ValueError(
                        f"{action.actor_id} cumulative commitment"
                        f" {resolved_cumulative_commitment} exceeds known starting"
                        f" stack {actor_seat.starting_stack}"
                    )
                if (
                    actor_seat.starting_stack is not None
                    and resolved_commitment is not None
                    and resolved_commitment > actor_seat.starting_stack
                ):
                    raise ValueError(
                        f"{action.actor_id} street commitment"
                        f" {resolved_commitment} exceeds known starting"
                        f" stack {actor_seat.starting_stack}"
                    )
                if (
                    actor_seat.starting_stack is not None
                    and action.action_type in _CHIP_ACTIONS - {"uncalled_return"}
                    and action.amount is not None
                    and action.amount > actor_seat.starting_stack
                ):
                    raise ValueError(
                        f"{action.actor_id} chip action amount {action.amount}"
                        f" exceeds known starting stack {actor_seat.starting_stack}"
                    )
                if (
                    actor_seat.starting_stack is not None
                    and resolved_cumulative_minimum > actor_seat.starting_stack
                ):
                    raise ValueError(
                        f"{action.actor_id} cumulative commitment lower bound"
                        f" {resolved_cumulative_minimum} exceeds"
                        f" known starting stack {actor_seat.starting_stack}"
                    )
                if (
                    actor_seat.starting_stack is not None
                    and resolved_cumulative_unresolved_positive
                    and resolved_cumulative_minimum == actor_seat.starting_stack
                ):
                    raise ValueError(
                        f"{action.actor_id} cumulative commitment lower bound"
                        f" {resolved_cumulative_minimum} equals known"
                        f" starting stack {actor_seat.starting_stack} while a"
                        " positive contribution remains numerically unresolved"
                    )
                positive_forced_commitment_evidence = any(
                    value is not None and value > 0
                    for value in (
                        resolved_cumulative_commitment,
                        resolved_commitment,
                        action.amount,
                    )
                )
                if action.action_type == "uncalled_return":
                    forced_stack_exhausted_players.discard(action.actor_id)
                elif (
                    action.action_type == "post_ante"
                    and (
                        known_stack_exhausted
                        or (
                            actor_seat.starting_stack is None
                            and confirmed_all_in
                            and positive_forced_commitment_evidence
                        )
                    )
                ):
                    forced_stack_exhausted_players.add(action.actor_id)
                if _apply_terminal_transition(
                    action,
                    street.street,
                    confirmed_all_in=confirmed_all_in,
                    known_stack_exhausted=known_stack_exhausted,
                    terminal_actors=terminal_actors,
                    live_players=live_players,
                    actionable_players=actionable_players,
                    inferred_stack_exhausted_players=(
                        inferred_stack_exhausted_players
                    ),
                ):
                    # A return restored chips to a player whose all-in state was
                    # inferred only from their prior known commitment. The
                    # hand-wide betting closure must be reconsidered with that
                    # player actionable again.
                    betting_closed_by_all_ins = False
                if action.action_type == "fold" and len(live_players) == 1:
                    fold_end = (street.street, next(iter(live_players)))
                cumulative_commitments[action.actor_id] = (
                    resolved_cumulative_commitment
                )
                cumulative_commitment_lower_bounds[action.actor_id] = (
                    resolved_cumulative_commitment_lower_bound
                )
                cumulative_unresolved_minimum_dead[action.actor_id] = (
                    unresolved_minimum_dead_before_street[action.actor_id]
                    + resolved_street_unresolved_minimum_dead
                )
                cumulative_unresolved_minimum_live[action.actor_id] = (
                    unresolved_minimum_live_before_street[action.actor_id]
                    + resolved_street_unresolved_minimum_live
                )
                cumulative_unresolved_positive_dead[action.actor_id] = any(
                    (
                        unresolved_positive_dead_before_street[action.actor_id],
                        resolved_street_unresolved_positive_dead,
                    )
                )
                cumulative_unresolved_positive_live[action.actor_id] = any(
                    (
                        unresolved_positive_live_before_street[action.actor_id],
                        resolved_street_unresolved_positive_live,
                    )
                )
                street_commitments[action.actor_id] = resolved_commitment
                street_commitment_lower_bounds[action.actor_id] = (
                    resolved_street_commitment_lower_bound
                )
                street_unresolved_minimum_dead[action.actor_id] = (
                    resolved_street_unresolved_minimum_dead
                )
                street_unresolved_minimum_live[action.actor_id] = (
                    resolved_street_unresolved_minimum_live
                )
                street_unresolved_positive_dead[action.actor_id] = (
                    resolved_street_unresolved_positive_dead
                )
                street_unresolved_positive_live[action.actor_id] = (
                    resolved_street_unresolved_positive_live
                )
                live_commitments[action.actor_id] = resolved_live_commitment
                last_full_wager_increment = _updated_full_wager_increment(
                    action,
                    last_full_wager_increment=last_full_wager_increment,
                    blinds=self.game.blinds,
                    posted_amount=posted_amount,
                    bet_increment=bet_increment,
                    raise_increment=raise_increment,
                    confirmed_all_in=confirmed_all_in,
                )
                if action.action_type in {
                    "bet",
                    "raise",
                    "post_small_blind",
                    "post_big_blind",
                    "post_straddle",
                }:
                    if (
                        action.action_type == "post_big_blind"
                        and short_forced_post
                        and configured_post_amount is not None
                        and len(live_players) >= 3
                    ):
                        nominal_bring_in = max(
                            nominal_bring_in,
                            configured_post_amount,
                        )
                    if resolved_live_commitment is None:
                        current_wager = None
                    elif current_wager is None:
                        current_wager = resolved_live_commitment
                    else:
                        current_wager = max(
                            current_wager,
                            resolved_live_commitment,
                            nominal_bring_in,
                        )
                elif action.action_type == "uncalled_return":
                    if resolved_live_commitment is None:
                        # An unresolved return cannot erase a previously known
                        # wager target and thereby legalize later action.
                        pass
                    elif any(
                        commitment is None
                        for commitment in live_commitments.values()
                    ):
                        current_wager = None
                    else:
                        current_wager = max(
                            *(
                                commitment
                                for commitment in live_commitments.values()
                                if commitment is not None
                            ),
                        )
                    return_seen = True
                    round_closed_by_return = return_settles_round
                if action.action_type in {"check", "bet", "call", "raise"}:
                    acted_wager_by_player[action.actor_id] = current_wager
                    reopen_increment_by_player[action.actor_id] = (
                        last_full_wager_increment
                    )
                sole_actionable_player = (
                    _sole_actionable_player_with_only_all_in_opponents(
                        live_players,
                        actionable_players,
                    )
                )
                if (
                    sole_actionable_player is not None
                    and current_wager is not None
                    and live_commitments[sole_actionable_player] is not None
                    and live_commitments[sole_actionable_player] >= current_wager
                ):
                    betting_closed_by_all_ins = True
                if (
                    clockwise_action_order is not None
                    and preflop_action_order is not None
                ):
                    if (
                        street.street == "preflop"
                        and pending_action_players is None
                        and action.action_type == "post_straddle"
                    ):
                        last_preflop_straddler = action.actor_id
                    if action.action_type in _TABLE_ACTIONS:
                        if action.action_type in {"bet", "raise"}:
                            pending_action_players = set(actionable_players)
                            pending_action_players.discard(action.actor_id)
                        else:
                            assert pending_action_players is not None
                            pending_action_players.discard(action.actor_id)
                            pending_action_players.intersection_update(
                                actionable_players
                            )
                        if pending_action_players:
                            next_action_player = _next_clockwise_player(
                                clockwise_action_order,
                                action.actor_id,
                                pending_action_players,
                            )
                        else:
                            next_action_player = None
                            known_action_round_closed = True
                    elif pending_action_players is not None:
                        pending_action_players.intersection_update(
                            actionable_players
                        )
                        if not pending_action_players:
                            next_action_player = None
                            known_action_round_closed = True
                        elif next_action_player not in pending_action_players:
                            next_action_player = _next_clockwise_player(
                                clockwise_action_order,
                                action.actor_id,
                                pending_action_players,
                            )
                if action.action_type in _TABLE_ACTIONS:
                    table_decision_seen = True
            if street.street == "preflop":
                missing_antes = missing_ante_posts()
                if missing_antes:
                    raise ValueError(
                        "the preflop street cannot end before all configured"
                        " ante posts; missing "
                        + ", ".join(missing_antes)
                    )
                missing_blind_posts = missing_structural_blind_posts()
                if missing_blind_posts:
                    raise ValueError(
                        "the preflop street cannot end before all configured"
                        " structural blind posts; missing "
                        + ", ".join(missing_blind_posts)
                    )
                if configured_straddle_required and not seen_straddle_players:
                    raise ValueError(
                        "the preflop street cannot end before a configured"
                        " post_straddle"
                    )
            closes_known_round = (
                street_index < len(self.streets) - 1
                or (
                    street_index == len(self.streets) - 1
                    and self.results is not None
                )
            )
            sole_actionable_player = (
                _sole_actionable_player_with_only_all_in_opponents(
                    live_players,
                    actionable_players,
                )
            )
            all_in_action_complete = (
                betting_closed_by_all_ins
                or not actionable_players
                or (
                    sole_actionable_player is not None
                    and current_wager is not None
                    and live_commitments[sole_actionable_player] is not None
                    and live_commitments[sole_actionable_player] >= current_wager
                )
            )
            observed_action_round_closed = (
                current_wager is not None
                and all(
                    acted_wager_by_player.get(player_id) == current_wager
                    for player_id in actionable_players
                )
            )
            if street_index == len(self.streets) - 1:
                final_street_betting_complete = (
                    fold_end is not None
                    or round_closed_by_return
                    or all_in_action_complete
                    or observed_action_round_closed
                    or (
                        known_action_orders is not None
                        and known_action_round_closed
                    )
                )
            if (
                closes_known_round
                and known_action_orders is not None
                and not known_action_round_closed
                and fold_end is None
                and not round_closed_by_return
                and not all_in_action_complete
            ):
                raise ValueError(
                    "a street cannot end before the known action round is complete"
                )
            if closes_known_round and current_wager is not None:
                for seat in self.seats:
                    if (
                        seat.participation != "dealt_in"
                        or seat.player_id in terminal_actors
                    ):
                        continue
                    live_commitment = live_commitments[seat.player_id]
                    if (
                        live_commitment is not None
                        and live_commitment < current_wager
                    ):
                        raise ValueError(
                            "a street cannot end while a non-folded, non-all-in"
                            " player has not matched the known wager"
                        )
                possible_contenders = [
                    seat.player_id
                    for seat in self.seats
                    if seat.participation in {"dealt_in", "unknown"}
                ]
                contender_commitments = [
                    live_commitments[player_id]
                    for player_id in possible_contenders
                ]
                highest_actual_commitment = (
                    max(
                        commitment
                        for commitment in contender_commitments
                        if commitment is not None
                    )
                    if contender_commitments
                    and all(
                        commitment is not None
                        for commitment in contender_commitments
                    )
                    else None
                )
                if (
                    highest_actual_commitment is not None
                    and highest_actual_commitment > 0
                    and sum(
                        commitment == highest_actual_commitment
                        for commitment in contender_commitments
                    )
                    < 2
                ):
                    raise ValueError(
                        "a street cannot end with a unique unmatched top wager;"
                        " an uncalled return is required"
                    )
            if committed_pot_before_street is not None and all(
                commitment is not None for commitment in street_commitments.values()
            ):
                committed_pot_before_street += sum(
                    (
                        commitment
                        for commitment in street_commitments.values()
                        if commitment is not None
                    ),
                    Decimal(0),
                )
            else:
                committed_pot_before_street = None
        if self.results is not None:
            referenced_result_players = {
                *(entry.player_id for entry in self.results.showdown),
                *(award.player_id for award in self.results.awards),
                *(result.player_id for result in self.results.players),
            }
            if not referenced_result_players.issubset(player_ids):
                raise ValueError("showdown, award, and result players must identify known seats")
            explicit_nonparticipants = {
                seat.player_id
                for seat in self.seats
                if seat.participation in {"sitting_out", "not_dealt"}
            }
            showdown_and_award_players = {
                *(entry.player_id for entry in self.results.showdown),
                *(award.player_id for award in self.results.awards),
            }
            if showdown_and_award_players.intersection(explicit_nonparticipants):
                raise ValueError(
                    "showdown participants and award recipients cannot be explicitly"
                    " sitting out or not dealt"
                )
            folded_players = {
                player_id
                for player_id, (reason, _) in terminal_actors.items()
                if reason == "folded"
            }
            folded_result_players = showdown_and_award_players.intersection(
                folded_players
            )
            if folded_result_players:
                raise ValueError(
                    "folded players cannot appear in showdown or receive pot"
                    " awards: " + ", ".join(sorted(folded_result_players))
                )
            for player_result in self.results.players:
                if player_result.player_id not in folded_players:
                    continue
                if (
                    player_result.total_collected is not None
                    and player_result.total_collected > 0
                ):
                    raise ValueError(
                        f"folded player {player_result.player_id} cannot report"
                        " positive total_collected"
                    )
                exact_contribution = cumulative_commitments[
                    player_result.player_id
                ]
                if (
                    player_result.total_collected is None
                    and player_result.net_result is not None
                    and exact_contribution is not None
                ):
                    implied_collection = (
                        player_result.net_result + exact_contribution
                    )
                    if implied_collection > 0:
                        raise ValueError(
                            f"folded player {player_result.player_id} net_result"
                            f" implies positive collection {implied_collection}"
                            " from exact contribution"
                            f" {exact_contribution}"
                        )
            if fold_end is None:
                if self.streets[-1].street != "river":
                    raise ValueError(
                        "results require the hand to reach a completed river or"
                        " end by folds"
                    )
                if not final_street_betting_complete:
                    raise ValueError(
                        "results require completed river betting or a fold-ended"
                        " terminal hand"
                    )

        boards = [street.board_cards for street in self.streets]
        previous_known_board: list[Card] | None = None
        for current in boards:
            if not current:
                continue
            if (
                previous_known_board is not None
                and current[: len(previous_known_board)] != previous_known_board
            ):
                raise ValueError("street boards must preserve the earlier board prefix")
            previous_known_board = current
        all_cards = [*self.hero_cards]
        if boards:
            all_cards.extend(max(boards, key=len))
        if len({card.code for card in all_cards}) != len(all_cards):
            raise ValueError("hero and board cards must be unique")
        _validate_showdown_cards(self)

        return self


class DetectedFieldEvidence(ImportedHandModel):
    confidence: UnitIntervalDecimal | None = None
    evidence: list[SourceEvidence] = Field(default_factory=list)
    warnings: list[NonEmptyText] = Field(default_factory=list)


class DetectedImportedHand(ImportedHandModel):
    schema_version: Literal["detected-imported-hand/v1"] = "detected-imported-hand/v1"
    detection_id: Identifier
    raw_source_id: Identifier
    detector_id: Identifier
    detector_version: Identifier
    detected_at: AwareDatetime
    state: ImportedHandState
    field_evidence: dict[str, DetectedFieldEvidence] = Field(default_factory=dict)
    warnings: list[NonEmptyText] = Field(default_factory=list)
    content_sha256: Sha256

    @model_validator(mode="after")
    def validate_detected_provenance(self) -> Self:
        _validate_detected_action_origins(self.state)
        if self.state.chronology.source_file_id != self.raw_source_id:
            raise ValueError(
                "detected state source_file_id must equal the detected raw_source_id"
            )
        if self.content_sha256 != imported_hand_state_sha256(self.state):
            raise ValueError("content_sha256 must match the normalized detected state")
        evidence_ids = {
            item.raw_source_id for item in _detected_source_evidence(self)
        }
        if evidence_ids.difference({self.raw_source_id}):
            raise ValueError(
                "detected evidence must reference only the detected raw source"
            )
        state_document = json.loads(self.state.model_dump_json())
        for pointer in self.field_evidence:
            try:
                _pointer_get(state_document, pointer)
            except ValueError as exc:
                raise ValueError(
                    f"field_evidence path does not exist in detected state: {pointer}"
                ) from exc
        return self

    @field_validator("field_evidence")
    @classmethod
    def validate_field_evidence_paths(
        cls, value: dict[str, DetectedFieldEvidence]
    ) -> dict[str, DetectedFieldEvidence]:
        for pointer in value:
            _validate_json_pointer(pointer)
        return value


class UserCorrection(ImportedHandModel):
    field_pointer: NonEmptyText
    detected_value: JsonValue
    approved_value: JsonValue
    corrected_at: AwareDatetime
    reason: str | None = Field(default=None, max_length=500, strict=True)

    @field_validator("field_pointer")
    @classmethod
    def validate_pointer(cls, value: str) -> str:
        _validate_json_pointer(value)
        return value


class CanonicalHandRevision(ImportedHandModel):
    schema_version: Literal["canonical-imported-hand/v1"] = "canonical-imported-hand/v1"
    revision: PositiveInteger
    detection_id: Identifier
    approved_at: AwareDatetime
    state: ImportedHandState
    corrections: list[UserCorrection] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_corrections(self) -> Self:
        pointers = [correction.field_pointer for correction in self.corrections]
        _validate_non_overlapping_correction_pointers(pointers)
        _validate_correction_timestamps(self)
        _validate_user_confirmed_origin_correction_presence(self)
        return self


class ImportConflict(ImportedHandModel):
    conflict_id: Identifier
    raw_source_ids: list[Identifier] = Field(min_length=2)
    detected_ids: list[Identifier] = Field(default_factory=list)
    active_canonical_revision_at_creation: PositiveInteger | None
    status: Literal["unresolved", "resolved_keep_active", "resolved_use_source"] = "unresolved"
    selected_raw_source_id: Identifier | None = None
    resolved_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        if len(self.raw_source_ids) != len(set(self.raw_source_ids)):
            raise ValueError("conflict raw_source_ids must be unique")
        if self.status != "unresolved":
            if self.selected_raw_source_id not in self.raw_source_ids:
                raise ValueError("resolved source must belong to the conflict")
            if self.resolved_at is None:
                raise ValueError("resolved conflict requires resolved_at")
        else:
            if self.selected_raw_source_id is not None:
                raise ValueError("only a resolved conflict can select a raw source")
            if self.resolved_at is not None:
                raise ValueError("an unresolved conflict cannot have resolved_at")
        return self


class DeletionRequest(ImportedHandModel):
    generation: PositiveInteger
    requested_at: AwareDatetime
    cleanup_status: Literal["pending", "failed"] = "pending"
    last_error: str | None = Field(default=None, max_length=1000, strict=True)

    @model_validator(mode="after")
    def validate_cleanup_failure(self) -> Self:
        if self.cleanup_status == "failed" and not self.last_error:
            raise ValueError("failed cleanup must expose its error")
        if self.cleanup_status == "pending" and self.last_error is not None:
            raise ValueError("pending cleanup cannot have a failure error")
        return self


class DeletionReceipt(ImportedHandModel):
    receipt_id: Identifier
    generation: PositiveInteger
    deleted_at: AwareDatetime
    tombstone_sha256: Sha256


class ImportedHandLifecycle(ImportedHandModel):
    status: LifecycleStatus
    active_canonical_revision: PositiveInteger | None = None
    deletion_generation: NonNegativeInteger = 0
    changed_at: AwareDatetime
    reason: NonEmptyText | None = None
    deletion_request: DeletionRequest | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.status == "active":
            if self.active_canonical_revision is None:
                raise ValueError("active lifecycle requires an active canonical revision")
        elif self.active_canonical_revision is not None:
            raise ValueError("inactive lifecycle cannot retain an active canonical pointer")
        if self.status == "deletion_pending":
            if self.deletion_request is None:
                raise ValueError("deletion_pending requires a deletion request")
            if self.deletion_request.generation != self.deletion_generation:
                raise ValueError("deletion request generation must match lifecycle generation")
        elif self.deletion_request is not None:
            raise ValueError("only deletion_pending can retain a deletion request")
        return self

    @property
    def learning_eligible(self) -> bool:
        return self.status == "active" and self.active_canonical_revision is not None


class SeatDecisionState(ImportedHandModel):
    """A dealt-in player's chip position immediately before a hero action.

    ``street_commitment`` and ``live_commitment`` differ by exactly the dead
    chips this player has posted on the street -- antes, which pay the pot but
    do not answer a wager. Only ``live_commitment`` is comparable to
    ``HeroActionContext.current_wager``: a call costs
    ``current_wager - live_commitment``, and subtracting the ante-inclusive
    ``street_commitment`` instead understates it by the posted ante.
    """

    player_id: Identifier
    position: StructuralPosition
    starting_stack: NonNegativeDecimal
    stack_before_action: NonNegativeDecimal
    street_commitment: NonNegativeDecimal
    live_commitment: NonNegativeDecimal
    hand_commitment: NonNegativeDecimal
    status: SeatDecisionStatus


class ResolvedAction(ImportedHandModel):
    """One imported action with the chips the extraction walk resolved for it.

    A source may state an action's incremental ``amount``, its street-cumulative
    ``total_committed``, or only one of the two. The walk resolves both from the
    ordered stream, so consumers read the resolved values rather than whichever
    field the adapter happened to fill. A value stays ``None`` only when the
    walk could not establish it exactly.

    ``all_in`` is likewise the verdict the walk reached, read back from the
    terminal state its own transition produced -- not the source's marker. A
    source that omits the marker on an action which exhausts a known stack
    still leaves its actor all-in, and the seat status published beside this
    record says so, so the two must be decided by the same rule.
    """

    action: ImportedAction
    amount: PositiveDecimal | None
    total_committed: NonNegativeDecimal | None
    all_in: bool


class StreetActionSlice(ImportedHandModel):
    """The ordered actions of one street as the extraction walk saw them.

    Completed streets carry every action; the street the hero is acting on is
    truncated immediately before the hero's own action, so the slice is exactly
    what the hero could have observed when deciding.
    """

    street: StreetName
    actions: list[ResolvedAction]


class HeroActionContext(ImportedHandModel):
    """Exact chip state the aggregate computed for one voluntary hero action.

    ``last_full_wager_increment`` is the yardstick a minimum legal raise is
    measured against -- the last full bet or raise increment still in force.
    ``None`` means the aggregate could not establish it; a known increment is
    always positive, so ``None`` is the only "unknown" and can never be
    confused with one. A consumer that cannot size a raise has to withhold the
    raise rather than offer one of arbitrary size.

    ``raise_reopened`` reports whether raising is legal for the hero here.
    It is ``False`` for either of two reasons the hand validator enforces:
    an actor who has already acted on this street is reopened only once
    the wager has grown by at least the increment that stood when they
    acted, so a short all-in leaves them call-or-fold; or the hero is the
    sole actionable player and every live opponent is all-in, so no one
    could answer a raise and the validator rejects one outright. It is
    ``True`` whenever the aggregate holds no evidence that betting is
    closed, which is exactly when the validator would admit a raise.

    ``action_history`` is the ordered betting line: every street from preflop
    through this one, with this street truncated before the hero's own action.
    Distinct lines reach identical pots, wagers, and commitments, so the chip
    snapshot alone cannot identify the spot a line-sensitive consumer needs.

    ``action`` is the hero's action exactly as approved, and ``resolved_action``
    wraps that same object with the chips and all-in verdict the walk resolved
    for it -- the treatment every opponent action already gets in the line. The
    raw field stays because ``active_hero_actions_for_extraction`` returns it.
    """

    @model_validator(mode="after")
    def validate_resolved_action(self) -> Self:
        if self.resolved_action.action != self.action:
            raise ValueError(
                "resolved_action must resolve this context's own hero action"
            )
        return self

    street: StreetName
    action_sequence: NonNegativeInteger
    action: ImportedAction
    resolved_action: ResolvedAction
    board_cards: list[Card]
    action_history: list[StreetActionSlice]
    committed_pot_before_street: NonNegativeDecimal
    pot_before_action: NonNegativeDecimal
    current_wager: NonNegativeDecimal
    amount_to_call: NonNegativeDecimal
    last_full_wager_increment: PositiveDecimal | None
    raise_reopened: bool
    hero_stack_before_action: NonNegativeDecimal
    seats: list[SeatDecisionState]


class ImportedHandRecord(ImportedHandModel):
    """Aggregate shape; persistence must transition it atomically."""

    schema_version: Literal["imported-hand-record/v1"] = "imported-hand-record/v1"
    identity: StableHandIdentity | None
    raw_sources: list[RawHandHistory] = Field(default_factory=list)
    detections: list[DetectedImportedHand] = Field(default_factory=list)
    conflicts: list[ImportConflict] = Field(default_factory=list)
    canonical_revisions: list[CanonicalHandRevision] = Field(default_factory=list)
    lifecycle: ImportedHandLifecycle
    deletion_receipt: DeletionReceipt | None = None

    def revalidated_snapshot(self) -> Self:
        """Rebuild the complete mutable graph before a trusted boundary."""

        payload = _unvalidated_python_graph(self)
        snapshot = type(self).model_validate(payload)
        _preserve_model_fields_set(self, snapshot)
        return snapshot

    @model_serializer(mode="wrap")
    def serialize_revalidated(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> Any:
        """Serialize only a complete, freshly validated aggregate snapshot."""

        return handler(self.revalidated_snapshot())

    @model_validator(mode="after")
    def validate_aggregate(self) -> Self:
        if self.lifecycle.status == "deleted":
            if self.identity is not None:
                raise ValueError("a deletion tombstone cannot retain the stable hand identity")
            if any(
                (
                    self.raw_sources,
                    self.detections,
                    self.conflicts,
                    self.canonical_revisions,
                )
            ):
                raise ValueError("permanently deleted records cannot retain hand-linked audit data")
            if self.deletion_receipt is None:
                raise ValueError("permanently deleted record requires a deletion receipt")
            if self.deletion_receipt.generation != self.lifecycle.deletion_generation:
                raise ValueError("deletion receipt generation must match lifecycle generation")
            if self.lifecycle.changed_at < self.deletion_receipt.deleted_at:
                raise ValueError(
                    "deleted lifecycle changed_at cannot precede deletion receipt"
                    " deleted_at"
                )
            return self
        elif self.identity is None:
            raise ValueError("a retained imported hand requires its stable identity")
        if self.deletion_receipt is not None:
            raise ValueError("only permanently deleted records can retain a deletion receipt")
        for raw in self.raw_sources:
            if raw.identity != self.identity:
                raise ValueError("all raw sources must share the stable hand identity")
        _validate_unique(self.raw_sources, "raw_source_id", "raw source")
        _validate_unique(self.raw_sources, "content_sha256", "raw source content")
        _validate_unique(self.detections, "detection_id", "detection")
        _validate_unique(self.conflicts, "conflict_id", "conflict")

        raw_by_id = {raw.raw_source_id: raw for raw in self.raw_sources}
        raw_ids = set(raw_by_id)
        detection_by_id = {detected.detection_id: detected for detected in self.detections}
        for detected in self.detections:
            _validate_detected_action_origins(detected.state)
            if detected.raw_source_id not in raw_ids:
                raise ValueError("detected hand must reference a retained raw source")
            detected_raw_source = raw_by_id[detected.raw_source_id]
            if detected.detected_at < detected_raw_source.provenance.imported_at:
                raise ValueError(
                    f"detection {detected.detection_id} detected_at cannot"
                    f" precede referenced raw source {detected.raw_source_id}"
                    " imported_at"
                )
            if detected.state.identity != self.identity:
                raise ValueError("detected hand must share the stable hand identity")
            for item in _detected_source_evidence(detected):
                _validate_source_evidence_location(
                    item,
                    raw_by_id[detected.raw_source_id],
                )
        for conflict in self.conflicts:
            if not set(conflict.raw_source_ids).issubset(raw_ids):
                raise ValueError("conflict must reference retained raw sources")
            if not set(conflict.detected_ids).issubset(detection_by_id):
                raise ValueError("conflict must reference retained detections")
            if any(
                detection_by_id[detection_id].raw_source_id
                not in conflict.raw_source_ids
                for detection_id in conflict.detected_ids
            ):
                raise ValueError(
                    "conflict detections must belong to the conflict raw sources"
                )

        revisions = [revision.revision for revision in self.canonical_revisions]
        if revisions != list(range(1, len(revisions) + 1)):
            raise ValueError("canonical revisions must be monotonic and contiguous from one")
        previous_revision: CanonicalHandRevision | None = None
        for revision in self.canonical_revisions:
            detected = detection_by_id.get(revision.detection_id)
            if detected is None:
                raise ValueError("canonical revision must reference a retained detection")
            if revision.approved_at < detected.detected_at:
                raise ValueError(
                    f"canonical revision {revision.revision} approved_at cannot"
                    f" precede referenced detection {detected.detection_id} detected_at"
                )
            if (
                previous_revision is not None
                and revision.approved_at < previous_revision.approved_at
            ):
                raise ValueError(
                    f"canonical revision {revision.revision} approved_at cannot"
                    f" precede canonical revision {previous_revision.revision} approved_at"
                )
            previous_revision = revision
            if revision.state.identity != self.identity:
                raise ValueError("canonical revision must share the stable hand identity")
            if revision.state.chronology.source_file_id != detected.raw_source_id:
                raise ValueError(
                    "canonical revision source_file_id must match its detected raw source"
                )
            revision_evidence = _state_source_evidence(revision.state)
            if not {
                item.raw_source_id for item in revision_evidence
            }.issubset(raw_ids):
                raise ValueError(
                    "canonical source evidence must reference a retained raw source"
                )
            for item in revision_evidence:
                _validate_source_evidence_location(
                    item,
                    raw_by_id[item.raw_source_id],
                )
            _validate_corrections_win(detected, revision)

        for conflict in self.conflicts:
            preserved_source_id = _conflict_preserved_source_id(
                conflict,
                detection_by_id=detection_by_id,
                revisions=self.canonical_revisions,
            )
            _validate_resolved_keep_active_source(
                conflict,
                preserved_source_id=preserved_source_id,
            )
            _validate_conflict_resolution_chronology(
                conflict,
                raw_by_id=raw_by_id,
                detection_by_id=detection_by_id,
                revisions=self.canonical_revisions,
                lifecycle_changed_at=self.lifecycle.changed_at,
            )

        active = self.lifecycle.active_canonical_revision
        if active is not None:
            if not revisions or active != revisions[-1]:
                raise ValueError("the active pointer must select the latest canonical revision")
            active_revision = self.canonical_revisions[active - 1]
            if self.lifecycle.changed_at < active_revision.approved_at:
                raise ValueError(
                    "active lifecycle changed_at cannot precede the selected"
                    " canonical revision approved_at"
                )
            latest_event = _latest_retained_audit_event(self)
            if (
                latest_event is not None
                and self.lifecycle.changed_at < latest_event[0]
            ):
                raise ValueError(
                    "active lifecycle changed_at cannot precede the"
                    f" latest retained {latest_event[1]}"
                )
        _validate_canonical_source_lineage(
            conflicts=self.conflicts,
            detection_by_id=detection_by_id,
            revisions=self.canonical_revisions,
            validate_active_conflicts=active is not None,
        )

        if self.lifecycle.status == "pending_review":
            latest_event = _latest_retained_audit_event(self)
            if (
                latest_event is not None
                and self.lifecycle.changed_at < latest_event[0]
            ):
                raise ValueError(
                    "pending_review lifecycle changed_at cannot precede the"
                    f" latest retained {latest_event[1]}"
                )
        elif self.lifecycle.status in {"withdrawn", "rejected"}:
            if not revisions:
                raise ValueError("withdrawal/rejection audit requires a canonical revision")
            latest_event = _latest_retained_audit_event(self)
            assert latest_event is not None
            if self.lifecycle.changed_at < latest_event[0]:
                raise ValueError(
                    "withdrawn/rejected lifecycle changed_at cannot precede the"
                    f" latest retained {latest_event[1]}"
                )
        elif self.lifecycle.status == "deletion_pending":
            deletion_request = self.lifecycle.deletion_request
            assert deletion_request is not None
            if self.lifecycle.changed_at < deletion_request.requested_at:
                raise ValueError(
                    "deletion_pending lifecycle changed_at cannot precede deletion"
                    " request requested_at"
                )
            for raw in self.raw_sources:
                if deletion_request.requested_at < raw.provenance.imported_at:
                    raise ValueError(
                        "deletion request requested_at cannot precede retained"
                        f" raw source {raw.raw_source_id} imported_at"
                    )
            for detected in self.detections:
                if deletion_request.requested_at < detected.detected_at:
                    raise ValueError(
                        "deletion request requested_at cannot precede retained"
                        f" detection {detected.detection_id} detected_at"
                    )
            for conflict in self.conflicts:
                if (
                    conflict.resolved_at is not None
                    and deletion_request.requested_at < conflict.resolved_at
                ):
                    raise ValueError(
                        "deletion request requested_at cannot precede retained"
                        f" conflict {conflict.conflict_id} resolved_at"
                    )
            if revisions:
                latest_approved_at = self.canonical_revisions[-1].approved_at
                if self.lifecycle.changed_at < latest_approved_at:
                    raise ValueError(
                        "deletion_pending lifecycle changed_at cannot precede the"
                        " latest canonical revision approved_at"
                    )
                if deletion_request.requested_at < latest_approved_at:
                    raise ValueError(
                        "deletion request requested_at cannot precede the latest"
                        " canonical revision approved_at"
                    )
        if len(raw_ids) > 1:
            conflict_source_ids = {
                raw_source_id
                for conflict in self.conflicts
                for raw_source_id in conflict.raw_source_ids
            }
            if conflict_source_ids != raw_ids:
                raise ValueError(
                    "every materially distinct retained raw source must be covered"
                    " by retained conflict audit state"
                )
        return self

    def _active_extraction_context(
        self,
    ) -> tuple[
        ImportedHandState,
        DetectedImportedHand,
        CanonicalHandRevision,
    ] | None:
        """Resolve state and its audit provenance from one validated snapshot."""

        try:
            snapshot = self.revalidated_snapshot()
        except (
            AttributeError,
            IndexError,
            KeyError,
            PydanticSerializationError,
            TypeError,
            ValidationError,
            ValueError,
        ):
            return None
        if not snapshot.lifecycle.learning_eligible:
            return None
        if not _record_conflict_resolution_is_valid(snapshot):
            return None
        revision = snapshot.lifecycle.active_canonical_revision
        if revision is None:
            return None
        active_revision = snapshot.canonical_revisions[revision - 1]
        active_detection = next(
            (
                detection
                for detection in snapshot.detections
                if detection.detection_id == active_revision.detection_id
            ),
            None,
        )
        if active_detection is None:
            return None
        return active_revision.state, active_detection, active_revision

    @property
    def active_state_for_extraction(self) -> ImportedHandState | None:
        context = self._active_extraction_context()
        return context[0] if context is not None else None

    @property
    def active_hero_decision_contexts(self) -> list[HeroActionContext]:
        """Return voluntary hero decisions with their exact chip context.

        Forced, client-automatic, and unresolved actions remain in the canonical
        audit stream but cannot become learning decision points. Player-selected
        decisions require a fully resolved, derivable dealt-in seat ring, known
        starting stacks for every dealt-in player, two approved hero cards, and
        the complete cumulative board for their street. Wagers also require an
        approved chip representation before extraction.
        """

        context = self._active_extraction_context()
        if context is None:
            return []
        state, detection, revision = context
        if state.hero_player_id is None:
            return []
        if not _terminal_hand_ready_for_extraction(state):
            return []
        if not _blind_structure_ready_for_extraction(state.game.blinds):
            return []
        if state.game.betting_limit not in {"no_limit", "pot_limit"}:
            return []
        dealt_in_starting_stacks = {
            seat.player_id: seat.starting_stack
            for seat in state.seats
            if seat.participation == "dealt_in"
        }
        if not _economics_ready_for_extraction(
            state.game.economics,
            dealt_in_starting_stacks=dealt_in_starting_stacks,
        ):
            return []
        if not _pot_reconciliation_ready_for_extraction(
            state,
            detection=detection,
            revision=revision,
        ):
            return []
        if not _cash_rake_consistent_for_extraction(state):
            return []
        hero = next(
            seat for seat in state.seats if seat.player_id == state.hero_player_id
        )
        if hero.participation != "dealt_in":
            return []
        if any(seat.participation == "unknown" for seat in state.seats):
            return []
        if any(
            seat.participation == "dealt_in" and seat.starting_stack is None
            for seat in state.seats
        ):
            return []
        if _known_action_orders(state.seats, state.button_seat) is None:
            return []
        return _hero_decision_contexts_for_extraction(state)

    @property
    def active_hero_actions_for_extraction(self) -> list[ImportedAction]:
        """Return the bare hero decisions behind ``active_hero_decision_contexts``."""

        return [context.action for context in self.active_hero_decision_contexts]

    @property
    def active_pot_reconciles_for_extraction(self) -> bool:
        """Report the extraction gate's pot verdict for the active revision.

        The independent comparator needs the active detection and revision,
        which only the aggregate resolves, so callers outside it reuse this
        verdict instead of reconciling the pot a second time.
        """

        context = self._active_extraction_context()
        if context is None:
            return False
        state, detection, revision = context
        return _pot_reconciliation_ready_for_extraction(
            state,
            detection=detection,
            revision=revision,
        )


class ReimportDisposition(ImportedHandModel):
    kind: Literal["new_identity", "exact_reimport", "identity_conflict"]
    existing_raw_source_id: Identifier | None = None


class RestoreDisposition(ImportedHandModel):
    kind: Literal[
        "allow",
        "stale_deletion_generation",
        "stale_record",
        "conflict_merge_required",
        "explicit_reimport_required",
    ]


def classify_reimport(
    existing_sources: list[RawHandHistory],
    candidate: RawHandHistory,
    *,
    existing_detections: list[DetectedImportedHand] | None = None,
    candidate_detection: DetectedImportedHand | None = None,
) -> ReimportDisposition:
    """Classify a candidate without silently mutating an existing identity."""

    same_identity = [source for source in existing_sources if source.identity == candidate.identity]
    if not same_identity:
        return ReimportDisposition(kind="new_identity")
    exact = next(
        (source for source in same_identity if source.content_sha256 == candidate.content_sha256),
        None,
    )
    if exact is not None:
        if candidate_detection is not None and existing_detections:
            matching_detections = [
                detection
                for detection in existing_detections
                if detection.raw_source_id == exact.raw_source_id
            ]
            if matching_detections and all(
                _detected_state_semantic_sha256(detection.state)
                != _detected_state_semantic_sha256(candidate_detection.state)
                for detection in matching_detections
            ):
                return ReimportDisposition(kind="identity_conflict")
        return ReimportDisposition(
            kind="exact_reimport",
            existing_raw_source_id=exact.raw_source_id,
        )
    return ReimportDisposition(kind="identity_conflict")


def classify_restore(
    current: ImportedHandRecord,
    candidate: ImportedHandRecord,
    *,
    user_authorized_reimport: bool = False,
) -> RestoreDisposition:
    """Guard one persisted record slot against resurrection by an old backup."""

    try:
        current = current.revalidated_snapshot()
        candidate = candidate.revalidated_snapshot()
    except (
        AttributeError,
        IndexError,
        KeyError,
        PydanticSerializationError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        return RestoreDisposition(kind="conflict_merge_required")
    if not all(
        _record_conflict_resolution_is_valid(record)
        and _record_lifecycle_audit_chronology_is_valid(record)
        for record in (current, candidate)
    ):
        return RestoreDisposition(kind="conflict_merge_required")
    both_retained = current.identity is not None and candidate.identity is not None
    if both_retained and current.identity != candidate.identity:
        return RestoreDisposition(kind="conflict_merge_required")
    if candidate.lifecycle.deletion_generation < current.lifecycle.deletion_generation:
        return RestoreDisposition(kind="stale_deletion_generation")
    if (
        current.lifecycle.status == "deleted"
        and candidate.lifecycle.status != "deleted"
    ):
        return RestoreDisposition(
            kind=(
                "allow"
                if user_authorized_reimport
                else "explicit_reimport_required"
            )
        )
    if (
        current.lifecycle.status == "deletion_pending"
        and candidate.lifecycle.status == "deleted"
        and candidate.lifecycle.deletion_generation
        == current.lifecycle.deletion_generation
    ):
        current_request = current.lifecycle.deletion_request
        candidate_receipt = candidate.deletion_receipt
        assert current_request is not None
        assert candidate_receipt is not None
        if (
            candidate.lifecycle.changed_at < current.lifecycle.changed_at
            or candidate_receipt.deleted_at < current_request.requested_at
        ):
            return RestoreDisposition(kind="conflict_merge_required")
        return RestoreDisposition(kind="allow")
    current_revisions = current.canonical_revisions
    candidate_revisions = candidate.canonical_revisions
    if candidate.lifecycle.deletion_generation > current.lifecycle.deletion_generation:
        if candidate.lifecycle.status == "deleted":
            return RestoreDisposition(kind="allow")
        if both_retained:
            if (
                len(candidate_revisions) < len(current_revisions)
                or candidate_revisions[: len(current_revisions)] != current_revisions
                or (
                    current.lifecycle.status
                    in {"withdrawn", "rejected", "deletion_pending"}
                    and candidate.lifecycle.status == "active"
                )
                or (
                    current.lifecycle.status == "deletion_pending"
                    and candidate.lifecycle.status != "deletion_pending"
                )
                or not _restore_candidate_preserves_audit(current, candidate)
            ):
                return RestoreDisposition(kind="conflict_merge_required")
        return RestoreDisposition(kind="allow")

    common_revision_count = min(len(current_revisions), len(candidate_revisions))
    if (
        current_revisions[:common_revision_count]
        != candidate_revisions[:common_revision_count]
    ):
        return RestoreDisposition(kind="conflict_merge_required")

    current_changed_at = current.lifecycle.changed_at
    candidate_changed_at = candidate.lifecycle.changed_at
    if len(candidate_revisions) < len(current_revisions):
        return RestoreDisposition(
            kind=(
                "stale_record"
                if candidate_changed_at <= current_changed_at
                else "conflict_merge_required"
            )
        )
    if len(candidate_revisions) > len(current_revisions):
        if candidate_changed_at <= current_changed_at:
            return RestoreDisposition(kind="conflict_merge_required")
    elif candidate_changed_at < current_changed_at:
        return RestoreDisposition(kind="stale_record")
    elif candidate_changed_at == current_changed_at:
        return RestoreDisposition(
            kind="allow" if candidate == current else "conflict_merge_required"
        )

    if (
        current.lifecycle.status in {"withdrawn", "rejected", "deletion_pending"}
        and candidate.lifecycle.status == "active"
    ):
        return RestoreDisposition(kind="conflict_merge_required")
    if (
        current.lifecycle.status == "deletion_pending"
        and candidate.lifecycle.status != "deletion_pending"
    ):
        return RestoreDisposition(kind="conflict_merge_required")
    if not _restore_candidate_preserves_audit(current, candidate):
        return RestoreDisposition(kind="conflict_merge_required")
    return RestoreDisposition(kind="allow")


def _restore_candidate_preserves_audit(
    current: ImportedHandRecord,
    candidate: ImportedHandRecord,
) -> bool:
    if current.identity != candidate.identity:
        return False
    if current.deletion_receipt != candidate.deletion_receipt:
        return False
    for attribute, key in (
        ("raw_sources", "raw_source_id"),
        ("detections", "detection_id"),
    ):
        current_items = getattr(current, attribute)
        candidate_by_id = {
            getattr(item, key): item for item in getattr(candidate, attribute)
        }
        if any(
            candidate_by_id.get(getattr(item, key)) != item
            for item in current_items
        ):
            return False

    candidate_conflicts = {
        conflict.conflict_id: conflict for conflict in candidate.conflicts
    }
    for conflict in current.conflicts:
        candidate_conflict = candidate_conflicts.get(conflict.conflict_id)
        if candidate_conflict is None:
            return False
        immutable_fields_match = (
            candidate_conflict.raw_source_ids == conflict.raw_source_ids
            and candidate_conflict.detected_ids == conflict.detected_ids
            and candidate_conflict.active_canonical_revision_at_creation
            == conflict.active_canonical_revision_at_creation
        )
        if not immutable_fields_match:
            return False
        if conflict.status != "unresolved" and candidate_conflict != conflict:
            return False
        if (
            conflict.status == "unresolved"
            and candidate_conflict.status == "unresolved"
            and candidate_conflict != conflict
        ):
            return False
    return True


def _latest_conflict_referenced_event_at(
    conflict: ImportConflict,
    *,
    raw_by_id: dict[str, RawHandHistory],
    detection_by_id: dict[str, DetectedImportedHand],
    revisions: list[CanonicalHandRevision],
) -> datetime:
    referenced_events = [
        raw_by_id[raw_source_id].provenance.imported_at
        for raw_source_id in conflict.raw_source_ids
    ]
    referenced_events.extend(
        detection_by_id[detection_id].detected_at
        for detection_id in conflict.detected_ids
    )
    preserved_revision = conflict.active_canonical_revision_at_creation
    if preserved_revision is not None:
        referenced_events.append(revisions[preserved_revision - 1].approved_at)
    return max(referenced_events)


def _conflict_preserved_source_id(
    conflict: ImportConflict,
    *,
    detection_by_id: dict[str, DetectedImportedHand],
    revisions: list[CanonicalHandRevision],
) -> str | None:
    preserved_revision = conflict.active_canonical_revision_at_creation
    if preserved_revision is None:
        return None
    if (
        not isinstance(preserved_revision, int)
        or isinstance(preserved_revision, bool)
        or preserved_revision < 1
        or preserved_revision > len(revisions)
    ):
        raise ValueError(
            "conflict active revision must reference a retained canonical revision"
        )
    preserved_detection_id = revisions[preserved_revision - 1].detection_id
    preserved_detection = detection_by_id.get(preserved_detection_id)
    if preserved_detection is None:
        raise ValueError(
            "conflict active revision must reference a retained canonical revision"
        )
    preserved_source_id = preserved_detection.raw_source_id
    if preserved_source_id not in conflict.raw_source_ids:
        raise ValueError("conflict active revision source must belong to the conflict")
    return preserved_source_id


def _validate_resolved_keep_active_source(
    conflict: ImportConflict,
    *,
    preserved_source_id: str | None,
) -> None:
    if conflict.status != "resolved_keep_active":
        return
    if preserved_source_id is None:
        raise ValueError(
            "resolved_keep_active conflict requires"
            " active_canonical_revision_at_creation"
        )
    if conflict.selected_raw_source_id != preserved_source_id:
        raise ValueError(
            "resolved_keep_active conflict selected source must match the"
            " preserved active revision source"
        )


def _validate_conflict_resolution_chronology(
    conflict: ImportConflict,
    *,
    raw_by_id: dict[str, RawHandHistory],
    detection_by_id: dict[str, DetectedImportedHand],
    revisions: list[CanonicalHandRevision],
    lifecycle_changed_at: datetime,
) -> None:
    if conflict.status == "unresolved":
        return
    if conflict.resolved_at is None:
        raise ValueError(
            f"resolved conflict {conflict.conflict_id} requires resolved_at"
        )
    latest_referenced_at = _latest_conflict_referenced_event_at(
        conflict,
        raw_by_id=raw_by_id,
        detection_by_id=detection_by_id,
        revisions=revisions,
    )
    if conflict.resolved_at < latest_referenced_at:
        raise ValueError(
            f"conflict {conflict.conflict_id} resolved_at cannot precede latest"
            f" referenced evidence at {latest_referenced_at.isoformat()}"
        )
    if lifecycle_changed_at < conflict.resolved_at:
        raise ValueError(
            "lifecycle changed_at cannot precede resolved conflict"
            f" {conflict.conflict_id} resolved_at"
        )


def _validate_canonical_source_lineage(
    *,
    conflicts: list[ImportConflict],
    detection_by_id: dict[str, DetectedImportedHand],
    revisions: list[CanonicalHandRevision],
    validate_active_conflicts: bool,
) -> None:
    """Bind each canonical source transition to its own conflict resolution."""

    source_ids: list[str] = []
    for revision in revisions:
        detected = detection_by_id.get(revision.detection_id)
        if detected is None:
            raise ValueError(
                "canonical source lineage must reference retained detections"
            )
        source_ids.append(detected.raw_source_id)
    if not source_ids:
        return

    source_run_start = 1
    for previous_revision, (previous_source_id, source_id) in enumerate(
        zip(source_ids[:-1], source_ids[1:], strict=True),
        start=1,
    ):
        if source_id == previous_source_id:
            continue
        destination_revision = revisions[previous_revision]
        transition_conflicts: list[ImportConflict] = []
        for conflict in conflicts:
            preserved_revision = conflict.active_canonical_revision_at_creation
            if (
                preserved_revision is None
                or preserved_revision < source_run_start
                or preserved_revision > previous_revision
            ):
                continue
            preserved_source_id = _conflict_preserved_source_id(
                conflict,
                detection_by_id=detection_by_id,
                revisions=revisions,
            )
            if (
                preserved_source_id != previous_source_id
                or not {previous_source_id, source_id}.issubset(
                    conflict.raw_source_ids
                )
            ):
                continue
            transition_conflicts.append(conflict)
        if any(
            conflict.status == "unresolved"
            for conflict in transition_conflicts
        ):
            raise ValueError(
                "an unresolved conflict cannot replace the preserved active source"
            )
        if any(
            conflict.resolved_at is None
            or conflict.resolved_at > destination_revision.approved_at
            for conflict in transition_conflicts
        ):
            raise ValueError(
                "an applicable conflict must be resolved before activating"
                " its destination canonical revision"
            )
        eligible_resolutions = [
            conflict
            for conflict in transition_conflicts
            if conflict.resolved_at is not None
        ]
        if not eligible_resolutions:
            raise ValueError(
                "activating a canonical raw-source change requires an"
                " explicitly resolved conflict selecting the new source"
            )
        transition_scopes: dict[tuple[str, ...], list[ImportConflict]] = {}
        for conflict in eligible_resolutions:
            transition_scopes.setdefault(
                tuple(sorted(conflict.raw_source_ids)),
                [],
            ).append(conflict)
        for scoped_resolutions in transition_scopes.values():
            latest_resolved_at = max(
                conflict.resolved_at for conflict in scoped_resolutions
            )
            latest_resolutions = [
                conflict
                for conflict in scoped_resolutions
                if conflict.resolved_at == latest_resolved_at
            ]
            if any(
                conflict.status != "resolved_use_source"
                or conflict.selected_raw_source_id != source_id
                for conflict in latest_resolutions
            ):
                raise ValueError(
                    "active canonical revision must use the selected conflict source"
                )
        source_run_start = previous_revision + 1

    initial_source_id = source_ids[0]
    initial_conflicts = [
        conflict
        for conflict in conflicts
        if conflict.active_canonical_revision_at_creation is None
    ]
    for conflict in initial_conflicts:
        if conflict.status == "unresolved":
            raise ValueError(
                "an unresolved conflict without a prior active revision"
                " cannot activate a canonical source"
            )
        if (
            conflict.resolved_at is None
            or conflict.resolved_at > revisions[0].approved_at
        ):
            raise ValueError(
                "a no-prior conflict must be resolved before activating"
                " the initial canonical revision"
            )
    initial_scopes: dict[tuple[str, ...], list[ImportConflict]] = {}
    for conflict in initial_conflicts:
        if initial_source_id in conflict.raw_source_ids:
            initial_scopes.setdefault(
                tuple(sorted(conflict.raw_source_ids)),
                [],
            ).append(conflict)
    for scoped_resolutions in initial_scopes.values():
        latest_resolved_at = max(
            conflict.resolved_at for conflict in scoped_resolutions
        )
        latest_resolutions = [
            conflict
            for conflict in scoped_resolutions
            if conflict.resolved_at == latest_resolved_at
        ]
        if any(
            conflict.selected_raw_source_id != initial_source_id
            for conflict in latest_resolutions
        ):
            raise ValueError(
                "active canonical revision must use the selected conflict source"
            )

    if not validate_active_conflicts:
        return

    active_source_id = source_ids[-1]
    for conflict in conflicts:
        if conflict.status != "unresolved":
            continue
        preserved_source_id = _conflict_preserved_source_id(
            conflict,
            detection_by_id=detection_by_id,
            revisions=revisions,
        )
        if preserved_source_id is None:
            raise ValueError(
                "an unresolved conflict without a prior active revision"
                " cannot activate a canonical source"
            )
        if active_source_id != preserved_source_id:
            raise ValueError(
                "an unresolved conflict cannot replace the preserved active source"
            )

    active_scopes: dict[tuple[str, ...], list[ImportConflict]] = {}
    for conflict in conflicts:
        preserved_revision = conflict.active_canonical_revision_at_creation
        if (
            preserved_revision is None
            or preserved_revision < source_run_start
            or conflict.status == "unresolved"
        ):
            continue
        active_scopes.setdefault(
            tuple(sorted(conflict.raw_source_ids)),
            [],
        ).append(conflict)
    for scoped_resolutions in active_scopes.values():
        latest_resolved_at = max(
            conflict.resolved_at for conflict in scoped_resolutions
        )
        latest_resolutions = [
            conflict
            for conflict in scoped_resolutions
            if conflict.resolved_at == latest_resolved_at
        ]
        if any(
            conflict.selected_raw_source_id != active_source_id
            for conflict in latest_resolutions
        ):
            raise ValueError(
                "active canonical revision must use the selected conflict source"
            )


def _record_conflict_resolution_is_valid(
    record: ImportedHandRecord,
) -> bool:
    raw_by_id = {raw.raw_source_id: raw for raw in record.raw_sources}
    detection_by_id = {
        detected.detection_id: detected for detected in record.detections
    }
    try:
        for expected_revision, revision in enumerate(
            record.canonical_revisions,
            start=1,
        ):
            if revision.revision != expected_revision:
                return False
            detected = detection_by_id.get(revision.detection_id)
            if (
                detected is None
                or detected.raw_source_id not in raw_by_id
                or revision.state.chronology.source_file_id
                != detected.raw_source_id
            ):
                return False
        for conflict in record.conflicts:
            preserved_source_id = _conflict_preserved_source_id(
                conflict,
                detection_by_id=detection_by_id,
                revisions=record.canonical_revisions,
            )
            _validate_resolved_keep_active_source(
                conflict,
                preserved_source_id=preserved_source_id,
            )
            _validate_conflict_resolution_chronology(
                conflict,
                raw_by_id=raw_by_id,
                detection_by_id=detection_by_id,
                revisions=record.canonical_revisions,
                lifecycle_changed_at=record.lifecycle.changed_at,
            )
        active = record.lifecycle.active_canonical_revision
        if active is not None:
            if (
                not isinstance(active, int)
                or isinstance(active, bool)
                or active < 1
                or active > len(record.canonical_revisions)
                or active != len(record.canonical_revisions)
            ):
                return False
            active_revision = record.canonical_revisions[active - 1]
            active_detection = detection_by_id.get(active_revision.detection_id)
            if active_detection is None:
                return False
        _validate_canonical_source_lineage(
            conflicts=record.conflicts,
            detection_by_id=detection_by_id,
            revisions=record.canonical_revisions,
            validate_active_conflicts=active is not None,
        )
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return False
    return True


def _latest_retained_audit_event(
    record: ImportedHandRecord,
) -> tuple[datetime, str] | None:
    events = [
        (
            raw.provenance.imported_at,
            f"raw source {raw.raw_source_id} imported_at",
        )
        for raw in record.raw_sources
    ]
    events.extend(
        (
            detected.detected_at,
            f"detection {detected.detection_id} detected_at",
        )
        for detected in record.detections
    )
    events.extend(
        (
            revision.approved_at,
            f"canonical revision {revision.revision} approved_at",
        )
        for revision in record.canonical_revisions
    )
    events.extend(
        (
            conflict.resolved_at,
            f"conflict {conflict.conflict_id} resolved_at",
        )
        for conflict in record.conflicts
        if conflict.resolved_at is not None
    )
    return max(events, key=lambda event: event[0]) if events else None


def _record_lifecycle_audit_chronology_is_valid(
    record: ImportedHandRecord,
) -> bool:
    latest_event = _latest_retained_audit_event(record)
    if record.lifecycle.status == "deletion_pending":
        deletion_request = record.lifecycle.deletion_request
        return (
            deletion_request is not None
            and record.lifecycle.changed_at >= deletion_request.requested_at
            and (
                latest_event is None
                or deletion_request.requested_at >= latest_event[0]
            )
        )
    if record.lifecycle.status in {
        "active",
        "pending_review",
        "withdrawn",
        "rejected",
    }:
        return (
            latest_event is None
            or record.lifecycle.changed_at >= latest_event[0]
        )
    return True


def imported_hand_state_sha256(state: ImportedHandState) -> str:
    """Return the canonical checksum used to identify detected-state content."""

    payload = json.dumps(
        _state_payload_for_hash(state),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _detected_state_semantic_sha256(state: ImportedHandState) -> str:
    """Hash detected poker meaning without source-file location evidence."""

    normalized = _without_source_evidence(_state_payload_for_hash(state))
    if state.game.blinds.ante == 0:
        normalized["game"]["blinds"].pop("ante_mode", None)
    chronology = normalized["chronology"]
    for field_name in ("source_file_id", "source_session_id", "hand_ordinal"):
        chronology.pop(field_name, None)
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _state_payload_for_hash(state: ImportedHandState) -> dict[str, Any]:
    """Keep legacy no-ante/per-player hashes stable while binding uncertainty."""

    payload = state.model_dump(mode="json")
    blinds = payload["game"]["blinds"]
    ante_mode = state.game.blinds.ante_mode
    ante = state.game.blinds.ante
    if ante_mode == "per_player" or (
        ante_mode == "unknown" and (ante is None or ante == 0)
    ):
        blinds.pop("ante_mode")
    return payload


def derive_structural_positions(
    seats: list[ImportedSeat],
    button_seat: int,
) -> dict[int, StructuralPosition]:
    """Derive positions from only the dealt-in clockwise ring.

    Seat numbers are treated as their clockwise table order. A sitting-out seat
    is skipped and therefore never changes another player's position.
    """

    _validate_unique(seats, "seat_number", "seat number")
    button = next((seat for seat in seats if seat.seat_number == button_seat), None)
    if button is None:
        raise ValueError("button_seat must identify a known seat")
    if button.participation != "dealt_in":
        raise ValueError("dead-button position derivation is unresolved")
    dealt = sorted(
        (seat for seat in seats if seat.participation == "dealt_in"),
        key=lambda seat: seat.seat_number,
    )
    count = len(dealt)
    if count < 2 or count > 10:
        raise ValueError("position derivation requires two to ten dealt-in seats")

    button_index = next(
        index for index, seat in enumerate(dealt) if seat.seat_number == button_seat
    )
    ring = dealt[button_index:] + dealt[:button_index]
    labels = structural_position_labels(count)
    return {
        seat.seat_number: StructuralPosition(
            dealt_in_player_count=count,
            action_index=_structural_action_index(count, distance),
            button_distance=distance,
            display_label=labels[distance],
        )
        for distance, seat in enumerate(ring)
    }


def _known_structural_positions(
    seats: list[ImportedSeat],
    button_seat: int | None,
) -> dict[int, StructuralPosition] | None:
    """Validate positions and resolve an exact dealt-in ring when possible."""

    dealt = [seat for seat in seats if seat.participation == "dealt_in"]
    positioned = [seat.position for seat in dealt if seat.position is not None]
    if positioned:
        if any(
            position.dealt_in_player_count != len(dealt)
            for position in positioned
        ):
            raise ValueError(
                "position dealt_in_player_count must match the actual dealt-in ring"
            )
        for attribute in ("button_distance", "action_index", "display_label"):
            values = [getattr(position, attribute) for position in positioned]
            if len(values) != len(set(values)):
                raise ValueError(
                    "supplied structural positions must have unique button"
                    " distances, action indexes, and display labels"
                )

    if (
        len(dealt) < 2
        or any(seat.participation == "unknown" for seat in seats)
    ):
        return None

    resolved_button_seat = button_seat
    if resolved_button_seat is not None:
        button = next(
            (seat for seat in dealt if seat.seat_number == resolved_button_seat),
            None,
        )
        if button is None:
            return None
    else:
        if len(positioned) != len(dealt):
            return None
        inferred_buttons = [
            seat
            for seat in dealt
            if seat.position is not None and seat.position.button_distance == 0
        ]
        if len(inferred_buttons) != 1:
            return None
        resolved_button_seat = inferred_buttons[0].seat_number

    derived = derive_structural_positions(seats, resolved_button_seat)
    for seat in dealt:
        if (
            seat.position is not None
            and seat.position != derived[seat.seat_number]
        ):
            raise ValueError(
                f"seat {seat.seat_number} structural position does not match"
                " the dealt-in ring"
            )
    return derived


def _known_action_orders(
    seats: list[ImportedSeat],
    button_seat: int | None,
) -> tuple[list[str], list[str]] | None:
    """Return exact clockwise and initial preflop orders when the ring is known."""

    derived = _known_structural_positions(seats, button_seat)
    if derived is None:
        return None
    dealt = [seat for seat in seats if seat.participation == "dealt_in"]
    clockwise = [
        seat.player_id
        for seat in sorted(
            dealt,
            key=lambda seat: derived[seat.seat_number].button_distance,
        )
    ]
    preflop = [
        seat.player_id
        for seat in sorted(
            dealt,
            key=lambda seat: derived[seat.seat_number].action_index,
        )
    ]
    return clockwise, preflop


def _next_clockwise_player(
    clockwise_order: list[str],
    after_player: str,
    candidates: set[str],
) -> str | None:
    """Return the next candidate clockwise after a known ring member."""

    start = clockwise_order.index(after_player)
    for offset in range(1, len(clockwise_order) + 1):
        player_id = clockwise_order[(start + offset) % len(clockwise_order)]
        if player_id in candidates:
            return player_id
    return None


def structural_position_labels(count: int) -> list[str]:
    """Return the table-size-specific label at each button distance."""

    if count < 2 or count > 10:
        raise ValueError("position labels require two to ten dealt-in seats")
    early: dict[int, list[str]] = {
        3: [],
        4: ["UTG"],
        5: ["HJ", "CO"],
        6: ["UTG", "HJ", "CO"],
        7: ["UTG", "UTG+1/LJ", "HJ", "CO"],
        8: ["UTG", "UTG+1", "LJ", "HJ", "CO"],
        9: ["UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO"],
        10: ["UTG", "UTG+1", "UTG+2", "UTG+3", "LJ", "HJ", "CO"],
    }
    if count == 2:
        return ["BTN/SB", "BB"]
    return ["BTN", "SB", "BB", *early[count]]


def _structural_action_index(count: int, button_distance: int) -> int:
    if count == 2:
        return button_distance
    return (button_distance - 3) % count


def _known_action_total(
    action: ImportedAction,
    prior: Decimal | None,
) -> Decimal | None:
    if action.action_type in {"fold", "check"}:
        if prior is None:
            return action.total_committed
        if (
            action.total_committed is not None
            and action.total_committed != prior
        ):
            raise ValueError(
                f"{action.action_type} total_committed"
                f" {action.total_committed} conflicts with prior commitment {prior}"
            )
        return prior
    if action.action_type == "uncalled_return" and prior is not None:
        if action.amount is not None and action.amount > prior:
            raise ValueError(
                f"uncalled_return amount {action.amount} exceeds prior total"
                f" commitment {prior}"
            )
        if (
            action.total_committed is not None
            and action.total_committed > prior
        ):
            raise ValueError(
                "uncalled_return total_committed"
                f" {action.total_committed} cannot exceed prior total"
                f" commitment {prior}"
            )
    if (
        prior is not None
        and action.amount is not None
        and action.total_committed is not None
    ):
        expected_total = (
            prior - action.amount
            if action.action_type == "uncalled_return"
            else prior + action.amount
        )
        if action.total_committed != expected_total:
            raise ValueError(
                f"{action.action_type} amount {action.amount} and total_committed"
                f" {action.total_committed} conflict with prior commitment {prior}"
            )
    if action.total_committed is not None:
        return action.total_committed
    if action.amount is None or prior is None:
        return None
    if action.action_type == "uncalled_return":
        return prior - action.amount
    return prior + action.amount


def _action_street_commitment_lower_bound(
    action: ImportedAction,
    prior: Decimal,
) -> Decimal:
    """Preserve provable commitment even when an exact prior is unknown."""

    if action.action_type == "uncalled_return":
        if action.amount is None:
            return (
                action.total_committed
                if action.total_committed is not None
                else Decimal(0)
            )
        amount_bound = max(prior - action.amount, Decimal(0))
        if action.total_committed is not None:
            if action.total_committed < amount_bound:
                raise ValueError(
                    f"{action.action_type} total_committed"
                    f" {action.total_committed} is below provable street"
                    f" commitment lower bound {amount_bound}"
                )
            return action.total_committed
        return amount_bound

    amount_bound = prior
    if action.action_type in _CHIP_ACTIONS and action.amount is not None:
        amount_bound += action.amount
    if action.total_committed is None:
        return amount_bound
    if action.total_committed < amount_bound:
        raise ValueError(
            f"{action.action_type} total_committed {action.total_committed}"
            f" is below provable street commitment lower bound {amount_bound}"
        )
    return action.total_committed


def _action_street_unresolved_positive_evidence(
    action: ImportedAction,
    *,
    prior_lower_bound: Decimal,
    resolved_lower_bound: Decimal,
    prior_minimum_dead: Decimal,
    prior_minimum_live: Decimal,
    prior_positive_dead: bool,
    prior_positive_live: bool,
    configured_post_minimum: Decimal,
    configured_post_strict_positive: bool,
) -> tuple[Decimal, Decimal, Decimal, bool, bool]:
    """Track quantified and strict-positive unresolved contribution evidence."""

    if action.action_type == "uncalled_return":
        prior_combined_minimum = sum(
            (
                prior_lower_bound,
                prior_minimum_dead,
                prior_minimum_live,
            ),
            Decimal(0),
        )
        if action.amount is None:
            required_total = prior_minimum_dead
        else:
            required_total = max(
                prior_minimum_dead,
                prior_combined_minimum - action.amount,
            )
        if action.total_committed is not None:
            if action.total_committed < required_total or (
                prior_positive_dead
                and action.total_committed <= required_total
            ):
                raise ValueError(
                    "uncalled_return total_committed"
                    f" {action.total_committed} cannot account for a configured"
                    " positive ante above required post-return commitment"
                    f" {required_total}"
                )
            return action.total_committed, Decimal(0), Decimal(0), False, False
        # A return can consume an unresolved live forced post. It cannot return
        # a dead ante, so preserve that evidence outside the numeric lower bound.
        return (
            required_total - prior_minimum_dead,
            prior_minimum_dead,
            Decimal(0),
            prior_positive_dead,
            False,
        )

    unresolved_minimum_dead = prior_minimum_dead
    unresolved_minimum_live = prior_minimum_live
    unresolved_positive_dead = prior_positive_dead
    unresolved_positive_live = prior_positive_live
    if action.action_type in {"bet", "call", "raise"} and action.amount is None:
        unresolved_positive_live = True
    elif configured_post_minimum > 0:
        if action.action_type == "post_ante":
            unresolved_minimum_dead += configured_post_minimum
        else:
            unresolved_minimum_live += configured_post_minimum
    if configured_post_strict_positive:
        if action.action_type == "post_ante":
            unresolved_positive_dead = True
        else:
            unresolved_positive_live = True

    if action.total_committed is None:
        return (
            resolved_lower_bound,
            unresolved_minimum_dead,
            unresolved_minimum_live,
            unresolved_positive_dead,
            unresolved_positive_live,
        )

    amount_bound = prior_lower_bound
    if action.action_type in _CHIP_ACTIONS and action.amount is not None:
        amount_bound += action.amount
    required_total = sum(
        (
            amount_bound,
            unresolved_minimum_dead,
            unresolved_minimum_live,
        ),
        Decimal(0),
    )
    has_strict_positive = unresolved_positive_dead or unresolved_positive_live
    if action.total_committed < required_total or (
        has_strict_positive and action.total_committed <= required_total
    ):
        raise ValueError(
            f"{action.action_type} total_committed {action.total_committed}"
            " cannot account for unresolved contributions requiring"
            f" commitment above {required_total}"
        )
    return action.total_committed, Decimal(0), Decimal(0), False, False


def _known_live_action_total(
    action: ImportedAction,
    prior_commitment: Decimal | None,
    resolved_commitment: Decimal | None,
    prior_live_commitment: Decimal | None,
) -> Decimal | None:
    """Resolve chips that count toward the live wager, excluding dead antes."""

    if prior_live_commitment is None:
        return None
    if (
        action.action_type == "uncalled_return"
        and action.amount is not None
        and action.amount > prior_live_commitment
    ):
        raise ValueError(
            f"uncalled_return amount {action.amount} exceeds prior live"
            f" commitment {prior_live_commitment}"
        )
    if action.action_type in {"fold", "check", "post_ante"}:
        return prior_live_commitment
    if prior_commitment is not None and resolved_commitment is not None:
        resolved_live_commitment = (
            prior_live_commitment + resolved_commitment - prior_commitment
        )
        if (
            action.action_type == "uncalled_return"
            and resolved_live_commitment < 0
        ):
            raise ValueError(
                "uncalled_return cannot reduce prior live commitment below zero"
            )
        if (
            action.action_type == "uncalled_return"
            and resolved_live_commitment > prior_live_commitment
        ):
            raise ValueError(
                "uncalled_return cannot increase prior live commitment"
            )
        return resolved_live_commitment
    if action.amount is None:
        return None
    if action.action_type == "uncalled_return":
        return prior_live_commitment - action.amount
    return prior_live_commitment + action.amount


def _resolved_action_amount(
    action: ImportedAction,
    *,
    prior_commitment: Decimal | None,
    resolved_commitment: Decimal | None,
) -> Decimal | None:
    """Return the chips this action moved, from the walk's own resolution.

    A stated amount is authoritative -- ``_known_action_total`` has already
    rejected one that contradicts the commitment stream. Otherwise the movement
    is the difference the walk resolved, which is zero for an action that only
    matches what the actor already had in.
    """

    if action.amount is not None:
        return action.amount
    if prior_commitment is None or resolved_commitment is None:
        return None
    moved = (
        prior_commitment - resolved_commitment
        if action.action_type == "uncalled_return"
        else resolved_commitment - prior_commitment
    )
    return moved if moved > 0 else None


def _stack_is_exhausted(
    starting_stack: Decimal | None,
    cumulative_commitment: Decimal | None,
) -> bool:
    """Report a known commitment that leaves its actor with no chips behind."""

    return (
        starting_stack is not None
        and cumulative_commitment is not None
        and cumulative_commitment == starting_stack
    )


def _configured_forced_post_amount(
    action: ImportedAction,
    blinds: BlindStructure,
) -> Decimal | None:
    """Return the chips this forced post was configured to add, if any."""

    field_name = _FORCED_POST_FIELDS.get(action.action_type)
    if field_name is None:
        return None
    configured: Decimal | None = getattr(blinds, field_name)
    return configured


def _posted_forced_amount(
    action: ImportedAction,
    *,
    prior_commitment: Decimal | None,
    resolved_commitment: Decimal | None,
) -> Decimal | None:
    """Recover a forced post's chips from its amount or its commitment delta."""

    if action.action_type not in _FORCED_POST_FIELDS:
        return None
    if action.amount is not None:
        return action.amount
    if prior_commitment is None or resolved_commitment is None:
        return None
    return resolved_commitment - prior_commitment


def _wager_increments(
    action: ImportedAction,
    *,
    current_wager: Decimal | None,
    actor_live_commitment: Decimal | None,
    resolved_live_commitment: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    """Return the bet and raise increments this action adds to the live wager."""

    if current_wager is None or resolved_live_commitment is None:
        return None, None
    if action.action_type == "bet":
        if actor_live_commitment is not None:
            return resolved_live_commitment - actor_live_commitment, None
        if action.amount is not None:
            return action.amount, None
        return None, None
    if action.action_type == "raise":
        return None, resolved_live_commitment - current_wager
    return None, None


def _updated_full_wager_increment(
    action: ImportedAction,
    *,
    last_full_wager_increment: Decimal | None,
    blinds: BlindStructure,
    posted_amount: Decimal | None,
    bet_increment: Decimal | None,
    raise_increment: Decimal | None,
    confirmed_all_in: bool,
) -> Decimal | None:
    """Advance the yardstick a minimum legal raise is measured against.

    ``None`` means the increment is no longer established -- a short all-in or
    an unresolved wager has erased it -- and callers must never read that as
    zero.
    """

    if action.action_type in {"post_big_blind", "post_straddle"}:
        configured_post_amount = _configured_forced_post_amount(action, blinds)
        full_live_post = posted_amount is not None and (
            (
                configured_post_amount is not None
                and posted_amount >= configured_post_amount
            )
            or (configured_post_amount is None and not confirmed_all_in)
        )
        if full_live_post and posted_amount is not None:
            if (
                last_full_wager_increment is None
                or posted_amount > last_full_wager_increment
            ):
                return posted_amount
            return last_full_wager_increment
        if action.action_type == "post_straddle" and posted_amount is None:
            return None
        return last_full_wager_increment
    if action.action_type == "bet":
        increment = bet_increment
    elif action.action_type == "raise":
        increment = raise_increment
    else:
        return last_full_wager_increment
    if increment is None:
        return None
    if (last_full_wager_increment is None and not confirmed_all_in) or (
        last_full_wager_increment is not None
        and increment >= last_full_wager_increment
    ):
        return increment
    return last_full_wager_increment


def _raise_is_reopened(
    player_id: str,
    *,
    enforce_full_raise_increment: bool,
    current_wager: Decimal | None,
    acted_wager_by_player: dict[str, Decimal | None],
    reopen_increment_by_player: dict[str, Decimal | None],
) -> bool:
    """Report whether raising is still legal for one actor at this wager.

    A player who has already acted is reopened only once the wager has grown by
    at least the full increment that stood when they acted; a short all-in that
    does not clear that bar leaves them with call-or-fold only.
    """

    if not enforce_full_raise_increment:
        return True
    if player_id not in acted_wager_by_player:
        return True
    acted_wager = acted_wager_by_player[player_id]
    reopen_increment = reopen_increment_by_player.get(player_id)
    if acted_wager is None or reopen_increment is None or current_wager is None:
        return True
    return current_wager - acted_wager >= reopen_increment


def _economics_ready_for_extraction(
    economics: Economics,
    *,
    dealt_in_starting_stacks: dict[str, Decimal | None],
) -> bool:
    """Require the exact route-critical strategy economics without defaults."""

    if isinstance(economics, UnknownEconomics):
        return False
    if isinstance(economics, CashEconomics):
        return (
            economics.currency is not None
            and economics.rake is not None
            and all(
                getattr(economics.rake, field_name) is not None
                for field_name in ("percentage", "cap", "fixed_drop")
            )
        )
    if not economics.icm_inputs_complete:
        return False
    required_route_context = (
        economics.tournament_type,
        economics.stage,
        economics.currency,
        economics.paid_places,
        economics.players_remaining,
        economics.bounty_format,
        economics.payouts,
        economics.remaining_stacks,
        economics.bounties,
    )
    if any(value is None or value == [] for value in required_route_context):
        return False
    if any(
        stack.stack is None or stack.stack <= 0
        for stack in economics.remaining_stacks
    ):
        return False
    remaining_stack_by_player = {
        stack.player_id: stack.stack for stack in economics.remaining_stacks
    }
    dealt_in_player_ids = set(dealt_in_starting_stacks)
    if not dealt_in_player_ids.issubset(
        remaining_stack_by_player
    ):
        return False
    if any(
        starting_stack is not None
        and remaining_stack_by_player[player_id] != starting_stack
        for player_id, starting_stack in dealt_in_starting_stacks.items()
    ):
        return False
    if any(bounty.value is None for bounty in economics.bounties):
        return False
    if not dealt_in_player_ids.issubset(
        {bounty.player_id for bounty in economics.bounties}
    ):
        return False
    if economics.bounty_format == "none" and any(
        bounty.value != 0 for bounty in economics.bounties
    ):
        return False
    return True


def _terminal_hand_ready_for_extraction(state: ImportedHandState) -> bool:
    """Reuse definitive result-boundary validation without requiring results."""

    terminal_payload = state.model_dump(mode="python")
    if state.results is None:
        terminal_payload["results"] = {}
    try:
        ImportedHandState.model_validate(terminal_payload)
    except ValidationError:
        return False
    return True


def _pot_reconciliation_ready_for_extraction(
    state: ImportedHandState,
    *,
    detection: DetectedImportedHand,
    revision: CanonicalHandRevision,
) -> bool:
    """Require an independent source total to match the derived pot exactly."""

    stated_pot = state.results.stated_pot if state.results is not None else None
    if stated_pot is None or not (
        stated_pot.gross_total is not None
        or bool(stated_pot.gross_pots)
        or (
            stated_pot.net_total is not None
            and stated_pot.rake is not None
        )
    ):
        return False
    if not _stated_pot_comparator_has_provenance(
        stated_pot,
        detection=detection,
        revision=revision,
    ):
        return False

    # pot imports these model contracts, so keep the reverse dependency local.
    from app.domain.imported_hands.pot import reconcile_pot

    reconciliation = reconcile_pot(state)
    return (
        reconciliation.status == "pass"
        and reconciliation.discrepancy == 0
    )


def _stated_pot_comparator_has_provenance(
    stated_pot: StatedPotSummary,
    *,
    detection: DetectedImportedHand,
    revision: CanonicalHandRevision,
) -> bool:
    """Require one complete independent comparator route for extraction."""

    comparator_routes: list[list[str]] = []
    if stated_pot.gross_total is not None:
        comparator_routes.append(["/results/stated_pot/gross_total"])
    if stated_pot.gross_pots:
        comparator_routes.append(
            [
                f"/results/stated_pot/gross_pots/{index}"
                for index in range(len(stated_pot.gross_pots))
            ]
        )
    if stated_pot.net_total is not None and stated_pot.rake is not None:
        comparator_routes.append(
            [
                "/results/stated_pot/net_total",
                "/results/stated_pot/rake",
            ]
        )
    if not comparator_routes:
        return False

    detected_document = json.loads(detection.state.model_dump_json())
    approved_document = json.loads(revision.state.model_dump_json())
    return any(
        all(
            _stated_pot_field_has_provenance(
                pointer,
                detection=detection,
                revision=revision,
                detected_document=detected_document,
                approved_document=approved_document,
            )
            for pointer in route
        )
        for route in comparator_routes
    )


def _stated_pot_field_has_provenance(
    pointer: str,
    *,
    detection: DetectedImportedHand,
    revision: CanonicalHandRevision,
    detected_document: JsonValue,
    approved_document: JsonValue,
) -> bool:
    """Verify one comparator leaf against raw evidence or a real correction."""

    pointer_tokens = _pointer_tokens(pointer)
    approved_value = _pointer_get(approved_document, pointer)
    try:
        detected_value = _pointer_get(detected_document, pointer)
    except ValueError:
        detected_value_matches = False
    else:
        detected_value_matches = _stated_pot_values_equal(
            detected_value,
            approved_value,
        )

    if detected_value_matches:
        stated_pot_tokens = ["results", "stated_pot"]
        for evidence_pointer, field in detection.field_evidence.items():
            if not field.evidence:
                continue
            evidence_tokens = _pointer_tokens(evidence_pointer)
            if (
                evidence_tokens[: len(stated_pot_tokens)] == stated_pot_tokens
                and pointer_tokens[: len(evidence_tokens)] == evidence_tokens
            ):
                return True
        return False

    return any(
        pointer_tokens[: len(correction_tokens)] == correction_tokens
        for correction in revision.corrections
        if (
            correction_tokens := _pointer_tokens(correction.field_pointer)
        )
    )


def _stated_pot_values_equal(left: JsonValue, right: JsonValue) -> bool:
    """Compare normalized pot amounts without treating decimal scale as a change."""

    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError):
        return False


def _cash_rake_consistent_for_extraction(state: ImportedHandState) -> bool:
    """Reject stated cash rake the approved schedule cannot prove exactly."""

    economics = state.game.economics
    if not isinstance(economics, CashEconomics):
        return True
    stated_pot = state.results.stated_pot if state.results is not None else None
    if stated_pot is None:
        return True
    stated_rake = stated_pot.rake
    if stated_rake is None:
        stated_gross = stated_pot.gross_total
        if stated_gross is None and stated_pot.gross_pots:
            stated_gross = sum(stated_pot.gross_pots, Decimal(0))
        if stated_gross is None or stated_pot.net_total is None:
            return True
        stated_rake = stated_gross - stated_pot.net_total
        if stated_rake == 0:
            return True
    schedule = economics.rake
    if schedule is None:
        return False
    components = (
        schedule.percentage,
        schedule.cap,
        schedule.fixed_drop,
    )
    if any(component is None for component in components):
        return False
    if any(component != 0 for component in components):
        # The current contract does not declare the percentage basis, cap/drop
        # ordering, applicability, or rounding policy needed to derive a
        # nonzero schedule's exact per-hand rake.
        return False
    return stated_rake == 0


def _blind_structure_ready_for_extraction(blinds: BlindStructure) -> bool:
    """Require exact blinds and an explicitly resolved ante context."""

    small_blind = blinds.small_blind
    big_blind = blinds.big_blind
    ante = blinds.ante
    return (
        small_blind is not None
        and big_blind is not None
        and ante is not None
        and small_blind > 0
        and big_blind > 0
        and ante >= 0
        and (
            ante == 0
            or blinds.ante_mode in {"per_player", "big_blind"}
        )
        and small_blind <= big_blind
    )


def _hero_decision_contexts_for_extraction(
    state: ImportedHandState,
) -> list[HeroActionContext]:
    """Return hero decisions with complete cards and reconstructable chip state.

    The walk already resolves every chip value a decision point needs, so it
    emits that context rather than discarding it; no caller re-derives the pot,
    the wager, or a seat's committed chips from the action stream a second time.
    """

    assert state.hero_player_id is not None
    positions = _known_structural_positions(state.seats, state.button_seat)
    # Unreachable through the aggregate property: its gate already rejects a
    # state whose `_known_action_orders` -- derived from these positions -- is
    # unresolved. Retained so the function stands on its own.
    if positions is None:
        return []
    ring = sorted(
        (seat for seat in state.seats if seat.participation == "dealt_in"),
        key=lambda seat: positions[seat.seat_number].button_distance,
    )
    player_ids = {seat.player_id for seat in state.seats}
    extracted: list[HeroActionContext] = []
    committed_pot_before_street: Decimal | None = Decimal(0)
    committed_hand_commitments: dict[str, Decimal] = {
        player_id: Decimal(0) for player_id in player_ids
    }
    terminal_actors: dict[str, tuple[Literal["folded", "all_in"], StreetName]] = {}
    live_players = {
        seat.player_id
        for seat in state.seats
        if seat.participation in {"dealt_in", "unknown"}
    }
    actionable_players = set(live_players)
    inferred_stack_exhausted_players: set[str] = set()
    completed_street_slices: list[StreetActionSlice] = []
    starting_stacks = {seat.player_id: seat.starting_stack for seat in state.seats}
    enforce_full_raise_increment = state.game.betting_limit in {
        "no_limit",
        "pot_limit",
    }
    live_player_count = sum(
        seat.participation in {"dealt_in", "unknown"} for seat in state.seats
    )

    for street in state.streets:
        required_board_cards = {
            "preflop": 0,
            "flop": 3,
            "turn": 4,
            "river": 5,
        }[street.street]
        cards_are_ready = (
            len(state.hero_cards) == 2
            and len(street.board_cards) == required_board_cards
        )
        street_commitments: dict[str, Decimal | None] = {
            player_id: Decimal(0) for player_id in player_ids
        }
        live_commitments: dict[str, Decimal | None] = {
            player_id: Decimal(0) for player_id in player_ids
        }
        current_wager: Decimal | None = Decimal(0)
        last_full_wager_increment: Decimal | None = state.game.blinds.big_blind
        increment_is_established = True
        acted_wager_by_player: dict[str, Decimal | None] = {}
        reopen_increment_by_player: dict[str, Decimal | None] = {}
        street_resolved_actions: list[ResolvedAction] = []

        for action in street.actions:
            prior_commitment = street_commitments[action.actor_id]
            prior_live_commitment = live_commitments[action.actor_id]
            effective_prior_commitment = _action_implied_prior_commitment(
                action,
                prior_commitment=prior_commitment,
                prior_live_commitment=prior_live_commitment,
                current_wager=current_wager,
            )
            exact_commitment_context = all(
                (
                    effective_prior_commitment
                    if player_id == action.actor_id
                    else commitment
                )
                is not None
                for player_id, commitment in street_commitments.items()
            )
            exact_live_context = all(
                commitment is not None
                for commitment in live_commitments.values()
            )
            selected_chip_action_is_resolved = not (
                action.action_type in {"bet", "raise"}
                and action.amount is None
                and action.total_committed is None
            ) and not (
                action.action_type == "call"
                and action.all_in
                and action.amount is None
                and action.total_committed is None
            )
            resolved_commitment = _known_action_total(
                action,
                effective_prior_commitment,
            )
            resolved_live_commitment = _known_live_action_total(
                action,
                effective_prior_commitment,
                resolved_commitment,
                prior_live_commitment,
            )
            if (
                action.action_type == "call"
                and not action.all_in
                and current_wager is not None
                and prior_live_commitment is not None
                and effective_prior_commitment is not None
            ):
                call_amount = current_wager - prior_live_commitment
                if call_amount >= 0:
                    if resolved_commitment is None:
                        resolved_commitment = (
                            effective_prior_commitment + call_amount
                        )
                    if resolved_live_commitment is None:
                        resolved_live_commitment = current_wager

            actor_starting_stack = starting_stacks[action.actor_id]
            actor_cumulative_commitment = (
                committed_hand_commitments[action.actor_id] + resolved_commitment
                if committed_pot_before_street is not None
                and resolved_commitment is not None
                else None
            )
            stack_is_exhausted = _stack_is_exhausted(
                actor_starting_stack,
                actor_cumulative_commitment,
            )
            confirmed_all_in = action.all_in and (
                actor_starting_stack is None or stack_is_exhausted
            )
            # Resolve the action once, before the emit that may publish it:
            # the hero's own decision carries it as its table action, and every
            # later decision reads the same record in the betting line.
            resolved_action = ResolvedAction(
                action=action,
                amount=_resolved_action_amount(
                    action,
                    prior_commitment=effective_prior_commitment,
                    resolved_commitment=resolved_commitment,
                ),
                total_committed=resolved_commitment,
                all_in=_action_leaves_actor_all_in(
                    action,
                    confirmed_all_in=confirmed_all_in,
                    known_stack_exhausted=stack_is_exhausted,
                ),
            )
            if (
                action.actor_id == state.hero_player_id
                and action.is_player_decision
                and cards_are_ready
                and committed_pot_before_street is not None
                and current_wager is not None
                and exact_commitment_context
                and exact_live_context
                and selected_chip_action_is_resolved
            ):
                assert effective_prior_commitment is not None
                extracted.append(
                    _hero_decision_context(
                        street=street,
                        action=action,
                        ring=ring,
                        positions=positions,
                        committed_hand_commitments=committed_hand_commitments,
                        street_commitments=street_commitments,
                        live_commitments=live_commitments,
                        actor_street_commitment=effective_prior_commitment,
                        resolved_action=resolved_action,
                        action_history=[
                            *completed_street_slices,
                            StreetActionSlice(
                                street=street.street,
                                actions=list(street_resolved_actions),
                            ),
                        ],
                        committed_pot_before_street=committed_pot_before_street,
                        current_wager=current_wager,
                        last_full_wager_increment=(
                            last_full_wager_increment
                            if increment_is_established
                            else None
                        ),
                        raise_reopened=(
                            _sole_actionable_player_with_only_all_in_opponents(
                                live_players,
                                actionable_players,
                            )
                            != action.actor_id
                            and _raise_is_reopened(
                                action.actor_id,
                                enforce_full_raise_increment=(
                                    enforce_full_raise_increment
                                ),
                                current_wager=current_wager,
                                acted_wager_by_player=acted_wager_by_player,
                                reopen_increment_by_player=(
                                    reopen_increment_by_player
                                ),
                            )
                        ),
                        terminal_actors=terminal_actors,
                    )
                )

            street_commitments[action.actor_id] = resolved_commitment
            live_commitments[action.actor_id] = resolved_live_commitment
            # The same transition the hand validator applies: a commitment that
            # exhausts a known stack is terminal even without the source's
            # all-in marker, and a later return that restores those chips makes
            # an inferred all-in actionable again.
            _apply_terminal_transition(
                action,
                street.street,
                confirmed_all_in=confirmed_all_in,
                known_stack_exhausted=stack_is_exhausted,
                terminal_actors=terminal_actors,
                live_players=live_players,
                actionable_players=actionable_players,
                inferred_stack_exhausted_players=inferred_stack_exhausted_players,
            )
            street_resolved_actions.append(resolved_action)

            posted_amount = _posted_forced_amount(
                action,
                prior_commitment=effective_prior_commitment,
                resolved_commitment=resolved_commitment,
            )
            bet_increment, raise_increment = _wager_increments(
                action,
                current_wager=current_wager,
                actor_live_commitment=prior_live_commitment,
                resolved_live_commitment=resolved_live_commitment,
            )
            last_full_wager_increment = _updated_full_wager_increment(
                action,
                last_full_wager_increment=last_full_wager_increment,
                blinds=state.game.blinds,
                posted_amount=posted_amount,
                bet_increment=bet_increment,
                raise_increment=raise_increment,
                confirmed_all_in=confirmed_all_in,
            )
            if (
                action.all_in
                and actor_starting_stack is not None
                and actor_cumulative_commitment is None
            ):
                # The validator can still confirm this all-in from a commitment
                # lower bound, which this walk does not track. Stop claiming an
                # increment rather than publish one derived from a weaker
                # verdict than the one the hand was validated against.
                increment_is_established = False

            current_wager = _advanced_current_wager(
                action,
                current_wager=current_wager,
                live_commitments=live_commitments,
                resolved_live_commitment=resolved_live_commitment,
                posted_amount=posted_amount,
                big_blind=state.game.blinds.big_blind,
                live_player_count=live_player_count,
            )
            if action.action_type in {"check", "bet", "call", "raise"}:
                acted_wager_by_player[action.actor_id] = current_wager
                reopen_increment_by_player[action.actor_id] = (
                    last_full_wager_increment if increment_is_established else None
                )

        completed_street_slices.append(
            StreetActionSlice(
                street=street.street,
                actions=list(street_resolved_actions),
            )
        )
        if committed_pot_before_street is not None and all(
            commitment is not None for commitment in street_commitments.values()
        ):
            for player_id, commitment in street_commitments.items():
                if commitment is not None:
                    committed_hand_commitments[player_id] += commitment
            committed_pot_before_street = sum(
                committed_hand_commitments.values(),
                Decimal(0),
            )
        else:
            committed_pot_before_street = None

    return extracted


def _advanced_current_wager(
    action: ImportedAction,
    *,
    current_wager: Decimal | None,
    live_commitments: dict[str, Decimal | None],
    resolved_live_commitment: Decimal | None,
    posted_amount: Decimal | None,
    big_blind: Decimal | None,
    live_player_count: int,
) -> Decimal | None:
    """Advance the outstanding wager once this action has been applied."""

    if action.action_type in {"fold", "check", "post_ante"}:
        return current_wager
    if action.action_type == "uncalled_return":
        if any(commitment is None for commitment in live_commitments.values()):
            return None
        return max(
            commitment
            for commitment in live_commitments.values()
            if commitment is not None
        )
    if action.action_type == "call":
        if (
            current_wager is None
            and resolved_live_commitment is not None
            and not action.all_in
        ):
            return resolved_live_commitment
        return current_wager
    if resolved_live_commitment is None:
        return None
    if action.action_type in {"bet", "raise"}:
        return resolved_live_commitment
    if current_wager is None:
        return None
    advanced = max(current_wager, resolved_live_commitment)
    if (
        action.action_type == "post_big_blind"
        and big_blind is not None
        and live_player_count >= 3
        and posted_amount is not None
        and 0 < posted_amount < big_blind
    ):
        return max(advanced, big_blind)
    return advanced


def _hero_decision_context(
    *,
    street: ImportedStreet,
    action: ImportedAction,
    ring: list[ImportedSeat],
    positions: dict[int, StructuralPosition],
    committed_hand_commitments: dict[str, Decimal],
    street_commitments: dict[str, Decimal | None],
    live_commitments: dict[str, Decimal | None],
    actor_street_commitment: Decimal,
    resolved_action: ResolvedAction,
    action_history: list[StreetActionSlice],
    committed_pot_before_street: Decimal,
    current_wager: Decimal,
    last_full_wager_increment: Decimal | None,
    raise_reopened: bool,
    terminal_actors: dict[str, tuple[Literal["folded", "all_in"], StreetName]],
) -> HeroActionContext:
    """Snapshot the chip state the extraction walk holds at one hero action.

    ``current_wager`` is tracked from ``live_commitments``, so the call amount
    is measured against the hero's live commitment -- the same quantity the
    walk's own call arithmetic uses. Measuring it against the ante-inclusive
    ``street_commitments`` would understate it by the hero's posted ante.
    """

    resolved_street_commitments: dict[str, Decimal] = {}
    for player_id, commitment in street_commitments.items():
        resolved = (
            actor_street_commitment
            if player_id == action.actor_id
            else commitment
        )
        assert resolved is not None
        resolved_street_commitments[player_id] = resolved
    seats: list[SeatDecisionState] = []
    for seat in ring:
        assert seat.starting_stack is not None
        street_commitment = resolved_street_commitments[seat.player_id]
        live_commitment = live_commitments[seat.player_id]
        assert live_commitment is not None
        hand_commitment = (
            committed_hand_commitments[seat.player_id] + street_commitment
        )
        terminal = terminal_actors.get(seat.player_id)
        # Defence in depth, not a guard against a stale `all_in`: the
        # extraction gate requires reconcile_pot(...).status == "pass",
        # so every commitment here is already exact and this exhaustion
        # check is redundant with the incremental membership above (0
        # divergences measured across 401 calls). It is also `or`-shaped,
        # so it can only add `all_in`, never clear one -- it would start
        # to matter only if inexact commitments were ever let through.
        status: SeatDecisionStatus = (
            "folded"
            if terminal is not None and terminal[0] == "folded"
            else "all_in"
            if (terminal is not None and terminal[0] == "all_in")
            or _stack_is_exhausted(seat.starting_stack, hand_commitment)
            else "live"
        )
        seats.append(
            SeatDecisionState(
                player_id=seat.player_id,
                position=positions[seat.seat_number],
                starting_stack=seat.starting_stack,
                stack_before_action=seat.starting_stack - hand_commitment,
                street_commitment=street_commitment,
                live_commitment=live_commitment,
                hand_commitment=hand_commitment,
                status=status,
            )
        )
    hero = next(seat for seat in seats if seat.player_id == action.actor_id)
    return HeroActionContext(
        street=street.street,
        action_sequence=action.sequence,
        action=action,
        resolved_action=resolved_action,
        board_cards=list(street.board_cards),
        action_history=action_history,
        committed_pot_before_street=committed_pot_before_street,
        pot_before_action=committed_pot_before_street
        + sum(resolved_street_commitments.values(), Decimal(0)),
        current_wager=current_wager,
        amount_to_call=max(Decimal(0), current_wager - hero.live_commitment),
        last_full_wager_increment=last_full_wager_increment,
        raise_reopened=raise_reopened,
        hero_stack_before_action=hero.stack_before_action,
        seats=seats,
    )


def _action_implied_prior_commitment(
    action: ImportedAction,
    *,
    prior_commitment: Decimal | None,
    prior_live_commitment: Decimal | None,
    current_wager: Decimal | None,
) -> Decimal | None:
    """Use dual fields or an exact call target to recover pre-action chips."""

    if prior_commitment is not None:
        return prior_commitment
    if action.action_type in {"fold", "check"}:
        return action.total_committed
    if action.amount is not None and action.total_committed is not None:
        if action.action_type == "uncalled_return":
            return action.total_committed + action.amount
        return action.total_committed - action.amount
    if (
        action.action_type == "call"
        and not action.all_in
        and action.total_committed is not None
        and prior_live_commitment is not None
        and current_wager is not None
    ):
        return action.total_committed - (
            current_wager - prior_live_commitment
        )
    return None


def _action_leaves_actor_all_in(
    action: ImportedAction,
    *,
    confirmed_all_in: bool,
    known_stack_exhausted: bool,
) -> bool:
    """Report whether this action leaves its actor with no chips to act again.

    A commitment that exhausts a known stack is terminal even when the source
    omits its all-in marker. Folding is terminal for a different reason and is
    never all-in.
    """

    return action.action_type != "fold" and (
        confirmed_all_in or known_stack_exhausted
    )


def _apply_terminal_transition(
    action: ImportedAction,
    street: StreetName,
    *,
    confirmed_all_in: bool,
    known_stack_exhausted: bool,
    terminal_actors: dict[str, tuple[Literal["folded", "all_in"], StreetName]],
    live_players: set[str],
    actionable_players: set[str],
    inferred_stack_exhausted_players: set[str],
) -> bool:
    """Advance terminal, live, and actionable membership for one action.

    An all-in inferred only from an exhausting commitment is reversible: a
    later return can restore the actor's chips and make them actionable again,
    while a marked all-in stays terminal. Returns ``True`` when such a reversal
    happened, because it reopens any hand-wide betting closure.
    """

    if action.action_type == "fold":
        terminal_actors[action.actor_id] = ("folded", street)
        inferred_stack_exhausted_players.discard(action.actor_id)
        live_players.discard(action.actor_id)
        actionable_players.discard(action.actor_id)
        return False
    if _action_leaves_actor_all_in(
        action,
        confirmed_all_in=confirmed_all_in,
        known_stack_exhausted=known_stack_exhausted,
    ):
        terminal_actors[action.actor_id] = ("all_in", street)
        if confirmed_all_in:
            inferred_stack_exhausted_players.discard(action.actor_id)
        else:
            inferred_stack_exhausted_players.add(action.actor_id)
        actionable_players.discard(action.actor_id)
        return False
    if action.actor_id in inferred_stack_exhausted_players:
        terminal_actors.pop(action.actor_id, None)
        inferred_stack_exhausted_players.discard(action.actor_id)
        actionable_players.add(action.actor_id)
        return True
    return False


def _sole_actionable_player_with_only_all_in_opponents(
    live_players: set[str],
    actionable_players: set[str],
) -> str | None:
    """Return the sole player with chips when every live opponent is all-in."""

    if len(actionable_players) != 1:
        return None
    sole_player = next(iter(actionable_players))
    if not live_players.difference({sole_player}):
        return None
    return sole_player


def _validate_unique(items: list[Any], attribute: str, label: str) -> None:
    values = [getattr(item, attribute) for item in items]
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")


def _validate_showdown_cards(hand: ImportedHandState) -> None:
    if hand.results is None or not hand.results.showdown:
        return

    known_cards = {card.code for card in hand.hero_cards}
    if hand.streets:
        known_board = max(
            (street.board_cards for street in hand.streets),
            key=len,
        )
        known_cards.update(card.code for card in known_board)

    hero_entry = next(
        (
            entry
            for entry in hand.results.showdown
            if entry.player_id == hand.hero_player_id
        ),
        None,
    )
    if hero_entry is not None and hero_entry.cards:
        hero_showdown_codes = [card.code for card in hero_entry.cards]
        if len(hero_showdown_codes) != len(set(hero_showdown_codes)):
            raise ValueError("showdown cards must be unique within one holding")
        if hand.hero_cards:
            if set(hero_showdown_codes) != {card.code for card in hand.hero_cards}:
                raise ValueError("hero showdown cards must match the stored hero holding")
        else:
            overlap = known_cards.intersection(hero_showdown_codes)
            if overlap:
                raise ValueError("showdown cards must not duplicate known board cards")
            known_cards.update(hero_showdown_codes)

    for entry in hand.results.showdown:
        if entry is hero_entry or not entry.cards:
            continue
        entry_codes = [card.code for card in entry.cards]
        if len(entry_codes) != len(set(entry_codes)):
            raise ValueError("showdown cards must be unique within one holding")
        overlap = known_cards.intersection(entry_codes)
        if overlap:
            raise ValueError("showdown holdings must not duplicate any known card")
        known_cards.update(entry_codes)


def _state_source_evidence(state: ImportedHandState) -> list[SourceEvidence]:
    evidence: list[SourceEvidence] = []
    for street in state.streets:
        for action in street.actions:
            evidence.extend(action.evidence)
            evidence.extend(action.origin.evidence)
    if state.results is not None:
        for entry in state.results.showdown:
            evidence.extend(entry.evidence)
        for award in state.results.awards:
            evidence.extend(award.evidence)
    return evidence


def _detected_source_evidence(
    detected: DetectedImportedHand,
) -> list[SourceEvidence]:
    evidence = _state_source_evidence(detected.state)
    for field in detected.field_evidence.values():
        evidence.extend(field.evidence)
    return evidence


def _validate_source_evidence_location(
    evidence: SourceEvidence,
    raw_source: RawHandHistory,
) -> None:
    source_lines = raw_source.raw_text.splitlines(keepends=True)
    source_line_count = len(source_lines)
    last_evidence_line = evidence.line_end or evidence.line_start
    if last_evidence_line is not None and last_evidence_line > source_line_count:
        raise ValueError(
            "source evidence line range exceeds retained raw source"
            f" {raw_source.raw_source_id} line count {source_line_count}"
        )
    excerpt_scope = raw_source.raw_text
    if evidence.line_start is not None:
        excerpt_scope = "".join(
            source_lines[
                evidence.line_start - 1 : evidence.line_end or evidence.line_start
            ]
        )
    if evidence.excerpt is not None and evidence.excerpt not in excerpt_scope:
        raise ValueError(
            "source evidence excerpt does not occur at its retained raw"
            " source location"
            f" {raw_source.raw_source_id}"
        )


def _without_source_evidence(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {
            key: _without_source_evidence(item)
            for key, item in value.items()
            if key != "evidence"
        }
    if isinstance(value, list):
        return [_without_source_evidence(item) for item in value]
    return value


def _validate_json_pointer(pointer: str) -> None:
    if not pointer.startswith("/") or pointer == "/":
        raise ValueError("field path must be a non-root RFC 6901 JSON pointer")
    for segment in pointer[1:].split("/"):
        index = 0
        while index < len(segment):
            if segment[index] == "~":
                if index + 1 >= len(segment) or segment[index + 1] not in {"0", "1"}:
                    raise ValueError("JSON pointer contains an invalid escape")
                index += 2
            else:
                index += 1


def _pointer_tokens(pointer: str) -> list[str]:
    _validate_json_pointer(pointer)
    return [segment.replace("~1", "/").replace("~0", "~") for segment in pointer[1:].split("/")]


def _pointer_get(document: JsonValue, pointer: str) -> JsonValue:
    current: Any = document
    for token in _pointer_tokens(pointer):
        if isinstance(current, list):
            current = current[_pointer_list_index(token, len(current), pointer)]
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise ValueError(f"correction path does not exist: {pointer}")
    return current


def _pointer_set(document: JsonValue, pointer: str, value: JsonValue) -> None:
    tokens = _pointer_tokens(pointer)
    current: Any = document
    for token in tokens[:-1]:
        if isinstance(current, list):
            current = current[_pointer_list_index(token, len(current), pointer)]
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise ValueError(f"correction path does not exist: {pointer}")
    final = tokens[-1]
    if isinstance(current, list):
        current[_pointer_list_index(final, len(current), pointer)] = value
    elif isinstance(current, dict) and final in current:
        current[final] = value
    else:
        raise ValueError(f"correction path does not exist: {pointer}")


def _pointer_list_index(token: str, length: int, pointer: str) -> int:
    canonical = token == "0" or (
        token.startswith(tuple("123456789"))
        and all("0" <= character <= "9" for character in token)
    )
    if not canonical:
        raise ValueError(
            f"correction path has a non-canonical array index: {pointer}"
        )
    index = int(token)
    if index >= length:
        raise ValueError(f"correction path does not exist: {pointer}")
    return index


def _validate_non_overlapping_correction_pointers(pointers: list[str]) -> None:
    if len(pointers) != len(set(pointers)):
        raise ValueError("one canonical revision cannot correct the same field twice")
    token_paths = [(pointer, _pointer_tokens(pointer)) for pointer in pointers]
    for index, (pointer, tokens) in enumerate(token_paths):
        for other_pointer, other_tokens in token_paths[index + 1 :]:
            shared_length = min(len(tokens), len(other_tokens))
            if tokens[:shared_length] == other_tokens[:shared_length]:
                raise ValueError(
                    "one canonical revision cannot correct overlapping fields:"
                    f" {pointer} and {other_pointer}"
                )


def _json_values_equal(left: JsonValue, right: JsonValue) -> bool:
    """Compare JSON values without Python's boolean/number coercion."""

    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        assert isinstance(right, dict)
        return left.keys() == right.keys() and all(
            _json_values_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        assert isinstance(right, list)
        return len(left) == len(right) and all(
            _json_values_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _validate_corrections_win(
    detected: DetectedImportedHand,
    revision: CanonicalHandRevision,
) -> None:
    _validate_correction_timestamps(revision)
    for correction in revision.corrections:
        if correction.corrected_at < detected.detected_at:
            raise ValueError(
                f"correction {correction.field_pointer} corrected_at cannot"
                f" precede referenced detection {detected.detection_id}"
                " detected_at"
            )
    detected_json = detected.state.model_dump_json()
    detected_document = json.loads(detected_json)
    for correction in revision.corrections:
        detected_value = _pointer_get(
            detected_document,
            correction.field_pointer,
        )
        if not _json_values_equal(detected_value, correction.detected_value):
            raise ValueError(
                f"correction detected_value does not match {correction.field_pointer}"
            )
    _validate_non_overlapping_correction_pointers(
        [correction.field_pointer for correction in revision.corrections]
    )
    _validate_user_confirmed_origin_corrections(detected, revision)
    expected = json.loads(detected_json)
    for correction in revision.corrections:
        _pointer_set(expected, correction.field_pointer, correction.approved_value)
    approved = json.loads(revision.state.model_dump_json())
    if not _json_values_equal(expected, approved):
        raise ValueError("canonical state may differ from detection only through corrections")


def _validate_detected_action_origins(state: ImportedHandState) -> None:
    """Prevent detector output from manufacturing a user confirmation."""

    for street_index, street in enumerate(state.streets):
        for action_index, action in enumerate(street.actions):
            if action.origin.basis == "user_confirmed":
                raise ValueError(
                    "detector-produced action origin cannot use user_confirmed"
                    " basis at"
                    f" /streets/{street_index}/actions/{action_index}/origin"
                )


def _validate_user_confirmed_origin_corrections(
    detected: DetectedImportedHand,
    revision: CanonicalHandRevision,
) -> None:
    """Require canonical user confirmation to resolve detected unknown origin."""

    _validate_user_confirmed_origin_correction_presence(revision)
    for street_index, street in enumerate(revision.state.streets):
        for action_index, action in enumerate(street.actions):
            if action.origin.basis != "user_confirmed":
                continue
            if (
                street_index >= len(detected.state.streets)
                or action_index
                >= len(detected.state.streets[street_index].actions)
            ):
                raise ValueError(
                    "user-confirmed origin must resolve a corresponding"
                    " detected action"
                )
            detected_origin = detected.state.streets[street_index].actions[
                action_index
            ].origin
            if not (
                detected_origin.kind == "unknown"
                and detected_origin.basis == "unresolved"
            ):
                raise ValueError(
                    "user-confirmed origin must resolve a detected unknown origin"
                )


def _validate_user_confirmed_origin_correction_presence(
    revision: CanonicalHandRevision,
) -> None:
    """Require every canonical user confirmation to overlap a correction."""

    correction_token_paths = [
        _pointer_tokens(correction.field_pointer)
        for correction in revision.corrections
    ]
    for street_index, street in enumerate(revision.state.streets):
        for action_index, action in enumerate(street.actions):
            if action.origin.basis != "user_confirmed":
                continue
            origin_tokens = [
                "streets",
                str(street_index),
                "actions",
                str(action_index),
                "origin",
            ]
            if not any(
                tokens[: len(origin_tokens)] == origin_tokens
                or origin_tokens[: len(tokens)] == tokens
                for tokens in correction_token_paths
            ):
                raise ValueError(
                    "user-confirmed origin requires an explicit canonical"
                    " correction"
                )


def _validate_correction_timestamps(revision: CanonicalHandRevision) -> None:
    for correction in revision.corrections:
        if correction.corrected_at > revision.approved_at:
            raise ValueError(
                f"correction {correction.field_pointer} corrected_at cannot follow"
                " approved_at"
            )
