"""Immutable contracts for versioned concepts and teaching principles."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.domain.imported_hands import HeroDecisionPoint
from app.domain.imported_hands.models import ActionType, StreetName


Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]*$",
        strict=True,
    ),
]
NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000, strict=True),
]
PositiveInteger = Annotated[int, Field(ge=1, strict=True)]
NonNegativeInteger = Annotated[int, Field(ge=0, strict=True)]
PositionLabel = Literal[
    "BTN/SB",
    "BTN",
    "SB",
    "BB",
    "UTG",
    "UTG+1",
    "UTG+2",
    "UTG+3",
    "UTG+3/LJ",
    "UTG+2/LJ",
    "UTG+1/LJ",
    "LJ",
    "HJ",
    "CO",
]
PrincipleStatus = Literal["draft", "approved", "superseded", "retired"]
PrincipleAuthorKind = Literal["human", "llm"]
PrincipleActorKind = Literal["human", "system"]
PrincipleFraming = Literal["conditional_educational_reference_guidance"]

EDUCATIONAL_GUIDANCE_PREFIX = (
    "Conditional educational reference guidance, not a guarantee of optimal play"
    " or outcomes: "
)


class LearningContentModel(BaseModel):
    """Strict immutable base for revision-pinned learning content."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )


class ConceptDefinition(LearningContentModel):
    """One stable concept with an immutable definition revision."""

    concept_id: Identifier
    definition_revision: Identifier
    series_id: Identifier
    parent_concept_id: Identifier | None = None
    contexts: tuple[NonEmptyText, ...] = Field(min_length=1)
    testable_definition: NonEmptyText

    @field_validator("contexts")
    @classmethod
    def validate_contexts(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("concept contexts must be unique")
        return value


class TaxonomyRevision(LearningContentModel):
    """One immutable snapshot of the complete concept hierarchy."""

    taxonomy_revision: Identifier
    series_id: Identifier
    predecessor_taxonomy_revision: Identifier | None = None
    concepts: tuple[ConceptDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_hierarchy(self) -> Self:
        if self.predecessor_taxonomy_revision == self.taxonomy_revision:
            raise ValueError("a taxonomy revision cannot be its own predecessor")
        concepts = {concept.concept_id: concept for concept in self.concepts}
        if len(concepts) != len(self.concepts):
            raise ValueError("concept ids must be unique within a taxonomy revision")
        for concept in self.concepts:
            if concept.series_id != self.series_id:
                raise ValueError(
                    f"concept {concept.concept_id} belongs to series"
                    f" {concept.series_id}, not {self.series_id}"
                )
            if (
                concept.parent_concept_id is not None
                and concept.parent_concept_id not in concepts
            ):
                raise ValueError(
                    f"concept {concept.concept_id} has unknown parent"
                    f" {concept.parent_concept_id}"
                )
            seen = {concept.concept_id}
            parent_id = concept.parent_concept_id
            while parent_id is not None:
                if parent_id in seen:
                    raise ValueError("concept hierarchy must not contain a cycle")
                seen.add(parent_id)
                parent_id = concepts[parent_id].parent_concept_id
        return self

    def concept(self, concept_id: str) -> ConceptDefinition | None:
        return next(
            (concept for concept in self.concepts if concept.concept_id == concept_id),
            None,
        )


class DecisionSelector(LearningContentModel):
    """A versioned, exact selector over canonical decision-state fields.

    Every populated field is conjunctive. An empty selector would be a catch-all
    concept, which the product specification explicitly forbids.
    """

    street: StreetName | None = None
    hero_position: PositionLabel | None = None
    dealt_in_player_count: Annotated[int, Field(ge=2, le=10, strict=True)] | None = None
    facing_wager: bool | None = None
    current_street_action_types: tuple[ActionType, ...] | None = None

    @model_validator(mode="after")
    def reject_catch_all(self) -> Self:
        if all(
            value is None
            for value in (
                self.street,
                self.hero_position,
                self.dealt_in_player_count,
                self.facing_wager,
                self.current_street_action_types,
            )
        ):
            raise ValueError("a concept mapping selector cannot be a catch-all")
        return self

    def matches(self, decision: HeroDecisionPoint) -> bool:
        current_actions = tuple(
            action.action_type for action in decision.state.action_history[-1].actions
        )
        return all(
            (
                self.street is None or self.street == decision.street,
                self.hero_position is None
                or self.hero_position == decision.state.hero_position.display_label,
                self.dealt_in_player_count is None
                or self.dealt_in_player_count
                == decision.state.dealt_in_player_count,
                self.facing_wager is None
                or self.facing_wager == (decision.state.amount_to_call > 0),
                self.current_street_action_types is None
                or self.current_street_action_types == current_actions,
            )
        )


class ConceptMappingRule(LearningContentModel):
    rule_id: Identifier
    concept_id: Identifier
    selector: DecisionSelector


class ConceptMappingRevision(LearningContentModel):
    """Immutable versioned rules for zero-or-one primary concept tagging."""

    mapping_revision: Identifier
    taxonomy_revision: Identifier
    predecessor_mapping_revision: Identifier | None = None
    rules: tuple[ConceptMappingRule, ...] = ()

    @model_validator(mode="after")
    def validate_rules(self) -> Self:
        if self.predecessor_mapping_revision == self.mapping_revision:
            raise ValueError("a mapping revision cannot be its own predecessor")
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("concept mapping rule ids must be unique")
        return self


class StableHandBinding(LearningContentModel):
    """Immutable copy of the adapter-defined hand identity."""

    site: Identifier
    source_hand_id: Identifier
    namespace: Identifier


class DecisionBinding(LearningContentModel):
    """Stable identity of one decision artifact revision."""

    identity: StableHandBinding
    canonical_revision: PositiveInteger
    deletion_generation: NonNegativeInteger
    decision_index: NonNegativeInteger

    @classmethod
    def from_decision(cls, decision: HeroDecisionPoint) -> "DecisionBinding":
        return cls(
            identity=StableHandBinding(
                site=decision.identity.site,
                source_hand_id=decision.identity.source_hand_id,
                namespace=decision.identity.namespace,
            ),
            canonical_revision=decision.canonical_revision,
            deletion_generation=decision.deletion_generation,
            decision_index=decision.decision_index,
        )


class PrimaryConceptTag(LearningContentModel):
    """One present primary tag with complete immutable provenance."""

    decision: DecisionBinding
    concept_id: Identifier
    taxonomy_revision: Identifier
    mapping_revision: Identifier
    concept_definition_revision: Identifier
    matched_rule_id: Identifier


class DecisionConceptTagging(LearningContentModel):
    """Explicit mapped or unsupported result; absence never invents a tag."""

    decision: DecisionBinding
    tag: PrimaryConceptTag | None = None
    absence_reason: Literal["no_matching_rule"] | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if (self.tag is None) == (self.absence_reason is None):
            raise ValueError(
                "tagging must contain either one primary tag or one absence reason"
            )
        if self.tag is not None and self.tag.decision != self.decision:
            raise ValueError("primary tag decision binding must match its result")
        return self


class PrincipleRevision(LearningContentModel):
    """Immutable authored principle text and its exact compatibility pins."""

    principle_id: Identifier
    principle_revision: Identifier
    concept_id: Identifier
    taxonomy_revision: Identifier
    concept_definition_revision: Identifier
    reference_policy_revision: Identifier
    author_kind: PrincipleAuthorKind
    author_id: Identifier
    authored_at: AwareDatetime
    content: NonEmptyText
    framing: PrincipleFraming = "conditional_educational_reference_guidance"
    supersedes_principle_revision: Identifier | None = None


class PrincipleLifecycleEvent(LearningContentModel):
    """One append-only principle status event with actor provenance."""

    sequence: NonNegativeInteger
    status: PrincipleStatus
    actor_kind: PrincipleActorKind
    actor_id: Identifier
    occurred_at: AwareDatetime
    review_basis: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if self.status == "approved":
            if self.actor_kind != "human":
                raise ValueError("principle approval requires a human reviewer")
            if self.review_basis is None:
                raise ValueError("principle approval requires reviewer provenance")
        elif self.review_basis is not None:
            raise ValueError("only a principle approval records a review basis")
        return self


class PrincipleRecord(LearningContentModel):
    """Immutable principle content plus its append-only lifecycle history."""

    principle: PrincipleRevision
    lifecycle: tuple[PrincipleLifecycleEvent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.lifecycle[0].status != "draft":
            raise ValueError("every principle revision must begin as a draft")
        sequences = [event.sequence for event in self.lifecycle]
        if sequences != list(range(len(self.lifecycle))):
            raise ValueError("principle lifecycle sequence must start at zero")
        allowed: dict[PrincipleStatus, set[PrincipleStatus]] = {
            "draft": {"approved", "retired"},
            "approved": {"superseded", "retired"},
            "superseded": set(),
            "retired": set(),
        }
        previous = self.lifecycle[0]
        if previous.occurred_at < self.principle.authored_at:
            raise ValueError("principle lifecycle cannot predate its content")
        for event in self.lifecycle[1:]:
            if event.status not in allowed[previous.status]:
                raise ValueError(
                    f"principle lifecycle cannot transition from"
                    f" {previous.status} to {event.status}"
                )
            if event.occurred_at < previous.occurred_at:
                raise ValueError("principle lifecycle timestamps must be ordered")
            previous = event
        return self

    @property
    def current_status(self) -> PrincipleStatus:
        return self.lifecycle[-1].status


class ApprovedPrincipleBinding(LearningContentModel):
    concept_id: Identifier
    principle_id: Identifier
    principle_revision: Identifier


class LearningContentActivationCheck(LearningContentModel):
    """Compatibility evidence for activating one taxonomy/reference pair."""

    taxonomy_revision: Identifier
    mapping_revision: Identifier
    reference_policy_revision: Identifier
    affected_concept_ids: tuple[Identifier, ...]
    eligible_principles: tuple[ApprovedPrincipleBinding, ...]
    missing_concept_ids: tuple[Identifier, ...]

    @property
    def allowed(self) -> bool:
        return not self.missing_concept_ids


class PrincipleReveal(LearningContentModel):
    """Principle-first reveal bound to exact decision and content versions."""

    decision: DecisionBinding
    concept_id: Identifier
    taxonomy_revision: Identifier
    mapping_revision: Identifier
    concept_definition_revision: Identifier
    reference_policy_revision: Identifier
    principle_id: Identifier
    principle_revision: Identifier
    framing: PrincipleFraming = "conditional_educational_reference_guidance"
    display_text: NonEmptyText

    @field_validator("display_text")
    @classmethod
    def validate_display_framing(cls, value: str) -> str:
        if not value.startswith(EDUCATIONAL_GUIDANCE_PREFIX):
            raise ValueError(
                "principle reveals require conditional educational framing"
            )
        return value


class PrincipleCacheKey(LearningContentModel):
    """All semantic inputs that can change one cached principle reveal."""

    concept_id: Identifier
    taxonomy_revision: Identifier
    mapping_revision: Identifier
    concept_definition_revision: Identifier
    reference_policy_revision: Identifier
    principle_id: Identifier
    principle_revision: Identifier

    def digest(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(payload).hexdigest()


def append_principle_lifecycle_event(
    record: PrincipleRecord,
    event: PrincipleLifecycleEvent,
) -> PrincipleRecord:
    """Return the next validated append-only lifecycle snapshot."""

    return PrincipleRecord(
        principle=record.principle,
        lifecycle=(*record.lifecycle, event),
    )


def principle_draft(
    principle: PrincipleRevision,
    *,
    actor_id: str,
    created_at: datetime,
) -> PrincipleRecord:
    """Create the mandatory draft entry for authored or LLM text."""

    return PrincipleRecord(
        principle=principle,
        lifecycle=(
            PrincipleLifecycleEvent(
                sequence=0,
                status="draft",
                actor_kind=(
                    "human" if principle.author_kind == "human" else "system"
                ),
                actor_id=actor_id,
                occurred_at=created_at,
            ),
        ),
    )
