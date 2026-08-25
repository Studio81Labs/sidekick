from pathlib import Path

import pytest

from app.storage.file_job_store import FileJobStore
from api_test_support import approve_job, make_client, upload_job


def test_records_training_decision_before_recommendation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    response = client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "raise", "sizing": 7.5, "certainty": "high"},
    )

    assert response.status_code == 200
    decision = response.json()["training_decision"]
    assert decision["action"] == "raise"
    assert decision["sizing"] == 7.5
    assert decision["certainty"] == "high"
    assert decision["recorded_at"]
    persisted = FileJobStore(tmp_path).get(job_id).training_decision
    assert persisted.action == "raise"
    assert persisted.certainty == "high"


def test_training_progress_reports_completed_decision_reviews(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "call", "sizing": None, "certainty": "medium"},
    )
    client.post(f"/api/jobs/{job_id}/recommend")

    response = client.get("/api/training/progress")

    assert response.status_code == 200
    progress = response.json()
    assert progress["reviewed_hands"] == 1
    assert progress["certainty_summaries"] == [
        {
            "certainty": "medium",
            "hands": 1,
            "action_matches": 1,
            "exact_matches": 1,
            "needs_review_hands": 0,
            "action_accuracy": 1.0,
            "exact_accuracy": 1.0,
            "ev_compared_hands": 0,
            "average_ev_loss_bb": None,
            "trend": None,
        }
    ]
    assert progress["unrated_hands"] == 0
    assert progress["unrated_needs_review_hands"] == 0
    assert progress["recent_hands"][0]["decision_certainty"] == "medium"
    assert progress["action_matches"] == 1
    assert progress["exact_matches"] == 1
    assert progress["different_actions"] == 0
    assert progress["needs_review_hands"] == 0
    assert progress["action_accuracy"] == 1
    assert progress["exact_accuracy"] == 1
    assert progress["ev_compared_hands"] == 0
    assert progress["average_ev_loss_bb"] is None
    assert progress["trend"] is None
    assert progress["action_differences"] == []
    assert progress["street_summaries"][0]["street"] == "flop"
    assert progress["street_summaries"][0]["ev_compared_hands"] == 0
    assert progress["street_summaries"][0]["average_ev_loss_bb"] is None
    assert progress["recent_hands"][0]["job_id"] == job_id
    assert progress["recent_hands"][0]["outcome"] == "match"
    assert progress["recent_hands"][0]["ev_loss_bb"] is None
    assert progress["lesson_count"] == 0
    assert progress["lesson_matching_hands"] == 0
    assert progress["lesson_hands"] == []
    assert progress["review_street_counts"] == {}
    assert progress["review_queue_hands"] == 0
    assert progress["review_queue"] == []


def test_training_progress_validates_review_filters(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    filtered = client.get(
        "/api/training/progress"
        "?review_order=ev_loss"
        "&review_street=flop"
        "&review_certainty=high"
        "&review_decision_action=fold"
        "&review_recommended_action=call"
        "&lesson_order=ev_loss"
    )
    invalid_order = client.get("/api/training/progress?review_order=unknown")
    invalid_lesson_order = client.get(
        "/api/training/progress?lesson_order=unknown"
    )
    invalid_street = client.get("/api/training/progress?review_street=showdown")
    invalid_certainty = client.get(
        "/api/training/progress?review_certainty=very_sure"
    )
    invalid_lesson_street = client.get(
        "/api/training/progress?lesson_street=showdown"
    )
    oversized_lesson_query = client.get(
        f"/api/training/progress?lesson_query={'x' * 121}"
    )
    incomplete_difference = client.get(
        "/api/training/progress?review_decision_action=fold"
    )
    invalid_difference = client.get(
        "/api/training/progress"
        "?review_decision_action=jam"
        "&review_recommended_action=call"
    )
    invalid_solver_fallback = client.get(
        "/api/training/progress?solver_fallback_key=not-a-hash"
    )
    valid_solver_fallback = client.get(
        f"/api/training/progress?solver_fallback_key={'a' * 64}"
    )
    invalid_solver_route = client.get(
        "/api/training/progress?solver_route_key=not-a-hash"
    )
    valid_solver_route = client.get(
        f"/api/training/progress?solver_route_key={'b' * 64}"
    )
    invalid_solver_unattributed = client.get(
        "/api/training/progress?solver_unattributed=not-a-bool"
    )
    valid_solver_unattributed = client.get(
        "/api/training/progress?solver_unattributed=true"
    )
    invalid_recent_position = client.get(
        "/api/training/progress?recent_position=%20"
    )
    valid_recent_position = client.get(
        "/api/training/progress?recent_position=button"
    )
    valid_recent_unpositioned = client.get(
        "/api/training/progress?recent_unpositioned=true"
    )
    invalid_review_position = client.get(
        "/api/training/progress?review_position=%20"
    )
    valid_review_position = client.get(
        "/api/training/progress?review_position=button"
    )
    valid_review_unpositioned = client.get(
        "/api/training/progress?review_unpositioned=true"
    )
    invalid_recent_street = client.get(
        "/api/training/progress?recent_street=middle"
    )
    valid_recent_street = client.get(
        "/api/training/progress?recent_street=flop"
    )
    invalid_recent_certainty = client.get(
        "/api/training/progress?recent_certainty=very"
    )
    valid_recent_certainty = client.get(
        "/api/training/progress?recent_certainty=high"
    )
    valid_recent_unrated = client.get(
        "/api/training/progress?recent_certainty=unrated"
    )
    conflicting_position_filters = client.get(
        "/api/training/progress"
        "?recent_position=button"
        "&recent_unpositioned=true"
    )
    conflicting_review_position_filters = client.get(
        "/api/training/progress"
        "?review_position=button"
        "&review_unpositioned=true"
    )
    conflicting_position_solver_filters = client.get(
        "/api/training/progress"
        "?recent_position=button"
        f"&solver_route_key={'b' * 64}"
    )
    conflicting_street_position_filters = client.get(
        "/api/training/progress"
        "?recent_street=flop"
        "&recent_position=button"
    )
    conflicting_street_solver_filters = client.get(
        "/api/training/progress"
        "?recent_street=flop"
        f"&solver_route_key={'b' * 64}"
    )
    conflicting_certainty_street_filters = client.get(
        "/api/training/progress"
        "?recent_certainty=high"
        "&recent_street=flop"
    )
    conflicting_solver_filters = client.get(
        "/api/training/progress"
        f"?solver_fallback_key={'a' * 64}"
        f"&solver_route_key={'b' * 64}"
    )
    conflicting_unattributed_filter = client.get(
        "/api/training/progress"
        f"?solver_route_key={'b' * 64}"
        "&solver_unattributed=true"
    )

    assert filtered.status_code == 200
    assert invalid_order.status_code == 422
    assert invalid_lesson_order.status_code == 422
    assert invalid_street.status_code == 422
    assert invalid_certainty.status_code == 422
    assert invalid_lesson_street.status_code == 422
    assert oversized_lesson_query.status_code == 422
    assert incomplete_difference.status_code == 422
    assert incomplete_difference.json()["detail"] == (
        "review_decision_action and review_recommended_action "
        "must be provided together"
    )
    assert invalid_difference.status_code == 422
    assert invalid_solver_fallback.status_code == 422
    assert valid_solver_fallback.status_code == 200
    assert invalid_solver_route.status_code == 422
    assert valid_solver_route.status_code == 200
    assert invalid_solver_unattributed.status_code == 422
    assert valid_solver_unattributed.status_code == 200
    assert invalid_recent_position.status_code == 422
    assert valid_recent_position.status_code == 200
    assert valid_recent_unpositioned.status_code == 200
    assert invalid_review_position.status_code == 422
    assert valid_review_position.status_code == 200
    assert valid_review_unpositioned.status_code == 200
    assert invalid_recent_street.status_code == 422
    assert valid_recent_street.status_code == 200
    assert invalid_recent_certainty.status_code == 422
    assert valid_recent_certainty.status_code == 200
    assert valid_recent_unrated.status_code == 200
    assert conflicting_position_filters.status_code == 422
    assert conflicting_position_filters.json()["detail"] == (
        "recent_position and recent_unpositioned are mutually exclusive"
    )
    assert conflicting_review_position_filters.status_code == 422
    assert conflicting_review_position_filters.json()["detail"] == (
        "review_position and review_unpositioned are mutually exclusive"
    )
    assert conflicting_position_solver_filters.status_code == 422
    assert conflicting_position_solver_filters.json()["detail"] == (
        "position and solver recent-hand filters are mutually exclusive"
    )
    assert conflicting_street_position_filters.status_code == 422
    assert conflicting_street_position_filters.json()["detail"] == (
        "street, position, and solver recent-hand filters are mutually exclusive"
    )
    assert conflicting_street_solver_filters.status_code == 422
    assert conflicting_street_solver_filters.json()["detail"] == (
        "street, position, and solver recent-hand filters are mutually exclusive"
    )
    assert conflicting_certainty_street_filters.status_code == 422
    assert conflicting_certainty_street_filters.json()["detail"] == (
        "certainty, street, position, and solver recent-hand filters "
        "are mutually exclusive"
    )
    assert conflicting_solver_filters.status_code == 422
    assert conflicting_solver_filters.json()["detail"] == (
        "solver_fallback_key, solver_route_key, and solver_unattributed "
        "are mutually exclusive"
    )
    assert conflicting_unattributed_filter.status_code == 422
    assert conflicting_unattributed_filter.json()["detail"] == (
        conflicting_solver_filters.json()["detail"]
    )


def test_completed_training_review_leaves_accuracy_and_clears_pending_queue(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "raise", "sizing": 7.5},
    )
    client.post(f"/api/jobs/{job_id}/recommend")

    before_review = client.get("/api/training/progress").json()
    too_long = client.put(
        f"/api/jobs/{job_id}/training-review",
        json={"note": "x" * 1001},
    )
    response = client.put(
        f"/api/jobs/{job_id}/training-review",
        json={"note": "  Watch the call price and blockers.  "},
    )
    repeated = client.put(f"/api/jobs/{job_id}/training-review")
    after_review = client.get("/api/training/progress").json()
    updated = client.put(
        f"/api/jobs/{job_id}/training-review",
        json={"note": "Review blockers before raising."},
    )
    after_update = client.get("/api/training/progress").json()
    filtered_lesson = client.get(
        "/api/training/progress?lesson_street=flop&lesson_query=BLOCKERS"
    ).json()
    unmatched_lesson = client.get(
        "/api/training/progress?lesson_street=turn&lesson_query=blockers"
    ).json()
    exported_lesson = client.get(
        "/api/training/lessons/export?lesson_street=flop&lesson_query=BLOCKERS"
    )
    unmatched_export = client.get(
        "/api/training/lessons/export?lesson_street=turn&lesson_query=blockers"
    )
    reopened = client.delete(f"/api/jobs/{job_id}/training-review")
    repeated_reopen = client.delete(f"/api/jobs/{job_id}/training-review")
    after_reopen = client.get("/api/training/progress").json()

    assert before_review["needs_review_hands"] == 1
    assert before_review["review_queue"][0]["job_id"] == job_id
    assert too_long.status_code == 422
    assert response.status_code == 200
    assert response.json()["training_reviewed_at"]
    assert response.json()["training_review_note"] == (
        "Watch the call price and blockers."
    )
    assert repeated.status_code == 200
    assert repeated.json()["training_reviewed_at"] == response.json()[
        "training_reviewed_at"
    ]
    assert repeated.json()["training_review_note"] == response.json()[
        "training_review_note"
    ]
    assert after_review["reviewed_hands"] == 1
    assert after_review["different_actions"] == 1
    assert after_review["needs_review_hands"] == 0
    assert after_review["review_queue"] == []
    assert after_review["recent_hands"][0]["reviewed_at"] == response.json()[
        "training_reviewed_at"
    ]
    assert after_review["recent_hands"][0]["review_note"] == (
        "Watch the call price and blockers."
    )
    assert after_review["lesson_count"] == 1
    assert after_review["lesson_hands"][0]["job_id"] == job_id
    assert after_review["lesson_hands"][0]["review_note"] == (
        "Watch the call price and blockers."
    )
    assert updated.status_code == 200
    assert updated.json()["training_reviewed_at"] == response.json()[
        "training_reviewed_at"
    ]
    assert updated.json()["training_review_note"] == "Review blockers before raising."
    assert after_update["recent_hands"][0]["review_note"] == (
        "Review blockers before raising."
    )
    assert after_update["lesson_hands"][0]["review_note"] == (
        "Review blockers before raising."
    )
    assert filtered_lesson["lesson_count"] == 1
    assert filtered_lesson["lesson_matching_hands"] == 1
    assert filtered_lesson["lesson_hands"][0]["job_id"] == job_id
    assert unmatched_lesson["lesson_count"] == 1
    assert unmatched_lesson["lesson_matching_hands"] == 0
    assert unmatched_lesson["lesson_hands"] == []
    assert exported_lesson.status_code == 200
    assert exported_lesson.headers["content-type"].startswith("text/markdown")
    assert "poker-hero-lessons-" in exported_lesson.headers["content-disposition"]
    assert "## Ah Kd - Flop" in exported_lesson.text
    assert "- Board: Qs Jc 2h" in exported_lesson.text
    assert "- Position: `button`" in exported_lesson.text
    assert "- Pot: 12.5 BB" in exported_lesson.text
    assert "> Review blockers before raising." in exported_lesson.text
    assert unmatched_export.status_code == 409
    assert unmatched_export.json()["detail"] == (
        "No saved lesson notes match the selected filters"
    )
    assert reopened.status_code == 200
    assert reopened.json()["training_reviewed_at"] is None
    assert reopened.json()["training_review_note"] == "Review blockers before raising."
    assert repeated_reopen.status_code == 200
    assert repeated_reopen.json()["training_reviewed_at"] is None
    assert repeated_reopen.json()["training_review_note"] == (
        "Review blockers before raising."
    )
    assert after_reopen["reviewed_hands"] == 1
    assert after_reopen["different_actions"] == 1
    assert after_reopen["needs_review_hands"] == 1
    assert after_reopen["review_queue"][0]["job_id"] == job_id
    assert after_reopen["review_queue"][0]["review_note"] == (
        "Review blockers before raising."
    )
    assert after_reopen["recent_hands"][0]["reviewed_at"] is None
    assert after_reopen["recent_hands"][0]["review_note"] == (
        "Review blockers before raising."
    )
    assert after_reopen["lesson_count"] == 0
    assert after_reopen["lesson_hands"] == []
    assert FileJobStore(tmp_path).get(job_id).training_reviewed_at is None


def test_training_review_requires_a_non_exact_comparison(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]

    incomplete = client.put(f"/api/jobs/{job_id}/training-review")
    incomplete_reopen = client.delete(f"/api/jobs/{job_id}/training-review")

    approve_job(client, job_id)
    client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "call", "sizing": None},
    )
    client.post(f"/api/jobs/{job_id}/recommend")
    exact = client.put(f"/api/jobs/{job_id}/training-review")
    exact_reopen = client.delete(f"/api/jobs/{job_id}/training-review")

    assert incomplete.status_code == 409
    assert incomplete.json()["detail"] == (
        "A completed decision comparison is required before review"
    )
    assert incomplete_reopen.status_code == 409
    assert incomplete_reopen.json()["detail"] == (
        "A completed decision comparison is required before reopening review"
    )
    assert exact.status_code == 409
    assert exact.json()["detail"] == "Exact matches do not need review"
    assert exact_reopen.status_code == 409
    assert exact_reopen.json()["detail"] == "Exact matches do not need review"


def test_training_review_rejects_supported_mixed_line(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "raise", "sizing": 8},
    )
    client.post(f"/api/jobs/{job_id}/recommend")

    store = FileJobStore(tmp_path)
    job = store.get(job_id)
    assert job.recommendation is not None
    job.recommendation.raw["candidates"] = [
        {"action": "call", "sizing": None, "frequency": 0.8},
        {"action": "raise", "sizing": 8, "frequency": 0.2},
    ]
    store.save(job)

    complete = client.put(f"/api/jobs/{job_id}/training-review")
    reopen = client.delete(f"/api/jobs/{job_id}/training-review")
    progress = client.get("/api/training/progress").json()

    assert complete.status_code == 409
    assert complete.json()["detail"] == "Exact matches do not need review"
    assert reopen.status_code == 409
    assert reopen.json()["detail"] == "Exact matches do not need review"
    assert store.get(job_id).training_reviewed_at is None
    assert progress["recent_hands"][0]["outcome"] == "mixed"
    assert progress["recent_hands"][0]["reviewed_at"] is None
    assert progress["review_queue"] == []


def test_training_decision_requires_approval_and_precedes_recommendation(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]

    before_approval = client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "call", "sizing": None},
    )
    assert before_approval.status_code == 409
    assert before_approval.json()["detail"] == (
        "Approve corrected state before recording your decision"
    )

    approve_job(client, job_id)
    client.post(f"/api/jobs/{job_id}/recommend")
    after_recommendation = client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "call", "sizing": None},
    )
    assert after_recommendation.status_code == 409
    assert after_recommendation.json()["detail"] == (
        "Your decision must be recorded before revealing the recommendation"
    )


def test_training_decision_rejects_sizing_for_non_wager_action(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    response = client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "call", "sizing": 2.5},
    )

    assert response.status_code == 422
    assert FileJobStore(tmp_path).get(job_id).training_decision is None


def test_training_decision_rejects_nonfinite_sizing(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    response = client.put(
        f"/api/jobs/{job_id}/decision",
        content=b'{"action":"raise","sizing":1e309}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == "Infinity"
    assert FileJobStore(tmp_path).get(job_id).training_decision is None


def test_training_decision_rejects_zero_wager_sizing(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    response = client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "raise", "sizing": 0},
    )

    assert response.status_code == 422
    assert FileJobStore(tmp_path).get(job_id).training_decision is None


@pytest.mark.parametrize("sizing", [True, "7.5"])
def test_training_decision_rejects_coerced_wager_sizing(
    tmp_path: Path,
    sizing: object,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    response = client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "raise", "sizing": sizing},
    )

    assert response.status_code == 422
    assert FileJobStore(tmp_path).get(job_id).training_decision is None


def test_training_decision_rejects_unknown_certainty(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    response = client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "call", "sizing": None, "certainty": "certain"},
    )

    assert response.status_code == 422
    assert FileJobStore(tmp_path).get(job_id).training_decision is None
