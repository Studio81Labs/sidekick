"""Prove solved grades have compatible reviewed content without activating them."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.domain.grading import (
    DecisionGrade,
    ReferencePolicyQualificationBinding,
    decision_grading_context_sha256,
    grade_decision,
)
from app.domain.imported_hands import (
    HeroDecisionPoint,
    imported_hand_canonical_json,
)
from app.domain.learning_content import (
    ApprovedPrincipleBinding,
    ConceptMappingRevision,
    DecisionBinding,
    DecisionConceptTagging,
    LearningContentActivationCheck,
    LearningReferencePolicyBinding,
    PrincipleRecord,
    TaxonomyRevision,
    evaluate_learning_content_activation,
    tag_primary_concept,
)


class LearningContentReadinessError(ValueError):
    """A grade cannot be proven ready for a future reference activation."""


class HeroDecisionSnapshot(BaseModel):
    """Deeply immutable canonical JSON snapshot of one validated decision."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    canonical_json: bytes

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        decision = _decision_from_canonical_json(self.canonical_json)
        if self.canonical_json != _canonical_decision_json(decision):
            raise ValueError("decision snapshot JSON must use canonical encoding")
        return self

    @classmethod
    def from_decision(cls, decision: HeroDecisionPoint) -> Self:
        decision = _validated_decision(decision)
        return cls(canonical_json=_canonical_decision_json(decision))

    def restore(self) -> HeroDecisionPoint:
        """Return a fresh mutable decision without exposing retained state."""

        return _decision_from_canonical_json(self.canonical_json)


class LearningContentReadyGrade(BaseModel):
    """Immutable evidence that one grade has compatible reviewed content.

    This artifact is not learning eligibility. A future authoritative catalog
    activation must still pin the concept and coverage band to one reference.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    decision_snapshot: HeroDecisionSnapshot
    grade: DecisionGrade
    taxonomy: TaxonomyRevision
    mapping: ConceptMappingRevision
    tagging: DecisionConceptTagging
    activation: LearningContentActivationCheck
    approved_principles: tuple[PrincipleRecord, ...]
    reference_policy_binding: ReferencePolicyQualificationBinding
    readiness: Literal["content_ready"] = "content_ready"
    learning_eligibility: Literal["requires_reference_activation"] = (
        "requires_reference_activation"
    )

    @model_validator(mode="after")
    def validate_readiness(self) -> Self:
        _revalidate_content_ready_grade(self)
        decision = self.decision_snapshot.restore()
        problem = _content_readiness_problem(
            decision=decision,
            grade=self.grade,
            tagging=self.tagging,
            activation=self.activation,
            reference_policy_binding=self.reference_policy_binding,
        )
        if problem is not None:
            raise ValueError(problem)
        assert self.grade.reference is not None

        expected_tagging = tag_primary_concept(
            decision,
            taxonomy=self.taxonomy,
            mapping=self.mapping,
        )
        if self.tagging != expected_tagging:
            raise ValueError(
                "concept tagging must be derived from the retained decision and"
                " content revisions"
            )
        assert expected_tagging.tag is not None
        expected_activation = evaluate_learning_content_activation(
            taxonomy=self.taxonomy,
            mapping=self.mapping,
            reference_policy_binding=_learning_reference_binding(
                self.reference_policy_binding
            ),
            affected_concept_ids=(expected_tagging.tag.concept_id,),
            principles=self.approved_principles,
        )
        if self.activation != expected_activation:
            raise ValueError(
                "content activation must be derived from the retained revisions"
                " and approved principle records"
            )
        if _principle_bindings(self.approved_principles) != (
            self.activation.eligible_principles
        ):
            raise ValueError(
                "retained approved principle records must exactly match the"
                " eligible activation bindings"
            )
        return self


def prepare_grade_for_content_activation(
    decision: HeroDecisionPoint,
    *,
    grade: DecisionGrade,
    taxonomy: TaxonomyRevision,
    mapping: ConceptMappingRevision,
    principles: tuple[PrincipleRecord, ...],
) -> LearningContentReadyGrade:
    """Recompute and retain compatible content evidence for one solved grade."""

    decision = _validated_decision(decision)
    decision_snapshot = HeroDecisionSnapshot.from_decision(decision)
    grade = _validated_grade(grade)
    taxonomy = _validated_taxonomy(taxonomy)
    mapping = _validated_mapping(mapping)
    validated_principles = tuple(
        _validated_principle(record) for record in principles
    )
    _require_grade_binding(decision, grade)
    assert grade.reference is not None
    assert grade.source_qualification is not None
    reference_policy_binding = grade.source_qualification.policy_binding
    learning_reference_policy_binding = _learning_reference_binding(
        reference_policy_binding
    )

    try:
        tagging = tag_primary_concept(
            decision,
            taxonomy=taxonomy,
            mapping=mapping,
        )
    except ValueError as exc:
        raise LearningContentReadinessError(
            "learning content inputs are not compatible"
        ) from exc

    if tagging.tag is None:
        raise LearningContentReadinessError(
            "content readiness requires one supported primary concept"
        )
    try:
        activation = evaluate_learning_content_activation(
            taxonomy=taxonomy,
            mapping=mapping,
            reference_policy_binding=learning_reference_policy_binding,
            affected_concept_ids=(tagging.tag.concept_id,),
            principles=validated_principles,
        )
    except ValueError as exc:
        raise LearningContentReadinessError(
            "learning content inputs are not compatible"
        ) from exc

    if not activation.allowed:
        raise LearningContentReadinessError(
            "content readiness requires approved coverage for every affected concept"
        )

    approved_principles = _eligible_principle_records(
        validated_principles,
        activation.eligible_principles,
    )
    problem = _content_readiness_problem(
        decision=decision,
        grade=grade,
        tagging=tagging,
        activation=activation,
        reference_policy_binding=reference_policy_binding,
    )
    if problem is not None:
        raise LearningContentReadinessError(problem)
    try:
        return LearningContentReadyGrade(
            decision_snapshot=decision_snapshot,
            grade=grade,
            taxonomy=taxonomy,
            mapping=mapping,
            tagging=tagging,
            activation=activation,
            approved_principles=approved_principles,
            reference_policy_binding=reference_policy_binding,
        )
    except ValidationError as exc:
        raise LearningContentReadinessError(
            "content-ready grade failed canonical validation"
        ) from exc


def _content_readiness_problem(
    *,
    decision: HeroDecisionPoint,
    grade: DecisionGrade,
    tagging: DecisionConceptTagging,
    activation: LearningContentActivationCheck,
    reference_policy_binding: ReferencePolicyQualificationBinding,
) -> str | None:
    if (
        grade.grade_source != "solved"
        or grade.policy_grade_eligibility != "gradeable"
        or grade.learning_eligibility != "requires_content_activation"
        or grade.reference is None
        or grade.source_qualification is None
    ):
        return "content readiness requires a gradeable solved policy comparison"
    if grade.decision != DecisionBinding.from_decision(decision):
        return "decision and grade must have the same canonical binding"
    if grade.decision_context_sha256 != decision_grading_context_sha256(decision):
        return "decision and grade must have the same grading context"
    expected_grade = grade_decision(
        decision,
        reference=grade.reference,
        source_qualification=grade.source_qualification,
    )
    if grade != expected_grade:
        return "decision grade must be derived from the retained canonical decision"
    expected_binding = ReferencePolicyQualificationBinding.from_reference(
        grade.reference
    )
    if (
        reference_policy_binding != expected_binding
        or reference_policy_binding
        != grade.source_qualification.policy_binding
    ):
        return "content readiness requires the grade's exact qualification binding"
    if tagging.tag is None:
        return "content readiness requires one supported primary concept"
    if tagging.decision != grade.decision:
        return "concept tagging and grade must bind the same canonical decision"
    if not activation.allowed:
        return "content readiness requires approved coverage for every affected concept"
    if (
        tagging.taxonomy_series_id,
        tagging.taxonomy_revision,
        tagging.mapping_revision,
    ) != (
        activation.taxonomy_series_id,
        activation.taxonomy_revision,
        activation.mapping_revision,
    ):
        return "concept tagging and content activation revisions must match"
    if activation.reference_policy_binding != _learning_reference_binding(
        reference_policy_binding
    ):
        return "content activation and grade reference bindings must match"
    if tagging.tag.concept_id not in activation.affected_concept_ids:
        return "the tagged concept must be covered by the content activation"
    return None


def _require_grade_binding(
    decision: HeroDecisionPoint,
    grade: DecisionGrade,
) -> None:
    if (
        grade.grade_source != "solved"
        or grade.policy_grade_eligibility != "gradeable"
        or grade.learning_eligibility != "requires_content_activation"
        or grade.reference is None
        or grade.source_qualification is None
    ):
        raise LearningContentReadinessError(
            "content readiness requires a gradeable solved policy comparison"
        )
    if grade.decision != DecisionBinding.from_decision(decision):
        raise LearningContentReadinessError(
            "decision and grade must have the same canonical binding"
        )
    if grade.decision_context_sha256 != decision_grading_context_sha256(decision):
        raise LearningContentReadinessError(
            "decision and grade must have the same grading context"
        )
    if grade != grade_decision(
        decision,
        reference=grade.reference,
        source_qualification=grade.source_qualification,
    ):
        raise LearningContentReadinessError(
            "decision grade must be derived from the retained canonical decision"
        )
    if grade.source_qualification.policy_binding != (
        ReferencePolicyQualificationBinding.from_reference(grade.reference)
    ):
        raise LearningContentReadinessError(
            "content readiness requires the grade's exact qualification binding"
        )


def _eligible_principle_records(
    principles: tuple[PrincipleRecord, ...],
    eligible: tuple[ApprovedPrincipleBinding, ...],
) -> tuple[PrincipleRecord, ...]:
    records_by_key = {
        _principle_key(_principle_binding(principle)): principle
        for principle in principles
        if principle.current_status == "approved"
    }
    return tuple(records_by_key[_principle_key(binding)] for binding in eligible)


def _principle_bindings(
    principles: tuple[PrincipleRecord, ...],
) -> tuple[ApprovedPrincipleBinding, ...]:
    return tuple(
        sorted(
            (_principle_binding(record) for record in principles),
            key=_principle_key,
        )
    )


def _principle_binding(
    record: PrincipleRecord,
) -> ApprovedPrincipleBinding:
    principle = record.principle
    return ApprovedPrincipleBinding(
        concept_id=principle.concept_id,
        principle_id=principle.principle_id,
        principle_revision=principle.principle_revision,
        principle_semantic_digest=principle.semantic_digest(),
    )


def _principle_key(
    binding: ApprovedPrincipleBinding,
) -> tuple[str, str, str, str]:
    return (
        binding.concept_id,
        binding.principle_id,
        binding.principle_revision,
        binding.principle_semantic_digest,
    )


def _revalidate_content_ready_grade(evidence: LearningContentReadyGrade) -> None:
    try:
        HeroDecisionSnapshot.model_validate(
            evidence.decision_snapshot.model_dump(mode="python")
        )
        _validated_grade(evidence.grade)
        _validated_taxonomy(evidence.taxonomy)
        _validated_mapping(evidence.mapping)
        DecisionConceptTagging.model_validate(
            evidence.tagging.model_dump(mode="python")
        )
        LearningContentActivationCheck.model_validate(
            evidence.activation.model_dump(mode="python")
        )
        for record in evidence.approved_principles:
            _validated_principle(record)
        ReferencePolicyQualificationBinding.model_validate(
            evidence.reference_policy_binding.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise ValueError("content-ready grade must retain canonical evidence") from exc


def _validated_decision(value: HeroDecisionPoint) -> HeroDecisionPoint:
    try:
        return HeroDecisionPoint.model_validate(value.model_dump(mode="python"))
    except (AttributeError, ValidationError) as exc:
        raise LearningContentReadinessError(
            "decision snapshot failed canonical validation"
        ) from exc


def _canonical_decision_json(decision: HeroDecisionPoint) -> bytes:
    return imported_hand_canonical_json(decision.model_dump(mode="json"))


def _decision_from_canonical_json(payload: bytes) -> HeroDecisionPoint:
    try:
        return HeroDecisionPoint.model_validate_json(payload)
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValueError("decision snapshot failed canonical validation") from exc


def _validated_grade(value: DecisionGrade) -> DecisionGrade:
    try:
        return DecisionGrade.model_validate(value.model_dump(mode="python"))
    except (AttributeError, ValidationError) as exc:
        raise LearningContentReadinessError(
            "decision grade snapshot failed canonical validation"
        ) from exc


def _validated_taxonomy(value: TaxonomyRevision) -> TaxonomyRevision:
    try:
        return TaxonomyRevision.model_validate(value.model_dump(mode="python"))
    except (AttributeError, ValidationError) as exc:
        raise LearningContentReadinessError(
            "taxonomy snapshot failed canonical validation"
        ) from exc


def _validated_mapping(value: ConceptMappingRevision) -> ConceptMappingRevision:
    try:
        return ConceptMappingRevision.model_validate(value.model_dump(mode="python"))
    except (AttributeError, ValidationError) as exc:
        raise LearningContentReadinessError(
            "mapping snapshot failed canonical validation"
        ) from exc


def _validated_principle(value: PrincipleRecord) -> PrincipleRecord:
    try:
        return PrincipleRecord.model_validate(value.model_dump(mode="python"))
    except (AttributeError, ValidationError) as exc:
        raise LearningContentReadinessError(
            "principle record failed canonical validation"
        ) from exc


def _learning_reference_binding(
    value: ReferencePolicyQualificationBinding,
) -> LearningReferencePolicyBinding:
    try:
        return LearningReferencePolicyBinding.model_validate(
            value.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise LearningContentReadinessError(
            "reference policy binding failed learning-content validation"
        ) from exc
