"""Voluntary hero decision points extracted from approved imported hands.

Extraction never re-derives chip arithmetic: every pot, wager, call, and stack
value is copied from the ``HeroActionContext`` the aggregate already computed.
A hand that cannot be extracted reports why instead of failing silently.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from app.domain.imported_hands.models import (
    ActionOrigin,
    ActionType,
    BettingLimit,
    BlindStructure,
    Economics,
    GameVariant,
    HeroActionContext,
    HeroDecisionGateRejection,
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
    _CHIP_ACTIONS,
    _raise_is_reopened,
    _sole_actionable_player_with_only_all_in_opponents,
    _stack_is_exhausted,
    _STREET_BOARD_CARDS,
    _STREET_ORDER,
    _TABLE_ACTIONS,
    _validate_action_shape,
)
from app.domain.poker import Card


HeroActionExclusion = Literal[
    "forced_or_system",
    "client_automatic",
    "unresolved_origin",
]

ExtractionRejection = HeroDecisionGateRejection

DecisionOutcome = Literal["decisions", "no_decision", "not_extractable"]

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
    evidence: list[SourceEvidence] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_table_action_shape(self) -> Self:
        # The same rules the import boundary applied to this action: a rehydrated
        # payload must not carry a shape `ImportedAction` would have refused,
        # such as a check with an amount or a fold marked all-in.
        _validate_action_shape(
            self.action_type,
            amount=self.amount,
            all_in=self.all_in,
            origin_kind=self.origin.kind,
        )
        return self


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

    @model_validator(mode="after")
    def validate_record_shape(self) -> Self:
        # The line drops the origin, so only the rules that do not need it
        # apply -- but a check carrying chips, or a fold marked all-in, is
        # impossible however the record was rehydrated.
        _validate_action_shape(
            self.action_type,
            amount=self.amount,
            all_in=self.all_in,
        )
        return self


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

    ``raise_reopened`` is ``False`` when the hero may only call or fold, for
    any of three reasons: the hero holds no chips beyond ``amount_to_call``, so
    an all-in call is the most they can put in; an opponent's short all-in did
    not raise the wager by a full increment; or the hero is the sole actionable
    player and every live opponent is all-in, so no one could answer a raise.
    Offering a raise there grades against an action the hand validator itself
    would reject, or one the hero cannot afford.

    ``acted_wager`` and ``reopen_increment`` retain the historical inputs the
    aggregate used for the short-all-in rule. Rehydration passes those scalars
    through the aggregate's shared reopening helper instead of replaying the
    betting line, so all three closure reasons remain independently checkable.

    ``last_full_wager_increment`` is the yardstick a minimum legal raise is
    measured against. ``None`` means the aggregate could not establish
    it; a known increment is always positive, so ``None`` is the only "unknown"
    and can never be confused with one; a consumer that cannot size a raise has to
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
    last_full_wager_increment: PositiveDecimal | None
    acted_wager: NonNegativeDecimal | None
    reopen_increment: PositiveDecimal | None
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
        self._validate_seat_ring()
        self._validate_cards()
        self._validate_current_street()
        self._validate_raise_legality()
        return self

    def _hero_seat(self) -> SeatDecisionState:
        hero = next(
            (
                seat
                for seat in self.seats
                if seat.position == self.hero_position
            ),
            None,
        )
        if hero is None:
            raise ValueError("hero_position does not identify a seat")
        return hero

    def _validate_raise_legality(self) -> None:
        """Re-derive the raise verdict from the aggregate-owned rules.

        The historical wager inputs are scalars copied from the extraction
        walk. Passing them through ``_raise_is_reopened`` keeps the short-all-in
        rule in one implementation; the action history is evidence for grading,
        not a second state machine for validation.
        """

        hero = self._hero_seat()
        affordable = hero.stack_before_action > self.amount_to_call
        sole_actionable = _sole_actionable_player_with_only_all_in_opponents(
            {seat.player_id for seat in self.seats if seat.status != "folded"},
            {seat.player_id for seat in self.seats if seat.status == "live"},
        )
        increment_reopened = _raise_is_reopened(
            hero.player_id,
            enforce_full_raise_increment=(
                self.betting_limit in {"no_limit", "pot_limit"}
            ),
            current_wager=self.current_wager,
            acted_wager_by_player={hero.player_id: self.acted_wager},
            reopen_increment_by_player={hero.player_id: self.reopen_increment},
        )
        expected = (
            affordable
            and sole_actionable != hero.player_id
            and increment_reopened
        )
        if self.raise_reopened == expected:
            return
        if self.raise_reopened and not affordable:
            raise ValueError(
                f"raising is published open, but the hero's"
                f" {hero.stack_before_action} behind cannot beat the"
                f" {self.amount_to_call} call"
            )
        if self.raise_reopened and sole_actionable == hero.player_id:
            raise ValueError(
                "raising is published open, but every live opponent is all-in"
                " and no one could answer a raise"
            )
        if self.raise_reopened:
            raise ValueError(
                "raising is published open, but the wager has not grown by"
                " the full increment that stood when the hero last acted"
            )
        raise ValueError(
            "raising is published closed, but affordability, opponent"
            " actionability, and the prior full-wager increment all leave it"
            " open"
        )

    def _validate_seat_ring(self) -> None:
        """Require the seats to be one complete ring of the declared size.

        ``StructuralPosition`` already ties each seat's label and action index
        to its own count and button distance, so what remains is that the seats
        agree on that count and occupy every distance in the ring exactly once,
        in order -- which is the ring ``derive_structural_positions`` builds.
        """

        if len(self.seats) != self.dealt_in_player_count:
            raise ValueError(
                f"dealt_in_player_count {self.dealt_in_player_count} does not"
                f" match the {len(self.seats)} seats published"
            )
        mismatched = [
            seat.player_id
            for seat in self.seats
            if seat.position.dealt_in_player_count != self.dealt_in_player_count
        ]
        if mismatched:
            raise ValueError(
                f"seat positions disagree with dealt_in_player_count:"
                f" {', '.join(mismatched)}"
            )
        distances = [seat.position.button_distance for seat in self.seats]
        if distances != list(range(self.dealt_in_player_count)):
            raise ValueError(
                "seats must run once around the ring in button order"
            )
        if self.hero_position.dealt_in_player_count != self.dealt_in_player_count:
            raise ValueError(
                "hero_position disagrees with dealt_in_player_count"
            )

    def _validate_cards(self) -> None:
        """Require the exact cards this street's decision is made with."""

        if len(self.hero_cards) != 2:
            raise ValueError("a decision requires both hero cards")
        expected_board = _STREET_BOARD_CARDS[self.street]
        if len(self.board_cards) != expected_board:
            raise ValueError(
                f"a {self.street} decision requires exactly {expected_board}"
                f" board cards, not {len(self.board_cards)}"
            )
        codes = [card.code for card in (*self.hero_cards, *self.board_cards)]
        if len(set(codes)) != len(codes):
            raise ValueError(
                "hero cards and board cards must not repeat a card"
            )

    def _validate_current_street(self) -> None:
        """Bind the street in progress to the chip snapshot beside it.

        Every seat's ``street_commitment`` is the cumulative total of that
        player's last action on this street, or zero if they have not acted --
        including the hero, whose own action the line excludes, so their
        commitment is the one they carry into the decision. That tie is skipped
        when any record on this street has an unresolved total, exactly as the
        completed-street check skips, because the walk may legitimately leave a
        value unknown and this contract must not read that as zero.

        The pot, the call amount, and the stacks are then checked against the
        seats unconditionally: they are derived from values the same snapshot
        publishes, so nothing about them can be unknown.
        """

        current = self.action_history[-1]
        street_totals: dict[str, NonNegativeDecimal] = {}
        for record in current.actions:
            if record.total_committed is None:
                street_totals = {}
                break
            street_totals[record.player_id] = record.total_committed
        else:
            for seat in self.seats:
                published = street_totals.get(seat.player_id, Decimal(0))
                if seat.street_commitment != published:
                    raise ValueError(
                        f"{seat.player_id} committed {seat.street_commitment} on"
                        f" {self.street}, which contradicts the"
                        f" {published} its action history shows"
                    )
        last_action_by_player = {
            record.player_id: record.action_type
            for entry in self.action_history
            for record in entry.actions
        }
        for seat in self.seats:
            if seat.live_commitment > seat.street_commitment:
                raise ValueError(
                    f"{seat.player_id} live commitment exceeds its street"
                    " commitment"
                )
            if seat.stack_before_action != (
                seat.starting_stack - seat.hand_commitment
            ):
                raise ValueError(
                    f"{seat.player_id} stack does not match its starting stack"
                    " less what it has committed"
                )
            # The producer's own derivation: a player who has folded is out, a
            # player whose commitment exhausts their stack is all-in, and
            # anyone else is still live.
            expected_status = (
                "folded"
                if last_action_by_player.get(seat.player_id) == "fold"
                else "all_in"
                if _stack_is_exhausted(seat.starting_stack, seat.hand_commitment)
                else "live"
            )
            if seat.status != expected_status:
                raise ValueError(
                    f"{seat.player_id} is published {seat.status} but its stack"
                    f" and betting history make it {expected_status}"
                )
        pot = self.committed_pot_before_street + sum(
            (seat.street_commitment for seat in self.seats),
            Decimal(0),
        )
        if pot != self.pot_before_action:
            raise ValueError(
                f"pot_before_action {self.pot_before_action} contradicts the"
                f" {pot} its seats and completed streets commit"
            )
        hero = self._hero_seat()
        if self.hero_stack_before_action != hero.stack_before_action:
            raise ValueError(
                "hero_stack_before_action contradicts the hero's own seat"
            )
        # Tie the wager to the seats rather than to the call amount, which is
        # derived from it: the outstanding wager is the highest live commitment
        # on the table, and the one thing that can lift it above that is a big
        # blind posted short, which floors it at the configured big blind.
        highest_live = max(
            (seat.live_commitment for seat in self.seats),
            default=Decimal(0),
        )
        if self.current_wager < highest_live:
            raise ValueError(
                f"current_wager {self.current_wager} is below the {highest_live}"
                " its seats have live"
            )
        if (
            self.current_wager > highest_live
            and self.current_wager != self.blinds.big_blind
        ):
            raise ValueError(
                f"current_wager {self.current_wager} exceeds the {highest_live}"
                " its seats have live without a short blind post to explain it"
            )
        expected_call = max(
            Decimal(0), self.current_wager - hero.live_commitment
        )
        if self.amount_to_call != expected_call:
            raise ValueError(
                f"amount_to_call {self.amount_to_call} contradicts the"
                f" {expected_call} owed at wager {self.current_wager}"
            )


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
        self._validate_table_action_chips()
        return self

    def _validate_table_action_chips(self) -> None:
        """Bind what the hero did to the chips they had when they did it.

        The seats are the state immediately before this action, so the action's
        own chips have to continue from them: what it adds lands on the hero's
        street commitment, an action that takes their last chip is all-in, and
        a call matches what is owed or goes all-in for less.
        """

        action = self.table_action
        hero = self.state._hero_seat()
        if action.action_type not in _CHIP_ACTIONS:
            if action.total_committed != hero.street_commitment:
                raise ValueError(
                    f"a {action.action_type} leaves the hero's street"
                    f" commitment at {hero.street_commitment}, not"
                    f" {action.total_committed}"
                )
            return
        if action.amount is None or action.total_committed is None:
            raise ValueError(
                f"a {action.action_type} requires the chips it moved and the"
                " commitment it left"
            )
        expected_total = hero.street_commitment + action.amount
        if action.total_committed != expected_total:
            raise ValueError(
                f"a {action.action_type} of {action.amount} on top of"
                f" {hero.street_commitment} leaves {expected_total}, not"
                f" {action.total_committed}"
            )
        if action.amount > hero.stack_before_action:
            raise ValueError(
                f"a {action.action_type} of {action.amount} exceeds the hero's"
                f" {hero.stack_before_action} behind"
            )
        exhausts = action.amount == hero.stack_before_action
        if action.all_in != exhausts:
            raise ValueError(
                f"a {action.action_type} of {action.amount} against"
                f" {hero.stack_before_action} behind is"
                f" {'' if exhausts else 'not '}all-in"
            )
        if action.action_type == "call":
            owed = min(self.state.amount_to_call, hero.stack_before_action)
            if action.amount != owed:
                raise ValueError(
                    f"a call must put in the {owed} owed or the hero's whole"
                    f" stack, not {action.amount}"
                )


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

    rejection, snapshot, state, contexts = (
        record._active_hero_decision_context_gate(
            require_complete_extraction=True,
        )
    )
    source_record = snapshot if snapshot is not None else record
    deletion_generation = source_record.lifecycle.deletion_generation
    if rejection is not None:
        return HandDecisionExtraction(
            identity=source_record.identity,
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
    assert snapshot is not None
    assert snapshot.identity is not None
    canonical_revision = snapshot.lifecycle.active_canonical_revision
    assert canonical_revision is not None
    provenance = _active_provenance(snapshot, state)
    decision_points = [
        _decision_point(
            context,
            state=state,
            identity=snapshot.identity,
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
        identity=snapshot.identity,
        chronology=state.chronology,
        provenance=provenance,
        canonical_revision=canonical_revision,
        deletion_generation=deletion_generation,
        outcome="decisions" if decision_points else "no_decision",
        rejection=None,
        decision_points=decision_points,
        excluded_actions=excluded_actions,
    )


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
            acted_wager=context.acted_wager,
            reopen_increment=context.reopen_increment,
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
