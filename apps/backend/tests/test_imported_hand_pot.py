from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.imported_hands import HandResults, ImportedHandState, reconcile_pot


NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


def evidence() -> dict[str, object]:
    return {"raw_source_id": "file-1", "line_start": 1}


def origin(*, forced: bool = False) -> dict[str, object]:
    return {
        "kind": "forced_system" if forced else "player_selected",
        "basis": "explicit_marker",
        "confidence": Decimal("1"),
        "evidence": [evidence()],
    }


def action(
    sequence: int,
    actor_id: str,
    action_type: str,
    *,
    amount: str | None = None,
    total: str | None = None,
    all_in: bool = False,
) -> dict[str, object]:
    forced = action_type.startswith("post_") or action_type == "uncalled_return"
    return {
        "sequence": sequence,
        "actor_id": actor_id,
        "action_type": action_type,
        "amount": Decimal(amount) if amount is not None else None,
        "total_committed": Decimal(total) if total is not None else None,
        "all_in": all_in,
        "origin": origin(forced=forced),
        "evidence": [evidence()],
    }


def hand(
    streets: list[dict[str, object]],
    *,
    stated_gross: str | None,
    rake: str | None = "0",
    stated_net: str | None = None,
    gross_pots: list[str] | None = None,
    awards: list[tuple[str, str | None, int | None]] | None = None,
    player_results: list[tuple[str, str | None, str | None]] | None = None,
    starting_stack: str = "200",
    starting_stacks: dict[str, str | None] | None = None,
    participations: dict[str, str] | None = None,
    include_results: bool = True,
    player_ids: list[str] | None = None,
) -> ImportedHandState:
    seat_player_ids = player_ids or ["p1", "p2", "p3"]
    represented_player_ids = {
        action_payload["actor_id"]
        for street in streets
        for action_payload in street["actions"]
    } | {
        player_id for player_id, _, _ in (awards or [])
    } | {
        player_id for player_id, _, _ in (player_results or [])
    }
    stated = None
    if stated_gross is not None or stated_net is not None or gross_pots:
        stated = {
            "gross_total": Decimal(stated_gross) if stated_gross is not None else None,
            "rake": Decimal(rake) if rake is not None else None,
            "net_total": Decimal(stated_net) if stated_net is not None else None,
            "gross_pots": [Decimal(value) for value in (gross_pots or [])],
        }
    return ImportedHandState(
        identity={"site": "pokerstars", "source_hand_id": "123"},
        chronology={"source_file_id": "file-1"},
        game={
            "betting_limit": "no_limit",
            "table_size": len(seat_player_ids),
            "blinds": {
                "small_blind": Decimal("0.5"),
                "big_blind": Decimal("1"),
            },
            "economics": {
                "kind": "cash",
                "currency": "USD",
                "rake": None,
            },
        },
        button_seat=1,
        seats=[
            {
                "seat_number": index,
                "player_id": player_id,
                "starting_stack": (
                    Decimal(stack)
                    if (
                        stack := (starting_stacks or {}).get(
                            player_id, starting_stack
                        )
                    )
                    is not None
                    else None
                ),
                "participation": (
                    (participations or {}).get(
                        player_id,
                        (
                            "dealt_in"
                            if player_id in represented_player_ids
                            else "not_dealt"
                        ),
                    )
                ),
            }
            for index, player_id in enumerate(seat_player_ids, start=1)
        ],
        streets=streets,
        results=(
            {
                "stated_pot": stated,
                "awards": [
                    {
                        "player_id": player_id,
                        "amount": Decimal(amount) if amount is not None else None,
                        "pot_index": pot_index,
                        "evidence": [evidence()],
                    }
                    for player_id, amount, pot_index in (awards or [])
                ],
                "players": [
                    {
                        "player_id": player_id,
                        "total_collected": (
                            Decimal(total_collected)
                            if total_collected is not None
                            else None
                        ),
                        "net_result": (
                            Decimal(net_result)
                            if net_result is not None
                            else None
                        ),
                    }
                    for player_id, total_collected, net_result in (player_results or [])
                ],
            }
            if include_results
            else None
        ),
    )


def test_reconciles_basic_blinds_call_and_check() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[("p1", "2", 0)],
        player_results=[("p1", "2", "1")],
    )

    result = reconcile_pot(state)

    assert result.status == "pass"
    assert result.derived_gross_total == Decimal("2.0")
    assert result.contributions == {
        "p1": Decimal("1.0"),
        "p2": Decimal("1"),
        "p3": Decimal("0"),
    }
    assert [pot.amount for pot in result.pots] == [Decimal("2.0")]
    assert result.amount_parse_validated_only is True


def test_reconciles_per_street_commitments_rake_and_aggregate_awards() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            },
            {
                "street": "flop",
                "board_cards": [
                    {"rank": "A", "suit": "spades"},
                    {"rank": "K", "suit": "hearts"},
                    {"rank": "2", "suit": "clubs"},
                ],
                "actions": [
                    action(0, "p2", "bet", amount="4", total="4"),
                    action(1, "p1", "call", amount="4", total="4"),
                ],
            },
        ],
        stated_gross="10",
        rake="0.5",
        stated_net="9.5",
        awards=[("p1", "9.5", 0)],
    )

    result = reconcile_pot(state)

    assert result.status == "pass"
    assert result.contributions["p1"] == Decimal("5.0")
    assert result.contributions["p2"] == Decimal("5")
    assert result.derived_gross_total == Decimal("10.0")
    assert result.derived_net_total == Decimal("9.5")
    assert result.awarded_total == Decimal("9.5")


def test_reconciles_uncalled_return_before_comparing_the_pot() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "raise", amount="2.5", total="3"),
                    action(3, "p2", "fold", total="1"),
                    action(4, "p1", "uncalled_return", amount="2", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[("p1", "2", 0)],
        player_results=[("p1", "2", "1")],
    )

    result = reconcile_pot(state)

    assert result.status == "pass"
    assert result.uncalled_returns == {"p1": Decimal("2")}
    assert result.contributions["p1"] == Decimal("1.0")
    assert result.pots[0].eligible_players == ["p1"]


def test_short_big_blind_nominal_call_return_reconciles_without_missing_return() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(
                        0,
                        "p3",
                        "post_big_blind",
                        amount="0.5",
                        total="0.5",
                    ),
                    action(1, "p1", "call", amount="1", total="1"),
                    action(2, "p2", "fold", total="0"),
                    action(
                        3,
                        "p1",
                        "uncalled_return",
                        amount="0.5",
                        total="0.5",
                    ),
                ],
            }
        ],
        stated_gross="1",
        stated_net="1",
        awards=[("p1", "1", 0)],
        starting_stacks={"p3": "0.5"},
    )

    result = reconcile_pot(state)

    assert result.status == "pass"
    assert not any("uncalled return is missing" in error for error in result.errors)


@pytest.mark.parametrize(
    ("return_total", "stated_total", "expected_status"),
    [("4", "5", "fail"), ("1", "2", "pass")],
)
def test_total_only_uncalled_return_cannot_increase_commitment(
    return_total: str, stated_total: str, expected_status: str
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="3", total="3"),
                    action(1, "p2", "call", amount="1", total="1", all_in=True),
                    action(2, "p1", "uncalled_return", total=return_total),
                ],
            }
        ],
        stated_gross=stated_total,
        stated_net=stated_total,
        awards=[("p1", stated_total, None)],
        starting_stacks={"p2": "1"},
        include_results=expected_status == "pass",
    )
    if expected_status == "fail":
        state = state.model_copy(
            update={
                "results": HandResults.model_validate(
                    {
                        "stated_pot": {
                            "gross_total": Decimal(stated_total),
                            "rake": Decimal("0"),
                            "net_total": Decimal(stated_total),
                        },
                        "awards": [
                            {
                                "player_id": "p1",
                                "amount": Decimal(stated_total),
                                "evidence": [evidence()],
                            }
                        ],
                    }
                )
            }
        )

    result = reconcile_pot(state)

    assert result.status == expected_status
    if expected_status == "fail":
        assert any(
            "uncalled return cannot increase total_committed" in error
            for error in result.errors
        )
    else:
        assert result.uncalled_returns == {"p1": Decimal("2")}


def test_missing_uncalled_return_fails_even_if_a_bad_source_total_matches() -> None:
    partial_state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "raise", amount="2.5", total="3"),
                    action(3, "p2", "fold", total="1"),
                ],
            }
        ],
        stated_gross="4",
        stated_net="4",
        awards=[("p1", "4", 0)],
        include_results=False,
    )
    state = partial_state.model_copy(
        update={
            "results": HandResults.model_validate(
                {
                    "stated_pot": {
                        "gross_total": Decimal("4"),
                        "rake": Decimal("0"),
                        "net_total": Decimal("4"),
                    },
                    "awards": [
                        {
                            "player_id": "p1",
                            "amount": Decimal("4"),
                            "pot_index": 0,
                            "evidence": [evidence()],
                        }
                    ],
                }
            )
        }
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any("uncalled return is missing" in error for error in result.errors)


def test_derives_all_in_main_and_side_pots_without_treating_folds_as_caps() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="20", total="20", all_in=True),
                    action(1, "p2", "call", amount="20", total="20"),
                    action(2, "p3", "call", amount="20", total="20"),
                ],
            },
            {
                "street": "flop",
                "board_cards": [
                    {"rank": "A", "suit": "spades"},
                    {"rank": "K", "suit": "hearts"},
                    {"rank": "2", "suit": "clubs"},
                ],
                "actions": [
                    action(0, "p2", "bet", amount="30", total="30", all_in=True),
                    action(1, "p3", "call", amount="30", total="30"),
                ],
            },
        ],
        stated_gross="120",
        stated_net="120",
        gross_pots=["60", "60"],
        awards=[("p1", "60", 0), ("p3", "60", 1)],
        starting_stacks={"p1": "20", "p2": "50"},
    )

    result = reconcile_pot(state)

    assert result.status == "pass"
    assert [pot.amount for pot in result.pots] == [Decimal("60"), Decimal("60")]
    assert result.pots[0].contributors == ["p1", "p2", "p3"]
    assert result.pots[1].contributors == ["p2", "p3"]


def test_known_exhausted_stack_creates_an_all_in_pot_boundary() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="5", total="5"),
                    action(1, "p2", "call", amount="5", total="5"),
                    action(2, "p3", "call", amount="5", total="5"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p2", "bet", amount="5", total="5"),
                    action(1, "p3", "call", amount="5", total="5"),
                ],
            },
        ],
        stated_gross="25",
        stated_net="25",
        gross_pots=["15", "10"],
        awards=[("p1", "15", 0), ("p2", "10", 1)],
        starting_stacks={"p1": "5", "p2": "10", "p3": "10"},
    )

    result = reconcile_pot(state)

    assert result.status == "pass"
    assert [pot.amount for pot in result.pots] == [Decimal("15"), Decimal("10")]
    assert result.pots[0].eligible_players == ["p1", "p2", "p3"]
    assert result.pots[1].eligible_players == ["p2", "p3"]


def test_false_all_in_marker_below_a_known_stack_does_not_split_the_pot() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="5", total="5", all_in=True),
                    action(1, "p2", "call", amount="5", total="5"),
                    action(2, "p3", "call", amount="5", total="5"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p2", "bet", amount="5", total="5"),
                    action(1, "p3", "call", amount="5", total="5"),
                ],
            },
        ],
        stated_gross="25",
        stated_net="25",
        gross_pots=["15", "10"],
        awards=[("p1", "15", 0), ("p2", "10", 1)],
        starting_stacks={"p1": "100", "p2": "10", "p3": "10"},
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert [pot.amount for pot in result.pots] == [Decimal("25")]
    assert any(
        "all-in cumulative commitment 5 does not exhaust starting stack 100"
        in error
        for error in result.errors
    )


def test_mismatched_side_pot_components_fail_without_guessing_rake_allocation() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="20", total="20", all_in=True),
                    action(1, "p2", "call", amount="20", total="20"),
                    action(2, "p3", "call", amount="20", total="20"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p2", "bet", amount="30", total="30"),
                    action(1, "p3", "call", amount="30", total="30"),
                ],
            },
        ],
        stated_gross="120",
        stated_net="120",
        gross_pots=["50", "70"],
        awards=[("p3", "120", None)],
        starting_stacks={"p1": "20"},
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any("main/side-pot layers" in error for error in result.errors)


def test_unknown_commitment_makes_reconciliation_indeterminate() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
    )

    result = reconcile_pot(state)

    assert result.status == "indeterminate"
    assert result.derived_gross_total is None
    assert result.errors == []


def test_amount_total_disagreement_and_award_mismatch_are_explicit_failures() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_ante", amount="0.5", total="1"),
                    action(1, "p2", "post_ante", amount="0.5", total="0.5"),
                ],
            }
        ],
        stated_gross="1",
        stated_net="1",
        awards=[("p1", "0.5", 0)],
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any("amount disagrees" in error for error in result.errors)
    assert any("aggregate pot awards" in error for error in result.errors)


def test_commitments_cannot_exceed_a_known_starting_stack() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="20", total="20", all_in=True),
                    action(1, "p2", "call", amount="20", total="20", all_in=True),
                ],
            }
        ],
        stated_gross="40",
        stated_net="40",
        awards=[("p1", "40", 0)],
        starting_stack="10",
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any("exceeds starting stack 10" in error for error in result.errors)


def test_indexed_award_must_reference_an_existing_pot() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[("p1", "2", 1)],
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any("nonexistent pot index 1" in error for error in result.errors)


def test_duplicate_nonexistent_pot_indexes_are_reported_once() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[("p1", "1", 1), ("p2", None, 1)],
    )

    result = reconcile_pot(state)

    assert [
        error for error in result.errors if "nonexistent pot index 1" in error
    ] == ["pot award references nonexistent pot index 1"]


def test_indexed_award_recipient_must_be_eligible_for_the_pot_layer() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="20", total="20", all_in=True),
                    action(1, "p2", "call", amount="20", total="20"),
                    action(2, "p3", "call", amount="20", total="20"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p2", "bet", amount="30", total="30", all_in=True),
                    action(1, "p3", "call", amount="30", total="30"),
                ],
            },
        ],
        stated_gross="120",
        stated_net="120",
        gross_pots=["60", "60"],
        awards=[("p1", "60", 0), ("p1", "60", 1)],
        starting_stacks={"p1": "20", "p2": "50"},
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any("p1 is not eligible for pot index 1" in error for error in result.errors)


def test_duplicate_indexed_ineligibility_is_reported_once_per_recipient_and_pot(
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="20", total="20", all_in=True),
                    action(1, "p2", "call", amount="20", total="20"),
                    action(2, "p3", "call", amount="20", total="20"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p2", "bet", amount="30", total="30", all_in=True),
                    action(1, "p3", "call", amount="30", total="30"),
                ],
            },
        ],
        stated_gross="120",
        stated_net="120",
        gross_pots=["60", "60"],
        awards=[("p1", "60", 0), ("p1", "30", 1), ("p1", "30", 1)],
        starting_stacks={"p1": "20", "p2": "50"},
    )

    result = reconcile_pot(state)

    assert [
        error
        for error in result.errors
        if "p1 is not eligible for pot index 1" in error
    ] == ["pot award recipient p1 is not eligible for pot index 1"]


def test_unindexed_award_recipient_must_be_eligible_for_a_derived_pot() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "fold", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[("p2", "2", None)],
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any(
        "unindexed pot award recipient p2 is not eligible for any derived pot"
        in error
        for error in result.errors
    )


def test_duplicate_unindexed_ineligibility_is_reported_once_per_recipient() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "fold", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[("p2", "1", None), ("p2", "1", None)],
    )

    result = reconcile_pot(state)

    assert [
        error
        for error in result.errors
        if "unindexed pot award recipient p2" in error
    ] == [
        "unindexed pot award recipient p2 is not eligible for any derived pot"
    ]


@pytest.mark.parametrize(
    ("awards", "expected_status", "expected_total"),
    [
        ([("p1", "25", None)], "fail", "25"),
        ([("p1", "8", None), ("p1", "8", None), ("p2", "9", None)], "fail", "16"),
        ([("p1", "15", None), ("p2", "10", None)], "pass", None),
        ([("p1", "10", 0), ("p1", "5", None), ("p2", "10", 1)], "pass", None),
        ([("p1", "10", 0), ("p1", "6", None), ("p2", "9", 1)], "fail", "16"),
    ],
)
def test_unindexed_awards_cannot_exceed_recipient_eligible_pot_layers(
    awards: list[tuple[str, str | None, int | None]],
    expected_status: str,
    expected_total: str | None,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="5", total="5"),
                    action(1, "p2", "call", amount="5", total="5"),
                    action(2, "p3", "call", amount="5", total="5"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p2", "bet", amount="5", total="5"),
                    action(1, "p3", "call", amount="5", total="5"),
                ],
            },
        ],
        stated_gross="25",
        stated_net="25",
        gross_pots=["15", "10"],
        awards=awards,
        starting_stacks={"p1": "5", "p2": "10", "p3": "10"},
    )

    result = reconcile_pot(state)

    assert result.status == expected_status
    capacity_errors = [
        error for error in result.errors if "eligible derived pots" in error
    ]
    if expected_total is None:
        assert capacity_errors == []
    else:
        assert capacity_errors == [
            f"concrete awards {expected_total} to p1 exceed eligible derived pots 15"
        ]


@pytest.mark.parametrize(
    ("awards", "expected_status"),
    [
        ([("p1", "15", None), ("p2", "15", None)], "fail"),
        (
            [("p1", "10", None), ("p2", "10", None), ("p3", "10", None)],
            "pass",
        ),
        ([("p3", "30", None)], "pass"),
    ],
)
def test_unindexed_awards_share_cumulative_eligible_pot_capacity(
    awards: list[tuple[str, str | None, int | None]],
    expected_status: str,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="5", total="5", all_in=True),
                    action(1, "p2", "call", amount="5", total="5", all_in=True),
                    action(2, "p3", "call", amount="5", total="5"),
                    action(3, "p4", "call", amount="5", total="5"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p3", "bet", amount="5", total="5"),
                    action(1, "p4", "call", amount="5", total="5"),
                ],
            },
        ],
        stated_gross="30",
        stated_net="30",
        gross_pots=["20", "10"],
        awards=awards,
        starting_stacks={"p1": "5", "p2": "5", "p3": "10", "p4": "10"},
        player_ids=["p1", "p2", "p3", "p4"],
    )

    result = reconcile_pot(state)

    assert result.status == expected_status
    shared_capacity_errors = [
        error for error in result.errors if "shared eligible pot capacity" in error
    ]
    if expected_status == "fail":
        assert shared_capacity_errors == [
            "concrete unindexed awards 30 for players p1, p2 exceed shared"
            " eligible pot capacity 20 through pot index 0"
        ]
    else:
        assert shared_capacity_errors == []


@pytest.mark.parametrize(
    ("awards", "expected_status", "expected_capacity"),
    [
        ([("p3", "20", 0), ("p1", "10", None)], "fail", "0"),
        (
            [("p3", "10", 0), ("p3", "10", 1), ("p1", "10", None)],
            "pass",
            None,
        ),
    ],
)
def test_unindexed_awards_share_capacity_remaining_after_indexed_awards(
    awards: list[tuple[str, str | None, int | None]],
    expected_status: str,
    expected_capacity: str | None,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="5", total="5", all_in=True),
                    action(1, "p2", "call", amount="5", total="5", all_in=True),
                    action(2, "p3", "call", amount="5", total="5"),
                    action(3, "p4", "call", amount="5", total="5"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p3", "bet", amount="5", total="5"),
                    action(1, "p4", "call", amount="5", total="5"),
                ],
            },
        ],
        stated_gross="30",
        stated_net="30",
        gross_pots=["20", "10"],
        awards=awards,
        starting_stacks={"p1": "5", "p2": "5", "p3": "10", "p4": "10"},
        player_ids=["p1", "p2", "p3", "p4"],
    )

    result = reconcile_pot(state)

    assert result.status == expected_status
    shared_capacity_errors = [
        error for error in result.errors if "shared eligible pot capacity" in error
    ]
    if expected_capacity is None:
        assert shared_capacity_errors == []
    else:
        assert shared_capacity_errors == [
            "concrete unindexed awards 10 for players p1 exceed shared"
            f" eligible pot capacity {expected_capacity} through pot index 0"
        ]


def test_exact_indexed_residual_failure_does_not_repeat_as_prefix_failure() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="5", total="5", all_in=True),
                    action(1, "p2", "call", amount="5", total="5", all_in=True),
                    action(2, "p3", "call", amount="5", total="5"),
                    action(3, "p4", "call", amount="5", total="5"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p3", "bet", amount="5", total="5"),
                    action(1, "p4", "call", amount="5", total="5"),
                ],
            },
        ],
        stated_gross="30",
        stated_net="30",
        gross_pots=["20", "10"],
        awards=[("p3", "20", 0), ("p1", None, 0)],
        starting_stacks={"p1": "5", "p2": "5", "p3": "10", "p4": "10"},
        player_ids=["p1", "p2", "p3", "p4"],
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert [
        error
        for error in result.errors
        if "unknown indexed pot awards require positive residual" in error
    ] == [
        "unknown indexed pot awards require positive residual capacity at pot index 0"
    ]
    assert not any(
        "positive residual beyond concrete" in error for error in result.errors
    )


@pytest.mark.parametrize(
    ("awards", "expected_status", "expected_cutoff"),
    [
        ([('p3', '20', 0), ('p1', None, None)], "fail", 0),
        ([('p3', '19.5', 0), ('p1', None, None)], "indeterminate", None),
        (
            [('p1', '10', None), ('p2', '10', None), ('p1', None, None)],
            "fail",
            0,
        ),
        (
            [('p1', '10', None), ('p2', '10', None), ('p3', None, None)],
            "indeterminate",
            None,
        ),
    ],
)
def test_unknown_unindexed_awards_require_reachable_nested_capacity(
    awards: list[tuple[str, str | None, int | None]],
    expected_status: str,
    expected_cutoff: int | None,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="5", total="5", all_in=True),
                    action(1, "p2", "call", amount="5", total="5", all_in=True),
                    action(2, "p3", "call", amount="5", total="5"),
                    action(3, "p4", "call", amount="5", total="5"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p3", "bet", amount="5", total="5"),
                    action(1, "p4", "call", amount="5", total="5"),
                ],
            },
        ],
        stated_gross="30",
        stated_net="30",
        gross_pots=["20", "10"],
        awards=awards,
        starting_stacks={"p1": "5", "p2": "5", "p3": "10", "p4": "10"},
        player_ids=["p1", "p2", "p3", "p4"],
    )

    result = reconcile_pot(state)

    assert result.status == expected_status
    positive_residual_errors = [
        error
        for error in result.errors
        if "unknown pot awards require positive residual beyond" in error
    ]
    if expected_cutoff is None:
        assert positive_residual_errors == []
        assert result.errors == []
    else:
        assert len(positive_residual_errors) == 1
        assert positive_residual_errors[0].endswith(
            f"through pot index {expected_cutoff}"
        )


@pytest.mark.parametrize(
    ("awards", "expected_status", "expected_cutoff"),
    [
        (
            [('p1', '10', None), ('p2', '10', None), ('p3', None, 0)],
            "fail",
            0,
        ),
        (
            [('p1', '9.5', None), ('p2', '10', None), ('p3', None, 0)],
            "indeterminate",
            None,
        ),
        (
            [
                ('p1', '10', None),
                ('p2', '10', None),
                ('p3', '10', None),
                ('p4', None, 1),
            ],
            "fail",
            None,
        ),
        (
            [
                ('p1', '10', None),
                ('p2', '10', None),
                ('p3', '9.5', None),
                ('p4', None, 1),
            ],
            "indeterminate",
            None,
        ),
    ],
)
def test_unknown_indexed_awards_participate_in_prefix_and_final_capacity(
    awards: list[tuple[str, str | None, int | None]],
    expected_status: str,
    expected_cutoff: int | None,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="5", total="5", all_in=True),
                    action(1, "p2", "call", amount="5", total="5", all_in=True),
                    action(2, "p3", "call", amount="5", total="5"),
                    action(3, "p4", "call", amount="5", total="5"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p3", "bet", amount="5", total="5"),
                    action(1, "p4", "call", amount="5", total="5"),
                ],
            },
        ],
        stated_gross="30",
        stated_net="30",
        gross_pots=["20", "10"],
        awards=awards,
        starting_stacks={"p1": "5", "p2": "5", "p3": "10", "p4": "10"},
        player_ids=["p1", "p2", "p3", "p4"],
    )

    result = reconcile_pot(state)

    assert result.status == expected_status
    positive_residual_errors = [
        error
        for error in result.errors
        if "unknown pot awards require positive residual beyond" in error
    ]
    if expected_cutoff is None:
        assert positive_residual_errors == []
        if expected_status == "indeterminate":
            assert result.errors == []
    else:
        assert any(
            error.endswith(f"through pot index {expected_cutoff}")
            for error in positive_residual_errors
        )


def test_unknown_unindexed_award_amount_keeps_recipient_capacity_reviewable() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="5", total="5"),
                    action(1, "p2", "call", amount="5", total="5"),
                    action(2, "p3", "call", amount="5", total="5"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p2", "bet", amount="5", total="5"),
                    action(1, "p3", "call", amount="5", total="5"),
                ],
            },
        ],
        stated_gross="25",
        stated_net="25",
        gross_pots=["15", "10"],
        awards=[("p1", None, None)],
        starting_stacks={"p1": "5", "p2": "10", "p3": "10"},
    )

    result = reconcile_pot(state)

    assert result.status == "indeterminate"
    assert not any("eligible derived pots" in error for error in result.errors)


@pytest.mark.parametrize(
    ("rake", "stated_net", "known_total", "ceiling"),
    [("0.5", "1.5", "1.5", "1.5"), (None, None, "2", "2")],
)
def test_unknown_award_requires_positive_global_net_or_gross_residual(
    rake: str | None,
    stated_net: str | None,
    known_total: str,
    ceiling: str,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        rake=rake,
        stated_net=stated_net,
        awards=[("p1", known_total, 0), ("p2", None, None)],
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert (
        f"unknown pot awards require positive residual below known distributable pot"
        f" {ceiling}"
    ) in result.errors


@pytest.mark.parametrize(
    ("known_indexed", "expected_status"),
    [("2", "fail"), ("1.5", "indeterminate")],
)
def test_unknown_indexed_award_requires_positive_exact_pot_residual(
    known_indexed: str,
    expected_status: str,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[("p1", known_indexed, 0), ("p2", None, 0)],
    )

    result = reconcile_pot(state)

    assert result.status == expected_status
    exact_residual_errors = [
        error
        for error in result.errors
        if "unknown indexed pot awards require positive residual capacity" in error
    ]
    if expected_status == "fail":
        assert exact_residual_errors == []
        assert (
            "unknown pot awards require positive residual below known"
            " distributable pot 2"
        ) in result.errors
        assert not any(
            "positive residual beyond concrete" in error
            for error in result.errors
        )
    else:
        assert exact_residual_errors == []
        assert result.errors == []


@pytest.mark.parametrize(
    ("rake", "stated_net", "awards", "known_total", "ceiling"),
    [
        (
            "0.5",
            "1.5",
            [("p1", "1", 0), ("p2", "0.75", None), ("p1", None, None)],
            "1.75",
            "1.5",
        ),
        (
            None,
            None,
            [("p1", "1.5", None), ("p2", "1", None), ("p1", None, None)],
            "2.5",
            "2",
        ),
    ],
)
def test_known_award_subtotal_cannot_exceed_distributable_net_or_gross(
    rake: str | None,
    stated_net: str | None,
    awards: list[tuple[str, str | None, int | None]],
    known_total: str,
    ceiling: str,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        rake=rake,
        stated_net=stated_net,
        awards=awards,
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any(
        f"known concrete pot awards {known_total} exceed known distributable pot"
        f" {ceiling}" in error
        for error in result.errors
    )


@pytest.mark.parametrize(
    ("unindexed_amount", "expected_status", "expected_residual"),
    [("0.75", "fail", "0.5"), ("0.25", "indeterminate", None)],
)
def test_unindexed_awards_share_final_capacity_remaining_after_indexed_awards(
    unindexed_amount: str,
    expected_status: str,
    expected_residual: str | None,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[
            ("p1", "1.5", 0),
            ("p2", unindexed_amount, None),
            ("p1", None, None),
        ],
    )

    result = reconcile_pot(state)

    assert result.status == expected_status
    shared_capacity_errors = [
        error for error in result.errors if "shared eligible pot capacity" in error
    ]
    if expected_residual is None:
        assert shared_capacity_errors == []
        assert result.errors == []
    else:
        assert shared_capacity_errors == [
            f"concrete unindexed awards {unindexed_amount} for players p2 exceed"
            f" shared eligible pot capacity {expected_residual} through pot index 0"
        ]


def test_incomplete_contributions_keep_unindexed_award_capacity_reviewable() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[("p1", "2", None)],
    )

    result = reconcile_pot(state)

    assert result.status == "indeterminate"
    assert not any("eligible derived pots" in error for error in result.errors)


def test_incomplete_contributions_preserve_unknown_global_positive_demand() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[("p1", "2", None), ("p2", None, None)],
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert [
        error
        for error in result.errors
        if "unknown pot awards require positive residual" in error
    ] == [
        "unknown pot awards require positive residual below known distributable pot 2"
    ]


def test_aggregate_awards_cannot_exceed_a_known_gross_pot() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        rake=None,
        awards=[("p1", "100", None)],
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any(
        "aggregate pot awards 100 exceed known gross pot 2" in error
        for error in result.errors
    )


def test_player_collections_cannot_exceed_the_distributable_pot() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        player_results=[("p1", "100", None)],
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any(
        "known player collections 100 exceed known distributable pot 2" in error
        for error in result.errors
    )


@pytest.mark.parametrize(
    ("include_totals", "collections", "rake", "stated_net", "expected_status"),
    [
        (True, ("1", "0"), "0", "2", "fail"),
        (False, ("1", "0"), "0", "2", "fail"),
        (True, ("1", "1"), "0", "2", "pass"),
        (True, ("1.5", "0"), "0.5", "1.5", "pass"),
    ],
)
def test_complete_player_results_must_distribute_the_net_pot(
    include_totals: bool,
    collections: tuple[str, str],
    rake: str,
    stated_net: str,
    expected_status: str,
) -> None:
    contributions = {"p1": Decimal("1"), "p2": Decimal("1")}
    player_results = [
        (
            player_id,
            collection if include_totals else None,
            str(Decimal(collection) - contributions[player_id]),
        )
        for player_id, collection in zip(contributions, collections, strict=True)
    ]
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        rake=rake,
        stated_net=stated_net,
        player_results=player_results,
    )

    result = reconcile_pot(state)

    assert result.status == expected_status
    distribution_errors = [
        error
        for error in result.errors
        if "complete player result collections" in error
    ]
    if expected_status == "fail":
        expected_collection = "1" if include_totals else "1.0"
        assert distribution_errors == [
            f"complete player result collections {expected_collection} do not"
            " match distributable pot 2"
        ]
    else:
        assert distribution_errors == []


def test_partial_player_results_do_not_assert_complete_distribution() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        player_results=[("p1", "1", "0")],
    )

    result = reconcile_pot(state)

    assert result.status == "pass"
    assert not any(
        "complete player result collections" in error for error in result.errors
    )


def test_incomplete_contributions_do_not_assert_complete_result_distribution() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        player_results=[("p1", "1", None), ("p2", "0", None)],
    )

    result = reconcile_pot(state)

    assert result.status == "indeterminate"
    assert not any(
        "complete player result collections" in error for error in result.errors
    )


def test_unknown_distributable_net_does_not_assert_complete_result_distribution(
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        rake=None,
        player_results=[("p1", "1", "0"), ("p2", "0", "-1")],
    )

    result = reconcile_pot(state)

    assert result.status == "pass"
    assert not any(
        "complete player result collections" in error for error in result.errors
    )


@pytest.mark.parametrize(
    ("player_id", "total_collected", "net_result", "expected_status"),
    [
        ("p2", "2", "1", "fail"),
        ("p1", "2", "1", "pass"),
        ("p2", "0", "-1", "pass"),
    ],
)
def test_player_result_collections_require_derived_pot_eligibility(
    player_id: str,
    total_collected: str,
    net_result: str,
    expected_status: str,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "fold", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        player_results=[(player_id, total_collected, net_result)],
    )

    result = reconcile_pot(state)

    assert result.status == expected_status
    eligibility_errors = [
        error for error in result.errors if "not eligible for any derived pot" in error
    ]
    if expected_status == "fail":
        assert eligibility_errors == [
            "player result p2 has positive collection 2 but is not eligible"
            " for any derived pot"
        ]
    else:
        assert eligibility_errors == []


def test_implied_player_collection_requires_derived_pot_eligibility() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "fold", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        player_results=[("p2", None, "1")],
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any(
        "player result p2 has positive collection 2 but is not eligible"
        " for any derived pot" in error
        for error in result.errors
    )


@pytest.mark.parametrize(
    (
        "player_id",
        "total_collected",
        "net_result",
        "expected_status",
        "expected_eligible_total",
    ),
    [
        ("p1", "25", "20", "fail", "15"),
        ("p1", None, "20", "fail", "15"),
        ("p1", "15", "10", "pass", None),
        ("p2", "25", "15", "pass", None),
    ],
)
def test_player_result_collection_cannot_exceed_eligible_pot_layers(
    player_id: str,
    total_collected: str | None,
    net_result: str,
    expected_status: str,
    expected_eligible_total: str | None,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="5", total="5"),
                    action(1, "p2", "call", amount="5", total="5"),
                    action(2, "p3", "call", amount="5", total="5"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p2", "bet", amount="5", total="5"),
                    action(1, "p3", "call", amount="5", total="5"),
                ],
            },
        ],
        stated_gross="25",
        stated_net="25",
        gross_pots=["15", "10"],
        player_results=[(player_id, total_collected, net_result)],
        starting_stacks={"p1": "5", "p2": "10", "p3": "10"},
    )

    result = reconcile_pot(state)

    assert result.status == expected_status
    capacity_errors = [
        error
        for error in result.errors
        if "player result" in error and "eligible derived pots" in error
    ]
    if expected_eligible_total is None:
        assert capacity_errors == []
    else:
        collection = (
            Decimal(total_collected)
            if total_collected is not None
            else Decimal(net_result) + result.contributions[player_id]
        )
        assert capacity_errors == [
            f"player result {player_id} collection {collection} exceeds"
            f" eligible derived pots {expected_eligible_total}"
        ]


@pytest.mark.parametrize(
    ("include_totals", "collections", "expected_status"),
    [
        (True, ("15", "15", "0", "0"), "fail"),
        (False, ("15", "15", "0", "0"), "fail"),
        (True, ("10", "10", "10", "0"), "pass"),
        (True, ("0", "0", "30", "0"), "pass"),
    ],
)
def test_player_results_share_cumulative_eligible_pot_capacity(
    include_totals: bool,
    collections: tuple[str, str, str, str],
    expected_status: str,
) -> None:
    contributions = {
        "p1": Decimal("5"),
        "p2": Decimal("5"),
        "p3": Decimal("10"),
        "p4": Decimal("10"),
    }
    player_results = [
        (
            player_id,
            collection if include_totals else None,
            str(Decimal(collection) - contributions[player_id]),
        )
        for player_id, collection in zip(contributions, collections, strict=True)
    ]
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="5", total="5", all_in=True),
                    action(1, "p2", "call", amount="5", total="5", all_in=True),
                    action(2, "p3", "call", amount="5", total="5"),
                    action(3, "p4", "call", amount="5", total="5"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p3", "bet", amount="5", total="5"),
                    action(1, "p4", "call", amount="5", total="5"),
                ],
            },
        ],
        stated_gross="30",
        stated_net="30",
        gross_pots=["20", "10"],
        player_results=player_results,
        starting_stacks={"p1": "5", "p2": "5", "p3": "10", "p4": "10"},
        player_ids=["p1", "p2", "p3", "p4"],
    )

    result = reconcile_pot(state)

    assert result.status == expected_status
    shared_capacity_errors = [
        error for error in result.errors if "shared eligible pot capacity" in error
    ]
    if expected_status == "fail":
        assert shared_capacity_errors == [
            "known player collections 30 for players p1, p2 exceed shared"
            " eligible pot capacity 20 through pot index 0"
        ]
    else:
        assert shared_capacity_errors == []


@pytest.mark.parametrize(
    ("total_collected", "net_result", "message"),
    [
        ("1", "0", "does not match concrete awards 2"),
        ("2", "0", "does not match collected 2 minus contribution 1"),
    ],
)
def test_player_results_must_reconcile_with_awards_and_contributions(
    total_collected: str, net_result: str, message: str
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[("p1", "2", None)],
        player_results=[("p1", total_collected, net_result)],
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any(message in error for error in result.errors)


@pytest.mark.parametrize(
    ("total_collected", "net_result", "expected_status", "message"),
    [
        ("2", "1", "fail", "does not match concrete awards 0"),
        (None, "1", "fail", "does not match collected 0 minus contribution 1"),
        ("0", "-1", "pass", None),
        (None, "-1", "pass", None),
    ],
)
def test_exhaustive_concrete_awards_reconcile_results_for_players_without_awards(
    total_collected: str | None,
    net_result: str,
    expected_status: str,
    message: str | None,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[("p1", "2", None)],
        player_results=[("p2", total_collected, net_result)],
    )

    result = reconcile_pot(state)

    assert result.status == expected_status
    if message is not None:
        assert any(message in error for error in result.errors)
    else:
        assert result.errors == []


def test_concrete_awards_do_not_imply_zero_for_other_players_without_a_known_net() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        rake=None,
        awards=[("p1", "2", None)],
        player_results=[("p2", "2", "1")],
    )

    result = reconcile_pot(state)

    assert result.status == "pass"
    assert not any("does not match concrete awards 0" in error for error in result.errors)


def test_derived_net_can_make_concrete_awards_exhaustive_for_player_results() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        rake="0",
        awards=[("p1", "1", None), ("p1", "1", None)],
        player_results=[("p1", "2", "1"), ("p2", "0", "-1")],
    )

    result = reconcile_pot(state)

    assert result.status == "pass"
    assert result.derived_net_total == Decimal("2")
    assert result.errors == []


@pytest.mark.parametrize(
    ("stated_gross", "gross_pots", "rake", "distributable_net"),
    [
        ("2", None, "0", "2"),
        (None, ["2"], "0", "2"),
        ("2", None, "0.5", "1.5"),
    ],
)
def test_stated_gross_and_rake_make_awards_exhaustive_when_actions_are_incomplete(
    stated_gross: str | None,
    gross_pots: list[str] | None,
    rake: str,
    distributable_net: str,
) -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call"),
                ],
            }
        ],
        stated_gross=stated_gross,
        gross_pots=gross_pots,
        rake=rake,
        awards=[("p1", distributable_net, None)],
        player_results=[("p2", distributable_net, "1")],
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert result.derived_net_total is None
    assert any(
        f"player result p2 total_collected {distributable_net} does not match"
        " concrete awards 0" in error
        for error in result.errors
    )


def test_unknown_rake_keeps_award_exhaustiveness_indeterminate_with_incomplete_actions() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call"),
                ],
            }
        ],
        stated_gross="2",
        rake=None,
        awards=[("p1", "2", None)],
        player_results=[("p2", "2", "1")],
    )

    result = reconcile_pot(state)

    assert result.status == "indeterminate"
    assert result.derived_net_total is None
    assert not any("does not match concrete awards 0" in error for error in result.errors)


def test_unknown_award_amount_does_not_imply_zero_for_other_players() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "post_small_blind", amount="0.5", total="0.5"),
                    action(1, "p2", "post_big_blind", amount="1", total="1"),
                    action(2, "p1", "call", amount="0.5", total="1"),
                    action(3, "p2", "check", total="1"),
                ],
            }
        ],
        stated_gross="2",
        stated_net="2",
        awards=[("p1", None, None)],
        player_results=[("p2", "2", "1")],
    )

    result = reconcile_pot(state)

    assert result.status == "indeterminate"
    assert not any("does not match concrete awards 0" in error for error in result.errors)


def test_zero_rake_indexed_awards_must_reconcile_each_pot_layer() -> None:
    state = hand(
        [
            {
                "street": "preflop",
                "actions": [
                    action(0, "p1", "bet", amount="20", total="20", all_in=True),
                    action(1, "p2", "call", amount="20", total="20"),
                    action(2, "p3", "call", amount="20", total="20"),
                ],
            },
            {
                "street": "flop",
                "actions": [
                    action(0, "p2", "bet", amount="30", total="30", all_in=True),
                    action(1, "p3", "call", amount="30", total="30"),
                ],
            },
        ],
        stated_gross="120",
        stated_net="120",
        gross_pots=["60", "60"],
        awards=[("p3", "70", 0), ("p3", "50", 1)],
        starting_stacks={"p1": "20", "p2": "50"},
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any("indexed awards 70 exceed gross pot 60" in error for error in result.errors)
    assert not any(
        "indexed awards 70 do not match pot 60" in error for error in result.errors
    )
    assert any("indexed awards 50 do not match pot 60" in error for error in result.errors)
