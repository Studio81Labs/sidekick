"""Pure, fail-closed comparison of one decision with one resolved policy."""

from __future__ import annotations

import json
from hashlib import sha256

from app.domain.grading.models import (
    DecisionGrade,
    GradeClassification,
    GradeReason,
    PolicyLine,
    ResolvedReferencePolicy,
    WAGER_ACTIONS,
)
from app.domain.imported_hands import HeroDecisionPoint
from app.domain.learning_content.models import DecisionBinding


def decision_grading_context_sha256(decision: HeroDecisionPoint) -> str:
    """Fingerprint every route-critical field without including the action taken."""

    validated = _validated_decision(decision)
    payload = json.dumps(
        validated.state.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def grade_decision(
    decision: HeroDecisionPoint,
    *,
    reference: ResolvedReferencePolicy | None,
) -> DecisionGrade:
    """Classify one voluntary action while keeping later learning gates closed."""

    validated = _validated_decision(decision)
    binding = DecisionBinding.from_decision(validated)
    context_sha256 = decision_grading_context_sha256(validated)
    if reference is None:
        return _unavailable_grade(
            binding,
            context_sha256=context_sha256,
            reason="reference_unavailable",
        )

    reference = ResolvedReferencePolicy.model_validate(
        reference.model_dump(mode="python")
    )
    if reference.context_sha256 != context_sha256:
        return _unavailable_grade(
            binding,
            context_sha256=context_sha256,
            reason="decision_context_mismatch",
            reference=reference,
        )
    if validated.table_action.action_type in WAGER_ACTIONS and (
        validated.table_action.total_committed is None
        or validated.state.blinds.big_blind is None
        or validated.state.blinds.big_blind <= 0
    ):
        return _unavailable_grade(
            binding,
            context_sha256=context_sha256,
            reason="decision_sizing_unverified",
            reference=reference,
        )
    if not _policy_lines_are_legal(validated, reference):
        return _unavailable_grade(
            binding,
            context_sha256=context_sha256,
            reason="reference_policy_illegal",
            reference=reference,
        )
    if not reference.policy_complete:
        return DecisionGrade(
            decision=binding,
            decision_context_sha256=context_sha256,
            grade_source="solved",
            classification="policy_incomplete",
            policy_grade_eligibility="ungraded",
            learning_eligibility="ineligible",
            reason="policy_incomplete",
            reference=reference,
            ev_unit=reference.ev_unit,
        )

    supported_lines = tuple(
        line
        for line in reference.policy_lines
        if _line_is_supported(line, reference)
    )
    matched_line = _matched_policy_line(validated, reference)
    if matched_line is None:
        return _gradeable_result(
            binding,
            context_sha256=context_sha256,
            reference=reference,
            supported_lines=supported_lines,
            matched_line=None,
            classification="mistake",
            reason="outside_policy_support",
        )
    if matched_line in supported_lines:
        return _gradeable_result(
            binding,
            context_sha256=context_sha256,
            reference=reference,
            supported_lines=supported_lines,
            matched_line=matched_line,
            classification="supported",
            reason="supported_policy_match",
        )
    return _gradeable_result(
        binding,
        context_sha256=context_sha256,
        reference=reference,
        supported_lines=supported_lines,
        matched_line=matched_line,
        classification="mistake",
        reason="policy_match_below_support",
    )


def _validated_decision(decision: HeroDecisionPoint) -> HeroDecisionPoint:
    return HeroDecisionPoint.model_validate(decision.model_dump(mode="python"))


def _line_is_supported(
    line: PolicyLine,
    reference: ResolvedReferencePolicy,
) -> bool:
    ev_cost = reference.ev_cost_for(line)
    return (
        line.frequency >= reference.minimum_supported_frequency
        or ev_cost <= reference.maximum_equivalent_ev_cost
    )


def _policy_lines_are_legal(
    decision: HeroDecisionPoint,
    reference: ResolvedReferencePolicy,
) -> bool:
    state = decision.state
    if state.betting_limit not in {"no_limit", "pot_limit"}:
        return False
    hero = next(seat for seat in state.seats if seat.position == state.hero_position)
    amount_to_call = state.amount_to_call
    for line in reference.policy_lines:
        if line.action == "fold":
            if amount_to_call <= 0:
                return False
            continue
        if line.action == "check":
            if amount_to_call != 0:
                return False
            continue
        if line.action == "call":
            if amount_to_call <= 0 or hero.stack_before_action <= 0:
                return False
            continue
        if not state.raise_reopened:
            return False
        if line.action == "bet" and state.current_wager != 0:
            return False
        if line.action == "raise" and state.current_wager == 0:
            return False
        if not _wager_line_is_legal(line, decision):
            return False
    return True


def _wager_line_is_legal(
    line: PolicyLine,
    decision: HeroDecisionPoint,
) -> bool:
    state = decision.state
    hero = next(seat for seat in state.seats if seat.position == state.hero_position)
    big_blind = state.blinds.big_blind
    assert line.total_committed_bb is not None
    if big_blind is None or big_blind <= 0:
        return False
    total_committed = line.total_committed_bb * big_blind
    maximum_total = hero.street_commitment + hero.stack_before_action
    if total_committed > maximum_total:
        return False
    if state.betting_limit == "pot_limit":
        maximum_wager_addition = (
            state.pot_before_action + state.amount_to_call * 2
        )
        if total_committed > hero.street_commitment + maximum_wager_addition:
            return False

    if line.action == "bet":
        minimum_increment = state.last_full_wager_increment or big_blind
        minimum_total = hero.street_commitment + minimum_increment
    else:
        if state.last_full_wager_increment is None:
            return False
        dead_commitment = hero.street_commitment - hero.live_commitment
        minimum_total = (
            dead_commitment
            + state.current_wager
            + state.last_full_wager_increment
        )
    return total_committed >= minimum_total or total_committed == maximum_total


def _matched_policy_line(
    decision: HeroDecisionPoint,
    reference: ResolvedReferencePolicy,
) -> PolicyLine | None:
    action = decision.table_action.action_type
    candidates = [line for line in reference.policy_lines if line.action == action]
    if action not in WAGER_ACTIONS:
        return candidates[0] if candidates else None

    total_committed = decision.table_action.total_committed
    big_blind = decision.state.blinds.big_blind
    if total_committed is None or big_blind is None or big_blind <= 0:
        return None
    tolerance = reference.sizing_tolerance_bb * big_blind
    matches = [
        line
        for line in candidates
        if line.total_committed_bb is not None
        and abs(line.total_committed_bb * big_blind - total_committed) <= tolerance
    ]
    return matches[0] if len(matches) == 1 else None


def _unavailable_grade(
    binding: DecisionBinding,
    *,
    context_sha256: str,
    reason: GradeReason,
    reference: ResolvedReferencePolicy | None = None,
) -> DecisionGrade:
    return DecisionGrade(
        decision=binding,
        decision_context_sha256=context_sha256,
        grade_source="heuristic",
        classification="reference_unavailable",
        policy_grade_eligibility="ungraded",
        learning_eligibility="ineligible",
        reason=reason,
        reference=reference,
    )


def _gradeable_result(
    binding: DecisionBinding,
    *,
    context_sha256: str,
    reference: ResolvedReferencePolicy,
    supported_lines: tuple[PolicyLine, ...],
    matched_line: PolicyLine | None,
    classification: GradeClassification,
    reason: GradeReason,
) -> DecisionGrade:
    return DecisionGrade(
        decision=binding,
        decision_context_sha256=context_sha256,
        grade_source="solved",
        classification=classification,
        policy_grade_eligibility="gradeable",
        learning_eligibility="requires_content_activation",
        reason=reason,
        reference=reference,
        supported_policy_lines=supported_lines,
        matched_policy_line=matched_line,
        ev_cost=(
            reference.ev_cost_for(matched_line)
            if matched_line is not None
            else None
        ),
        ev_unit=reference.ev_unit,
    )
