from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.grading import (
    DecisionGrade,
    PolicyLine,
    ReferenceBenchmarkEvidence,
    ReferenceBenchmarkOutcome,
    ReferenceDeliveryMode,
    ReferenceEvidence,
    ReferencePolicyQualificationBinding,
    ReferenceQualificationStatus,
    ReferenceRight,
    ReferenceRightsEvidence,
    ReferenceSourceQualification,
    ResolvedReferencePolicy,
    decision_grading_context_sha256,
    grade_decision,
)
from app.domain.imported_hands import HeroDecisionPoint, extract_hero_decision_points
from test_imported_hand_decisions import (
    baseline_decision_record,
    full_raise_decision_record,
    hero_fold_decision_record,
)
from test_imported_hand_models import ante_decision_record, multi_street_decision_record


def decision():
    extraction = extract_hero_decision_points(baseline_decision_record())
    assert extraction.outcome == "decisions"
    return extraction.decision_points[0]


def wager_decision():
    extraction = extract_hero_decision_points(multi_street_decision_record())
    assert extraction.outcome == "decisions"
    return extraction.decision_points[1]


def action_decision(action: str):
    records = {
        "fold": hero_fold_decision_record,
        "check": full_raise_decision_record,
        "raise": full_raise_decision_record,
    }
    extraction = extract_hero_decision_points(records[action]())
    assert extraction.outcome == "decisions"
    return next(
        point
        for point in extraction.decision_points
        if point.table_action.action_type == action
    )


def line(
    action: str,
    frequency: str,
    expected_value: str | None,
    *,
    total_committed_bb: str | None = None,
) -> PolicyLine:
    return PolicyLine(
        action=action,
        total_committed_bb=(
            Decimal(total_committed_bb)
            if total_committed_bb is not None
            else None
        ),
        frequency=Decimal(frequency),
        expected_value=(
            Decimal(expected_value) if expected_value is not None else None
        ),
    )


def reference(
    target,
    *,
    lines: tuple[PolicyLine, ...] | None = None,
    policy_complete: bool = True,
    context_sha256: str | None = None,
    minimum_supported_frequency: str = "0.05",
    maximum_equivalent_ev_cost: str = "0.02",
    sizing_tolerance_bb: str = "0.05",
) -> ResolvedReferencePolicy:
    return ResolvedReferencePolicy(
        reference_revision="reference-2026.09",
        policy_revision="policy-2026.09.1",
        tolerance_revision="tolerance-2026.09",
        reference_evidence_sha256="1" * 64,
        policy_artifact_sha256="2" * 64,
        coverage_revision="coverage-2026.09",
        coverage_sha256="6" * 64,
        route_binding_id="route.preflop.bb-defense",
        route_binding_revision="binding-v1",
        context_sha256=(
            context_sha256 or decision_grading_context_sha256(target)
        ),
        engine_id="verified-solver",
        engine_revision="solver-2026.09",
        engine_configuration_sha256="3" * 64,
        economic_model="cash-rake",
        economic_model_revision="cash-rake-v1",
        economic_configuration_sha256="4" * 64,
        utility_model="cash-ev",
        utility_model_revision="cash-ev-v1",
        utility_configuration_sha256="5" * 64,
        ev_unit="bb",
        policy_complete=policy_complete,
        minimum_supported_frequency=Decimal(minimum_supported_frequency),
        maximum_equivalent_ev_cost=Decimal(maximum_equivalent_ev_cost),
        sizing_tolerance_bb=Decimal(sizing_tolerance_bb),
        policy_lines=lines
        or (
            line("call", "0.60", "0"),
            line("raise", "0.40", "-0.03", total_committed_bb="3"),
        ),
    )


def source_qualification(
    resolved: ResolvedReferencePolicy,
    *,
    status: ReferenceQualificationStatus = "qualified",
    benchmark_outcome: ReferenceBenchmarkOutcome = "passed",
    delivery_mode: ReferenceDeliveryMode = "shipped_static_lookup",
    bound_reference: ResolvedReferencePolicy | None = None,
    grants: tuple[ReferenceRight, ...] | None = None,
) -> ReferenceSourceQualification:
    bound = bound_reference or resolved
    completed_benchmark = benchmark_outcome != "pending"
    rights = grants or (
        (
            "commercial_use",
            "embedding",
            "redistribution",
            "updates",
        )
        if delivery_mode == "shipped_static_lookup"
        else (
            "commercial_use",
            "commercial_serving",
            "derived_outputs",
        )
    )
    return ReferenceSourceQualification(
        qualification_revision="qualification-2026.09",
        status=status,
        assessed_at=datetime(2026, 9, 4, tzinfo=timezone.utc),
        assessor_id="reviewer.poker-and-rights",
        source_id="independent-solver-source",
        source_revision="source-2026.09",
        source_artifact_sha256="7" * 64,
        source_configuration_sha256="8" * 64,
        qualification_evidence=ReferenceEvidence(
            revision="qualification-dossier-v1",
            pointer="dossier/qualification-v1.json",
            sha256="9" * 64,
        ),
        independent_solved_evidence=ReferenceEvidence(
            revision="independent-review-v1",
            pointer="dossier/independent-review-v1.json",
            sha256="a" * 64,
        ),
        coverage_evidence=ReferenceEvidence(
            revision=bound.coverage_revision,
            pointer="dossier/coverage-v1.json",
            sha256=bound.coverage_sha256,
        ),
        rights=ReferenceRightsEvidence(
            basis="licensed",
            delivery_mode=delivery_mode,
            grants=rights,
            evidence=ReferenceEvidence(
                revision="rights-v1",
                pointer="dossier/rights-v1.pdf",
                sha256="b" * 64,
            ),
        ),
        benchmark=ReferenceBenchmarkEvidence(
            suite_revision="reference-benchmark-v5",
            threshold_revision="reference-thresholds-v1",
            outcome=benchmark_outcome,
            evidence=(
                ReferenceEvidence(
                    revision="benchmark-run-v1",
                    pointer="dossier/benchmark-run-v1.json",
                    sha256="c" * 64,
                )
                if completed_benchmark
                else None
            ),
        ),
        policy_binding=ReferencePolicyQualificationBinding.from_reference(bound),
    )


def qualified_grade(
    target: HeroDecisionPoint,
    resolved: ResolvedReferencePolicy,
) -> DecisionGrade:
    return grade_decision(
        target,
        reference=resolved,
        source_qualification=source_qualification(resolved),
    )


def test_missing_reference_is_heuristic_and_cannot_enter_learning() -> None:
    result = grade_decision(
        decision(),
        reference=None,
        source_qualification=None,
    )

    assert result.grade_source == "heuristic"
    assert result.classification == "reference_unavailable"
    assert result.policy_grade_eligibility == "ungraded"
    assert result.learning_eligibility == "ineligible"
    assert result.reason == "reference_unavailable"
    assert result.reference is None
    assert result.ev_cost is None
    assert result.ev_unit is None


def test_source_qualification_cannot_exist_without_its_reference() -> None:
    target = decision()
    resolved = reference(target)

    with pytest.raises(ValueError, match="without a reference"):
        grade_decision(
            target,
            reference=None,
            source_qualification=source_qualification(resolved),
        )


def test_unqualified_reference_is_heuristic_and_cannot_enter_learning() -> None:
    target = decision()
    resolved = reference(target)

    result = grade_decision(
        target,
        reference=resolved,
        source_qualification=None,
    )

    assert result.grade_source == "heuristic"
    assert result.classification == "reference_unavailable"
    assert result.reason == "reference_source_unqualified"
    assert result.reference == resolved
    assert result.source_qualification is None
    assert result.policy_grade_eligibility == "ungraded"
    assert result.learning_eligibility == "ineligible"


@pytest.mark.parametrize(
    ("status", "benchmark_outcome"),
    [
        ("staged", "passed"),
        ("rejected", "passed"),
        ("rejected", "failed"),
    ],
)
def test_nonqualified_source_status_remains_ungraded(
    status: ReferenceQualificationStatus,
    benchmark_outcome: ReferenceBenchmarkOutcome,
) -> None:
    target = decision()
    resolved = reference(target)
    qualification = source_qualification(
        resolved,
        status=status,
        benchmark_outcome=benchmark_outcome,
    )

    result = grade_decision(
        target,
        reference=resolved,
        source_qualification=qualification,
    )

    assert result.grade_source == "heuristic"
    assert result.reason == "reference_source_unqualified"
    assert result.reference == resolved
    assert result.source_qualification == qualification
    assert result.policy_grade_eligibility == "ungraded"
    assert result.learning_eligibility == "ineligible"


def test_qualified_source_requires_a_passed_benchmark() -> None:
    resolved = reference(decision())

    with pytest.raises(ValidationError, match="requires a passed benchmark"):
        source_qualification(
            resolved,
            status="qualified",
            benchmark_outcome="pending",
        )


def test_completed_benchmark_requires_immutable_evidence() -> None:
    with pytest.raises(ValidationError, match="completed evidence must be retained"):
        ReferenceBenchmarkEvidence(
            suite_revision="reference-benchmark-v5",
            threshold_revision="reference-thresholds-v1",
            outcome="passed",
            evidence=None,
        )


def test_qualification_coverage_must_match_its_policy_binding() -> None:
    qualification = source_qualification(reference(decision()))
    payload = qualification.model_dump(mode="python")
    payload["coverage_evidence"]["sha256"] = "d" * 64

    with pytest.raises(ValidationError, match="coverage evidence must match"):
        ReferenceSourceQualification.model_validate(payload)


@pytest.mark.parametrize(
    ("delivery_mode", "grants", "missing"),
    [
        (
            "shipped_static_lookup",
            ("commercial_use", "embedding", "updates"),
            "redistribution",
        ),
        (
            "server_side_feed",
            ("commercial_use", "commercial_serving"),
            "derived_outputs",
        ),
    ],
)
def test_source_qualification_rejects_rights_for_the_wrong_delivery_mode(
    delivery_mode: ReferenceDeliveryMode,
    grants: tuple[ReferenceRight, ...],
    missing: str,
) -> None:
    with pytest.raises(ValidationError, match=f"missing grants: {missing}"):
        source_qualification(
            reference(decision()),
            delivery_mode=delivery_mode,
            grants=grants,
        )


def test_remote_source_cannot_grade_without_lookup_delivery_provenance() -> None:
    target = decision()
    resolved = reference(target)
    qualification = source_qualification(
        resolved,
        delivery_mode="server_side_feed",
    )

    result = grade_decision(
        target,
        reference=resolved,
        source_qualification=qualification,
    )

    assert result.grade_source == "heuristic"
    assert result.reason == "reference_delivery_unverified"
    assert result.reference == resolved
    assert result.source_qualification == qualification
    assert result.policy_grade_eligibility == "ungraded"
    assert result.learning_eligibility == "ineligible"


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("reference_revision", "reference-other"),
        ("policy_revision", "policy-other"),
        ("tolerance_revision", "tolerance-other"),
        ("reference_evidence_sha256", "d" * 64),
        ("policy_artifact_sha256", "e" * 64),
        ("policy_complete", False),
        ("policy_lines", (line("fold", "1", "0"),)),
        ("coverage_revision", "coverage-other"),
        ("coverage_sha256", "f" * 64),
        ("route_binding_id", "route.other"),
        ("route_binding_revision", "binding-other"),
        ("context_sha256", "0" * 64),
        ("engine_id", "other-solver"),
        ("engine_revision", "solver-other"),
        ("engine_configuration_sha256", "d" * 64),
        ("economic_model", "other-economics"),
        ("economic_model_revision", "economics-other"),
        ("economic_configuration_sha256", "e" * 64),
        ("utility_model", "other-utility"),
        ("utility_model_revision", "utility-other"),
        ("utility_configuration_sha256", "f" * 64),
        ("ev_unit", "currency"),
        ("minimum_supported_frequency", Decimal("0.10")),
        ("maximum_equivalent_ev_cost", Decimal("0.03")),
        ("sizing_tolerance_bb", Decimal("0.06")),
    ],
)
def test_source_qualification_must_bind_the_exact_policy_identity(
    field_name: str,
    replacement: object,
) -> None:
    target = decision()
    resolved = reference(target)
    bound_payload = resolved.model_dump(mode="python")
    bound_payload[field_name] = replacement
    differently_bound = ResolvedReferencePolicy.model_validate(bound_payload)
    qualification = source_qualification(
        resolved,
        bound_reference=differently_bound,
    )

    result = grade_decision(
        target,
        reference=resolved,
        source_qualification=qualification,
    )

    assert result.grade_source == "heuristic"
    assert result.reason == "reference_qualification_mismatch"
    assert result.reference == resolved
    assert result.source_qualification == qualification
    assert result.policy_grade_eligibility == "ungraded"
    assert result.learning_eligibility == "ineligible"


def test_context_mismatch_fails_closed_without_losing_attempted_reference() -> None:
    target = decision()
    attempted = reference(target, context_sha256="f" * 64)

    result = qualified_grade(target, attempted)

    assert result.grade_source == "heuristic"
    assert result.classification == "reference_unavailable"
    assert result.reason == "decision_context_mismatch"
    assert result.reference == attempted
    assert result.policy_grade_eligibility == "ungraded"
    assert result.learning_eligibility == "ineligible"


def test_context_binding_does_not_hash_the_action_being_graded() -> None:
    call_decision = decision()
    fold_payload = call_decision.model_dump(mode="python")
    fold_payload["table_action"].update(
        {
            "action_type": "fold",
            "amount": None,
            "total_committed": Decimal("0.5"),
            "all_in": False,
        }
    )
    fold_decision = HeroDecisionPoint.model_validate(fold_payload)

    assert (
        decision_grading_context_sha256(call_decision)
        == decision_grading_context_sha256(fold_decision)
    )


def test_incomplete_solved_policy_remains_visible_but_ungraded() -> None:
    target = decision()
    incomplete = reference(
        target,
        policy_complete=False,
        lines=(line("call", "0.60", None),),
    )

    result = qualified_grade(target, incomplete)

    assert result.grade_source == "solved"
    assert result.classification == "policy_incomplete"
    assert result.reason == "policy_incomplete"
    assert result.policy_grade_eligibility == "ungraded"
    assert result.learning_eligibility == "ineligible"
    assert result.reference == incomplete
    assert result.ev_unit == "bb"
    assert result.ev_cost is None


def test_incomplete_policy_with_an_illegal_line_fails_closed() -> None:
    target = decision()
    incomplete = reference(
        target,
        policy_complete=False,
        lines=(line("check", "0.60", None),),
    )

    result = qualified_grade(target, incomplete)

    assert result.grade_source == "heuristic"
    assert result.classification == "reference_unavailable"
    assert result.reason == "reference_policy_illegal"
    assert result.policy_grade_eligibility == "ungraded"


def test_incomplete_wager_policy_still_requires_verified_bb_sizing() -> None:
    target = wager_decision()
    payload = target.model_dump(mode="python")
    payload["state"]["blinds"]["big_blind"] = None
    target = HeroDecisionPoint.model_validate(payload)
    incomplete = reference(
        target,
        policy_complete=False,
        lines=(line("bet", "0.60", None, total_committed_bb="2"),),
    )

    result = qualified_grade(target, incomplete)

    assert result.grade_source == "heuristic"
    assert result.classification == "reference_unavailable"
    assert result.reason == "decision_sizing_unverified"
    assert result.policy_grade_eligibility == "ungraded"


def test_supported_mixed_policy_action_is_not_a_mistake() -> None:
    target = decision()
    solved = reference(target)

    result = qualified_grade(target, solved)

    assert result.classification == "supported"
    assert result.reason == "supported_policy_match"
    assert result.matched_policy_line == solved.policy_lines[0]
    assert result.matched_policy_line.frequency == Decimal("0.60")
    assert result.ev_cost == Decimal(0)
    assert result.policy_grade_eligibility == "gradeable"
    assert result.learning_eligibility == "requires_content_activation"


@pytest.mark.parametrize(
    ("action", "total_committed_bb"),
    [("fold", None), ("check", None), ("raise", "3")],
)
def test_supported_policy_matches_other_action_shapes(
    action: str,
    total_committed_bb: str | None,
) -> None:
    target = action_decision(action)
    solved = reference(
        target,
        lines=(
            line(
                action,
                "1",
                "0",
                total_committed_bb=total_committed_bb,
            ),
        ),
    )

    result = qualified_grade(target, solved)

    assert result.classification == "supported"
    assert result.matched_policy_line == solved.policy_lines[0]


def test_low_frequency_ev_equivalent_action_is_supported() -> None:
    target = decision()
    solved = reference(
        target,
        lines=(
            line("call", "0.01", "-0.01"),
            line("fold", "0.99", "0"),
        ),
        minimum_supported_frequency="0.05",
        maximum_equivalent_ev_cost="0.01",
    )

    result = qualified_grade(target, solved)

    assert result.classification == "supported"
    assert result.matched_policy_line == solved.policy_lines[0]
    assert result.ev_cost == Decimal("0.01")


def test_low_frequency_materially_costly_action_is_a_mistake() -> None:
    target = decision()
    solved = reference(
        target,
        lines=(
            line("call", "0.01", "-0.20"),
            line("fold", "0.99", "0"),
        ),
    )

    result = qualified_grade(target, solved)

    assert result.classification == "mistake"
    assert result.reason == "policy_match_below_support"
    assert result.matched_policy_line == solved.policy_lines[0]
    assert result.ev_cost == Decimal("0.20")
    assert result.ev_unit == "bb"


def test_action_outside_complete_policy_is_a_unit_pinned_mistake() -> None:
    target = decision()
    solved = reference(
        target,
        lines=(line("fold", "1", "0"),),
    )

    result = qualified_grade(target, solved)

    assert result.classification == "mistake"
    assert result.reason == "outside_policy_support"
    assert result.matched_policy_line is None
    assert result.ev_cost is None
    assert result.ev_unit == "bb"


@pytest.mark.parametrize(
    "illegal_line",
    [
        line("check", "1", "0"),
        line("bet", "1", "0", total_committed_bb="3"),
    ],
)
def test_illegal_reference_action_fails_closed(
    illegal_line: PolicyLine,
) -> None:
    target = decision()
    solved = reference(target, lines=(illegal_line,))

    result = qualified_grade(target, solved)

    assert result.grade_source == "heuristic"
    assert result.classification == "reference_unavailable"
    assert result.reason == "reference_policy_illegal"
    assert result.policy_grade_eligibility == "ungraded"
    assert result.learning_eligibility == "ineligible"
    assert result.reference == solved


def test_reference_wager_beyond_the_hero_stack_fails_closed() -> None:
    target = wager_decision()
    solved = reference(
        target,
        lines=(
            line("bet", "1", "0", total_committed_bb="1000000"),
        ),
    )

    result = qualified_grade(target, solved)

    assert result.grade_source == "heuristic"
    assert result.classification == "reference_unavailable"
    assert result.reason == "reference_policy_illegal"
    assert result.policy_grade_eligibility == "ungraded"


def test_reference_wager_beyond_the_pot_limit_cap_fails_closed() -> None:
    target = wager_decision()
    payload = target.model_dump(mode="python")
    payload["state"]["betting_limit"] = "pot_limit"
    target = HeroDecisionPoint.model_validate(payload)
    solved = reference(
        target,
        lines=(line("bet", "1", "0", total_committed_bb="3"),),
    )

    result = qualified_grade(target, solved)

    assert result.grade_source == "heuristic"
    assert result.classification == "reference_unavailable"
    assert result.reason == "reference_policy_illegal"
    assert result.policy_grade_eligibility == "ungraded"


def test_reference_raise_minimum_includes_the_hero_dead_ante() -> None:
    extraction = extract_hero_decision_points(ante_decision_record())
    assert extraction.outcome == "decisions"
    target = extraction.decision_points[0]
    solved = reference(
        target,
        lines=(line("raise", "1", "0", total_committed_bb="2"),),
    )

    result = qualified_grade(target, solved)

    assert result.grade_source == "heuristic"
    assert result.classification == "reference_unavailable"
    assert result.reason == "reference_policy_illegal"
    assert result.policy_grade_eligibility == "ungraded"


def test_wager_sizing_matches_inside_the_strict_tolerance_boundary() -> None:
    target = wager_decision()
    solved = reference(
        target,
        lines=(line("bet", "1", "0", total_committed_bb="2.049"),),
        sizing_tolerance_bb="0.05",
    )

    result = qualified_grade(target, solved)

    assert result.classification == "supported"
    assert result.matched_policy_line == solved.policy_lines[0]


def test_wager_sizing_at_the_exact_tolerance_boundary_is_not_a_match() -> None:
    target = wager_decision()
    solved = reference(
        target,
        lines=(line("bet", "1", "0", total_committed_bb="2.05"),),
        sizing_tolerance_bb="0.05",
    )

    result = qualified_grade(target, solved)

    assert result.classification == "mistake"
    assert result.reason == "outside_policy_support"
    assert result.matched_policy_line is None


def test_wager_sizing_outside_tolerance_is_a_mistake() -> None:
    target = wager_decision()
    solved = reference(
        target,
        lines=(line("bet", "1", "0", total_committed_bb="2.06"),),
        sizing_tolerance_bb="0.05",
    )

    result = qualified_grade(target, solved)

    assert result.classification == "mistake"
    assert result.reason == "outside_policy_support"
    assert result.matched_policy_line is None


def test_unverified_wager_normalization_fails_closed() -> None:
    target = wager_decision()
    payload = target.model_dump(mode="python")
    payload["state"]["blinds"]["big_blind"] = None
    target = HeroDecisionPoint.model_validate(payload)
    solved = reference(
        target,
        lines=(line("bet", "1", "0", total_committed_bb="2"),),
    )

    result = qualified_grade(target, solved)

    assert result.grade_source == "heuristic"
    assert result.classification == "reference_unavailable"
    assert result.reason == "decision_sizing_unverified"
    assert result.policy_grade_eligibility == "ungraded"
    assert result.learning_eligibility == "ineligible"


@pytest.mark.parametrize(
    ("lines", "complete", "expected_error"),
    [
        (
            (line("call", "0.5", "0"), line("call", "0.5", "-0.1")),
            True,
            "identities must be unique",
        ),
        (
            (line("call", "0.8", "0"),),
            True,
            "frequencies must sum to one",
        ),
        (
            (line("call", "0.5", "0"), line("fold", "0.5", None)),
            True,
            "candidate EVs must cover every line or none",
        ),
        (
            (
                line("bet", "0.5", "0", total_committed_bb="2"),
                line("bet", "0.5", "-0.1", total_committed_bb="2.05"),
            ),
            True,
            "must not have overlapping sizing tolerances",
        ),
    ],
)
def test_reference_policy_rejects_ambiguous_or_incomplete_claims(
    lines: tuple[PolicyLine, ...],
    complete: bool,
    expected_error: str,
) -> None:
    with pytest.raises(ValidationError, match=expected_error):
        reference(decision(), lines=lines, policy_complete=complete)


def test_reference_policy_allows_sizes_exactly_two_tolerances_apart() -> None:
    target = wager_decision()

    solved = reference(
        target,
        lines=(
            line("bet", "0.5", "0", total_committed_bb="2"),
            line("bet", "0.5", "-0.1", total_committed_bb="2.1"),
        ),
        sizing_tolerance_bb="0.05",
    )

    assert len(solved.policy_lines) == 2


def test_reference_policy_rejects_zero_sizing_tolerance() -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        reference(decision(), sizing_tolerance_bb="0")


@pytest.mark.parametrize(
    ("kwargs", "expected_error"),
    [
        (
            {
                "action": "bet",
                "frequency": Decimal(1),
                "expected_value": Decimal(0),
            },
            "require total_committed_bb",
        ),
        (
            {
                "action": "call",
                "total_committed_bb": Decimal(1),
                "frequency": Decimal(1),
                "expected_value": Decimal(0),
            },
            "only bet and raise",
        ),
    ],
)
def test_policy_line_rejects_invalid_sizing_shapes(
    kwargs: dict[str, object],
    expected_error: str,
) -> None:
    with pytest.raises(ValidationError, match=expected_error):
        PolicyLine(**kwargs)


def test_grade_preserves_decision_and_reference_provenance() -> None:
    target = decision()
    solved = reference(target)
    qualification = source_qualification(solved)

    result = grade_decision(
        target,
        reference=solved,
        source_qualification=qualification,
    )

    assert result.decision.identity.site == target.identity.site
    assert result.decision.identity.source_hand_id == target.identity.source_hand_id
    assert result.decision.canonical_revision == target.canonical_revision
    assert result.decision.deletion_generation == target.deletion_generation
    assert result.decision.decision_index == target.decision_index
    assert result.decision_context_sha256 == solved.context_sha256
    assert result.reference == solved
    assert result.reference.reference_revision == "reference-2026.09"
    assert result.reference.policy_revision == "policy-2026.09.1"
    assert result.reference.tolerance_revision == "tolerance-2026.09"
    assert result.reference.economic_model_revision == "cash-rake-v1"
    assert result.reference.utility_model_revision == "cash-ev-v1"
    assert result.source_qualification == qualification
    assert result.source_qualification.qualification_revision == (
        "qualification-2026.09"
    )
    assert result.source_qualification.policy_binding.matches(solved)
    assert tuple(
        policy_line.expected_value for policy_line in result.reference.policy_lines
    ) == (Decimal("0"), Decimal("-0.03"))
    assert result.ev_cost == Decimal("0")


def test_grade_revalidates_the_complete_mutable_decision_graph() -> None:
    target = decision()
    target.state.action_history[0].actions.clear()

    with pytest.raises(ValidationError, match="action history shows"):
        grade_decision(
            target,
            reference=None,
            source_qualification=None,
        )


def test_grade_contract_has_no_aggregate_or_mastery_authorization_fields() -> None:
    target = decision()
    result = qualified_grade(target, reference(target))

    assert "mastery" not in type(result).model_fields
    assert "aggregate" not in type(result).model_fields
    assert "drill" not in type(result).model_fields
    assert result.learning_eligibility == "requires_content_activation"


def test_grade_model_rejects_a_supported_label_with_a_mistake_reason() -> None:
    target = decision()
    result = qualified_grade(target, reference(target))
    payload = result.model_dump(mode="python")
    payload["reason"] = "outside_policy_support"

    with pytest.raises(ValidationError, match="support reason"):
        DecisionGrade.model_validate(payload)


def test_grade_model_cannot_spoof_solved_without_source_qualification() -> None:
    target = decision()
    result = qualified_grade(target, reference(target))
    payload = result.model_dump(mode="python")
    payload["source_qualification"] = None

    with pytest.raises(ValidationError, match="exactly qualified local reference"):
        DecisionGrade.model_validate(payload)


def test_grade_model_requires_ev_cost_derived_from_retained_candidate_evs() -> None:
    target = decision()
    result = qualified_grade(target, reference(target))
    payload = result.model_dump(mode="python")
    payload["ev_cost"] = None

    with pytest.raises(ValidationError, match="derived from the retained candidate"):
        DecisionGrade.model_validate(payload)


def test_grade_model_rejects_context_mismatch_for_incomplete_policy() -> None:
    target = decision()
    result = qualified_grade(
        target,
        reference(
            target,
            policy_complete=False,
            lines=(line("call", "0.60", None),),
        ),
    )
    payload = result.model_dump(mode="python")
    payload["decision_context_sha256"] = "f" * 64

    with pytest.raises(ValidationError, match="incomplete solved evidence"):
        DecisionGrade.model_validate(payload)
