"""Read-only local evaluation of current approved player decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.domain.grading import grade_decision
from app.domain.imported_hands import (
    DecisionOutcome,
    ExtractionRejection,
    HandDecisionExtraction,
    ImportedHandRecord,
)
from app.domain.learning_content import DecisionBinding
from app.domain.remote_references import evaluate_remote_reference_preflight
from app.player_hands import (
    PlayerHandIdentity,
    player_hand_record_version,
)


class PlayerDecisionEvaluationModel(BaseModel):
    """Strict immutable projection that cannot authorize learning or egress."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PlayerLocalDecisionGrade(PlayerDecisionEvaluationModel):
    """Current fail-closed grade while no qualified reference is available."""

    decision_context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    grade_source: Literal["heuristic"]
    classification: Literal["reference_unavailable"]
    policy_grade_eligibility: Literal["ungraded"]
    learning_eligibility: Literal["ineligible"]
    reason: Literal["reference_unavailable"]
    framing: Literal["conditional_educational_reference_guidance"]


class PlayerLocalRemoteReferenceEvaluation(PlayerDecisionEvaluationModel):
    """Explicit proof that the current evaluation performed no remote lookup."""

    evaluated_at: AwareDatetime
    outcome: Literal["unavailable"]
    reason: Literal["local_only"]
    policy_grade_eligibility: Literal["ungraded"]
    outbound_request: None = None
    resolved_reference: None = None


class PlayerActiveDecisionEvaluation(PlayerDecisionEvaluationModel):
    """One current decision with both learning and egress gates closed."""

    decision: DecisionBinding
    grade: PlayerLocalDecisionGrade
    remote_reference: PlayerLocalRemoteReferenceEvaluation


class PlayerActiveHandDecisionEvaluations(PlayerDecisionEvaluationModel):
    """Revision-bound evaluation results for one current decision artifact."""

    schema_name: Literal["player-active-hand-decision-evaluations/v1"] = Field(
        default="player-active-hand-decision-evaluations/v1",
        alias="schema",
    )
    record_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    record_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    identity: PlayerHandIdentity
    active_canonical_revision: int = Field(gt=0, strict=True)
    deletion_generation: int = Field(ge=0, strict=True)
    extraction_outcome: DecisionOutcome
    extraction_rejection: ExtractionRejection | None
    evaluated_at: AwareDatetime
    evaluations: tuple[PlayerActiveDecisionEvaluation, ...]

    @model_validator(mode="after")
    def validate_artifact_binding(self) -> Self:
        has_decisions = self.extraction_outcome == "decisions"
        if has_decisions != bool(self.evaluations):
            raise ValueError(
                "only a decisions extraction may contain decision evaluations"
            )
        if (self.extraction_outcome == "not_extractable") != (
            self.extraction_rejection is not None
        ):
            raise ValueError(
                "only a not-extractable result may contain an extraction rejection"
            )
        expected_indexes = tuple(range(len(self.evaluations)))
        actual_indexes = tuple(
            evaluation.decision.decision_index for evaluation in self.evaluations
        )
        if actual_indexes != expected_indexes:
            raise ValueError("decision evaluations must retain contiguous source order")
        for evaluation in self.evaluations:
            decision = evaluation.decision
            if (
                decision.identity.site != self.identity.site
                or decision.identity.source_hand_id != self.identity.source_hand_id
                or decision.identity.namespace != self.identity.namespace
                or decision.canonical_revision != self.active_canonical_revision
                or decision.deletion_generation != self.deletion_generation
            ):
                raise ValueError(
                    "decision evaluation does not match its active hand revision"
                )
            if evaluation.remote_reference.evaluated_at != self.evaluated_at:
                raise ValueError(
                    "decision evaluations must share one evaluation timestamp"
                )
        return self


def evaluate_player_active_hand_decisions(
    record_key: str,
    record: ImportedHandRecord,
    extraction: HandDecisionExtraction,
    *,
    at: datetime,
) -> PlayerActiveHandDecisionEvaluations:
    """Evaluate only current canonical points with learning and egress disabled."""

    active_revision = record.lifecycle.active_canonical_revision
    if not record.lifecycle.learning_eligible or active_revision is None:
        raise ValueError("decision evaluation requires an active approved hand")
    if record.identity is None:
        raise ValueError("decision evaluation requires a stable hand identity")
    if extraction.identity != record.identity:
        raise ValueError("decision extraction identity does not match the active hand")
    if extraction.deletion_generation != record.lifecycle.deletion_generation:
        raise ValueError("decision extraction deletion generation is stale")
    if extraction.canonical_revision not in {None, active_revision}:
        raise ValueError("decision extraction canonical revision is stale")

    evaluations: list[PlayerActiveDecisionEvaluation] = []
    for point in extraction.decision_points:
        grade = grade_decision(point, reference=None)
        remote_reference = evaluate_remote_reference_preflight(
            point,
            mode="local_only",
            policy=None,
            consent=None,
            route=None,
            now=at,
        )
        evaluations.append(
            PlayerActiveDecisionEvaluation(
                decision=grade.decision,
                grade=PlayerLocalDecisionGrade(
                    decision_context_sha256=grade.decision_context_sha256,
                    grade_source=grade.grade_source,
                    classification=grade.classification,
                    policy_grade_eligibility=grade.policy_grade_eligibility,
                    learning_eligibility=grade.learning_eligibility,
                    reason=grade.reason,
                    framing=grade.framing,
                ),
                remote_reference=PlayerLocalRemoteReferenceEvaluation(
                    evaluated_at=remote_reference.evaluated_at,
                    outcome=remote_reference.outcome,
                    reason=remote_reference.reason,
                    policy_grade_eligibility=(
                        remote_reference.policy_grade_eligibility
                    ),
                    outbound_request=remote_reference.outbound_request,
                    resolved_reference=remote_reference.resolved_reference,
                ),
            )
        )

    return PlayerActiveHandDecisionEvaluations(
        record_key=record_key,
        record_version=player_hand_record_version(record),
        identity=PlayerHandIdentity(
            namespace=record.identity.namespace,
            site=record.identity.site,
            source_hand_id=record.identity.source_hand_id,
        ),
        active_canonical_revision=active_revision,
        deletion_generation=record.lifecycle.deletion_generation,
        extraction_outcome=extraction.outcome,
        extraction_rejection=extraction.rejection,
        evaluated_at=at,
        evaluations=tuple(evaluations),
    )
