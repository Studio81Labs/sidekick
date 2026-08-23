import pytest
from pydantic import ValidationError

from app.domain.poker import (
    Card,
    CompletedPostflopAction,
    CompletedPostflopStreetHistory,
    PostflopAction,
    PreflopAction,
)
from app.models import CanonicalState
from app.models import Card as CompatibilityCard
from app.models import CompletedPostflopAction as CompatibilityCompletedAction
from app.models import (
    CompletedPostflopStreetHistory as CompatibilityCompletedHistory,
)
from app.models import PostflopAction as CompatibilityPostflopAction
from app.models import PreflopAction as CompatibilityPreflopAction


def test_models_compatibility_surface_reexports_poker_contracts() -> None:
    assert CompatibilityCard is Card
    assert CompatibilityPostflopAction is PostflopAction
    assert CompatibilityCompletedAction is CompletedPostflopAction
    assert CompatibilityCompletedHistory is CompletedPostflopStreetHistory
    assert CompatibilityPreflopAction is PreflopAction


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
