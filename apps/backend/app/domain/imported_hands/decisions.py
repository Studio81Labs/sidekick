"""Voluntary hero decision points extracted from approved imported hands.

Extraction never re-derives chip arithmetic: every pot, wager, call, and stack
value is copied from the ``HeroActionContext`` the aggregate already computed.
A hand that cannot be extracted reports why instead of failing silently.
"""

from __future__ import annotations

from decimal import Decimal
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
    Identifier,
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
    _STREET_ORDER,
    _TABLE_ACTIONS,
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
    """What the player actually did, from the ordered imported history.

    ``amount``, ``total_committed`` and ``all_in`` are the aggregate's resolved
    values, exactly as in the betting line -- the hero's own action is the one
    the line excludes, and it must not be the one action a grader reads from
    raw source fields. A shove that exhausts the hero's stack is published
    all-in even when the source omits the marker, and a sizing stays ``None``
    only where the walk could not establish it.

    ``origin`` and ``evidence`` stay raw: they are this action's audit trail.
    """

    action_type: ActionType
    amount: PositiveDecimal | None
    total_committed: NonNegativeDecimal | None
    all_in: bool
    origin: ActionOrigin
    evidence: list[SourceEvidence]


class DecisionActionRecord(ImportedHandModel):
    """One table action in the betting line, as a grader needs to read it.

    Origin and evidence are deliberately absent: a betting line is defined by
    what happened at the table, not by why the source believes it happened.
    The hero's own action keeps its origin on ``HeroTableAction``.

    ``amount``, ``total_committed`` and ``all_in`` are the values the
    extraction walk resolved, not whichever the adapter happened to state, so a
    consumer sizing against the line reads the same chips -- and the same
    all-in verdict -- that the pot and seat fields were built from. An action
    exhausting a known stack is published as all-in even when the source omits
    the marker, matching the seat status beside it. A chip value stays ``None``
    only when the walk could not establish it exactly.
    """

    sequence: NonNegativeInteger
    player_id: Identifier
    position: StructuralPosition
    action_type: ActionType
    amount: PositiveDecimal | None
    total_committed: NonNegativeDecimal | None
    all_in: bool


class StreetActionHistory(ImportedHandModel):
    """Every action taken on one street, in the order they were taken."""

    street: StreetName
    actions: list[DecisionActionRecord]

    @model_validator(mode="after")
    def validate_action_order(self) -> Self:
        sequences = [record.sequence for record in self.actions]
        if sequences != list(range(len(sequences))):
            raise ValueError(
                f"{self.street} action history must be contiguous and ordered"
                " from zero"
            )
        return self


class HeroDecisionState(ImportedHandModel):
    """Everything a grading route needs about the spot, exactly.

    The wager fields alone do not describe the legal action set. A consumer
    must read both raise-legality fields before offering a raise:

    ``raise_reopened`` is ``False`` when the hero may only call or fold,
    for either of two reasons: an opponent's short all-in did not raise
    the wager by a full increment, or the hero is the sole actionable
    player and every live opponent is all-in, so no one could answer a
    raise. Offering a raise there grades against an action the hand
    validator itself would reject.

    ``last_full_wager_increment`` is the yardstick a minimum legal raise is
    measured against. ``None`` means the aggregate could not establish it and
    must never be read as zero; a consumer that cannot size a raise has to
    withhold it rather than offer one of arbitrary size.

    ``action_history`` is the ordered betting line: every street from preflop
    through ``street``, the current one truncated immediately before the hero's
    own action. Compare an entry's ``street`` against ``street`` to tell the
    completed prefix from the street in progress. It is not redundant with the
    chip fields -- distinct lines reach identical pots, wagers, and
    commitments, so a line-sensitive route cannot identify the spot without it.
    """

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
    last_full_wager_increment: NonNegativeDecimal | None
    raise_reopened: bool
    hero_stack_before_action: NonNegativeDecimal
    seats: list[SeatDecisionState]
    action_history: list[StreetActionHistory]

    @model_validator(mode="after")
    def validate_action_history(self) -> Self:
        streets = [entry.street for entry in self.action_history]
        if not streets:
            raise ValueError("a decision state requires its betting line")
        expected = [
            street
            for street, order in sorted(
                _STREET_ORDER.items(),
                key=lambda item: item[1],
            )
            if order <= _STREET_ORDER[self.street]
        ]
        if streets != expected:
            raise ValueError(
                "action_history must run in street order from preflop through"
                f" {self.street} without gaps or duplicates"
            )
        positions = {seat.player_id: seat.position for seat in self.seats}
        for entry in self.action_history:
            for record in entry.actions:
                seat_position = positions.get(record.player_id)
                if seat_position is None:
                    raise ValueError(
                        f"action history actor {record.player_id} is not a"
                        " dealt-in seat of this decision"
                    )
                if record.position != seat_position:
                    raise ValueError(
                        f"action history position for {record.player_id} does"
                        " not match its seat"
                    )
        completed_total = _completed_street_commitment(self.action_history[:-1])
        if (
            completed_total is not None
            and completed_total != self.committed_pot_before_street
        ):
            raise ValueError(
                "completed action history commits"
                f" {completed_total}, which contradicts"
                f" committed_pot_before_street {self.committed_pot_before_street}"
            )
        return self


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

    @model_validator(mode="after")
    def validate_decision_binding(self) -> Self:
        # Only a voluntary table decision can be graded. Forced posts,
        # client-automatic actions, and unresolved origins are retained as
        # excluded actions; nothing may rehydrate one of them as a decision and
        # feed it to grading or mastery as though the player chose it.
        if self.table_action.action_type not in _TABLE_ACTIONS:
            raise ValueError(
                "a decision point requires a table decision, not a forced or"
                " system action"
            )
        if self.table_action.origin.kind != "player_selected":
            raise ValueError(
                "a decision point requires a player-selected table action, not"
                f" a {self.table_action.origin.kind} one"
            )
        if self.state.street != self.street:
            raise ValueError("decision state street must match the decision")
        current = self.state.action_history[-1]
        if len(current.actions) != self.action_sequence:
            raise ValueError(
                "the current street's action history must hold every action"
                " before the hero's own and stop there"
            )
        return self


class ExcludedHeroAction(ImportedHandModel):
    """A hero action retained for audit but never graded."""

    street: StreetName
    action_sequence: NonNegativeInteger
    action_type: ActionType
    origin: ActionOrigin
    reason: HeroActionExclusion

    @model_validator(mode="after")
    def validate_exclusion(self) -> Self:
        """Keep the exclusion honest in both directions.

        A player-selected action is a decision and must not be parked here --
        an origin the player confirmed during approval is player-selected by
        the time it reaches extraction, so parking one would drop a decision
        the hand is required to grade. And the reason must be the one this
        origin actually earns, not another exclusion's.
        """

        expected = _EXCLUSION_REASONS.get(self.origin.kind)
        if expected is None:
            raise ValueError(
                "a player-selected action is a decision, not an excluded action"
            )
        if expected != self.reason:
            raise ValueError(
                f"a {self.origin.kind} action must be excluded as {expected},"
                f" not {self.reason}"
            )
        return self


class HandDecisionExtraction(ImportedHandModel):
    """The complete extraction result for one imported hand.

    ``chronology`` and ``provenance`` are hand-level facts, carried here rather
    than only on the decision points, because a valid hand can have no
    decisions at all -- a big-blind walk is retained with its provenance and an
    explicit ``no_decision`` outcome, and points alone would leave it with
    none. They follow ``canonical_revision``: present for every extracted hand,
    absent for a rejected one, which binds no canonical artifact.
    """

    identity: StableHandIdentity | None
    chronology: SourceChronology | None
    provenance: ImportProvenance | None
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
            self._require_hand_provenance("decisions")
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
            self._require_hand_provenance("no_decision")
        else:
            if self.rejection is None:
                raise ValueError(
                    "a not_extractable outcome requires its rejection reason"
                )
            if self.decision_points:
                raise ValueError(
                    "a not_extractable outcome cannot retain decision points"
                )
            if self.excluded_actions:
                raise ValueError(
                    "a not_extractable outcome cannot retain excluded actions"
                )
            if self.canonical_revision is not None:
                raise ValueError(
                    "a not_extractable outcome cannot bind a canonical revision"
                )
            if self.chronology is not None or self.provenance is not None:
                raise ValueError(
                    "a not_extractable outcome cannot bind hand provenance"
                )
        if self.identity is None and self.outcome != "not_extractable":
            raise ValueError("an extracted hand requires its stable identity")
        return self

    def _require_hand_provenance(self, outcome: str) -> None:
        if self.chronology is None:
            raise ValueError(
                f"a {outcome} outcome requires its source chronology"
            )
        if self.provenance is None:
            raise ValueError(
                f"a {outcome} outcome requires its import provenance"
            )

    @model_validator(mode="after")
    def validate_point_binding(self) -> Self:
        """Bind every retained artifact to this envelope and to the hand's order.

        ``validate_outcome`` runs first and already proves that decision points
        exist only for a ``decisions`` outcome, which carries a non-``None``
        identity and canonical revision -- so the equality checks below are only
        ever reached with a fully bound envelope. A rejection outcome retains no
        points or excluded actions at all, and nothing here applies to it.

        Without this, a rehydrated envelope could mix revisions or generations,
        or reorder what the hand actually did, and supersede or deletion logic
        would treat stale decisions as current.

        ``chronology`` and ``provenance`` are bound the same way, against the
        envelope's own copies: every point in one envelope came from one hand,
        so a point that disagrees can only have been assembled by hand or
        corrupted.
        """

        for point in self.decision_points:
            if point.identity != self.identity:
                raise ValueError(
                    "decision point identity does not match the extracted hand"
                )
            if point.canonical_revision != self.canonical_revision:
                raise ValueError(
                    "decision point canonical revision does not match the"
                    " extracted hand"
                )
            if point.deletion_generation != self.deletion_generation:
                raise ValueError(
                    "decision point deletion generation does not match the"
                    " extracted hand"
                )
            if point.chronology != self.chronology:
                raise ValueError(
                    "decision point source chronology does not match the"
                    " extracted hand"
                )
            if point.provenance != self.provenance:
                raise ValueError(
                    "decision point import provenance does not match the"
                    " extracted hand"
                )
        indexes = [point.decision_index for point in self.decision_points]
        if indexes != list(range(len(indexes))):
            raise ValueError(
                "decision_index values must be contiguous and ordered from zero"
            )
        decided = [
            (_STREET_ORDER[point.street], point.action_sequence)
            for point in self.decision_points
        ]
        if decided != sorted(set(decided)):
            raise ValueError(
                "decision points must run in street then action order"
            )
        excluded = [
            (_STREET_ORDER[action.street], action.action_sequence)
            for action in self.excluded_actions
        ]
        if excluded != sorted(set(excluded)):
            raise ValueError(
                "excluded actions must run in street then action order without"
                " repeating one"
            )
        if set(decided) & set(excluded):
            raise ValueError(
                "a hero action cannot be both a decision point and an excluded"
                " action"
            )
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
            chronology=None,
            provenance=None,
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
        chronology=state.chronology,
        provenance=provenance,
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


def _completed_street_commitment(
    completed: list[StreetActionHistory],
) -> NonNegativeDecimal | None:
    """Total the chips the completed streets say every player has committed.

    A player's commitment on a finished street is the cumulative total of their
    last action on it, so the line and ``committed_pot_before_street`` must
    agree. Returns ``None`` when any of those totals is unresolved, which the
    walk allows and this contract must not treat as zero.
    """

    total = Decimal(0)
    for entry in completed:
        street_totals: dict[str, Decimal] = {}
        for record in entry.actions:
            if record.total_committed is None:
                return None
            street_totals[record.player_id] = record.total_committed
        total += sum(street_totals.values(), Decimal(0))
    return total


def _action_history(context: HeroActionContext) -> list[StreetActionHistory]:
    """Project the walk's ordered line into its grading-relevant shape."""

    positions = {seat.player_id: seat.position for seat in context.seats}
    return [
        StreetActionHistory(
            street=slice_.street,
            actions=[
                DecisionActionRecord(
                    sequence=resolved.action.sequence,
                    player_id=resolved.action.actor_id,
                    position=positions[resolved.action.actor_id],
                    action_type=resolved.action.action_type,
                    amount=resolved.amount,
                    total_committed=resolved.total_committed,
                    all_in=resolved.all_in,
                )
                for resolved in slice_.actions
            ],
        )
        for slice_ in context.action_history
    ]


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
    resolved = context.resolved_action
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
            last_full_wager_increment=context.last_full_wager_increment,
            raise_reopened=context.raise_reopened,
            hero_stack_before_action=context.hero_stack_before_action,
            seats=list(context.seats),
            action_history=_action_history(context),
        ),
        table_action=HeroTableAction(
            action_type=action.action_type,
            amount=resolved.amount,
            total_committed=resolved.total_committed,
            all_in=resolved.all_in,
            origin=action.origin,
            evidence=list(action.evidence),
        ),
    )
