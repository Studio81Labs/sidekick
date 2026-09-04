"""Immutable contracts for fail-closed per-decision policy grading."""

from __future__ import annotations

import json
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.domain.learning_content.models import DecisionBinding


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
PositiveDecimal = Annotated[
    Decimal,
    Field(gt=0, allow_inf_nan=False, strict=True),
]
NonNegativeDecimal = Annotated[
    Decimal,
    Field(ge=0, allow_inf_nan=False, strict=True),
]
FiniteDecimal = Annotated[
    Decimal,
    Field(allow_inf_nan=False, strict=True),
]
PositiveProbability = Annotated[
    Decimal,
    Field(gt=0, le=1, allow_inf_nan=False, strict=True),
]

GradeAction = Literal["fold", "check", "call", "bet", "raise"]
GradeSource = Literal["heuristic", "solved"]
GradeClassification = Literal[
    "reference_unavailable",
    "policy_incomplete",
    "supported",
    "mistake",
]
PolicyGradeEligibility = Literal["ungraded", "gradeable"]
LearningEligibility = Literal["ineligible", "requires_content_activation"]
GradeReason = Literal[
    "reference_unavailable",
    "reference_source_unqualified",
    "reference_qualification_mismatch",
    "reference_delivery_unverified",
    "decision_context_mismatch",
    "decision_sizing_unverified",
    "reference_policy_illegal",
    "policy_incomplete",
    "supported_policy_match",
    "outside_policy_support",
    "policy_match_below_support",
]
GradeEvUnit = Literal["bb", "chips", "currency", "utility"]
GradeFraming = Literal["conditional_educational_reference_guidance"]
ReferenceQualificationStatus = Literal["staged", "qualified", "rejected"]
ReferenceDeliveryMode = Literal["shipped_static_lookup", "server_side_feed"]
ReferenceRight = Literal[
    "commercial_use",
    "embedding",
    "redistribution",
    "updates",
    "commercial_serving",
    "derived_outputs",
]
ReferenceBenchmarkOutcome = Literal["pending", "passed", "failed"]
EvidencePointer = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=1000,
        strict=True,
    ),
]

WAGER_ACTIONS = {"bet", "raise"}


class GradingModel(BaseModel):
    """Strict immutable base for data that may later become learning evidence."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _normalize_policy_content(value: object) -> object:
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        sign, digits, exponent = value.as_tuple()
        canonical_digits = list(digits)
        while canonical_digits[-1] == 0:
            canonical_digits.pop()
            exponent += 1
        coefficient = "".join(str(digit) for digit in canonical_digits)
        return f"{'-' if sign else ''}{coefficient}e{exponent}"
    if isinstance(value, dict):
        return {
            key: _normalize_policy_content(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_policy_content(item) for item in value]
    return value


class ReferenceEvidence(GradingModel):
    """One immutable evidence record retained outside the runtime payload."""

    revision: Identifier
    pointer: EvidencePointer
    sha256: Sha256Digest


class ReferenceRightsEvidence(GradingModel):
    """Rights that match the selected reference delivery mode."""

    basis: Literal["owned", "licensed"]
    delivery_mode: ReferenceDeliveryMode
    grants: tuple[ReferenceRight, ...] = Field(min_length=1, max_length=6)
    evidence: ReferenceEvidence

    @model_validator(mode="after")
    def validate_delivery_rights(self) -> Self:
        if len(self.grants) != len(set(self.grants)):
            raise ValueError("reference rights grants must be unique")
        required = {
            "shipped_static_lookup": {
                "commercial_use",
                "embedding",
                "redistribution",
                "updates",
            },
            "server_side_feed": {
                "commercial_use",
                "commercial_serving",
                "derived_outputs",
            },
        }[self.delivery_mode]
        missing = required.difference(self.grants)
        if missing:
            raise ValueError(
                f"{self.delivery_mode} rights evidence is missing grants:"
                f" {', '.join(sorted(missing))}"
            )
        return self


class ReferenceBenchmarkEvidence(GradingModel):
    """Versioned pass/fail evidence from an independent reference benchmark."""

    suite_revision: Identifier
    threshold_revision: Identifier
    outcome: ReferenceBenchmarkOutcome
    evidence: ReferenceEvidence | None = None

    @model_validator(mode="after")
    def validate_outcome_evidence(self) -> Self:
        if (self.outcome == "pending") != (self.evidence is None):
            raise ValueError(
                "pending benchmark evidence must be absent and completed evidence"
                " must be retained"
            )
        return self


class PolicyLine(GradingModel):
    """One candidate action/sizing from an already-resolved reference policy.

    Wager sizes are exact total commitments normalized by the decision's big
    blind, not incremental bet amounts. ``expected_value`` uses ``ev_unit``
    from the owning reference. The grade derives loss from the complete set of
    candidate values instead of trusting an adapter-supplied difference.
    """

    action: GradeAction
    total_committed_bb: PositiveDecimal | None = None
    frequency: PositiveProbability
    expected_value: FiniteDecimal | None = None

    @model_validator(mode="after")
    def validate_sizing(self) -> Self:
        if self.action in WAGER_ACTIONS and self.total_committed_bb is None:
            raise ValueError("bet and raise policy lines require total_committed_bb")
        if self.action not in WAGER_ACTIONS and self.total_committed_bb is not None:
            raise ValueError(
                "only bet and raise policy lines may carry total_committed_bb"
            )
        return self


class ResolvedReferencePolicy(GradingModel):
    """An application-supplied solved policy already bound to one exact spot.

    This contract does not approve source rights, run a benchmark, activate a
    reference, or authorize a remote request. Those remain upstream gates. It
    retains the immutable identities a later application adapter must prove.
    """

    reference_revision: Identifier
    policy_revision: Identifier
    tolerance_revision: Identifier
    reference_evidence_sha256: Sha256Digest
    policy_artifact_sha256: Sha256Digest
    coverage_revision: Identifier
    coverage_sha256: Sha256Digest
    route_binding_id: Identifier
    route_binding_revision: Identifier
    context_sha256: Sha256Digest
    engine_id: Identifier
    engine_revision: Identifier
    engine_configuration_sha256: Sha256Digest
    economic_model: Identifier
    economic_model_revision: Identifier
    economic_configuration_sha256: Sha256Digest
    utility_model: Identifier
    utility_model_revision: Identifier
    utility_configuration_sha256: Sha256Digest
    ev_unit: GradeEvUnit
    policy_complete: bool
    minimum_supported_frequency: PositiveProbability
    maximum_equivalent_ev_cost: NonNegativeDecimal
    sizing_tolerance_bb: PositiveDecimal
    policy_lines: tuple[PolicyLine, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        identities = [
            (line.action, line.total_committed_bb) for line in self.policy_lines
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("policy line action/sizing identities must be unique")

        frequency_total = sum(
            (line.frequency for line in self.policy_lines),
            Decimal(0),
        )
        if self.policy_complete and frequency_total != Decimal(1):
            raise ValueError("complete policy line frequencies must sum to one")
        if not self.policy_complete and frequency_total > Decimal(1):
            raise ValueError("incomplete policy line frequencies cannot exceed one")

        has_expected_value = [
            line.expected_value is not None for line in self.policy_lines
        ]
        if any(has_expected_value) and not all(has_expected_value):
            raise ValueError("policy candidate EVs must cover every line or none")
        if self.policy_complete and not all(has_expected_value):
            raise ValueError(
                "a complete policy requires an expected value for every line"
            )

        wager_lines = [
            line for line in self.policy_lines if line.action in WAGER_ACTIONS
        ]
        for index, first in enumerate(wager_lines):
            assert first.total_committed_bb is not None
            for second in wager_lines[index + 1 :]:
                if first.action != second.action:
                    continue
                assert second.total_committed_bb is not None
                separation = abs(
                    first.total_committed_bb - second.total_committed_bb
                )
                if separation < self.sizing_tolerance_bb * 2:
                    raise ValueError(
                        "same-action wager policy lines must not have overlapping"
                        " sizing tolerances"
                    )
        return self

    def ev_cost_for(self, line: PolicyLine) -> Decimal:
        """Derive one candidate's loss from the retained policy EV evidence."""

        if line not in self.policy_lines:
            raise ValueError("EV cost can only be derived for a policy candidate")
        expected_values = tuple(
            candidate.expected_value for candidate in self.policy_lines
        )
        if line.expected_value is None or any(
            value is None for value in expected_values
        ):
            raise ValueError("EV cost requires expected values for every candidate")
        concrete_values = tuple(
            value for value in expected_values if value is not None
        )
        return max(concrete_values) - line.expected_value

    def policy_content_sha256(self) -> str:
        """Fingerprint the exact completeness, action, frequency, sizing, and EV data."""

        payload = json.dumps(
            _normalize_policy_content(
                {
                    "policy_complete": self.policy_complete,
                    "policy_lines": [
                        line.model_dump(mode="python")
                        for line in self.policy_lines
                    ],
                }
            ),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(payload).hexdigest()


class ReferencePolicyQualificationBinding(GradingModel):
    """Exact immutable policy identity approved by a source qualification."""

    reference_revision: Identifier
    policy_revision: Identifier
    tolerance_revision: Identifier
    reference_evidence_sha256: Sha256Digest
    policy_artifact_sha256: Sha256Digest
    policy_content_sha256: Sha256Digest
    coverage_revision: Identifier
    coverage_sha256: Sha256Digest
    route_binding_id: Identifier
    route_binding_revision: Identifier
    context_sha256: Sha256Digest
    engine_id: Identifier
    engine_revision: Identifier
    engine_configuration_sha256: Sha256Digest
    economic_model: Identifier
    economic_model_revision: Identifier
    economic_configuration_sha256: Sha256Digest
    utility_model: Identifier
    utility_model_revision: Identifier
    utility_configuration_sha256: Sha256Digest
    ev_unit: GradeEvUnit
    minimum_supported_frequency: PositiveProbability
    maximum_equivalent_ev_cost: NonNegativeDecimal
    sizing_tolerance_bb: PositiveDecimal

    @classmethod
    def from_reference(
        cls,
        reference: ResolvedReferencePolicy,
    ) -> "ReferencePolicyQualificationBinding":
        return cls(
            reference_revision=reference.reference_revision,
            policy_revision=reference.policy_revision,
            tolerance_revision=reference.tolerance_revision,
            reference_evidence_sha256=reference.reference_evidence_sha256,
            policy_artifact_sha256=reference.policy_artifact_sha256,
            policy_content_sha256=reference.policy_content_sha256(),
            coverage_revision=reference.coverage_revision,
            coverage_sha256=reference.coverage_sha256,
            route_binding_id=reference.route_binding_id,
            route_binding_revision=reference.route_binding_revision,
            context_sha256=reference.context_sha256,
            engine_id=reference.engine_id,
            engine_revision=reference.engine_revision,
            engine_configuration_sha256=reference.engine_configuration_sha256,
            economic_model=reference.economic_model,
            economic_model_revision=reference.economic_model_revision,
            economic_configuration_sha256=(
                reference.economic_configuration_sha256
            ),
            utility_model=reference.utility_model,
            utility_model_revision=reference.utility_model_revision,
            utility_configuration_sha256=(
                reference.utility_configuration_sha256
            ),
            ev_unit=reference.ev_unit,
            minimum_supported_frequency=reference.minimum_supported_frequency,
            maximum_equivalent_ev_cost=reference.maximum_equivalent_ev_cost,
            sizing_tolerance_bb=reference.sizing_tolerance_bb,
        )

    def matches(self, reference: ResolvedReferencePolicy) -> bool:
        return self == self.from_reference(reference)


class ReferenceSourceQualification(GradingModel):
    """Independent reviewed authority for one exact reference-policy identity.

    This snapshot records evidence; it does not fetch a source, execute a
    benchmark, authorize remote transport, or activate learning content.
    """

    qualification_revision: Identifier
    status: ReferenceQualificationStatus
    assessed_at: AwareDatetime
    assessor_id: Identifier
    source_id: Identifier
    source_revision: Identifier
    source_artifact_sha256: Sha256Digest
    source_configuration_sha256: Sha256Digest
    qualification_evidence: ReferenceEvidence
    independent_solved_evidence: ReferenceEvidence
    coverage_evidence: ReferenceEvidence
    rights: ReferenceRightsEvidence
    benchmark: ReferenceBenchmarkEvidence
    policy_binding: ReferencePolicyQualificationBinding

    @model_validator(mode="after")
    def validate_qualification(self) -> Self:
        if self.status == "qualified" and self.benchmark.outcome != "passed":
            raise ValueError(
                "a qualified reference source requires a passed benchmark"
            )
        if (
            self.coverage_evidence.revision
            != self.policy_binding.coverage_revision
            or self.coverage_evidence.sha256
            != self.policy_binding.coverage_sha256
        ):
            raise ValueError(
                "qualification coverage evidence must match its policy binding"
            )
        return self

    @property
    def source_is_qualified(self) -> bool:
        return self.status == "qualified" and self.benchmark.outcome == "passed"

    def matches(self, reference: ResolvedReferencePolicy) -> bool:
        return self.policy_binding.matches(reference)

    def permits_local_grading(self, reference: ResolvedReferencePolicy) -> bool:
        return (
            self.source_is_qualified
            and self.matches(reference)
            and self.rights.delivery_mode == "shipped_static_lookup"
        )


class DecisionGrade(GradingModel):
    """One reviewable policy comparison; not persisted mastery authorization."""

    decision: DecisionBinding
    decision_context_sha256: Sha256Digest
    grade_source: GradeSource
    classification: GradeClassification
    policy_grade_eligibility: PolicyGradeEligibility
    learning_eligibility: LearningEligibility
    reason: GradeReason
    reference: ResolvedReferencePolicy | None = None
    source_qualification: ReferenceSourceQualification | None = None
    supported_policy_lines: tuple[PolicyLine, ...] = ()
    matched_policy_line: PolicyLine | None = None
    ev_cost: NonNegativeDecimal | None = None
    ev_unit: GradeEvUnit | None = None
    framing: GradeFraming = "conditional_educational_reference_guidance"

    @model_validator(mode="after")
    def validate_grade_state(self) -> Self:
        gradeable = self.policy_grade_eligibility == "gradeable"
        qualification_ready = (
            self.reference is not None
            and self.source_qualification is not None
            and self.source_qualification.permits_local_grading(self.reference)
        )
        if gradeable != (self.classification in {"supported", "mistake"}):
            raise ValueError(
                "only supported or mistake classifications are policy-gradeable"
            )
        expected_learning = (
            "requires_content_activation" if gradeable else "ineligible"
        )
        if self.learning_eligibility != expected_learning:
            raise ValueError(
                "learning eligibility must remain gated on policy gradeability and"
                " later content activation"
            )

        if self.grade_source == "solved" and not qualification_ready:
            raise ValueError(
                "solved evidence requires an exactly qualified local reference"
            )
        if gradeable and self.grade_source != "solved":
            raise ValueError("a gradeable policy comparison must be solved")
        if self.source_qualification is not None and self.reference is None:
            raise ValueError(
                "source qualification cannot exist without its resolved reference"
            )

        if self.classification == "reference_unavailable":
            if self.grade_source != "heuristic" or self.reason not in {
                "reference_unavailable",
                "reference_source_unqualified",
                "reference_qualification_mismatch",
                "reference_delivery_unverified",
                "decision_context_mismatch",
                "decision_sizing_unverified",
                "reference_policy_illegal",
            }:
                raise ValueError(
                    "reference-unavailable results must be heuristic and explain"
                    " why no reference matched"
                )
            if self.reason == "reference_unavailable" and (
                self.reference is not None or self.source_qualification is not None
            ):
                raise ValueError(
                    "a missing-reference result cannot retain reference evidence"
                )
            if self.reason == "reference_source_unqualified" and (
                self.reference is None
                or (
                    self.source_qualification is not None
                    and self.source_qualification.source_is_qualified
                )
            ):
                raise ValueError(
                    "an unqualified-source result requires an unqualified source"
                )
            if self.reason == "reference_qualification_mismatch" and (
                self.reference is None
                or self.source_qualification is None
                or self.source_qualification.matches(self.reference)
            ):
                raise ValueError(
                    "a qualification-mismatch result requires mismatched evidence"
                )
            if self.reason == "reference_delivery_unverified" and (
                self.reference is None
                or self.source_qualification is None
                or not self.source_qualification.source_is_qualified
                or not self.source_qualification.matches(self.reference)
                or self.source_qualification.rights.delivery_mode
                != "server_side_feed"
            ):
                raise ValueError(
                    "an unverified-delivery result requires a qualified remote feed"
                )
            if self.reason in {
                "decision_context_mismatch",
                "decision_sizing_unverified",
                "reference_policy_illegal",
            } and not qualification_ready:
                raise ValueError(
                    "policy validation failures require a qualified local reference"
                )
            if any(
                value is not None
                for value in (self.matched_policy_line, self.ev_cost, self.ev_unit)
            ) or self.supported_policy_lines:
                raise ValueError(
                    "reference-unavailable results cannot publish policy grading"
                    " evidence"
                )
        elif self.classification == "policy_incomplete":
            if (
                self.grade_source != "solved"
                or not qualification_ready
                or self.reason != "policy_incomplete"
                or self.reference is None
                or self.reference.policy_complete
                or self.reference.context_sha256 != self.decision_context_sha256
                or self.ev_unit != self.reference.ev_unit
            ):
                raise ValueError(
                    "policy-incomplete results must retain incomplete solved"
                    " evidence and its EV unit"
                )
            if self.matched_policy_line is not None or self.supported_policy_lines:
                raise ValueError(
                    "an incomplete policy cannot publish action support"
                )

        if gradeable:
            assert self.reference is not None
            if not qualification_ready:
                raise ValueError(
                    "a policy grade requires an exactly qualified local reference"
                )
            if not self.reference.policy_complete:
                raise ValueError("a policy grade requires a complete reference policy")
            if self.reference.context_sha256 != self.decision_context_sha256:
                raise ValueError("a policy grade requires an exact decision context")
            if self.ev_unit != self.reference.ev_unit:
                raise ValueError("a policy grade must preserve its reference EV unit")
            if not self.supported_policy_lines:
                raise ValueError("a complete policy grade requires supported lines")
            expected_supported = tuple(
                line
                for line in self.reference.policy_lines
                if line.frequency >= self.reference.minimum_supported_frequency
                or (
                    self.reference.ev_cost_for(line)
                    <= self.reference.maximum_equivalent_ev_cost
                )
            )
            if self.supported_policy_lines != expected_supported:
                raise ValueError(
                    "published policy support must match the reference thresholds"
                )
        elif self.ev_cost is not None:
            raise ValueError("an ungraded result cannot publish an EV cost")

        if self.matched_policy_line is not None and (
            self.reference is None
            or self.matched_policy_line not in self.reference.policy_lines
        ):
            raise ValueError("a matched line must come from the resolved policy")
        if self.classification == "supported":
            if self.reason != "supported_policy_match":
                raise ValueError("a supported grade requires its support reason")
            if self.matched_policy_line is None:
                raise ValueError("a supported grade requires its matched policy line")
            if self.matched_policy_line not in self.supported_policy_lines:
                raise ValueError("a supported match must be inside policy support")
        if self.classification == "mistake":
            expected_reason = (
                "outside_policy_support"
                if self.matched_policy_line is None
                else "policy_match_below_support"
            )
            if self.reason != expected_reason:
                raise ValueError("a mistake reason must match its policy-line evidence")
            if self.matched_policy_line in self.supported_policy_lines:
                raise ValueError("a supported policy match cannot be labeled a mistake")
        if self.matched_policy_line is None:
            if self.ev_cost is not None:
                raise ValueError("an unmatched action cannot publish an EV cost")
        else:
            assert self.reference is not None
            expected_ev_cost = self.reference.ev_cost_for(self.matched_policy_line)
            if self.ev_cost != expected_ev_cost:
                raise ValueError(
                    "grade EV cost must be derived from the retained candidate EVs"
                )
        return self
