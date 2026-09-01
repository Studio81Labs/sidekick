"""Pure validation and selection services for versioned learning content."""

from __future__ import annotations

from pydantic import ValidationError

from app.domain.imported_hands import HeroDecisionPoint

from app.domain.learning_content.models import (
    EDUCATIONAL_GUIDANCE_PREFIX,
    ApprovedPrincipleBinding,
    ConceptMappingRevision,
    DecisionBinding,
    DecisionConceptTagging,
    LearningContentActivationCheck,
    PrimaryConceptTag,
    PrincipleCacheKey,
    PrincipleRecord,
    PrincipleReveal,
    TaxonomyRevision,
)


class LearningContentCompatibilityError(ValueError):
    """Two immutable learning-content revisions cannot be combined safely."""


class AmbiguousConceptMappingError(LearningContentCompatibilityError):
    """More than one primary-concept rule matched the same decision."""


class ApprovedPrincipleUnavailableError(LearningContentCompatibilityError):
    """A reveal requested a draft, inactive, or incompatible principle."""


def validate_taxonomy_successor(
    lineage: tuple[TaxonomyRevision, ...],
    candidate: TaxonomyRevision,
) -> None:
    """Protect identities and definitions across a complete taxonomy lineage."""

    if not lineage:
        raise LearningContentCompatibilityError(
            "taxonomy successor validation requires the complete active lineage"
        )
    revision_ids = tuple(revision.taxonomy_revision for revision in lineage)
    if len(set(revision_ids)) != len(revision_ids):
        raise LearningContentCompatibilityError(
            "taxonomy lineage revision identifiers must be unique"
        )
    root = lineage[0]
    if root.predecessor_taxonomy_revision is not None:
        raise LearningContentCompatibilityError(
            "a complete taxonomy lineage must begin at its root revision"
        )
    for earlier, later in zip(lineage, lineage[1:], strict=False):
        if later.series_id != root.series_id:
            raise LearningContentCompatibilityError(
                "a taxonomy lineage must remain in one concept series"
            )
        if later.predecessor_taxonomy_revision != earlier.taxonomy_revision:
            raise LearningContentCompatibilityError(
                "taxonomy lineage predecessor revisions must be contiguous"
            )

    previous = lineage[-1]
    if candidate.taxonomy_revision in revision_ids:
        raise LearningContentCompatibilityError(
            "a taxonomy successor must use a new revision identifier"
        )
    if candidate.series_id != previous.series_id:
        raise LearningContentCompatibilityError(
            "a taxonomy successor must remain in the same concept series"
        )
    if candidate.predecessor_taxonomy_revision != previous.taxonomy_revision:
        raise LearningContentCompatibilityError(
            "a taxonomy successor must pin the active predecessor revision"
        )
    historical_definitions = {}
    for revision in lineage:
        for concept in revision.concepts:
            key = (concept.concept_id, concept.definition_revision)
            historical = historical_definitions.get(key)
            if historical is not None and historical != concept:
                raise LearningContentCompatibilityError(
                    f"taxonomy lineage rewrites concept {concept.concept_id}"
                    f" definition revision {concept.definition_revision}"
                )
            historical_definitions[key] = concept
    for concept in candidate.concepts:
        prior = historical_definitions.get(
            (concept.concept_id, concept.definition_revision)
        )
        if prior is None:
            continue
        if concept != prior:
            raise LearningContentCompatibilityError(
                f"concept {concept.concept_id} changes an immutable definition"
                f" revision {concept.definition_revision}"
            )


def validate_mapping_successor(
    lineage: tuple[ConceptMappingRevision, ...],
    candidate: ConceptMappingRevision,
) -> None:
    """Protect identity and continuity across a complete mapping lineage."""

    if not lineage:
        raise LearningContentCompatibilityError(
            "mapping successor validation requires the complete active lineage"
        )
    revision_ids = tuple(revision.mapping_revision for revision in lineage)
    if len(set(revision_ids)) != len(revision_ids):
        raise LearningContentCompatibilityError(
            "mapping lineage revision identifiers must be unique"
        )
    root = lineage[0]
    if root.predecessor_mapping_revision is not None:
        raise LearningContentCompatibilityError(
            "a complete mapping lineage must begin at its root revision"
        )
    for earlier, later in zip(lineage, lineage[1:], strict=False):
        if later.predecessor_mapping_revision != earlier.mapping_revision:
            raise LearningContentCompatibilityError(
                "mapping lineage predecessor revisions must be contiguous"
            )

    previous = lineage[-1]
    if candidate.mapping_revision in revision_ids:
        raise LearningContentCompatibilityError(
            "a mapping successor must use a new revision identifier"
        )
    if candidate.predecessor_mapping_revision != previous.mapping_revision:
        raise LearningContentCompatibilityError(
            "a mapping successor must pin the active predecessor revision"
        )


def validate_mapping_revision(
    taxonomy: TaxonomyRevision,
    mapping: ConceptMappingRevision,
) -> None:
    """Require every mapping target to exist in its pinned taxonomy."""

    if mapping.taxonomy_revision != taxonomy.taxonomy_revision:
        raise LearningContentCompatibilityError(
            "mapping revision does not target the supplied taxonomy revision"
        )
    concept_ids = {concept.concept_id for concept in taxonomy.concepts}
    unknown = sorted(
        {rule.concept_id for rule in mapping.rules} - concept_ids
    )
    if unknown:
        raise LearningContentCompatibilityError(
            f"mapping rules target unknown concepts: {', '.join(unknown)}"
        )


def tag_primary_concept(
    decision: HeroDecisionPoint,
    *,
    taxonomy: TaxonomyRevision,
    mapping: ConceptMappingRevision,
) -> DecisionConceptTagging:
    """Map one canonical decision to zero or one primary concept."""

    validate_mapping_revision(taxonomy, mapping)
    binding = DecisionBinding.from_decision(decision)
    matched = tuple(rule for rule in mapping.rules if rule.selector.matches(decision))
    if not matched:
        return DecisionConceptTagging(
            decision=binding,
            absence_reason="no_matching_rule",
        )
    if len(matched) > 1:
        raise AmbiguousConceptMappingError(
            "multiple primary-concept rules matched decision"
            f" {binding.identity.site}/{binding.identity.source_hand_id}:"
            f"{binding.decision_index}:"
            f" {', '.join(rule.rule_id for rule in matched)}"
        )
    rule = matched[0]
    concept = taxonomy.concept(rule.concept_id)
    assert concept is not None
    tag = PrimaryConceptTag(
        decision=binding,
        concept_id=concept.concept_id,
        taxonomy_revision=taxonomy.taxonomy_revision,
        mapping_revision=mapping.mapping_revision,
        concept_definition_revision=concept.definition_revision,
        matched_rule_id=rule.rule_id,
    )
    return DecisionConceptTagging(decision=binding, tag=tag)


def evaluate_learning_content_activation(
    *,
    taxonomy: TaxonomyRevision,
    mapping: ConceptMappingRevision,
    reference_policy_revision: str,
    principles: tuple[PrincipleRecord, ...],
) -> LearningContentActivationCheck:
    """Gate activation on compatible approved principles for mapped concepts."""

    validate_mapping_revision(taxonomy, mapping)
    validated_principles = tuple(
        _validated_principle_record(record) for record in principles
    )
    principle_keys = [
        (
            record.principle.principle_id,
            record.principle.principle_revision,
        )
        for record in validated_principles
    ]
    if len(set(principle_keys)) != len(principle_keys):
        raise LearningContentCompatibilityError(
            "activation requires one current record per principle revision"
        )
    affected = tuple(sorted({rule.concept_id for rule in mapping.rules}))
    definitions = {
        concept.concept_id: concept.definition_revision
        for concept in taxonomy.concepts
    }
    eligible = {
        (
            record.principle.concept_id,
            record.principle.principle_id,
            record.principle.principle_revision,
        )
        for record in validated_principles
        if record.current_status == "approved"
        and record.principle.concept_id in affected
        and record.principle.taxonomy_revision == taxonomy.taxonomy_revision
        and record.principle.concept_definition_revision
        == definitions[record.principle.concept_id]
        and record.principle.reference_policy_revision
        == reference_policy_revision
    }
    eligible_bindings = tuple(
        ApprovedPrincipleBinding(
            concept_id=concept_id,
            principle_id=principle_id,
            principle_revision=principle_revision,
        )
        for concept_id, principle_id, principle_revision in sorted(eligible)
    )
    covered = {binding.concept_id for binding in eligible_bindings}
    return LearningContentActivationCheck(
        taxonomy_revision=taxonomy.taxonomy_revision,
        mapping_revision=mapping.mapping_revision,
        reference_policy_revision=reference_policy_revision,
        affected_concept_ids=affected,
        eligible_principles=eligible_bindings,
        missing_concept_ids=tuple(
            concept_id for concept_id in affected if concept_id not in covered
        ),
    )


def _require_approved_compatibility(
    tag: PrimaryConceptTag,
    *,
    reference_policy_revision: str,
    record: PrincipleRecord,
) -> PrincipleRecord:
    validated_record = _validated_principle_record(record)
    principle = validated_record.principle
    if validated_record.current_status != "approved":
        raise ApprovedPrincipleUnavailableError(
            "only a human-approved principle can be revealed or cached"
        )
    expected = (
        tag.concept_id,
        tag.taxonomy_revision,
        tag.concept_definition_revision,
        reference_policy_revision,
    )
    actual = (
        principle.concept_id,
        principle.taxonomy_revision,
        principle.concept_definition_revision,
        principle.reference_policy_revision,
    )
    if actual != expected:
        raise ApprovedPrincipleUnavailableError(
            "principle compatibility pins do not match the decision tag and"
            " reference policy"
        )
    return validated_record


def _validated_principle_record(record: PrincipleRecord) -> PrincipleRecord:
    """Revalidate a complete lifecycle graph at an approval trust boundary."""

    try:
        return PrincipleRecord.model_validate(record.model_dump(mode="python"))
    except ValidationError as error:
        raise LearningContentCompatibilityError(
            "principle record failed canonical validation"
        ) from error


def build_principle_reveal(
    tag: PrimaryConceptTag,
    *,
    reference_policy_revision: str,
    record: PrincipleRecord,
) -> PrincipleReveal:
    """Build a conditionally framed reveal with exact semantic provenance."""

    validated_record = _require_approved_compatibility(
        tag,
        reference_policy_revision=reference_policy_revision,
        record=record,
    )
    principle = validated_record.principle
    return PrincipleReveal(
        decision=tag.decision,
        concept_id=tag.concept_id,
        taxonomy_revision=tag.taxonomy_revision,
        mapping_revision=tag.mapping_revision,
        concept_definition_revision=tag.concept_definition_revision,
        reference_policy_revision=reference_policy_revision,
        principle_id=principle.principle_id,
        principle_revision=principle.principle_revision,
        display_text=f"{EDUCATIONAL_GUIDANCE_PREFIX}{principle.content}",
    )


def principle_cache_key(
    tag: PrimaryConceptTag,
    *,
    reference_policy_revision: str,
    record: PrincipleRecord,
) -> PrincipleCacheKey:
    """Return a cache key that changes with every semantic input revision."""

    validated_record = _require_approved_compatibility(
        tag,
        reference_policy_revision=reference_policy_revision,
        record=record,
    )
    principle = validated_record.principle
    return PrincipleCacheKey(
        concept_id=tag.concept_id,
        taxonomy_revision=tag.taxonomy_revision,
        mapping_revision=tag.mapping_revision,
        concept_definition_revision=tag.concept_definition_revision,
        reference_policy_revision=reference_policy_revision,
        principle_id=principle.principle_id,
        principle_revision=principle.principle_revision,
    )
