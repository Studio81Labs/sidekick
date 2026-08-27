from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.domain.imported_hands import ImportedHandState, reconcile_pot


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
) -> ImportedHandState:
    player_ids = ["p1", "p2", "p3"]
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
            "table_size": 3,
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
                "participation": "dealt_in",
            }
            for index, player_id in enumerate(player_ids, start=1)
        ],
        streets=streets,
        results={
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
                        Decimal(net_result) if net_result is not None else None
                    ),
                }
                for player_id, total_collected, net_result in (player_results or [])
            ],
        },
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
    state = hand(
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
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any("p1 is not eligible for pot index 1" in error for error in result.errors)


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
    )

    result = reconcile_pot(state)

    assert result.status == "fail"
    assert any("indexed awards 70 exceed gross pot 60" in error for error in result.errors)
    assert any("indexed awards 50 do not match pot 60" in error for error in result.errors)
