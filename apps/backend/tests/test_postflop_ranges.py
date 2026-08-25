from __future__ import annotations

from typing import Literal

import pytest

from app.config import DEFAULT_POSTFLOP_IP_RANGE, DEFAULT_POSTFLOP_OOP_RANGE
from app.domain.poker import (
    CanonicalState,
    CompletedPostflopAction,
    CompletedPostflopStreetHistory,
    PostflopAction,
    PreflopAction,
)
from app.solvers.preflop_context import POSTED_BLIND_BB, Position
from app.solvers.postflop_ranges import (
    resolve_cold_four_bet_pot_relative_position,
    resolve_isolation_raised_pot_relative_position,
    resolve_limp_reraised_pot_relative_position,
    resolve_squeeze_pot_relative_position,
    select_postflop_ranges,
)
from app.solvers.preflop_chart import (
    COLD_FOUR_BET_DEFENSE_POLICIES,
    COLD_THREE_BET_DEFENSE_POLICIES,
    FOUR_BET_DEFENSE_POLICIES,
    ISOLATION_RESPONSE_POLICIES,
    LIMP_RERAISE_RESPONSE_POLICIES,
    SQUEEZE_DEFENSE_POLICIES,
    THREE_BET_DEFENSE_POLICIES,
    hand_classes_in_policy_band,
)


def limped_pot_state(
    *,
    hero_position: str = "big_blind",
    limper_position: str = "button",
) -> CanonicalState:
    opponent_position = (
        limper_position if hero_position == "big_blind" else "big_blind"
    )
    return CanonicalState(
        players_in_hand=2,
        hero_position=hero_position,
        opponent_position=opponent_position,
        street="flop",
        pot_size=2.0 if limper_position == "small_blind" else 2.5,
        current_bet=0,
        effective_stack=99.0,
        preflop_action_history=[
            PreflopAction(actor=limper_position, action="call", amount=1.0),
        ],
    )


def single_raised_pot_state(*, hero_position: str = "big_blind") -> CanonicalState:
    opponent_position = "button" if hero_position == "big_blind" else "big_blind"
    return CanonicalState(
        players_in_hand=2,
        hero_position=hero_position,
        opponent_position=opponent_position,
        street="flop",
        pot_size=5.5,
        current_bet=0,
        effective_stack=97.5,
        preflop_action_history=[
            PreflopAction(actor="button", action="raise", amount=2.5),
            PreflopAction(actor="big_blind", action="call", amount=2.5),
        ],
    )


def isolation_raised_pot_state(
    *,
    hero_position: Position = "big_blind",
    limper_position: Position = "button",
    isolation_raise_size: float = 4.0,
) -> CanonicalState:
    opponent_position = (
        limper_position if hero_position == "big_blind" else "big_blind"
    )
    return CanonicalState(
        players_in_hand=2,
        hero_position=hero_position,
        opponent_position=opponent_position,
        street="flop",
        pot_size=(
            1.5
            - POSTED_BLIND_BB[limper_position]
            - POSTED_BLIND_BB["big_blind"]
            + 2 * isolation_raise_size
        ),
        current_bet=0,
        effective_stack=100.0 - isolation_raise_size,
        preflop_action_history=[
            PreflopAction(
                actor=limper_position,
                action="call",
                amount=1.0,
            ),
            PreflopAction(
                actor="big_blind",
                action="raise",
                amount=isolation_raise_size,
            ),
            PreflopAction(
                actor=limper_position,
                action="call",
                amount=isolation_raise_size,
            ),
        ],
    )


def limp_reraised_pot_state(
    *,
    hero_position: Position = "button",
    limper_position: Position = "utg",
    isolation_raiser_position: Position = "button",
    isolation_raise_size: float = 4.0,
    limp_reraise_size: float = 12.0,
) -> CanonicalState:
    opponent_position = (
        limper_position
        if hero_position == isolation_raiser_position
        else isolation_raiser_position
    )
    return CanonicalState(
        players_in_hand=2,
        hero_position=hero_position,
        opponent_position=opponent_position,
        street="flop",
        pot_size=(
            1.5
            - POSTED_BLIND_BB[limper_position]
            - POSTED_BLIND_BB[isolation_raiser_position]
            + 2 * limp_reraise_size
        ),
        current_bet=0,
        effective_stack=100.0 - limp_reraise_size,
        preflop_action_history=[
            PreflopAction(
                actor=limper_position,
                action="call",
                amount=1.0,
            ),
            PreflopAction(
                actor=isolation_raiser_position,
                action="raise",
                amount=isolation_raise_size,
            ),
            PreflopAction(
                actor=limper_position,
                action="raise",
                amount=limp_reraise_size,
            ),
            PreflopAction(
                actor=isolation_raiser_position,
                action="call",
                amount=limp_reraise_size,
            ),
        ],
    )


def three_bet_pot_state(*, hero_position: str = "button") -> CanonicalState:
    opponent_position = "big_blind" if hero_position == "button" else "button"
    return CanonicalState(
        players_in_hand=2,
        hero_position=hero_position,
        opponent_position=opponent_position,
        street="flop",
        pot_size=16.5,
        current_bet=0,
        effective_stack=92.0,
        preflop_action_history=[
            PreflopAction(actor="button", action="raise", amount=2.5),
            PreflopAction(actor="big_blind", action="raise", amount=8.0),
            PreflopAction(actor="button", action="call", amount=8.0),
        ],
    )


def cold_three_bet_pot_state(
    *,
    hero_position: str = "button",
) -> CanonicalState:
    opponent_position = "cutoff" if hero_position == "button" else "button"
    return CanonicalState(
        players_in_hand=2,
        hero_position=hero_position,
        opponent_position=opponent_position,
        street="flop",
        pot_size=20.0,
        current_bet=0,
        effective_stack=92.0,
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="cutoff", action="raise", amount=8.0),
            PreflopAction(actor="button", action="call", amount=8.0),
        ],
    )


def squeeze_pot_state(*, hero_position: str = "button") -> CanonicalState:
    opponent_position = (
        "small_blind" if hero_position == "button" else "button"
    )
    return CanonicalState(
        players_in_hand=2,
        hero_position=hero_position,
        opponent_position=opponent_position,
        street="flop",
        pot_size=23.5,
        current_bet=0,
        effective_stack=90.0,
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="button", action="call", amount=2.5),
            PreflopAction(
                actor="small_blind",
                action="raise",
                amount=10.0,
            ),
            PreflopAction(actor="button", action="call", amount=10.0),
        ],
    )


def four_bet_pot_state(*, hero_position: str = "button") -> CanonicalState:
    opponent_position = "big_blind" if hero_position == "button" else "button"
    return CanonicalState(
        players_in_hand=2,
        hero_position=hero_position,
        opponent_position=opponent_position,
        street="flop",
        pot_size=40.5,
        current_bet=0,
        effective_stack=80.0,
        preflop_action_history=[
            PreflopAction(actor="button", action="raise", amount=2.5),
            PreflopAction(actor="big_blind", action="raise", amount=8.0),
            PreflopAction(actor="button", action="raise", amount=20.0),
            PreflopAction(actor="big_blind", action="call", amount=20.0),
        ],
    )


def cold_four_bet_pot_state(*, hero_position: str = "button") -> CanonicalState:
    opponent_position = "cutoff" if hero_position == "button" else "button"
    return CanonicalState(
        players_in_hand=2,
        hero_position=hero_position,
        opponent_position=opponent_position,
        street="flop",
        pot_size=44.0,
        current_bet=0,
        effective_stack=80.0,
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="cutoff", action="raise", amount=8.0),
            PreflopAction(actor="button", action="raise", amount=20.0),
            PreflopAction(actor="cutoff", action="call", amount=20.0),
        ],
    )


def select(state: CanonicalState, *, contextual_enabled: bool = True):
    return select_postflop_ranges(
        state,
        hero_relative_position=(
            "oop" if state.hero_position == "big_blind" else "ip"
        ),
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=contextual_enabled,
    )


def test_selects_chart_ranges_for_heads_up_limped_pot() -> None:
    selection = select(limped_pot_state())

    assert selection.source == "preflop_chart_limped_pot"
    assert selection.context == {
        "scenario": "limped_pot",
        "limper_position": "button",
        "big_blind_position": "big_blind",
        "limp_size_bb": 1.0,
        "limper_range_model": "stack_adjusted_first_in_proxy",
        "limp_response_policy": "heads_up_single_limper",
        "stack_depth_policy": "standard",
        "starting_effective_stack_bb": 100.0,
        "stack_depth_source": "reconstructed",
        "limper_base_fraction": 0.45,
        "limper_fraction": 0.45,
        "big_blind_base_raise_fraction": 0.36,
        "big_blind_raise_fraction": 0.36,
    }
    assert "AA" in selection.ip_range.split(",")
    assert "AA" not in selection.oop_range.split(",")
    assert "72o" not in selection.ip_range.split(",")
    assert "72o" in selection.oop_range.split(",")


def test_assigns_limped_ranges_by_relative_position() -> None:
    big_blind_hero = select(limped_pot_state())
    limper_hero = select(
        limped_pot_state(hero_position="button")
    )

    assert limper_hero.ip_range == big_blind_hero.ip_range
    assert limper_hero.oop_range == big_blind_hero.oop_range


@pytest.mark.parametrize(
    "limper_position",
    ("utg", "hijack", "cutoff", "button", "small_blind"),
)
def test_supports_every_charted_heads_up_limped_pot(
    limper_position: str,
) -> None:
    state = limped_pot_state(limper_position=limper_position)
    hero_relative_position = "ip" if limper_position == "small_blind" else "oop"

    selection = select_postflop_ranges(
        state,
        hero_relative_position=hero_relative_position,
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "preflop_chart_limped_pot"


@pytest.mark.parametrize(
    ("hero_position", "opponent_position", "hero_relative_position"),
    (
        ("big_blind", "OOP", "ip"),
        ("OOP", "big_blind", "oop"),
    ),
)
def test_assigns_blind_limp_ranges_with_explicit_relative_label(
    hero_position: str,
    opponent_position: str,
    hero_relative_position: str,
) -> None:
    state = limped_pot_state(limper_position="small_blind")
    state.hero_position = hero_position
    state.opponent_position = opponent_position

    selection = select_postflop_ranges(
        state,
        hero_relative_position=hero_relative_position,
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "preflop_chart_limped_pot"
    assert "AA" in selection.oop_range.split(",")
    assert "AA" not in selection.ip_range.split(",")


@pytest.mark.parametrize(
    ("hero_position", "opponent_position", "hero_relative_position"),
    (
        ("dealer", "big_blind", "ip"),
        ("big_blind", "dealer", "oop"),
    ),
)
def test_assigns_heads_up_dealer_as_small_blind_limper(
    hero_position: str,
    opponent_position: str,
    hero_relative_position: str,
) -> None:
    state = limped_pot_state(limper_position="small_blind")
    state.hero_position = hero_position
    state.opponent_position = opponent_position

    selection = select_postflop_ranges(
        state,
        hero_relative_position=hero_relative_position,
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "preflop_chart_limped_pot"
    assert "AA" in selection.ip_range.split(",")
    assert "AA" not in selection.oop_range.split(",")


def test_rejects_blind_limp_with_contradictory_relative_label() -> None:
    state = limped_pot_state(limper_position="small_blind")
    state.opponent_position = "OOP"

    selection = select_postflop_ranges(
        state,
        hero_relative_position="oop",
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "configured"


def test_rejects_relative_label_that_contradicts_nonblind_limper() -> None:
    state = limped_pot_state(limper_position="button")
    state.opponent_position = "OOP"

    selection = select_postflop_ranges(
        state,
        hero_relative_position="ip",
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "configured"


def test_selects_limped_ranges_on_turn_after_completed_flop() -> None:
    state = limped_pot_state()
    state.street = "turn"
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(actor="oop", action="check"),
                CompletedPostflopAction(actor="ip", action="check"),
            ],
        )
    ]

    selection = select(state)

    assert selection.source == "preflop_chart_limped_pot"
    assert selection.context["decision_street"] == "turn"
    assert selection.context["completed_street_count"] == 1.0


def test_limped_ranges_apply_stack_depth_policy() -> None:
    short = limped_pot_state()
    short.effective_stack = 19.0
    deep = limped_pot_state()
    deep.effective_stack = 200.0

    short_selection = select(short)
    deep_selection = select(deep)

    assert short_selection.context["stack_depth_policy"] == "short"
    assert short_selection.context["limper_fraction"] == 0.405
    assert short_selection.context["big_blind_raise_fraction"] == 0.468
    assert deep_selection.context["stack_depth_policy"] == "deep"
    assert deep_selection.context["limper_fraction"] == 0.4635
    assert deep_selection.context["big_blind_raise_fraction"] == 0.324


def test_keeps_configured_ranges_for_inexact_limped_pot() -> None:
    state = limped_pot_state()
    state.players_in_hand = 3
    assert select(state).source == "configured"

    state = limped_pot_state()
    state.preflop_action_history[0].action = "raise"
    assert select(state).source == "configured"

    state = limped_pot_state()
    state.preflop_action_history[0].amount = 1.5
    assert select(state).source == "configured"

    state = limped_pot_state()
    state.preflop_action_history.append(
        PreflopAction(actor="small_blind", action="call", amount=1.0)
    )
    assert select(state).source == "configured"

    state = limped_pot_state()
    state.opponent_position = "cutoff"
    assert select(state).source == "configured"

    state = limped_pot_state()
    state.preflop_opener_position = "button"
    assert select(state).source == "configured"

    state = limped_pot_state()
    state.preflop_open_size = 2.5
    assert select(state).source == "configured"

    state = limped_pot_state()
    state.pot_size = 4.0
    assert select(state).source == "configured"


def test_selects_chart_ranges_for_heads_up_isolation_raised_pot() -> None:
    selection = select(isolation_raised_pot_state())

    assert selection.source == "preflop_chart_isolation_raised_pot"
    assert selection.context == {
        "scenario": "isolation_raised_pot",
        "limper_position": "button",
        "isolation_raiser_position": "big_blind",
        "limp_size_bb": 1.0,
        "isolation_raise_size_bb": 4.0,
        "limp_response_policy": "heads_up_single_limper",
        "isolation_response_policy": "heads_up_after_hero_limp",
        "isolation_raise_size_policy": "standard",
        "stack_depth_policy": "standard",
        "starting_effective_stack_bb": 100.0,
        "stack_depth_source": "reconstructed",
        "isolation_raiser_base_fraction": 0.36,
        "isolation_raiser_fraction": 0.36,
        "limper_base_continue_fraction": 0.19,
        "limper_base_reraise_fraction": 0.06,
        "limper_continue_fraction": 0.19,
        "limper_reraise_fraction": 0.06,
    }
    assert "AA" in selection.oop_range.split(",")
    assert "AA" not in selection.ip_range.split(",")
    assert selection.ip_range != DEFAULT_POSTFLOP_IP_RANGE
    assert selection.oop_range != DEFAULT_POSTFLOP_OOP_RANGE


def test_assigns_isolation_raised_ranges_by_relative_position() -> None:
    isolation_raiser_hero = select(isolation_raised_pot_state())
    limper_hero = select(
        isolation_raised_pot_state(hero_position="button")
    )

    assert limper_hero.ip_range == isolation_raiser_hero.ip_range
    assert limper_hero.oop_range == isolation_raiser_hero.oop_range


@pytest.mark.parametrize(
    ("hero_position", "opponent_position", "hero_relative_position"),
    (
        ("OOP", "IP", "oop"),
        ("IP", "OOP", "ip"),
    ),
)
def test_assigns_isolation_raised_ranges_from_relative_labels(
    hero_position: str,
    opponent_position: str,
    hero_relative_position: Literal["ip", "oop"],
) -> None:
    state = isolation_raised_pot_state()
    state.hero_position = hero_position
    state.opponent_position = opponent_position

    selection = select_postflop_ranges(
        state,
        hero_relative_position=hero_relative_position,
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "preflop_chart_isolation_raised_pot"
    assert "AA" in selection.oop_range.split(",")
    assert "AA" not in selection.ip_range.split(",")


def test_rejects_isolation_raised_pot_with_duplicate_relative_labels() -> None:
    state = isolation_raised_pot_state()
    state.hero_position = "OOP"
    state.opponent_position = "OOP"

    selection = select_postflop_ranges(
        state,
        hero_relative_position="oop",
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "configured"


@pytest.mark.parametrize(
    ("hero_position", "opponent_position", "hero_relative_position"),
    (
        ("small_blind", "IP", "oop"),
        ("OOP", "big_blind", "oop"),
        ("big_blind", "OOP", "ip"),
        ("IP", "small_blind", "ip"),
    ),
)
def test_assigns_blind_isolation_ranges_from_consistent_mixed_labels(
    hero_position: str,
    opponent_position: str,
    hero_relative_position: Literal["ip", "oop"],
) -> None:
    state = isolation_raised_pot_state(limper_position="small_blind")
    state.hero_position = hero_position
    state.opponent_position = opponent_position

    selection = select_postflop_ranges(
        state,
        hero_relative_position=hero_relative_position,
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "preflop_chart_isolation_raised_pot"


@pytest.mark.parametrize(
    ("hero_position", "opponent_position", "hero_relative_position"),
    (
        ("small_blind", "OOP", "ip"),
        ("IP", "big_blind", "ip"),
        ("big_blind", "IP", "oop"),
        ("OOP", "small_blind", "oop"),
    ),
)
def test_rejects_blind_isolation_ranges_from_contradictory_mixed_labels(
    hero_position: str,
    opponent_position: str,
    hero_relative_position: Literal["ip", "oop"],
) -> None:
    state = isolation_raised_pot_state(limper_position="small_blind")
    state.hero_position = hero_position
    state.opponent_position = opponent_position

    selection = select_postflop_ranges(
        state,
        hero_relative_position=hero_relative_position,
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "configured"


def test_resolves_blind_isolation_raised_pot_relative_position() -> None:
    state = isolation_raised_pot_state(limper_position="small_blind")

    assert resolve_isolation_raised_pot_relative_position(state) == "ip"

    state.hero_position = "small_blind"
    state.opponent_position = "big_blind"
    assert resolve_isolation_raised_pot_relative_position(state) == "oop"

    state.pot_size = 10.0
    assert resolve_isolation_raised_pot_relative_position(state) is None


def test_selects_isolation_raised_ranges_on_turn_after_completed_flop() -> None:
    state = isolation_raised_pot_state()
    state.street = "turn"
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(actor="oop", action="check"),
                CompletedPostflopAction(actor="ip", action="check"),
            ],
        )
    ]

    selection = select(state)

    assert selection.source == "preflop_chart_isolation_raised_pot"
    assert selection.context["decision_street"] == "turn"
    assert selection.context["completed_street_count"] == 1.0


@pytest.mark.parametrize(
    "limper_position",
    tuple(
        sorted(
            limper
            for limper, isolation_raiser in ISOLATION_RESPONSE_POLICIES
            if isolation_raiser == "big_blind"
        )
    ),
)
def test_supports_every_charted_big_blind_isolation_call(
    limper_position: Position,
) -> None:
    state = isolation_raised_pot_state(limper_position=limper_position)
    hero_relative_position = "ip" if limper_position == "small_blind" else "oop"

    selection = select_postflop_ranges(
        state,
        hero_relative_position=hero_relative_position,
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "preflop_chart_isolation_raised_pot"


def test_isolation_raised_ranges_apply_size_and_stack_policies() -> None:
    short = isolation_raised_pot_state()
    short.effective_stack = 16.0
    deep = isolation_raised_pot_state(isolation_raise_size=5.0)
    deep.effective_stack = 195.0

    short_selection = select(short)
    deep_selection = select(deep)

    assert short_selection.context["stack_depth_policy"] == "short"
    assert short_selection.context["isolation_raise_size_policy"] == "standard"
    assert short_selection.context["isolation_raiser_fraction"] == 0.468
    assert short_selection.context["limper_continue_fraction"] == 0.171
    assert short_selection.context["limper_reraise_fraction"] == 0.078
    assert deep_selection.context["stack_depth_policy"] == "deep"
    assert deep_selection.context["isolation_raise_size_policy"] == "large"
    assert deep_selection.context["isolation_raiser_fraction"] == 0.324
    assert deep_selection.context["limper_continue_fraction"] == 0.1756
    assert deep_selection.context["limper_reraise_fraction"] == 0.0497


def test_call_first_isolation_history_ignores_legacy_opener_metadata() -> None:
    state = isolation_raised_pot_state()
    state.preflop_opener_position = "cutoff"
    state.preflop_open_size = 2.5

    assert select(state).source == "preflop_chart_isolation_raised_pot"


def test_keeps_configured_ranges_for_inexact_isolation_raised_pot() -> None:
    state = isolation_raised_pot_state()
    state.players_in_hand = 3
    assert select(state).source == "configured"

    state = isolation_raised_pot_state()
    state.preflop_action_history[0].amount = 1.5
    assert select(state).source == "configured"

    state = isolation_raised_pot_state()
    state.preflop_action_history[1].actor = "small_blind"
    assert select(state).source == "configured"

    state = isolation_raised_pot_state()
    state.preflop_action_history[1].amount = 5.5
    state.preflop_action_history[2].amount = 5.5
    assert select(state).source == "configured"

    state = isolation_raised_pot_state()
    state.preflop_action_history[2].actor = "cutoff"
    assert select(state).source == "configured"

    state = isolation_raised_pot_state()
    state.preflop_action_history[2].amount = 3.5
    assert select(state).source == "configured"

    state = isolation_raised_pot_state()
    state.opponent_position = "cutoff"
    assert select(state).source == "configured"

    state = isolation_raised_pot_state()
    state.pot_size = 10.0
    assert select(state).source == "configured"


def test_selects_chart_ranges_for_heads_up_limp_reraised_pot() -> None:
    selection = select(limp_reraised_pot_state())

    assert selection.source == "preflop_chart_limp_reraised_pot"
    assert selection.context == {
        "scenario": "limp_reraised_pot",
        "limper_position": "utg",
        "isolation_raiser_position": "button",
        "limp_reraiser_position": "utg",
        "limp_size_bb": 1.0,
        "isolation_raise_size_bb": 4.0,
        "limp_reraise_size_bb": 12.0,
        "limp_reraise_to_isolation_ratio": 3.0,
        "isolation_response_policy": "heads_up_after_hero_limp",
        "limp_reraise_response_policy": (
            "heads_up_original_limper_reraise"
        ),
        "isolation_raise_size_policy": "standard",
        "limp_reraise_size_policy": "large",
        "stack_depth_policy": "standard",
        "starting_effective_stack_bb": 100.0,
        "stack_depth_source": "reconstructed",
        "limper_base_reraise_fraction": 0.045,
        "limper_reraise_fraction": 0.045,
        "isolation_raiser_base_continue_fraction": 0.05,
        "isolation_raiser_base_four_bet_fraction": 0.022,
        "isolation_raiser_continue_fraction": 0.045,
        "isolation_raiser_four_bet_fraction": 0.0209,
    }
    assert "AA" in selection.oop_range.split(",")
    assert "AA" not in selection.ip_range.split(",")
    assert selection.oop_range != DEFAULT_POSTFLOP_OOP_RANGE
    assert selection.ip_range != DEFAULT_POSTFLOP_IP_RANGE


@pytest.mark.parametrize(
    ("limper_position", "isolation_raiser_position"),
    tuple(LIMP_RERAISE_RESPONSE_POLICIES),
)
def test_supports_every_charted_called_limp_reraise(
    limper_position: Position,
    isolation_raiser_position: Position,
) -> None:
    state = limp_reraised_pot_state(
        limper_position=limper_position,
        isolation_raiser_position=isolation_raiser_position,
        hero_position=isolation_raiser_position,
    )
    hero_relative_position = resolve_limp_reraised_pot_relative_position(
        state
    )

    assert hero_relative_position is not None
    selection = select_postflop_ranges(
        state,
        hero_relative_position=hero_relative_position,
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )
    assert selection.source == "preflop_chart_limp_reraised_pot"


@pytest.mark.parametrize(
    ("hero_position", "opponent_position", "hero_relative_position"),
    (
        ("IP", "OOP", "ip"),
        ("OOP", "IP", "oop"),
        ("button", "OOP", "ip"),
        ("IP", "utg", "ip"),
    ),
)
def test_assigns_limp_reraised_ranges_from_reviewed_position_labels(
    hero_position: str,
    opponent_position: str,
    hero_relative_position: Literal["ip", "oop"],
) -> None:
    state = limp_reraised_pot_state()
    state.hero_position = hero_position
    state.opponent_position = opponent_position

    selection = select_postflop_ranges(
        state,
        hero_relative_position=hero_relative_position,
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "preflop_chart_limp_reraised_pot"


@pytest.mark.parametrize(
    ("hero_position", "opponent_position", "hero_relative_position"),
    (
        ("button", "IP", "oop"),
        ("OOP", "utg", "oop"),
        ("IP", "IP", "ip"),
    ),
)
def test_rejects_contradictory_limp_reraised_position_labels(
    hero_position: str,
    opponent_position: str,
    hero_relative_position: Literal["ip", "oop"],
) -> None:
    state = limp_reraised_pot_state()
    state.hero_position = hero_position
    state.opponent_position = opponent_position

    selection = select_postflop_ranges(
        state,
        hero_relative_position=hero_relative_position,
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "configured"
    assert resolve_limp_reraised_pot_relative_position(state) is None


def test_resolves_blind_limp_reraised_pot_relative_position() -> None:
    state = limp_reraised_pot_state(
        hero_position="big_blind",
        limper_position="small_blind",
        isolation_raiser_position="big_blind",
    )

    assert resolve_limp_reraised_pot_relative_position(state) == "ip"

    state.hero_position = "small_blind"
    state.opponent_position = "big_blind"
    assert resolve_limp_reraised_pot_relative_position(state) == "oop"

    state.pot_size = 30.0
    assert resolve_limp_reraised_pot_relative_position(state) is None


@pytest.mark.parametrize(
    ("hero_position", "opponent_position", "hero_relative_position"),
    (
        ("dealer", "big_blind", "ip"),
        ("button", "big_blind", "ip"),
        ("big_blind", "dealer", "oop"),
        ("big_blind", "button", "oop"),
    ),
)
def test_assigns_heads_up_dealer_as_small_blind_limp_reraiser(
    hero_position: str,
    opponent_position: str,
    hero_relative_position: Literal["ip", "oop"],
) -> None:
    state = limp_reraised_pot_state(
        hero_position="small_blind",
        limper_position="small_blind",
        isolation_raiser_position="big_blind",
    )
    state.hero_position = hero_position
    state.opponent_position = opponent_position

    assert (
        resolve_limp_reraised_pot_relative_position(state)
        == hero_relative_position
    )
    selection = select_postflop_ranges(
        state,
        hero_relative_position=hero_relative_position,
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "preflop_chart_limp_reraised_pot"
    assert "AA" in selection.ip_range.split(",")
    assert "AA" not in selection.oop_range.split(",")


def test_limp_reraised_ranges_apply_size_and_stack_policies() -> None:
    short = limp_reraised_pot_state(
        isolation_raise_size=3.0,
        limp_reraise_size=8.0,
    )
    short.effective_stack = 12.0
    deep = limp_reraised_pot_state(
        isolation_raise_size=5.0,
        limp_reraise_size=20.0,
    )
    deep.effective_stack = 180.0

    short_selection = select(short)
    deep_selection = select(deep)

    assert short_selection.context["stack_depth_policy"] == "short"
    assert short_selection.context["isolation_raise_size_policy"] == "small"
    assert short_selection.context["limp_reraise_size_policy"] == "standard"
    assert short_selection.context["limper_reraise_fraction"] == 0.0614
    assert short_selection.context["isolation_raiser_continue_fraction"] == 0.045
    assert short_selection.context["isolation_raiser_four_bet_fraction"] == 0.0286
    assert deep_selection.context["stack_depth_policy"] == "deep"
    assert deep_selection.context["isolation_raise_size_policy"] == "large"
    assert deep_selection.context["limp_reraise_size_policy"] == "very_large"
    assert deep_selection.context["limper_reraise_fraction"] == 0.0373
    assert deep_selection.context["isolation_raiser_continue_fraction"] == 0.042
    assert deep_selection.context["isolation_raiser_four_bet_fraction"] == 0.0178


def test_selects_limp_reraised_ranges_after_completed_flop() -> None:
    state = limp_reraised_pot_state()
    state.street = "turn"
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(actor="oop", action="check"),
                CompletedPostflopAction(actor="ip", action="check"),
            ],
        )
    ]

    selection = select(state)

    assert selection.source == "preflop_chart_limp_reraised_pot"
    assert selection.context["decision_street"] == "turn"
    assert selection.context["completed_street_count"] == 1.0


def test_call_first_limp_reraise_history_ignores_legacy_opener_metadata() -> None:
    state = limp_reraised_pot_state()
    state.preflop_opener_position = "cutoff"
    state.preflop_open_size = 2.5

    assert select(state).source == "preflop_chart_limp_reraised_pot"


def test_keeps_configured_ranges_for_inexact_limp_reraised_pot() -> None:
    state = limp_reraised_pot_state()
    state.players_in_hand = 3
    assert select(state).source == "configured"

    state = limp_reraised_pot_state()
    state.preflop_action_history[0].amount = 1.5
    assert select(state).source == "configured"

    state = limp_reraised_pot_state()
    state.preflop_action_history[1].amount = 5.5
    assert select(state).source == "configured"

    state = limp_reraised_pot_state()
    state.preflop_action_history[2].actor = "hijack"
    assert select(state).source == "configured"

    state = limp_reraised_pot_state()
    state.preflop_action_history[2].amount = 6.0
    state.preflop_action_history[3].amount = 6.0
    assert select(state).source == "configured"

    state = limp_reraised_pot_state()
    state.preflop_action_history[2].amount = 17.0
    state.preflop_action_history[3].amount = 17.0
    assert select(state).source == "configured"

    state = limp_reraised_pot_state()
    state.preflop_action_history[3].actor = "cutoff"
    assert select(state).source == "configured"

    state = limp_reraised_pot_state()
    state.preflop_action_history[3].amount = 11.0
    assert select(state).source == "configured"

    state = limp_reraised_pot_state()
    state.opponent_position = "cutoff"
    assert select(state).source == "configured"

    state = limp_reraised_pot_state()
    state.pot_size = 30.0
    assert select(state).source == "configured"


def test_selects_chart_ranges_for_heads_up_single_raised_pot() -> None:
    selection = select(single_raised_pot_state())

    assert selection.source == "preflop_chart_single_raised_pot"
    assert selection.context == {
        "scenario": "single_raised_pot",
        "opener_position": "button",
        "caller_position": "big_blind",
        "opening_size_bb": 2.5,
        "open_size_policy": "standard",
        "stack_depth_policy": "standard",
        "starting_effective_stack_bb": 100.0,
        "stack_depth_source": "reconstructed",
        "opener_base_fraction": 0.45,
        "opener_fraction": 0.45,
        "caller_base_continue_fraction": 0.4,
        "caller_base_reraise_fraction": 0.12,
        "caller_continue_fraction": 0.4,
        "caller_reraise_fraction": 0.12,
    }
    assert "AA" in selection.ip_range.split(",")
    assert "AA" not in selection.oop_range.split(",")
    assert selection.ip_range != DEFAULT_POSTFLOP_IP_RANGE
    assert selection.oop_range != DEFAULT_POSTFLOP_OOP_RANGE


def test_assigns_contextual_ranges_by_relative_position() -> None:
    caller_hero = select(single_raised_pot_state(hero_position="big_blind"))
    opener_hero = select(single_raised_pot_state(hero_position="button"))

    assert opener_hero.ip_range == caller_hero.ip_range
    assert opener_hero.oop_range == caller_hero.oop_range


def test_selects_single_raised_ranges_on_turn_after_completed_flop() -> None:
    state = single_raised_pot_state()
    state.street = "turn"
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(actor="oop", action="check"),
                CompletedPostflopAction(actor="ip", action="check"),
            ],
        )
    ]

    selection = select(state)

    assert selection.source == "preflop_chart_single_raised_pot"
    assert selection.context["starting_effective_stack_bb"] == 100.0
    assert selection.context["stack_depth_source"] == "reconstructed"
    assert selection.context["decision_street"] == "turn"
    assert selection.context["completed_street_count"] == 1.0


def test_reconstructs_turn_range_depth_after_flop_bet_call() -> None:
    state = single_raised_pot_state()
    state.street = "turn"
    state.pot_size = 9.5
    state.hero_stack = 95.5
    state.opponent_stack = 95.5
    state.effective_stack = 95.5
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(
                    actor="oop",
                    action="bet",
                    amount=2.0,
                ),
                CompletedPostflopAction(
                    actor="ip",
                    action="call",
                    amount=2.0,
                ),
            ],
        )
    ]

    selection = select(state)

    assert selection.source == "preflop_chart_single_raised_pot"
    assert selection.context["starting_effective_stack_bb"] == 100.0
    assert selection.context["stack_depth_source"] == "reconstructed"
    assert selection.context["decision_street"] == "turn"
    assert selection.context["completed_street_count"] == 1.0


def test_selects_single_raised_ranges_on_river_after_exact_prior_streets() -> None:
    state = single_raised_pot_state()
    state.street = "river"
    state.pot_size = 11.5
    state.hero_stack = 94.5
    state.opponent_stack = 94.5
    state.effective_stack = 94.5
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(actor="oop", action="check"),
                CompletedPostflopAction(actor="ip", action="check"),
            ],
        ),
        CompletedPostflopStreetHistory(
            street="turn",
            actions=[
                CompletedPostflopAction(
                    actor="oop",
                    action="bet",
                    amount=3.0,
                ),
                CompletedPostflopAction(
                    actor="ip",
                    action="call",
                    amount=3.0,
                ),
            ],
        ),
    ]

    selection = select(state)

    assert selection.source == "preflop_chart_single_raised_pot"
    assert selection.context["starting_effective_stack_bb"] == 100.0
    assert selection.context["stack_depth_source"] == "reconstructed"
    assert selection.context["decision_street"] == "river"
    assert selection.context["completed_street_count"] == 2.0


def test_selects_turn_ranges_while_facing_a_current_street_bet() -> None:
    state = single_raised_pot_state()
    state.street = "turn"
    state.pot_size = 11.5
    state.current_bet = 2.0
    state.facing_action = "bet"
    state.hero_stack = 95.5
    state.opponent_stack = 93.5
    state.effective_stack = 93.5
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(
                    actor="oop",
                    action="bet",
                    amount=2.0,
                ),
                CompletedPostflopAction(
                    actor="ip",
                    action="call",
                    amount=2.0,
                ),
            ],
        )
    ]
    state.postflop_action_history = [
        PostflopAction(actor="oop", action="check"),
        PostflopAction(actor="ip", action="bet", amount=2.0),
    ]

    selection = select(state)

    assert selection.source == "preflop_chart_single_raised_pot"
    assert selection.context["starting_effective_stack_bb"] == 100.0
    assert selection.context["stack_depth_source"] == "reconstructed"


def test_keeps_configured_ranges_for_incomplete_river_history() -> None:
    state = single_raised_pot_state()
    state.street = "river"
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(actor="oop", action="check"),
                CompletedPostflopAction(actor="ip", action="check"),
            ],
        )
    ]

    selection = select(state)

    assert selection.source == "configured"


def test_keeps_configured_ranges_for_contradictory_completed_street_pot() -> None:
    state = single_raised_pot_state()
    state.street = "turn"
    state.pot_size = 10.5
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(
                    actor="oop",
                    action="bet",
                    amount=2.0,
                ),
                CompletedPostflopAction(
                    actor="ip",
                    action="call",
                    amount=2.0,
                ),
            ],
        )
    ]

    selection = select(state)

    assert selection.source == "configured"


def test_selects_chart_ranges_for_heads_up_three_bet_pot() -> None:
    selection = select(three_bet_pot_state())

    assert selection.source == "preflop_chart_three_bet_pot"
    assert selection.context == {
        "scenario": "three_bet_pot",
        "opener_position": "button",
        "three_bettor_position": "big_blind",
        "opening_size_bb": 2.5,
        "three_bet_size_bb": 8.0,
        "open_size_policy": "standard",
        "three_bet_size_policy": "standard",
        "stack_depth_policy": "standard",
        "starting_effective_stack_bb": 100.0,
        "stack_depth_source": "reconstructed",
        "three_bettor_base_fraction": 0.12,
        "three_bettor_fraction": 0.12,
        "opener_base_continue_fraction": 0.18,
        "opener_base_four_bet_fraction": 0.065,
        "opener_continue_fraction": 0.18,
        "opener_four_bet_fraction": 0.065,
    }
    assert "AA" in selection.oop_range.split(",")
    assert "AA" not in selection.ip_range.split(",")
    assert selection.ip_range != DEFAULT_POSTFLOP_IP_RANGE
    assert selection.oop_range != DEFAULT_POSTFLOP_OOP_RANGE


def test_assigns_three_bet_ranges_by_relative_position() -> None:
    opener_hero = select(three_bet_pot_state(hero_position="button"))
    three_bettor_hero = select(
        three_bet_pot_state(hero_position="big_blind")
    )

    assert opener_hero.ip_range == three_bettor_hero.ip_range
    assert opener_hero.oop_range == three_bettor_hero.oop_range


@pytest.mark.parametrize(
    ("opener", "three_bettor"),
    sorted(THREE_BET_DEFENSE_POLICIES),
)
def test_supports_every_charted_three_bet_matchup(
    opener: Position,
    three_bettor: Position,
) -> None:
    final_commitment = 8.0
    state = CanonicalState(
        players_in_hand=2,
        hero_position=opener,
        opponent_position=three_bettor,
        street="flop",
        pot_size=(
            1.5
            - POSTED_BLIND_BB[opener]
            - POSTED_BLIND_BB[three_bettor]
            + 2 * final_commitment
        ),
        current_bet=0,
        preflop_action_history=[
            PreflopAction(actor=opener, action="raise", amount=2.5),
            PreflopAction(
                actor=three_bettor,
                action="raise",
                amount=final_commitment,
            ),
            PreflopAction(
                actor=opener,
                action="call",
                amount=final_commitment,
            ),
        ],
    )

    assert select(state).source == "preflop_chart_three_bet_pot"


def test_selects_chart_ranges_for_heads_up_cold_three_bet_pot() -> None:
    selection = select(cold_three_bet_pot_state())

    assert selection.source == "preflop_chart_cold_three_bet_pot"
    assert selection.context == {
        "scenario": "cold_three_bet_pot",
        "folded_opener_position": "utg",
        "folded_opener_commitment_bb": 2.5,
        "three_bettor_position": "cutoff",
        "cold_caller_position": "button",
        "opening_size_bb": 2.5,
        "three_bet_size_bb": 8.0,
        "open_size_policy": "standard",
        "three_bet_size_policy": "standard",
        "stack_depth_policy": "standard",
        "starting_effective_stack_bb": 100.0,
        "stack_depth_source": "reconstructed",
        "three_bettor_base_fraction": 0.05,
        "three_bettor_fraction": 0.05,
        "cold_caller_base_continue_fraction": 0.05,
        "cold_caller_base_four_bet_fraction": 0.02,
        "cold_caller_continue_fraction": 0.05,
        "cold_caller_four_bet_fraction": 0.02,
        "cold_three_bet_policy": "conservative_three_player",
    }
    assert "AA" in selection.oop_range.split(",")
    assert "AA" not in selection.ip_range.split(",")
    assert selection.ip_range != DEFAULT_POSTFLOP_IP_RANGE
    assert selection.oop_range != DEFAULT_POSTFLOP_OOP_RANGE


def test_assigns_cold_three_bet_ranges_by_relative_position() -> None:
    caller_hero = select(cold_three_bet_pot_state(hero_position="button"))
    three_bettor_hero = select_postflop_ranges(
        cold_three_bet_pot_state(hero_position="cutoff"),
        hero_relative_position="oop",
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert caller_hero.ip_range == three_bettor_hero.ip_range
    assert caller_hero.oop_range == three_bettor_hero.oop_range


@pytest.mark.parametrize(
    ("folded_opener", "three_bettor", "cold_caller"),
    sorted(COLD_THREE_BET_DEFENSE_POLICIES),
)
def test_supports_every_charted_cold_three_bet_matchup(
    folded_opener: Position,
    three_bettor: Position,
    cold_caller: Position,
) -> None:
    opening_size = 2.5
    final_commitment = 8.0
    state = CanonicalState(
        players_in_hand=2,
        hero_position=cold_caller,
        opponent_position=three_bettor,
        street="flop",
        pot_size=(
            1.5
            + opening_size
            - POSTED_BLIND_BB[folded_opener]
            + final_commitment
            - POSTED_BLIND_BB[three_bettor]
            + final_commitment
            - POSTED_BLIND_BB[cold_caller]
        ),
        current_bet=0,
        preflop_action_history=[
            PreflopAction(
                actor=folded_opener,
                action="raise",
                amount=opening_size,
            ),
            PreflopAction(
                actor=three_bettor,
                action="raise",
                amount=final_commitment,
            ),
            PreflopAction(
                actor=cold_caller,
                action="call",
                amount=final_commitment,
            ),
        ],
    )

    assert select(state).source == "preflop_chart_cold_three_bet_pot"


def test_selects_cold_three_bet_ranges_on_turn_after_completed_flop() -> None:
    state = cold_three_bet_pot_state()
    state.street = "turn"
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(actor="oop", action="check"),
                CompletedPostflopAction(actor="ip", action="check"),
            ],
        )
    ]

    selection = select(state)

    assert selection.source == "preflop_chart_cold_three_bet_pot"
    assert selection.context["decision_street"] == "turn"
    assert selection.context["completed_street_count"] == 1.0


def test_keeps_configured_ranges_for_contradictory_cold_three_bet_history() -> None:
    state = cold_three_bet_pot_state()
    state.players_in_hand = 3
    assert select(state).source == "configured"

    state = cold_three_bet_pot_state()
    state.opponent_position = "utg"
    assert select(state).source == "configured"

    state = cold_three_bet_pot_state()
    state.preflop_action_history[2].amount = 7.5
    assert select(state).source == "configured"

    state = cold_three_bet_pot_state()
    state.preflop_action_history[2].actor = "cutoff"
    assert select(state).source == "configured"

    state = cold_three_bet_pot_state()
    state.preflop_action_history[0].actor = "button"
    assert select(state).source == "configured"

    state = cold_three_bet_pot_state()
    state.preflop_action_history[1].amount = 13.0
    state.preflop_action_history[2].amount = 13.0
    state.pot_size = 30.0
    assert select(state).source == "configured"

    state = cold_three_bet_pot_state()
    state.pot_size = 17.5
    assert select(state).source == "configured"

    state = cold_three_bet_pot_state()
    state.preflop_opener_position = "hijack"
    assert select(state).source == "configured"

    state = cold_three_bet_pot_state()
    state.preflop_open_size = 3.0
    assert select(state).source == "configured"


def test_selects_chart_ranges_for_heads_up_squeeze_pot() -> None:
    selection = select(squeeze_pot_state())

    assert selection.source == "preflop_chart_squeeze_pot"
    assert selection.context == {
        "scenario": "squeeze_pot",
        "folded_opener_position": "utg",
        "folded_opener_commitment_bb": 2.5,
        "caller_position": "button",
        "squeezer_position": "small_blind",
        "opening_size_bb": 2.5,
        "squeeze_size_bb": 10.0,
        "open_size_policy": "standard",
        "squeeze_size_policy": "large",
        "caller_adjustment_policy": "single_caller_conservative",
        "stack_depth_policy": "standard",
        "starting_effective_stack_bb": 100.0,
        "stack_depth_source": "reconstructed",
        "squeezer_base_fraction": 0.05,
        "squeezer_fraction": 0.045,
        "caller_base_continue_fraction": 0.045,
        "caller_base_four_bet_fraction": 0.02,
        "caller_continue_fraction": 0.0405,
        "caller_four_bet_fraction": 0.019,
        "squeeze_response_policy": "conservative_heads_up_squeeze",
    }
    assert "AA" in selection.oop_range.split(",")
    assert "AA" not in selection.ip_range.split(",")
    assert selection.ip_range != DEFAULT_POSTFLOP_IP_RANGE
    assert selection.oop_range != DEFAULT_POSTFLOP_OOP_RANGE


def test_assigns_squeeze_ranges_by_relative_position() -> None:
    caller_hero = select(squeeze_pot_state(hero_position="button"))
    squeezer_hero = select_postflop_ranges(
        squeeze_pot_state(hero_position="small_blind"),
        hero_relative_position="oop",
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert caller_hero.ip_range == squeezer_hero.ip_range
    assert caller_hero.oop_range == squeezer_hero.oop_range


@pytest.mark.parametrize(
    ("folded_opener", "caller", "squeezer"),
    sorted(SQUEEZE_DEFENSE_POLICIES),
)
def test_supports_every_charted_squeeze_matchup(
    folded_opener: Position,
    caller: Position,
    squeezer: Position,
) -> None:
    opening_size = 2.5
    final_commitment = 10.0
    state = CanonicalState(
        players_in_hand=2,
        hero_position=caller,
        opponent_position=squeezer,
        street="flop",
        pot_size=(
            1.5
            + opening_size
            - POSTED_BLIND_BB[folded_opener]
            + final_commitment
            - POSTED_BLIND_BB[caller]
            + final_commitment
            - POSTED_BLIND_BB[squeezer]
        ),
        current_bet=0,
        preflop_action_history=[
            PreflopAction(
                actor=folded_opener,
                action="raise",
                amount=opening_size,
            ),
            PreflopAction(
                actor=caller,
                action="call",
                amount=opening_size,
            ),
            PreflopAction(
                actor=squeezer,
                action="raise",
                amount=final_commitment,
            ),
            PreflopAction(
                actor=caller,
                action="call",
                amount=final_commitment,
            ),
        ],
    )

    assert select(state).source == "preflop_chart_squeeze_pot"


def test_resolves_blind_squeeze_survivors_from_reviewed_history() -> None:
    state = CanonicalState(
        players_in_hand=2,
        hero_position="small_blind",
        opponent_position="big_blind",
        street="flop",
        pot_size=22.5,
        current_bet=0,
        preflop_action_history=[
            PreflopAction(actor="button", action="raise", amount=2.5),
            PreflopAction(actor="small_blind", action="call", amount=2.5),
            PreflopAction(actor="big_blind", action="raise", amount=10.0),
            PreflopAction(actor="small_blind", action="call", amount=10.0),
        ],
    )

    assert resolve_squeeze_pot_relative_position(state) == "oop"
    state.hero_position = "big_blind"
    state.opponent_position = "small_blind"
    assert resolve_squeeze_pot_relative_position(state) == "ip"


def test_keeps_blind_pair_ambiguous_without_exact_squeeze_history() -> None:
    state = CanonicalState(
        players_in_hand=2,
        hero_position="small_blind",
        opponent_position="big_blind",
        street="flop",
        pot_size=22.5,
        current_bet=0,
        preflop_action_history=[
            PreflopAction(actor="button", action="raise", amount=2.5),
            PreflopAction(actor="small_blind", action="call", amount=2.5),
            PreflopAction(actor="big_blind", action="raise", amount=10.0),
        ],
    )

    assert resolve_squeeze_pot_relative_position(state) is None


def test_selects_squeeze_ranges_on_turn_after_completed_flop() -> None:
    state = squeeze_pot_state()
    state.street = "turn"
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(actor="oop", action="check"),
                CompletedPostflopAction(actor="ip", action="check"),
            ],
        )
    ]

    selection = select(state)

    assert selection.source == "preflop_chart_squeeze_pot"
    assert selection.context["decision_street"] == "turn"
    assert selection.context["completed_street_count"] == 1.0


def test_keeps_configured_ranges_for_contradictory_squeeze_history() -> None:
    state = squeeze_pot_state()
    state.players_in_hand = 3
    assert select(state).source == "configured"

    state = squeeze_pot_state()
    state.opponent_position = "utg"
    assert select(state).source == "configured"

    state = squeeze_pot_state()
    state.preflop_action_history[1].amount = 3.0
    assert select(state).source == "configured"

    state = squeeze_pot_state()
    state.preflop_action_history[3].amount = 9.5
    assert select(state).source == "configured"

    state = squeeze_pot_state()
    state.preflop_action_history[3].actor = "small_blind"
    assert select(state).source == "configured"

    state = squeeze_pot_state()
    state.preflop_action_history[0].actor = "button"
    assert select(state).source == "configured"

    state = squeeze_pot_state()
    state.preflop_action_history[2].amount = 3.5
    state.preflop_action_history[3].amount = 3.5
    state.pot_size = 10.5
    assert select(state).source == "configured"

    state = squeeze_pot_state()
    state.preflop_action_history[2].amount = 13.0
    state.preflop_action_history[3].amount = 13.0
    state.pot_size = 29.5
    assert select(state).source == "configured"

    state = squeeze_pot_state()
    state.pot_size = 21.0
    assert select(state).source == "configured"

    state = squeeze_pot_state()
    state.preflop_opener_position = "hijack"
    assert select(state).source == "configured"

    state = squeeze_pot_state()
    state.preflop_open_size = 3.0
    assert select(state).source == "configured"


def test_selects_chart_ranges_for_heads_up_four_bet_pot() -> None:
    selection = select(four_bet_pot_state())

    assert selection.source == "preflop_chart_four_bet_pot"
    assert selection.context == {
        "scenario": "four_bet_pot",
        "opener_position": "button",
        "three_bettor_position": "big_blind",
        "opening_size_bb": 2.5,
        "three_bet_size_bb": 8.0,
        "four_bet_size_bb": 20.0,
        "three_bet_size_policy": "standard",
        "four_bet_size_policy": "standard",
        "stack_depth_policy": "standard",
        "starting_effective_stack_bb": 100.0,
        "stack_depth_source": "reconstructed",
        "opener_base_four_bet_fraction": 0.065,
        "opener_four_bet_fraction": 0.065,
        "three_bettor_base_continue_fraction": 0.07,
        "three_bettor_base_five_bet_fraction": 0.038,
        "three_bettor_continue_fraction": 0.07,
        "three_bettor_five_bet_fraction": 0.038,
    }
    assert "AA" in selection.ip_range.split(",")
    assert "AA" not in selection.oop_range.split(",")
    assert selection.ip_range != DEFAULT_POSTFLOP_IP_RANGE
    assert selection.oop_range != DEFAULT_POSTFLOP_OOP_RANGE


def test_assigns_four_bet_ranges_by_relative_position() -> None:
    opener_hero = select(four_bet_pot_state(hero_position="button"))
    three_bettor_hero = select(
        four_bet_pot_state(hero_position="big_blind")
    )

    assert opener_hero.ip_range == three_bettor_hero.ip_range
    assert opener_hero.oop_range == three_bettor_hero.oop_range


def test_selects_chart_ranges_for_heads_up_cold_four_bet_pot() -> None:
    selection = select(cold_four_bet_pot_state())

    assert selection.source == "preflop_chart_cold_four_bet_pot"
    assert selection.context == {
        "scenario": "cold_four_bet_pot",
        "folded_opener_position": "utg",
        "folded_opener_commitment_bb": 2.5,
        "three_bettor_position": "cutoff",
        "cold_four_bettor_position": "button",
        "opening_size_bb": 2.5,
        "three_bet_size_bb": 8.0,
        "four_bet_size_bb": 20.0,
        "three_bet_size_policy": "standard",
        "four_bet_size_policy": "standard",
        "stack_depth_policy": "standard",
        "starting_effective_stack_bb": 100.0,
        "stack_depth_source": "reconstructed",
        "cold_four_bettor_base_four_bet_fraction": 0.02,
        "cold_four_bettor_four_bet_fraction": 0.02,
        "cold_four_bettor_range_policy": "conservative_three_player",
        "three_bettor_base_continue_fraction": 0.027,
        "three_bettor_base_five_bet_fraction": 0.016,
        "three_bettor_continue_fraction": 0.027,
        "three_bettor_five_bet_fraction": 0.016,
        "cold_four_bet_policy": "conservative_heads_up_after_opener_folds",
    }
    assert "AA" in selection.ip_range.split(",")
    assert "AA" not in selection.oop_range.split(",")
    assert selection.ip_range != DEFAULT_POSTFLOP_IP_RANGE
    assert selection.oop_range != DEFAULT_POSTFLOP_OOP_RANGE


def test_selects_cold_four_bet_ranges_on_turn_after_completed_flop() -> None:
    state = cold_four_bet_pot_state()
    state.street = "turn"
    state.completed_postflop_streets = [
        CompletedPostflopStreetHistory(
            street="flop",
            actions=[
                CompletedPostflopAction(actor="oop", action="check"),
                CompletedPostflopAction(actor="ip", action="check"),
            ],
        )
    ]

    selection = select(state)

    assert selection.source == "preflop_chart_cold_four_bet_pot"
    assert selection.context["decision_street"] == "turn"
    assert selection.context["completed_street_count"] == 1.0


def test_resolves_cold_four_bet_blind_pair_from_exact_history() -> None:
    state = CanonicalState(
        players_in_hand=2,
        hero_position="small_blind",
        opponent_position="big_blind",
        street="flop",
        pot_size=42.5,
        current_bet=0,
        effective_stack=80.0,
        preflop_action_history=[
            PreflopAction(actor="button", action="raise", amount=2.5),
            PreflopAction(actor="small_blind", action="raise", amount=8.0),
            PreflopAction(actor="big_blind", action="raise", amount=20.0),
            PreflopAction(actor="small_blind", action="call", amount=20.0),
        ],
    )

    assert resolve_cold_four_bet_pot_relative_position(state) == "oop"
    state.hero_position = "big_blind"
    state.opponent_position = "small_blind"
    assert resolve_cold_four_bet_pot_relative_position(state) == "ip"

    state.preflop_action_history.pop()
    assert resolve_cold_four_bet_pot_relative_position(state) is None


def test_assigns_cold_four_bet_ranges_by_relative_position() -> None:
    cold_four_bettor_hero = select(cold_four_bet_pot_state())
    three_bettor_state = cold_four_bet_pot_state(hero_position="cutoff")
    three_bettor_hero = select_postflop_ranges(
        three_bettor_state,
        hero_relative_position="oop",
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert cold_four_bettor_hero.ip_range == three_bettor_hero.ip_range
    assert cold_four_bettor_hero.oop_range == three_bettor_hero.oop_range


@pytest.mark.parametrize(
    ("folded_opener", "three_bettor", "cold_four_bettor"),
    sorted(COLD_FOUR_BET_DEFENSE_POLICIES),
)
def test_supports_every_charted_cold_four_bet_matchup(
    folded_opener: Position,
    three_bettor: Position,
    cold_four_bettor: Position,
) -> None:
    final_commitment = 20.0
    state = CanonicalState(
        players_in_hand=2,
        hero_position=cold_four_bettor,
        opponent_position=three_bettor,
        street="flop",
        pot_size=(
            1.5
            - POSTED_BLIND_BB[folded_opener]
            - POSTED_BLIND_BB[three_bettor]
            - POSTED_BLIND_BB[cold_four_bettor]
            + 2.5
            + 2 * final_commitment
        ),
        current_bet=0,
        effective_stack=80.0,
        preflop_action_history=[
            PreflopAction(actor=folded_opener, action="raise", amount=2.5),
            PreflopAction(actor=three_bettor, action="raise", amount=8.0),
            PreflopAction(
                actor=cold_four_bettor,
                action="raise",
                amount=final_commitment,
            ),
            PreflopAction(
                actor=three_bettor,
                action="call",
                amount=final_commitment,
            ),
        ],
    )

    selection = select_postflop_ranges(
        state,
        hero_relative_position="ip",
        configured_oop_range=DEFAULT_POSTFLOP_OOP_RANGE,
        configured_ip_range=DEFAULT_POSTFLOP_IP_RANGE,
        contextual_enabled=True,
    )

    assert selection.source == "preflop_chart_cold_four_bet_pot"


@pytest.mark.parametrize(
    ("opener", "three_bettor"),
    sorted(FOUR_BET_DEFENSE_POLICIES),
)
def test_supports_every_charted_four_bet_matchup(
    opener: Position,
    three_bettor: Position,
) -> None:
    final_commitment = 20.0
    state = CanonicalState(
        players_in_hand=2,
        hero_position=opener,
        opponent_position=three_bettor,
        street="flop",
        pot_size=(
            1.5
            - POSTED_BLIND_BB[opener]
            - POSTED_BLIND_BB[three_bettor]
            + 2 * final_commitment
        ),
        current_bet=0,
        preflop_action_history=[
            PreflopAction(actor=opener, action="raise", amount=2.5),
            PreflopAction(actor=three_bettor, action="raise", amount=8.0),
            PreflopAction(
                actor=opener,
                action="raise",
                amount=final_commitment,
            ),
            PreflopAction(
                actor=three_bettor,
                action="call",
                amount=final_commitment,
            ),
        ],
    )

    assert select(state).source == "preflop_chart_four_bet_pot"


def test_keeps_configured_ranges_when_contextual_mode_is_disabled() -> None:
    selection = select(single_raised_pot_state(), contextual_enabled=False)

    assert selection.source == "configured"
    assert selection.context == {}
    assert selection.oop_range == DEFAULT_POSTFLOP_OOP_RANGE
    assert selection.ip_range == DEFAULT_POSTFLOP_IP_RANGE


def test_keeps_configured_ranges_for_incomplete_or_contradictory_history() -> None:
    state = single_raised_pot_state()
    state.preflop_action_history[1].amount = 3.0
    assert select(state).source == "configured"

    state = single_raised_pot_state()
    state.opponent_position = "cutoff"
    assert select(state).source == "configured"

    state = single_raised_pot_state()
    state.players_in_hand = 3
    assert select(state).source == "configured"

    state = single_raised_pot_state()
    state.preflop_open_size = 3.0
    assert select(state).source == "configured"

    state = single_raised_pot_state()
    state.pot_size = 15.0
    assert select(state).source == "configured"

    state = single_raised_pot_state()
    state.pot_size = None
    assert select(state).source == "configured"

    state = single_raised_pot_state()
    state.street = "turn"
    assert select(state).source == "configured"


def test_policy_band_excludes_the_reraise_segment() -> None:
    caller_classes = hand_classes_in_policy_band(0.4, minimum_exclusive=0.12)
    opener_classes = hand_classes_in_policy_band(0.45)

    assert caller_classes
    assert "AA" not in caller_classes
    assert "AA" in opener_classes


def test_open_size_adjusts_the_contextual_caller_band() -> None:
    small_open = single_raised_pot_state()
    small_open.preflop_action_history[0].amount = 2.0
    small_open.preflop_action_history[1].amount = 2.0
    small_open.pot_size = 4.5
    large_open = single_raised_pot_state()
    large_open.preflop_action_history[0].amount = 4.0
    large_open.preflop_action_history[1].amount = 4.0
    large_open.pot_size = 8.5

    small_selection = select(small_open)
    large_selection = select(large_open)

    assert small_selection.context["open_size_policy"] == "small"
    assert small_selection.context["caller_continue_fraction"] == 0.44
    assert small_selection.context["caller_reraise_fraction"] == 0.126
    assert large_selection.context["open_size_policy"] == "very_large"
    assert large_selection.context["caller_continue_fraction"] == 0.312
    assert large_selection.context["caller_reraise_fraction"] == 0.108
    assert len(small_selection.oop_range.split(",")) > len(
        large_selection.oop_range.split(",")
    )


def test_three_bet_size_adjusts_the_opener_call_band() -> None:
    small_three_bet = three_bet_pot_state()
    small_three_bet.preflop_action_history[1].amount = 6.5
    small_three_bet.preflop_action_history[2].amount = 6.5
    small_three_bet.pot_size = 13.5
    large_three_bet = three_bet_pot_state()
    large_three_bet.preflop_action_history[1].amount = 12.0
    large_three_bet.preflop_action_history[2].amount = 12.0
    large_three_bet.pot_size = 24.5

    small_selection = select(small_three_bet)
    large_selection = select(large_three_bet)

    assert small_selection.context["three_bet_size_policy"] == "small"
    assert small_selection.context["opener_continue_fraction"] == 0.189
    assert small_selection.context["opener_four_bet_fraction"] == 0.0683
    assert large_selection.context["three_bet_size_policy"] == "very_large"
    assert large_selection.context["opener_continue_fraction"] == 0.144
    assert large_selection.context["opener_four_bet_fraction"] == 0.0585
    assert len(small_selection.ip_range.split(",")) > len(
        large_selection.ip_range.split(",")
    )


def test_three_bet_size_adjusts_the_cold_caller_band() -> None:
    small_three_bet = cold_three_bet_pot_state()
    small_three_bet.preflop_action_history[1].amount = 6.5
    small_three_bet.preflop_action_history[2].amount = 6.5
    small_three_bet.pot_size = 17.0
    large_three_bet = cold_three_bet_pot_state()
    large_three_bet.preflop_action_history[1].amount = 12.0
    large_three_bet.preflop_action_history[2].amount = 12.0
    large_three_bet.pot_size = 28.0

    small_selection = select(small_three_bet)
    large_selection = select(large_three_bet)

    assert small_selection.context["three_bet_size_policy"] == "small"
    assert small_selection.context["cold_caller_continue_fraction"] == 0.0525
    assert small_selection.context["cold_caller_four_bet_fraction"] == 0.021
    assert large_selection.context["three_bet_size_policy"] == "very_large"
    assert large_selection.context["cold_caller_continue_fraction"] == 0.04
    assert large_selection.context["cold_caller_four_bet_fraction"] == 0.018
    assert len(small_selection.ip_range.split(",")) > len(
        large_selection.ip_range.split(",")
    )


def test_squeeze_size_adjusts_the_caller_band() -> None:
    small_squeeze = squeeze_pot_state()
    small_squeeze.preflop_action_history[2].amount = 6.5
    small_squeeze.preflop_action_history[3].amount = 6.5
    small_squeeze.pot_size = 16.5
    large_squeeze = squeeze_pot_state()
    large_squeeze.preflop_action_history[2].amount = 12.0
    large_squeeze.preflop_action_history[3].amount = 12.0
    large_squeeze.pot_size = 27.5

    small_selection = select(small_squeeze)
    large_selection = select(large_squeeze)

    assert small_selection.context["squeeze_size_policy"] == "small"
    assert small_selection.context["caller_continue_fraction"] == 0.0473
    assert small_selection.context["caller_four_bet_fraction"] == 0.021
    assert large_selection.context["squeeze_size_policy"] == "very_large"
    assert large_selection.context["caller_continue_fraction"] == 0.036
    assert large_selection.context["caller_four_bet_fraction"] == 0.018
    assert len(small_selection.ip_range.split(",")) > len(
        large_selection.ip_range.split(",")
    )


def test_open_size_adjusts_the_squeezer_band() -> None:
    small_open = squeeze_pot_state()
    small_open.preflop_action_history[0].amount = 2.0
    small_open.preflop_action_history[1].amount = 2.0
    small_open.preflop_action_history[2].amount = 6.0
    small_open.preflop_action_history[3].amount = 6.0
    small_open.pot_size = 15.0
    large_open = squeeze_pot_state()
    large_open.preflop_action_history[0].amount = 4.0
    large_open.preflop_action_history[1].amount = 4.0
    large_open.preflop_action_history[2].amount = 12.0
    large_open.preflop_action_history[3].amount = 12.0
    large_open.pot_size = 29.0

    small_selection = select(small_open)
    large_selection = select(large_open)

    assert small_selection.context["open_size_policy"] == "small"
    assert small_selection.context["squeeze_size_policy"] == "standard"
    assert small_selection.context["squeezer_fraction"] == 0.0473
    assert large_selection.context["open_size_policy"] == "very_large"
    assert large_selection.context["squeeze_size_policy"] == "standard"
    assert large_selection.context["squeezer_fraction"] == 0.0405
    assert len(small_selection.oop_range.split(",")) > len(
        large_selection.oop_range.split(",")
    )


def test_short_starting_stack_adjusts_single_raised_pot_ranges() -> None:
    state = single_raised_pot_state()
    state.effective_stack = 17.5

    selection = select(state)

    assert selection.context["stack_depth_policy"] == "short"
    assert selection.context["starting_effective_stack_bb"] == 20.0
    assert selection.context["stack_depth_source"] == "reconstructed"
    assert selection.context["opener_base_fraction"] == 0.45
    assert selection.context["opener_fraction"] == 0.405
    assert selection.context["caller_continue_fraction"] == 0.36
    assert selection.context["caller_reraise_fraction"] == 0.156


def test_deep_starting_stack_adjusts_three_bet_pot_ranges() -> None:
    state = three_bet_pot_state()
    state.effective_stack = 192.0

    selection = select(state)

    assert selection.context["stack_depth_policy"] == "deep"
    assert selection.context["starting_effective_stack_bb"] == 200.0
    assert selection.context["stack_depth_source"] == "reconstructed"
    assert selection.context["three_bettor_fraction"] == 0.108
    assert selection.context["opener_continue_fraction"] == 0.189
    assert selection.context["opener_four_bet_fraction"] == 0.0585


def test_medium_starting_stack_adjusts_four_bet_pot_ranges() -> None:
    state = four_bet_pot_state()
    state.effective_stack = 30.0

    selection = select(state)

    assert selection.context["stack_depth_policy"] == "medium"
    assert selection.context["starting_effective_stack_bb"] == 50.0
    assert selection.context["stack_depth_source"] == "reconstructed"
    assert selection.context["opener_four_bet_fraction"] == 0.0747
    assert selection.context["three_bettor_continue_fraction"] == 0.0665
    assert selection.context["three_bettor_five_bet_fraction"] == 0.0437


def test_medium_starting_stack_adjusts_cold_four_bet_pot_ranges() -> None:
    state = cold_four_bet_pot_state()
    state.effective_stack = 30.0

    selection = select(state)

    assert selection.context["stack_depth_policy"] == "medium"
    assert selection.context["starting_effective_stack_bb"] == 50.0
    assert selection.context["stack_depth_source"] == "reconstructed"
    assert selection.context["cold_four_bettor_four_bet_fraction"] == 0.023
    assert selection.context["three_bettor_continue_fraction"] == 0.0256
    assert selection.context["three_bettor_five_bet_fraction"] == 0.0184


def test_reconstructs_starting_stack_across_current_street_wagers() -> None:
    state = three_bet_pot_state()
    state.pot_size = 18.5
    state.current_bet = 2.0
    state.facing_action = "bet"
    state.hero_stack = 92.0
    state.opponent_stack = 90.0
    state.effective_stack = 90.0
    state.postflop_action_history = [
        PostflopAction(actor="oop", action="bet", amount=2.0)
    ]

    selection = select(state)

    assert selection.context["stack_depth_policy"] == "standard"
    assert selection.context["starting_effective_stack_bb"] == 100.0
    assert selection.context["stack_depth_source"] == "reconstructed"


def test_reconstructs_starting_stack_from_explicit_first_bet() -> None:
    state = three_bet_pot_state()
    state.pot_size = 18.5
    state.current_bet = 2.0
    state.facing_action = "bet"
    state.hero_stack = 92.0
    state.opponent_stack = 90.0
    state.effective_stack = 90.0

    selection = select(state)

    assert selection.context["stack_depth_policy"] == "standard"
    assert selection.context["starting_effective_stack_bb"] == 100.0
    assert selection.context["stack_depth_source"] == "reconstructed"


def test_reconstructs_starting_stack_across_current_street_reraises() -> None:
    state = three_bet_pot_state(hero_position="button")
    state.pot_size = 32.5
    state.current_bet = 4.0
    state.facing_action = "raise"
    state.hero_stack = 86.0
    state.opponent_stack = 82.0
    state.effective_stack = 82.0
    state.postflop_action_history = [
        PostflopAction(actor="oop", action="bet", amount=2.0),
        PostflopAction(actor="ip", action="raise", amount=6.0),
        PostflopAction(actor="oop", action="raise", amount=10.0),
    ]

    selection = select(state)

    assert selection.source == "preflop_chart_three_bet_pot"
    assert selection.context["stack_depth_policy"] == "standard"
    assert selection.context["starting_effective_stack_bb"] == 100.0
    assert selection.context["stack_depth_source"] == "reconstructed"


def test_uses_standard_stack_assumption_when_reconstruction_is_incomplete() -> None:
    state = three_bet_pot_state()
    state.pot_size = 18.5
    state.current_bet = 2.0
    state.facing_action = "bet"
    state.hero_stack = 92.0
    state.opponent_stack = None
    state.effective_stack = 90.0
    state.postflop_action_history = [
        PostflopAction(actor="oop", action="bet", amount=2.0)
    ]

    selection = select(state)

    assert selection.context["stack_depth_policy"] == "standard"
    assert selection.context["starting_effective_stack_bb"] == 100.0
    assert selection.context["stack_depth_source"] == "standard_assumption"


def test_uses_standard_stack_assumption_for_contradictory_visible_stacks() -> None:
    state = single_raised_pot_state()
    state.hero_stack = 97.5
    state.opponent_stack = 95.0
    state.effective_stack = 94.0

    selection = select(state)

    assert selection.context["stack_depth_policy"] == "standard"
    assert selection.context["starting_effective_stack_bb"] == 100.0
    assert selection.context["stack_depth_source"] == "standard_assumption"


def test_keeps_configured_ranges_for_contradictory_three_bet_history() -> None:
    state = three_bet_pot_state()
    state.preflop_action_history[2].amount = 7.5
    assert select(state).source == "configured"

    state = three_bet_pot_state()
    state.pot_size = 30.0
    assert select(state).source == "configured"

    state = three_bet_pot_state()
    state.preflop_action_history[0].actor = "big_blind"
    state.preflop_action_history[2].actor = "big_blind"
    state.preflop_action_history[1].actor = "button"
    assert select(state).source == "configured"

    state = three_bet_pot_state()
    state.preflop_action_history[1].amount = 13.0
    state.preflop_action_history[2].amount = 13.0
    state.pot_size = 26.5
    assert select(state).source == "configured"

    state = three_bet_pot_state()
    state.players_in_hand = 3
    assert select(state).source == "configured"


def test_four_bet_size_adjusts_the_three_bettor_call_band() -> None:
    small_four_bet = four_bet_pot_state()
    small_four_bet.preflop_action_history[2].amount = 16.0
    small_four_bet.preflop_action_history[3].amount = 16.0
    small_four_bet.pot_size = 32.5
    large_four_bet = four_bet_pot_state()
    large_four_bet.preflop_action_history[2].amount = 26.0
    large_four_bet.preflop_action_history[3].amount = 26.0
    large_four_bet.pot_size = 52.5

    small_selection = select(small_four_bet)
    large_selection = select(large_four_bet)

    assert small_selection.context["four_bet_size_policy"] == "small"
    assert small_selection.context["three_bettor_continue_fraction"] == 0.0735
    assert small_selection.context["three_bettor_five_bet_fraction"] == 0.0399
    assert large_selection.context["four_bet_size_policy"] == "very_large"
    assert large_selection.context["three_bettor_continue_fraction"] == 0.056
    assert large_selection.context["three_bettor_five_bet_fraction"] == 0.0342
    assert len(small_selection.oop_range.split(",")) > len(
        large_selection.oop_range.split(",")
    )


def test_cold_four_bet_sizes_adjust_both_players_ranges() -> None:
    small_three_bet = cold_four_bet_pot_state()
    small_three_bet.preflop_action_history[1].amount = 6.5
    small_three_bet.preflop_action_history[2].amount = 16.0
    small_three_bet.preflop_action_history[3].amount = 16.0
    small_three_bet.pot_size = 36.0
    large_three_bet = cold_four_bet_pot_state()
    large_three_bet.preflop_action_history[1].amount = 10.5
    large_three_bet.preflop_action_history[2].amount = 26.0
    large_three_bet.preflop_action_history[3].amount = 26.0
    large_three_bet.pot_size = 56.0

    small_selection = select(small_three_bet)
    large_selection = select(large_three_bet)

    assert small_selection.context["three_bet_size_policy"] == "small"
    assert small_selection.context["cold_four_bettor_four_bet_fraction"] == 0.021
    assert large_selection.context["three_bet_size_policy"] == "large"
    assert large_selection.context["cold_four_bettor_four_bet_fraction"] == 0.019
    assert (
        small_selection.context["cold_four_bettor_four_bet_fraction"]
        > large_selection.context["cold_four_bettor_four_bet_fraction"]
    )

    small_four_bet = cold_four_bet_pot_state()
    small_four_bet.preflop_action_history[2].amount = 16.0
    small_four_bet.preflop_action_history[3].amount = 16.0
    small_four_bet.pot_size = 36.0
    large_four_bet = cold_four_bet_pot_state()
    large_four_bet.preflop_action_history[2].amount = 26.0
    large_four_bet.preflop_action_history[3].amount = 26.0
    large_four_bet.pot_size = 56.0

    small_selection = select(small_four_bet)
    large_selection = select(large_four_bet)

    assert small_selection.context["four_bet_size_policy"] == "small"
    assert small_selection.context["three_bettor_continue_fraction"] == 0.0284
    assert small_selection.context["three_bettor_five_bet_fraction"] == 0.0168
    assert large_selection.context["four_bet_size_policy"] == "very_large"
    assert large_selection.context["three_bettor_continue_fraction"] == 0.0216
    assert large_selection.context["three_bettor_five_bet_fraction"] == 0.0144
    assert (
        small_selection.context["three_bettor_continue_fraction"]
        > large_selection.context["three_bettor_continue_fraction"]
    )


def test_keeps_configured_ranges_for_contradictory_four_bet_history() -> None:
    state = four_bet_pot_state()
    state.preflop_action_history[3].amount = 19.0
    assert select(state).source == "configured"

    state = four_bet_pot_state()
    state.pot_size = 60.0
    assert select(state).source == "configured"

    state = four_bet_pot_state()
    state.preflop_action_history[2].actor = "big_blind"
    assert select(state).source == "configured"

    state = four_bet_pot_state()
    state.preflop_action_history[2].amount = 12.0
    state.preflop_action_history[3].amount = 12.0
    state.pot_size = 24.5
    assert select(state).source == "configured"

    state = four_bet_pot_state()
    state.preflop_action_history[2].amount = 29.0
    state.preflop_action_history[3].amount = 29.0
    state.pot_size = 58.5
    assert select(state).source == "configured"

    state = four_bet_pot_state()
    state.players_in_hand = 3
    assert select(state).source == "configured"


def test_keeps_configured_ranges_for_contradictory_cold_four_bet_history() -> None:
    state = cold_four_bet_pot_state()
    state.preflop_action_history[3].amount = 19.0
    assert select(state).source == "configured"

    state = cold_four_bet_pot_state()
    state.pot_size = 60.0
    assert select(state).source == "configured"

    state = cold_four_bet_pot_state()
    state.preflop_action_history[2].actor = "utg"
    assert select(state).source == "configured"

    state = cold_four_bet_pot_state()
    state.preflop_action_history[1].actor = "button"
    state.preflop_action_history[2].actor = "cutoff"
    state.preflop_action_history[3].actor = "button"
    assert select(state).source == "configured"

    state = cold_four_bet_pot_state()
    state.preflop_action_history[2].amount = 12.0
    state.preflop_action_history[3].amount = 12.0
    state.pot_size = 28.0
    assert select(state).source == "configured"

    state = cold_four_bet_pot_state()
    state.preflop_action_history[2].amount = 29.0
    state.preflop_action_history[3].amount = 29.0
    state.pot_size = 62.0
    assert select(state).source == "configured"

    state = cold_four_bet_pot_state()
    state.players_in_hand = 3
    assert select(state).source == "configured"

    state = cold_four_bet_pot_state()
    state.opponent_position = "utg"
    assert select(state).source == "configured"

    state = cold_four_bet_pot_state()
    state.preflop_opener_position = "hijack"
    assert select(state).source == "configured"

    state = cold_four_bet_pot_state()
    state.preflop_open_size = 3.0
    assert select(state).source == "configured"


def test_reconstructs_flop_root_from_current_street_wagers() -> None:
    isolation_facing_bet = isolation_raised_pot_state()
    isolation_facing_bet.pot_size = 10.5
    isolation_facing_bet.current_bet = 2.0
    isolation_facing_bet.facing_action = "bet"
    assert select(isolation_facing_bet).source == (
        "preflop_chart_isolation_raised_pot"
    )

    limp_reraised_facing_bet = limp_reraised_pot_state()
    limp_reraised_facing_bet.pot_size = 27.5
    limp_reraised_facing_bet.current_bet = 2.0
    limp_reraised_facing_bet.facing_action = "bet"
    assert select(limp_reraised_facing_bet).source == (
        "preflop_chart_limp_reraised_pot"
    )

    facing_bet = single_raised_pot_state()
    facing_bet.pot_size = 7.5
    facing_bet.current_bet = 2.0
    facing_bet.facing_action = "bet"
    assert select(facing_bet).source == "preflop_chart_single_raised_pot"

    facing_raise = single_raised_pot_state()
    facing_raise.pot_size = 14.5
    facing_raise.current_bet = 5.0
    facing_raise.facing_action = "raise"
    facing_raise.postflop_action_history = [
        PostflopAction(actor="oop", action="bet", amount=2.0),
        PostflopAction(actor="ip", action="raise", amount=7.0),
    ]
    assert select(facing_raise).source == "preflop_chart_single_raised_pot"

    three_bet_facing_bet = three_bet_pot_state()
    three_bet_facing_bet.pot_size = 18.5
    three_bet_facing_bet.current_bet = 2.0
    three_bet_facing_bet.facing_action = "bet"
    assert select(three_bet_facing_bet).source == (
        "preflop_chart_three_bet_pot"
    )

    cold_three_bet_facing_bet = cold_three_bet_pot_state()
    cold_three_bet_facing_bet.pot_size = 22.0
    cold_three_bet_facing_bet.current_bet = 2.0
    cold_three_bet_facing_bet.facing_action = "bet"
    assert select(cold_three_bet_facing_bet).source == (
        "preflop_chart_cold_three_bet_pot"
    )

    squeeze_facing_bet = squeeze_pot_state()
    squeeze_facing_bet.pot_size = 25.5
    squeeze_facing_bet.current_bet = 2.0
    squeeze_facing_bet.facing_action = "bet"
    assert select(squeeze_facing_bet).source == (
        "preflop_chart_squeeze_pot"
    )

    four_bet_facing_bet = four_bet_pot_state()
    four_bet_facing_bet.pot_size = 42.5
    four_bet_facing_bet.current_bet = 2.0
    four_bet_facing_bet.facing_action = "bet"
    assert select(four_bet_facing_bet).source == (
        "preflop_chart_four_bet_pot"
    )

    cold_four_bet_facing_bet = cold_four_bet_pot_state()
    cold_four_bet_facing_bet.pot_size = 46.0
    cold_four_bet_facing_bet.current_bet = 2.0
    cold_four_bet_facing_bet.facing_action = "bet"
    assert select(cold_four_bet_facing_bet).source == (
        "preflop_chart_cold_four_bet_pot"
    )
