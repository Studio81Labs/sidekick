from datetime import datetime, timezone

import pytest

from app.domain.grading import decision_grading_context_sha256
from app.domain.imported_hands import extract_hero_decision_points
from app.player_decision_evaluations import evaluate_player_active_hand_decisions
from app.player_hands import player_hand_record_version
from app.storage.imported_hand_store import imported_hand_record_key
from test_imported_hand_decisions import (
    big_blind_walk_record,
    hero_fold_decision_record,
)
from test_imported_hand_store import approved_record, sample_identity


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def test_active_decision_evaluation_is_explicitly_local_and_ungraded() -> None:
    record = hero_fold_decision_record()
    extraction = extract_hero_decision_points(record)
    key = imported_hand_record_key(record.identity)

    result = evaluate_player_active_hand_decisions(
        key,
        record,
        extraction,
        at=NOW,
    )

    assert result.schema_name == "player-active-hand-decision-evaluations/v1"
    assert result.record_key == key
    assert result.record_version == player_hand_record_version(record)
    assert result.active_canonical_revision == 1
    assert result.deletion_generation == 0
    assert result.extraction_outcome == "decisions"
    assert result.extraction_rejection is None
    assert result.evaluated_at == NOW
    assert len(result.evaluations) == 1

    evaluation = result.evaluations[0]
    assert evaluation.decision.canonical_revision == 1
    assert evaluation.decision.deletion_generation == 0
    assert evaluation.decision.decision_index == 0
    assert evaluation.grade.decision_context_sha256 == (
        decision_grading_context_sha256(extraction.decision_points[0])
    )
    assert evaluation.grade.grade_source == "heuristic"
    assert evaluation.grade.classification == "reference_unavailable"
    assert evaluation.grade.policy_grade_eligibility == "ungraded"
    assert evaluation.grade.learning_eligibility == "ineligible"
    assert evaluation.grade.reason == "reference_unavailable"
    assert evaluation.grade.framing == (
        "conditional_educational_reference_guidance"
    )
    assert evaluation.remote_reference.evaluated_at == NOW
    assert evaluation.remote_reference.outcome == "unavailable"
    assert evaluation.remote_reference.reason == "local_only"
    assert evaluation.remote_reference.policy_grade_eligibility == "ungraded"
    assert evaluation.remote_reference.outbound_request is None
    assert evaluation.remote_reference.resolved_reference is None

    serialized = result.model_dump_json(by_alias=True)
    assert "raw_text" not in serialized
    assert "excerpt" not in serialized
    assert "evidence" not in serialized
    assert "outbound_categories" not in serialized


@pytest.mark.parametrize(
    ("record_factory", "expected_outcome", "expected_rejection"),
    [
        (big_blind_walk_record, "no_decision", None),
        (approved_record, "not_extractable", "incomplete_hand_state"),
    ],
)
def test_active_decision_evaluation_preserves_explicit_empty_outcomes(
    record_factory,
    expected_outcome: str,
    expected_rejection: str | None,
) -> None:
    record = record_factory()
    extraction = extract_hero_decision_points(record)
    key = imported_hand_record_key(record.identity)

    result = evaluate_player_active_hand_decisions(
        key,
        record,
        extraction,
        at=NOW,
    )

    assert result.extraction_outcome == expected_outcome
    assert result.extraction_rejection == expected_rejection
    assert result.evaluations == ()


def test_active_decision_evaluation_rejects_a_foreign_extraction() -> None:
    record = hero_fold_decision_record()
    foreign = hero_fold_decision_record().model_copy(
        update={"identity": sample_identity(hand_ordinal=2)}
    )

    with pytest.raises(ValueError, match="identity does not match"):
        evaluate_player_active_hand_decisions(
            imported_hand_record_key(record.identity),
            record,
            extract_hero_decision_points(foreign),
            at=NOW,
        )


def test_active_decision_evaluation_rejects_a_stale_generation() -> None:
    record = hero_fold_decision_record()
    extraction = extract_hero_decision_points(record).model_copy(
        update={"deletion_generation": 1}
    )

    with pytest.raises(ValueError, match="deletion generation is stale"):
        evaluate_player_active_hand_decisions(
            imported_hand_record_key(record.identity),
            record,
            extraction,
            at=NOW,
        )
