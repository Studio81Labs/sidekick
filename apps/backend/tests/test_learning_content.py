from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.imported_hands import extract_hero_decision_points
from app.domain.learning_content import (
    EDUCATIONAL_GUIDANCE_PREFIX,
    AmbiguousConceptMappingError,
    ApprovedPrincipleUnavailableError,
    ConceptDefinition,
    ConceptMappingRevision,
    ConceptMappingRule,
    DecimalRange,
    DecisionConceptTagging,
    DecisionSelector,
    LearningContentCompatibilityError,
    PrincipleLifecycleEvent,
    PrincipleRecord,
    PrincipleRevision,
    PositionStackSelector,
    RouteActionSelector,
    RouteStreetSelector,
    TaxonomyRevision,
    append_principle_lifecycle_event,
    build_principle_reveal,
    evaluate_learning_content_activation,
    principle_cache_key,
    principle_draft,
    tag_primary_concept,
    validate_mapping_revision,
    validate_mapping_successor,
    validate_taxonomy_successor,
)
from test_imported_hand_decisions import baseline_decision_record
from test_imported_hand_models import multi_street_decision_record


NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def decision():
    extraction = extract_hero_decision_points(baseline_decision_record())
    assert extraction.outcome == "decisions"
    return extraction.decision_points[0]


def taxonomy(
    *,
    revision: str = "taxonomy-v1",
    predecessor: str | None = None,
    definition_revision: str = "definition-v1",
    definition: str = "Choose a response to a preflop wager from the big blind.",
) -> TaxonomyRevision:
    return TaxonomyRevision(
        taxonomy_revision=revision,
        series_id="preflop-core",
        predecessor_taxonomy_revision=predecessor,
        concepts=(
            ConceptDefinition(
                concept_id="preflop.big-blind-defense",
                definition_revision=definition_revision,
                series_id="preflop-core",
                contexts=("preflop", "facing-wager"),
                testable_definition=definition,
            ),
        ),
    )


def mapping(
    *rules: ConceptMappingRule,
    revision: str = "mapping-v1",
    taxonomy_revision: str = "taxonomy-v1",
    predecessor: str | None = None,
) -> ConceptMappingRevision:
    return ConceptMappingRevision(
        mapping_revision=revision,
        taxonomy_revision=taxonomy_revision,
        predecessor_mapping_revision=predecessor,
        rules=rules,
    )


def matching_rule(
    *,
    rule_id: str = "bb-defense",
    selector: DecisionSelector | None = None,
) -> ConceptMappingRule:
    return ConceptMappingRule(
        rule_id=rule_id,
        concept_id="preflop.big-blind-defense",
        selector=selector or DecisionSelector(street="preflop"),
    )


def principle(
    *,
    principle_revision: str = "principle-v1",
    taxonomy_revision: str = "taxonomy-v1",
    definition_revision: str = "definition-v1",
    reference_revision: str = "reference-v1",
    author_kind: str = "llm",
    content: str = (
        "Against this pinned reference, continue ranges depend on the"
        " opener, sizing, stack depth, and intervening action."
    ),
) -> PrincipleRevision:
    return PrincipleRevision(
        principle_id="bb-defense-guidance",
        principle_revision=principle_revision,
        concept_id="preflop.big-blind-defense",
        taxonomy_revision=taxonomy_revision,
        concept_definition_revision=definition_revision,
        reference_policy_revision=reference_revision,
        author_kind=author_kind,
        author_id="principle-author",
        authored_at=NOW,
        content=content,
    )


def draft_record(**kwargs: str) -> PrincipleRecord:
    authored = principle(**kwargs)
    return principle_draft(
        authored,
        actor_id="draft-generator",
        created_at=NOW,
    )


def approved_record(**kwargs: str) -> PrincipleRecord:
    draft = draft_record(**kwargs)
    return append_principle_lifecycle_event(
        draft,
        PrincipleLifecycleEvent(
            sequence=1,
            status="approved",
            actor_kind="human",
            actor_id="reviewer-1",
            occurred_at=NOW + timedelta(minutes=5),
            review_basis="Reviewed against the pinned reference export.",
        ),
    )


def tagged_decision(
    *,
    mapping_revision: str = "mapping-v1",
):
    result = tag_primary_concept(
        decision(),
        taxonomy=taxonomy(),
        mapping=mapping(
            matching_rule(),
            revision=mapping_revision,
        ),
    )
    assert result.tag is not None
    return result.tag


def test_taxonomy_requires_a_valid_acyclic_hierarchy() -> None:
    with pytest.raises(ValidationError, match="unknown parent"):
        TaxonomyRevision(
            taxonomy_revision="taxonomy-v1",
            series_id="preflop-core",
            concepts=(
                ConceptDefinition(
                    concept_id="child",
                    definition_revision="definition-v1",
                    series_id="preflop-core",
                    parent_concept_id="missing",
                    contexts=("preflop",),
                    testable_definition="A testable child concept.",
                ),
            ),
        )


def test_mapping_selector_rejects_a_catch_all() -> None:
    with pytest.raises(ValidationError, match="catch-all"):
        DecisionSelector()
    with pytest.raises(ValidationError, match="contiguous street prefix"):
        DecisionSelector(
            action_route=(RouteStreetSelector(street="flop", actions=()),)
        )


def test_mapping_selector_matches_versioned_route_actor_stack_and_sizing() -> None:
    point = decision()
    route = (
        RouteStreetSelector(
            street="preflop",
            actions=(
                RouteActionSelector(
                    actor_position="BTN/SB",
                    action_type="post_small_blind",
                    amount_big_blinds=DecimalRange(
                        minimum=Decimal("0.5"),
                        maximum=Decimal("0.5"),
                    ),
                ),
                RouteActionSelector(
                    actor_position="BB",
                    action_type="post_big_blind",
                    total_committed_big_blinds=DecimalRange(
                        minimum=Decimal("1"),
                        maximum=Decimal("1"),
                    ),
                ),
            ),
        ),
    )
    selector = DecisionSelector(
        hero_stack_before_action_big_blinds=DecimalRange(
            minimum=Decimal("99"),
            maximum=Decimal("100"),
        ),
        position_stack_depths=(
            PositionStackSelector(
                position="BB",
                stack_before_action_big_blinds=DecimalRange(
                    minimum=Decimal("99"),
                    maximum=Decimal("99"),
                ),
                status="live",
            ),
        ),
        action_route=route,
    )
    assert selector.matches(point)

    wrong_actor = selector.model_copy(
        update={
            "action_route": (
                route[0].model_copy(
                    update={
                        "actions": (
                            route[0].actions[0],
                            route[0].actions[1].model_copy(
                                update={"actor_position": "BTN/SB"}
                            ),
                        )
                    }
                ),
            )
        }
    )
    assert not wrong_actor.matches(point)

    wrong_size = selector.model_copy(
        update={
            "action_route": (
                route[0].model_copy(
                    update={
                        "actions": (
                            route[0].actions[0],
                            route[0].actions[1].model_copy(
                                update={
                                    "total_committed_big_blinds": DecimalRange(
                                        minimum=Decimal("2"),
                                        maximum=Decimal("2"),
                                    )
                                }
                            ),
                        )
                    }
                ),
            )
        }
    )
    assert not wrong_size.matches(point)

    wrong_stack = selector.model_copy(
        update={
            "hero_stack_before_action_big_blinds": DecimalRange(
                maximum=Decimal("20")
            )
        }
    )
    assert not wrong_stack.matches(point)


def test_mapping_selector_preserves_unresolved_action_sizing() -> None:
    extraction = extract_hero_decision_points(multi_street_decision_record())
    assert extraction.outcome == "decisions"
    point = extraction.decision_points[1]
    assert point.street == "flop"
    assert point.state.action_history[-1].actions[-1].amount is None

    route_streets = tuple(
        RouteStreetSelector(
            street=history.street,
            actions=tuple(
                RouteActionSelector(
                    actor_position=action.position.display_label,
                    action_type=action.action_type,
                )
                for action in history.actions
            ),
        )
        for history in point.state.action_history
    )
    route = DecisionSelector(action_route=route_streets)
    current_street = route_streets[-1]
    unresolved_action = current_street.actions[-1]
    sized_route = route.model_copy(
        update={
            "action_route": (
                *route_streets[:-1],
                current_street.model_copy(
                    update={
                        "actions": (
                            *current_street.actions[:-1],
                            unresolved_action.model_copy(
                                update={
                                    "amount_big_blinds": DecimalRange(
                                        minimum=Decimal("0")
                                    )
                                }
                            ),
                        ),
                    }
                ),
            )
        }
    )
    assert route.matches(point)
    assert not sized_route.matches(point)


def test_tagging_is_optional_deterministic_and_revision_pinned() -> None:
    point = decision()
    mapped_revision = mapping(matching_rule())

    first = tag_primary_concept(
        point,
        taxonomy=taxonomy(),
        mapping=mapped_revision,
    )
    second = tag_primary_concept(
        point,
        taxonomy=taxonomy(),
        mapping=mapped_revision,
    )

    assert first == second
    assert first.tag is not None
    assert first.absence_reason is None
    assert first.tag.concept_id == "preflop.big-blind-defense"
    assert first.tag.taxonomy_revision == "taxonomy-v1"
    assert first.tag.mapping_revision == "mapping-v1"
    assert first.tag.concept_definition_revision == "definition-v1"
    assert first.tag.decision.canonical_revision == point.canonical_revision
    assert first.tag.decision.deletion_generation == point.deletion_generation
    assert first.tag.decision.decision_index == point.decision_index

    unsupported = tag_primary_concept(
        point,
        taxonomy=taxonomy(),
        mapping=mapping(
            matching_rule(selector=DecisionSelector(street="river")),
        ),
    )
    assert unsupported.tag is None
    assert unsupported.absence_reason == "no_matching_rule"


def test_tagging_fails_on_multiple_primary_concepts() -> None:
    with pytest.raises(AmbiguousConceptMappingError, match="multiple"):
        tag_primary_concept(
            decision(),
            taxonomy=taxonomy(),
            mapping=mapping(
                matching_rule(rule_id="street-rule"),
                matching_rule(
                    rule_id="wager-rule",
                    selector=DecisionSelector(facing_wager=True),
                ),
            ),
        )


def test_tagging_result_cannot_fabricate_or_mix_absence() -> None:
    point = decision()
    binding = tagged_decision().decision
    with pytest.raises(ValidationError, match="either one primary tag"):
        DecisionConceptTagging(decision=binding)
    with pytest.raises(ValidationError, match="either one primary tag"):
        DecisionConceptTagging(
            decision=binding,
            tag=tagged_decision(),
            absence_reason="no_matching_rule",
        )
    assert point.identity.site == binding.identity.site
    assert point.identity.source_hand_id == binding.identity.source_hand_id
    assert point.identity.namespace == binding.identity.namespace


def test_mapping_rejects_unknown_or_mismatched_taxonomy_targets() -> None:
    unknown = ConceptMappingRule(
        rule_id="unknown",
        concept_id="preflop.unknown",
        selector=DecisionSelector(street="preflop"),
    )
    with pytest.raises(LearningContentCompatibilityError, match="unknown concepts"):
        validate_mapping_revision(taxonomy(), mapping(unknown))
    with pytest.raises(LearningContentCompatibilityError, match="does not target"):
        validate_mapping_revision(
            taxonomy(),
            mapping(matching_rule(), taxonomy_revision="taxonomy-v2"),
        )


def test_taxonomy_successor_cannot_rewrite_an_immutable_definition() -> None:
    previous = taxonomy()
    rewritten = taxonomy(
        revision="taxonomy-v2",
        predecessor="taxonomy-v1",
        definition="A different meaning under the same immutable revision.",
    )
    with pytest.raises(LearningContentCompatibilityError, match="immutable"):
        validate_taxonomy_successor((previous,), rewritten)

    revised = taxonomy(
        revision="taxonomy-v2",
        predecessor="taxonomy-v1",
        definition_revision="definition-v2",
        definition="A deliberately revised, separately pinned definition.",
    )
    validate_taxonomy_successor((previous,), revised)


def test_taxonomy_successor_requires_a_distinct_revision_identity() -> None:
    with pytest.raises(ValidationError, match="own predecessor"):
        taxonomy(predecessor="taxonomy-v1")

    reused_identity = taxonomy(
        definition_revision="definition-v2",
        definition="A changed definition under a reused taxonomy identity.",
    )
    with pytest.raises(LearningContentCompatibilityError, match="new revision"):
        validate_taxonomy_successor((taxonomy(),), reused_identity)

    second = taxonomy(
        revision="taxonomy-v2",
        predecessor="taxonomy-v1",
        definition_revision="definition-v2",
        definition="A deliberately revised definition.",
    )
    recycled = taxonomy(
        revision="taxonomy-v1",
        predecessor="taxonomy-v2",
        definition_revision="definition-v3",
        definition="A third definition under a recycled taxonomy identity.",
    )
    with pytest.raises(LearningContentCompatibilityError, match="new revision"):
        validate_taxonomy_successor((taxonomy(), second), recycled)


def test_mapping_successor_requires_distinct_identity_and_continuity() -> None:
    previous = mapping(matching_rule())
    with pytest.raises(ValidationError, match="own predecessor"):
        mapping(matching_rule(), predecessor="mapping-v1")

    reused_identity = mapping(
        matching_rule(selector=DecisionSelector(street="river")),
    )
    with pytest.raises(LearningContentCompatibilityError, match="new revision"):
        validate_mapping_successor((previous,), reused_identity)

    skipped_predecessor = mapping(
        matching_rule(),
        revision="mapping-v2",
        predecessor="mapping-v0",
    )
    with pytest.raises(
        LearningContentCompatibilityError,
        match="active predecessor",
    ):
        validate_mapping_successor((previous,), skipped_predecessor)

    second = mapping(
        matching_rule(),
        revision="mapping-v2",
        predecessor="mapping-v1",
    )
    validate_mapping_successor(
        (previous,),
        second,
    )
    recycled = mapping(
        matching_rule(selector=DecisionSelector(street="river")),
        revision="mapping-v1",
        predecessor="mapping-v2",
    )
    with pytest.raises(LearningContentCompatibilityError, match="new revision"):
        validate_mapping_successor((previous, second), recycled)

    validate_mapping_successor(
        (previous,),
        mapping(
            matching_rule(),
            revision="mapping-v2",
            predecessor="mapping-v1",
        ),
    )


def test_principle_lifecycle_requires_draft_then_human_review() -> None:
    authored = principle()
    with pytest.raises(ValidationError, match="begin as a draft"):
        PrincipleRecord(
            principle=authored,
            lifecycle=(
                PrincipleLifecycleEvent(
                    sequence=0,
                    status="approved",
                    actor_kind="human",
                    actor_id="reviewer-1",
                    occurred_at=NOW,
                    review_basis="Manual review.",
                ),
            ),
        )
    with pytest.raises(ValidationError, match="human reviewer"):
        PrincipleLifecycleEvent(
            sequence=1,
            status="approved",
            actor_kind="system",
            actor_id="approval-bot",
            occurred_at=NOW,
            review_basis="Automated review is not human review.",
        )

    approved = approved_record()
    assert approved.lifecycle[0].status == "draft"
    assert approved.current_status == "approved"
    assert approved.lifecycle[-1].actor_id == "reviewer-1"
    assert approved.lifecycle[-1].review_basis is not None


def test_principle_terminal_states_are_append_only_and_terminal() -> None:
    approved = approved_record()
    superseded = append_principle_lifecycle_event(
        approved,
        PrincipleLifecycleEvent(
            sequence=2,
            status="superseded",
            actor_kind="human",
            actor_id="reviewer-1",
            occurred_at=NOW + timedelta(minutes=10),
        ),
    )
    with pytest.raises(ValidationError, match="cannot transition"):
        append_principle_lifecycle_event(
            superseded,
            PrincipleLifecycleEvent(
                sequence=3,
                status="approved",
                actor_kind="human",
                actor_id="reviewer-2",
                occurred_at=NOW + timedelta(minutes=15),
                review_basis="A terminal revision cannot be reactivated.",
            ),
        )


def test_activation_excludes_drafts_and_requires_exact_compatibility() -> None:
    active_taxonomy = taxonomy()
    active_mapping = mapping(matching_rule())
    draft = draft_record(principle_revision="principle-draft")

    blocked = evaluate_learning_content_activation(
        taxonomy=active_taxonomy,
        mapping=active_mapping,
        reference_policy_revision="reference-v1",
        principles=(draft,),
    )
    assert not blocked.allowed
    assert blocked.missing_concept_ids == ("preflop.big-blind-defense",)
    assert blocked.eligible_principles == ()

    wrong_reference = approved_record(
        principle_revision="principle-reference-v2",
        reference_revision="reference-v2",
    )
    still_blocked = evaluate_learning_content_activation(
        taxonomy=active_taxonomy,
        mapping=active_mapping,
        reference_policy_revision="reference-v1",
        principles=(wrong_reference,),
    )
    assert not still_blocked.allowed

    approved = approved_record()
    allowed = evaluate_learning_content_activation(
        taxonomy=active_taxonomy,
        mapping=active_mapping,
        reference_policy_revision="reference-v1",
        principles=(draft, wrong_reference, approved),
    )
    assert allowed.allowed
    assert allowed.missing_concept_ids == ()
    assert [binding.principle_revision for binding in allowed.eligible_principles] == [
        "principle-v1"
    ]


def test_activation_rejects_duplicate_principle_revision_snapshots() -> None:
    draft = draft_record()
    approved = approved_record()
    with pytest.raises(
        LearningContentCompatibilityError,
        match="one current record",
    ):
        evaluate_learning_content_activation(
            taxonomy=taxonomy(),
            mapping=mapping(matching_rule()),
            reference_policy_revision="reference-v1",
            principles=(draft, approved),
        )


def test_approval_boundaries_revalidate_forged_lifecycle_snapshots() -> None:
    draft = draft_record()
    forged_event = draft.lifecycle[0].model_copy(
        update={
            "status": "approved",
            "actor_kind": "system",
            "review_basis": None,
        }
    )
    forged_record = draft.model_copy(update={"lifecycle": (forged_event,)})

    with pytest.raises(
        LearningContentCompatibilityError,
        match="canonical validation",
    ):
        evaluate_learning_content_activation(
            taxonomy=taxonomy(),
            mapping=mapping(matching_rule()),
            reference_policy_revision="reference-v1",
            principles=(forged_record,),
        )
    with pytest.raises(
        LearningContentCompatibilityError,
        match="canonical validation",
    ):
        build_principle_reveal(
            tagged_decision(),
            reference_policy_revision="reference-v1",
            record=forged_record,
        )


def test_reveal_requires_approved_compatible_principle_and_exact_versions() -> None:
    tag = tagged_decision()
    with pytest.raises(ApprovedPrincipleUnavailableError, match="human-approved"):
        build_principle_reveal(
            tag,
            reference_policy_revision="reference-v1",
            record=draft_record(),
        )
    with pytest.raises(ApprovedPrincipleUnavailableError, match="compatibility"):
        build_principle_reveal(
            tag,
            reference_policy_revision="reference-v1",
            record=approved_record(reference_revision="reference-v2"),
        )

    reveal = build_principle_reveal(
        tag,
        reference_policy_revision="reference-v1",
        record=approved_record(),
    )
    assert reveal.decision == tag.decision
    assert reveal.taxonomy_revision == tag.taxonomy_revision
    assert reveal.mapping_revision == tag.mapping_revision
    assert reveal.concept_definition_revision == tag.concept_definition_revision
    assert reveal.reference_policy_revision == "reference-v1"
    assert reveal.principle_revision == "principle-v1"
    assert reveal.display_text.startswith(EDUCATIONAL_GUIDANCE_PREFIX)
    assert "not a guarantee of optimal play or outcomes" in reveal.display_text.lower()


def test_reveal_allows_the_maximum_principle_content_after_framing() -> None:
    authored = principle(content="x" * 4000)
    record = principle_draft(
        authored,
        actor_id="draft-generator",
        created_at=NOW,
    )
    approved = append_principle_lifecycle_event(
        record,
        PrincipleLifecycleEvent(
            sequence=1,
            status="approved",
            actor_kind="human",
            actor_id="reviewer-1",
            occurred_at=NOW + timedelta(minutes=5),
            review_basis="Reviewed the maximum-length principle.",
        ),
    )

    reveal = build_principle_reveal(
        tagged_decision(),
        reference_policy_revision="reference-v1",
        record=approved,
    )
    assert len(reveal.display_text) == 4000 + len(EDUCATIONAL_GUIDANCE_PREFIX)
    assert reveal.display_text.endswith("x" * 4000)


def test_cache_key_changes_with_every_semantic_revision() -> None:
    base = principle_cache_key(
        tagged_decision(),
        reference_policy_revision="reference-v1",
        record=approved_record(),
    )
    mapping_changed = principle_cache_key(
        tagged_decision(mapping_revision="mapping-v2"),
        reference_policy_revision="reference-v1",
        record=approved_record(),
    )
    reference_changed = principle_cache_key(
        tagged_decision(),
        reference_policy_revision="reference-v2",
        record=approved_record(reference_revision="reference-v2"),
    )
    principle_changed = principle_cache_key(
        tagged_decision(),
        reference_policy_revision="reference-v1",
        record=approved_record(principle_revision="principle-v2"),
    )

    assert len(base.digest()) == 64
    assert len(
        {
            base.digest(),
            mapping_changed.digest(),
            reference_changed.digest(),
            principle_changed.digest(),
        }
    ) == 4
