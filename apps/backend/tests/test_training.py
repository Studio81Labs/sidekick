import hashlib
from datetime import datetime, timezone

import pytest

from app.domain.hands import JobRecord
from app.domain.poker import CanonicalState, Card, Street
from app.domain.recommendations import RecommendationAction, RecommendationResult
from app.domain.training import TrainingCertainty, TrainingDecision
from app.training import build_training_lessons_markdown, summarize_training


def reviewed_job(
    job_id: str,
    street: Street,
    decision_action: RecommendationAction,
    recommended_action: RecommendationAction,
    recorded_at: datetime,
    decision_sizing: float | None = None,
    recommended_sizing: float | None = None,
    recommendation_raw: dict[str, object] | None = None,
    training_reviewed_at: datetime | None = None,
    training_review_note: str | None = None,
    decision_certainty: TrainingCertainty | None = None,
    hero_position: str | None = None,
) -> JobRecord:
    return JobRecord(
        id=job_id,
        status="recommended",
        original_filename=f"{street}.png",
        image_filename="original.png",
        parser_provider="mock",
        recommendation_provider="mock",
        approved_state=CanonicalState(
            hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
            hero_position=hero_position,
            street=street,
            user_approved=True,
        ),
        training_decision=TrainingDecision(
            action=decision_action,
            sizing=decision_sizing,
            certainty=decision_certainty,
            recorded_at=recorded_at,
        ),
        recommendation=RecommendationResult(
            action=recommended_action,
            sizing=recommended_sizing,
            confidence=0.8,
            explanation="Test recommendation",
            raw=recommendation_raw or {},
        ),
        training_reviewed_at=training_reviewed_at,
        training_review_note=training_review_note,
    )


def test_summarize_training_scores_actions_sizes_streets_and_recency() -> None:
    jobs = [
        reviewed_job(
            "1" * 32,
            "preflop",
            "call",
            "call",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        ),
        reviewed_job(
            "2" * 32,
            "flop",
            "bet",
            "bet",
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            decision_sizing=5,
            recommended_sizing=6,
        ),
        reviewed_job(
            "3" * 32,
            "turn",
            "fold",
            "call",
            datetime(2026, 7, 3, tzinfo=timezone.utc),
        ),
        JobRecord(
            id="4" * 32,
            original_filename="incomplete.png",
            image_filename="original.png",
            parser_provider="mock",
            recommendation_provider="mock",
            training_decision=TrainingDecision(action="check"),
        ),
    ]

    progress = summarize_training(jobs)

    assert progress.reviewed_hands == 3
    assert progress.action_matches == 2
    assert progress.exact_matches == 1
    assert progress.different_actions == 1
    assert progress.needs_review_hands == 2
    assert progress.action_accuracy == pytest.approx(2 / 3)
    assert progress.exact_accuracy == pytest.approx(1 / 3)
    assert progress.trend is not None
    assert progress.trend.window_hands == 1
    assert progress.trend.action_accuracy_delta == -1
    assert progress.trend.exact_accuracy_delta == 0
    assert progress.trend.average_ev_loss_delta_bb is None
    assert len(progress.action_differences) == 1
    assert progress.action_differences[0].decision_action == "fold"
    assert progress.action_differences[0].recommended_action == "call"
    assert progress.action_differences[0].hands == 1
    assert [summary.street for summary in progress.street_summaries] == [
        "preflop",
        "flop",
        "turn",
    ]
    assert [hand.job_id for hand in progress.recent_hands] == [
        "3" * 32,
        "2" * 32,
        "1" * 32,
    ]
    assert [hand.outcome for hand in progress.recent_hands] == [
        "different",
        "same_action",
        "match",
    ]
    assert progress.review_street_counts == {"flop": 1, "turn": 1}
    assert progress.review_queue_hands == 2
    assert [hand.job_id for hand in progress.review_queue] == ["3" * 32, "2" * 32]


def test_summarize_training_compares_equal_recent_street_windows() -> None:
    candidates = {
        "candidates": [
            {"action": "fold", "sizing": None, "ev": 0.0},
            {"action": "call", "sizing": None, "ev": 1.0},
        ]
    }
    jobs = [
        reviewed_job(
            f"{index:032x}",
            "flop",
            "fold" if index < 2 else "call",
            "call",
            datetime(2026, 7, index + 1, tzinfo=timezone.utc),
            recommendation_raw=candidates,
        )
        for index in range(4)
    ]
    jobs.append(
        reviewed_job(
            "f" * 32,
            "turn",
            "check",
            "check",
            datetime(2026, 7, 5, tzinfo=timezone.utc),
        )
    )

    progress = summarize_training(jobs)

    flop = progress.street_summaries[0]
    assert flop.street == "flop"
    assert flop.trend is not None
    assert flop.trend.window_hands == 2
    assert flop.trend.recent_action_accuracy == 1
    assert flop.trend.previous_action_accuracy == 0
    assert flop.trend.action_accuracy_delta == 1
    assert flop.trend.recent_exact_accuracy == 1
    assert flop.trend.previous_exact_accuracy == 0
    assert flop.trend.exact_accuracy_delta == 1
    assert flop.trend.recent_ev_compared_hands == 2
    assert flop.trend.previous_ev_compared_hands == 2
    assert flop.trend.recent_average_ev_loss_bb == 0
    assert flop.trend.previous_average_ev_loss_bb == 1
    assert flop.trend.average_ev_loss_delta_bb == -1
    assert progress.street_summaries[1].street == "turn"
    assert progress.street_summaries[1].trend is None


def test_summarize_training_reports_performance_by_normalized_position() -> None:
    ev_candidates = {
        "candidates": [
            {"action": "fold", "sizing": None, "ev": 0.0},
            {"action": "call", "sizing": None, "ev": 1.0},
        ]
    }
    jobs = [
        reviewed_job(
            "1" * 32,
            "preflop",
            "call",
            "call",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            hero_position="btn",
        ),
        reviewed_job(
            "2" * 32,
            "flop",
            "fold",
            "call",
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            recommendation_raw=ev_candidates,
            hero_position="dealer",
        ),
        reviewed_job(
            "3" * 32,
            "turn",
            "check",
            "check",
            datetime(2026, 7, 3, tzinfo=timezone.utc),
            hero_position="in_position",
        ),
        reviewed_job(
            "4" * 32,
            "river",
            "check",
            "check",
            datetime(2026, 7, 4, tzinfo=timezone.utc),
            hero_position="lojack",
        ),
        reviewed_job(
            "5" * 32,
            "river",
            "check",
            "check",
            datetime(2026, 7, 5, tzinfo=timezone.utc),
        ),
    ]

    progress = summarize_training(jobs)

    assert [summary.position for summary in progress.position_summaries] == [
        "BTN",
        "IP",
        "LOJACK",
    ]
    button = progress.position_summaries[0]
    assert button.reviewed_hands == 2
    assert button.action_matches == 1
    assert button.exact_matches == 1
    assert button.action_accuracy == 0.5
    assert button.exact_accuracy == 0.5
    assert button.needs_review_hands == 1
    assert button.ev_compared_hands == 1
    assert button.average_ev_loss_bb == 1
    in_position = progress.position_summaries[1]
    assert in_position.reviewed_hands == 1
    assert in_position.action_accuracy == 1
    assert in_position.exact_accuracy == 1
    assert in_position.ev_compared_hands == 0
    assert in_position.average_ev_loss_bb is None
    assert progress.position_summaries[2].reviewed_hands == 1
    assert progress.unpositioned_hands == 1
    assert progress.unpositioned_needs_review_hands == 0


def test_summarize_training_compares_equal_recent_position_windows() -> None:
    candidates = {
        "candidates": [
            {"action": "fold", "sizing": None, "ev": 0.0},
            {"action": "call", "sizing": None, "ev": 1.0},
        ]
    }
    aliases = ["button", "btn", "dealer", "BTN"]
    jobs = [
        reviewed_job(
            f"{index:032x}",
            "flop",
            "fold" if index < 2 else "call",
            "call",
            datetime(2026, 7, index + 1, tzinfo=timezone.utc),
            recommendation_raw=candidates,
            hero_position=aliases[index],
        )
        for index in range(4)
    ]
    jobs.append(
        reviewed_job(
            "f" * 32,
            "turn",
            "check",
            "check",
            datetime(2026, 7, 5, tzinfo=timezone.utc),
            hero_position="out_of_position",
        )
    )

    progress = summarize_training(jobs)

    button = progress.position_summaries[0]
    assert button.position == "BTN"
    assert button.trend is not None
    assert button.trend.window_hands == 2
    assert button.trend.recent_action_accuracy == 1
    assert button.trend.previous_action_accuracy == 0
    assert button.trend.action_accuracy_delta == 1
    assert button.trend.recent_exact_accuracy == 1
    assert button.trend.previous_exact_accuracy == 0
    assert button.trend.exact_accuracy_delta == 1
    assert button.trend.recent_ev_compared_hands == 2
    assert button.trend.previous_ev_compared_hands == 2
    assert button.trend.recent_average_ev_loss_bb == 0
    assert button.trend.previous_average_ev_loss_bb == 1
    assert button.trend.average_ev_loss_delta_bb == -1
    assert progress.position_summaries[1].position == "OOP"
    assert progress.position_summaries[1].trend is None


def test_summarize_training_filters_recent_hands_by_normalized_position() -> None:
    jobs = [
        reviewed_job(
            "1" * 32,
            "preflop",
            "call",
            "call",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            hero_position="btn",
        ),
        reviewed_job(
            "2" * 32,
            "flop",
            "call",
            "call",
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            hero_position="dealer",
        ),
        reviewed_job(
            "3" * 32,
            "turn",
            "check",
            "check",
            datetime(2026, 7, 3, tzinfo=timezone.utc),
            hero_position="out_of_position",
        ),
        reviewed_job(
            "4" * 32,
            "river",
            "check",
            "check",
            datetime(2026, 7, 4, tzinfo=timezone.utc),
        ),
    ]

    button_progress = summarize_training(
        jobs,
        recent_limit=1,
        recent_position="button",
    )
    unpositioned_progress = summarize_training(
        jobs,
        recent_unpositioned=True,
    )

    assert button_progress.recent_matching_hands == 2
    assert [hand.job_id for hand in button_progress.recent_hands] == ["2" * 32]
    assert unpositioned_progress.recent_matching_hands == 1
    assert [hand.job_id for hand in unpositioned_progress.recent_hands] == [
        "4" * 32
    ]


def test_summarize_training_filters_pending_reviews_by_position() -> None:
    jobs = [
        reviewed_job(
            "1" * 32,
            "preflop",
            "fold",
            "call",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            hero_position="button",
        ),
        reviewed_job(
            "2" * 32,
            "flop",
            "call",
            "call",
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            hero_position="btn",
        ),
        reviewed_job(
            "3" * 32,
            "turn",
            "fold",
            "call",
            datetime(2026, 7, 3, tzinfo=timezone.utc),
            hero_position="out_of_position",
        ),
        reviewed_job(
            "4" * 32,
            "river",
            "fold",
            "call",
            datetime(2026, 7, 4, tzinfo=timezone.utc),
        ),
        reviewed_job(
            "5" * 32,
            "river",
            "fold",
            "call",
            datetime(2026, 7, 5, tzinfo=timezone.utc),
            training_reviewed_at=datetime(
                2026,
                7,
                6,
                tzinfo=timezone.utc,
            ),
        ),
    ]

    button_progress = summarize_training(
        jobs,
        review_position="dealer",
    )
    unpositioned_progress = summarize_training(
        jobs,
        review_unpositioned=True,
    )

    assert button_progress.review_queue_hands == 1
    assert [hand.job_id for hand in button_progress.review_queue] == [
        "1" * 32
    ]
    button_summary = button_progress.position_summaries[0]
    assert button_summary.position == "BTN"
    assert button_summary.needs_review_hands == 1
    assert unpositioned_progress.review_queue_hands == 1
    assert [hand.job_id for hand in unpositioned_progress.review_queue] == [
        "4" * 32
    ]
    assert unpositioned_progress.unpositioned_hands == 2
    assert unpositioned_progress.unpositioned_needs_review_hands == 1


def test_summarize_training_filters_recent_hands_by_street() -> None:
    jobs = [
        reviewed_job(
            "1" * 32,
            "preflop",
            "call",
            "call",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
        ),
        reviewed_job(
            "2" * 32,
            "flop",
            "call",
            "call",
            datetime(2026, 7, 2, tzinfo=timezone.utc),
        ),
        reviewed_job(
            "3" * 32,
            "flop",
            "fold",
            "call",
            datetime(2026, 7, 3, tzinfo=timezone.utc),
        ),
        reviewed_job(
            "4" * 32,
            "turn",
            "check",
            "check",
            datetime(2026, 7, 4, tzinfo=timezone.utc),
        ),
    ]

    progress = summarize_training(
        jobs,
        recent_limit=1,
        recent_street="flop",
    )

    assert progress.reviewed_hands == 4
    assert [summary.street for summary in progress.street_summaries] == [
        "preflop",
        "flop",
        "turn",
    ]
    assert progress.recent_matching_hands == 2
    assert [hand.job_id for hand in progress.recent_hands] == ["3" * 32]
    assert progress.review_queue_hands == 1


def test_summarize_training_filters_recent_hands_by_certainty() -> None:
    jobs = [
        reviewed_job(
            "1" * 32,
            "preflop",
            "call",
            "call",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            decision_certainty="high",
        ),
        reviewed_job(
            "2" * 32,
            "flop",
            "call",
            "call",
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            decision_certainty="low",
        ),
        reviewed_job(
            "3" * 32,
            "turn",
            "fold",
            "call",
            datetime(2026, 7, 3, tzinfo=timezone.utc),
            decision_certainty="high",
        ),
        reviewed_job(
            "4" * 32,
            "river",
            "check",
            "check",
            datetime(2026, 7, 4, tzinfo=timezone.utc),
        ),
    ]

    high_progress = summarize_training(
        jobs,
        recent_limit=1,
        recent_certainty="high",
    )
    unrated_progress = summarize_training(
        jobs,
        recent_certainty="unrated",
    )

    assert high_progress.reviewed_hands == 4
    assert high_progress.recent_matching_hands == 2
    assert [hand.job_id for hand in high_progress.recent_hands] == ["3" * 32]
    assert unrated_progress.recent_matching_hands == 1
    assert [hand.job_id for hand in unrated_progress.recent_hands] == [
        "4" * 32
    ]


def test_summarize_training_reports_solver_routes_and_fallbacks() -> None:
    unsupported_reason = "hero position must identify IP or OOP"
    jobs = [
        reviewed_job(
            "1" * 32,
            "flop",
            "check",
            "check",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            recommendation_raw={"engine": "postflop_solver"},
        ),
        reviewed_job(
            "2" * 32,
            "river",
            "fold",
            "fold",
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            recommendation_raw={"engine": "postflop_solver"},
        ),
        reviewed_job(
            "3" * 32,
            "flop",
            "fold",
            "call",
            datetime(2026, 7, 3, tzinfo=timezone.utc),
            recommendation_raw={
                "engine": "local_ev_solver_v1",
                "fallback_reason": unsupported_reason,
                "requested_engine": "postflop_solver",
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 0.2},
                    {"action": "fold", "sizing": None, "ev": -0.2},
                ],
            },
        ),
        reviewed_job(
            "4" * 32,
            "turn",
            "call",
            "call",
            datetime(2026, 7, 4, tzinfo=timezone.utc),
            recommendation_raw={
                "engine": "local_ev_solver_v1",
                "fallback_reason": unsupported_reason,
                "requested_engine": "postflop_solver",
            },
        ),
        reviewed_job(
            "5" * 32,
            "preflop",
            "raise",
            "raise",
            datetime(2026, 7, 5, tzinfo=timezone.utc),
            recommendation_raw={
                "engine": "preflop_chart_v1",
                "routing_reason": "the hand is preflop",
                "requested_engine": "postflop_solver",
            },
        ),
        reviewed_job(
            "6" * 32,
            "flop",
            "check",
            "check",
            datetime(2026, 7, 6, tzinfo=timezone.utc),
        ),
    ]

    progress = summarize_training(jobs)
    coverage = progress.solver_coverage

    assert coverage.total_hands == 6
    assert coverage.tracked_hands == 5
    assert coverage.unattributed_hands == 1
    assert coverage.fallback_hands == 2
    assert coverage.fallback_rate == pytest.approx(1 / 3)
    assert coverage.trend is not None
    assert coverage.trend.window_hands == 3
    assert coverage.trend.recent_attribution_rate == pytest.approx(2 / 3)
    assert coverage.trend.previous_attribution_rate == 1
    assert coverage.trend.attribution_rate_delta == pytest.approx(-1 / 3)
    assert coverage.trend.recent_fallback_rate == pytest.approx(1 / 3)
    assert coverage.trend.previous_fallback_rate == pytest.approx(1 / 3)
    assert coverage.trend.fallback_rate_delta == 0
    assert [route.engine for route in coverage.routes] == [
        "local_ev_solver_v1",
        "postflop_solver",
        "preflop_chart_v1",
    ]
    route_keys = {
        route.engine: route.key
        for route in coverage.routes
    }
    assert route_keys == {
        engine: hashlib.sha256(engine.encode("utf-8")).hexdigest()
        for engine in (
            "local_ev_solver_v1",
            "postflop_solver",
            "preflop_chart_v1",
        )
    }
    assert coverage.routes[0].fallback_hands == 2
    assert coverage.routes[0].action_matches == 1
    assert coverage.routes[0].exact_matches == 1
    assert coverage.routes[0].action_accuracy == 0.5
    assert coverage.routes[0].exact_accuracy == 0.5
    assert coverage.routes[0].ev_compared_hands == 1
    assert coverage.routes[0].average_ev_loss_bb == 0.4
    assert coverage.routes[0].trend is not None
    assert coverage.routes[0].trend.window_hands == 1
    assert coverage.routes[0].trend.recent_action_accuracy == 1
    assert coverage.routes[0].trend.previous_action_accuracy == 0
    assert coverage.routes[0].trend.action_accuracy_delta == 1
    assert coverage.routes[0].trend.recent_exact_accuracy == 1
    assert coverage.routes[0].trend.previous_exact_accuracy == 0
    assert coverage.routes[0].trend.exact_accuracy_delta == 1
    assert coverage.routes[0].trend.recent_ev_compared_hands == 0
    assert coverage.routes[0].trend.previous_ev_compared_hands == 1
    assert coverage.routes[0].trend.average_ev_loss_delta_bb is None
    assert coverage.routes[0].street_counts == {"flop": 1, "turn": 1}
    assert coverage.routes[1].fallback_hands == 0
    assert coverage.routes[1].action_accuracy == 1
    assert coverage.routes[1].exact_accuracy == 1
    assert coverage.routes[1].ev_compared_hands == 0
    assert coverage.routes[1].average_ev_loss_bb is None
    assert coverage.routes[1].trend is not None
    assert coverage.routes[1].trend.action_accuracy_delta == 0
    assert coverage.routes[1].trend.exact_accuracy_delta == 0
    assert coverage.routes[1].street_counts == {"flop": 1, "river": 1}
    assert coverage.routes[2].fallback_hands == 0
    assert coverage.routes[2].trend is None
    assert len(coverage.fallback_reasons) == 1
    fallback_key = hashlib.sha256(unsupported_reason.encode("utf-8")).hexdigest()
    assert coverage.fallback_reasons[0].key == fallback_key
    assert coverage.fallback_reasons[0].reason == unsupported_reason
    assert coverage.fallback_reasons[0].hands == 2
    assert coverage.fallback_reasons[0].action_matches == 1
    assert coverage.fallback_reasons[0].exact_matches == 1
    assert coverage.fallback_reasons[0].action_accuracy == 0.5
    assert coverage.fallback_reasons[0].exact_accuracy == 0.5
    assert coverage.fallback_reasons[0].ev_compared_hands == 1
    assert coverage.fallback_reasons[0].average_ev_loss_bb == 0.4
    assert coverage.fallback_reasons[0].trend == coverage.routes[0].trend
    assert coverage.fallback_reasons[0].street_counts == {"flop": 1, "turn": 1}
    assert progress.recent_matching_hands == 6

    filtered = summarize_training(
        jobs,
        recent_limit=1,
        solver_fallback_key=fallback_key,
    )

    assert filtered.reviewed_hands == 6
    assert filtered.solver_coverage == coverage
    assert filtered.recent_matching_hands == 2
    assert [hand.job_id for hand in filtered.recent_hands] == ["4" * 32]

    route_filtered = summarize_training(
        jobs,
        recent_limit=1,
        solver_route_key=route_keys["postflop_solver"],
    )

    assert route_filtered.reviewed_hands == 6
    assert route_filtered.solver_coverage == coverage
    assert route_filtered.recent_matching_hands == 2
    assert [hand.job_id for hand in route_filtered.recent_hands] == ["2" * 32]

    unattributed_filtered = summarize_training(
        jobs,
        recent_limit=1,
        solver_unattributed=True,
    )

    assert unattributed_filtered.reviewed_hands == 6
    assert unattributed_filtered.solver_coverage == coverage
    assert unattributed_filtered.recent_matching_hands == 1
    assert [hand.job_id for hand in unattributed_filtered.recent_hands] == [
        "6" * 32
    ]


def test_summarize_training_calibrates_self_rated_certainty() -> None:
    candidates = {
        "candidates": [
            {"action": "fold", "sizing": None, "ev": 0.0},
            {"action": "call", "sizing": None, "ev": 1.0},
        ]
    }
    jobs = [
        reviewed_job(
            "1" * 32,
            "flop",
            "call",
            "call",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            recommendation_raw=candidates,
            decision_certainty="low",
        ),
        reviewed_job(
            "2" * 32,
            "turn",
            "fold",
            "call",
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            recommendation_raw=candidates,
            decision_certainty="high",
        ),
        reviewed_job(
            "3" * 32,
            "river",
            "call",
            "call",
            datetime(2026, 7, 3, tzinfo=timezone.utc),
            recommendation_raw=candidates,
            decision_certainty="high",
        ),
        reviewed_job(
            "4" * 32,
            "preflop",
            "call",
            "call",
            datetime(2026, 7, 4, tzinfo=timezone.utc),
        ),
    ]

    progress = summarize_training(jobs)

    assert [summary.certainty for summary in progress.certainty_summaries] == [
        "low",
        "high",
    ]
    low, high = progress.certainty_summaries
    assert low.hands == 1
    assert low.needs_review_hands == 0
    assert low.action_accuracy == 1
    assert low.exact_accuracy == 1
    assert low.average_ev_loss_bb == 0
    assert low.trend is None
    assert high.hands == 2
    assert high.needs_review_hands == 1
    assert high.action_accuracy == 0.5
    assert high.exact_accuracy == 0.5
    assert high.ev_compared_hands == 2
    assert high.average_ev_loss_bb == 0.5
    assert high.trend is not None
    assert high.trend.window_hands == 1
    assert high.trend.recent_action_accuracy == 1
    assert high.trend.previous_action_accuracy == 0
    assert high.trend.action_accuracy_delta == 1
    assert high.trend.recent_exact_accuracy == 1
    assert high.trend.previous_exact_accuracy == 0
    assert high.trend.exact_accuracy_delta == 1
    assert high.trend.recent_ev_compared_hands == 1
    assert high.trend.previous_ev_compared_hands == 1
    assert high.trend.recent_average_ev_loss_bb == 0
    assert high.trend.previous_average_ev_loss_bb == 1
    assert high.trend.average_ev_loss_delta_bb == -1
    assert progress.unrated_hands == 1
    assert progress.unrated_needs_review_hands == 0
    assert progress.recent_hands[0].decision_certainty is None
    assert progress.recent_hands[1].decision_certainty == "high"


def test_summarize_training_limits_recent_hands() -> None:
    jobs = [
        reviewed_job(
            f"{index:032x}",
            "river",
            "check",
            "check",
            datetime(2026, 7, index + 1, tzinfo=timezone.utc),
        )
        for index in range(4)
    ]

    progress = summarize_training(jobs, recent_limit=2)

    assert progress.reviewed_hands == 4
    assert len(progress.recent_hands) == 2
    assert progress.recent_hands[0].job_id == f"{3:032x}"


def test_summarize_training_lists_completed_lesson_notes_by_review_time() -> None:
    jobs = [
        reviewed_job(
            "1" * 32,
            "flop",
            "fold",
            "call",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            training_reviewed_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
            training_review_note="Respect the call price.",
        ),
        reviewed_job(
            "2" * 32,
            "turn",
            "fold",
            "raise",
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            training_reviewed_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
            training_review_note="Check blockers before folding.",
        ),
        reviewed_job(
            "3" * 32,
            "river",
            "call",
            "raise",
            datetime(2026, 7, 3, tzinfo=timezone.utc),
            training_review_note="This reopened note is still being revised.",
        ),
        reviewed_job(
            "4" * 32,
            "preflop",
            "call",
            "call",
            datetime(2026, 7, 4, tzinfo=timezone.utc),
            training_reviewed_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        ),
    ]

    progress = summarize_training(jobs, recent_limit=1, lesson_limit=1)

    assert progress.lesson_count == 2
    assert progress.lesson_matching_hands == 2
    assert len(progress.lesson_hands) == 1
    assert progress.lesson_hands[0].job_id == "2" * 32
    assert progress.lesson_hands[0].review_note == "Check blockers before folding."

    filtered = summarize_training(
        jobs,
        lesson_street="turn",
        lesson_query="BLOCKERS",
    )

    assert filtered.lesson_count == 2
    assert filtered.lesson_matching_hands == 1
    assert [hand.job_id for hand in filtered.lesson_hands] == ["2" * 32]

    unmatched = summarize_training(
        jobs,
        lesson_street="flop",
        lesson_query="blockers",
    )

    assert unmatched.lesson_count == 2
    assert unmatched.lesson_matching_hands == 0
    assert unmatched.lesson_hands == []

    document, exported_count = build_training_lessons_markdown(
        jobs,
        lesson_street="turn",
        lesson_query="BLOCKERS",
    )

    assert exported_count == 1
    assert document.startswith("# Poker Hero Lessons\n")
    assert "1 saved lesson note." in document
    assert "## Ah Kd - Turn" in document
    assert "- Board: Not recorded" in document
    assert "- You: Fold" in document
    assert "- Solver: Raise" in document
    assert "> Check blockers before folding." in document
    assert "Respect the call price." not in document


def test_training_lesson_export_uses_safe_code_span_delimiters() -> None:
    job = reviewed_job(
        "1" * 32,
        "flop",
        "check",
        "check",
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        training_reviewed_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
        training_review_note="Keep the metadata literal.",
    )
    job.original_filename = "`table`<strong>unsafe</strong>.png"
    assert job.approved_state is not None
    job.approved_state.hero_position = "cut``off"
    job.approved_state.opponent_position = "big``blind"

    document, exported_count = build_training_lessons_markdown([job])

    assert exported_count == 1
    assert "- Source: `` `table`<strong>unsafe</strong>.png ``" in document
    assert "- Position: ```cut``off```" in document
    assert "- Opponent position: ```big``blind```" in document
    assert "\\`" not in document


def test_training_lessons_can_prioritize_ev_loss_before_display_limit() -> None:
    highest_loss = reviewed_job(
        "1" * 32,
        "flop",
        "fold",
        "call",
        datetime(2026, 7, 1, tzinfo=timezone.utc),
        recommendation_raw={
            "candidates": [
                {"action": "fold", "sizing": None, "ev": -2.0},
                {"action": "call", "sizing": None, "ev": 0.0},
            ]
        },
        training_reviewed_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
        training_review_note="Study the highest-loss fold.",
    )
    lower_loss = reviewed_job(
        "2" * 32,
        "turn",
        "fold",
        "call",
        datetime(2026, 7, 2, tzinfo=timezone.utc),
        recommendation_raw={
            "candidates": [
                {"action": "fold", "sizing": None, "ev": -0.5},
                {"action": "call", "sizing": None, "ev": 0.0},
            ]
        },
        training_reviewed_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
        training_review_note="Study the lower-loss fold.",
    )
    ungraded = reviewed_job(
        "3" * 32,
        "river",
        "fold",
        "call",
        datetime(2026, 7, 3, tzinfo=timezone.utc),
        training_reviewed_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        training_review_note="Keep ungraded lessons available.",
    )
    highest_loss.original_filename = "highest-loss.png"
    lower_loss.original_filename = "lower-loss.png"
    ungraded.original_filename = "ungraded.png"
    jobs = [highest_loss, lower_loss, ungraded]

    recent = summarize_training(jobs, lesson_limit=2)
    prioritized = summarize_training(
        jobs,
        lesson_limit=2,
        lesson_order="ev_loss",
    )
    document, exported_count = build_training_lessons_markdown(
        jobs,
        lesson_order="ev_loss",
    )

    assert [hand.job_id for hand in recent.lesson_hands] == [
        ungraded.id,
        lower_loss.id,
    ]
    assert [hand.job_id for hand in prioritized.lesson_hands] == [
        highest_loss.id,
        lower_loss.id,
    ]
    assert exported_count == 3
    assert document.index("highest-loss.png") < document.index("lower-loss.png")
    assert document.index("lower-loss.png") < document.index("ungraded.png")


def test_summarize_training_compares_equal_recent_windows() -> None:
    candidates = {
        "candidates": [
            {"action": "fold", "sizing": None, "ev": 0.0},
            {"action": "call", "sizing": None, "ev": 1.0},
        ]
    }
    jobs = [
        reviewed_job(
            f"{index:032x}",
            "flop",
            "fold" if index < 2 else "call",
            "call",
            datetime(2026, 7, index + 1, tzinfo=timezone.utc),
            recommendation_raw=candidates,
        )
        for index in range(4)
    ]

    progress = summarize_training(jobs)

    assert progress.trend is not None
    assert progress.trend.window_hands == 2
    assert progress.trend.recent_action_accuracy == 1
    assert progress.trend.previous_action_accuracy == 0
    assert progress.trend.action_accuracy_delta == 1
    assert progress.trend.recent_exact_accuracy == 1
    assert progress.trend.previous_exact_accuracy == 0
    assert progress.trend.exact_accuracy_delta == 1
    assert progress.trend.recent_ev_compared_hands == 2
    assert progress.trend.previous_ev_compared_hands == 2
    assert progress.trend.recent_average_ev_loss_bb == 0
    assert progress.trend.previous_average_ev_loss_bb == 1
    assert progress.trend.average_ev_loss_delta_bb == -1


def test_summarize_training_groups_and_orders_action_differences() -> None:
    jobs = [
        reviewed_job(
            "1" * 32,
            "flop",
            "fold",
            "call",
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            recommendation_raw={
                "candidates": [
                    {"action": "fold", "sizing": None, "ev": 0.0},
                    {"action": "call", "sizing": None, "ev": 1.2},
                ]
            },
        ),
        reviewed_job(
            "2" * 32,
            "turn",
            "fold",
            "call",
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            training_reviewed_at=datetime(2026, 7, 6, tzinfo=timezone.utc),
        ),
        reviewed_job(
            "3" * 32,
            "river",
            "raise",
            "call",
            datetime(2026, 7, 3, tzinfo=timezone.utc),
            decision_sizing=4,
            recommendation_raw={
                "candidates": [
                    {"action": "raise", "sizing": 4, "ev": 0.0},
                    {"action": "call", "sizing": None, "ev": 2.0},
                ]
            },
        ),
        reviewed_job(
            "4" * 32,
            "river",
            "check",
            "bet",
            datetime(2026, 7, 4, tzinfo=timezone.utc),
            recommended_sizing=3,
        ),
        reviewed_job(
            "5" * 32,
            "river",
            "raise",
            "call",
            datetime(2026, 7, 5, tzinfo=timezone.utc),
            decision_sizing=4,
            recommendation_raw={
                "candidates": [
                    {
                        "action": "raise",
                        "sizing": 4,
                        "frequency": 0.2,
                    },
                    {
                        "action": "call",
                        "sizing": None,
                        "frequency": 0.8,
                    },
                ]
            },
        ),
    ]

    progress = summarize_training(jobs)
    raise_to_call = summarize_training(
        jobs,
        review_action_difference=("raise", "call"),
    )

    assert [
        (
            difference.decision_action,
            difference.recommended_action,
            difference.hands,
        )
        for difference in progress.action_differences
    ] == [
        ("fold", "call", 2),
        ("raise", "call", 1),
        ("check", "bet", 1),
    ]
    fold_to_call = progress.action_differences[0]
    assert fold_to_call.needs_review_hands == 1
    assert fold_to_call.ev_compared_hands == 1
    assert fold_to_call.average_ev_loss_bb == 1.2
    assert progress.action_differences[1].average_ev_loss_bb == 2
    assert progress.action_differences[2].average_ev_loss_bb is None
    assert raise_to_call.review_queue_hands == 1
    assert [hand.job_id for hand in raise_to_call.review_queue] == ["3" * 32]


def test_summarize_training_prioritizes_pending_action_differences() -> None:
    reviewed_at = datetime(2026, 7, 10, tzinfo=timezone.utc)
    actions = [
        ("fold", "call", reviewed_at),
        ("fold", "call", reviewed_at),
        ("fold", "call", reviewed_at),
        ("check", "bet", reviewed_at),
        ("check", "bet", reviewed_at),
        ("call", "raise", reviewed_at),
        ("bet", "raise", None),
    ]
    jobs = [
        reviewed_job(
            f"{index:032x}",
            "flop",
            decision_action,
            recommended_action,
            datetime(2026, 7, index, tzinfo=timezone.utc),
            training_reviewed_at=training_reviewed_at,
        )
        for index, (
            decision_action,
            recommended_action,
            training_reviewed_at,
        ) in enumerate(actions, start=1)
    ]

    progress = summarize_training(jobs)

    assert [
        (
            difference.decision_action,
            difference.recommended_action,
            difference.hands,
            difference.needs_review_hands,
        )
        for difference in progress.action_differences
    ] == [
        ("bet", "raise", 1, 1),
        ("fold", "call", 3, 0),
        ("check", "bet", 2, 0),
        ("call", "raise", 1, 0),
    ]


def test_summarize_training_limits_review_queue_independently() -> None:
    jobs = [
        reviewed_job(
            f"{index:032x}",
            "turn",
            "raise",
            "call",
            datetime(2026, 7, index + 1, tzinfo=timezone.utc),
            decision_sizing=4,
        )
        for index in range(4)
    ]

    progress = summarize_training(jobs, recent_limit=1, review_limit=2)

    assert progress.needs_review_hands == 4
    assert progress.review_queue_hands == 4
    assert len(progress.recent_hands) == 1
    assert [hand.job_id for hand in progress.review_queue] == [f"{3:032x}", f"{2:032x}"]


def test_summarize_training_prioritizes_review_queue_by_ev_loss() -> None:
    jobs = [
        reviewed_job(
            "1" * 32,
            "flop",
            "fold",
            "call",
            datetime(2026, 7, 5, tzinfo=timezone.utc),
            recommendation_raw={
                "candidates": [
                    {"action": "fold", "sizing": None, "ev": 0.0},
                    {"action": "call", "sizing": None, "ev": 1.2},
                ]
            },
        ),
        reviewed_job(
            "2" * 32,
            "turn",
            "fold",
            "call",
            datetime(2026, 7, 6, tzinfo=timezone.utc),
            recommendation_raw={
                "candidates": [
                    {"action": "fold", "sizing": None, "ev": 0.0},
                    {"action": "call", "sizing": None, "ev": 0.2},
                ]
            },
        ),
        reviewed_job(
            "3" * 32,
            "river",
            "fold",
            "call",
            datetime(2026, 7, 7, tzinfo=timezone.utc),
        ),
    ]

    progress = summarize_training(jobs, review_limit=2, review_order="ev_loss")
    complete_queue = summarize_training(jobs, review_limit=3, review_order="ev_loss")

    assert progress.needs_review_hands == 3
    assert [hand.job_id for hand in progress.recent_hands] == [
        "3" * 32,
        "2" * 32,
        "1" * 32,
    ]
    assert [hand.job_id for hand in progress.review_queue] == [
        "1" * 32,
        "2" * 32,
    ]
    assert [hand.ev_loss_bb for hand in progress.review_queue] == [1.2, 0.2]
    assert [hand.job_id for hand in complete_queue.review_queue] == [
        "1" * 32,
        "2" * 32,
        "3" * 32,
    ]
    assert complete_queue.review_queue[2].ev_loss_bb is None


def test_summarize_training_filters_review_street_before_ordering_and_limit() -> None:
    jobs = [
        reviewed_job(
            "1" * 32,
            "flop",
            "fold",
            "call",
            datetime(2026, 7, 5, tzinfo=timezone.utc),
            recommendation_raw={
                "candidates": [
                    {"action": "fold", "sizing": None, "ev": 0.0},
                    {"action": "call", "sizing": None, "ev": 0.4},
                ]
            },
        ),
        reviewed_job(
            "2" * 32,
            "turn",
            "fold",
            "call",
            datetime(2026, 7, 7, tzinfo=timezone.utc),
            recommendation_raw={
                "candidates": [
                    {"action": "fold", "sizing": None, "ev": 0.0},
                    {"action": "call", "sizing": None, "ev": 2.0},
                ]
            },
        ),
        reviewed_job(
            "3" * 32,
            "flop",
            "fold",
            "call",
            datetime(2026, 7, 6, tzinfo=timezone.utc),
            recommendation_raw={
                "candidates": [
                    {"action": "fold", "sizing": None, "ev": 0.0},
                    {"action": "call", "sizing": None, "ev": 0.8},
                ]
            },
        ),
    ]

    progress = summarize_training(
        jobs,
        review_limit=1,
        review_order="ev_loss",
        review_street="flop",
    )

    assert progress.needs_review_hands == 3
    assert progress.review_street_counts == {"flop": 2, "turn": 1}
    assert progress.review_queue_hands == 2
    assert [hand.job_id for hand in progress.review_queue] == ["3" * 32]
    assert [hand.job_id for hand in progress.recent_hands] == [
        "2" * 32,
        "3" * 32,
        "1" * 32,
    ]


def test_summarize_training_filters_pending_reviews_by_certainty() -> None:
    jobs = [
        reviewed_job(
            "1" * 32,
            "flop",
            "fold",
            "call",
            datetime(2026, 7, 5, tzinfo=timezone.utc),
            decision_certainty="high",
        ),
        reviewed_job(
            "2" * 32,
            "turn",
            "fold",
            "call",
            datetime(2026, 7, 6, tzinfo=timezone.utc),
            decision_certainty="low",
        ),
        reviewed_job(
            "3" * 32,
            "river",
            "fold",
            "call",
            datetime(2026, 7, 7, tzinfo=timezone.utc),
        ),
    ]

    high = summarize_training(jobs, review_certainty="high")
    unrated = summarize_training(jobs, review_certainty="unrated")

    assert high.needs_review_hands == 3
    assert high.review_queue_hands == 1
    assert [hand.job_id for hand in high.review_queue] == ["1" * 32]
    assert high.review_queue[0].decision_certainty == "high"
    assert unrated.needs_review_hands == 3
    assert unrated.review_queue_hands == 1
    assert [hand.job_id for hand in unrated.review_queue] == ["3" * 32]
    assert unrated.review_queue[0].decision_certainty is None
    assert unrated.unrated_hands == 1
    assert unrated.unrated_needs_review_hands == 1


def test_summarize_training_excludes_completed_reviews_from_pending_queue() -> None:
    completed_at = datetime(2026, 7, 10, tzinfo=timezone.utc)
    jobs = [
        reviewed_job(
            "7" * 32,
            "turn",
            "raise",
            "call",
            datetime(2026, 7, 7, tzinfo=timezone.utc),
            decision_sizing=5,
            training_reviewed_at=completed_at,
        ),
        reviewed_job(
            "8" * 32,
            "river",
            "bet",
            "bet",
            datetime(2026, 7, 8, tzinfo=timezone.utc),
            decision_sizing=5,
            recommended_sizing=6,
        ),
    ]

    progress = summarize_training(jobs)

    assert progress.reviewed_hands == 2
    assert progress.needs_review_hands == 1
    assert progress.review_queue_hands == 1
    assert [hand.job_id for hand in progress.review_queue] == ["8" * 32]
    assert progress.recent_hands[1].reviewed_at == completed_at


def test_summarize_training_applies_sizing_tolerance() -> None:
    jobs = [
        reviewed_job(
            "5" * 32,
            "flop",
            "bet",
            "bet",
            datetime(2026, 7, 5, tzinfo=timezone.utc),
            decision_sizing=5,
            recommended_sizing=5.005,
        ),
        reviewed_job(
            "6" * 32,
            "flop",
            "bet",
            "bet",
            datetime(2026, 7, 6, tzinfo=timezone.utc),
            decision_sizing=5,
            recommended_sizing=5.02,
        ),
        reviewed_job(
            "7" * 32,
            "flop",
            "bet",
            "bet",
            datetime(2026, 7, 7, tzinfo=timezone.utc),
            decision_sizing=5.01,
            recommended_sizing=5,
        ),
        reviewed_job(
            "8" * 32,
            "flop",
            "bet",
            "bet",
            datetime(2026, 7, 8, tzinfo=timezone.utc),
            decision_sizing=7.5099999995,
            recommended_sizing=7.5,
        ),
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 4
    assert progress.exact_matches == 2
    assert [hand.outcome for hand in progress.recent_hands] == [
        "match",
        "same_action",
        "same_action",
        "match",
    ]
    assert [hand.job_id for hand in progress.review_queue] == [
        "7" * 32,
        "6" * 32,
    ]


def test_summarize_training_scores_meaningful_solver_mixes() -> None:
    jobs = [
        reviewed_job(
            "9" * 32,
            "turn",
            "raise",
            "call",
            datetime(2026, 7, 9, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "frequency": 0.8},
                    {"action": "raise", "sizing": 8, "frequency": 0.2},
                ]
            },
        ),
        reviewed_job(
            "a" * 32,
            "river",
            "raise",
            "call",
            datetime(2026, 7, 10, tzinfo=timezone.utc),
            decision_sizing=9,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "frequency": 0.8},
                    {"action": "raise", "sizing": 8, "frequency": 0.2},
                ]
            },
        ),
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 2
    assert progress.exact_matches == 1
    assert progress.different_actions == 0
    assert progress.needs_review_hands == 1
    assert [hand.outcome for hand in progress.recent_hands] == [
        "mixed_action",
        "mixed",
    ]
    assert [hand.job_id for hand in progress.review_queue] == ["a" * 32]


def test_summarize_training_applies_solver_mix_frequency_boundary() -> None:
    jobs = [
        reviewed_job(
            "b" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 11, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "frequency": 0.95},
                    {"action": "raise", "sizing": 8, "frequency": 0.05},
                ]
            },
        ),
        reviewed_job(
            "c" * 32,
            "turn",
            "raise",
            "call",
            datetime(2026, 7, 12, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "frequency": 0.950001},
                    {"action": "raise", "sizing": 8, "frequency": 0.049999},
                ]
            },
        ),
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.different_actions == 1
    assert progress.needs_review_hands == 1
    assert [hand.outcome for hand in progress.recent_hands] == [
        "different",
        "mixed",
    ]
    assert [hand.job_id for hand in progress.review_queue] == ["c" * 32]


def test_summarize_training_keeps_supported_mix_with_nonnumeric_ev_ungraded() -> None:
    jobs = [
        reviewed_job(
            "d" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 13, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 1.4, "frequency": 0.78},
                    {"action": "raise", "sizing": 8, "ev": "1.1", "frequency": 0.2},
                    {"action": "fold", "sizing": None, "ev": 0, "frequency": 0.02},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.different_actions == 0
    assert progress.needs_review_hands == 0
    assert progress.ev_compared_hands == 0
    assert progress.average_ev_loss_bb is None
    assert progress.recent_hands[0].outcome == "mixed"
    assert progress.recent_hands[0].ev_loss_bb is None
    assert progress.review_queue == []


def test_summarize_training_rejects_nonnumeric_recommended_line_ev() -> None:
    jobs = [
        reviewed_job(
            "e" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 14, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": "1.4", "frequency": 0.78},
                    {"action": "raise", "sizing": 8, "ev": 1.1, "frequency": 0.2},
                    {"action": "fold", "sizing": None, "ev": 0, "frequency": 0.02},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.different_actions == 0
    assert progress.needs_review_hands == 0
    assert progress.ev_compared_hands == 0
    assert progress.average_ev_loss_bb is None
    assert progress.recent_hands[0].outcome == "mixed"
    assert progress.recent_hands[0].ev_loss_bb is None
    assert progress.review_queue == []


def test_summarize_training_ignores_unrelated_nonnumeric_candidate_ev() -> None:
    jobs = [
        reviewed_job(
            "e" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 14, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 1.4, "frequency": 0.78},
                    {"action": "raise", "sizing": 8, "ev": 1.1, "frequency": 0.2},
                    {"action": "fold", "sizing": None, "ev": "99", "frequency": 0.02},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.different_actions == 0
    assert progress.needs_review_hands == 0
    assert progress.ev_compared_hands == 1
    assert progress.average_ev_loss_bb == pytest.approx(0.3)
    assert progress.recent_hands[0].outcome == "mixed"
    assert progress.recent_hands[0].ev_loss_bb == pytest.approx(0.3)
    assert progress.review_queue == []


@pytest.mark.parametrize("invalid_sizing", [-1, 0])
def test_summarize_training_ignores_unrelated_invalid_candidate_sizing(
    invalid_sizing: int,
) -> None:
    jobs = [
        reviewed_job(
            "f" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 15, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 1.4, "frequency": 0.78},
                    {"action": "raise", "sizing": 8, "ev": 1.1, "frequency": 0.2},
                    {
                        "action": "bet",
                        "sizing": invalid_sizing,
                        "ev": 99,
                        "frequency": 0.02,
                    },
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.different_actions == 0
    assert progress.needs_review_hands == 0
    assert progress.ev_compared_hands == 1
    assert progress.average_ev_loss_bb == pytest.approx(0.3)
    assert progress.recent_hands[0].outcome == "mixed"
    assert progress.recent_hands[0].ev_loss_bb == pytest.approx(0.3)
    assert progress.review_queue == []


def test_summarize_training_ignores_unrelated_invalid_candidate_action() -> None:
    jobs = [
        reviewed_job(
            "0" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 16, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 1.4, "frequency": 0.78},
                    {"action": "raise", "sizing": 8, "ev": 1.1, "frequency": 0.2},
                    {"action": "jam", "sizing": None, "ev": 99, "frequency": 0.02},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.different_actions == 0
    assert progress.needs_review_hands == 0
    assert progress.ev_compared_hands == 1
    assert progress.average_ev_loss_bb == pytest.approx(0.3)
    assert progress.recent_hands[0].outcome == "mixed"
    assert progress.recent_hands[0].ev_loss_bb == pytest.approx(0.3)
    assert progress.review_queue == []


def test_summarize_training_ev_grading_does_not_require_frequency() -> None:
    jobs = [
        reviewed_job(
            "1" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 17, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 1.4, "frequency": 0.78},
                    {"action": "raise", "sizing": 8, "ev": 1.1, "frequency": 0.2},
                    {"action": "bet", "sizing": 6, "ev": 2.0, "frequency": "20%"},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.different_actions == 0
    assert progress.needs_review_hands == 0
    assert progress.ev_compared_hands == 1
    assert progress.average_ev_loss_bb == pytest.approx(0.9)
    assert progress.recent_hands[0].outcome == "mixed"
    assert progress.recent_hands[0].ev_loss_bb == pytest.approx(0.9)
    assert progress.review_queue == []


def test_summarize_training_policy_support_requires_valid_frequency() -> None:
    jobs = [
        reviewed_job(
            "2" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 18, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 1.4, "frequency": 0.78},
                    {"action": "raise", "sizing": 8, "ev": 1.1, "frequency": "20%"},
                    {"action": "fold", "sizing": None, "ev": 0, "frequency": 0.02},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 0
    assert progress.exact_matches == 0
    assert progress.different_actions == 1
    assert progress.needs_review_hands == 1
    assert progress.ev_compared_hands == 1
    assert progress.average_ev_loss_bb == pytest.approx(0.3)
    assert progress.recent_hands[0].outcome == "different"
    assert progress.recent_hands[0].ev_loss_bb == pytest.approx(0.3)
    assert [hand.job_id for hand in progress.review_queue] == ["2" * 32]


def test_summarize_training_policy_support_rejects_frequency_above_one() -> None:
    jobs = [
        reviewed_job(
            "3" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 19, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 1.4, "frequency": 0.78},
                    {"action": "raise", "sizing": 8, "ev": 1.1, "frequency": 1.000001},
                    {"action": "fold", "sizing": None, "ev": 0, "frequency": 0.02},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 0
    assert progress.exact_matches == 0
    assert progress.different_actions == 1
    assert progress.needs_review_hands == 1
    assert progress.ev_compared_hands == 1
    assert progress.average_ev_loss_bb == pytest.approx(0.3)
    assert progress.recent_hands[0].outcome == "different"
    assert progress.recent_hands[0].ev_loss_bb == pytest.approx(0.3)
    assert [hand.job_id for hand in progress.review_queue] == ["3" * 32]


def test_summarize_training_policy_support_accepts_frequency_at_one() -> None:
    jobs = [
        reviewed_job(
            "9" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 25, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 1.4, "frequency": 0.78},
                    {"action": "raise", "sizing": 8, "ev": 1.1, "frequency": 1.0},
                    {"action": "fold", "sizing": None, "ev": 0, "frequency": 0.02},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.different_actions == 0
    assert progress.needs_review_hands == 0
    assert progress.ev_compared_hands == 1
    assert progress.average_ev_loss_bb == pytest.approx(0.3)
    assert progress.recent_hands[0].outcome == "mixed"
    assert progress.recent_hands[0].ev_loss_bb == pytest.approx(0.3)
    assert progress.review_queue == []


def test_summarize_training_policy_support_requires_explicit_frequency() -> None:
    jobs = [
        reviewed_job(
            "4" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 20, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 1.4, "frequency": 0.78},
                    {"action": "raise", "sizing": 8, "ev": 1.1},
                    {"action": "fold", "sizing": None, "ev": 0, "frequency": 0.02},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 0
    assert progress.exact_matches == 0
    assert progress.different_actions == 1
    assert progress.needs_review_hands == 1
    assert progress.ev_compared_hands == 1
    assert progress.average_ev_loss_bb == pytest.approx(0.3)
    assert progress.recent_hands[0].outcome == "different"
    assert progress.recent_hands[0].ev_loss_bb == pytest.approx(0.3)
    assert [hand.job_id for hand in progress.review_queue] == ["4" * 32]


def test_summarize_training_recommended_line_requires_explicit_sizing() -> None:
    jobs = [
        reviewed_job(
            "5" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 21, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "ev": 1.4, "frequency": 0.78},
                    {"action": "raise", "sizing": 8, "ev": 1.1, "frequency": 0.2},
                    {"action": "fold", "sizing": None, "ev": 0, "frequency": 0.02},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.different_actions == 0
    assert progress.needs_review_hands == 0
    assert progress.ev_compared_hands == 0
    assert progress.average_ev_loss_bb is None
    assert progress.recent_hands[0].outcome == "mixed"
    assert progress.recent_hands[0].ev_loss_bb is None
    assert progress.review_queue == []


def test_summarize_training_recommended_line_rejects_invalid_sizing() -> None:
    jobs = [
        reviewed_job(
            "6" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 22, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": 2.5, "ev": 1.4, "frequency": 0.78},
                    {"action": "raise", "sizing": 8, "ev": 1.1, "frequency": 0.2},
                    {"action": "fold", "sizing": None, "ev": 0, "frequency": 0.02},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.different_actions == 0
    assert progress.needs_review_hands == 0
    assert progress.ev_compared_hands == 0
    assert progress.average_ev_loss_bb is None
    assert progress.recent_hands[0].outcome == "mixed"
    assert progress.recent_hands[0].ev_loss_bb is None
    assert progress.review_queue == []


def test_summarize_training_recommended_line_ev_does_not_require_frequency() -> None:
    jobs = [
        reviewed_job(
            "7" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 23, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 1.4},
                    {"action": "raise", "sizing": 8, "ev": 1.1, "frequency": 0.2},
                    {"action": "fold", "sizing": None, "ev": 0, "frequency": 0.02},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.different_actions == 0
    assert progress.needs_review_hands == 0
    assert progress.ev_compared_hands == 1
    assert progress.average_ev_loss_bb == pytest.approx(0.3)
    assert progress.recent_hands[0].outcome == "mixed"
    assert progress.recent_hands[0].ev_loss_bb == pytest.approx(0.3)
    assert progress.review_queue == []


def test_summarize_training_recommended_line_ev_ignores_malformed_frequency() -> None:
    jobs = [
        reviewed_job(
            "8" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 24, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 1.4, "frequency": "78%"},
                    {"action": "raise", "sizing": 8, "ev": 1.1, "frequency": 0.2},
                    {"action": "fold", "sizing": None, "ev": 0, "frequency": 0.02},
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.different_actions == 0
    assert progress.needs_review_hands == 0
    assert progress.ev_compared_hands == 1
    assert progress.average_ev_loss_bb == pytest.approx(0.3)
    assert progress.recent_hands[0].outcome == "mixed"
    assert progress.recent_hands[0].ev_loss_bb == pytest.approx(0.3)
    assert progress.review_queue == []


def test_summarize_training_reports_available_candidate_ev_loss() -> None:
    jobs = [
        reviewed_job(
            "d" * 32,
            "flop",
            "call",
            "raise",
            datetime(2026, 7, 13, tzinfo=timezone.utc),
            recommended_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "fold", "sizing": None, "ev": 0.0},
                    {"action": "call", "sizing": None, "ev": 2.7},
                    {"action": "raise", "sizing": 8, "ev": 2.82},
                ]
            },
        ),
        reviewed_job(
            "e" * 32,
            "flop",
            "raise",
            "raise",
            datetime(2026, 7, 14, tzinfo=timezone.utc),
            decision_sizing=8,
            recommended_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "sizing": None, "ev": 2.8},
                    {"action": "raise", "sizing": 8, "ev": 2.82},
                ]
            },
        ),
        reviewed_job(
            "f" * 32,
            "turn",
            "bet",
            "bet",
            datetime(2026, 7, 15, tzinfo=timezone.utc),
            decision_sizing=6,
            recommended_sizing=6,
            recommendation_raw={
                "candidates": [
                    {"action": "check", "sizing": None, "ev": 1.4},
                    {"action": "bet", "sizing": 5, "ev": 1.5},
                ]
            },
        ),
    ]

    progress = summarize_training(jobs)

    assert progress.ev_compared_hands == 2
    assert progress.average_ev_loss_bb == pytest.approx(0.06)
    assert progress.recent_hands[1].ev_loss_bb == 0
    assert progress.recent_hands[2].ev_loss_bb == pytest.approx(0.12)
    assert progress.recent_hands[0].ev_loss_bb is None
    assert progress.street_summaries[0].ev_compared_hands == 2
    assert progress.street_summaries[0].average_ev_loss_bb == pytest.approx(0.06)
    assert progress.street_summaries[1].ev_compared_hands == 0
    assert progress.street_summaries[1].average_ev_loss_bb is None


def test_summarize_training_rejects_malformed_candidate_ev_metadata() -> None:
    jobs = [
        reviewed_job(
            f"{index + 16:032x}",
            "river",
            "call",
            "raise",
            datetime(2026, 7, 16 + index, tzinfo=timezone.utc),
            recommended_sizing=8,
            recommendation_raw={"candidates": candidates},
        )
        for index, candidates in enumerate(
            [
                [{"action": "call", "sizing": None, "ev": "2.4"}],
                [{"action": "call", "ev": 2.4}],
                [{"action": "call", "sizing": 0, "ev": 2.4}],
                [{"action": "unknown", "sizing": None, "ev": 2.4}],
                [{"action": "call", "sizing": None, "ev": float("nan")}],
                [{"action": "call", "sizing": None, "ev": 2.4}],
                [
                    {"action": "fold", "sizing": None, "ev": 0.0},
                    {"action": "call", "sizing": None, "ev": 2.4},
                ],
            ]
        )
    ]

    progress = summarize_training(jobs)

    assert progress.ev_compared_hands == 0
    assert progress.average_ev_loss_bb is None
    assert all(hand.ev_loss_bb is None for hand in progress.recent_hands)


@pytest.mark.parametrize(
    "candidates",
    [
        [
            {
                "action": "raise",
                "sizing": 8,
                "ev": 1.4,
                "frequency": 1.0,
            }
        ],
        [
            {
                "action": "raise",
                "sizing": 8,
                "ev": 1.4,
                "frequency": 1.0,
            },
            {
                "action": "raise",
                "sizing": 8.001,
                "ev": 1.3,
                "frequency": 0.0,
            },
        ],
        [
            {
                "action": "raise",
                "sizing": 8 + index / 200_000,
                "ev": 1.4,
                "frequency": 1.0,
            }
            for index in range(1_000)
        ],
    ],
    ids=["single", "duplicate", "large-equivalent"],
)
def test_summarize_training_does_not_grade_without_distinct_candidate_ev(
    candidates: list[dict[str, object]],
) -> None:
    jobs = [
        reviewed_job(
            "d" * 32,
            "flop",
            "raise",
            "raise",
            datetime(2026, 7, 23, tzinfo=timezone.utc),
            decision_sizing=8,
            recommended_sizing=8,
            recommendation_raw={"candidates": candidates},
        )
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 1
    assert progress.exact_matches == 1
    assert progress.ev_compared_hands == 0
    assert progress.average_ev_loss_bb is None
    assert progress.recent_hands[0].outcome == "match"
    assert progress.recent_hands[0].ev_loss_bb is None


@pytest.mark.parametrize(
    "candidate_sizings",
    [
        [8, 8.01],
        [8.009, 8, 8.018],
        [8, 8.018, 8.009],
    ],
    ids=["boundary", "bridge-first", "endpoints-first"],
)
def test_summarize_training_grades_distinct_candidates_regardless_of_order(
    candidate_sizings: list[float],
) -> None:
    jobs = [
        reviewed_job(
            "e" * 32,
            "flop",
            "raise",
            "raise",
            datetime(2026, 7, 24, tzinfo=timezone.utc),
            decision_sizing=8,
            recommended_sizing=8,
            recommendation_raw={
                "candidates": [
                    {
                        "action": "raise",
                        "sizing": candidate_sizing,
                        "ev": 1.4 if candidate_sizing == 8 else 1.3,
                    }
                    for candidate_sizing in candidate_sizings
                ]
            },
        )
    ]

    progress = summarize_training(jobs)

    assert progress.ev_compared_hands == 1
    assert progress.average_ev_loss_bb == 0
    assert progress.recent_hands[0].ev_loss_bb == 0


def test_summarize_training_ignores_noise_and_malformed_policy_candidates() -> None:
    jobs = [
        reviewed_job(
            "b" * 32,
            "flop",
            "raise",
            "call",
            datetime(2026, 7, 11, tzinfo=timezone.utc),
            decision_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "raise", "sizing": 8, "frequency": 0.049},
                    {"action": "raise", "sizing": 8, "frequency": "20%"},
                    {"action": "raise", "frequency": 0.2},
                    {"action": "raise", "sizing": None, "frequency": 0.2},
                    {"action": "raise", "sizing": 8, "frequency": True},
                ]
            },
        ),
        reviewed_job(
            "c" * 32,
            "turn",
            "call",
            "raise",
            datetime(2026, 7, 12, tzinfo=timezone.utc),
            recommended_sizing=8,
            recommendation_raw={
                "candidates": [
                    {"action": "call", "frequency": 0.2},
                ]
            },
        ),
    ]

    progress = summarize_training(jobs)

    assert progress.action_matches == 0
    assert progress.exact_matches == 0
    assert progress.different_actions == 2
    assert progress.needs_review_hands == 2
    assert [hand.outcome for hand in progress.recent_hands] == [
        "different",
        "different",
    ]


def test_summarize_training_handles_empty_history() -> None:
    progress = summarize_training([])

    assert progress.reviewed_hands == 0
    assert progress.needs_review_hands == 0
    assert progress.action_accuracy == 0
    assert progress.exact_accuracy == 0
    assert progress.ev_compared_hands == 0
    assert progress.average_ev_loss_bb is None
    assert progress.solver_coverage.total_hands == 0
    assert progress.solver_coverage.routes == []
    assert progress.solver_coverage.fallback_reasons == []
    assert progress.street_summaries == []
    assert progress.recent_hands == []
    assert progress.review_queue == []
