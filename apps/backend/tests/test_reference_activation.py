from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.application.learning_evidence import (
    LearningContentReadyGrade,
    prepare_grade_for_content_activation,
)
from app.application.learning_content_catalog import LearningContentCatalog
from app.application.reference_activation import (
    CoverageBand,
    ReferenceActivation,
    ReferenceActivatedGrade,
    ReferenceActivationCatalog,
    ReferenceActivationError,
    ReferenceSeriesBinding,
    activate_reference_series,
    bind_grade_to_active_reference,
    revalidate_reference_activated_grade,
)
from app.domain.grading import grade_decision
from app.domain.imported_hands import extract_hero_decision_points
from app.domain.learning_content import (
    DecisionSelector,
    LearningReferencePolicyBinding,
    PrincipleLifecycleEvent,
    append_principle_lifecycle_event,
)
from test_grading import action_decision, reference, source_qualification
from test_imported_hand_decisions import (
    baseline_decision_record,
    hero_fold_decision_record,
)
from test_learning_content import approved_record, draft_record
from test_learning_content_readiness import readiness_fixture


ACTIVATED_AT = datetime(2026, 9, 4, 19, 0, tzinfo=timezone.utc)


def readiness() -> LearningContentReadyGrade:
    fixture = readiness_fixture()
    return prepare_grade_for_content_activation(
        fixture.decision,
        grade=fixture.grade,
        taxonomy=fixture.taxonomy,
        mapping=fixture.mapping,
        principles=fixture.principles,
    )


def solved_readiness(target, *, resolved=None) -> LearningContentReadyGrade:
    fixture = readiness_fixture()
    solved = resolved or reference(target)
    grade = grade_decision(
        target,
        reference=solved,
        source_qualification=source_qualification(solved),
    )
    assert grade.source_qualification is not None
    learning_binding = LearningReferencePolicyBinding.model_validate(
        grade.source_qualification.policy_binding.model_dump(mode="python")
    )
    return prepare_grade_for_content_activation(
        target,
        grade=grade,
        taxonomy=fixture.taxonomy,
        mapping=fixture.mapping,
        principles=(approved_record(reference_policy_binding=learning_binding),),
    )


def coverage_band(
    evidence: LearningContentReadyGrade,
    *,
    coverage_band_id: str = "cash.preflop.bb-defense.100bb",
    selector: DecisionSelector | None = None,
) -> CoverageBand:
    binding = evidence.reference_policy_binding
    decision = evidence.decision_snapshot.restore()
    return CoverageBand.define(
        coverage_band_id=coverage_band_id,
        definition_revision="coverage-band-v1",
        definition_pointer="coverage/cash-preflop-bb-defense-100bb.json",
        definition_sha256="b" * 64,
        selector=selector
        or DecisionSelector(
            street=decision.street,
            hero_position=decision.state.hero_position.display_label,
        ),
        coverage_revision=binding.coverage_revision,
        coverage_sha256=binding.coverage_sha256,
    )


def activate(
    catalog: ReferenceActivationCatalog,
    evidence: LearningContentReadyGrade,
    *,
    band: CoverageBand | None = None,
    activation_id: str = "activation-1",
    mastery_series_id: str = "mastery-series-1",
) -> ReferenceActivationCatalog:
    return activate_reference_series(
        catalog,
        evidence,
        band or coverage_band(evidence),
        activation_id=activation_id,
        mastery_series_id=mastery_series_id,
        activated_at=ACTIVATED_AT,
    )


def rewrite_activation(
    activation: ReferenceActivation,
    **changes: object,
) -> ReferenceActivation:
    candidate = activation.model_copy(
        update={**changes, "activation_sha256": "0" * 64}
    )
    return candidate.model_copy(
        update={"activation_sha256": candidate.semantic_digest()}
    )


def current_learning_content(
    evidence: LearningContentReadyGrade,
    *,
    catalog_id: str = "learning-content-catalog",
) -> LearningContentCatalog:
    empty = LearningContentCatalog.empty(catalog_id)
    return LearningContentCatalog(
        catalog_id=catalog_id,
        catalog_revision=1,
        predecessor_catalog_sha256=empty.semantic_digest(),
        taxonomy_lineage=(evidence.taxonomy,),
        mapping_lineage=(evidence.mapping,),
        principles=evidence.approved_principles,
    )


def test_activation_binds_only_the_exact_catalog_snapshot_series() -> None:
    evidence = readiness()
    band = coverage_band(evidence)
    empty = ReferenceActivationCatalog.empty("learning-reference-catalog")

    catalog = activate(empty, evidence, band=band)
    eligible = bind_grade_to_active_reference(
        catalog,
        evidence,
        coverage_band_id=band.coverage_band_id,
    )

    assert empty.catalog_revision == 0
    assert empty.activations == ()
    assert catalog.catalog_revision == 1
    assert catalog.active_activation_ids == ("activation-1",)
    activation = catalog.activations[0]
    assert activation.concept_id == evidence.tagging.tag.concept_id
    assert activation.coverage_band == band
    assert activation.reference_series == ReferenceSeriesBinding.from_reference(
        evidence.reference_policy_binding
    )
    assert activation.activation_reference_binding == (
        evidence.reference_policy_binding
    )
    assert activation.approved_principles == evidence.approved_principles
    assert activation.source_qualification == evidence.grade.source_qualification
    assert eligible.reference_activation == "active_in_catalog_snapshot"
    assert eligible.learning_eligibility == (
        "requires_current_catalog_hand_and_content"
    )
    assert eligible.readiness.learning_eligibility == (
        "requires_reference_activation"
    )
    assert eligible.catalog_sha256 == catalog.semantic_digest()
    assert eligible.activation_id == activation.activation_id
    assert eligible.mastery_series_id == activation.mastery_series_id


def test_revalidation_reproduces_current_hand_reference_and_content() -> None:
    evidence = readiness()
    catalog = activate(ReferenceActivationCatalog.empty("catalog"), evidence)
    retained = bind_grade_to_active_reference(
        catalog,
        evidence,
        coverage_band_id="cash.preflop.bb-defense.100bb",
    )
    extraction = extract_hero_decision_points(baseline_decision_record())

    result = revalidate_reference_activated_grade(
        retained,
        current_reference_catalog=catalog,
        current_learning_content=current_learning_content(evidence),
        active_hand_decisions=extraction,
    )

    assert result == retained
    assert result.learning_eligibility == (
        "requires_current_catalog_hand_and_content"
    )
    with pytest.raises(ReferenceActivationError, match="not published"):
        revalidate_reference_activated_grade(
            retained,
            current_reference_catalog=catalog,
            current_learning_content=LearningContentCatalog.empty(
                "learning-content-catalog"
            ),
            active_hand_decisions=extraction,
        )


def test_revalidation_rejects_any_current_reference_catalog_change() -> None:
    evidence = readiness()
    first = activate(ReferenceActivationCatalog.empty("catalog"), evidence)
    retained = bind_grade_to_active_reference(
        first,
        evidence,
        coverage_band_id="cash.preflop.bb-defense.100bb",
    )
    other_evidence = solved_readiness(action_decision("raise"))
    current = activate(
        first,
        other_evidence,
        band=coverage_band(
            other_evidence,
            coverage_band_id="cash.preflop.bb-defense.40bb",
        ),
        activation_id="activation-2",
        mastery_series_id="mastery-series-2",
    )

    with pytest.raises(ReferenceActivationError, match="current reference catalog"):
        revalidate_reference_activated_grade(
            retained,
            current_reference_catalog=current,
            current_learning_content=current_learning_content(evidence),
            active_hand_decisions=extract_hero_decision_points(
                baseline_decision_record()
            ),
        )


def test_revalidation_requires_the_exact_current_active_decision() -> None:
    evidence = readiness()
    catalog = activate(ReferenceActivationCatalog.empty("catalog"), evidence)
    retained = bind_grade_to_active_reference(
        catalog,
        evidence,
        coverage_band_id="cash.preflop.bb-defense.100bb",
    )

    with pytest.raises(ReferenceActivationError, match="current active hand"):
        revalidate_reference_activated_grade(
            retained,
            current_reference_catalog=catalog,
            current_learning_content=current_learning_content(evidence),
            active_hand_decisions=extract_hero_decision_points(
                hero_fold_decision_record()
            ),
        )


def test_revalidation_accepts_irrelevant_draft_content_but_rejects_retirement(
) -> None:
    evidence = readiness()
    catalog = activate(ReferenceActivationCatalog.empty("catalog"), evidence)
    retained = bind_grade_to_active_reference(
        catalog,
        evidence,
        coverage_band_id="cash.preflop.bb-defense.100bb",
    )
    first_content = current_learning_content(evidence)
    unrelated_draft = draft_record(
        principle_id="zz-unpublished-guidance",
        reference_policy_binding=LearningReferencePolicyBinding.model_validate(
            evidence.reference_policy_binding.model_dump(mode="python")
        ),
    )
    current_with_draft = LearningContentCatalog(
        catalog_id=first_content.catalog_id,
        catalog_revision=2,
        predecessor_catalog_sha256=first_content.semantic_digest(),
        taxonomy_lineage=first_content.taxonomy_lineage,
        mapping_lineage=first_content.mapping_lineage,
        principles=(*first_content.principles, unrelated_draft),
    )
    extraction = extract_hero_decision_points(baseline_decision_record())

    assert revalidate_reference_activated_grade(
        retained,
        current_reference_catalog=catalog,
        current_learning_content=current_with_draft,
        active_hand_decisions=extraction,
    ) == retained

    retired = append_principle_lifecycle_event(
        evidence.approved_principles[0],
        PrincipleLifecycleEvent(
            sequence=2,
            status="retired",
            actor_kind="human",
            actor_id="reviewer-1",
            occurred_at=ACTIVATED_AT + timedelta(minutes=1),
        ),
    )
    retired_content = LearningContentCatalog(
        catalog_id=first_content.catalog_id,
        catalog_revision=2,
        predecessor_catalog_sha256=first_content.semantic_digest(),
        taxonomy_lineage=first_content.taxonomy_lineage,
        mapping_lineage=first_content.mapping_lineage,
        principles=(retired,),
    )
    with pytest.raises(ReferenceActivationError, match="does not reproduce"):
        revalidate_reference_activated_grade(
            retained,
            current_reference_catalog=catalog,
            current_learning_content=retired_content,
            active_hand_decisions=extraction,
        )


def test_revalidation_requires_activation_principles_to_match_current_readiness(
) -> None:
    evidence = readiness()
    different_principle = approved_record(
        principle_id="alternative-guidance",
        reference_policy_binding=LearningReferencePolicyBinding.model_validate(
            evidence.reference_policy_binding.model_dump(mode="python")
        ),
    )
    activation_readiness = prepare_grade_for_content_activation(
        evidence.decision_snapshot.restore(),
        grade=evidence.grade,
        taxonomy=evidence.taxonomy,
        mapping=evidence.mapping,
        principles=(different_principle,),
    )
    catalog = activate(
        ReferenceActivationCatalog.empty("catalog"),
        activation_readiness,
    )
    retained = bind_grade_to_active_reference(
        catalog,
        evidence,
        coverage_band_id="cash.preflop.bb-defense.100bb",
    )

    with pytest.raises(ReferenceActivationError, match="approved content"):
        revalidate_reference_activated_grade(
            retained,
            current_reference_catalog=catalog,
            current_learning_content=current_learning_content(evidence),
            active_hand_decisions=extract_hero_decision_points(
                baseline_decision_record()
            ),
        )


def test_catalog_replacement_retains_audit_and_starts_a_separate_series() -> None:
    evidence = readiness()
    first = activate(ReferenceActivationCatalog.empty("catalog"), evidence)
    revised_band = coverage_band(evidence).model_copy(
        update={
            "definition_revision": "coverage-band-v2",
            "definition_pointer": "coverage/cash-preflop-bb-defense-100bb-v2.json",
            "definition_sha256": "c" * 64,
        }
    )

    second = activate(
        first,
        evidence,
        band=revised_band,
        activation_id="activation-2",
        mastery_series_id="mastery-series-2",
    )

    assert first.active_activation_ids == ("activation-1",)
    assert first.catalog_revision == 1
    assert second.catalog_revision == 2
    assert tuple(item.activation_id for item in second.activations) == (
        "activation-1",
        "activation-2",
    )
    assert second.active_activation_ids == ("activation-2",)
    assert second.activations[0] == first.activations[0]
    assert second.activations[0].mastery_series_id == "mastery-series-1"
    assert second.activations[1].mastery_series_id == "mastery-series-2"
    assert second.activations[0].coverage_band.definition_revision == (
        "coverage-band-v1"
    )
    assert second.activations[1].coverage_band == revised_band

    eligible = bind_grade_to_active_reference(
        second,
        evidence,
        coverage_band_id="cash.preflop.bb-defense.100bb",
    )
    assert eligible.activation_id == "activation-2"
    assert eligible.mastery_series_id == "mastery-series-2"


def test_distinct_coverage_bands_can_be_active_together() -> None:
    evidence = readiness()
    first = activate(ReferenceActivationCatalog.empty("catalog"), evidence)
    second_evidence = solved_readiness(action_decision("raise"))
    second_band = coverage_band(
        second_evidence,
        coverage_band_id="cash.preflop.bb-defense.40bb",
    )

    catalog = activate(
        first,
        second_evidence,
        band=second_band,
        activation_id="activation-2",
        mastery_series_id="mastery-series-2",
    )

    assert catalog.active_activation_ids == ("activation-1", "activation-2")
    assert catalog.active_for(
        concept_id=second_evidence.tagging.tag.concept_id,
        coverage_band_id="cash.preflop.bb-defense.100bb",
    ) == catalog.activations[0]
    assert catalog.active_for(
        concept_id=evidence.tagging.tag.concept_id,
        coverage_band_id="cash.preflop.bb-defense.40bb",
    ) == catalog.activations[1]


def test_activation_rejects_coverage_drift_and_reused_identities() -> None:
    evidence = readiness()
    empty = ReferenceActivationCatalog.empty("catalog")
    wrong_band = coverage_band(evidence).model_copy(
        update={"coverage_sha256": "f" * 64}
    )

    with pytest.raises(ReferenceActivationError, match="does not match"):
        activate(empty, evidence, band=wrong_band)

    nonmember_band = coverage_band(
        evidence,
        selector=DecisionSelector(street="flop"),
    )
    with pytest.raises(ReferenceActivationError, match="does not belong"):
        activate(empty, evidence, band=nonmember_band)

    forged_band_payload = coverage_band(evidence).model_dump(mode="python")
    forged_band_payload["selector_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="exact selector"):
        CoverageBand.model_validate(forged_band_payload)

    first = activate(empty, evidence)
    alias_band = coverage_band(
        evidence,
        coverage_band_id="cash.preflop.bb-defense.alias",
    )
    with pytest.raises(ReferenceActivationError, match="another active"):
        activate(
            first,
            evidence,
            band=alias_band,
            activation_id="activation-alias",
            mastery_series_id="mastery-series-alias",
        )
    with pytest.raises(ReferenceActivationError, match="activation id"):
        activate(
            first,
            evidence,
            activation_id="activation-1",
            mastery_series_id="mastery-series-2",
        )
    with pytest.raises(ReferenceActivationError, match="distinct mastery series"):
        activate(
            first,
            evidence,
            activation_id="activation-2",
            mastery_series_id="mastery-series-1",
        )
    with pytest.raises(ReferenceActivationError, match="canonical validation"):
        activate_reference_series(
            first,
            evidence,
            coverage_band(evidence),
            activation_id="activation-2",
            mastery_series_id="mastery-series-2",
            activated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
    assert first.active_activation_ids == ("activation-1",)


def test_catalog_contract_rejects_nonlatest_or_mixed_series_state() -> None:
    evidence = readiness()
    first = activate(ReferenceActivationCatalog.empty("catalog"), evidence)
    second = activate(
        first,
        evidence,
        activation_id="activation-2",
        mastery_series_id="mastery-series-2",
    )

    payload = second.model_dump(mode="python")
    payload["active_activation_ids"] = ("activation-1",)
    with pytest.raises(ValidationError, match="latest activation"):
        ReferenceActivationCatalog.model_validate(payload)

    payload = second.model_dump(mode="python")
    activations = list(payload["activations"])
    activations[1]["mastery_series_id"] = "mastery-series-1"
    payload["activations"] = tuple(activations)
    with pytest.raises(ValidationError, match="semantic digest"):
        ReferenceActivationCatalog.model_validate(payload)

    rewritten = rewrite_activation(
        second.activations[1],
        mastery_series_id="mastery-series-1",
    )
    payload = second.model_dump(mode="python")
    activations = list(payload["activations"])
    activations[1] = rewritten.model_dump(mode="python")
    payload["activations"] = tuple(activations)
    with pytest.raises(ValidationError, match="distinct mastery series"):
        ReferenceActivationCatalog.model_validate(payload)

    payload = second.model_dump(mode="python")
    activations = list(payload["activations"])
    activations[1] = rewrite_activation(
        second.activations[1],
        sequence=3,
    ).model_dump(mode="python")
    payload["activations"] = tuple(activations)
    with pytest.raises(ValidationError, match="contiguous"):
        ReferenceActivationCatalog.model_validate(payload)


def test_activation_contract_revalidates_human_review_and_reference_binding() -> None:
    catalog = activate(ReferenceActivationCatalog.empty("catalog"), readiness())
    payload = catalog.activations[0].model_dump(mode="python")
    payload["approved_principles"][0]["lifecycle"] = payload[
        "approved_principles"
    ][0]["lifecycle"][:1]
    with pytest.raises(ValidationError, match="human-approved"):
        ReferenceActivation.model_validate(payload)

    payload = catalog.activations[0].model_dump(mode="python")
    payload["activation_reference_binding"]["policy_revision"] = "policy-other"
    with pytest.raises(ValidationError, match="qualified local reference source"):
        ReferenceActivation.model_validate(payload)

    payload = catalog.activations[0].model_dump(mode="python")
    payload["source_qualification"]["status"] = "staged"
    with pytest.raises(ValidationError, match="qualified local reference source"):
        ReferenceActivation.model_validate(payload)


def test_binding_rejects_reference_or_mapping_drift() -> None:
    first_evidence = readiness()
    catalog = activate(
        ReferenceActivationCatalog.empty("catalog"),
        first_evidence,
    )
    fixture = readiness_fixture()
    next_reference = reference(fixture.decision).model_copy(
        update={"policy_revision": "policy-2026.10.1"}
    )
    next_grade = grade_decision(
        fixture.decision,
        reference=next_reference,
        source_qualification=source_qualification(next_reference),
    )
    assert next_grade.source_qualification is not None
    next_learning_binding = LearningReferencePolicyBinding.model_validate(
        next_grade.source_qualification.policy_binding.model_dump(mode="python")
    )
    next_evidence = prepare_grade_for_content_activation(
        fixture.decision,
        grade=next_grade,
        taxonomy=fixture.taxonomy,
        mapping=fixture.mapping,
        principles=(
            approved_record(reference_policy_binding=next_learning_binding),
        ),
    )

    with pytest.raises(ReferenceActivationError, match="no matching active"):
        bind_grade_to_active_reference(
            catalog,
            next_evidence,
            coverage_band_id="cash.preflop.bb-defense.100bb",
        )

    next_mapping = fixture.mapping.model_copy(
        update={"mapping_revision": "mapping-2026.10"}
    )
    remapped_evidence = prepare_grade_for_content_activation(
        fixture.decision,
        grade=fixture.grade,
        taxonomy=fixture.taxonomy,
        mapping=next_mapping,
        principles=fixture.principles,
    )
    with pytest.raises(ReferenceActivationError, match="no matching active"):
        bind_grade_to_active_reference(
            catalog,
            remapped_evidence,
            coverage_band_id="cash.preflop.bb-defense.100bb",
        )

    changed_concepts = tuple(
        concept.model_copy(
            update={"testable_definition": "Materially changed under a reused ID."}
        )
        if concept.concept_id == first_evidence.tagging.tag.concept_id
        else concept
        for concept in fixture.taxonomy.concepts
    )
    changed_taxonomy = fixture.taxonomy.model_copy(
        update={"concepts": changed_concepts}
    )
    retagged_evidence = prepare_grade_for_content_activation(
        fixture.decision,
        grade=fixture.grade,
        taxonomy=changed_taxonomy,
        mapping=fixture.mapping,
        principles=fixture.principles,
    )
    with pytest.raises(ReferenceActivationError, match="no matching active"):
        bind_grade_to_active_reference(
            catalog,
            retagged_evidence,
            coverage_band_id="cash.preflop.bb-defense.100bb",
        )

    changed_rules = tuple(
        rule.model_copy(update={"rule_id": f"{rule.rule_id}-reused-revision"})
        for rule in fixture.mapping.rules
    )
    changed_mapping = fixture.mapping.model_copy(update={"rules": changed_rules})
    remapped_same_revision = prepare_grade_for_content_activation(
        fixture.decision,
        grade=fixture.grade,
        taxonomy=fixture.taxonomy,
        mapping=changed_mapping,
        principles=fixture.principles,
    )
    with pytest.raises(ReferenceActivationError, match="no matching active"):
        bind_grade_to_active_reference(
            catalog,
            remapped_same_revision,
            coverage_band_id="cash.preflop.bb-defense.100bb",
        )


def test_binding_keeps_route_and_context_evidence_decision_specific() -> None:
    first_evidence = readiness()
    catalog = activate(
        ReferenceActivationCatalog.empty("catalog"),
        first_evidence,
    )
    fixture = readiness_fixture()
    other_state = fixture.decision.state.model_copy(
        update={"hero_cards": list(reversed(fixture.decision.state.hero_cards))}
    )
    other_decision = fixture.decision.model_copy(update={"state": other_state})
    other_reference = reference(other_decision).model_copy(
        update={
            "route_binding_id": "route.preflop.bb-defense.variant",
            "route_binding_revision": "binding-v2",
        }
    )
    other_evidence = solved_readiness(
        other_decision,
        resolved=other_reference,
    )

    activated = bind_grade_to_active_reference(
        catalog,
        other_evidence,
        coverage_band_id="cash.preflop.bb-defense.100bb",
    )

    assert (
        activated.readiness.reference_policy_binding
        != activated.catalog.activations[0].activation_reference_binding
    )
    assert ReferenceSeriesBinding.from_reference(
        activated.readiness.reference_policy_binding
    ) == activated.catalog.activations[0].reference_series


def test_eligibility_contract_rejects_stale_or_forged_catalog_evidence() -> None:
    evidence = readiness()
    first = activate(ReferenceActivationCatalog.empty("catalog"), evidence)
    eligible = bind_grade_to_active_reference(
        first,
        evidence,
        coverage_band_id="cash.preflop.bb-defense.100bb",
    )
    second = activate(
        first,
        evidence,
        activation_id="activation-2",
        mastery_series_id="mastery-series-2",
    )

    payload = eligible.model_dump(mode="python")
    payload["catalog"] = second.model_dump(mode="python")
    payload["catalog_sha256"] = second.semantic_digest()
    with pytest.raises(ValidationError, match="active activation and series"):
        ReferenceActivatedGrade.model_validate(payload)

    payload = eligible.model_dump(mode="python")
    payload["catalog_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="exact catalog"):
        ReferenceActivatedGrade.model_validate(payload)

    rewritten_activation = first.activations[0].model_copy(
        update={"mastery_series_id": "rewritten-series"}
    )
    rewritten_catalog = first.model_copy(
        update={"activations": (rewritten_activation,)}
    )
    with pytest.raises(ReferenceActivationError, match="canonical validation"):
        bind_grade_to_active_reference(
            rewritten_catalog,
            evidence,
            coverage_band_id="cash.preflop.bb-defense.100bb",
        )

    noncanonical_mapping = evidence.mapping.model_copy(
        update={"predecessor_mapping_revision": " prior-mapping "}
    )
    noncanonical_readiness = evidence.model_copy(
        update={"mapping": noncanonical_mapping}
    )
    with pytest.raises(ValidationError, match="readiness must be canonical"):
        ReferenceActivatedGrade(
            readiness=noncanonical_readiness,
            catalog=first,
            catalog_sha256=first.semantic_digest(),
            coverage_band_id="cash.preflop.bb-defense.100bb",
            activation_id="activation-1",
            mastery_series_id="mastery-series-1",
        )


def test_activation_and_binding_reject_forged_readiness_instances() -> None:
    evidence = readiness()
    forged = evidence.model_copy(update={"readiness": "not-ready"})
    empty = ReferenceActivationCatalog.empty("catalog")

    with pytest.raises(ReferenceActivationError, match="readiness"):
        activate(empty, forged)

    catalog = activate(empty, evidence)
    with pytest.raises(ReferenceActivationError, match="readiness"):
        bind_grade_to_active_reference(
            catalog,
            forged,
            coverage_band_id="cash.preflop.bb-defense.100bb",
        )
