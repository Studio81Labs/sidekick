import pytest
from pydantic import ValidationError

from app.domain.poker import (
    Card,
    CanonicalState,
    CompletedPostflopAction,
    CompletedPostflopStreetHistory,
    DetectedState,
    ParserResult,
    PostflopAction,
    PreflopAction,
)
from app.models import Card as CompatibilityCard
from app.models import CanonicalState as CompatibilityCanonicalState
from app.models import CompletedPostflopAction as CompatibilityCompletedAction
from app.models import (
    CompletedPostflopStreetHistory as CompatibilityCompletedHistory,
)
from app.models import DetectedState as CompatibilityDetectedState
from app.models import ParserResult as CompatibilityParserResult
from app.models import PostflopAction as CompatibilityPostflopAction
from app.models import PreflopAction as CompatibilityPreflopAction


def test_models_compatibility_surface_reexports_poker_contracts() -> None:
    assert CompatibilityCard is Card
    assert CompatibilityPostflopAction is PostflopAction
    assert CompatibilityCompletedAction is CompletedPostflopAction
    assert CompatibilityCompletedHistory is CompletedPostflopStreetHistory
    assert CompatibilityPreflopAction is PreflopAction
    assert CompatibilityDetectedState is DetectedState
    assert CompatibilityParserResult is ParserResult
    assert CompatibilityCanonicalState is CanonicalState


def test_card_codes_retain_normalization_and_serialization() -> None:
    card = Card.from_code("10H")

    assert card.code == "Th"
    assert card.model_dump(mode="json") == {"rank": "T", "suit": "hearts"}


def test_completed_postflop_history_accepts_a_terminal_call() -> None:
    history = CompletedPostflopStreetHistory(
        street="flop",
        actions=[
            {"actor": "oop", "action": "bet", "amount": 2.5},
            {"actor": "ip", "action": "call", "amount": 2.5},
        ],
    )

    assert [action.action for action in history.actions] == ["bet", "call"]


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (PostflopAction, {"actor": "oop", "action": "check", "amount": 1.0}),
        (PreflopAction, {"actor": "button", "action": "raise", "amount": 0}),
        (
            CompletedPostflopStreetHistory,
            {
                "street": "flop",
                "actions": [
                    {"actor": "oop", "action": "bet", "amount": 2.5},
                    {"actor": "ip", "action": "check"},
                ],
            },
        ),
    ],
)
def test_poker_contracts_reject_invalid_actions(
    model: type[PostflopAction]
    | type[PreflopAction]
    | type[CompletedPostflopStreetHistory],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_canonical_state_uses_domain_poker_contracts() -> None:
    state = CanonicalState(
        hero_cards=[{"rank": "A", "suit": "hearts"}],
        preflop_action_history=[
            {"actor": "button", "action": "raise", "amount": 2.5}
        ],
    )

    assert type(state.hero_cards[0]) is Card
    assert type(state.preflop_action_history[0]) is PreflopAction


def test_parser_state_conversion_preserves_values_without_approval() -> None:
    parser_result = ParserResult(
        state={
            "hero_cards": [
                {"rank": "A", "suit": "hearts"},
                {"rank": "K", "suit": "diamonds"},
            ],
            "board_cards": [
                {"rank": "Q", "suit": "spades"},
                {"rank": "J", "suit": "clubs"},
                {"rank": "2", "suit": "hearts"},
            ],
            "pot_size": 12.5,
            "current_bet": 2.5,
            "players_in_hand": 3,
            "opponents_at_current_bet": 1,
            "opponent_wager": 2.5,
            "street": "flop",
        },
        confidences={"hero_cards": 0.99, "pot_size": 0.92},
        warnings=["Review opponent position"],
    )

    canonical = CanonicalState.from_parser_result(parser_result)

    assert canonical.model_dump(mode="json") == {
        **parser_result.state.model_dump(mode="json"),
        "user_approved": False,
    }
    assert canonical.hero_cards is not parser_result.state.hero_cards


def test_detected_state_json_round_trip_preserves_action_history() -> None:
    state = DetectedState(
        hero_cards=[
            {"rank": "A", "suit": "hearts"},
            {"rank": "K", "suit": "diamonds"},
        ],
        board_cards=[
            {"rank": "Q", "suit": "spades"},
            {"rank": "J", "suit": "clubs"},
            {"rank": "2", "suit": "hearts"},
            {"rank": "3", "suit": "diamonds"},
        ],
        pot_size=18.0,
        current_bet=4.0,
        players_in_hand=2,
        opponents_at_current_bet=1,
        opponent_wager=4.0,
        opponent_commitment_total=4.0,
        street="turn",
        completed_postflop_streets=[
            {
                "street": "flop",
                "actions": [
                    {"actor": "oop", "action": "bet", "amount": 5.0},
                    {"actor": "ip", "action": "call", "amount": 5.0},
                ],
            }
        ],
        postflop_action_history=[
            {"actor": "oop", "action": "bet", "amount": 4.0}
        ],
    )

    restored = DetectedState.model_validate_json(state.model_dump_json())

    assert restored == state


@pytest.mark.parametrize(
    "payload",
    [
        {
            "hero_cards": [
                {"rank": "A", "suit": "hearts"},
                {"rank": "A", "suit": "hearts"},
            ]
        },
        {"confidences": {"hero_cards": 1.01}},
        {
            "state": {
                "current_bet": 2.5,
                "players_in_hand": 2,
                "opponents_at_current_bet": 2,
            }
        },
    ],
)
def test_state_contracts_reject_invalid_legacy_payloads(
    payload: dict[str, object],
) -> None:
    model = (
        ParserResult
        if "state" in payload or "confidences" in payload
        else DetectedState
    )
    parser_payload = payload
    if model is ParserResult and "state" not in payload:
        parser_payload = {"state": {}, **payload}

    with pytest.raises(ValidationError):
        model.model_validate(parser_payload)
