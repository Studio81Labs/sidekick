"""Site-agnostic contracts for detected and player-approved imported hands.

These models deliberately do not reuse the V1 screenshot ``CanonicalState``.
An imported hand carries a lossless ordered action stream and has its own
revision/deletion lifecycle before it can become learning evidence.
"""

from __future__ import annotations

import json
from hashlib import sha256
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

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
    variant: Literal["texas_holdem"] = "texas_holdem"
    betting_limit: Literal["no_limit", "pot_limit", "fixed_limit", "unknown"]
    table_size: Annotated[int, Field(ge=2, le=10, strict=True)]
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
            self.action_type in {"fold", "check", "bet", "call", "raise"}
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
        fold_end: tuple[StreetName, str] | None = None
        enforce_full_raise_increment = self.game.betting_limit in {
            "no_limit",
            "pot_limit",
        }
        for street in self.streets:
            street_commitments: dict[str, Decimal | None] = {
                player_id: Decimal(0) for player_id in player_ids
            }
            live_commitments: dict[str, Decimal | None] = {
                player_id: Decimal(0) for player_id in player_ids
            }
            acted_wager_by_player: dict[str, Decimal | None] = {}
            reopen_increment_by_player: dict[str, Decimal | None] = {}
            current_wager: Decimal | None = Decimal(0)
            nominal_bring_in = Decimal(0)
            last_full_wager_increment = self.game.blinds.big_blind
            for action in street.actions:
                if action.actor_id not in player_ids:
                    raise ValueError("every action actor must identify a known seat")
                participation = next(
                    seat.participation
                    for seat in self.seats
                    if seat.player_id == action.actor_id
                )
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
                posted_amount: Decimal | None = None
                configured_post_amount: Decimal | None = None
                short_forced_post = False
                bet_increment: Decimal | None = None
                raise_increment: Decimal | None = None
                forced_post_field = _FORCED_POST_FIELDS.get(action.action_type)
                if forced_post_field is not None:
                    if street.street != "preflop":
                        raise ValueError("forced blind and ante posts must be preflop")
                    configured_post_amount = getattr(
                        self.game.blinds,
                        forced_post_field,
                    )
                    posted_amount = action.amount
                    if (
                        posted_amount is None
                        and actor_commitment is not None
                        and resolved_commitment is not None
                    ):
                        posted_amount = resolved_commitment - actor_commitment
                    if (
                        configured_post_amount is not None
                        and posted_amount is not None
                        and posted_amount != configured_post_amount
                    ):
                        starting_stack = next(
                            seat.starting_stack
                            for seat in self.seats
                            if seat.player_id == action.actor_id
                        )
                        short_stack_exhausted = (
                            Decimal(0) < posted_amount < configured_post_amount
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
                                or resolved_commitment is None
                            )
                        )
                        short_forced_post = short_stack_exhausted
                        if not short_stack_exhausted:
                            raise ValueError(
                                f"{action.action_type} amount {posted_amount} does not"
                                f" match configured {forced_post_field}"
                                f" {configured_post_amount} or a short-stack all-in"
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
                            resolved_live_commitment < current_wager and not action.all_in
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
                    if resolved_live_commitment is not None:
                        if actor_live_commitment is not None:
                            bet_increment = (
                                resolved_live_commitment - actor_live_commitment
                            )
                        elif action.amount is not None:
                            bet_increment = action.amount
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
                        and not action.all_in
                    ):
                        raise ValueError(
                            "a non-all-in bet must be at least the minimum full"
                            " wager increment"
                        )
                elif action.action_type == "raise" and current_wager is not None:
                    if current_wager == 0:
                        raise ValueError("a raise requires an outstanding wager")
                    if resolved_live_commitment is not None:
                        raise_increment = resolved_live_commitment - current_wager
                        if raise_increment <= 0:
                            raise ValueError("a raise must increase the outstanding wager")
                        acted_wager = acted_wager_by_player.get(action.actor_id)
                        reopen_increment = reopen_increment_by_player.get(
                            action.actor_id
                        )
                        if (
                            enforce_full_raise_increment
                            and action.actor_id in acted_wager_by_player
                            and acted_wager is not None
                            and reopen_increment is not None
                            and current_wager - acted_wager < reopen_increment
                        ):
                            raise ValueError(
                                "a raise is not allowed because short all-ins have not"
                                " reopened betting for this actor"
                            )
                        if (
                            enforce_full_raise_increment
                            and last_full_wager_increment is not None
                            and raise_increment < last_full_wager_increment
                            and not action.all_in
                        ):
                            raise ValueError(
                                "a non-all-in raise must be at least the last full"
                                " bet or raise increment"
                            )
                if action.action_type == "fold":
                    terminal_actors[action.actor_id] = ("folded", street.street)
                    live_players.discard(action.actor_id)
                    if len(live_players) == 1:
                        fold_end = (street.street, next(iter(live_players)))
                elif action.all_in:
                    terminal_actors[action.actor_id] = ("all_in", street.street)
                street_commitments[action.actor_id] = resolved_commitment
                live_commitments[action.actor_id] = resolved_live_commitment
                if action.action_type in {"post_big_blind", "post_straddle"}:
                    full_live_post = (
                        posted_amount is not None
                        and (
                            (
                                configured_post_amount is not None
                                and posted_amount >= configured_post_amount
                            )
                            or (
                                configured_post_amount is None
                                and not action.all_in
                            )
                        )
                    )
                    if full_live_post and posted_amount is not None:
                        if (
                            last_full_wager_increment is None
                            or posted_amount > last_full_wager_increment
                        ):
                            last_full_wager_increment = posted_amount
                    elif action.action_type == "post_straddle" and posted_amount is None:
                        last_full_wager_increment = None
                elif action.action_type == "bet":
                    if bet_increment is None:
                        last_full_wager_increment = None
                    elif (
                        last_full_wager_increment is None
                        and not action.all_in
                    ) or (
                        last_full_wager_increment is not None
                        and bet_increment >= last_full_wager_increment
                    ):
                        last_full_wager_increment = bet_increment
                elif action.action_type == "raise":
                    if raise_increment is None:
                        last_full_wager_increment = None
                    elif (
                        last_full_wager_increment is None
                        and not action.all_in
                    ) or (
                        last_full_wager_increment is not None
                        and raise_increment >= last_full_wager_increment
                    ):
                        last_full_wager_increment = raise_increment
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
                    if any(
                        commitment is None
                        for commitment in live_commitments.values()
                    ):
                        current_wager = None
                    else:
                        current_wager = max(
                            nominal_bring_in,
                            *(
                                commitment
                                for commitment in live_commitments.values()
                                if commitment is not None
                            ),
                        )
                if action.action_type in {"check", "bet", "call", "raise"}:
                    acted_wager_by_player[action.actor_id] = current_wager
                    reopen_increment_by_player[action.actor_id] = (
                        last_full_wager_increment
                    )
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

        dealt = [seat for seat in self.seats if seat.participation == "dealt_in"]
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

        if self.button_seat is not None:
            button = next(seat for seat in self.seats if seat.seat_number == self.button_seat)
            if button.participation == "dealt_in" and len(dealt) >= 2:
                expected = derive_structural_positions(self.seats, self.button_seat)
                for seat in self.seats:
                    if seat.position is not None and seat.position != expected.get(seat.seat_number):
                        raise ValueError(
                            f"seat {seat.seat_number} structural position does not match the dealt-in ring"
                        )
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
        if self.state.chronology.source_file_id != self.raw_source_id:
            raise ValueError(
                "detected state source_file_id must equal the detected raw_source_id"
            )
        if self.content_sha256 != imported_hand_state_sha256(self.state):
            raise ValueError("content_sha256 must match the normalized detected state")
        evidence_ids = _state_source_evidence_ids(self.state)
        evidence_ids.update(
            item.raw_source_id
            for field in self.field_evidence.values()
            for item in field.evidence
        )
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
    def validate_unique_corrections(self) -> Self:
        pointers = [correction.field_pointer for correction in self.corrections]
        if len(pointers) != len(set(pointers)):
            raise ValueError("one canonical revision cannot correct the same field twice")
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

        raw_ids = {raw.raw_source_id for raw in self.raw_sources}
        detection_by_id = {detected.detection_id: detected for detected in self.detections}
        for detected in self.detections:
            if detected.raw_source_id not in raw_ids:
                raise ValueError("detected hand must reference a retained raw source")
            if detected.state.identity != self.identity:
                raise ValueError("detected hand must share the stable hand identity")
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
        for revision in self.canonical_revisions:
            detected = detection_by_id.get(revision.detection_id)
            if detected is None:
                raise ValueError("canonical revision must reference a retained detection")
            if revision.state.identity != self.identity:
                raise ValueError("canonical revision must share the stable hand identity")
            if revision.state.chronology.source_file_id != detected.raw_source_id:
                raise ValueError(
                    "canonical revision source_file_id must match its detected raw source"
                )
            if not _state_source_evidence_ids(revision.state).issubset(raw_ids):
                raise ValueError(
                    "canonical source evidence must reference a retained raw source"
                )
            _validate_corrections_win(detected, revision)

        conflict_active_sources: dict[str, str] = {}
        for conflict in self.conflicts:
            preserved_revision = conflict.active_canonical_revision_at_creation
            if preserved_revision is None:
                continue
            if preserved_revision > len(self.canonical_revisions):
                raise ValueError(
                    "conflict active revision must reference a retained canonical revision"
                )
            preserved_detection_id = self.canonical_revisions[
                preserved_revision - 1
            ].detection_id
            preserved_source_id = detection_by_id[
                preserved_detection_id
            ].raw_source_id
            if preserved_source_id not in conflict.raw_source_ids:
                raise ValueError(
                    "conflict active revision source must belong to the conflict"
                )
            conflict_active_sources[conflict.conflict_id] = preserved_source_id

        active = self.lifecycle.active_canonical_revision
        if active is not None:
            if not revisions or active != revisions[-1]:
                raise ValueError("the active pointer must select the latest canonical revision")
            active_revision = self.canonical_revisions[active - 1]
            active_source_id = detection_by_id[
                active_revision.detection_id
            ].raw_source_id
            for conflict in self.conflicts:
                if conflict.status == "unresolved":
                    preserved_source_id = conflict_active_sources.get(
                        conflict.conflict_id
                    )
                    if preserved_source_id is None:
                        raise ValueError(
                            "an unresolved conflict without a prior active revision"
                            " cannot activate a canonical source"
                        )
                    if active_source_id != preserved_source_id:
                        raise ValueError(
                            "an unresolved conflict cannot replace the preserved"
                            " active source"
                        )
                elif (
                    active_source_id in conflict.raw_source_ids
                    and active_source_id != conflict.selected_raw_source_id
                ):
                    raise ValueError(
                        "active canonical revision must use the selected conflict source"
                    )

        if self.lifecycle.status in {"withdrawn", "rejected"} and not revisions:
            raise ValueError("withdrawal/rejection audit requires a canonical revision")
        return self

    @property
    def active_state_for_extraction(self) -> ImportedHandState | None:
        if not self.lifecycle.learning_eligible:
            return None
        revision = self.lifecycle.active_canonical_revision
        if revision is None:
            return None
        return self.canonical_revisions[revision - 1].state

    @property
    def active_hero_actions_for_extraction(self) -> list[ImportedAction]:
        """Return only voluntary hero actions from the active approved revision.

        Forced, client-automatic, and unresolved actions remain in the canonical
        audit stream but cannot become learning decision points.
        """

        state = self.active_state_for_extraction
        if state is None or state.hero_player_id is None:
            return []
        hero = next(
            seat for seat in state.seats if seat.player_id == state.hero_player_id
        )
        if hero.participation != "dealt_in":
            return []
        return [
            action
            for street in state.streets
            for action in street.actions
            if action.actor_id == state.hero_player_id and action.is_player_decision
        ]


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
    if candidate.lifecycle.deletion_generation > current.lifecycle.deletion_generation:
        return RestoreDisposition(kind="allow")

    current_revisions = current.canonical_revisions
    candidate_revisions = candidate.canonical_revisions
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


def imported_hand_state_sha256(state: ImportedHandState) -> str:
    """Return the canonical checksum used to identify detected-state content."""

    payload = json.dumps(
        state.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _detected_state_semantic_sha256(state: ImportedHandState) -> str:
    """Hash detected poker meaning without source-file location evidence."""

    normalized = _without_source_evidence(state.model_dump(mode="json"))
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
        9: ["UTG", "UTG+1", "UTG+2/LJ", "HJ", "CO"],
        10: ["UTG", "UTG+1", "UTG+2", "UTG+3/LJ", "HJ", "CO"],
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
        return prior if prior is not None else action.total_committed
    if action.total_committed is not None:
        return action.total_committed
    if action.amount is None or prior is None:
        return None
    if action.action_type == "uncalled_return":
        return prior - action.amount
    return prior + action.amount


def _known_live_action_total(
    action: ImportedAction,
    prior_commitment: Decimal | None,
    resolved_commitment: Decimal | None,
    prior_live_commitment: Decimal | None,
) -> Decimal | None:
    """Resolve chips that count toward the live wager, excluding dead antes."""

    if prior_live_commitment is None:
        return None
    if action.action_type in {"fold", "check", "post_ante"}:
        return prior_live_commitment
    if prior_commitment is not None and resolved_commitment is not None:
        return prior_live_commitment + resolved_commitment - prior_commitment
    if action.amount is None:
        return None
    if action.action_type == "uncalled_return":
        return prior_live_commitment - action.amount
    return prior_live_commitment + action.amount


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


def _state_source_evidence_ids(state: ImportedHandState) -> set[str]:
    evidence_ids: set[str] = set()
    for street in state.streets:
        for action in street.actions:
            evidence_ids.update(item.raw_source_id for item in action.evidence)
            evidence_ids.update(item.raw_source_id for item in action.origin.evidence)
    if state.results is not None:
        for entry in state.results.showdown:
            evidence_ids.update(item.raw_source_id for item in entry.evidence)
        for award in state.results.awards:
            evidence_ids.update(item.raw_source_id for item in award.evidence)
    return evidence_ids


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


def _validate_corrections_win(
    detected: DetectedImportedHand,
    revision: CanonicalHandRevision,
) -> None:
    expected = json.loads(detected.state.model_dump_json())
    for correction in revision.corrections:
        detected_value = _pointer_get(expected, correction.field_pointer)
        if detected_value != correction.detected_value:
            raise ValueError(
                f"correction detected_value does not match {correction.field_pointer}"
            )
        _pointer_set(expected, correction.field_pointer, correction.approved_value)
    approved = json.loads(revision.state.model_dump_json())
    if expected != approved:
        raise ValueError("canonical state may differ from detection only through corrections")
