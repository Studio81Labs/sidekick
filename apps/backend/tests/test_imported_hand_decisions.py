from __future__ import annotations

import copy
from decimal import Decimal
from typing import Literal

import pytest
from pydantic import ValidationError

from app.domain.imported_hands import decisions
from app.domain.imported_hands import (
    DeletionReceipt,
    DeletionRequest,
    ExcludedHeroAction,
    HandDecisionExtraction,
    HeroActionContext,
    HeroDecisionPoint,
    ImportProvenance,
    ImportedHandLifecycle,
    ImportedHandRecord,
    ImportedHandState,
    UserCorrection,
    extract_hero_decision_points,
)
from test_imported_hand_models import (
    IDENTITY,
    NOW,
    ante_decision_record,
    automatic_action,
    contested_decision_record,
    decision_context_board,
    extraction_ready_state_payload,
    extraction_record_for_state,
    extraction_record_for_streets,
    forced_post,
    full_raise_decision_record,
    heads_up_shove_and_call_decision_record,
    hero_facing_a_raise_decision_record,
    multi_street_decision_record,
    origin_confirmation_record,
    raw_source,
    reapproval_extraction_record,
    short_all_in_raise_decision_record,
    short_all_in_with_live_caller_decision_record,
    short_stacked_hero_decision_record,
    state_with_reviewed_action_origin,
    unmarked_all_in_blind_decision_record,
    user_confirmed_origin_corrections,
    wager_action,
)


def baseline_decision_record() -> ImportedHandRecord:
    """Build the package's extraction-ready record: hero posts, then calls."""

    return extraction_record_for_state(
        ImportedHandState.model_validate(extraction_ready_state_payload())
    )


def returned_post(
    sequence: int,
    actor_id: str,
    *,
    amount: Decimal,
    total: Decimal,
) -> dict[str, object]:
    """Return an uncalled-return post attributed to an explicit actor."""

    return {
        **forced_post(sequence, "uncalled_return", amount=amount, total=total),
        "actor_id": actor_id,
    }


def big_blind_walk_record() -> ImportedHandRecord:
    """Build a hand where hero only posts the big blind and everybody folds."""

    return extraction_record_for_streets(
        [
            {
                "street": "preflop",
                "actions": [
                    wager_action(
                        0,
                        "villain",
                        "post_small_blind",
                        amount=Decimal("0.5"),
                        total=Decimal("0.5"),
                    ),
                    wager_action(
                        1,
                        "hero",
                        "post_big_blind",
                        amount=Decimal("1"),
                        total=Decimal("1"),
                    ),
                    wager_action(2, "villain", "fold", total=Decimal("0.5")),
                    returned_post(
                        3,
                        "hero",
                        amount=Decimal("0.5"),
                        total=Decimal("0.5"),
                    ),
                ],
            }
        ],
        button_seat=2,
        configured_blinds=True,
        stated_gross=Decimal("1"),
    )


def hero_fold_decision_record() -> ImportedHandRecord:
    """Build a hand whose single hero decision is a preflop fold."""

    payload = extraction_ready_state_payload()
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(2, "hero", "fold", total=Decimal("0.5")),
                returned_post(
                    3,
                    "villain",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
            ],
        }
    ]
    payload["results"] = {"stated_pot": {"gross_total": Decimal("1")}}
    return extraction_record_for_state(ImportedHandState.model_validate(payload))


def hero_all_in_decision_record() -> ImportedHandRecord:
    """Build a hand where hero shoves preflop and the villains play on alone."""

    board = decision_context_board()
    payload = extraction_ready_state_payload()
    payload["game"]["table_size"] = 3
    payload["seats"][0]["starting_stack"] = Decimal("5")
    payload["seats"].append(
        {
            "seat_number": 3,
            "player_id": "villain-2",
            "starting_stack": Decimal("100"),
            "participation": "dealt_in",
        }
    )
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "villain-2",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    2,
                    "hero",
                    "raise",
                    amount=Decimal("5"),
                    total=Decimal("5"),
                    all_in=True,
                ),
                wager_action(
                    3,
                    "villain",
                    "call",
                    amount=Decimal("4.5"),
                    total=Decimal("5"),
                ),
                wager_action(
                    4,
                    "villain-2",
                    "call",
                    amount=Decimal("4"),
                    total=Decimal("5"),
                ),
            ],
        },
        {
            "street": "flop",
            "board_cards": board[:3],
            "actions": [
                wager_action(0, "villain", "check", total=Decimal(0)),
                wager_action(
                    1,
                    "villain-2",
                    "bet",
                    amount=Decimal("10"),
                    total=Decimal("10"),
                ),
                wager_action(2, "villain", "fold", total=Decimal(0)),
                returned_post(
                    3,
                    "villain-2",
                    amount=Decimal("10"),
                    total=Decimal(0),
                ),
            ],
        },
        {"street": "turn", "board_cards": board[:4], "actions": []},
        {"street": "river", "board_cards": board, "actions": []},
    ]
    payload["results"] = {"stated_pot": {"gross_total": Decimal("15")}}
    return extraction_record_for_state(ImportedHandState.model_validate(payload))


def hero_automatic_action_record() -> ImportedHandRecord:
    """Build a hand with one hero decision plus an auto-check and auto-fold."""

    board = decision_context_board()
    payload = extraction_ready_state_payload()
    auto_fold = automatic_action(1, "hero", "fold", total=Decimal(0))
    auto_fold["origin"]["automatic_reason"] = "disconnect"
    payload["streets"] = [
        {
            "street": "preflop",
            "actions": [
                wager_action(
                    0,
                    "hero",
                    "post_small_blind",
                    amount=Decimal("0.5"),
                    total=Decimal("0.5"),
                ),
                wager_action(
                    1,
                    "villain",
                    "post_big_blind",
                    amount=Decimal("1"),
                    total=Decimal("1"),
                ),
                wager_action(
                    2,
                    "hero",
                    "call",
                    amount=Decimal("0.5"),
                    total=Decimal("1"),
                ),
                wager_action(3, "villain", "check", total=Decimal("1")),
            ],
        },
        {
            "street": "flop",
            "board_cards": board[:3],
            "actions": [
                wager_action(0, "villain", "check", total=Decimal(0)),
                automatic_action(1, "hero", "check", total=Decimal(0)),
            ],
        },
        {
            "street": "turn",
            "board_cards": board[:4],
            "actions": [
                wager_action(
                    0,
                    "villain",
                    "bet",
                    amount=Decimal("2"),
                    total=Decimal("2"),
                ),
                auto_fold,
                returned_post(2, "villain", amount=Decimal("2"), total=Decimal(0)),
            ],
        },
    ]
    payload["results"] = {"stated_pot": {"gross_total": Decimal("2")}}
    return extraction_record_for_state(ImportedHandState.model_validate(payload))


def unresolved_conflict_record() -> ImportedHandRecord:
    """Build an active extraction-ready record with an unresolved conflict."""

    record = baseline_decision_record()
    return ImportedHandRecord.model_validate(
        {
            **record.model_dump(mode="python"),
            "raw_sources": [
                *(raw.model_dump(mode="python") for raw in record.raw_sources),
                raw_source(
                    raw_source_id="file-2",
                    raw_text="conflicting source\n",
                ).model_dump(mode="python"),
            ],
            "conflicts": [
                {
                    "conflict_id": "conflict-1",
                    "raw_source_ids": ["file-1", "file-2"],
                    "detected_ids": [],
                    "active_canonical_revision_at_creation": 1,
                }
            ],
        }
    )


def broken_lineage_record() -> ImportedHandRecord:
    """Build a copy whose canonical revision numbering is no longer contiguous."""

    record = baseline_decision_record()
    return record.model_copy(
        update={
            "canonical_revisions": [
                record.canonical_revisions[0].model_copy(update={"revision": 2})
            ]
        }
    )


def inactive_record(
    status: Literal[
        "pending_review",
        "withdrawn",
        "rejected",
        "deletion_pending",
        "deleted",
    ],
) -> ImportedHandRecord:
    """Build a record outside the active, user-approved learning boundary."""

    record = baseline_decision_record()
    if status == "pending_review":
        return ImportedHandRecord(
            identity=record.identity,
            raw_sources=record.raw_sources,
            detections=record.detections,
            lifecycle={"status": "pending_review", "changed_at": NOW},
        )
    if status == "deletion_pending":
        return record.model_copy(
            update={
                "lifecycle": ImportedHandLifecycle(
                    status="deletion_pending",
                    deletion_generation=1,
                    changed_at=NOW,
                    deletion_request=DeletionRequest(
                        generation=1,
                        requested_at=NOW,
                    ),
                )
            }
        )
    if status == "deleted":
        return ImportedHandRecord(
            identity=None,
            lifecycle={
                "status": "deleted",
                "deletion_generation": 2,
                "changed_at": NOW,
                "reason": "purged",
            },
            deletion_receipt=DeletionReceipt(
                receipt_id="deletion-2",
                generation=2,
                deleted_at=NOW,
                tombstone_sha256="b" * 64,
            ),
        )
    return record.model_copy(
        update={"lifecycle": ImportedHandLifecycle(status=status, changed_at=NOW)}
    )


def hero_actions(record: ImportedHandRecord) -> list[tuple[str, object]]:
    """Return hero's ordered actions from the record's active canonical state."""

    state = record.active_state_for_extraction
    assert state is not None
    return [
        (street.street, action)
        for street in state.streets
        for action in street.actions
        if action.actor_id == state.hero_player_id
    ]


def test_extraction_orders_every_street_decision_of_a_multi_street_hand() -> None:
    record = multi_street_decision_record()
    state = record.active_state_for_extraction

    extraction = extract_hero_decision_points(record)

    assert state is not None
    assert extraction.outcome == "decisions"
    assert extraction.rejection is None
    assert extraction.identity == IDENTITY
    assert extraction.canonical_revision == 1
    assert extraction.deletion_generation == 0
    assert [point.decision_index for point in extraction.decision_points] == [
        0,
        1,
        2,
        3,
    ]
    assert [
        (point.street, point.action_sequence)
        for point in extraction.decision_points
    ] == [("preflop", 2), ("flop", 1), ("turn", 1), ("river", 1)]
    assert [point.state.street for point in extraction.decision_points] == [
        "preflop",
        "flop",
        "turn",
        "river",
    ]
    assert [
        point.state.board_cards for point in extraction.decision_points
    ] == [street.board_cards for street in state.streets]
    assert [
        len(point.state.board_cards) for point in extraction.decision_points
    ] == [0, 3, 4, 5]

    hero_history = [action for _, action in hero_actions(record)]
    graded = [action for action in hero_history if action.is_player_decision]
    assert len(graded) == 4
    for point, action in zip(extraction.decision_points, graded, strict=True):
        assert point.table_action.action_type == action.action_type
        assert point.table_action.amount == action.amount
        assert point.table_action.total_committed == action.total_committed
        assert point.table_action.all_in == action.all_in
        assert point.table_action.origin == action.origin
        assert point.table_action.evidence == action.evidence

    assert all(
        (
            point.identity,
            point.chronology,
            point.provenance,
            point.canonical_revision,
            point.deletion_generation,
        )
        == (
            IDENTITY,
            state.chronology,
            record.raw_sources[0].provenance,
            1,
            0,
        )
        for point in extraction.decision_points
    )
    # R5: a low-confidence detected field is preserved, never a gate.
    assert record.detections[0].field_evidence[
        "/hero_player_id"
    ].confidence == Decimal("0.40")


def test_extraction_copies_the_aggregate_chip_context_without_recomputing_it(
) -> None:
    record = multi_street_decision_record()
    state = record.active_state_for_extraction
    contexts = record.active_hero_decision_contexts

    extraction = extract_hero_decision_points(record)

    assert state is not None
    assert len(contexts) == len(extraction.decision_points) == 4
    for point, context in zip(
        extraction.decision_points,
        contexts,
        strict=True,
    ):
        assert point.state.committed_pot_before_street == (
            context.committed_pot_before_street
        )
        assert point.state.pot_before_action == context.pot_before_action
        assert point.state.current_wager == context.current_wager
        assert point.state.amount_to_call == context.amount_to_call
        assert point.state.last_full_wager_increment == (
            context.last_full_wager_increment
        )
        assert point.state.raise_reopened == context.raise_reopened
        assert point.state.hero_stack_before_action == (
            context.hero_stack_before_action
        )
        assert point.state.seats == context.seats
        assert [
            (
                entry.street,
                [
                    (
                        item.sequence,
                        item.player_id,
                        item.action_type,
                        item.amount,
                        item.total_committed,
                        item.all_in,
                    )
                    for item in entry.actions
                ],
            )
            for entry in point.state.action_history
        ] == [
            (
                slice_.street,
                [
                    (
                        resolved.action.sequence,
                        resolved.action.actor_id,
                        resolved.action.action_type,
                        resolved.amount,
                        resolved.total_committed,
                        resolved.action.all_in,
                    )
                    for resolved in slice_.actions
                ],
            )
            for slice_ in context.action_history
        ]
    first = extraction.decision_points[0]
    assert first.state.hero_cards == state.hero_cards
    assert first.state.hero_position.display_label == "BTN/SB"
    assert first.state.dealt_in_player_count == 2
    assert first.state.variant == "texas_holdem"
    assert first.state.betting_limit == "no_limit"
    assert first.state.table_size == 2
    assert first.state.blinds == state.game.blinds
    assert first.state.economics == state.game.economics


def test_extraction_returns_one_decision_when_hero_folds_preflop() -> None:
    record = hero_fold_decision_record()

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    assert extraction.rejection is None
    assert len(extraction.decision_points) == 1
    decision = extraction.decision_points[0]
    assert decision.decision_index == 0
    assert decision.street == "preflop"
    assert decision.table_action.action_type == "fold"
    assert decision.table_action.amount is None
    assert decision.table_action.all_in is False
    assert decision.state.amount_to_call == Decimal("0.5")
    assert [excluded.action_type for excluded in extraction.excluded_actions] == [
        "post_small_blind"
    ]


def test_extraction_closes_raising_after_a_short_all_in() -> None:
    record = short_all_in_raise_decision_record()
    contexts = record.active_hero_decision_contexts

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    assert [
        (point.street, point.action_sequence)
        for point in extraction.decision_points
    ] == [("preflop", 2), ("preflop", 5)]
    opening, facing_all_in = extraction.decision_points

    # The hero's own raise to 3 leaves a standing increment of 2; villain's
    # all-in to 4 adds only 1, so the hero may still only call or fold.
    assert opening.state.raise_reopened is True
    assert facing_all_in.state.current_wager == Decimal("4")
    assert facing_all_in.state.amount_to_call == Decimal("1")
    assert facing_all_in.state.last_full_wager_increment == Decimal("2")
    assert facing_all_in.state.raise_reopened is False
    assert [
        (point.state.last_full_wager_increment, point.state.raise_reopened)
        for point in extraction.decision_points
    ] == [
        (context.last_full_wager_increment, context.raise_reopened)
        for context in contexts
    ]


def test_extraction_reopens_raising_after_a_full_raise() -> None:
    record = full_raise_decision_record()

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    facing_raise = extraction.decision_points[1]
    assert (facing_raise.street, facing_raise.action_sequence) == ("preflop", 5)

    # Villain's raise to 5 adds exactly the standing increment of 2, so raising
    # is legal again and the published yardstick sizes the minimum.
    assert facing_raise.state.current_wager == Decimal("5")
    assert facing_raise.state.amount_to_call == Decimal("2")
    assert facing_raise.state.last_full_wager_increment == Decimal("2")
    assert facing_raise.state.raise_reopened is True
    assert [
        point.state.raise_reopened for point in extraction.decision_points
    ] == [True] * 5


def test_extraction_publishes_an_unestablished_increment_as_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An increment the aggregate could not establish stays ``None``, not zero.

    No fixture reaches this state through the aggregate: the walk withholds the
    increment only for an all-in whose commitment it cannot resolve, and that
    same unknown commitment blocks every later hero decision on the street. The
    contexts are therefore supplied directly, which is what the field is for.
    """

    record = multi_street_decision_record()
    unestablished = [
        context.model_copy(update={"last_full_wager_increment": None})
        for context in record.active_hero_decision_contexts
    ]
    assert len(unestablished) == 4
    monkeypatch.setattr(
        decisions,
        "_hero_decision_contexts_for_extraction",
        lambda state: unestablished,
    )

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    assert [
        point.state.last_full_wager_increment
        for point in extraction.decision_points
    ] == [None] * 4
    assert [
        point.state.raise_reopened for point in extraction.decision_points
    ] == [True] * 4


def test_extraction_marks_a_hero_all_in_decision_with_exact_chip_state() -> None:
    record = hero_all_in_decision_record()

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    assert len(extraction.decision_points) == 1
    decision = extraction.decision_points[0]
    assert decision.table_action.action_type == "raise"
    assert decision.table_action.all_in is True
    assert decision.table_action.amount == Decimal("5")
    assert decision.table_action.total_committed == Decimal("5")
    assert decision.state.amount_to_call == Decimal("1")
    assert decision.state.hero_stack_before_action == Decimal("5")
    assert decision.state.pot_before_action == Decimal("1.5")
    assert decision.state.dealt_in_player_count == 3
    assert decision.state.hero_position.display_label == "BTN"


def test_extraction_skips_streets_without_a_hero_action() -> None:
    record = hero_all_in_decision_record()
    state = record.active_state_for_extraction

    extraction = extract_hero_decision_points(record)

    assert state is not None
    assert [street.street for street in state.streets] == [
        "preflop",
        "flop",
        "turn",
        "river",
    ]
    assert [action.actor_id for action in state.streets[1].actions] == [
        "villain",
        "villain-2",
        "villain",
        "villain-2",
    ]
    assert extraction.outcome == "decisions"
    assert [point.street for point in extraction.decision_points] == ["preflop"]
    assert extraction.excluded_actions == []


def test_extraction_reports_no_decision_for_a_big_blind_walk() -> None:
    record = big_blind_walk_record()

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "no_decision"
    assert extraction.rejection is None
    assert extraction.decision_points == []
    assert extraction.canonical_revision == 1
    assert [
        (
            excluded.street,
            excluded.action_sequence,
            excluded.action_type,
            excluded.reason,
        )
        for excluded in extraction.excluded_actions
    ] == [
        ("preflop", 1, "post_big_blind", "forced_or_system"),
        ("preflop", 3, "uncalled_return", "forced_or_system"),
    ]


def test_extraction_never_grades_a_forced_post() -> None:
    record = baseline_decision_record()

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    assert [point.table_action.action_type for point in extraction.decision_points] == [
        "call"
    ]
    assert [
        (excluded.action_type, excluded.reason, excluded.origin.kind)
        for excluded in extraction.excluded_actions
    ] == [("post_small_blind", "forced_or_system", "forced_system")]
    assert all(
        point.table_action.origin.kind == "player_selected"
        for point in extraction.decision_points
    )


def test_extraction_never_grades_a_posted_ante() -> None:
    record = ante_decision_record()

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    assert [
        (point.street, point.action_sequence, point.table_action.action_type)
        for point in extraction.decision_points
    ] == [("preflop", 4, "call")]
    assert [
        (
            excluded.street,
            excluded.action_sequence,
            excluded.action_type,
            excluded.reason,
        )
        for excluded in extraction.excluded_actions
    ] == [
        ("preflop", 0, "post_ante", "forced_or_system"),
        ("preflop", 2, "post_small_blind", "forced_or_system"),
    ]
    # The ante is dead money: it never answers the blind, so the call the
    # decision reports is the full blind gap the hero's own action declares.
    decision = extraction.decision_points[0]
    assert decision.state.amount_to_call == Decimal("0.5")
    assert decision.state.amount_to_call == decision.table_action.amount
    seats = {seat.player_id: seat for seat in decision.state.seats}
    assert seats["hero"].street_commitment == Decimal("0.75")
    assert seats["hero"].live_commitment == Decimal("0.5")


def test_extraction_excludes_client_automatic_actions() -> None:
    record = hero_automatic_action_record()

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    assert [
        (point.street, point.table_action.action_type)
        for point in extraction.decision_points
    ] == [("preflop", "call")]
    assert [
        (
            excluded.street,
            excluded.action_type,
            excluded.reason,
            excluded.origin.automatic_reason,
        )
        for excluded in extraction.excluded_actions
    ] == [
        ("preflop", "post_small_blind", "forced_or_system", None),
        ("flop", "check", "client_automatic", "timeout"),
        ("turn", "fold", "client_automatic", "disconnect"),
    ]


def test_extraction_excludes_an_unresolved_action_origin() -> None:
    unresolved = state_with_reviewed_action_origin(
        kind="unknown",
        basis="unresolved",
    )
    record = origin_confirmation_record(unresolved, unresolved, [])

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "no_decision"
    assert extraction.decision_points == []
    assert [
        (excluded.action_type, excluded.reason)
        for excluded in extraction.excluded_actions
    ] == [
        ("post_small_blind", "forced_or_system"),
        ("call", "unresolved_origin"),
    ]
    assert extraction.excluded_actions[1].origin.basis == "unresolved"


def test_extraction_grades_a_user_confirmed_action_origin() -> None:
    unresolved = state_with_reviewed_action_origin(
        kind="unknown",
        basis="unresolved",
    )
    confirmed = state_with_reviewed_action_origin(
        kind="player_selected",
        basis="user_confirmed",
        review_reference="review-action-0",
    )
    corrections = user_confirmed_origin_corrections(
        unresolved,
        confirmed,
        leaf_fields=False,
    )
    record = origin_confirmation_record(unresolved, confirmed, corrections)

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    assert [point.table_action.action_type for point in extraction.decision_points] == [
        "call"
    ]
    origin = extraction.decision_points[0].table_action.origin
    assert origin.basis == "user_confirmed"
    assert origin.review_reference == "review-action-0"
    # The detected value and its correction both stay on the record.
    assert (
        record.detections[0].state.streets[0].actions[2].origin.kind == "unknown"
    )
    assert [
        correction.field_pointer
        for correction in record.canonical_revisions[0].corrections
    ] == ["/streets/0/actions/2/origin"]


@pytest.mark.parametrize(
    "status",
    ["pending_review", "withdrawn", "rejected", "deletion_pending", "deleted"],
)
def test_extraction_rejects_records_outside_the_active_boundary(
    status: str,
) -> None:
    record = inactive_record(status)

    extraction = extract_hero_decision_points(record)

    assert record.lifecycle.learning_eligible is False
    assert extraction.outcome == "not_extractable"
    assert extraction.rejection == "not_active"
    assert extraction.decision_points == []
    assert extraction.canonical_revision is None
    assert extraction.excluded_actions == []


def test_extraction_rejects_an_unresolved_conflict() -> None:
    record = unresolved_conflict_record()

    extraction = extract_hero_decision_points(record)

    # R4: stricter than the aggregate, which still exposes the hero action.
    assert [conflict.status for conflict in record.conflicts] == ["unresolved"]
    assert len(record.active_hero_actions_for_extraction) == 1
    assert extraction.outcome == "not_extractable"
    assert extraction.rejection == "unresolved_conflict"
    assert extraction.decision_points == []
    assert extraction.canonical_revision is None


def test_extraction_rejects_broken_canonical_revision_lineage() -> None:
    record = broken_lineage_record()

    extraction = extract_hero_decision_points(record)

    assert record.lifecycle.learning_eligible is True
    assert record.active_state_for_extraction is None
    assert extraction.outcome == "not_extractable"
    assert extraction.rejection == "invalid_revision_lineage"
    assert extraction.decision_points == []
    assert extraction.canonical_revision is None


@pytest.mark.parametrize("gap", ["hero_cards", "unknown_participation"])
def test_extraction_rejects_incomplete_hand_state(gap: str) -> None:
    payload = extraction_ready_state_payload()
    if gap == "hero_cards":
        payload["hero_cards"] = []
    else:
        payload["game"]["table_size"] = 3
        payload["seats"].append(
            {
                "seat_number": 3,
                "player_id": "unknown-player",
                "starting_stack": None,
                "participation": "unknown",
            }
        )
        payload["results"] = None
    record = extraction_record_for_state(
        ImportedHandState.model_validate(payload)
    )

    extraction = extract_hero_decision_points(record)

    assert record.active_state_for_extraction is not None
    assert extraction.outcome == "not_extractable"
    assert extraction.rejection == "incomplete_hand_state"
    assert extraction.decision_points == []
    assert extraction.canonical_revision is None


def test_extraction_rejects_incomplete_economics() -> None:
    payload = extraction_ready_state_payload()
    payload["game"]["economics"] = {
        "kind": "cash",
        "currency": "USD",
        "rake": None,
    }
    record = extraction_record_for_state(
        ImportedHandState.model_validate(payload)
    )

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "not_extractable"
    assert extraction.rejection == "incomplete_economics"
    assert extraction.decision_points == []
    assert extraction.canonical_revision is None


@pytest.mark.parametrize("pot_evidence", ["mismatched_total", "missing_comparator"])
def test_extraction_rejects_an_unreconciled_pot(pot_evidence: str) -> None:
    payload = extraction_ready_state_payload()
    if pot_evidence == "mismatched_total":
        payload["results"]["stated_pot"]["gross_total"] = Decimal("3")
    else:
        payload["results"] = None
    record = extraction_record_for_state(
        ImportedHandState.model_validate(payload)
    )

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "not_extractable"
    assert extraction.rejection == "unreconciled_pot"
    assert extraction.decision_points == []
    assert extraction.canonical_revision is None


def test_extraction_emits_from_the_walk_it_proved_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A drifted extraction gate cannot silently erase hero decisions."""

    record = multi_street_decision_record()
    expected = extract_hero_decision_points(record)
    assert expected.outcome == "decisions"
    assert len(expected.decision_points) == 4

    monkeypatch.setattr(
        ImportedHandRecord,
        "active_hero_decision_contexts",
        property(lambda self: []),
    )

    assert record.active_hero_decision_contexts == []
    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    assert len(extraction.decision_points) == 4
    assert extraction == expected


def test_extraction_is_deterministic_for_the_same_record() -> None:
    record = multi_street_decision_record()

    first = extract_hero_decision_points(record)
    second = extract_hero_decision_points(record)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_extraction_isolates_a_rejected_record_from_an_extractable_one() -> None:
    extractable = multi_street_decision_record()
    rejected = inactive_record("withdrawn")

    forwards = [
        extract_hero_decision_points(extractable),
        extract_hero_decision_points(rejected),
    ]
    backwards = [
        extract_hero_decision_points(rejected),
        extract_hero_decision_points(extractable),
    ]

    assert [result.outcome for result in forwards] == [
        "decisions",
        "not_extractable",
    ]
    assert [result.outcome for result in backwards] == [
        "not_extractable",
        "decisions",
    ]
    assert forwards[0] == backwards[1]
    assert forwards[1] == backwards[0]


def test_extraction_binds_every_decision_to_hand_history_provenance() -> None:
    record = multi_street_decision_record()

    extraction = extract_hero_decision_points(record)

    assert extraction.decision_points
    assert all(
        point.provenance.source_kind == "hand_history"
        for point in extraction.decision_points
    )
    # The schema cannot express any other import kind, so a V1 screenshot
    # recommendation can never become a hero table action.
    assert (
        ImportProvenance.model_fields["source_kind"].annotation
        == Literal["hand_history"]
    )


def test_extraction_binds_every_decision_to_the_active_revision() -> None:
    """A hand corrected and reapproved must extract revision 2's state.

    #411's fixture list named "reapproval", but no test built one: every
    other extraction fixture carries a single canonical revision, so an
    implementation hard-coded to revision 1 (or ``canonical_revisions[0]``)
    would still pass all of them. Revision 2 here corrects hero's first hole
    card, a value revision 1 never had, so reading the wrong revision
    surfaces the wrong card.
    """

    detected_state = multi_street_decision_record().canonical_revisions[0].state
    assert detected_state.hero_cards[0].rank == "A"
    corrected_payload = detected_state.model_dump()
    corrected_payload["hero_cards"][0] = {"rank": "T", "suit": "hearts"}
    corrected_state = ImportedHandState.model_validate(corrected_payload)
    assert corrected_state.hero_cards[0].rank == "T"
    correction = UserCorrection(
        field_pointer="/hero_cards/0/rank",
        detected_value="A",
        approved_value="T",
        corrected_at=NOW,
        reason="Hero's hole card corrected from a reread of the hand history",
    )
    record = reapproval_extraction_record(
        detected_state, corrected_state, [correction]
    )
    assert record.active_state_for_extraction == corrected_state

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    assert extraction.canonical_revision == 2
    assert len(extraction.decision_points) == 4
    assert all(
        point.canonical_revision == 2 for point in extraction.decision_points
    )
    assert all(
        point.state.hero_cards[0].rank == "T"
        for point in extraction.decision_points
    )


def test_extraction_carries_a_nonzero_deletion_generation_when_extractable() -> None:
    """Every existing nonzero ``deletion_generation`` fixture is a rejected or
    permanently deleted record; prove the counter also reaches every decision
    point on a record that is fully extractable.
    """

    record = baseline_decision_record()
    record = record.model_copy(
        update={
            "lifecycle": record.lifecycle.model_copy(
                update={"deletion_generation": 3}
            )
        }
    )

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    assert extraction.rejection is None
    assert extraction.deletion_generation == 3
    assert extraction.decision_points
    assert all(
        point.deletion_generation == 3 for point in extraction.decision_points
    )


def sample_decision_point() -> HeroDecisionPoint:
    extraction = extract_hero_decision_points(baseline_decision_record())
    return extraction.decision_points[0]


def sample_excluded_action() -> ExcludedHeroAction:
    extraction = extract_hero_decision_points(hero_fold_decision_record())
    return extraction.excluded_actions[0]


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        (
            {"outcome": "decisions", "decision_points": []},
            "requires at least one decision point",
        ),
        (
            {"rejection": "not_active"},
            "cannot report a rejection",
        ),
        (
            {"outcome": "no_decision"},
            "cannot retain decision points",
        ),
        (
            {"outcome": "not_extractable", "decision_points": []},
            "requires its rejection reason",
        ),
        (
            {
                "outcome": "not_extractable",
                "rejection": "not_active",
                "decision_points": [],
            },
            "cannot bind a canonical revision",
        ),
        (
            {"outcome": "not_extractable", "rejection": "not_active"},
            "cannot retain decision points",
        ),
        (
            {
                "outcome": "not_extractable",
                "rejection": "not_active",
                "decision_points": [],
                "excluded_actions": [sample_excluded_action()],
            },
            "cannot retain excluded actions",
        ),
        (
            {"outcome": "decisions", "canonical_revision": None},
            "requires its canonical revision",
        ),
        (
            {
                "outcome": "no_decision",
                "rejection": "not_active",
                "decision_points": [],
            },
            "cannot report a rejection",
        ),
        (
            {
                "outcome": "no_decision",
                "canonical_revision": None,
                "decision_points": [],
            },
            "requires its canonical revision",
        ),
        (
            {"identity": None},
            "requires its stable identity",
        ),
    ],
)
def test_hand_decision_extraction_binds_its_outcome_to_its_contents(
    overrides: dict[str, object],
    expected_error: str,
) -> None:
    point = sample_decision_point()
    payload: dict[str, object] = {
        "identity": IDENTITY,
        "chronology": point.chronology,
        "provenance": point.provenance,
        "canonical_revision": 1,
        "deletion_generation": 0,
        "outcome": "decisions",
        "rejection": None,
        "decision_points": [point],
        "excluded_actions": [],
        **overrides,
    }

    with pytest.raises(ValidationError, match=expected_error):
        HandDecisionExtraction.model_validate(payload)


def identical_chips_different_line_records() -> (
    tuple[ImportedHandRecord, ImportedHandRecord]
):
    """Build two hands whose turn decision is chip-identical but line-distinct.

    Both flops put two chips in from each player and leave the same stacks; one
    gets there with a hero bet that villain calls, the other with a villain bet
    that the hero calls.
    """

    board = decision_context_board()
    preflop = {
        "street": "preflop",
        "actions": [
            wager_action(
                0,
                "hero",
                "post_small_blind",
                amount=Decimal("0.5"),
                total=Decimal("0.5"),
            ),
            wager_action(
                1,
                "villain",
                "post_big_blind",
                amount=Decimal("1"),
                total=Decimal("1"),
            ),
            wager_action(
                2, "hero", "call", amount=Decimal("0.5"), total=Decimal("1")
            ),
            wager_action(3, "villain", "check", total=Decimal("1")),
        ],
    }
    hero_led_flop = {
        "street": "flop",
        "board_cards": board[:3],
        "actions": [
            wager_action(0, "villain", "check", total=Decimal(0)),
            wager_action(1, "hero", "bet", amount=Decimal("2"), total=Decimal("2")),
            wager_action(
                2, "villain", "call", amount=Decimal("2"), total=Decimal("2")
            ),
        ],
    }
    villain_led_flop = {
        "street": "flop",
        "board_cards": board[:3],
        "actions": [
            wager_action(
                0, "villain", "bet", amount=Decimal("2"), total=Decimal("2")
            ),
            wager_action(1, "hero", "call", amount=Decimal("2"), total=Decimal("2")),
        ],
    }
    turn = {
        "street": "turn",
        "board_cards": board[:4],
        "actions": [
            wager_action(0, "villain", "check", total=Decimal(0)),
            wager_action(1, "hero", "bet", amount=Decimal("2"), total=Decimal("2")),
            wager_action(
                2, "villain", "call", amount=Decimal("2"), total=Decimal("2")
            ),
        ],
    }
    river = {
        "street": "river",
        "board_cards": board,
        "actions": [
            wager_action(0, "villain", "check", total=Decimal(0)),
            wager_action(1, "hero", "check", total=Decimal(0)),
        ],
    }
    return tuple(  # type: ignore[return-value]
        extraction_record_for_streets(
            [preflop, flop, turn, river],
            button_seat=1,
            configured_blinds=True,
            stated_gross=Decimal("10"),
        )
        for flop in (hero_led_flop, villain_led_flop)
    )


def test_extraction_carries_the_completed_postflop_prefix() -> None:
    result = extract_hero_decision_points(multi_street_decision_record())

    histories = {
        point.street: [entry.street for entry in point.state.action_history]
        for point in result.decision_points
    }

    assert histories == {
        "preflop": ["preflop"],
        "flop": ["preflop", "flop"],
        "turn": ["preflop", "flop", "turn"],
        "river": ["preflop", "flop", "turn", "river"],
    }

    turn = next(
        point for point in result.decision_points if point.street == "turn"
    )
    flop_prefix = turn.state.action_history[1]
    assert flop_prefix.street == "flop"
    assert [
        (record.sequence, record.action_type) for record in flop_prefix.actions
    ] == [(0, "check"), (1, "bet"), (2, "call")]

    river = next(
        point for point in result.decision_points if point.street == "river"
    )
    assert [
        [(record.sequence, record.action_type) for record in entry.actions]
        for entry in river.state.action_history[1:3]
    ] == [
        [(0, "check"), (1, "bet"), (2, "call")],
        [(0, "check"), (1, "bet"), (2, "call")],
    ]


def test_extraction_history_stops_before_the_hero_action() -> None:
    result = extract_hero_decision_points(multi_street_decision_record())

    for point in result.decision_points:
        current = point.state.action_history[-1]
        assert current.street == point.street
        assert all(
            record.sequence < point.action_sequence for record in current.actions
        )
        assert len(current.actions) == point.action_sequence


def test_extraction_preflop_history_holds_only_the_truncated_prefix() -> None:
    result = extract_hero_decision_points(baseline_decision_record())

    (point,) = result.decision_points

    assert point.street == "preflop"
    assert [entry.street for entry in point.state.action_history] == ["preflop"]
    (preflop,) = point.state.action_history
    assert [
        (record.sequence, record.player_id, record.action_type)
        for record in preflop.actions
    ] == [
        (0, "hero", "post_small_blind"),
        (1, "villain", "post_big_blind"),
    ]
    assert all(record.action_type != "call" for record in preflop.actions)


def test_extraction_history_separates_identical_chip_states() -> None:
    hero_led, villain_led = identical_chips_different_line_records()

    hero_led_turn = extract_hero_decision_points(hero_led).decision_points[2]
    villain_led_turn = extract_hero_decision_points(villain_led).decision_points[2]

    assert hero_led_turn.street == villain_led_turn.street == "turn"
    assert (
        hero_led_turn.action_sequence == villain_led_turn.action_sequence == 1
    )
    hero_state = hero_led_turn.state
    villain_state = villain_led_turn.state
    for field_name in (
        "board_cards",
        "committed_pot_before_street",
        "pot_before_action",
        "current_wager",
        "amount_to_call",
        "last_full_wager_increment",
        "raise_reopened",
        "hero_stack_before_action",
        "seats",
    ):
        assert getattr(hero_state, field_name) == getattr(
            villain_state, field_name
        ), field_name

    # Every aggregate chip value matches; only the ordered line tells the two
    # spots apart, which is the whole reason it is carried.
    assert hero_state.action_history != villain_state.action_history
    assert hero_state.action_history[0] == villain_state.action_history[0]
    assert [
        (record.player_id, record.action_type)
        for record in hero_state.action_history[1].actions
    ] == [("villain", "check"), ("hero", "bet"), ("villain", "call")]
    assert [
        (record.player_id, record.action_type)
        for record in villain_state.action_history[1].actions
    ] == [("villain", "bet"), ("hero", "call")]


def test_decision_state_rejects_a_broken_action_history() -> None:
    point = extract_hero_decision_points(
        multi_street_decision_record()
    ).decision_points[2]
    payload = point.state.model_dump(mode="python")

    with pytest.raises(ValidationError, match="without gaps or duplicates"):
        decisions.HeroDecisionState.model_validate(
            {**payload, "action_history": payload["action_history"][:1]}
        )

    reordered = [
        payload["action_history"][1],
        payload["action_history"][0],
        payload["action_history"][2],
    ]
    with pytest.raises(ValidationError, match="without gaps or duplicates"):
        decisions.HeroDecisionState.model_validate(
            {**payload, "action_history": reordered}
        )


def test_decision_point_rejects_a_history_covering_its_own_action() -> None:
    point = extract_hero_decision_points(
        multi_street_decision_record()
    ).decision_points[2]
    payload = point.model_dump(mode="python")
    current = payload["state"]["action_history"][-1]
    current["actions"] = [*current["actions"], {**current["actions"][0], "sequence": 1}]

    with pytest.raises(ValidationError, match="stop there"):
        HeroDecisionPoint.model_validate(payload)


def multi_street_decision_payload(index: int) -> dict[str, object]:
    """Round-trip one decision of the shared four-street hand as a payload."""

    point = extract_hero_decision_points(
        multi_street_decision_record()
    ).decision_points[index]
    return point.model_dump(mode="python")


def empty_current_street(payload: dict[str, object]) -> None:
    payload["state"]["action_history"][-1]["actions"] = []


def truncate_completed_turn(payload: dict[str, object]) -> None:
    turn = payload["state"]["action_history"][2]
    turn["actions"] = turn["actions"][:1]


def reverse_completed_flop(payload: dict[str, object]) -> None:
    flop = payload["state"]["action_history"][1]
    flop["actions"] = list(reversed(flop["actions"]))


def claim_a_later_action_sequence(payload: dict[str, object]) -> None:
    payload["action_sequence"] = 3
    payload["state"]["action_history"][-1]["actions"] = []


def rename_an_actor(payload: dict[str, object]) -> None:
    payload["state"]["action_history"][1]["actions"][0]["player_id"] = "ghost"


def swap_an_actor_position(payload: dict[str, object]) -> None:
    seats = payload["state"]["seats"]
    record = payload["state"]["action_history"][1]["actions"][0]
    other = next(
        seat for seat in seats if seat["player_id"] != record["player_id"]
    )
    record["position"] = other["position"]


def duplicate_a_completed_sequence(payload: dict[str, object]) -> None:
    flop = payload["state"]["action_history"][1]
    flop["actions"] = [*flop["actions"], dict(flop["actions"][-1])]


@pytest.mark.parametrize(
    ("index", "mutate", "expected_error"),
    [
        (2, empty_current_street, "stop there"),
        (3, truncate_completed_turn, "contradicts committed_pot_before_street"),
        (3, reverse_completed_flop, "contiguous and ordered"),
        (3, claim_a_later_action_sequence, "stop there"),
        (3, rename_an_actor, "is not a dealt-in seat"),
        (3, swap_an_actor_position, "does not match its seat"),
        (3, duplicate_a_completed_sequence, "contiguous and ordered"),
    ],
)
def test_decision_point_rejects_a_corrupted_betting_history(
    index: int,
    mutate: object,
    expected_error: str,
) -> None:
    payload = multi_street_decision_payload(index)

    assert HeroDecisionPoint.model_validate(payload) is not None
    mutate(payload)  # type: ignore[operator]

    with pytest.raises(ValidationError, match=expected_error):
        HeroDecisionPoint.model_validate(payload)


def half_stated_chip_records() -> tuple[ImportedHandRecord, ImportedHandRecord]:
    """Build one hand stating only a call's amount and one only its total."""

    board = decision_context_board()

    def hand(*, amount: Decimal | None, total: Decimal | None) -> ImportedHandRecord:
        return extraction_record_for_streets(
            [
                {
                    "street": "preflop",
                    "actions": [
                        wager_action(
                            0,
                            "hero",
                            "post_small_blind",
                            amount=Decimal("0.5"),
                            total=Decimal("0.5"),
                        ),
                        wager_action(
                            1,
                            "villain",
                            "post_big_blind",
                            amount=Decimal("1"),
                            total=Decimal("1"),
                        ),
                        wager_action(
                            2,
                            "hero",
                            "call",
                            amount=Decimal("0.5"),
                            total=Decimal("1"),
                        ),
                        wager_action(3, "villain", "check", total=Decimal("1")),
                    ],
                },
                {
                    "street": "flop",
                    "board_cards": board[:3],
                    "actions": [
                        wager_action(0, "villain", "check", total=Decimal(0)),
                        wager_action(
                            1,
                            "hero",
                            "bet",
                            amount=Decimal("2"),
                            total=Decimal("2"),
                        ),
                        wager_action(
                            2, "villain", "call", amount=amount, total=total
                        ),
                    ],
                },
                {
                    "street": "turn",
                    "board_cards": board[:4],
                    "actions": [
                        wager_action(0, "villain", "check", total=Decimal(0)),
                        wager_action(
                            1,
                            "hero",
                            "check",
                            total=Decimal(0),
                        ),
                    ],
                },
                {
                    "street": "river",
                    "board_cards": board,
                    "actions": [
                        wager_action(0, "villain", "check", total=Decimal(0)),
                        wager_action(1, "hero", "check", total=Decimal(0)),
                    ],
                },
            ],
            button_seat=1,
            configured_blinds=True,
            stated_gross=Decimal("6"),
        )

    return (
        hand(amount=Decimal("2"), total=None),
        hand(amount=None, total=Decimal("2")),
    )


def test_extraction_history_publishes_the_resolved_chip_values() -> None:
    amount_only, total_only = half_stated_chip_records()

    amount_turn = extract_hero_decision_points(amount_only).decision_points[2]
    total_turn = extract_hero_decision_points(total_only).decision_points[2]

    assert amount_turn.street == total_turn.street == "turn"
    for point in (amount_turn, total_turn):
        villain_call = point.state.action_history[1].actions[2]
        assert (villain_call.player_id, villain_call.action_type) == (
            "villain",
            "call",
        )
        # The walk resolved both halves; the line publishes them whichever one
        # the adapter stated, so it agrees with the pot and seat fields.
        assert villain_call.amount == Decimal("2")
        assert villain_call.total_committed == Decimal("2")
        assert point.state.committed_pot_before_street == Decimal("6")

    assert amount_turn.state.action_history == total_turn.state.action_history


def test_extraction_history_publishes_the_resolved_all_in_verdict() -> None:
    """A stack-exhausting post is all-in in the line even without a marker."""

    record = unmarked_all_in_blind_decision_record()
    state = record.active_state_for_extraction

    (point,) = extract_hero_decision_points(record).decision_points

    assert state is not None
    blind_post = state.streets[0].actions[0]
    assert (blind_post.actor_id, blind_post.all_in) == ("villain", False)

    published = point.state.action_history[0].actions[0]
    seat = next(
        item for item in point.state.seats if item.player_id == "villain"
    )
    assert (published.player_id, published.action_type) == (
        "villain",
        "post_small_blind",
    )
    assert published.total_committed == seat.starting_stack == Decimal("0.5")
    assert seat.status == "all_in"
    assert seat.stack_before_action == Decimal(0)
    # The post took villain's whole stack, so the line says so too rather than
    # contradicting the seat beside it.
    assert published.all_in is True


def cumulative_commitment(
    history: list[decisions.StreetActionHistory],
    entry: decisions.StreetActionHistory,
    record: decisions.DecisionActionRecord,
) -> Decimal | None:
    """Total what a record says its actor has committed across the hand."""

    if record.total_committed is None:
        return None
    total = record.total_committed
    for earlier in history:
        if earlier.street == entry.street:
            break
        street_total = {
            item.player_id: item.total_committed for item in earlier.actions
        }.get(record.player_id)
        if street_total is None:
            continue
        total += street_total
    return total


def test_extraction_history_all_in_never_contradicts_the_seats() -> None:
    records = [
        unmarked_all_in_blind_decision_record(),
        heads_up_shove_and_call_decision_record(),
        short_all_in_raise_decision_record(),
        contested_decision_record(),
        full_raise_decision_record(),
        multi_street_decision_record(),
        ante_decision_record(),
    ]

    inspected = 0
    marked = 0
    for record in records:
        extraction = extract_hero_decision_points(record)
        assert extraction.outcome == "decisions"
        for point in extraction.decision_points:
            seats = {item.player_id: item for item in point.state.seats}
            for entry in point.state.action_history:
                for item in entry.actions:
                    inspected += 1
                    seat = seats[item.player_id]
                    if item.all_in:
                        marked += 1
                        # Whoever the line says is all-in must be all-in now:
                        # nothing can give those chips back.
                        assert seat.status == "all_in", (
                            entry.street,
                            item.player_id,
                        )
                    committed = cumulative_commitment(
                        point.state.action_history, entry, item
                    )
                    if committed is not None and committed == seat.starting_stack:
                        # An action that took the actor's last chip is all-in
                        # however the source labelled it.
                        assert item.all_in is True, (
                            entry.street,
                            item.sequence,
                            item.player_id,
                        )

    assert inspected > 0
    assert marked > 0


def test_extraction_table_action_publishes_resolved_chips_and_all_in() -> None:
    record = short_stacked_hero_decision_record()
    state = record.active_state_for_extraction

    points = extract_hero_decision_points(record).decision_points

    assert state is not None
    assert [(point.street, point.action_sequence) for point in points] == [
        ("preflop", 2),
        ("flop", 1),
        ("turn", 1),
    ]

    # The source states this bet's street total but never its amount.
    flop_source = state.streets[1].actions[1]
    assert (flop_source.actor_id, flop_source.amount) == ("hero", None)
    assert points[1].table_action.amount == Decimal("2")
    assert points[1].table_action.total_committed == Decimal("2")

    # The source never marks this bet all-in, but it is the hero's last chips.
    turn_source = state.streets[2].actions[1]
    assert (turn_source.actor_id, turn_source.all_in) == ("hero", False)
    turn = points[2]
    hero_seat = next(
        seat
        for seat in turn.state.seats
        if seat.position == turn.state.hero_position
    )
    assert turn.table_action.amount == hero_seat.stack_before_action == Decimal("2")
    assert hero_seat.hand_commitment + turn.table_action.amount == (
        hero_seat.starting_stack
    )
    assert turn.table_action.all_in is True

    # The audit trail is untouched by the resolution.
    assert turn.table_action.origin == turn_source.origin
    assert turn.table_action.evidence == list(turn_source.evidence)


def test_extraction_table_action_never_contradicts_the_hero_seat() -> None:
    records = [
        short_stacked_hero_decision_record(),
        heads_up_shove_and_call_decision_record(),
        short_all_in_raise_decision_record(),
        unmarked_all_in_blind_decision_record(),
        contested_decision_record(),
        full_raise_decision_record(),
        multi_street_decision_record(),
        ante_decision_record(),
    ]

    inspected = 0
    shoves = 0
    for record in records:
        extraction = extract_hero_decision_points(record)
        assert extraction.outcome == "decisions"
        for point in extraction.decision_points:
            inspected += 1
            action = point.table_action
            hero_seat = next(
                seat
                for seat in point.state.seats
                if seat.position == point.state.hero_position
            )
            if action.action_type in {"bet", "call", "raise"}:
                # The walk resolved both halves for every wager it emitted.
                assert action.amount is not None
                assert action.total_committed is not None
                if action.amount == hero_seat.stack_before_action:
                    shoves += 1
                    # Committing the last chip is all-in however it was
                    # labelled, exactly as in the betting line.
                    assert action.all_in is True
            if action.all_in:
                assert action.amount == hero_seat.stack_before_action

    assert inspected > 0
    assert shoves > 0


def foreign_identity(payload: dict[str, object]) -> None:
    payload["decision_points"][0]["identity"] = {
        "site": "ggpoker",
        "source_hand_id": "999999999",
    }


def foreign_canonical_revision(payload: dict[str, object]) -> None:
    payload["decision_points"][1]["canonical_revision"] = 2


def foreign_deletion_generation(payload: dict[str, object]) -> None:
    payload["decision_points"][1]["deletion_generation"] = 7


def gapped_decision_indexes(payload: dict[str, object]) -> None:
    for offset, point in enumerate(payload["decision_points"]):
        point["decision_index"] = 10 + offset * 3


def duplicated_decision_index(payload: dict[str, object]) -> None:
    payload["decision_points"][1]["decision_index"] = 0


def shuffled_decision_chronology(payload: dict[str, object]) -> None:
    points = payload["decision_points"]
    points[0], points[-1] = points[-1], points[0]
    for index, point in enumerate(points):
        point["decision_index"] = index


def duplicated_excluded_action(payload: dict[str, object]) -> None:
    payload["excluded_actions"] = [
        *payload["excluded_actions"],
        dict(payload["excluded_actions"][0]),
    ]


def reversed_excluded_actions(payload: dict[str, object]) -> None:
    payload["excluded_actions"] = list(reversed(payload["excluded_actions"]))


def forced_table_action(payload: dict[str, object]) -> None:
    action = payload["decision_points"][0]["table_action"]
    action["action_type"] = "post_small_blind"
    action["origin"] = {**action["origin"], "kind": "forced_system"}


def automatic_table_action(payload: dict[str, object]) -> None:
    action = payload["decision_points"][0]["table_action"]
    action["origin"] = {
        **action["origin"],
        "kind": "client_automatic",
        "automatic_reason": "timeout",
    }


def unresolved_table_action(payload: dict[str, object]) -> None:
    action = payload["decision_points"][0]["table_action"]
    action["origin"] = {
        **action["origin"],
        "kind": "unknown",
        "basis": "unresolved",
    }


def envelope_without_chronology(payload: dict[str, object]) -> None:
    payload["chronology"] = None


def envelope_without_provenance(payload: dict[str, object]) -> None:
    payload["provenance"] = None


def divergent_chronology(payload: dict[str, object]) -> None:
    payload["decision_points"][1]["chronology"]["hand_ordinal"] = 99


def divergent_provenance(payload: dict[str, object]) -> None:
    payload["decision_points"][1]["provenance"]["import_id"] = "import-other"


def excluded_action_shadowing_a_decision(payload: dict[str, object]) -> None:
    point = payload["decision_points"][0]
    shadow = dict(payload["excluded_actions"][0])
    shadow["street"] = point["street"]
    shadow["action_sequence"] = point["action_sequence"]
    payload["excluded_actions"] = [shadow]


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (foreign_identity, "identity does not match the extracted hand"),
        (
            foreign_canonical_revision,
            "canonical revision does not match the extracted hand",
        ),
        (
            foreign_deletion_generation,
            "deletion generation does not match the extracted hand",
        ),
        (
            forced_table_action,
            "requires a table decision, not a forced or system action",
        ),
        (
            automatic_table_action,
            "requires a player-selected table action, not a client_automatic",
        ),
        (
            unresolved_table_action,
            "requires a player-selected table action, not a unknown",
        ),
        (
            divergent_chronology,
            "source chronology does not match the extracted hand",
        ),
        (
            divergent_provenance,
            "import provenance does not match the extracted hand",
        ),
        (
            envelope_without_chronology,
            "a decisions outcome requires its source chronology",
        ),
        (
            envelope_without_provenance,
            "a decisions outcome requires its import provenance",
        ),
        (gapped_decision_indexes, "contiguous and ordered from zero"),
        (duplicated_decision_index, "contiguous and ordered from zero"),
        (
            shuffled_decision_chronology,
            "decision points must run in street then action order",
        ),
        (
            duplicated_excluded_action,
            "excluded actions must run in street then action order",
        ),
        (
            excluded_action_shadowing_a_decision,
            "cannot be both a decision point and an excluded action",
        ),
    ],
)
def test_hand_decision_extraction_rejects_an_unbound_envelope(
    mutate: object,
    expected_error: str,
) -> None:
    payload = extract_hero_decision_points(
        multi_street_decision_record()
    ).model_dump(mode="python")

    assert HandDecisionExtraction.model_validate(payload) is not None
    mutate(payload)  # type: ignore[operator]

    with pytest.raises(ValidationError, match=expected_error):
        HandDecisionExtraction.model_validate(payload)


def test_hand_decision_extraction_rejects_reordered_excluded_actions() -> None:
    # The shared four-street hand excludes only the hero's blind post, so
    # reversing it is a no-op; the ante hand excludes an ante and a blind.
    payload = extract_hero_decision_points(ante_decision_record()).model_dump(
        mode="python"
    )

    assert len(payload["excluded_actions"]) == 2
    assert HandDecisionExtraction.model_validate(payload) is not None
    reversed_excluded_actions(payload)

    with pytest.raises(
        ValidationError,
        match="excluded actions must run in street then action order",
    ):
        HandDecisionExtraction.model_validate(payload)


def test_hand_decision_extraction_binds_every_point_to_the_envelope() -> None:
    extraction = extract_hero_decision_points(multi_street_decision_record())

    assert extraction.outcome == "decisions"
    assert len(extraction.decision_points) == 4
    for index, point in enumerate(extraction.decision_points):
        assert point.identity == extraction.identity
        assert point.canonical_revision == extraction.canonical_revision
        assert point.deletion_generation == extraction.deletion_generation
        assert point.decision_index == index
    assert [
        (point.street, point.action_sequence)
        for point in extraction.decision_points
    ] == [("preflop", 2), ("flop", 1), ("turn", 1), ("river", 1)]


def test_excluded_action_rejects_a_voluntary_or_mislabelled_origin() -> None:
    """An exclusion must not park a decision, nor borrow another's reason."""

    payload = extract_hero_decision_points(
        multi_street_decision_record()
    ).excluded_actions[0].model_dump(mode="python")

    assert decisions.ExcludedHeroAction.model_validate(payload) is not None
    assert (payload["origin"]["kind"], payload["reason"]) == (
        "forced_system",
        "forced_or_system",
    )

    voluntary = {
        **payload,
        "action_type": "bet",
        "origin": {**payload["origin"], "kind": "player_selected"},
    }
    with pytest.raises(
        ValidationError, match="is a decision, not an excluded action"
    ):
        decisions.ExcludedHeroAction.model_validate(voluntary)

    mislabelled = {**payload, "reason": "client_automatic"}
    with pytest.raises(
        ValidationError, match="must be excluded as forced_or_system"
    ):
        decisions.ExcludedHeroAction.model_validate(mislabelled)


def test_extraction_keeps_a_user_confirmed_origin_gradeable() -> None:
    """The voluntary-action rule must not exclude a confirmed origin."""

    unresolved = state_with_reviewed_action_origin(
        kind="unknown",
        basis="unresolved",
    )
    confirmed = state_with_reviewed_action_origin(
        kind="player_selected",
        basis="user_confirmed",
        review_reference="review-action-0",
    )
    record = origin_confirmation_record(
        unresolved,
        confirmed,
        user_confirmed_origin_corrections(
            unresolved, confirmed, leaf_fields=False
        ),
    )

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "decisions"
    (point,) = extraction.decision_points
    assert point.table_action.origin.basis == "user_confirmed"
    # An origin the player confirmed during approval is player-selected by the
    # time it reaches a decision, so the rule admits it rather than parking it.
    assert point.table_action.origin.kind == "player_selected"
    assert point.table_action.action_type == "call"
    assert HeroDecisionPoint.model_validate(
        point.model_dump(mode="python")
    ) == point
    assert not [
        action
        for action in extraction.excluded_actions
        if action.origin.basis == "user_confirmed"
    ]


def test_extraction_retains_hand_provenance_without_any_decision() -> None:
    """A big-blind walk is retained with its provenance, not just its identity."""

    record = big_blind_walk_record()
    state = record.active_state_for_extraction

    extraction = extract_hero_decision_points(record)

    assert state is not None
    assert extraction.outcome == "no_decision"
    assert extraction.decision_points == []
    # No decision point carries them here, so the envelope has to.
    assert extraction.chronology == state.chronology
    assert extraction.provenance == record.raw_sources[0].provenance
    assert extraction.identity == record.identity
    assert extraction.canonical_revision == 1


def test_extraction_binds_hand_provenance_to_every_decision() -> None:
    extraction = extract_hero_decision_points(multi_street_decision_record())

    assert extraction.outcome == "decisions"
    assert extraction.chronology is not None
    assert extraction.provenance is not None
    for point in extraction.decision_points:
        assert point.chronology == extraction.chronology
        assert point.provenance == extraction.provenance


def test_extraction_rejection_binds_no_hand_provenance() -> None:
    record = big_blind_walk_record().model_copy(
        update={
            "lifecycle": ImportedHandLifecycle(status="withdrawn", changed_at=NOW)
        }
    )

    extraction = extract_hero_decision_points(record)

    assert extraction.outcome == "not_extractable"
    # A rejected hand binds no canonical artifact, provenance included.
    assert extraction.chronology is None
    assert extraction.provenance is None
    assert extraction.canonical_revision is None


@pytest.mark.parametrize(
    "outcome",
    ["decisions", "no_decision"],
)
def test_hand_decision_extraction_requires_hand_provenance(outcome: str) -> None:
    source = (
        multi_street_decision_record()
        if outcome == "decisions"
        else big_blind_walk_record()
    )
    payload = extract_hero_decision_points(source).model_dump(mode="python")

    assert payload["outcome"] == outcome
    assert HandDecisionExtraction.model_validate(payload) is not None

    for field_name, expected in (
        ("chronology", "requires its source chronology"),
        ("provenance", "requires its import provenance"),
    ):
        with pytest.raises(ValidationError, match=f"a {outcome} outcome {expected}"):
            HandDecisionExtraction.model_validate({**payload, field_name: None})


def test_decision_types_reject_a_zero_full_wager_increment() -> None:
    """Zero is never a legal yardstick; unknown stays distinct as ``None``."""

    record = multi_street_decision_record()
    context = record.active_hero_decision_contexts[0]
    point = extract_hero_decision_points(record).decision_points[0]

    assert context.last_full_wager_increment == Decimal("1")
    assert point.state.last_full_wager_increment == Decimal("1")

    context_payload = context.model_dump(mode="python")
    state_payload = point.state.model_dump(mode="python")
    for model, payload in (
        (HeroActionContext, context_payload),
        (decisions.HeroDecisionState, state_payload),
    ):
        assert model.model_validate(payload) is not None
        assert (
            model.model_validate(
                {**payload, "last_full_wager_increment": None}
            ).last_full_wager_increment
            is None
        )
        assert model.model_validate(
            {**payload, "last_full_wager_increment": Decimal("2")}
        ).last_full_wager_increment == Decimal("2")
        with pytest.raises(ValidationError, match="greater than 0"):
            model.model_validate(
                {**payload, "last_full_wager_increment": Decimal(0)}
            )


@pytest.mark.parametrize(
    ("index", "street", "board_cards"),
    [(0, "preflop", 0), (1, "flop", 3), (2, "turn", 4), (3, "river", 5)],
)
def test_decision_state_rejects_a_malformed_card_set(
    index: int,
    street: str,
    board_cards: int,
) -> None:
    point = extract_hero_decision_points(
        multi_street_decision_record()
    ).decision_points[index]
    payload = point.state.model_dump(mode="python")

    assert (payload["street"], len(payload["board_cards"])) == (
        street,
        board_cards,
    )
    assert decisions.HeroDecisionState.model_validate(payload) is not None

    # One hero card is not a hand.
    with pytest.raises(ValidationError, match="requires both hero cards"):
        decisions.HeroDecisionState.model_validate(
            {**payload, "hero_cards": payload["hero_cards"][:1]}
        )

    # The board must be exactly this street's, short or long.
    river = extract_hero_decision_points(
        multi_street_decision_record()
    ).decision_points[3]
    # One card past the river, so even a five-card street can be overfilled.
    full_board = [
        *river.state.model_dump(mode="python")["board_cards"],
        {"rank": "3", "suit": "spades"},
    ]
    for wrong in (board_cards + 1, board_cards - 1):
        if wrong < 0:
            continue
        with pytest.raises(
            ValidationError,
            match=f"a {street} decision requires exactly {board_cards} board",
        ):
            decisions.HeroDecisionState.model_validate(
                {**payload, "board_cards": full_board[:wrong]}
            )

    # A card cannot be in two places at once.
    if board_cards:
        duplicated = [dict(payload["hero_cards"][0]), *payload["board_cards"][1:]]
        with pytest.raises(ValidationError, match="must not repeat a card"):
            decisions.HeroDecisionState.model_validate(
                {**payload, "board_cards": duplicated}
            )


def test_hero_table_action_rejects_an_invalid_action_shape() -> None:
    payload = extract_hero_decision_points(
        multi_street_decision_record()
    ).decision_points[1].table_action.model_dump(mode="python")

    assert payload["action_type"] == "bet"
    assert decisions.HeroTableAction.model_validate(payload) is not None

    with pytest.raises(ValidationError, match="cannot carry an amount"):
        decisions.HeroTableAction.model_validate(
            {**payload, "action_type": "check", "amount": Decimal("5")}
        )
    with pytest.raises(ValidationError, match="cannot be all-in"):
        decisions.HeroTableAction.model_validate(
            {**payload, "action_type": "fold", "amount": None, "all_in": True}
        )


def test_decision_state_binds_the_current_street_to_the_chip_snapshot() -> None:
    """The line in progress and the chip snapshot must tell the same story."""

    point = extract_hero_decision_points(
        contested_decision_record()
    ).decision_points[1]
    payload = point.state.model_dump(mode="python")

    assert payload["street"] == "flop"
    assert decisions.HeroDecisionState.model_validate(payload) is not None
    opponent_bet = payload["action_history"][-1]["actions"][0]
    assert (opponent_bet["player_id"], opponent_bet["total_committed"]) == (
        "villain-2",
        Decimal("4"),
    )

    # Inflate the action and leave the snapshot alone.
    inflated_action = copy.deepcopy(payload)
    inflated_action["action_history"][-1]["actions"][0]["total_committed"] = (
        Decimal("5")
    )
    with pytest.raises(
        ValidationError, match="contradicts the 5 its action history shows"
    ):
        decisions.HeroDecisionState.model_validate(inflated_action)

    # Inflate the snapshot and leave the action alone.
    inflated_seat = copy.deepcopy(payload)
    next(
        seat
        for seat in inflated_seat["seats"]
        if seat["player_id"] == "villain-2"
    )["street_commitment"] = Decimal("5")
    with pytest.raises(
        ValidationError, match="contradicts the 4 its action history shows"
    ):
        decisions.HeroDecisionState.model_validate(inflated_seat)

    # The derived fields are bound to the seats too.
    wrong_pot = {**payload, "pot_before_action": Decimal("7")}
    with pytest.raises(ValidationError, match="pot_before_action 7 contradicts"):
        decisions.HeroDecisionState.model_validate(wrong_pot)
    wrong_call = {**payload, "amount_to_call": Decimal("1")}
    with pytest.raises(ValidationError, match="amount_to_call 1 contradicts"):
        decisions.HeroDecisionState.model_validate(wrong_call)


def contested_flop_state_payload() -> dict[str, object]:
    """Round-trip the three-handed flop decision, one seat folded, one all-in."""

    return extract_hero_decision_points(
        contested_decision_record()
    ).decision_points[1].state.model_dump(mode="python")


def test_decision_state_binds_the_wager_to_live_seat_commitments() -> None:
    payload = contested_flop_state_payload()

    assert decisions.HeroDecisionState.model_validate(payload) is not None
    assert (payload["current_wager"], payload["amount_to_call"]) == (
        Decimal("4"),
        Decimal("4"),
    )

    # Moving the wager and the call together leaves them consistent with each
    # other, so only the seats can catch it.
    raised_together = {
        **payload,
        "current_wager": Decimal("5"),
        "amount_to_call": Decimal("5"),
    }
    with pytest.raises(
        ValidationError, match="current_wager 5 exceeds the 4 its seats have live"
    ):
        decisions.HeroDecisionState.model_validate(raised_together)

    lowered = {
        **payload,
        "current_wager": Decimal("3"),
        "amount_to_call": Decimal("3"),
    }
    with pytest.raises(
        ValidationError, match="current_wager 3 is below the 4 its seats have live"
    ):
        decisions.HeroDecisionState.model_validate(lowered)


@pytest.mark.parametrize(
    ("player_id", "published", "expected"),
    [
        ("villain-2", "live", "all_in"),
        ("villain-2", "folded", "all_in"),
        ("villain", "live", "folded"),
        ("villain", "all_in", "folded"),
    ],
)
def test_decision_state_binds_seat_status_to_stacks_and_history(
    player_id: str,
    published: str,
    expected: str,
) -> None:
    payload = contested_flop_state_payload()

    assert decisions.HeroDecisionState.model_validate(payload) is not None
    seats = {seat["player_id"]: seat["status"] for seat in payload["seats"]}
    assert seats == {"hero": "live", "villain": "folded", "villain-2": "all_in"}

    mutated = copy.deepcopy(payload)
    next(
        seat for seat in mutated["seats"] if seat["player_id"] == player_id
    )["status"] = published

    with pytest.raises(
        ValidationError,
        match=f"{player_id} is published {published} but its stack and betting"
        f" history make it {expected}",
    ):
        decisions.HeroDecisionState.model_validate(mutated)


def test_decision_action_record_rejects_an_impossible_shape() -> None:
    payload = contested_flop_state_payload()
    record = payload["action_history"][0]["actions"][4]

    assert decisions.HeroDecisionState.model_validate(payload) is not None
    assert (record["player_id"], record["action_type"]) == ("villain-2", "check")

    with_amount = copy.deepcopy(payload)
    with_amount["action_history"][0]["actions"][4]["amount"] = Decimal("5")
    with pytest.raises(ValidationError, match="cannot carry an amount"):
        decisions.HeroDecisionState.model_validate(with_amount)

    marked_all_in = copy.deepcopy(payload)
    marked_all_in["action_history"][0]["actions"][4]["all_in"] = True
    with pytest.raises(ValidationError, match="cannot be all-in"):
        decisions.HeroDecisionState.model_validate(marked_all_in)

    # A post legitimately carries chips, so the rule is not a blanket ban.
    blind_post = payload["action_history"][0]["actions"][0]
    assert (blind_post["action_type"], blind_post["amount"]) == (
        "post_small_blind",
        Decimal("0.5"),
    )


def test_decision_point_binds_the_table_action_to_the_hero_snapshot() -> None:
    point = extract_hero_decision_points(
        multi_street_decision_record()
    ).decision_points[1]
    payload = point.model_dump(mode="python")
    hero = next(
        seat
        for seat in payload["state"]["seats"]
        if seat["position"] == payload["state"]["hero_position"]
    )

    assert HeroDecisionPoint.model_validate(payload) is not None
    assert payload["table_action"]["action_type"] == "bet"
    assert (
        payload["table_action"]["amount"],
        payload["table_action"]["total_committed"],
    ) == (Decimal("2"), Decimal("2"))
    assert hero["street_commitment"] == Decimal(0)

    # A bet larger than the hero holds.
    inflated = copy.deepcopy(payload)
    inflated["table_action"]["amount"] = Decimal("200")
    inflated["table_action"]["total_committed"] = Decimal("200")
    with pytest.raises(ValidationError, match="exceeds the hero's 99 behind"):
        HeroDecisionPoint.model_validate(inflated)

    # A delta that does not land on the hero's commitment.
    drifted = copy.deepcopy(payload)
    drifted["table_action"]["total_committed"] = Decimal("3")
    with pytest.raises(ValidationError, match="leaves 2, not 3"):
        HeroDecisionPoint.model_validate(drifted)

    # An action taking the hero's last chip is all-in, and only then.
    mislabelled = copy.deepcopy(payload)
    mislabelled["table_action"]["all_in"] = True
    with pytest.raises(ValidationError, match="behind is not all-in"):
        HeroDecisionPoint.model_validate(mislabelled)


def test_decision_point_binds_a_call_to_what_is_owed() -> None:
    point = extract_hero_decision_points(
        hero_facing_a_raise_decision_record(hero_stack=Decimal("10"))
    ).decision_points[1]
    payload = point.model_dump(mode="python")

    assert HeroDecisionPoint.model_validate(payload) is not None
    assert payload["table_action"]["action_type"] == "call"
    assert payload["state"]["amount_to_call"] == Decimal("3")

    underpaid = copy.deepcopy(payload)
    underpaid["table_action"]["amount"] = Decimal("2")
    underpaid["table_action"]["total_committed"] = Decimal("3")
    with pytest.raises(ValidationError, match="a call must put in the 3"):
        HeroDecisionPoint.model_validate(underpaid)

    # A short all-in call is the one legitimate way to pay less than is owed.
    short_all_in = extract_hero_decision_points(
        hero_facing_a_raise_decision_record(hero_stack=Decimal("4"))
    ).decision_points[1]
    assert short_all_in.table_action.amount == Decimal("3")
    assert short_all_in.state.amount_to_call == Decimal("3")
    assert short_all_in.table_action.all_in is True


@pytest.mark.parametrize(
    ("factory", "index", "expected_error"),
    [
        (
            contested_decision_record,
            1,
            "every live opponent is all-in",
        ),
        (
            heads_up_shove_and_call_decision_record,
            1,
            "cannot beat the 99 call",
        ),
        (
            lambda: hero_facing_a_raise_decision_record(hero_stack=Decimal("4")),
            1,
            "cannot beat the 3",
        ),
    ],
)
def test_decision_state_rejects_a_flipped_raise_verdict(
    factory: object,
    index: int,
    expected_error: str,
) -> None:
    payload = extract_hero_decision_points(
        factory()  # type: ignore[operator]
    ).decision_points[index].state.model_dump(mode="python")

    assert payload["raise_reopened"] is False
    assert decisions.HeroDecisionState.model_validate(payload) is not None

    with pytest.raises(ValidationError, match=expected_error):
        decisions.HeroDecisionState.model_validate(
            {**payload, "raise_reopened": True}
        )


def test_decision_state_cannot_rederive_a_short_all_in_raise_verdict() -> None:
    """Pin the one closed verdict the published state cannot prove.

    Neither reason a decision state can check applies here, so a flipped
    verdict on this point is not caught. Closing it needs the increment that
    stood when the hero acted, which the state does not carry.
    """

    point = extract_hero_decision_points(
        short_all_in_with_live_caller_decision_record()
    ).decision_points[1]
    state = point.state
    hero = next(
        seat for seat in state.seats if seat.position == state.hero_position
    )

    assert (point.street, point.action_sequence) == ("preflop", 5)
    assert state.raise_reopened is False
    # The hero has chips behind ...
    assert hero.stack_before_action > state.amount_to_call
    # ... and an opponent who can still answer a raise.
    assert [seat.status for seat in state.seats] == ["live", "all_in", "live"]


def test_hero_table_action_requires_its_evidence() -> None:
    payload = extract_hero_decision_points(
        multi_street_decision_record()
    ).decision_points[0].table_action.model_dump(mode="python")

    assert decisions.HeroTableAction.model_validate(payload) is not None
    assert len(payload["evidence"]) == 1

    with pytest.raises(ValidationError, match="at least 1 item"):
        decisions.HeroTableAction.model_validate({**payload, "evidence": []})


@pytest.mark.parametrize("declared", [1, 3, 9])
def test_decision_state_binds_the_declared_ring_to_its_seats(
    declared: int,
) -> None:
    payload = extract_hero_decision_points(
        multi_street_decision_record()
    ).decision_points[0].state.model_dump(mode="python")

    assert decisions.HeroDecisionState.model_validate(payload) is not None
    assert payload["dealt_in_player_count"] == len(payload["seats"]) == 2

    with pytest.raises(
        ValidationError,
        match=f"dealt_in_player_count {declared} does not match the 2 seats",
    ):
        decisions.HeroDecisionState.model_validate(
            {**payload, "dealt_in_player_count": declared}
        )


def test_decision_state_rejects_a_broken_seat_ring() -> None:
    payload = extract_hero_decision_points(
        contested_decision_record()
    ).decision_points[0].state.model_dump(mode="python")

    assert decisions.HeroDecisionState.model_validate(payload) is not None
    assert [
        seat["position"]["button_distance"] for seat in payload["seats"]
    ] == [0, 1, 2]

    out_of_order = copy.deepcopy(payload)
    out_of_order["seats"] = [
        out_of_order["seats"][1],
        out_of_order["seats"][0],
        out_of_order["seats"][2],
    ]
    with pytest.raises(ValidationError, match="once around the ring"):
        decisions.HeroDecisionState.model_validate(out_of_order)
