"""Voluntary hero decision points extracted from approved imported hands.

Extraction never re-derives chip arithmetic: every pot, wager, call, and stack
value is copied from the ``HeroActionContext`` the aggregate already computed.
A hand that cannot be extracted reports why instead of failing silently.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator

from app.domain.imported_hands.models import (
    ActionOrigin,
    ActionType,
    BettingLimit,
    BlindStructure,
    Economics,
    GameVariant,
    HeroActionContext,
    ImportedAction,
    ImportedHandModel,
    ImportedHandRecord,
    ImportedHandState,
    ImportProvenance,
    NonNegativeDecimal,
    NonNegativeInteger,
    OriginKind,
    PositiveDecimal,
    PositiveInteger,
    SeatDecisionState,
    SourceChronology,
    SourceEvidence,
    StableHandIdentity,
    StreetName,
    StructuralPosition,
    TableSize,
    _blind_structure_ready_for_extraction,
    _cash_rake_consistent_for_extraction,
    _economics_ready_for_extraction,
    _hero_decision_contexts_for_extraction,
    _known_action_orders,
    _terminal_hand_ready_for_extraction,
)
from app.domain.poker import Card


HeroActionExclusion = Literal[
    "forced_or_system",
    "client_automatic",
    "unresolved_origin",
]

ExtractionRejection = Literal[
    "not_active",
    "unresolved_conflict",
    "invalid_revision_lineage",
    "incomplete_hand_state",
    "incomplete_economics",
    "unreconciled_pot",
]

DecisionOutcome = Literal["decisions", "no_decision", "not_extractable"]

_RESOLVED_CONFLICT_STATUSES = {"resolved_keep_active", "resolved_use_source"}
_EXTRACTABLE_BETTING_LIMITS = {"no_limit", "pot_limit"}
_EXCLUSION_REASONS: dict[OriginKind, HeroActionExclusion] = {
    "forced_system": "forced_or_system",
    "client_automatic": "client_automatic",
    "unknown": "unresolved_origin",
}


class HeroTableAction(ImportedHandModel):
    """What the player actually did, from the ordered imported history."""

    action_type: ActionType
    amount: PositiveDecimal | None
    total_committed: NonNegativeDecimal | None
    all_in: bool
    origin: ActionOrigin
    evidence: list[SourceEvidence]


class HeroDecisionState(ImportedHandModel):
    """Everything a grading route needs about the spot, exactly."""

    street: StreetName
    board_cards: list[Card]
    hero_cards: list[Card]
    hero_position: StructuralPosition
    dealt_in_player_count: PositiveInteger
    variant: GameVariant
    betting_limit: BettingLimit
    table_size: TableSize
    blinds: BlindStructure
    economics: Economics
    committed_pot_before_street: NonNegativeDecimal
    pot_before_action: NonNegativeDecimal
    current_wager: NonNegativeDecimal
    amount_to_call: NonNegativeDecimal
    hero_stack_before_action: NonNegativeDecimal
    seats: list[SeatDecisionState]


class HeroDecisionPoint(ImportedHandModel):
    """One voluntary hero decision bound to its exact canonical revision."""

    identity: StableHandIdentity
    chronology: SourceChronology
    provenance: ImportProvenance
    canonical_revision: PositiveInteger
    deletion_generation: NonNegativeInteger
    decision_index: NonNegativeInteger
    street: StreetName
    action_sequence: NonNegativeInteger
    state: HeroDecisionState
    table_action: HeroTableAction


class ExcludedHeroAction(ImportedHandModel):
    """A hero action retained for audit but never graded."""

    street: StreetName
    action_sequence: NonNegativeInteger
    action_type: ActionType
    origin: ActionOrigin
    reason: HeroActionExclusion


class HandDecisionExtraction(ImportedHandModel):
    """The complete extraction result for one imported hand."""

    identity: StableHandIdentity | None
    canonical_revision: PositiveInteger | None
    deletion_generation: NonNegativeInteger
    outcome: DecisionOutcome
    rejection: ExtractionRejection | None
    decision_points: list[HeroDecisionPoint]
    excluded_actions: list[ExcludedHeroAction]

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.outcome == "decisions":
            if not self.decision_points:
                raise ValueError(
                    "a decisions outcome requires at least one decision point"
                )
            if self.rejection is not None:
                raise ValueError("a decisions outcome cannot report a rejection")
            if self.canonical_revision is None:
                raise ValueError(
                    "a decisions outcome requires its canonical revision"
                )
        elif self.outcome == "no_decision":
            if self.decision_points:
                raise ValueError(
                    "a no_decision outcome cannot retain decision points"
                )
            if self.rejection is not None:
                raise ValueError("a no_decision outcome cannot report a rejection")
            if self.canonical_revision is None:
                raise ValueError(
                    "a no_decision outcome requires its canonical revision"
                )
        else:
            if self.rejection is None:
                raise ValueError(
                    "a not_extractable outcome requires its rejection reason"
                )
            if self.decision_points:
                raise ValueError(
                    "a not_extractable outcome cannot retain decision points"
                )
            if self.canonical_revision is not None:
                raise ValueError(
                    "a not_extractable outcome cannot bind a canonical revision"
                )
        if self.identity is None and self.outcome != "not_extractable":
            raise ValueError("an extracted hand requires its stable identity")
        return self


def extract_hero_decision_points(
    record: ImportedHandRecord,
) -> HandDecisionExtraction:
    """Extract the voluntary hero decisions an approved record can prove."""

    state = record.active_state_for_extraction
    rejection, contexts = _rejection_reason(record, state)
    deletion_generation = record.lifecycle.deletion_generation
    if rejection is not None:
        return HandDecisionExtraction(
            identity=record.identity,
            canonical_revision=None,
            deletion_generation=deletion_generation,
            outcome="not_extractable",
            rejection=rejection,
            decision_points=[],
            excluded_actions=[],
        )
    assert state is not None
    assert record.identity is not None
    canonical_revision = record.lifecycle.active_canonical_revision
    assert canonical_revision is not None
    provenance = _active_provenance(record, state)
    decision_points = [
        _decision_point(
            context,
            state=state,
            identity=record.identity,
            provenance=provenance,
            canonical_revision=canonical_revision,
            deletion_generation=deletion_generation,
            decision_index=decision_index,
        )
        for decision_index, context in enumerate(contexts)
    ]
    excluded_actions = [
        ExcludedHeroAction(
            street=street,
            action_sequence=action.sequence,
            action_type=action.action_type,
            origin=action.origin,
            reason=_EXCLUSION_REASONS[action.origin.kind],
        )
        for street, action in _hero_actions(state)
        if not action.is_player_decision
    ]
    return HandDecisionExtraction(
        identity=record.identity,
        canonical_revision=canonical_revision,
        deletion_generation=deletion_generation,
        outcome="decisions" if decision_points else "no_decision",
        rejection=None,
        decision_points=decision_points,
        excluded_actions=excluded_actions,
    )


def _rejection_reason(
    record: ImportedHandRecord,
    state: ImportedHandState | None,
) -> tuple[ExtractionRejection | None, list[HeroActionContext]]:
    """Resolve the first rejection reason in ``ExtractionRejection`` order.

    The accepted hero contexts come back with the verdict so the caller emits
    decision points from the very walk this function proved complete. Reading
    them from a second traversal instead would let the two silently disagree:
    a hand with hero decisions could then report ``no_decision``, which is a
    structurally legal result no validator can reject.
    """

    if not record.lifecycle.learning_eligible:
        return "not_active", []
    if any(
        conflict.status not in _RESOLVED_CONFLICT_STATUSES
        for conflict in record.conflicts
    ):
        return "unresolved_conflict", []
    if state is None:
        return "invalid_revision_lineage", []
    contexts = _complete_hand_state_contexts(state)
    if contexts is None:
        return "incomplete_hand_state", []
    if not _economics_are_complete(state):
        return "incomplete_economics", []
    if not record.active_pot_reconciles_for_extraction:
        return "unreconciled_pot", []
    return None, contexts


def _complete_hand_state_contexts(
    state: ImportedHandState,
) -> list[HeroActionContext] | None:
    """Return the walk's hero contexts, or ``None`` for an incomplete state.

    Every condition up to the walk is the aggregate's own hand-state condition.
    The final clause is deliberately **stricter** than the aggregate: the gate
    is content to publish a partial walk, dropping the hero decisions it could
    not resolve, whereas extraction rejects the whole hand. A decision point
    silently missing from the middle of a hand is indistinguishable from a hand
    that never had one, so it has to be a reported reason instead.
    """

    if state.hero_player_id is None:
        return None
    if not _terminal_hand_ready_for_extraction(state):
        return None
    if not _blind_structure_ready_for_extraction(state.game.blinds):
        return None
    if state.game.betting_limit not in _EXTRACTABLE_BETTING_LIMITS:
        return None
    hero = next(
        (seat for seat in state.seats if seat.player_id == state.hero_player_id),
        None,
    )
    if hero is None or hero.participation != "dealt_in":
        return None
    if any(seat.participation == "unknown" for seat in state.seats):
        return None
    if any(
        seat.participation == "dealt_in" and seat.starting_stack is None
        for seat in state.seats
    ):
        return None
    if _known_action_orders(state.seats, state.button_seat) is None:
        return None
    # Cards, boards, and chip representations are resolved inside the walk, so
    # an unemitted hero decision means the state itself is still incomplete.
    contexts = _hero_decision_contexts_for_extraction(state)
    graded = [
        action for _, action in _hero_actions(state) if action.is_player_decision
    ]
    if len(contexts) != len(graded):
        return None
    return contexts


def _economics_are_complete(state: ImportedHandState) -> bool:
    """Apply the aggregate's own economics conditions for extraction."""

    dealt_in_starting_stacks = {
        seat.player_id: seat.starting_stack
        for seat in state.seats
        if seat.participation == "dealt_in"
    }
    return _economics_ready_for_extraction(
        state.game.economics,
        dealt_in_starting_stacks=dealt_in_starting_stacks,
    ) and _cash_rake_consistent_for_extraction(state)


def _hero_actions(
    state: ImportedHandState,
) -> list[tuple[StreetName, ImportedAction]]:
    """Return hero's actions in street then sequence order."""

    return [
        (street.street, action)
        for street in state.streets
        for action in street.actions
        if action.actor_id == state.hero_player_id
    ]


def _active_provenance(
    record: ImportedHandRecord,
    state: ImportedHandState,
) -> ImportProvenance:
    """Return the import provenance of the raw source behind the active state.

    The aggregate binds the active canonical revision to its detected raw
    source, and the lineage check that already passed re-proves that binding,
    so the retained raw source always exists here.
    """

    return next(
        raw.provenance
        for raw in record.raw_sources
        if raw.raw_source_id == state.chronology.source_file_id
    )


def _decision_point(
    context: HeroActionContext,
    *,
    state: ImportedHandState,
    identity: StableHandIdentity,
    provenance: ImportProvenance,
    canonical_revision: int,
    deletion_generation: int,
    decision_index: int,
) -> HeroDecisionPoint:
    """Bind one emitted hero action context to its canonical revision."""

    hero_seat = next(
        seat for seat in context.seats if seat.player_id == state.hero_player_id
    )
    action = context.action
    return HeroDecisionPoint(
        identity=identity,
        chronology=state.chronology,
        provenance=provenance,
        canonical_revision=canonical_revision,
        deletion_generation=deletion_generation,
        decision_index=decision_index,
        street=context.street,
        action_sequence=context.action_sequence,
        state=HeroDecisionState(
            street=context.street,
            board_cards=list(context.board_cards),
            hero_cards=list(state.hero_cards),
            hero_position=hero_seat.position,
            dealt_in_player_count=hero_seat.position.dealt_in_player_count,
            variant=state.game.variant,
            betting_limit=state.game.betting_limit,
            table_size=state.game.table_size,
            blinds=state.game.blinds,
            economics=state.game.economics,
            committed_pot_before_street=context.committed_pot_before_street,
            pot_before_action=context.pot_before_action,
            current_wager=context.current_wager,
            amount_to_call=context.amount_to_call,
            hero_stack_before_action=context.hero_stack_before_action,
            seats=list(context.seats),
        ),
        table_action=HeroTableAction(
            action_type=action.action_type,
            amount=action.amount,
            total_committed=action.total_committed,
            all_in=action.all_in,
            origin=action.origin,
            evidence=list(action.evidence),
        ),
    )
