"""Activate content-ready grades under one revision-isolated reference catalog."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from app.application.learning_evidence import LearningContentReadyGrade
from app.domain.grading import (
    ReferencePolicyQualificationBinding,
    ReferenceSourceQualification,
)
from app.domain.learning_content import (
    DecisionSelector,
    LearningReferencePolicyBinding,
    PrincipleRecord,
)


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
Sha256Digest = Annotated[
    str,
    StringConstraints(pattern=r"^[a-f0-9]{64}$", strict=True),
]
EvidencePointer = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=1000,
        strict=True,
    ),
]
PositiveInteger = Annotated[int, Field(ge=1, strict=True)]
NonNegativeInteger = Annotated[int, Field(ge=0, strict=True)]
PositiveDecimal = Annotated[
    Decimal,
    Field(gt=0, allow_inf_nan=False, strict=True),
]
NonNegativeDecimal = Annotated[
    Decimal,
    Field(ge=0, allow_inf_nan=False, strict=True),
]
PositiveProbability = Annotated[
    Decimal,
    Field(gt=0, le=1, allow_inf_nan=False, strict=True),
]


class ReferenceActivationError(ValueError):
    """A reference cannot be activated or used for learning."""


class ReferenceActivationModel(BaseModel):
    """Strict immutable base for reference-activation evidence."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CoverageBand(ReferenceActivationModel):
    """Stable band identity pinned to one immutable coverage definition."""

    coverage_band_id: Identifier
    definition_revision: Identifier
    definition_pointer: EvidencePointer
    definition_sha256: Sha256Digest
    selector: DecisionSelector
    selector_sha256: Sha256Digest
    coverage_revision: Identifier
    coverage_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_band(self) -> Self:
        try:
            selector = DecisionSelector.model_validate(
                self.selector.model_dump(mode="python")
            )
        except (AttributeError, ValidationError) as exc:
            raise ValueError("coverage band selector must be canonical") from exc
        if selector != self.selector:
            raise ValueError("coverage band selector must be canonical")
        if self.selector_sha256 != _model_sha256(selector):
            raise ValueError("coverage band must bind its exact selector")
        return self

    @classmethod
    def define(
        cls,
        *,
        coverage_band_id: str,
        definition_revision: str,
        definition_pointer: str,
        definition_sha256: str,
        selector: DecisionSelector,
        coverage_revision: str,
        coverage_sha256: str,
    ) -> Self:
        return cls(
            coverage_band_id=coverage_band_id,
            definition_revision=definition_revision,
            definition_pointer=definition_pointer,
            definition_sha256=definition_sha256,
            selector=selector,
            selector_sha256=_model_sha256(selector),
            coverage_revision=coverage_revision,
            coverage_sha256=coverage_sha256,
        )


class ReferenceSeriesBinding(ReferenceActivationModel):
    """Reference fields that must remain comparable throughout one series.

    Route, decision-context, and exact policy-content identities remain on each
    grade. They intentionally do not define the broader concept/coverage series.
    """

    reference_revision: Identifier
    policy_revision: Identifier
    tolerance_revision: Identifier
    reference_evidence_sha256: Sha256Digest
    policy_artifact_sha256: Sha256Digest
    coverage_revision: Identifier
    coverage_sha256: Sha256Digest
    engine_id: Identifier
    engine_revision: Identifier
    engine_configuration_sha256: Sha256Digest
    economic_model: Identifier
    economic_model_revision: Identifier
    economic_configuration_sha256: Sha256Digest
    utility_model: Identifier
    utility_model_revision: Identifier
    utility_configuration_sha256: Sha256Digest
    ev_unit: Literal["bb", "chips", "currency", "utility"]
    minimum_supported_frequency: PositiveProbability
    maximum_equivalent_ev_cost: NonNegativeDecimal
    sizing_tolerance_bb: PositiveDecimal

    @classmethod
    def from_reference(
        cls,
        binding: ReferencePolicyQualificationBinding,
    ) -> Self:
        return cls(
            reference_revision=binding.reference_revision,
            policy_revision=binding.policy_revision,
            tolerance_revision=binding.tolerance_revision,
            reference_evidence_sha256=binding.reference_evidence_sha256,
            policy_artifact_sha256=binding.policy_artifact_sha256,
            coverage_revision=binding.coverage_revision,
            coverage_sha256=binding.coverage_sha256,
            engine_id=binding.engine_id,
            engine_revision=binding.engine_revision,
            engine_configuration_sha256=binding.engine_configuration_sha256,
            economic_model=binding.economic_model,
            economic_model_revision=binding.economic_model_revision,
            economic_configuration_sha256=(
                binding.economic_configuration_sha256
            ),
            utility_model=binding.utility_model,
            utility_model_revision=binding.utility_model_revision,
            utility_configuration_sha256=(
                binding.utility_configuration_sha256
            ),
            ev_unit=binding.ev_unit,
            minimum_supported_frequency=binding.minimum_supported_frequency,
            maximum_equivalent_ev_cost=binding.maximum_equivalent_ev_cost,
            sizing_tolerance_bb=binding.sizing_tolerance_bb,
        )


class ReferenceActivation(ReferenceActivationModel):
    """One append-only activation event retained for audit."""

    sequence: PositiveInteger
    catalog_id: Identifier
    activation_id: Identifier
    predecessor_activation_sha256: Sha256Digest | None = None
    activation_sha256: Sha256Digest
    activated_at: AwareDatetime
    concept_id: Identifier
    coverage_band: CoverageBand
    taxonomy_series_id: Identifier
    taxonomy_revision: Identifier
    taxonomy_sha256: Sha256Digest
    mapping_revision: Identifier
    mapping_sha256: Sha256Digest
    concept_definition_revision: Identifier
    reference_series: ReferenceSeriesBinding
    activation_reference_binding: ReferencePolicyQualificationBinding
    source_qualification: ReferenceSourceQualification
    approved_principles: tuple[PrincipleRecord, ...] = Field(min_length=1)
    mastery_series_id: Identifier

    @model_validator(mode="after")
    def validate_activation(self) -> Self:
        coverage_band = _validated_coverage_band(self.coverage_band)
        source_qualification = _validated_source_qualification(
            self.source_qualification
        )
        reference_binding = _validated_reference_binding(
            self.activation_reference_binding
        )
        if coverage_band != self.coverage_band:
            raise ValueError("activation coverage band must be canonical")
        if source_qualification != self.source_qualification:
            raise ValueError("activation source qualification must be canonical")
        if reference_binding != self.activation_reference_binding:
            raise ValueError("activation reference binding must be canonical")
        if (
            not source_qualification.source_is_qualified
            or source_qualification.rights.delivery_mode
            != "shipped_static_lookup"
            or source_qualification.policy_binding
            != reference_binding
        ):
            raise ValueError(
                "activation requires the exact qualified local reference source"
            )
        if self.reference_series != ReferenceSeriesBinding.from_reference(
            reference_binding
        ):
            raise ValueError(
                "activation reference must belong to the retained reference series"
            )
        if (
            coverage_band.coverage_revision,
            coverage_band.coverage_sha256,
        ) != (
            self.reference_series.coverage_revision,
            self.reference_series.coverage_sha256,
        ):
            raise ValueError(
                "coverage band must match the activated reference coverage"
            )

        records = tuple(
            _validated_principle(record) for record in self.approved_principles
        )
        if records != self.approved_principles:
            raise ValueError("activation principle records must be canonical")
        identities = tuple(
            (record.principle.principle_id, record.principle.principle_revision)
            for record in records
        )
        if len(set(identities)) != len(identities):
            raise ValueError(
                "activation requires one record per principle revision identity"
            )
        if records != tuple(sorted(records, key=_principle_record_key)):
            raise ValueError("activation principle records must be canonical")

        learning_binding = _learning_reference_binding(
            reference_binding
        )
        for record in records:
            principle = record.principle
            if record.current_status != "approved":
                raise ValueError("activation requires human-approved principles")
            if (
                principle.concept_id,
                principle.taxonomy_series_id,
                principle.taxonomy_revision,
                principle.concept_definition_revision,
                principle.reference_policy_binding,
            ) != (
                self.concept_id,
                self.taxonomy_series_id,
                self.taxonomy_revision,
                self.concept_definition_revision,
                learning_binding,
            ):
                raise ValueError(
                    "activation principles must match the concept and exact reference"
                )
        evidence_times = (
            source_qualification.assessed_at,
            *(record.lifecycle[-1].occurred_at for record in records),
        )
        if self.activated_at < max(evidence_times):
            raise ValueError("activation cannot precede its reviewed evidence")
        if self.activation_sha256 != self.semantic_digest():
            raise ValueError("activation content must match its semantic digest")
        return self

    @classmethod
    def create(cls, **data: object) -> Self:
        data.pop("activation_sha256", None)
        candidate = cls.model_construct(
            **data,
            activation_sha256="0" * 64,
        )
        return cls(**data, activation_sha256=candidate.semantic_digest())

    @property
    def key(self) -> tuple[str, str]:
        return (self.concept_id, self.coverage_band.coverage_band_id)

    def semantic_digest(self) -> str:
        return _model_sha256(self, exclude={"activation_sha256"})


class ReferenceActivationCatalog(ReferenceActivationModel):
    """Append-only catalog with one latest activation per concept/band key."""

    catalog_id: Identifier
    catalog_revision: NonNegativeInteger
    activations: tuple[ReferenceActivation, ...] = ()
    active_activation_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_catalog(self) -> Self:
        activations = tuple(
            ReferenceActivation.model_validate(item.model_dump(mode="python"))
            for item in self.activations
        )
        if activations != self.activations:
            raise ValueError("catalog activations must be canonical")
        if self.catalog_revision != len(activations):
            raise ValueError(
                "catalog revision must equal its append-only activation count"
            )
        if tuple(item.sequence for item in activations) != tuple(
            range(1, len(activations) + 1)
        ):
            raise ValueError("catalog activation sequences must be contiguous")
        if tuple(item.activated_at for item in activations) != tuple(
            sorted(item.activated_at for item in activations)
        ):
            raise ValueError("catalog activation times must be monotonic")
        if any(item.catalog_id != self.catalog_id for item in activations):
            raise ValueError("catalog activations must retain the catalog identity")
        for index, activation in enumerate(activations):
            predecessor = (
                None if index == 0 else activations[index - 1].activation_sha256
            )
            if activation.predecessor_activation_sha256 != predecessor:
                raise ValueError("catalog activation digest chain is not contiguous")

        activation_ids = tuple(item.activation_id for item in activations)
        if len(set(activation_ids)) != len(activation_ids):
            raise ValueError("catalog activation ids must be unique")
        mastery_series_ids = tuple(item.mastery_series_id for item in activations)
        if len(set(mastery_series_ids)) != len(mastery_series_ids):
            raise ValueError(
                "every catalog activation must start a distinct mastery series"
            )
        if self.active_activation_ids != tuple(sorted(set(self.active_activation_ids))):
            raise ValueError("active activation ids must be sorted and unique")
        unknown = set(self.active_activation_ids) - set(activation_ids)
        if unknown:
            raise ValueError("active activation ids must belong to the catalog")

        latest_by_key: dict[tuple[str, str], ReferenceActivation] = {}
        for activation in activations:
            latest_by_key[activation.key] = activation
        expected_active = tuple(
            sorted(item.activation_id for item in latest_by_key.values())
        )
        if self.active_activation_ids != expected_active:
            raise ValueError(
                "catalog must select the latest activation for every concept band"
            )
        active = tuple(
            item for item in activations if item.activation_id in expected_active
        )
        selector_keys = tuple(
            (item.concept_id, item.coverage_band.selector_sha256) for item in active
        )
        if len(set(selector_keys)) != len(selector_keys):
            raise ValueError(
                "active coverage bands for one concept require distinct selectors"
            )
        return self

    @classmethod
    def empty(cls, catalog_id: str) -> Self:
        return cls(
            catalog_id=catalog_id,
            catalog_revision=0,
            activations=(),
            active_activation_ids=(),
        )

    def active_for(
        self,
        *,
        concept_id: str,
        coverage_band_id: str,
    ) -> ReferenceActivation | None:
        active_ids = set(self.active_activation_ids)
        return next(
            (
                activation
                for activation in self.activations
                if activation.activation_id in active_ids
                and activation.key == (concept_id, coverage_band_id)
            ),
            None,
        )

    def semantic_digest(self) -> str:
        return _model_sha256(self)


class ReferenceActivatedGrade(ReferenceActivationModel):
    """Grade bound to active reference/content evidence, not current hand state."""

    readiness: LearningContentReadyGrade
    catalog: ReferenceActivationCatalog
    catalog_sha256: Sha256Digest
    coverage_band_id: Identifier
    activation_id: Identifier
    mastery_series_id: Identifier
    reference_activation: Literal["active_in_catalog_snapshot"] = (
        "active_in_catalog_snapshot"
    )
    learning_eligibility: Literal[
        "requires_current_catalog_hand_and_content"
    ] = (
        "requires_current_catalog_hand_and_content"
    )

    @model_validator(mode="after")
    def validate_eligibility(self) -> Self:
        readiness = _validated_readiness(self.readiness)
        catalog = _validated_catalog(self.catalog)
        if readiness != self.readiness:
            raise ValueError("learning content readiness must be canonical")
        if catalog != self.catalog:
            raise ValueError("reference activation catalog must be canonical")
        if self.catalog_sha256 != catalog.semantic_digest():
            raise ValueError("learning eligibility must bind the exact catalog")
        activation = _matching_active_activation(
            catalog,
            readiness,
            self.coverage_band_id,
        )
        if activation is None:
            raise ValueError(
                "learning eligibility requires a matching active reference"
            )
        if (
            self.activation_id,
            self.mastery_series_id,
        ) != (
            activation.activation_id,
            activation.mastery_series_id,
        ):
            raise ValueError(
                "learning eligibility must retain the active activation and series"
            )
        return self


def activate_reference_series(
    catalog: ReferenceActivationCatalog,
    readiness: LearningContentReadyGrade,
    coverage_band: CoverageBand,
    *,
    activation_id: str,
    mastery_series_id: str,
    activated_at: datetime,
) -> ReferenceActivationCatalog:
    """Atomically return a successor catalog or leave the input unchanged."""

    catalog = _validated_catalog(catalog)
    readiness = _validated_readiness(readiness)
    coverage_band = _validated_coverage_band(coverage_band)
    tag = readiness.tagging.tag
    if tag is None:
        raise ReferenceActivationError(
            "reference activation requires one content-ready concept"
        )
    reference_binding = readiness.reference_policy_binding
    if (
        coverage_band.coverage_revision,
        coverage_band.coverage_sha256,
    ) != (
        reference_binding.coverage_revision,
        reference_binding.coverage_sha256,
    ):
        raise ReferenceActivationError(
            "coverage band does not match the content-ready reference"
        )
    decision = readiness.decision_snapshot.restore()
    if not coverage_band.selector.matches(decision):
        raise ReferenceActivationError(
            "content-ready decision does not belong to the coverage band"
        )
    active_ids = set(catalog.active_activation_ids)
    ambiguous = tuple(
        item
        for item in catalog.activations
        if item.activation_id in active_ids
        and item.concept_id == tag.concept_id
        and item.key
        != (tag.concept_id, coverage_band.coverage_band_id)
        and item.coverage_band.selector.matches(decision)
    )
    if ambiguous:
        raise ReferenceActivationError(
            "content-ready decision matches another active coverage band"
        )
    if activation_id in {item.activation_id for item in catalog.activations}:
        raise ReferenceActivationError("activation id has already been used")
    if mastery_series_id in {
        item.mastery_series_id for item in catalog.activations
    }:
        raise ReferenceActivationError(
            "catalog upgrades must start a distinct mastery series"
        )
    assert readiness.grade.source_qualification is not None

    try:
        activation = ReferenceActivation.create(
            sequence=catalog.catalog_revision + 1,
            catalog_id=catalog.catalog_id,
            activation_id=activation_id,
            predecessor_activation_sha256=(
                None
                if not catalog.activations
                else catalog.activations[-1].activation_sha256
            ),
            activated_at=activated_at,
            concept_id=tag.concept_id,
            coverage_band=coverage_band,
            taxonomy_series_id=tag.taxonomy_series_id,
            taxonomy_revision=tag.taxonomy_revision,
            taxonomy_sha256=_model_sha256(readiness.taxonomy),
            mapping_revision=tag.mapping_revision,
            mapping_sha256=_model_sha256(readiness.mapping),
            concept_definition_revision=tag.concept_definition_revision,
            reference_series=ReferenceSeriesBinding.from_reference(reference_binding),
            activation_reference_binding=reference_binding,
            source_qualification=readiness.grade.source_qualification,
            approved_principles=tuple(
                sorted(readiness.approved_principles, key=_principle_record_key)
            ),
            mastery_series_id=mastery_series_id,
        )
        prior_active = {
            item.activation_id: item
            for item in catalog.activations
            if item.activation_id in set(catalog.active_activation_ids)
        }
        retained_active_ids = tuple(
            item_id
            for item_id, item in prior_active.items()
            if item.key != activation.key
        )
        return ReferenceActivationCatalog(
            catalog_id=catalog.catalog_id,
            catalog_revision=catalog.catalog_revision + 1,
            activations=(*catalog.activations, activation),
            active_activation_ids=tuple(
                sorted((*retained_active_ids, activation.activation_id))
            ),
        )
    except ValidationError as exc:
        raise ReferenceActivationError(
            "reference activation failed canonical validation"
        ) from exc


def bind_grade_to_active_reference(
    catalog: ReferenceActivationCatalog,
    readiness: LearningContentReadyGrade,
    *,
    coverage_band_id: str,
) -> ReferenceActivatedGrade:
    """Bind a grade to active reference evidence pending a hand-state recheck."""

    catalog = _validated_catalog(catalog)
    readiness = _validated_readiness(readiness)
    activation = _matching_active_activation(
        catalog,
        readiness,
        coverage_band_id,
    )
    if activation is None:
        raise ReferenceActivationError(
            "content-ready grade has no matching active reference"
        )
    try:
        return ReferenceActivatedGrade(
            readiness=readiness,
            catalog=catalog,
            catalog_sha256=catalog.semantic_digest(),
            coverage_band_id=coverage_band_id,
            activation_id=activation.activation_id,
            mastery_series_id=activation.mastery_series_id,
        )
    except ValidationError as exc:
        raise ReferenceActivationError(
            "learning eligibility failed canonical validation"
        ) from exc


def _matching_active_activation(
    catalog: ReferenceActivationCatalog,
    readiness: LearningContentReadyGrade,
    coverage_band_id: str,
) -> ReferenceActivation | None:
    tag = readiness.tagging.tag
    if tag is None:
        return None
    decision = readiness.decision_snapshot.restore()
    active_ids = set(catalog.active_activation_ids)
    matches = tuple(
        activation
        for activation in catalog.activations
        if activation.activation_id in active_ids
        and activation.concept_id == tag.concept_id
        and activation.coverage_band.selector.matches(decision)
    )
    if len(matches) != 1:
        return None
    activation = matches[0]
    if activation.coverage_band.coverage_band_id != coverage_band_id:
        return None
    if (
        activation.taxonomy_series_id,
        activation.taxonomy_revision,
        activation.taxonomy_sha256,
        activation.mapping_revision,
        activation.mapping_sha256,
        activation.concept_definition_revision,
        activation.reference_series,
    ) != (
        tag.taxonomy_series_id,
        tag.taxonomy_revision,
        _model_sha256(readiness.taxonomy),
        tag.mapping_revision,
        _model_sha256(readiness.mapping),
        tag.concept_definition_revision,
        ReferenceSeriesBinding.from_reference(readiness.reference_policy_binding),
    ):
        return None
    if (
        activation.coverage_band.coverage_revision,
        activation.coverage_band.coverage_sha256,
    ) != (
        readiness.reference_policy_binding.coverage_revision,
        readiness.reference_policy_binding.coverage_sha256,
    ):
        return None
    return activation


def _validated_catalog(
    value: ReferenceActivationCatalog,
) -> ReferenceActivationCatalog:
    try:
        return ReferenceActivationCatalog.model_validate(
            value.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise ReferenceActivationError(
            "reference activation catalog failed canonical validation"
        ) from exc


def _validated_readiness(
    value: LearningContentReadyGrade,
) -> LearningContentReadyGrade:
    try:
        return LearningContentReadyGrade.model_validate(
            value.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise ReferenceActivationError(
            "learning content readiness failed canonical validation"
        ) from exc


def _validated_coverage_band(value: CoverageBand) -> CoverageBand:
    try:
        return CoverageBand.model_validate(value.model_dump(mode="python"))
    except (AttributeError, ValidationError) as exc:
        raise ReferenceActivationError(
            "coverage band failed canonical validation"
        ) from exc


def _validated_reference_binding(
    value: ReferencePolicyQualificationBinding,
) -> ReferencePolicyQualificationBinding:
    try:
        return ReferencePolicyQualificationBinding.model_validate(
            value.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise ValueError("activation reference binding must be canonical") from exc


def _validated_principle(value: PrincipleRecord) -> PrincipleRecord:
    try:
        return PrincipleRecord.model_validate(value.model_dump(mode="python"))
    except (AttributeError, ValidationError) as exc:
        raise ValueError("activation principle failed canonical validation") from exc


def _validated_source_qualification(
    value: ReferenceSourceQualification,
) -> ReferenceSourceQualification:
    try:
        return ReferenceSourceQualification.model_validate(
            value.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise ValueError(
            "activation source qualification failed canonical validation"
        ) from exc


def _learning_reference_binding(
    value: ReferencePolicyQualificationBinding,
) -> LearningReferencePolicyBinding:
    try:
        return LearningReferencePolicyBinding.model_validate(
            value.model_dump(mode="python")
        )
    except (AttributeError, ValidationError) as exc:
        raise ValueError("activation reference binding is not compatible") from exc


def _principle_record_key(record: PrincipleRecord) -> tuple[str, str, str]:
    principle = record.principle
    return (
        principle.principle_id,
        principle.principle_revision,
        principle.semantic_digest(),
    )


def _model_sha256(
    model: BaseModel,
    *,
    exclude: set[str] | None = None,
) -> str:
    payload = json.dumps(
        model.model_dump(mode="json", exclude=exclude),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()
