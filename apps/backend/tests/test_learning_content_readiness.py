from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.application.learning_evidence import (
    LearningContentReadinessError,
    LearningContentReadyGrade,
    prepare_grade_for_content_activation,
)
from app.domain.grading import (
    DecisionGrade,
    ReferencePolicyQualificationBinding,
    grade_decision,
)
from app.domain.imported_hands import HeroDecisionPoint
from app.domain.learning_content import (
    ConceptMappingRevision,
    LearningContentActivationCheck,
    LearningReferencePolicyBinding,
    PrincipleRecord,
    TaxonomyRevision,
)
from test_grading import decision, line, qualified_grade, reference
from test_learning_content import (
    approved_record,
    draft_record,
    mapping,
    matching_rule,
    taxonomy,
)


@dataclass(frozen=True)
class ReadinessFixture:
    decision: HeroDecisionPoint
    grade: DecisionGrade
    taxonomy: TaxonomyRevision
    mapping: ConceptMappingRevision
    principles: tuple[PrincipleRecord, ...]


def readiness_fixture() -> ReadinessFixture:
    target = decision()
    resolved = reference(target)
    grade = qualified_grade(target, resolved)
    assert grade.source_qualification is not None
    reference_policy_binding = LearningReferencePolicyBinding.model_validate(
        grade.source_qualification.policy_binding.model_dump(mode="python")
    )
    return ReadinessFixture(
        decision=target,
        grade=grade,
        taxonomy=taxonomy(),
        mapping=mapping(matching_rule()),
        principles=(
            approved_record(
                reference_policy_binding=reference_policy_binding,
            ),
            draft_record(
                principle_id="draft-guidance",
                principle_revision="draft-v1",
                reference_policy_binding=reference_policy_binding,
            ),
        ),
    )


def prepare(fixture: ReadinessFixture) -> LearningContentReadyGrade:
    return prepare_grade_for_content_activation(
        fixture.decision,
        grade=fixture.grade,
        taxonomy=fixture.taxonomy,
        mapping=fixture.mapping,
        principles=fixture.principles,
    )


def test_readiness_retains_complete_grade_content_and_approval_provenance() -> None:
    fixture = readiness_fixture()

    result = prepare(fixture)

    assert result.readiness == "content_ready"
    assert result.learning_eligibility == "requires_reference_activation"
    assert result.decision == fixture.decision
    assert result.grade == fixture.grade
    assert result.taxonomy == fixture.taxonomy
    assert result.mapping == fixture.mapping
    assert result.tagging.tag is not None
    assert result.activation.allowed
    assert len(result.approved_principles) == 1
    approved = result.approved_principles[0]
    assert approved.current_status == "approved"
    assert approved.lifecycle[-1].actor_kind == "human"
    assert approved.lifecycle[-1].actor_id == "reviewer-1"
    assert approved.lifecycle[-1].review_basis is not None
    assert result.grade.reference is not None
    assert result.grade.source_qualification is not None
    assert result.reference_policy_binding == (
        result.grade.source_qualification.policy_binding
    )
    assert result.reference_policy_binding == (
        ReferencePolicyQualificationBinding.from_reference(result.grade.reference)
    )
    assert result.grade.learning_eligibility == "requires_content_activation"


def test_learning_reference_binding_stays_aligned_with_grading() -> None:
    assert set(LearningReferencePolicyBinding.model_fields) == set(
        ReferencePolicyQualificationBinding.model_fields
    )


def test_readiness_rejects_an_ungradeable_or_incomplete_grade() -> None:
    fixture = readiness_fixture()
    heuristic = grade_decision(
        fixture.decision,
        reference=None,
        source_qualification=None,
    )
    incomplete_reference = reference(
        fixture.decision,
        policy_complete=False,
        lines=(line("call", "0.60", None),),
    )
    incomplete = qualified_grade(fixture.decision, incomplete_reference)

    for ungradeable in (heuristic, incomplete):
        with pytest.raises(
            LearningContentReadinessError,
            match="gradeable solved policy comparison",
        ):
            prepare_grade_for_content_activation(
                fixture.decision,
                grade=ungradeable,
                taxonomy=fixture.taxonomy,
                mapping=fixture.mapping,
                principles=fixture.principles,
            )


def test_readiness_rejects_an_absent_primary_concept() -> None:
    fixture = readiness_fixture()

    with pytest.raises(
        LearningContentReadinessError,
        match="supported primary concept",
    ):
        prepare_grade_for_content_activation(
            fixture.decision,
            grade=fixture.grade,
            taxonomy=fixture.taxonomy,
            mapping=mapping(),
            principles=fixture.principles,
        )


def test_readiness_rejects_a_grade_for_another_decision_revision() -> None:
    fixture = readiness_fixture()
    other_decision = fixture.decision.model_copy(
        update={"decision_index": fixture.decision.decision_index + 1}
    )

    with pytest.raises(
        LearningContentReadinessError,
        match="same canonical binding",
    ):
        prepare_grade_for_content_activation(
            other_decision,
            grade=fixture.grade,
            taxonomy=fixture.taxonomy,
            mapping=fixture.mapping,
            principles=fixture.principles,
        )


def test_readiness_rejects_a_grade_for_another_decision_context() -> None:
    fixture = readiness_fixture()
    other_state = fixture.decision.state.model_copy(
        update={"hero_cards": list(reversed(fixture.decision.state.hero_cards))}
    )
    other_decision = fixture.decision.model_copy(update={"state": other_state})

    with pytest.raises(
        LearningContentReadinessError,
        match="same grading context",
    ):
        prepare_grade_for_content_activation(
            other_decision,
            grade=fixture.grade,
            taxonomy=fixture.taxonomy,
            mapping=fixture.mapping,
            principles=fixture.principles,
        )


def test_readiness_rejects_a_grade_for_another_selected_action() -> None:
    fixture = readiness_fixture()
    hero = next(
        seat
        for seat in fixture.decision.state.seats
        if seat.position == fixture.decision.state.hero_position
    )
    other_action = fixture.decision.table_action.model_copy(
        update={
            "action_type": "fold",
            "amount": None,
            "total_committed": hero.street_commitment,
            "all_in": False,
        }
    )
    other_decision = fixture.decision.model_copy(
        update={"table_action": other_action}
    )

    with pytest.raises(
        LearningContentReadinessError,
        match="derived from the retained canonical decision",
    ):
        prepare_grade_for_content_activation(
            other_decision,
            grade=fixture.grade,
            taxonomy=fixture.taxonomy,
            mapping=fixture.mapping,
            principles=fixture.principles,
        )


def test_readiness_rejects_missing_or_wrong_policy_principle_coverage() -> None:
    fixture = readiness_fixture()
    wrong_policy_binding = (
        fixture.principles[0].principle.reference_policy_binding.model_copy(
            update={"policy_revision": "policy-v2"}
        )
    )
    wrong_policy = approved_record(
        reference_policy_binding=wrong_policy_binding,
    )

    for principles in ((), (wrong_policy,)):
        with pytest.raises(
            LearningContentReadinessError,
            match="approved coverage for every affected concept",
        ):
            prepare_grade_for_content_activation(
                fixture.decision,
                grade=fixture.grade,
                taxonomy=fixture.taxonomy,
                mapping=fixture.mapping,
                principles=principles,
            )


def test_readiness_rejects_principles_bound_to_another_reference_identity() -> None:
    fixture = readiness_fixture()
    different_reference = (
        fixture.principles[0].principle.reference_policy_binding.model_copy(
            update={
                "reference_revision": "reference-2026.10",
                "tolerance_revision": "tolerance-2026.10",
                "maximum_equivalent_ev_cost": Decimal("0.03"),
            }
        )
    )
    mismatched = approved_record(
        reference_policy_binding=different_reference,
    )

    with pytest.raises(
        LearningContentReadinessError,
        match="approved coverage for every affected concept",
    ):
        prepare_grade_for_content_activation(
            fixture.decision,
            grade=fixture.grade,
            taxonomy=fixture.taxonomy,
            mapping=fixture.mapping,
            principles=(mismatched,),
        )


def test_readiness_scopes_coverage_to_the_recomputed_primary_concept() -> None:
    fixture = readiness_fixture()
    primary_rule = matching_rule()
    secondary_concept = fixture.taxonomy.concepts[0].model_copy(
        update={
            "concept_id": "postflop.flop-defense",
            "definition_revision": "flop-definition-v1",
            "contexts": ("flop", "facing-wager"),
            "testable_definition": "Choose a response to a flop wager.",
        }
    )
    expanded_taxonomy = fixture.taxonomy.model_copy(
        update={
            "concepts": (*fixture.taxonomy.concepts, secondary_concept),
        }
    )
    secondary_rule = primary_rule.model_copy(
        update={
            "rule_id": "flop-defense",
            "concept_id": secondary_concept.concept_id,
            "selector": primary_rule.selector.model_copy(update={"street": "flop"}),
        }
    )
    expanded_mapping = fixture.mapping.model_copy(
        update={"rules": (primary_rule, secondary_rule)}
    )

    result = prepare_grade_for_content_activation(
        fixture.decision,
        grade=fixture.grade,
        taxonomy=expanded_taxonomy,
        mapping=expanded_mapping,
        principles=fixture.principles,
    )

    assert result.tagging.tag is not None
    assert result.activation.affected_concept_ids == (
        result.tagging.tag.concept_id,
    )
    assert result.activation.allowed


def test_readiness_validates_principle_identity_collisions_before_selection() -> None:
    fixture = readiness_fixture()
    active = fixture.principles[0]
    other_binding = active.principle.reference_policy_binding.model_copy(
        update={"reference_revision": "reference-2026.10"}
    )
    conflicting = approved_record(
        reference_policy_binding=other_binding,
        content="Conflicting content under the same principle revision.",
    )

    with pytest.raises(
        LearningContentReadinessError,
        match="learning content inputs are not compatible",
    ):
        prepare_grade_for_content_activation(
            fixture.decision,
            grade=fixture.grade,
            taxonomy=fixture.taxonomy,
            mapping=fixture.mapping,
            principles=(active, conflicting),
        )


def test_readiness_rejects_unapproved_principle_evidence() -> None:
    fixture = readiness_fixture()
    unapproved = fixture.principles[0].model_copy(
        update={"lifecycle": fixture.principles[0].lifecycle[:1]}
    )

    with pytest.raises(
        LearningContentReadinessError,
        match="approved coverage for every affected concept",
    ):
        prepare_grade_for_content_activation(
            fixture.decision,
            grade=fixture.grade,
            taxonomy=fixture.taxonomy,
            mapping=fixture.mapping,
            principles=(unapproved,),
        )


def test_readiness_contract_rejects_a_forged_full_policy_binding() -> None:
    result = prepare(readiness_fixture())
    payload = result.model_dump(mode="python")
    payload["reference_policy_binding"]["policy_revision"] = "policy-v2"

    with pytest.raises(ValidationError, match="exact qualification binding"):
        LearningContentReadyGrade.model_validate(payload)


def test_readiness_contract_recomputes_grade_for_the_retained_action() -> None:
    result = prepare(readiness_fixture())
    hero = next(
        seat
        for seat in result.decision.state.seats
        if seat.position == result.decision.state.hero_position
    )
    other_action = result.decision.table_action.model_copy(
        update={
            "action_type": "fold",
            "amount": None,
            "total_committed": hero.street_commitment,
            "all_in": False,
        }
    )
    other_decision = result.decision.model_copy(
        update={"table_action": other_action}
    )
    payload = result.model_dump(mode="python")
    payload["decision"] = other_decision.model_dump(mode="python")

    with pytest.raises(ValidationError, match="derived from the retained"):
        LearningContentReadyGrade.model_validate(payload)


def test_readiness_contract_binds_each_principle_to_the_exact_reference() -> None:
    result = prepare(readiness_fixture())
    payload = result.model_dump(mode="python")
    payload["approved_principles"][0]["principle"]["reference_policy_binding"][
        "reference_revision"
    ] = "reference-2026.10"

    with pytest.raises(ValidationError, match="must be derived"):
        LearningContentReadyGrade.model_validate(payload)


def test_readiness_contract_recomputes_definition_and_mapping_provenance() -> None:
    result = prepare(readiness_fixture())
    payload = result.model_dump(mode="python")
    payload["tagging"]["tag"]["concept_definition_revision"] = "definition-v2"
    payload["tagging"]["tag"]["matched_rule_id"] = "invented-rule"

    with pytest.raises(ValidationError, match="must be derived"):
        LearningContentReadyGrade.model_validate(payload)


def test_readiness_contract_recomputes_activation_from_principle_records() -> None:
    result = prepare(readiness_fixture())
    payload = result.model_dump(mode="python")
    payload["activation"]["eligible_principles"][0][
        "principle_semantic_digest"
    ] = "f" * 64

    with pytest.raises(ValidationError, match="must be derived"):
        LearningContentReadyGrade.model_validate(payload)


def test_readiness_contract_revalidates_nested_grade_snapshots() -> None:
    result = prepare(readiness_fixture())
    payload = result.model_dump(mode="python")
    payload["grade"]["grade_source"] = "heuristic"

    with pytest.raises(ValidationError, match="must be solved"):
        LearningContentReadyGrade.model_validate(payload)


def test_activation_check_requires_canonical_complete_coverage() -> None:
    result = prepare(readiness_fixture())
    payload = result.activation.model_dump(mode="python")
    payload["affected_concept_ids"] = (
        "preflop.big-blind-defense",
        "preflop.big-blind-defense",
    )
    with pytest.raises(ValidationError, match="sorted and unique"):
        LearningContentActivationCheck.model_validate(payload)

    payload = result.activation.model_dump(mode="python")
    payload["missing_concept_ids"] = ("preflop.big-blind-defense",)
    with pytest.raises(ValidationError, match="exactly describe uncovered"):
        LearningContentActivationCheck.model_validate(payload)

    payload = result.activation.model_dump(mode="python")
    payload["eligible_principles"][0]["principle_semantic_digest"] = "not-a-digest"
    with pytest.raises(ValidationError, match="String should match pattern"):
        LearningContentActivationCheck.model_validate(payload)


def test_content_ready_grade_does_not_publish_mastery_or_drill_state() -> None:
    result = prepare(readiness_fixture())

    assert result.learning_eligibility != "eligible"
    assert not hasattr(result, "mastery")
    assert not hasattr(result, "drill")
