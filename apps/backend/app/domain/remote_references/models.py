"""Immutable contracts for consented, minimized remote-reference preflight."""

from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256
from ipaddress import ip_address
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.domain.imported_hands.models import structural_position_labels
from app.domain.learning_content.models import DecisionBinding


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
Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^[a-f0-9]{64}$", strict=True),
]
PositiveInteger = Annotated[int, Field(gt=0, strict=True)]
TableSize = Annotated[int, Field(ge=2, le=10, strict=True)]
PositiveDecimal = Annotated[
    Decimal,
    Field(gt=0, allow_inf_nan=False, strict=True),
]
NonNegativeDecimal = Annotated[
    Decimal,
    Field(ge=0, allow_inf_nan=False, strict=True),
]
CardCode = Annotated[
    str,
    StringConstraints(pattern=r"^(?:[2-9TJQKA])[cdhs]$", strict=True),
]

RemoteOutboundCategory = Literal[
    "board_abstraction",
    "board_cards",
    "conditioned_ranges",
    "game_economics",
    "hole_card_abstraction",
    "hole_cards",
    "prior_actions",
    "stack_wager_pot",
    "table_position",
]
RemoteReferenceMode = Literal["local_only", "remote_enabled"]
RemoteProviderStatus = Literal["staged", "active", "disabled"]
RemoteConsentStatus = Literal["active", "revoked"]
RemoteDispatchOutcome = Literal["unavailable", "dispatch_candidate"]
RemoteDispatchReason = Literal[
    "clock_invalid",
    "mode_invalid",
    "local_only",
    "provider_unconfigured",
    "provider_inactive",
    "consent_absent",
    "consent_revoked",
    "consent_not_yet_active",
    "consent_expired",
    "provider_policy_mismatch",
    "disclosure_mismatch",
    "outbound_categories_mismatch",
    "route_unavailable",
    "route_binding_mismatch",
    "route_schema_mismatch",
    "route_manifest_mismatch",
    "preflight_passed",
]
RemoteLookupUnavailableReason = Literal[
    "provider_failure",
    "network_failure",
    "response_invalid",
    "remote_coverage_unavailable",
]
RemoteStreet = Literal["preflop", "flop", "turn", "river"]
RemoteAction = Literal["fold", "check", "call", "bet", "raise"]
PositionLabel = Literal[
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
EconomicModel = Literal[
    "cash_rake",
    "tournament_bounty_icm",
    "tournament_chip_ev",
    "tournament_icm",
]
UtilityModel = Literal[
    "bounty_adjusted_equity",
    "chip_ev",
    "currency_ev",
    "icm_equity",
]
StartingHandClass = Annotated[
    str,
    StringConstraints(
        pattern=r"^(?:[2-9TJQKA]{2}|[2-9TJQKA]{2}[so])$",
        strict=True,
    ),
]


class RemoteReferenceModel(BaseModel):
    """Strict immutable base for the sole optional player-data egress seam."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _canonical_sha256(model: BaseModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _validate_sorted_unique_categories(
    categories: tuple[RemoteOutboundCategory, ...],
) -> None:
    if categories != tuple(sorted(categories)):
        raise ValueError("outbound categories must be sorted")
    if len(categories) != len(set(categories)):
        raise ValueError("outbound categories must be unique")
    category_set = set(categories)
    if {"board_cards", "board_abstraction"} <= category_set:
        raise ValueError("board cards and board abstraction are mutually exclusive")
    if {"hole_cards", "hole_card_abstraction"} <= category_set:
        raise ValueError(
            "hole cards and hole-card abstraction are mutually exclusive"
        )


def _is_canonical_dns_label(label: str) -> bool:
    return (
        bool(label)
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(
            (character.isascii() and character.isalnum()) or character == "-"
            for character in label
        )
    )


def _validate_https_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("provider endpoint must be a valid HTTPS origin") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("provider endpoint must be an HTTPS origin only")
    if parsed.hostname.lower() != parsed.hostname or ":" in parsed.hostname:
        raise ValueError("provider endpoint host must be canonical lowercase DNS")
    try:
        ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        raise ValueError("provider endpoint must use a DNS hostname, not an IP")
    labels = parsed.hostname.split(".")
    if len(labels) < 2 or not all(_is_canonical_dns_label(label) for label in labels):
        raise ValueError("provider endpoint must use a canonical DNS hostname")
    authority = parsed.hostname
    if port is not None:
        if port == 0:
            raise ValueError("provider endpoint port must be positive")
        authority = f"{authority}:{port}"
    canonical = f"https://{authority}"
    if value != canonical:
        raise ValueError("provider endpoint must use canonical origin syntax")
    return value


HttpsOrigin = Annotated[
    str,
    StringConstraints(min_length=9, max_length=512, strict=True),
    AfterValidator(_validate_https_origin),
]


class RemoteReferenceDisclosure(RemoteReferenceModel):
    """Exact disclosure semantics that one explicit consent accepts."""

    disclosure_revision: Identifier
    terms_revision: Identifier
    terms_sha256: Sha256Digest
    privacy_policy_revision: Identifier
    privacy_policy_sha256: Sha256Digest
    retention_policy_revision: Identifier
    retention_policy_sha256: Sha256Digest
    training_use_policy_revision: Identifier
    training_use_policy_sha256: Sha256Digest
    logging_policy_revision: Identifier
    logging_policy_sha256: Sha256Digest
    route_schema_revision: Identifier
    route_schema_sha256: Sha256Digest
    outbound_categories: tuple[RemoteOutboundCategory, ...] = Field(min_length=1)
    network_dependency_disclosed: Literal[True] = True
    local_only_mode_disclosed: Literal[True] = True
    failure_behavior: Literal["remote_coverage_unavailable_ungraded"] = (
        "remote_coverage_unavailable_ungraded"
    )

    @field_validator("outbound_categories")
    @classmethod
    def validate_outbound_categories(
        cls,
        value: tuple[RemoteOutboundCategory, ...],
    ) -> tuple[RemoteOutboundCategory, ...]:
        _validate_sorted_unique_categories(value)
        return value

    def semantic_digest(self) -> str:
        return _canonical_sha256(self)


class EconomicConfigurationBinding(RemoteReferenceModel):
    economic_model: EconomicModel
    economic_model_revision: Identifier
    economic_configuration_sha256: Sha256Digest


class UtilityConfigurationBinding(RemoteReferenceModel):
    utility_model: UtilityModel
    utility_model_revision: Identifier
    utility_configuration_sha256: Sha256Digest


class AbstractionSchemaBinding(RemoteReferenceModel):
    abstraction_schema_revision: Identifier
    abstraction_schema_sha256: Sha256Digest


class RemoteReferenceRouteManifest(RemoteReferenceModel):
    """Provider-owned allowlist for every eligible route revision and digest."""

    manifest_revision: Identifier
    eligible_route_context_sha256s: tuple[Sha256Digest, ...] = Field(min_length=1)
    economic_configurations: tuple[EconomicConfigurationBinding, ...] = Field(
        min_length=1
    )
    utility_configurations: tuple[UtilityConfigurationBinding, ...] = Field(
        min_length=1
    )
    hole_card_abstraction_schemas: tuple[AbstractionSchemaBinding, ...] = ()

    @model_validator(mode="after")
    def validate_manifest_order(self) -> Self:
        model_bindings = (
            self.economic_configurations,
            self.utility_configurations,
            self.hole_card_abstraction_schemas,
        )
        for bindings in model_bindings:
            digests = [_canonical_sha256(binding) for binding in bindings]
            if digests != sorted(digests) or len(digests) != len(set(digests)):
                raise ValueError("route-manifest bindings must be sorted and unique")
        if self.eligible_route_context_sha256s != tuple(
            sorted(self.eligible_route_context_sha256s)
        ) or len(self.eligible_route_context_sha256s) != len(
            set(self.eligible_route_context_sha256s)
        ):
            raise ValueError("eligible route contexts must be sorted and unique")
        return self

    def semantic_digest(self) -> str:
        return _canonical_sha256(self)


class RemoteReferenceProviderPolicy(RemoteReferenceModel):
    """Application-supplied provider policy; not proof that a source is solved."""

    provider_id: Identifier
    provider_configuration_revision: Identifier
    provider_policy_revision: Identifier
    provider_status: RemoteProviderStatus
    endpoint_origin: HttpsOrigin
    reference_source_revision: Identifier
    commercial_serving_rights_revision: Identifier
    commercial_serving_rights_sha256: Sha256Digest
    derived_output_rights_revision: Identifier
    derived_output_rights_sha256: Sha256Digest
    disclosure: RemoteReferenceDisclosure
    route_manifest: RemoteReferenceRouteManifest
    delivery_mode: Literal["server_side_feed"] = "server_side_feed"
    transport_requirement: Literal["https"] = "https"
    credential_placement: Literal["authorization_header_only"] = (
        "authorization_header_only"
    )
    fallback_behavior: Literal["no_remote_or_heuristic_solved_fallback"] = (
        "no_remote_or_heuristic_solved_fallback"
    )

    def semantic_digest(self) -> str:
        return _canonical_sha256(self)


class RemoteReferenceConsent(RemoteReferenceModel):
    """One consent snapshot pinned for an authoritative generation recheck."""

    consent_id: Identifier
    consent_generation: PositiveInteger
    provider_id: Identifier
    provider_configuration_revision: Identifier
    provider_policy_revision: Identifier
    provider_policy_sha256: Sha256Digest
    endpoint_origin: HttpsOrigin
    disclosure_revision: Identifier
    disclosure_sha256: Sha256Digest
    accepted_outbound_categories: tuple[RemoteOutboundCategory, ...] = Field(
        min_length=1
    )
    network_dependency_accepted: Literal[True] = True
    retention_and_use_accepted: Literal[True] = True
    status: RemoteConsentStatus
    consented_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    revoked_at: AwareDatetime | None = None

    @field_validator("accepted_outbound_categories")
    @classmethod
    def validate_accepted_categories(
        cls,
        value: tuple[RemoteOutboundCategory, ...],
    ) -> tuple[RemoteOutboundCategory, ...]:
        _validate_sorted_unique_categories(value)
        return value

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.expires_at is not None and self.expires_at <= self.consented_at:
            raise ValueError("consent expiry must be after consent time")
        if self.status == "active" and self.revoked_at is not None:
            raise ValueError("active consent cannot carry a revocation time")
        if self.status == "revoked":
            if self.revoked_at is None:
                raise ValueError("revoked consent requires a revocation time")
            if self.revoked_at < self.consented_at:
                raise ValueError("consent revocation cannot predate consent")
        return self


class GameEconomicsRoute(RemoteReferenceModel):
    category: Literal["game_economics"] = "game_economics"
    game_variant: Literal["texas_holdem"]
    betting_limit: Literal["no_limit"]
    game_format: Literal["cash", "tournament"]
    economic_model: EconomicModel
    economic_model_revision: Identifier
    economic_configuration_sha256: Sha256Digest
    utility_model: UtilityModel
    utility_model_revision: Identifier
    utility_configuration_sha256: Sha256Digest
    small_blind_bb: PositiveDecimal
    big_blind_bb: PositiveDecimal
    ante_bb: NonNegativeDecimal
    ante_mode: Literal["none", "per_player", "big_blind"]

    @model_validator(mode="after")
    def validate_blind_units(self) -> Self:
        if self.game_format != "cash":
            raise ValueError(
                "tournament routes remain unavailable until tournament state is modeled"
            )
        if self.big_blind_bb != Decimal(1):
            raise ValueError("BB-normalized routes require big_blind_bb equal to one")
        if self.small_blind_bb >= self.big_blind_bb:
            raise ValueError("small blind must be less than the big blind")
        if (self.ante_bb == 0) != (self.ante_mode == "none"):
            raise ValueError("ante amount and ante mode must agree")
        if self.economic_model != "cash_rake":
            raise ValueError("cash routes require the cash-rake economic model")
        if self.utility_model not in {"chip_ev", "currency_ev"}:
            raise ValueError("cash routes require a cash-compatible utility")
        return self


class TablePositionRoute(RemoteReferenceModel):
    category: Literal["table_position"] = "table_position"
    dealt_in_player_count: TableSize
    hero_position: PositionLabel
    hero_button_distance: Annotated[int, Field(ge=0, le=9, strict=True)]
    hero_action_index: Annotated[int, Field(ge=0, le=9, strict=True)]
    active_player_positions: tuple[PositionLabel, ...] = Field(
        min_length=2,
        max_length=10,
    )
    relative_position: Literal["not_applicable", "in_position", "out_of_position"]

    @model_validator(mode="after")
    def validate_position_indices(self) -> Self:
        if self.hero_button_distance >= self.dealt_in_player_count:
            raise ValueError("button distance must be within the dealt-in table")
        if self.hero_action_index >= self.dealt_in_player_count:
            raise ValueError("hero action index must be within the dealt-in table")
        labels = structural_position_labels(self.dealt_in_player_count)
        if self.hero_position != labels[self.hero_button_distance]:
            raise ValueError("hero position must match table size and button distance")
        expected_action_index = (
            self.hero_button_distance
            if self.dealt_in_player_count == 2
            else (self.hero_button_distance - 3) % self.dealt_in_player_count
        )
        if self.hero_action_index != expected_action_index:
            raise ValueError("hero action index must match the structural position")
        if self.active_player_positions != tuple(sorted(self.active_player_positions)):
            raise ValueError("active player positions must be sorted")
        if len(self.active_player_positions) != len(set(self.active_player_positions)):
            raise ValueError("active player positions must be unique")
        if self.hero_position not in self.active_player_positions:
            raise ValueError("active player positions must include the hero")
        valid_positions = set(labels)
        if any(
            position not in valid_positions
            for position in self.active_player_positions
        ):
            raise ValueError("active position must exist at the dealt-in table")
        return self


class PositionedStack(RemoteReferenceModel):
    position: PositionLabel
    remaining_stack_bb: NonNegativeDecimal


class PositionedCommitment(RemoteReferenceModel):
    position: PositionLabel
    committed_bb: NonNegativeDecimal


class StackWagerPotRoute(RemoteReferenceModel):
    category: Literal["stack_wager_pot"] = "stack_wager_pot"
    hero_stack_bb: NonNegativeDecimal
    active_player_stacks: tuple[PositionedStack, ...] = Field(
        min_length=2,
        max_length=10,
    )
    committed_pot_before_street_bb: NonNegativeDecimal
    current_street_commitments: tuple[PositionedCommitment, ...] = Field(
        min_length=2,
        max_length=10,
    )
    pot_bb: NonNegativeDecimal
    current_wager_bb: NonNegativeDecimal
    amount_to_call_bb: NonNegativeDecimal

    @model_validator(mode="after")
    def validate_wagers(self) -> Self:
        if self.amount_to_call_bb > self.hero_stack_bb:
            raise ValueError("amount to call cannot exceed the hero stack")
        positions = [item.position for item in self.active_player_stacks]
        if positions != sorted(positions):
            raise ValueError("active player stacks must be sorted by position")
        if len(positions) != len(set(positions)):
            raise ValueError("active player stacks require unique positions")
        commitment_positions = [
            item.position for item in self.current_street_commitments
        ]
        if commitment_positions != sorted(commitment_positions):
            raise ValueError("current-street commitments must be sorted by position")
        if len(commitment_positions) != len(set(commitment_positions)):
            raise ValueError("current-street commitments require unique positions")
        derived_wager = max(
            item.committed_bb for item in self.current_street_commitments
        )
        if self.current_wager_bb < derived_wager:
            raise ValueError("current wager cannot trail position commitments")
        derived_pot = self.committed_pot_before_street_bb + sum(
            (item.committed_bb for item in self.current_street_commitments),
            start=Decimal(0),
        )
        if self.pot_bb != derived_pot:
            raise ValueError("pot must match prior pot and current commitments")
        return self


class RemotePriorAction(RemoteReferenceModel):
    street: RemoteStreet
    sequence: Annotated[int, Field(ge=0, strict=True)]
    actor_position: PositionLabel
    action: RemoteAction
    total_committed_bb: NonNegativeDecimal | None = None
    all_in: bool

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.action in {"bet", "call", "raise"} and self.total_committed_bb is None:
            raise ValueError("chip actions require total_committed_bb")
        if (
            self.action in {"bet", "call", "raise"}
            and self.total_committed_bb is not None
            and self.total_committed_bb <= 0
        ):
            raise ValueError("chip actions require a positive total commitment")
        if self.action in {"fold", "check"} and self.total_committed_bb is not None:
            raise ValueError("fold and check cannot carry total_committed_bb")
        if self.all_in and self.action in {"fold", "check"}:
            raise ValueError("fold and check cannot be all-in actions")
        return self


class PriorActionsRoute(RemoteReferenceModel):
    category: Literal["prior_actions"] = "prior_actions"
    actions: tuple[RemotePriorAction, ...] = Field(max_length=256)

    @model_validator(mode="after")
    def validate_action_order(self) -> Self:
        street_order = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}
        order = [street_order[action.street] for action in self.actions]
        if order != sorted(order):
            raise ValueError("prior actions must remain in street order")
        for street in ("preflop", "flop", "turn", "river"):
            sequences = [
                action.sequence for action in self.actions if action.street == street
            ]
            if sequences and sequences != list(range(len(sequences))):
                raise ValueError("prior-action sequences must be contiguous per street")
        return self


class BoardCardsRoute(RemoteReferenceModel):
    category: Literal["board_cards"] = "board_cards"
    cards: tuple[CardCode, ...] = Field(min_length=3, max_length=5)

    @field_validator("cards")
    @classmethod
    def validate_cards(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("board cards must be unique")
        return value


class BoardAbstractionRoute(RemoteReferenceModel):
    category: Literal["board_abstraction"] = "board_abstraction"
    street: Literal["flop", "turn", "river"]
    abstraction_schema_revision: Identifier
    abstraction_schema_sha256: Sha256Digest
    abstraction_sha256: Sha256Digest


class HoleCardsRoute(RemoteReferenceModel):
    category: Literal["hole_cards"] = "hole_cards"
    cards: tuple[CardCode, CardCode]

    @field_validator("cards")
    @classmethod
    def validate_cards(cls, value: tuple[str, str]) -> tuple[str, str]:
        if value[0] == value[1]:
            raise ValueError("hole cards must be distinct")
        return tuple(sorted(value))


class HoleCardAbstractionRoute(RemoteReferenceModel):
    category: Literal["hole_card_abstraction"] = "hole_card_abstraction"
    abstraction_schema_revision: Identifier
    abstraction_schema_sha256: Sha256Digest
    starting_hand_class: StartingHandClass

    @field_validator("starting_hand_class")
    @classmethod
    def validate_starting_hand_class(cls, value: str) -> str:
        rank_order = "23456789TJQKA"
        first, second = value[0], value[1]
        if first == second and len(value) != 2:
            raise ValueError("paired starting hands cannot carry suitedness")
        if first != second:
            if len(value) != 3:
                raise ValueError("unpaired starting hands require suitedness")
            if rank_order.index(first) <= rank_order.index(second):
                raise ValueError("starting-hand ranks must be in descending order")
        return value


class ConditionedRange(RemoteReferenceModel):
    position: PositionLabel
    range_artifact_sha256: Sha256Digest


class ConditionedRangesRoute(RemoteReferenceModel):
    category: Literal["conditioned_ranges"] = "conditioned_ranges"
    ranges: tuple[ConditionedRange, ...] = Field(min_length=1, max_length=9)

    @field_validator("ranges")
    @classmethod
    def validate_ranges(
        cls,
        value: tuple[ConditionedRange, ...],
    ) -> tuple[ConditionedRange, ...]:
        positions = [item.position for item in value]
        if len(positions) != len(set(positions)):
            raise ValueError("conditioned ranges require unique positions")
        if positions != sorted(positions):
            raise ValueError("conditioned ranges must be sorted by position")
        return value


RemoteRouteComponent = Annotated[
    GameEconomicsRoute
    | TablePositionRoute
    | StackWagerPotRoute
    | PriorActionsRoute
    | BoardCardsRoute
    | BoardAbstractionRoute
    | HoleCardsRoute
    | HoleCardAbstractionRoute
    | ConditionedRangesRoute,
    Field(discriminator="category"),
]


class RemoteReferenceRouteRequest(RemoteReferenceModel):
    """The complete outbound DTO; local hand identity is unrepresentable."""

    route_schema_revision: Identifier
    route_schema_sha256: Sha256Digest
    decision_street: RemoteStreet
    components: tuple[RemoteRouteComponent, ...] = Field(min_length=1, max_length=9)

    @model_validator(mode="after")
    def validate_components(self) -> Self:
        categories = self.outbound_categories
        _validate_sorted_unique_categories(categories)
        category_set = set(categories)
        required = {
            "game_economics",
            "prior_actions",
            "stack_wager_pot",
            "table_position",
        }
        if not required <= category_set:
            raise ValueError("route is missing required structural state")
        if not category_set & {"hole_cards", "hole_card_abstraction"}:
            raise ValueError("route requires hole cards or their abstraction")

        board = next(
            (
                component
                for component in self.components
                if isinstance(component, (BoardCardsRoute, BoardAbstractionRoute))
            ),
            None,
        )
        if self.decision_street == "preflop" and board is not None:
            raise ValueError("preflop routes cannot contain board state")
        if self.decision_street != "preflop" and board is None:
            raise ValueError("postflop routes require board state")
        if (
            self.decision_street != "preflop"
            and "conditioned_ranges" not in category_set
        ):
            raise ValueError("postflop routes require conditioned ranges")
        if isinstance(board, BoardCardsRoute):
            expected_cards = {"flop": 3, "turn": 4, "river": 5}
            if len(board.cards) != expected_cards[self.decision_street]:
                raise ValueError("board-card count must match the decision street")
            hole = next(
                (
                    component
                    for component in self.components
                    if isinstance(component, HoleCardsRoute)
                ),
                None,
            )
            if hole is not None and set(board.cards) & set(hole.cards):
                raise ValueError("board and hole cards must be globally unique")
        if (
            isinstance(board, BoardAbstractionRoute)
            and board.street != self.decision_street
        ):
            raise ValueError("board abstraction must match the decision street")

        prior_actions = next(
            component
            for component in self.components
            if isinstance(component, PriorActionsRoute)
        )
        street_order = {"preflop": 0, "flop": 1, "turn": 2, "river": 3}
        if any(
            street_order[action.street] > street_order[self.decision_street]
            for action in prior_actions.actions
        ):
            raise ValueError("prior actions cannot occur after the decision street")
        table = next(
            component
            for component in self.components
            if isinstance(component, TablePositionRoute)
        )
        economics = next(
            component
            for component in self.components
            if isinstance(component, GameEconomicsRoute)
        )
        valid_positions = set(structural_position_labels(table.dealt_in_player_count))
        if any(
            action.actor_position not in valid_positions
            for action in prior_actions.actions
        ):
            raise ValueError("prior-action position must exist at the dealt-in table")
        ranges = next(
            (
                component
                for component in self.components
                if isinstance(component, ConditionedRangesRoute)
            ),
            None,
        )
        if ranges is not None and any(
            item.position not in valid_positions for item in ranges.ranges
        ):
            raise ValueError("conditioned-range position must exist at the table")
        if self.decision_street == "preflop":
            if table.relative_position != "not_applicable":
                raise ValueError("preflop routes have no postflop relative position")
        elif len(table.active_player_positions) == 2:
            if table.relative_position == "not_applicable":
                raise ValueError("heads-up postflop requires relative position")
        elif table.relative_position != "not_applicable":
            raise ValueError("multiway postflop has no binary relative position")
        if ranges is not None:
            expected_range_positions = set(table.active_player_positions) - {
                table.hero_position
            }
            actual_range_positions = {item.position for item in ranges.ranges}
            if actual_range_positions != expected_range_positions:
                raise ValueError(
                    "conditioned ranges must cover every active opponent exactly"
                )
        stacks = next(
            component
            for component in self.components
            if isinstance(component, StackWagerPotRoute)
        )
        remaining_stack_by_position = {
            item.position: item.remaining_stack_bb
            for item in stacks.active_player_stacks
        }
        if set(remaining_stack_by_position) != set(table.active_player_positions):
            raise ValueError("stacks must cover every active player exactly")
        hero_stack = remaining_stack_by_position[table.hero_position]
        if hero_stack != stacks.hero_stack_bb:
            raise ValueError("position-bound hero stack must match hero_stack_bb")
        if hero_stack == 0:
            raise ValueError("a hero with no remaining stack cannot have a decision")
        commitment_by_position = {
            item.position: item.committed_bb
            for item in stacks.current_street_commitments
        }
        if set(commitment_by_position) != valid_positions:
            raise ValueError("commitments must cover every dealt-in position exactly")
        hero_commitment = commitment_by_position[table.hero_position]
        expected_call = min(
            max(stacks.current_wager_bb - hero_commitment, Decimal(0)),
            stacks.hero_stack_bb,
        )
        if stacks.amount_to_call_bb != expected_call:
            raise ValueError("amount to call must match wager and hero commitment")

        small_blind_position = (
            "BTN/SB" if table.dealt_in_player_count == 2 else "SB"
        )
        action_actor_positions = {
            action.actor_position for action in prior_actions.actions
        }
        zero_stack_positions = {
            position
            for position, remaining_stack in remaining_stack_by_position.items()
            if remaining_stack == 0
        }
        initial_all_in_positions = zero_stack_positions - action_actor_positions
        forced_contribution_positions = {small_blind_position, "BB"}
        if economics.ante_mode == "per_player":
            forced_contribution_positions.update(valid_positions)
        elif economics.ante_mode == "big_blind":
            forced_contribution_positions.add("BB")
        if not initial_all_in_positions <= forced_contribution_positions:
            raise ValueError(
                "a stackless player without an action requires a represented"
                " forced contribution"
            )
        live_positions = set(valid_positions)
        folded_positions: set[str] = set()
        all_in_positions = set(initial_all_in_positions)
        for street in ("preflop", "flop", "turn", "river"):
            simulated_commitments = {
                position: Decimal(0) for position in valid_positions
            }
            running_wager = Decimal(0)
            minimum_raise_increment = Decimal(0)
            last_action_wager_by_position: dict[str, Decimal] = {}
            pending_action_positions = live_positions - all_in_positions
            if street == "preflop":
                simulated_commitments[small_blind_position] = (
                    commitment_by_position[small_blind_position]
                    if small_blind_position in initial_all_in_positions
                    else economics.small_blind_bb
                )
                simulated_commitments["BB"] = (
                    commitment_by_position["BB"]
                    if "BB" in initial_all_in_positions
                    else economics.big_blind_bb
                )
                running_wager = economics.big_blind_bb
                minimum_raise_increment = economics.big_blind_bb

            def close_completed_betting_round() -> None:
                eligible = live_positions - all_in_positions
                if len(eligible) != 1:
                    return
                sole_position = next(iter(eligible))
                if simulated_commitments[sole_position] >= running_wager:
                    pending_action_positions.clear()

            for action in prior_actions.actions:
                if action.street != street:
                    continue
                close_completed_betting_round()
                actor = action.actor_position
                if actor in folded_positions or actor in all_in_positions:
                    raise ValueError("folded or all-in players cannot act again")
                if actor not in pending_action_positions:
                    raise ValueError(
                        "the action line cannot continue after betting closes"
                    )
                actor_commitment = simulated_commitments[actor]
                if action.action == "fold":
                    folded_positions.add(actor)
                    live_positions.remove(actor)
                    pending_action_positions.remove(actor)
                    continue
                if action.action == "check":
                    if actor_commitment != running_wager:
                        raise ValueError("a player facing a wager cannot check")
                    last_action_wager_by_position[actor] = running_wager
                    pending_action_positions.remove(actor)
                    continue

                assert action.total_committed_bb is not None
                new_commitment = action.total_committed_bb
                if new_commitment <= actor_commitment:
                    raise ValueError("chip actions must increase the actor commitment")
                if action.action == "call":
                    if actor_commitment >= running_wager:
                        raise ValueError("a call requires an outstanding wager")
                    if action.all_in:
                        if new_commitment > running_wager:
                            raise ValueError("an all-in call cannot exceed the wager")
                    elif new_commitment != running_wager:
                        raise ValueError("a call must match the running wager")
                    full_wager_change = False
                elif action.action == "bet":
                    if running_wager != 0:
                        raise ValueError("a bet cannot be made into an existing wager")
                    minimum_raise_increment = new_commitment - actor_commitment
                    running_wager = new_commitment
                    full_wager_change = True
                else:
                    last_action_wager = last_action_wager_by_position.get(actor)
                    if (
                        last_action_wager is not None
                        and running_wager - last_action_wager
                        < minimum_raise_increment
                    ):
                        raise ValueError(
                            "a short all-in did not reopen this player's raise"
                        )
                    if running_wager == 0 or new_commitment <= running_wager:
                        raise ValueError("a raise must advance an existing wager")
                    raise_increment = new_commitment - running_wager
                    if (
                        not action.all_in
                        and raise_increment < minimum_raise_increment
                    ):
                        raise ValueError("a non-all-in raise must meet the minimum")
                    if raise_increment >= minimum_raise_increment:
                        minimum_raise_increment = raise_increment
                        full_wager_change = True
                    else:
                        full_wager_change = False
                    running_wager = new_commitment
                simulated_commitments[actor] = new_commitment
                last_action_wager_by_position[actor] = running_wager
                if action.all_in:
                    all_in_positions.add(actor)
                if action.action == "call":
                    pending_action_positions.remove(actor)
                elif full_wager_change:
                    pending_action_positions = (
                        live_positions - all_in_positions - {actor}
                    )
                else:
                    pending_action_positions = {
                        position
                        for position in live_positions - all_in_positions - {actor}
                        if simulated_commitments[position] < running_wager
                    }

            close_completed_betting_round()
            if street == self.decision_street:
                if simulated_commitments != commitment_by_position:
                    raise ValueError(
                        "action totals must match current-street commitments"
                    )
                if running_wager != stacks.current_wager_bb:
                    raise ValueError(
                        "current wager must match the reconstructed betting wager"
                    )
                if table.hero_position not in pending_action_positions:
                    raise ValueError(
                        "the action line ended after the betting round closed"
                    )
                break
            if pending_action_positions:
                raise ValueError("a prior-street betting round is incomplete")

        if live_positions != set(table.active_player_positions):
            raise ValueError("active players must match action-line survivors")
        if all_in_positions != zero_stack_positions:
            raise ValueError(
                "all-in players must exactly match active players with no"
                " remaining stack"
            )

        if self.decision_street == "preflop":
            expected_ante_pot = (
                Decimal(0)
                if economics.ante_mode == "none"
                else economics.ante_bb
                if economics.ante_mode == "big_blind"
                else economics.ante_bb * table.dealt_in_player_count
            )
            if stacks.committed_pot_before_street_bb != expected_ante_pot:
                raise ValueError("preflop prior pot must match the configured antes")
            for position, nominal_blind in (
                (small_blind_position, economics.small_blind_bb),
                ("BB", economics.big_blind_bb),
            ):
                contribution = commitment_by_position[position]
                if position in initial_all_in_positions:
                    if contribution > nominal_blind:
                        raise ValueError(
                            "an initial all-in blind cannot exceed its nominal blind"
                        )
                elif contribution < nominal_blind:
                    raise ValueError(f"{position} blind commitment is missing")
            ordered_positions = sorted(
                valid_positions,
                key=lambda position: (
                    structural_position_labels(
                        table.dealt_in_player_count
                    ).index(position)
                    if table.dealt_in_player_count == 2
                    else (
                        structural_position_labels(
                            table.dealt_in_player_count
                        ).index(position)
                        - 3
                    )
                    % table.dealt_in_player_count
                ),
            )
            actionable = [
                position
                for position in ordered_positions
                if position not in initial_all_in_positions
            ]
            cursor = 0
            for action in prior_actions.actions:
                if action.street != "preflop":
                    continue
                if not actionable or action.actor_position != actionable[cursor]:
                    raise ValueError(
                        "preflop actions must be complete and in structural order"
                    )
                if action.action == "fold" or action.all_in:
                    actionable.pop(cursor)
                    if actionable:
                        cursor %= len(actionable)
                else:
                    cursor = (cursor + 1) % len(actionable)
            if not actionable or actionable[cursor] != table.hero_position:
                raise ValueError("preflop action line must end at the hero decision")
        return self

    @property
    def outbound_categories(self) -> tuple[RemoteOutboundCategory, ...]:
        return tuple(component.category for component in self.components)

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    def semantic_digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


class RemoteReferenceRouteDerivation(RemoteReferenceModel):
    """A local decision binding kept outside the closed outbound DTO."""

    decision: DecisionBinding
    decision_state_sha256: Sha256Digest
    outbound_request: RemoteReferenceRouteRequest


class RemoteReferenceDispatchPreflight(RemoteReferenceModel):
    """One single-dispatch candidate or explicit fail-closed unavailable result."""

    decision: DecisionBinding
    evaluated_at: AwareDatetime | None
    outcome: RemoteDispatchOutcome
    reason: RemoteDispatchReason
    provider_id: Identifier | None = None
    provider_configuration_revision: Identifier | None = None
    provider_policy_revision: Identifier | None = None
    provider_policy_sha256: Sha256Digest | None = None
    route_manifest_revision: Identifier | None = None
    route_manifest_sha256: Sha256Digest | None = None
    endpoint_origin: HttpsOrigin | None = None
    reference_source_revision: Identifier | None = None
    commercial_serving_rights_revision: Identifier | None = None
    commercial_serving_rights_sha256: Sha256Digest | None = None
    derived_output_rights_revision: Identifier | None = None
    derived_output_rights_sha256: Sha256Digest | None = None
    disclosure_sha256: Sha256Digest | None = None
    consent_id: Identifier | None = None
    consent_generation: PositiveInteger | None = None
    request_sha256: Sha256Digest | None = None
    outbound_request: RemoteReferenceRouteRequest | None = None
    fresh_consent_recheck: Literal["required_immediately_before_dispatch"] | None = (
        None
    )
    policy_grade_eligibility: Literal["ungraded"] = "ungraded"
    resolved_reference: None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        candidate = self.outcome == "dispatch_candidate"
        if candidate != (self.reason == "preflight_passed"):
            raise ValueError("only a passing preflight is a dispatch candidate")
        candidate_fields = (
            self.provider_id,
            self.provider_configuration_revision,
            self.provider_policy_revision,
            self.provider_policy_sha256,
            self.route_manifest_revision,
            self.route_manifest_sha256,
            self.endpoint_origin,
            self.reference_source_revision,
            self.commercial_serving_rights_revision,
            self.commercial_serving_rights_sha256,
            self.derived_output_rights_revision,
            self.derived_output_rights_sha256,
            self.disclosure_sha256,
            self.consent_id,
            self.consent_generation,
            self.request_sha256,
            self.outbound_request,
            self.fresh_consent_recheck,
        )
        if candidate and any(value is None for value in candidate_fields):
            raise ValueError("a dispatch candidate requires complete local provenance")
        if self.reason == "clock_invalid":
            if self.evaluated_at is not None:
                raise ValueError("an invalid clock cannot claim an evaluation time")
        elif self.evaluated_at is None:
            raise ValueError("a valid preflight requires an evaluation time")
        if not candidate and (
            self.outbound_request is not None
            or self.fresh_consent_recheck is not None
        ):
            raise ValueError(
                "an unavailable preflight cannot expose an outbound request"
            )
        if self.outbound_request is not None:
            if self.request_sha256 != self.outbound_request.semantic_digest():
                raise ValueError("request digest must bind the exact outbound request")
        return self


class RemoteReferenceLookupUnavailable(RemoteReferenceModel):
    """Auditable failure after a passing preflight; never solved evidence."""

    decision: DecisionBinding
    preflight_evaluated_at: AwareDatetime
    occurred_at: AwareDatetime
    reason: RemoteLookupUnavailableReason
    provider_id: Identifier
    provider_configuration_revision: Identifier
    provider_policy_revision: Identifier
    provider_policy_sha256: Sha256Digest
    route_manifest_revision: Identifier
    route_manifest_sha256: Sha256Digest
    endpoint_origin: HttpsOrigin
    reference_source_revision: Identifier
    commercial_serving_rights_revision: Identifier
    commercial_serving_rights_sha256: Sha256Digest
    derived_output_rights_revision: Identifier
    derived_output_rights_sha256: Sha256Digest
    disclosure_sha256: Sha256Digest
    consent_id: Identifier
    consent_generation: PositiveInteger
    route_schema_revision: Identifier
    route_schema_sha256: Sha256Digest
    request_sha256: Sha256Digest
    response_sha256: Sha256Digest | None = None
    remote_coverage: Literal["unavailable"] = "unavailable"
    policy_grade_eligibility: Literal["ungraded"] = "ungraded"
    fallback_behavior: Literal["forbidden"] = "forbidden"
    resolved_reference: None = None

    @model_validator(mode="after")
    def validate_response_evidence(self) -> Self:
        if self.occurred_at < self.preflight_evaluated_at:
            raise ValueError("remote unavailability cannot predate its preflight")
        if self.reason in {"provider_failure", "network_failure"}:
            if self.response_sha256 is not None:
                raise ValueError("transport failures cannot claim response evidence")
        elif self.response_sha256 is None:
            raise ValueError("response outcomes require a local response digest")
        return self
