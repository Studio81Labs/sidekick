"""Player-safe projections of retained historical grade evidence."""

from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.application.reference_activation import ReferenceActivatedGrade
from app.domain.grading import (
    GradeEvUnit,
    GradeFraming,
    PolicyLine,
    ReferencePolicyQualificationBinding,
    ReferenceRight,
    ReferenceSourceQualification,
)
from app.domain.imported_hands import ImportedHandRecord
from app.domain.learning_content import ApprovedPrincipleBinding, DecisionBinding
from app.player_hands import player_hand_record_version


DEFAULT_PLAYER_GRADE_AUDIT_PAGE_SIZE = 25
MAX_PLAYER_GRADE_AUDIT_PAGE_SIZE = 100


class PlayerGradeAuditError(RuntimeError):
    """Retained grade evidence cannot be projected safely."""


class PlayerGradeAuditCursorError(ValueError):
    """An opaque grade-audit cursor does not name retained evidence."""


class PlayerGradeAuditModel(BaseModel):
    """Strict immutable base for the local audit-only response."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PlayerGradeAuditEvidence(PlayerGradeAuditModel):
    """Redacted evidence identity without its potentially local pointer."""

    revision: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PlayerGradeAuditRights(PlayerGradeAuditModel):
    basis: Literal["owned", "licensed"]
    delivery_mode: Literal["shipped_static_lookup"]
    grants: tuple[ReferenceRight, ...]
    evidence: PlayerGradeAuditEvidence


class PlayerGradeAuditBenchmark(PlayerGradeAuditModel):
    suite_revision: str
    threshold_revision: str
    outcome: Literal["passed"]
    evidence: PlayerGradeAuditEvidence


class PlayerGradeAuditQualification(PlayerGradeAuditModel):
    qualification_revision: str
    status: Literal["qualified"]
    assessed_at: AwareDatetime
    assessor_id: str
    source_id: str
    source_revision: str
    source_artifact_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    qualification_evidence: PlayerGradeAuditEvidence
    independent_solved_evidence: PlayerGradeAuditEvidence
    coverage_evidence: PlayerGradeAuditEvidence
    rights: PlayerGradeAuditRights
    benchmark: PlayerGradeAuditBenchmark


class PlayerGradeAuditReferencePolicy(PlayerGradeAuditModel):
    binding: ReferencePolicyQualificationBinding
    policy_complete: bool
    policy_lines: tuple[PolicyLine, ...]


class PlayerGradeAuditContent(PlayerGradeAuditModel):
    concept_id: str
    taxonomy_series_id: str
    taxonomy_revision: str
    taxonomy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mapping_revision: str
    mapping_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    concept_definition_revision: str
    matched_rule_id: str
    approved_principles: tuple[ApprovedPrincipleBinding, ...]


class PlayerGradeAuditActivation(PlayerGradeAuditModel):
    activation_id: str
    activation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    activated_at: AwareDatetime
    mastery_series_id: str
    coverage_band_id: str
    coverage_definition_revision: str
    coverage_definition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    coverage_selector_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    coverage_revision: str
    coverage_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PlayerRetainedGradeAudit(PlayerGradeAuditModel):
    """One integrity-checked grade that remains historical audit evidence."""

    audit_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    audit_status: Literal["historical_only"]
    decision: DecisionBinding
    decision_context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    grade_source: Literal["solved"]
    classification: Literal["supported", "mistake"]
    policy_grade_eligibility: Literal["gradeable"]
    grade_learning_eligibility: Literal["requires_content_activation"]
    reason: Literal[
        "supported_policy_match",
        "outside_policy_support",
        "policy_match_below_support",
    ]
    supported_policy_lines: tuple[PolicyLine, ...]
    matched_policy_line: PolicyLine | None
    ev_cost: Decimal | None
    ev_unit: GradeEvUnit
    framing: GradeFraming
    reference: PlayerGradeAuditReferencePolicy
    qualification: PlayerGradeAuditQualification
    catalog_id: str
    catalog_revision: int = Field(ge=1, strict=True)
    catalog_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    activation: PlayerGradeAuditActivation
    content: PlayerGradeAuditContent
    reference_activation: Literal["active_in_catalog_snapshot"]
    learning_eligibility: Literal[
        "requires_current_catalog_hand_and_content"
    ]


class PlayerRetainedGradeAuditPage(PlayerGradeAuditModel):
    schema_name: Literal["player-retained-grade-audits/v1"] = Field(
        default="player-retained-grade-audits/v1",
        alias="schema",
    )
    record_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    record_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    items: tuple[PlayerRetainedGradeAudit, ...]
    next_cursor: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


GradeArtifactIdentity = tuple[int, int, int, str]


def select_grade_audit_page(
    record_key: str,
    artifacts: list[GradeArtifactIdentity],
    *,
    limit: int,
    cursor: str | None,
) -> tuple[list[GradeArtifactIdentity], str | None]:
    """Select one snapshot-bound page without exposing storage filenames."""

    if limit < 1 or limit > MAX_PLAYER_GRADE_AUDIT_PAGE_SIZE:
        raise ValueError("grade audit page limit is out of bounds")
    snapshot_sha256 = _grade_audit_snapshot_sha256(record_key, artifacts)
    start = 0
    if cursor is not None:
        matches = tuple(
            index
            for index, (*_, filename) in enumerate(artifacts)
            if _grade_audit_cursor(snapshot_sha256, filename) == cursor
        )
        if len(matches) != 1:
            raise PlayerGradeAuditCursorError(
                "Grade audit cursor does not match retained evidence"
            )
        start = matches[0] + 1
    page = artifacts[start : start + limit + 1]
    has_more = len(page) > limit
    visible = page[:limit]
    next_cursor = (
        _grade_audit_cursor(snapshot_sha256, visible[-1][3])
        if has_more
        else None
    )
    return visible, next_cursor


def project_player_grade_audit_page(
    record_key: str,
    record: ImportedHandRecord,
    artifacts: list[tuple[str, ReferenceActivatedGrade]],
    *,
    next_cursor: str | None,
) -> PlayerRetainedGradeAuditPage:
    """Project validated retained grades without canonical snapshots or pointers."""

    return PlayerRetainedGradeAuditPage(
        record_key=record_key,
        record_version=player_hand_record_version(record),
        items=tuple(
            _project_player_grade_audit(filename, grade)
            for filename, grade in artifacts
        ),
        next_cursor=next_cursor,
    )


def grade_audit_id(filename: str) -> str:
    """Return an opaque stable identifier for one storage-owned artifact name."""

    return sha256(
        b"player-retained-grade-audit/v1\0" + filename.encode("utf-8")
    ).hexdigest()


def _grade_audit_snapshot_sha256(
    record_key: str,
    artifacts: list[GradeArtifactIdentity],
) -> str:
    """Bind pagination to the complete ordered evidence set for one hand."""

    digest = sha256(
        b"player-retained-grade-audit-snapshot/v1\0"
        + record_key.encode("utf-8")
        + b"\0"
    )
    for *_, filename in artifacts:
        digest.update(filename.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _grade_audit_cursor(snapshot_sha256: str, filename: str) -> str:
    """Return an opaque position bound to one immutable listing snapshot."""

    return sha256(
        b"player-retained-grade-audit-cursor/v2\0"
        + snapshot_sha256.encode("ascii")
        + b"\0"
        + filename.encode("utf-8")
    ).hexdigest()


def _project_player_grade_audit(
    filename: str,
    retained: ReferenceActivatedGrade,
) -> PlayerRetainedGradeAudit:
    grade = retained.readiness.grade
    reference = grade.reference
    qualification = grade.source_qualification
    tag = retained.readiness.tagging.tag
    activation = next(
        (
            candidate
            for candidate in retained.catalog.activations
            if candidate.activation_id == retained.activation_id
        ),
        None,
    )
    if (
        reference is None
        or qualification is None
        or tag is None
        or activation is None
        or grade.grade_source != "solved"
        or grade.policy_grade_eligibility != "gradeable"
        or grade.ev_unit is None
    ):
        raise PlayerGradeAuditError("Retained grade evidence is not audit-safe")

    return PlayerRetainedGradeAudit(
        audit_id=grade_audit_id(filename),
        audit_status="historical_only",
        decision=grade.decision,
        decision_context_sha256=grade.decision_context_sha256,
        grade_source=grade.grade_source,
        classification=grade.classification,
        policy_grade_eligibility=grade.policy_grade_eligibility,
        grade_learning_eligibility=grade.learning_eligibility,
        reason=grade.reason,
        supported_policy_lines=grade.supported_policy_lines,
        matched_policy_line=grade.matched_policy_line,
        ev_cost=grade.ev_cost,
        ev_unit=grade.ev_unit,
        framing=grade.framing,
        reference=PlayerGradeAuditReferencePolicy(
            binding=qualification.policy_binding,
            policy_complete=reference.policy_complete,
            policy_lines=reference.policy_lines,
        ),
        qualification=_project_qualification(qualification),
        catalog_id=retained.catalog.catalog_id,
        catalog_revision=retained.catalog.catalog_revision,
        catalog_sha256=retained.catalog_sha256,
        activation=PlayerGradeAuditActivation(
            activation_id=activation.activation_id,
            activation_sha256=activation.activation_sha256,
            activated_at=activation.activated_at,
            mastery_series_id=activation.mastery_series_id,
            coverage_band_id=activation.coverage_band.coverage_band_id,
            coverage_definition_revision=(
                activation.coverage_band.definition_revision
            ),
            coverage_definition_sha256=(
                activation.coverage_band.definition_sha256
            ),
            coverage_selector_sha256=activation.coverage_band.selector_sha256,
            coverage_revision=activation.coverage_band.coverage_revision,
            coverage_sha256=activation.coverage_band.coverage_sha256,
        ),
        content=PlayerGradeAuditContent(
            concept_id=tag.concept_id,
            taxonomy_series_id=tag.taxonomy_series_id,
            taxonomy_revision=tag.taxonomy_revision,
            taxonomy_sha256=activation.taxonomy_sha256,
            mapping_revision=tag.mapping_revision,
            mapping_sha256=activation.mapping_sha256,
            concept_definition_revision=tag.concept_definition_revision,
            matched_rule_id=tag.matched_rule_id,
            approved_principles=retained.readiness.activation.eligible_principles,
        ),
        reference_activation=retained.reference_activation,
        learning_eligibility=retained.learning_eligibility,
    )


def _project_qualification(
    qualification: ReferenceSourceQualification,
) -> PlayerGradeAuditQualification:
    benchmark_evidence = qualification.benchmark.evidence
    if (
        not qualification.source_is_qualified
        or qualification.rights.delivery_mode != "shipped_static_lookup"
        or benchmark_evidence is None
    ):
        raise PlayerGradeAuditError(
            "Retained source qualification is not audit-safe"
        )
    return PlayerGradeAuditQualification(
        qualification_revision=qualification.qualification_revision,
        status=qualification.status,
        assessed_at=qualification.assessed_at,
        assessor_id=qualification.assessor_id,
        source_id=qualification.source_id,
        source_revision=qualification.source_revision,
        source_artifact_sha256=qualification.source_artifact_sha256,
        source_configuration_sha256=qualification.source_configuration_sha256,
        qualification_evidence=PlayerGradeAuditEvidence(
            revision=qualification.qualification_evidence.revision,
            sha256=qualification.qualification_evidence.sha256,
        ),
        independent_solved_evidence=PlayerGradeAuditEvidence(
            revision=qualification.independent_solved_evidence.revision,
            sha256=qualification.independent_solved_evidence.sha256,
        ),
        coverage_evidence=PlayerGradeAuditEvidence(
            revision=qualification.coverage_evidence.revision,
            sha256=qualification.coverage_evidence.sha256,
        ),
        rights=PlayerGradeAuditRights(
            basis=qualification.rights.basis,
            delivery_mode=qualification.rights.delivery_mode,
            grants=qualification.rights.grants,
            evidence=PlayerGradeAuditEvidence(
                revision=qualification.rights.evidence.revision,
                sha256=qualification.rights.evidence.sha256,
            ),
        ),
        benchmark=PlayerGradeAuditBenchmark(
            suite_revision=qualification.benchmark.suite_revision,
            threshold_revision=qualification.benchmark.threshold_revision,
            outcome=qualification.benchmark.outcome,
            evidence=PlayerGradeAuditEvidence(
                revision=benchmark_evidence.revision,
                sha256=benchmark_evidence.sha256,
            ),
        ),
    )
