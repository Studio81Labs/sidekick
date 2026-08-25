from collections.abc import Callable

import pytest

from app.domain.poker import (
    CanonicalState,
    Card,
    FacingAction,
    PreflopAction,
    PreflopPosition,
)
from app.domain.recommendations import RecommendationRequest
from app.solvers.preflop_chart import (
    COLD_FOUR_BET_DEFENSE_POLICIES,
    COLD_FOUR_BET_POLICY_NAME,
    COLD_THREE_BET_DEFENSE_POLICIES,
    COLD_THREE_BET_POLICY_NAME,
    DEFENSE_POLICIES,
    DOUBLE_CALLER_POLICY,
    FIVE_LIMPER_RESPONSE_POLICIES,
    FIVE_LIMPER_RESPONSE_POLICY_NAME,
    FOUR_BET_DEFENSE_POLICIES,
    FOUR_BET_SIZE_POLICIES,
    FOUR_CALLER_POLICY,
    FOUR_LIMPER_RESPONSE_POLICIES,
    FOUR_LIMPER_RESPONSE_POLICY_NAME,
    ISOLATION_RAISE_SIZE_POLICIES,
    ISOLATION_RESPONSE_POLICIES,
    ISOLATION_RESPONSE_POLICY_NAME,
    LIMP_RESPONSE_POLICIES,
    LIMP_RESPONSE_POLICY_NAME,
    LIMP_RERAISE_RESPONSE_POLICIES,
    LIMP_RERAISE_RESPONSE_POLICY_NAME,
    LIMP_RERAISE_SIZE_POLICIES,
    OPEN_SIZE_POLICIES,
    POSITION_POLICIES,
    SINGLE_CALLER_POLICY,
    SQUEEZE_DEFENSE_POLICIES,
    SQUEEZE_RESPONSE_POLICY_NAME,
    STACK_DEPTH_POLICIES,
    THREE_BET_DEFENSE_POLICIES,
    THREE_BET_SIZE_POLICIES,
    THREE_LIMPER_RESPONSE_POLICIES,
    THREE_LIMPER_RESPONSE_POLICY_NAME,
    TWO_LIMPER_RESPONSE_POLICIES,
    TWO_LIMPER_RESPONSE_POLICY_NAME,
    TRIPLE_CALLER_POLICY,
    adjusted_caller_defense_policy,
    adjusted_defense_policy,
    adjusted_four_bet_defense_policy,
    adjusted_limp_raise_fraction,
    adjusted_three_bet_defense_policy,
    canonical_hand_class,
    hand_top_fraction,
    normalize_position,
    policy_for_isolation_raise_size,
    policy_for_limp_reraise_size,
    policy_for_stack_depth,
    solve_preflop_chart,
)
from app.solvers.preflop_context import (
    MAX_SUPPORTED_ISOLATION_RAISE_SIZE_BB,
    MAX_SUPPORTED_LIMP_RERAISE_TO_ISOLATION_RATIO,
    MAX_SINGLE_OPEN_SIZE_BB,
    MIN_SINGLE_OPEN_SIZE_BB,
    POSITION_ACTION_ORDER,
    requires_hero_stack_for_preflop_chart,
    supports_preflop_chart,
)


def request_for(
    cards: tuple[str, str],
    *,
    position: str | None,
    current_bet: float = 0,
    pot_size: float = 1.5,
    hero_stack: float | None = None,
    effective_stack: float = 100,
    players_in_hand: int = 6,
    facing_action: FacingAction | None = None,
    action_context: str | None = None,
    preflop_opener_position: str | None = None,
    preflop_open_size: float | None = None,
    preflop_action_history: list[PreflopAction] | None = None,
) -> RecommendationRequest:
    return RecommendationRequest(
        provider="local_solver",
        state=CanonicalState(
            hero_cards=[Card.from_code(code) for code in cards],
            pot_size=pot_size,
            current_bet=current_bet,
            hero_stack=hero_stack,
            effective_stack=effective_stack,
            players_in_hand=players_in_hand,
            hero_position=position,
            preflop_opener_position=preflop_opener_position,
            preflop_open_size=preflop_open_size,
            preflop_action_history=preflop_action_history or [],
            street="preflop",
            facing_action=facing_action,
            action_context=action_context,
            user_approved=True,
        ),
    )


def structured_heads_up_limp_request(
    cards: tuple[str, str],
    *,
    limper_position: PreflopPosition = "button",
    limp_size: float = 1.0,
    effective_stack: float = 100.0,
    players_in_hand: int = 2,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    pot_size = 1.5 - posted_blinds[limper_position] + limp_size
    return request_for(
        cards,
        position="big_blind",
        current_bet=0,
        pot_size=pot_size,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        preflop_action_history=[
            PreflopAction(
                actor=limper_position,
                action="call",
                amount=limp_size,
            )
        ],
    )


def structured_two_limper_request(
    cards: tuple[str, str],
    *,
    limper_positions: tuple[PreflopPosition, PreflopPosition] = (
        "utg",
        "button",
    ),
    effective_stack: float = 100.0,
    players_in_hand: int = 3,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    pot_size = 1.5 + sum(
        1.0 - posted_blinds[position]
        for position in limper_positions
    )
    return request_for(
        cards,
        position="big_blind",
        current_bet=0,
        pot_size=pot_size,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        preflop_action_history=[
            PreflopAction(actor=position, action="call", amount=1.0)
            for position in limper_positions
        ],
    )


def structured_three_limper_request(
    cards: tuple[str, str],
    *,
    limper_positions: tuple[
        PreflopPosition,
        PreflopPosition,
        PreflopPosition,
    ] = ("utg", "cutoff", "button"),
    effective_stack: float = 100.0,
    players_in_hand: int = 4,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    pot_size = 1.5 + sum(
        1.0 - posted_blinds[position]
        for position in limper_positions
    )
    return request_for(
        cards,
        position="big_blind",
        current_bet=0,
        pot_size=pot_size,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        preflop_action_history=[
            PreflopAction(actor=position, action="call", amount=1.0)
            for position in limper_positions
        ],
    )


def structured_four_limper_request(
    cards: tuple[str, str],
    *,
    limper_positions: tuple[
        PreflopPosition,
        PreflopPosition,
        PreflopPosition,
        PreflopPosition,
    ] = ("utg", "hijack", "cutoff", "button"),
    effective_stack: float = 100.0,
    players_in_hand: int = 5,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    pot_size = 1.5 + sum(
        1.0 - posted_blinds[position]
        for position in limper_positions
    )
    return request_for(
        cards,
        position="big_blind",
        current_bet=0,
        pot_size=pot_size,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        preflop_action_history=[
            PreflopAction(actor=position, action="call", amount=1.0)
            for position in limper_positions
        ],
    )


def structured_five_limper_request(
    cards: tuple[str, str],
    *,
    effective_stack: float = 100.0,
    players_in_hand: int = 6,
) -> RecommendationRequest:
    limper_positions: tuple[
        PreflopPosition,
        PreflopPosition,
        PreflopPosition,
        PreflopPosition,
        PreflopPosition,
    ] = ("utg", "hijack", "cutoff", "button", "small_blind")
    return request_for(
        cards,
        position="big_blind",
        current_bet=0,
        pot_size=6,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        preflop_action_history=[
            PreflopAction(actor=position, action="call", amount=1.0)
            for position in limper_positions
        ],
    )


def structured_isolation_raise_request(
    cards: tuple[str, str],
    *,
    hero_position: PreflopPosition = "utg",
    raiser_position: PreflopPosition = "button",
    isolation_raise_size: float = 4.0,
    hero_stack: float | None = 99.0,
    effective_stack: float = 90.0,
    players_in_hand: int = 2,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    pot_size = (
        1.5
        - posted_blinds[hero_position]
        - posted_blinds[raiser_position]
        + 1.0
        + isolation_raise_size
    )
    return request_for(
        cards,
        position=hero_position,
        current_bet=isolation_raise_size - 1.0,
        pot_size=pot_size,
        hero_stack=hero_stack,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        facing_action="raise",
        action_context="Approved structured action history",
        preflop_action_history=[
            PreflopAction(actor=hero_position, action="call", amount=1.0),
            PreflopAction(
                actor=raiser_position,
                action="raise",
                amount=isolation_raise_size,
            ),
        ],
    )


def structured_limp_reraise_request(
    cards: tuple[str, str],
    *,
    limper_position: PreflopPosition = "utg",
    hero_position: PreflopPosition = "button",
    isolation_raise_size: float = 4.0,
    limp_reraise_size: float = 12.0,
    hero_stack: float | None = 96.0,
    effective_stack: float = 88.0,
    players_in_hand: int = 2,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    pot_size = (
        1.5
        - posted_blinds[limper_position]
        - posted_blinds[hero_position]
        + limp_reraise_size
        + isolation_raise_size
    )
    return request_for(
        cards,
        position=hero_position,
        current_bet=limp_reraise_size - isolation_raise_size,
        pot_size=pot_size,
        hero_stack=hero_stack,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        facing_action="raise",
        action_context="Approved structured action history",
        preflop_action_history=[
            PreflopAction(actor=limper_position, action="call", amount=1.0),
            PreflopAction(
                actor=hero_position,
                action="raise",
                amount=isolation_raise_size,
            ),
            PreflopAction(
                actor=limper_position,
                action="raise",
                amount=limp_reraise_size,
            ),
        ],
    )


def structured_three_bet_request(
    cards: tuple[str, str],
    *,
    hero_position: PreflopPosition = "cutoff",
    three_bettor_position: PreflopPosition = "button",
    opening_size: float = 2.5,
    three_bet_size: float = 8.0,
    hero_stack: float | None = 97.5,
    effective_stack: float = 92.0,
    preflop_opener_position: str | None = None,
    preflop_open_size: float | None = None,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    pot_size = (
        1.5
        - posted_blinds[hero_position]
        - posted_blinds[three_bettor_position]
        + opening_size
        + three_bet_size
    )
    return request_for(
        cards,
        position=hero_position,
        current_bet=three_bet_size - opening_size,
        pot_size=pot_size,
        hero_stack=hero_stack,
        effective_stack=effective_stack,
        facing_action="raise",
        action_context="Ambiguous OCR text is ignored when history is approved",
        preflop_opener_position=preflop_opener_position,
        preflop_open_size=preflop_open_size,
        preflop_action_history=[
            PreflopAction(actor=hero_position, action="raise", amount=opening_size),
            PreflopAction(
                actor=three_bettor_position,
                action="raise",
                amount=three_bet_size,
            ),
        ],
    )


def structured_called_open_request(
    cards: tuple[str, str],
    *,
    opener_position: PreflopPosition = "utg",
    caller_position: PreflopPosition = "hijack",
    hero_position: PreflopPosition = "button",
    opening_size: float = 2.5,
    caller_amount: float | None = None,
    effective_stack: float = 100.0,
    players_in_hand: int = 3,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    resolved_caller_amount = caller_amount or opening_size
    pot_size = (
        1.5
        - posted_blinds[opener_position]
        - posted_blinds[caller_position]
        + opening_size
        + resolved_caller_amount
    )
    return request_for(
        cards,
        position=hero_position,
        current_bet=opening_size - posted_blinds[hero_position],
        pot_size=pot_size,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        facing_action="raise",
        action_context="Structured history is authoritative",
        preflop_opener_position=opener_position,
        preflop_open_size=opening_size,
        preflop_action_history=[
            PreflopAction(
                actor=opener_position,
                action="raise",
                amount=opening_size,
            ),
            PreflopAction(
                actor=caller_position,
                action="call",
                amount=resolved_caller_amount,
            ),
        ],
    )


def structured_double_called_open_request(
    cards: tuple[str, str],
    *,
    opener_position: PreflopPosition = "utg",
    caller_positions: tuple[PreflopPosition, PreflopPosition] = (
        "hijack",
        "cutoff",
    ),
    hero_position: PreflopPosition = "button",
    opening_size: float = 2.5,
    caller_amounts: tuple[float, float] | None = None,
    effective_stack: float = 100.0,
    players_in_hand: int = 4,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    resolved_caller_amounts = caller_amounts or (opening_size, opening_size)
    commitments = (
        (opener_position, opening_size),
        *zip(caller_positions, resolved_caller_amounts, strict=True),
    )
    pot_size = 1.5 + sum(
        amount - posted_blinds[position]
        for position, amount in commitments
    )
    return request_for(
        cards,
        position=hero_position,
        current_bet=opening_size - posted_blinds[hero_position],
        pot_size=pot_size,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        facing_action="raise",
        action_context="Structured history is authoritative",
        preflop_opener_position=opener_position,
        preflop_open_size=opening_size,
        preflop_action_history=[
            PreflopAction(
                actor=opener_position,
                action="raise",
                amount=opening_size,
            ),
            *(
                PreflopAction(actor=position, action="call", amount=amount)
                for position, amount in zip(
                    caller_positions,
                    resolved_caller_amounts,
                    strict=True,
                )
            ),
        ],
    )


def structured_triple_called_open_request(
    cards: tuple[str, str],
    *,
    opener_position: PreflopPosition = "utg",
    caller_positions: tuple[
        PreflopPosition,
        PreflopPosition,
        PreflopPosition,
    ] = ("hijack", "cutoff", "button"),
    hero_position: PreflopPosition = "small_blind",
    opening_size: float = 2.5,
    caller_amounts: tuple[float, float, float] | None = None,
    effective_stack: float = 100.0,
    players_in_hand: int = 5,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    resolved_caller_amounts = caller_amounts or (
        opening_size,
        opening_size,
        opening_size,
    )
    commitments = (
        (opener_position, opening_size),
        *zip(caller_positions, resolved_caller_amounts, strict=True),
    )
    pot_size = 1.5 + sum(
        amount - posted_blinds[position]
        for position, amount in commitments
    )
    return request_for(
        cards,
        position=hero_position,
        current_bet=opening_size - posted_blinds[hero_position],
        pot_size=pot_size,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        facing_action="raise",
        action_context="Structured history is authoritative",
        preflop_opener_position=opener_position,
        preflop_open_size=opening_size,
        preflop_action_history=[
            PreflopAction(
                actor=opener_position,
                action="raise",
                amount=opening_size,
            ),
            *(
                PreflopAction(actor=position, action="call", amount=amount)
                for position, amount in zip(
                    caller_positions,
                    resolved_caller_amounts,
                    strict=True,
                )
            ),
        ],
    )


def structured_four_called_open_request(
    cards: tuple[str, str],
    *,
    opener_position: PreflopPosition = "utg",
    caller_positions: tuple[
        PreflopPosition,
        PreflopPosition,
        PreflopPosition,
        PreflopPosition,
    ] = ("hijack", "cutoff", "button", "small_blind"),
    hero_position: PreflopPosition = "big_blind",
    opening_size: float = 2.5,
    caller_amounts: tuple[float, float, float, float] | None = None,
    effective_stack: float = 100.0,
    players_in_hand: int = 6,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    resolved_caller_amounts = caller_amounts or (
        opening_size,
        opening_size,
        opening_size,
        opening_size,
    )
    commitments = (
        (opener_position, opening_size),
        *zip(caller_positions, resolved_caller_amounts, strict=True),
    )
    pot_size = 1.5 + sum(
        amount - posted_blinds[position]
        for position, amount in commitments
    )
    return request_for(
        cards,
        position=hero_position,
        current_bet=opening_size - posted_blinds[hero_position],
        pot_size=pot_size,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        facing_action="raise",
        action_context="Structured history is authoritative",
        preflop_opener_position=opener_position,
        preflop_open_size=opening_size,
        preflop_action_history=[
            PreflopAction(
                actor=opener_position,
                action="raise",
                amount=opening_size,
            ),
            *(
                PreflopAction(actor=position, action="call", amount=amount)
                for position, amount in zip(
                    caller_positions,
                    resolved_caller_amounts,
                    strict=True,
                )
            ),
        ],
    )


def structured_cold_three_bet_request(
    cards: tuple[str, str],
    *,
    opener_position: PreflopPosition = "utg",
    three_bettor_position: PreflopPosition = "button",
    hero_position: PreflopPosition = "big_blind",
    opening_size: float = 2.5,
    three_bet_size: float = 8.0,
    hero_stack: float | None = 99.0,
    effective_stack: float = 92.0,
    players_in_hand: int = 3,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    pot_size = (
        1.5
        - posted_blinds[opener_position]
        - posted_blinds[three_bettor_position]
        + opening_size
        + three_bet_size
    )
    return request_for(
        cards,
        position=hero_position,
        current_bet=three_bet_size - posted_blinds[hero_position],
        pot_size=pot_size,
        hero_stack=hero_stack,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        facing_action="raise",
        action_context="Structured history is authoritative",
        preflop_opener_position=opener_position,
        preflop_open_size=opening_size,
        preflop_action_history=[
            PreflopAction(
                actor=opener_position,
                action="raise",
                amount=opening_size,
            ),
            PreflopAction(
                actor=three_bettor_position,
                action="raise",
                amount=three_bet_size,
            ),
        ],
    )


def structured_squeeze_response_request(
    cards: tuple[str, str],
    *,
    opener_position: PreflopPosition = "utg",
    hero_position: PreflopPosition = "button",
    squeezer_position: PreflopPosition = "small_blind",
    opening_size: float = 2.5,
    squeeze_size: float = 10.0,
    hero_stack: float | None = 97.5,
    effective_stack: float = 90.0,
    players_in_hand: int = 2,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    commitments = (
        (opener_position, opening_size),
        (hero_position, opening_size),
        (squeezer_position, squeeze_size),
    )
    pot_size = 1.5 + sum(
        amount - posted_blinds[position]
        for position, amount in commitments
    )
    return request_for(
        cards,
        position=hero_position,
        current_bet=squeeze_size - opening_size,
        pot_size=pot_size,
        hero_stack=hero_stack,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        facing_action="raise",
        action_context="Structured history is authoritative",
        preflop_opener_position=opener_position,
        preflop_open_size=opening_size,
        preflop_action_history=[
            PreflopAction(
                actor=opener_position,
                action="raise",
                amount=opening_size,
            ),
            PreflopAction(
                actor=hero_position,
                action="call",
                amount=opening_size,
            ),
            PreflopAction(
                actor=squeezer_position,
                action="raise",
                amount=squeeze_size,
            ),
        ],
    )


def structured_four_bet_request(
    cards: tuple[str, str],
    *,
    opener_position: PreflopPosition = "cutoff",
    hero_position: PreflopPosition = "button",
    opening_size: float = 2.5,
    three_bet_size: float = 8.0,
    four_bet_size: float = 20.0,
    hero_stack: float | None = 92.0,
    effective_stack: float = 80.0,
    players_in_hand: int = 2,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    pot_size = (
        1.5
        - posted_blinds[opener_position]
        - posted_blinds[hero_position]
        + four_bet_size
        + three_bet_size
    )
    return request_for(
        cards,
        position=hero_position,
        current_bet=four_bet_size - three_bet_size,
        pot_size=pot_size,
        hero_stack=hero_stack,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        facing_action="raise",
        action_context="Structured history is authoritative",
        preflop_opener_position=opener_position,
        preflop_open_size=opening_size,
        preflop_action_history=[
            PreflopAction(
                actor=opener_position,
                action="raise",
                amount=opening_size,
            ),
            PreflopAction(
                actor=hero_position,
                action="raise",
                amount=three_bet_size,
            ),
            PreflopAction(
                actor=opener_position,
                action="raise",
                amount=four_bet_size,
            ),
        ],
    )


def structured_cold_four_bet_request(
    cards: tuple[str, str],
    *,
    opener_position: PreflopPosition = "utg",
    hero_position: PreflopPosition = "cutoff",
    four_bettor_position: PreflopPosition = "button",
    opening_size: float = 2.5,
    three_bet_size: float = 8.0,
    four_bet_size: float = 20.0,
    hero_stack: float | None = 92.0,
    effective_stack: float = 80.0,
    players_in_hand: int = 2,
) -> RecommendationRequest:
    posted_blinds = {
        "utg": 0.0,
        "hijack": 0.0,
        "cutoff": 0.0,
        "button": 0.0,
        "small_blind": 0.5,
        "big_blind": 1.0,
    }
    commitments = (
        (opener_position, opening_size),
        (hero_position, three_bet_size),
        (four_bettor_position, four_bet_size),
    )
    pot_size = 1.5 + sum(
        amount - posted_blinds[position]
        for position, amount in commitments
    )
    return request_for(
        cards,
        position=hero_position,
        current_bet=four_bet_size - three_bet_size,
        pot_size=pot_size,
        hero_stack=hero_stack,
        effective_stack=effective_stack,
        players_in_hand=players_in_hand,
        facing_action="raise",
        action_context="Structured history is authoritative",
        preflop_opener_position=opener_position,
        preflop_open_size=opening_size,
        preflop_action_history=[
            PreflopAction(
                actor=opener_position,
                action="raise",
                amount=opening_size,
            ),
            PreflopAction(
                actor=hero_position,
                action="raise",
                amount=three_bet_size,
            ),
            PreflopAction(
                actor=four_bettor_position,
                action="raise",
                amount=four_bet_size,
            ),
        ],
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("UTG", "utg"),
        ("middle-position", "hijack"),
        ("CO", "cutoff"),
        ("dealer", "button"),
        ("small_blind", "small_blind"),
        ("BB", "big_blind"),
        ("IP", None),
    ],
)
def test_normalizes_supported_preflop_positions(value: str, expected: str | None) -> None:
    assert normalize_position(value) == expected


def test_canonical_hand_class_is_order_independent() -> None:
    cards = [Card.from_code("7d"), Card.from_code("Ah")]

    assert canonical_hand_class(cards) == "A7o"
    assert canonical_hand_class(list(reversed(cards))) == "A7o"


def test_chart_ranking_accounts_for_suited_wheel_ace_playability() -> None:
    suited_ace = [Card.from_code("Ah"), Card.from_code("2h")]
    weak_offsuit = [Card.from_code("Kh"), Card.from_code("7d")]

    assert hand_top_fraction(suited_ace) < hand_top_fraction(weak_offsuit)


def test_defense_policies_cover_every_legal_position_matchup() -> None:
    expected_matchups = {
        (opener, hero)
        for opener in POSITION_POLICIES
        for hero in POSITION_POLICIES
        if POSITION_ACTION_ORDER[opener] < POSITION_ACTION_ORDER[hero]
    }

    assert set(DEFENSE_POLICIES) == expected_matchups
    assert all(
        0 < policy.reraise_fraction <= policy.continue_fraction <= 1
        for policy in DEFENSE_POLICIES.values()
    )


def test_three_bet_defense_policies_cover_every_legal_position_matchup() -> None:
    expected_matchups = {
        (hero, three_bettor)
        for hero in POSITION_POLICIES
        for three_bettor in POSITION_POLICIES
        if POSITION_ACTION_ORDER[hero] < POSITION_ACTION_ORDER[three_bettor]
    }

    assert set(THREE_BET_DEFENSE_POLICIES) == expected_matchups
    assert all(
        0 < policy.four_bet_fraction <= policy.continue_fraction <= 1
        for policy in THREE_BET_DEFENSE_POLICIES.values()
    )


def test_cold_three_bet_policies_cover_every_legal_three_seat_order() -> None:
    expected_matchups = {
        (opener, three_bettor, hero)
        for opener in POSITION_POLICIES
        for three_bettor in POSITION_POLICIES
        for hero in POSITION_POLICIES
        if POSITION_ACTION_ORDER[opener]
        < POSITION_ACTION_ORDER[three_bettor]
        < POSITION_ACTION_ORDER[hero]
    }

    assert set(COLD_THREE_BET_DEFENSE_POLICIES) == expected_matchups
    assert all(
        0 < policy.four_bet_fraction <= policy.continue_fraction <= 1
        for policy in COLD_THREE_BET_DEFENSE_POLICIES.values()
    )


def test_cold_three_bet_policies_remain_valid_after_all_adjustments() -> None:
    for policy in COLD_THREE_BET_DEFENSE_POLICIES.values():
        for size_policy in THREE_BET_SIZE_POLICIES:
            for stack_policy in STACK_DEPTH_POLICIES:
                adjusted = adjusted_three_bet_defense_policy(
                    policy,
                    size_policy,
                    stack_policy,
                )
                assert (
                    0
                    < adjusted.four_bet_fraction
                    <= adjusted.continue_fraction
                    <= 1
                )


def test_cold_three_bet_policies_are_tighter_than_opener_defense() -> None:
    for (opener, three_bettor, _), cold_policy in (
        COLD_THREE_BET_DEFENSE_POLICIES.items()
    ):
        opener_policy = THREE_BET_DEFENSE_POLICIES[(opener, three_bettor)]
        assert cold_policy.continue_fraction < opener_policy.continue_fraction
        assert cold_policy.four_bet_fraction <= opener_policy.four_bet_fraction


def test_squeeze_policies_cover_every_legal_three_seat_order() -> None:
    expected_matchups = {
        (opener, hero, squeezer)
        for opener in POSITION_POLICIES
        for hero in POSITION_POLICIES
        for squeezer in POSITION_POLICIES
        if POSITION_ACTION_ORDER[opener]
        < POSITION_ACTION_ORDER[hero]
        < POSITION_ACTION_ORDER[squeezer]
    }

    assert set(SQUEEZE_DEFENSE_POLICIES) == expected_matchups
    assert all(
        0 < policy.four_bet_fraction <= policy.continue_fraction <= 1
        for policy in SQUEEZE_DEFENSE_POLICIES.values()
    )


def test_squeeze_policies_remain_valid_after_all_adjustments() -> None:
    for policy in SQUEEZE_DEFENSE_POLICIES.values():
        for size_policy in THREE_BET_SIZE_POLICIES:
            for stack_policy in STACK_DEPTH_POLICIES:
                adjusted = adjusted_three_bet_defense_policy(
                    policy,
                    size_policy,
                    stack_policy,
                )
                assert (
                    0
                    < adjusted.four_bet_fraction
                    <= adjusted.continue_fraction
                    <= 1
                )


def test_squeeze_policies_are_tighter_than_opener_three_bet_defense() -> None:
    for (opener, _, squeezer), squeeze_policy in (
        SQUEEZE_DEFENSE_POLICIES.items()
    ):
        opener_policy = THREE_BET_DEFENSE_POLICIES[(opener, squeezer)]
        assert squeeze_policy.continue_fraction < opener_policy.continue_fraction
        assert squeeze_policy.four_bet_fraction <= opener_policy.four_bet_fraction


def test_four_bet_defense_policies_cover_every_legal_position_matchup() -> None:
    expected_matchups = {
        (opener, hero)
        for opener in POSITION_POLICIES
        for hero in POSITION_POLICIES
        if POSITION_ACTION_ORDER[opener] < POSITION_ACTION_ORDER[hero]
    }

    assert set(FOUR_BET_DEFENSE_POLICIES) == expected_matchups
    assert all(
        0 < policy.five_bet_fraction <= policy.continue_fraction <= 1
        for policy in FOUR_BET_DEFENSE_POLICIES.values()
    )


def test_four_bet_policies_remain_valid_after_all_adjustments() -> None:
    for policy in FOUR_BET_DEFENSE_POLICIES.values():
        for size_policy in FOUR_BET_SIZE_POLICIES:
            for stack_policy in STACK_DEPTH_POLICIES:
                adjusted = adjusted_four_bet_defense_policy(
                    policy,
                    size_policy,
                    stack_policy,
                )
                assert (
                    0
                    < adjusted.five_bet_fraction
                    <= adjusted.continue_fraction
                    <= 1
                )


def test_cold_four_bet_policies_cover_every_legal_three_seat_order() -> None:
    expected_matchups = {
        (opener, hero, four_bettor)
        for opener in POSITION_POLICIES
        for hero in POSITION_POLICIES
        for four_bettor in POSITION_POLICIES
        if POSITION_ACTION_ORDER[opener]
        < POSITION_ACTION_ORDER[hero]
        < POSITION_ACTION_ORDER[four_bettor]
    }

    assert set(COLD_FOUR_BET_DEFENSE_POLICIES) == expected_matchups
    assert all(
        0 < policy.five_bet_fraction <= policy.continue_fraction <= 1
        for policy in COLD_FOUR_BET_DEFENSE_POLICIES.values()
    )


def test_cold_four_bet_policies_remain_valid_after_all_adjustments() -> None:
    for policy in COLD_FOUR_BET_DEFENSE_POLICIES.values():
        for size_policy in FOUR_BET_SIZE_POLICIES:
            for stack_policy in STACK_DEPTH_POLICIES:
                adjusted = adjusted_four_bet_defense_policy(
                    policy,
                    size_policy,
                    stack_policy,
                )
                assert (
                    0
                    < adjusted.five_bet_fraction
                    <= adjusted.continue_fraction
                    <= 1
                )


def test_cold_four_bet_policies_are_tighter_than_opener_four_bets() -> None:
    for (opener, hero, _), cold_policy in (
        COLD_FOUR_BET_DEFENSE_POLICIES.items()
    ):
        opener_policy = FOUR_BET_DEFENSE_POLICIES[(opener, hero)]
        assert cold_policy.continue_fraction < opener_policy.continue_fraction
        assert cold_policy.five_bet_fraction <= opener_policy.five_bet_fraction


def test_limp_response_policies_cover_every_possible_limper_position() -> None:
    assert set(LIMP_RESPONSE_POLICIES) == set(POSITION_POLICIES) - {"big_blind"}
    assert all(
        0 < policy.raise_fraction <= 1
        for policy in LIMP_RESPONSE_POLICIES.values()
    )


def test_limp_response_range_widens_for_later_limpers() -> None:
    ordered_positions: tuple[PreflopPosition, ...] = (
        "utg",
        "hijack",
        "cutoff",
        "button",
        "small_blind",
    )

    assert [
        LIMP_RESPONSE_POLICIES[position].raise_fraction
        for position in ordered_positions
    ] == sorted(
        LIMP_RESPONSE_POLICIES[position].raise_fraction
        for position in ordered_positions
    )


def test_limp_response_ranges_remain_valid_after_stack_adjustments() -> None:
    for policy in LIMP_RESPONSE_POLICIES.values():
        for stack_policy in STACK_DEPTH_POLICIES:
            adjusted = adjusted_limp_raise_fraction(policy, stack_policy)
            assert 0 < adjusted <= 1


def test_open_size_policies_tighten_as_the_raise_grows() -> None:
    assert MIN_SINGLE_OPEN_SIZE_BB <= OPEN_SIZE_POLICIES[0].maximum_size
    assert OPEN_SIZE_POLICIES[-1].maximum_size == MAX_SINGLE_OPEN_SIZE_BB
    assert [policy.maximum_size for policy in OPEN_SIZE_POLICIES] == sorted(
        policy.maximum_size for policy in OPEN_SIZE_POLICIES
    )
    assert all(
        current.continue_multiplier >= following.continue_multiplier
        and current.reraise_multiplier >= following.reraise_multiplier
        for current, following in zip(OPEN_SIZE_POLICIES, OPEN_SIZE_POLICIES[1:])
    )


def test_single_caller_policy_tightens_existing_defense_boundaries() -> None:
    base = adjusted_defense_policy(
        DEFENSE_POLICIES[("utg", "button")],
        OPEN_SIZE_POLICIES[1],
        STACK_DEPTH_POLICIES[2],
    )

    adjusted = adjusted_caller_defense_policy(base, SINGLE_CALLER_POLICY)

    assert adjusted.continue_fraction < base.continue_fraction
    assert adjusted.reraise_fraction < base.reraise_fraction
    assert 0 < adjusted.reraise_fraction <= adjusted.continue_fraction


def test_caller_policies_tighten_as_more_callers_enter() -> None:
    base = adjusted_defense_policy(
        DEFENSE_POLICIES[("utg", "button")],
        OPEN_SIZE_POLICIES[1],
        STACK_DEPTH_POLICIES[2],
    )

    single_caller = adjusted_caller_defense_policy(base, SINGLE_CALLER_POLICY)
    double_caller = adjusted_caller_defense_policy(base, DOUBLE_CALLER_POLICY)
    triple_caller = adjusted_caller_defense_policy(base, TRIPLE_CALLER_POLICY)
    four_caller = adjusted_caller_defense_policy(base, FOUR_CALLER_POLICY)

    assert (
        0
        < four_caller.reraise_fraction
        < triple_caller.reraise_fraction
        < double_caller.reraise_fraction
        < single_caller.reraise_fraction
    )
    assert (
        four_caller.continue_fraction
        < triple_caller.continue_fraction
        < double_caller.continue_fraction
        < single_caller.continue_fraction
    )
    assert (
        SINGLE_CALLER_POLICY.squeeze_open_multiple
        < DOUBLE_CALLER_POLICY.squeeze_open_multiple
        < TRIPLE_CALLER_POLICY.squeeze_open_multiple
        < FOUR_CALLER_POLICY.squeeze_open_multiple
    )


def test_three_bet_size_policies_tighten_as_the_raise_grows() -> None:
    assert [policy.maximum_ratio for policy in THREE_BET_SIZE_POLICIES] == sorted(
        policy.maximum_ratio for policy in THREE_BET_SIZE_POLICIES
    )


def test_four_bet_size_policies_tighten_as_the_raise_grows() -> None:
    assert [policy.maximum_ratio for policy in FOUR_BET_SIZE_POLICIES] == sorted(
        policy.maximum_ratio for policy in FOUR_BET_SIZE_POLICIES
    )
    assert all(
        current.continue_multiplier >= following.continue_multiplier
        and current.five_bet_multiplier >= following.five_bet_multiplier
        for current, following in zip(
            FOUR_BET_SIZE_POLICIES,
            FOUR_BET_SIZE_POLICIES[1:],
        )
    )
    assert all(
        current.continue_multiplier >= following.continue_multiplier
        and current.four_bet_multiplier >= following.four_bet_multiplier
        for current, following in zip(
            THREE_BET_SIZE_POLICIES,
            THREE_BET_SIZE_POLICIES[1:],
        )
    )


def test_stack_depth_policies_are_ordered_and_keep_reraises_inside_continues() -> None:
    finite_maximums = [
        policy.maximum_stack
        for policy in STACK_DEPTH_POLICIES
        if policy.maximum_stack is not None
    ]

    assert finite_maximums == sorted(finite_maximums)
    assert STACK_DEPTH_POLICIES[-1].maximum_stack is None
    assert all(
        current.open_multiplier <= following.open_multiplier
        and current.continue_multiplier <= following.continue_multiplier
        and current.reraise_multiplier >= following.reraise_multiplier
        and current.opening_size <= following.opening_size
        for current, following in zip(STACK_DEPTH_POLICIES, STACK_DEPTH_POLICIES[1:])
    )
    for base_policy in DEFENSE_POLICIES.values():
        for size_policy in OPEN_SIZE_POLICIES:
            for stack_policy in STACK_DEPTH_POLICIES:
                adjusted = adjusted_defense_policy(
                    base_policy,
                    size_policy,
                    stack_policy,
                )
                assert adjusted.reraise_fraction <= adjusted.continue_fraction
    for base_policy in THREE_BET_DEFENSE_POLICIES.values():
        for size_policy in THREE_BET_SIZE_POLICIES:
            for stack_policy in STACK_DEPTH_POLICIES:
                adjusted = adjusted_three_bet_defense_policy(
                    base_policy,
                    size_policy,
                    stack_policy,
                )
                assert adjusted.four_bet_fraction <= adjusted.continue_fraction


@pytest.mark.parametrize(
    ("effective_stack", "expected_policy"),
    [
        (20.0, "short"),
        (20.01, "medium"),
        (50.0, "medium"),
        (50.01, "standard"),
        (150.0, "standard"),
        (150.01, "deep"),
    ],
)
def test_stack_depth_policy_boundaries(
    effective_stack: float,
    expected_policy: str,
) -> None:
    policy = policy_for_stack_depth(effective_stack)

    assert policy is not None
    assert policy.name == expected_policy


def test_raises_premium_hand_over_heads_up_button_limp() -> None:
    result = solve_preflop_chart(structured_heads_up_limp_request(("Ah", "Ad")))

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 4
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "heads_up_limp_big_blind"
    assert result.raw["chart_tier"] == "isolation_raise"
    assert result.raw["limper_position"] == "button"
    assert result.raw["limp_size"] == 1
    assert result.raw["limp_response_policy"] == LIMP_RESPONSE_POLICY_NAME
    assert result.raw["policy_source"] == "limper_position_stack_matchup"
    assert result.raw["base_limp_raise_fraction"] == 0.36
    assert result.raw["limp_raise_fraction"] == 0.36
    assert result.raw["target_limp_raise_size"] == 4
    assert result.raw["maximum_limp_raise_total"] == 101
    assert [candidate["action"] for candidate in result.raw["candidates"]] == [
        "check",
        "raise",
    ]


def test_checks_weak_hand_over_heads_up_button_limp() -> None:
    result = solve_preflop_chart(structured_heads_up_limp_request(("7h", "2d")))

    assert result is not None
    assert result.action == "check"
    assert result.sizing is None
    assert result.raw["chart_tier"] == "check_option"


def test_limp_response_accounts_for_limper_position() -> None:
    button = solve_preflop_chart(
        structured_heads_up_limp_request(("Jh", "8d"), limper_position="button")
    )
    small_blind = solve_preflop_chart(
        structured_heads_up_limp_request(
            ("Jh", "8d"),
            limper_position="small_blind",
        )
    )

    assert button is not None
    assert small_blind is not None
    assert button.action == "check"
    assert small_blind.action == "raise"
    assert button.raw["limp_raise_fraction"] == 0.36
    assert small_blind.raw["limp_raise_fraction"] == 0.44


@pytest.mark.parametrize("limper_position", tuple(LIMP_RESPONSE_POLICIES))
def test_routes_every_legal_heads_up_limper_position(
    limper_position: PreflopPosition,
) -> None:
    result = solve_preflop_chart(
        structured_heads_up_limp_request(
            ("Ah", "Ad"),
            limper_position=limper_position,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.raw["limper_position"] == limper_position


def test_short_stack_caps_heads_up_limp_raise_at_available_total() -> None:
    result = solve_preflop_chart(
        structured_heads_up_limp_request(("Ah", "Ad"), effective_stack=2)
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 3
    assert result.raw["target_limp_raise_size"] == 4
    assert result.raw["maximum_limp_raise_total"] == 3
    assert result.raw["stack_depth_policy"] == "short"
    assert result.raw["limp_raise_fraction"] == 0.468


def test_heads_up_small_blind_limp_reconstructs_blind_only_pot() -> None:
    request = structured_heads_up_limp_request(
        ("Ah", "Ad"),
        limper_position="small_blind",
    )

    assert request.state.pot_size == 2
    assert supports_preflop_chart(request)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 3),
        lambda state: setattr(state, "hero_position", "button"),
        lambda state: setattr(state, "current_bet", 0.5),
        lambda state: setattr(state, "facing_action", "raise"),
        lambda state: setattr(state, "pot_size", 9),
        lambda state: setattr(state, "preflop_opener_position", "button"),
        lambda state: setattr(state, "preflop_open_size", 2.5),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [PreflopAction(actor="big_blind", action="call", amount=1)],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [PreflopAction(actor="button", action="call", amount=1.5)],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [PreflopAction(actor="button", action="raise", amount=2.5)],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="cutoff", action="call", amount=1),
                PreflopAction(actor="button", action="call", amount=1),
            ],
        ),
    ],
)
def test_declines_inconsistent_heads_up_limp_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_heads_up_limp_request(("Ah", "Ad"))
    mutation(request.state)

    assert not supports_preflop_chart(request)
    assert solve_preflop_chart(request) is None


def test_two_limper_policies_cover_every_legal_ordered_pair() -> None:
    possible_limpers = tuple(
        position
        for position in POSITION_ACTION_ORDER
        if position != "big_blind"
    )
    expected_pairs = {
        (first, second)
        for first in possible_limpers
        for second in possible_limpers
        if POSITION_ACTION_ORDER[first] < POSITION_ACTION_ORDER[second]
    }

    assert set(TWO_LIMPER_RESPONSE_POLICIES) == expected_pairs
    assert all(
        0
        < policy.raise_fraction
        < min(
            LIMP_RESPONSE_POLICIES[first].raise_fraction,
            LIMP_RESPONSE_POLICIES[second].raise_fraction,
        )
        for (first, second), policy in TWO_LIMPER_RESPONSE_POLICIES.items()
    )


def test_two_limper_ranges_remain_valid_after_stack_adjustments() -> None:
    for policy in TWO_LIMPER_RESPONSE_POLICIES.values():
        for stack_policy in STACK_DEPTH_POLICIES:
            adjusted = adjusted_limp_raise_fraction(policy, stack_policy)
            assert 0 < adjusted <= 1


def test_raises_premium_hand_over_two_limpers() -> None:
    result = solve_preflop_chart(structured_two_limper_request(("Ah", "Ad")))

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 5.25
    assert result.raw["scenario"] == "two_limpers_big_blind"
    assert result.raw["chart_tier"] == "isolation_raise"
    assert result.raw["limper_positions"] == ["utg", "button"]
    assert result.raw["limper_count"] == 2
    assert result.raw["limp_size"] == 1
    assert result.raw["multi_limp_response_policy"] == (
        TWO_LIMPER_RESPONSE_POLICY_NAME
    )
    assert result.raw["policy_source"] == "limper_positions_stack_matchup"
    assert result.raw["base_multi_limp_raise_fraction"] == 0.16
    assert result.raw["multi_limp_raise_fraction"] == 0.16
    assert result.raw["target_multi_limp_raise_size"] == 5.25
    assert result.raw["maximum_multi_limp_raise_total"] == 101
    assert "limper_position" not in result.raw
    assert [candidate["action"] for candidate in result.raw["candidates"]] == [
        "check",
        "raise",
    ]


def test_checks_weak_hand_over_two_limpers() -> None:
    result = solve_preflop_chart(structured_two_limper_request(("7h", "2d")))

    assert result is not None
    assert result.action == "check"
    assert result.sizing is None
    assert result.raw["chart_tier"] == "check_option"


def test_two_limper_response_accounts_for_limper_positions() -> None:
    early = solve_preflop_chart(
        structured_two_limper_request(
            ("Kh", "Js"),
            limper_positions=("utg", "hijack"),
        )
    )
    late = solve_preflop_chart(
        structured_two_limper_request(
            ("Kh", "Js"),
            limper_positions=("button", "small_blind"),
        )
    )

    assert early is not None
    assert late is not None
    assert early.action == "check"
    assert late.action == "raise"


def test_two_limper_response_accounts_for_stack_depth() -> None:
    standard = solve_preflop_chart(
        structured_two_limper_request(
            ("Jh", "Th"),
            limper_positions=("utg", "cutoff"),
        )
    )
    short = solve_preflop_chart(
        structured_two_limper_request(
            ("Jh", "Th"),
            limper_positions=("utg", "cutoff"),
            effective_stack=20,
        )
    )

    assert standard is not None
    assert short is not None
    assert standard.action == "check"
    assert short.action == "raise"


@pytest.mark.parametrize(
    ("first_limper", "second_limper"),
    tuple(TWO_LIMPER_RESPONSE_POLICIES),
)
def test_routes_every_legal_two_limper_order(
    first_limper: PreflopPosition,
    second_limper: PreflopPosition,
) -> None:
    result = solve_preflop_chart(
        structured_two_limper_request(
            ("Ah", "Ad"),
            limper_positions=(first_limper, second_limper),
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.raw["limper_positions"] == [first_limper, second_limper]


def test_short_stack_caps_two_limper_raise_at_available_total() -> None:
    result = solve_preflop_chart(
        structured_two_limper_request(("Ah", "Ad"), effective_stack=2)
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 3
    assert result.raw["target_multi_limp_raise_size"] == 5.25
    assert result.raw["maximum_multi_limp_raise_total"] == 3
    assert result.raw["stack_depth_policy"] == "short"
    assert result.raw["multi_limp_raise_fraction"] == 0.208


def test_two_limpers_including_small_blind_reconstruct_pot() -> None:
    request = structured_two_limper_request(
        ("Ah", "Ad"),
        limper_positions=("button", "small_blind"),
    )

    assert request.state.pot_size == 3
    assert supports_preflop_chart(request)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 2),
        lambda state: setattr(state, "hero_position", "button"),
        lambda state: setattr(state, "current_bet", 0.5),
        lambda state: setattr(state, "facing_action", "raise"),
        lambda state: setattr(state, "pot_size", 9),
        lambda state: setattr(state, "preflop_opener_position", "button"),
        lambda state: setattr(state, "preflop_open_size", 2.5),
        lambda state: setattr(state.preflop_action_history[1], "actor", "utg"),
        lambda state: setattr(state.preflop_action_history[0], "actor", "button"),
        lambda state: setattr(state.preflop_action_history[1], "actor", "big_blind"),
        lambda state: setattr(state.preflop_action_history[0], "amount", 1.5),
        lambda state: setattr(state.preflop_action_history[1], "action", "raise"),
        lambda state: state.preflop_action_history.append(
            PreflopAction(actor="small_blind", action="call", amount=1)
        ),
    ],
)
def test_declines_inconsistent_two_limper_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_two_limper_request(("Ah", "Ad"))
    mutation(request.state)

    assert not supports_preflop_chart(request)
    assert solve_preflop_chart(request) is None


def test_three_limper_policies_cover_every_legal_ordered_triple() -> None:
    possible_limpers = tuple(
        position
        for position in POSITION_ACTION_ORDER
        if position != "big_blind"
    )
    expected_triples = {
        (first, second, third)
        for first in possible_limpers
        for second in possible_limpers
        for third in possible_limpers
        if (
            POSITION_ACTION_ORDER[first]
            < POSITION_ACTION_ORDER[second]
            < POSITION_ACTION_ORDER[third]
        )
    }

    assert set(THREE_LIMPER_RESPONSE_POLICIES) == expected_triples
    for positions, policy in THREE_LIMPER_RESPONSE_POLICIES.items():
        pair_policies = (
            TWO_LIMPER_RESPONSE_POLICIES[(positions[0], positions[1])],
            TWO_LIMPER_RESPONSE_POLICIES[(positions[0], positions[2])],
            TWO_LIMPER_RESPONSE_POLICIES[(positions[1], positions[2])],
        )
        assert 0 < policy.raise_fraction < min(
            pair.raise_fraction for pair in pair_policies
        )


def test_three_limper_ranges_remain_valid_after_stack_adjustments() -> None:
    for policy in THREE_LIMPER_RESPONSE_POLICIES.values():
        for stack_policy in STACK_DEPTH_POLICIES:
            adjusted = adjusted_limp_raise_fraction(policy, stack_policy)
            assert 0 < adjusted <= 1


def test_raises_premium_hand_over_three_limpers() -> None:
    result = solve_preflop_chart(
        structured_three_limper_request(("Ah", "Ad"))
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 6.75
    assert result.raw["scenario"] == "three_limpers_big_blind"
    assert result.raw["chart_tier"] == "isolation_raise"
    assert result.raw["limper_positions"] == ["utg", "cutoff", "button"]
    assert result.raw["limper_count"] == 3
    assert result.raw["limp_size"] == 1
    assert result.raw["multi_limp_response_policy"] == (
        THREE_LIMPER_RESPONSE_POLICY_NAME
    )
    assert result.raw["policy_source"] == "limper_positions_stack_matchup"
    assert result.raw["base_multi_limp_raise_fraction"] == 0.12
    assert result.raw["multi_limp_raise_fraction"] == 0.12
    assert result.raw["target_multi_limp_raise_size"] == 6.75
    assert result.raw["maximum_multi_limp_raise_total"] == 101
    assert "limper_position" not in result.raw


def test_checks_weak_hand_over_three_limpers() -> None:
    result = solve_preflop_chart(
        structured_three_limper_request(("7h", "2d"))
    )

    assert result is not None
    assert result.action == "check"
    assert result.sizing is None


def test_three_limper_response_accounts_for_limper_positions() -> None:
    early = solve_preflop_chart(
        structured_three_limper_request(
            ("Kh", "Js"),
            limper_positions=("utg", "hijack", "cutoff"),
        )
    )
    late = solve_preflop_chart(
        structured_three_limper_request(
            ("Kh", "Js"),
            limper_positions=("cutoff", "button", "small_blind"),
        )
    )

    assert early is not None
    assert late is not None
    assert early.action == "check"
    assert late.action == "raise"


def test_three_limper_response_accounts_for_stack_depth() -> None:
    standard = solve_preflop_chart(
        structured_three_limper_request(
            ("Jh", "Th"),
            limper_positions=("cutoff", "button", "small_blind"),
        )
    )
    short = solve_preflop_chart(
        structured_three_limper_request(
            ("Jh", "Th"),
            limper_positions=("cutoff", "button", "small_blind"),
            effective_stack=20,
        )
    )

    assert standard is not None
    assert short is not None
    assert standard.action == "check"
    assert short.action == "raise"


@pytest.mark.parametrize(
    ("first_limper", "second_limper", "third_limper"),
    tuple(THREE_LIMPER_RESPONSE_POLICIES),
)
def test_routes_every_legal_three_limper_order(
    first_limper: PreflopPosition,
    second_limper: PreflopPosition,
    third_limper: PreflopPosition,
) -> None:
    result = solve_preflop_chart(
        structured_three_limper_request(
            ("Ah", "Ad"),
            limper_positions=(
                first_limper,
                second_limper,
                third_limper,
            ),
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.raw["limper_positions"] == [
        first_limper,
        second_limper,
        third_limper,
    ]


def test_short_stack_caps_three_limper_raise_at_available_total() -> None:
    result = solve_preflop_chart(
        structured_three_limper_request(("Ah", "Ad"), effective_stack=2)
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 3
    assert result.raw["target_multi_limp_raise_size"] == 6.75
    assert result.raw["maximum_multi_limp_raise_total"] == 3
    assert result.raw["stack_depth_policy"] == "short"
    assert result.raw["multi_limp_raise_fraction"] == 0.156


def test_three_limpers_including_small_blind_reconstruct_pot() -> None:
    request = structured_three_limper_request(
        ("Ah", "Ad"),
        limper_positions=("utg", "button", "small_blind"),
    )

    assert request.state.pot_size == 4
    assert supports_preflop_chart(request)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 3),
        lambda state: setattr(state, "hero_position", "button"),
        lambda state: setattr(state, "current_bet", 0.5),
        lambda state: setattr(state, "facing_action", "raise"),
        lambda state: setattr(state, "pot_size", 9),
        lambda state: setattr(state, "preflop_opener_position", "button"),
        lambda state: setattr(state, "preflop_open_size", 2.5),
        lambda state: setattr(state.preflop_action_history[2], "actor", "utg"),
        lambda state: setattr(state.preflop_action_history[0], "actor", "button"),
        lambda state: setattr(state.preflop_action_history[2], "actor", "big_blind"),
        lambda state: setattr(state.preflop_action_history[0], "amount", 1.5),
        lambda state: setattr(state.preflop_action_history[2], "action", "raise"),
        lambda state: state.preflop_action_history.append(
            PreflopAction(actor="small_blind", action="call", amount=1)
        ),
    ],
)
def test_declines_inconsistent_three_limper_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_three_limper_request(("Ah", "Ad"))
    mutation(request.state)

    assert not supports_preflop_chart(request)
    assert solve_preflop_chart(request) is None


def test_four_limper_policies_cover_every_legal_ordered_group() -> None:
    possible_limpers = tuple(
        position
        for position in POSITION_ACTION_ORDER
        if position != "big_blind"
    )
    expected_groups = {
        (first, second, third, fourth)
        for first in possible_limpers
        for second in possible_limpers
        for third in possible_limpers
        for fourth in possible_limpers
        if (
            POSITION_ACTION_ORDER[first]
            < POSITION_ACTION_ORDER[second]
            < POSITION_ACTION_ORDER[third]
            < POSITION_ACTION_ORDER[fourth]
        )
    }

    assert set(FOUR_LIMPER_RESPONSE_POLICIES) == expected_groups
    for positions, policy in FOUR_LIMPER_RESPONSE_POLICIES.items():
        triple_policies = (
            THREE_LIMPER_RESPONSE_POLICIES[
                (positions[0], positions[1], positions[2])
            ],
            THREE_LIMPER_RESPONSE_POLICIES[
                (positions[0], positions[1], positions[3])
            ],
            THREE_LIMPER_RESPONSE_POLICIES[
                (positions[0], positions[2], positions[3])
            ],
            THREE_LIMPER_RESPONSE_POLICIES[
                (positions[1], positions[2], positions[3])
            ],
        )
        assert 0 < policy.raise_fraction < min(
            triple.raise_fraction for triple in triple_policies
        )


def test_four_limper_ranges_remain_valid_after_stack_adjustments() -> None:
    for policy in FOUR_LIMPER_RESPONSE_POLICIES.values():
        for stack_policy in STACK_DEPTH_POLICIES:
            adjusted = adjusted_limp_raise_fraction(policy, stack_policy)
            assert 0 < adjusted <= 1


def test_raises_premium_hand_over_four_limpers() -> None:
    result = solve_preflop_chart(
        structured_four_limper_request(("Ah", "Ad"))
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 8.25
    assert result.raw["scenario"] == "four_limpers_big_blind"
    assert result.raw["chart_tier"] == "isolation_raise"
    assert result.raw["limper_positions"] == [
        "utg",
        "hijack",
        "cutoff",
        "button",
    ]
    assert result.raw["limper_count"] == 4
    assert result.raw["limp_size"] == 1
    assert result.raw["multi_limp_response_policy"] == (
        FOUR_LIMPER_RESPONSE_POLICY_NAME
    )
    assert result.raw["policy_source"] == "limper_positions_stack_matchup"
    assert result.raw["base_multi_limp_raise_fraction"] == 0.075
    assert result.raw["multi_limp_raise_fraction"] == 0.075
    assert result.raw["target_multi_limp_raise_size"] == 8.25
    assert result.raw["maximum_multi_limp_raise_total"] == 101
    assert "limper_position" not in result.raw


def test_checks_weak_hand_over_four_limpers() -> None:
    result = solve_preflop_chart(
        structured_four_limper_request(("7h", "2d"))
    )

    assert result is not None
    assert result.action == "check"
    assert result.sizing is None


def test_four_limper_response_accounts_for_limper_positions() -> None:
    early = solve_preflop_chart(
        structured_four_limper_request(
            ("Ah", "Qs"),
            limper_positions=("utg", "hijack", "cutoff", "button"),
        )
    )
    late = solve_preflop_chart(
        structured_four_limper_request(
            ("Ah", "Qs"),
            limper_positions=("hijack", "cutoff", "button", "small_blind"),
        )
    )

    assert early is not None
    assert late is not None
    assert early.action == "check"
    assert late.action == "raise"


def test_four_limper_response_accounts_for_stack_depth() -> None:
    standard = solve_preflop_chart(
        structured_four_limper_request(
            ("Ah", "Td"),
            limper_positions=("hijack", "cutoff", "button", "small_blind"),
        )
    )
    short = solve_preflop_chart(
        structured_four_limper_request(
            ("Ah", "Td"),
            limper_positions=("hijack", "cutoff", "button", "small_blind"),
            effective_stack=20,
        )
    )

    assert standard is not None
    assert short is not None
    assert standard.action == "check"
    assert short.action == "raise"


@pytest.mark.parametrize(
    ("first_limper", "second_limper", "third_limper", "fourth_limper"),
    tuple(FOUR_LIMPER_RESPONSE_POLICIES),
)
def test_routes_every_legal_four_limper_order(
    first_limper: PreflopPosition,
    second_limper: PreflopPosition,
    third_limper: PreflopPosition,
    fourth_limper: PreflopPosition,
) -> None:
    result = solve_preflop_chart(
        structured_four_limper_request(
            ("Ah", "Ad"),
            limper_positions=(
                first_limper,
                second_limper,
                third_limper,
                fourth_limper,
            ),
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.raw["limper_positions"] == [
        first_limper,
        second_limper,
        third_limper,
        fourth_limper,
    ]


def test_short_stack_caps_four_limper_raise_at_available_total() -> None:
    result = solve_preflop_chart(
        structured_four_limper_request(("Ah", "Ad"), effective_stack=2)
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 3
    assert result.raw["target_multi_limp_raise_size"] == 8.25
    assert result.raw["maximum_multi_limp_raise_total"] == 3
    assert result.raw["stack_depth_policy"] == "short"
    assert result.raw["multi_limp_raise_fraction"] == 0.0975


def test_four_limpers_including_small_blind_reconstruct_pot() -> None:
    request = structured_four_limper_request(
        ("Ah", "Ad"),
        limper_positions=("utg", "hijack", "button", "small_blind"),
    )

    assert request.state.pot_size == 5
    assert supports_preflop_chart(request)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 4),
        lambda state: setattr(state, "players_in_hand", 6),
        lambda state: setattr(state, "hero_position", "button"),
        lambda state: setattr(state, "current_bet", 0.5),
        lambda state: setattr(state, "facing_action", "raise"),
        lambda state: setattr(state, "pot_size", 9),
        lambda state: setattr(state, "preflop_opener_position", "button"),
        lambda state: setattr(state, "preflop_open_size", 2.5),
        lambda state: setattr(state.preflop_action_history[3], "actor", "utg"),
        lambda state: setattr(state.preflop_action_history[0], "actor", "button"),
        lambda state: setattr(state.preflop_action_history[3], "actor", "big_blind"),
        lambda state: setattr(state.preflop_action_history[0], "amount", 1.5),
        lambda state: setattr(state.preflop_action_history[3], "action", "raise"),
        lambda state: state.preflop_action_history.append(
            PreflopAction(actor="small_blind", action="call", amount=1)
        ),
    ],
)
def test_declines_inconsistent_four_limper_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_four_limper_request(("Ah", "Ad"))
    mutation(request.state)

    assert not supports_preflop_chart(request)
    assert solve_preflop_chart(request) is None


def test_five_limper_policy_covers_full_table_and_tightens_every_subset() -> None:
    expected_positions: tuple[
        PreflopPosition,
        PreflopPosition,
        PreflopPosition,
        PreflopPosition,
        PreflopPosition,
    ] = ("utg", "hijack", "cutoff", "button", "small_blind")

    assert set(FIVE_LIMPER_RESPONSE_POLICIES) == {expected_positions}
    policy = FIVE_LIMPER_RESPONSE_POLICIES[expected_positions]
    four_limper_policies = (
        FOUR_LIMPER_RESPONSE_POLICIES[expected_positions[:4]],
        FOUR_LIMPER_RESPONSE_POLICIES[
            (
                expected_positions[0],
                expected_positions[1],
                expected_positions[2],
                expected_positions[4],
            )
        ],
        FOUR_LIMPER_RESPONSE_POLICIES[
            (
                expected_positions[0],
                expected_positions[1],
                expected_positions[3],
                expected_positions[4],
            )
        ],
        FOUR_LIMPER_RESPONSE_POLICIES[
            (
                expected_positions[0],
                expected_positions[2],
                expected_positions[3],
                expected_positions[4],
            )
        ],
        FOUR_LIMPER_RESPONSE_POLICIES[expected_positions[1:]],
    )
    assert 0 < policy.raise_fraction < min(
        subset.raise_fraction for subset in four_limper_policies
    )


def test_five_limper_range_remains_valid_after_stack_adjustments() -> None:
    policy = next(iter(FIVE_LIMPER_RESPONSE_POLICIES.values()))

    for stack_policy in STACK_DEPTH_POLICIES:
        adjusted = adjusted_limp_raise_fraction(policy, stack_policy)
        assert 0 < adjusted <= 1


def test_raises_premium_hand_over_five_limpers() -> None:
    result = solve_preflop_chart(
        structured_five_limper_request(("Ah", "Ad"))
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 9
    assert result.raw["scenario"] == "five_limpers_big_blind"
    assert result.raw["chart_tier"] == "isolation_raise"
    assert result.raw["limper_positions"] == [
        "utg",
        "hijack",
        "cutoff",
        "button",
        "small_blind",
    ]
    assert result.raw["limper_count"] == 5
    assert result.raw["limp_size"] == 1
    assert result.raw["multi_limp_response_policy"] == (
        FIVE_LIMPER_RESPONSE_POLICY_NAME
    )
    assert result.raw["policy_source"] == "limper_positions_stack_matchup"
    assert result.raw["base_multi_limp_raise_fraction"] == 0.06
    assert result.raw["multi_limp_raise_fraction"] == 0.06
    assert result.raw["target_multi_limp_raise_size"] == 9
    assert result.raw["maximum_multi_limp_raise_total"] == 101
    assert "limper_position" not in result.raw


def test_checks_weak_hand_over_five_limpers() -> None:
    result = solve_preflop_chart(
        structured_five_limper_request(("7h", "2d"))
    )

    assert result is not None
    assert result.action == "check"
    assert result.sizing is None


def test_five_limper_response_accounts_for_stack_depth() -> None:
    standard = solve_preflop_chart(
        structured_five_limper_request(("7h", "7d"))
    )
    short = solve_preflop_chart(
        structured_five_limper_request(
            ("7h", "7d"),
            effective_stack=20,
        )
    )

    assert standard is not None
    assert short is not None
    assert standard.action == "check"
    assert short.action == "raise"


def test_short_stack_caps_five_limper_raise_at_available_total() -> None:
    result = solve_preflop_chart(
        structured_five_limper_request(("Ah", "Ad"), effective_stack=2)
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 3
    assert result.raw["target_multi_limp_raise_size"] == 9
    assert result.raw["maximum_multi_limp_raise_total"] == 3
    assert result.raw["stack_depth_policy"] == "short"
    assert result.raw["multi_limp_raise_fraction"] == 0.078


def test_five_limpers_reconstruct_full_table_pot() -> None:
    request = structured_five_limper_request(("Ah", "Ad"))

    assert request.state.pot_size == 6
    assert supports_preflop_chart(request)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 5),
        lambda state: setattr(state, "players_in_hand", 7),
        lambda state: setattr(state, "hero_position", "button"),
        lambda state: setattr(state, "current_bet", 0.5),
        lambda state: setattr(state, "facing_action", "raise"),
        lambda state: setattr(state, "pot_size", 9),
        lambda state: setattr(state, "preflop_opener_position", "button"),
        lambda state: setattr(state, "preflop_open_size", 2.5),
        lambda state: setattr(state.preflop_action_history[4], "actor", "utg"),
        lambda state: state.preflop_action_history.reverse(),
        lambda state: setattr(state.preflop_action_history[4], "actor", "big_blind"),
        lambda state: setattr(state.preflop_action_history[0], "amount", 1.5),
        lambda state: setattr(state.preflop_action_history[4], "action", "raise"),
        lambda state: state.preflop_action_history.append(
            PreflopAction(actor="big_blind", action="call", amount=1)
        ),
    ],
)
def test_declines_inconsistent_five_limper_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_five_limper_request(("Ah", "Ad"))
    mutation(request.state)

    assert not supports_preflop_chart(request)
    assert solve_preflop_chart(request) is None


def test_opens_premium_hand_from_early_position() -> None:
    result = solve_preflop_chart(request_for(("Ah", "Ad"), position="UTG"))

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 2.5
    assert result.raw["engine"] == "preflop_chart_v1"
    assert result.raw["scenario"] == "first_in"
    assert result.raw["chart_tier"] == "open"


@pytest.mark.parametrize(
    ("effective_stack", "expected_action", "expected_policy", "expected_fraction"),
    [
        (20, "fold", "short", 0.405),
        (100, "raise", "standard", 0.45),
    ],
)
def test_first_in_range_accounts_for_stack_depth(
    effective_stack: float,
    expected_action: str,
    expected_policy: str,
    expected_fraction: float,
) -> None:
    result = solve_preflop_chart(
        request_for(
            ("9h", "8d"),
            position="button",
            effective_stack=effective_stack,
        )
    )

    assert result is not None
    assert result.action == expected_action
    assert result.raw["policy_source"] == "hero_position_stack"
    assert result.raw["stack_depth_policy"] == expected_policy
    assert result.raw["base_open_fraction"] == 0.45
    assert result.raw["open_fraction"] == expected_fraction


def test_short_stack_uses_smaller_first_in_open_size() -> None:
    result = solve_preflop_chart(
        request_for(
            ("Ah", "Ad"),
            position="button",
            effective_stack=20,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 2.2
    assert result.raw["target_open_size"] == 2.2


def test_folds_weak_unopened_button_hand() -> None:
    result = solve_preflop_chart(request_for(("7h", "2d"), position="button"))

    assert result is not None
    assert result.action == "fold"
    assert result.sizing is None


@pytest.mark.parametrize(
    "action_context",
    [
        "Cutoff raises; hero has 2.5 BB to call",
        "Cutoff opens to 2.5 BB",
        "Cutoff opened to 2.5 BB",
        "Cutoff open raises to 2.5 BB",
    ],
)
def test_defends_medium_button_hand_against_assumed_open_raise(
    action_context: str,
) -> None:
    result = solve_preflop_chart(
        request_for(
            ("Ah", "Jd"),
            position="button",
            current_bet=2.5,
            pot_size=4,
            facing_action="raise",
            action_context=action_context,
        )
    )

    assert result is not None
    assert result.action == "call"
    assert result.raw["scenario"] == "facing_open_raise"
    assert result.raw["policy_source"] == "hero_opener_size_stack_matchup"
    assert any("matchup-specific" in value for value in result.raw["assumptions"])


@pytest.mark.parametrize(
    ("opener_position", "expected_action", "expected_continue_fraction"),
    [
        ("utg", "fold", 0.20),
        ("button", "call", 0.40),
    ],
)
def test_big_blind_continue_range_accounts_for_opener_position(
    opener_position: str,
    expected_action: str,
    expected_continue_fraction: float,
) -> None:
    result = solve_preflop_chart(
        request_for(
            ("Ah", "9d"),
            position="big blind",
            current_bet=1.5,
            pot_size=4,
            facing_action="raise",
            action_context="Hero faces 1.5 BB to call",
            preflop_opener_position=opener_position,
            preflop_open_size=2.5,
        )
    )

    assert result is not None
    assert result.action == expected_action
    assert result.raw["continue_fraction"] == expected_continue_fraction
    assert result.raw["opener_position"] == opener_position


@pytest.mark.parametrize(
    ("opener_position", "expected_action", "expected_reraise_fraction"),
    [
        ("utg", "call", 0.06),
        ("button", "raise", 0.12),
    ],
)
def test_big_blind_reraise_range_accounts_for_opener_position(
    opener_position: str,
    expected_action: str,
    expected_reraise_fraction: float,
) -> None:
    result = solve_preflop_chart(
        request_for(
            ("Ah", "Qd"),
            position="big blind",
            current_bet=1.5,
            pot_size=4,
            facing_action="raise",
            action_context="Hero faces 1.5 BB to call",
            preflop_opener_position=opener_position,
            preflop_open_size=2.5,
        )
    )

    assert result is not None
    assert result.action == expected_action
    assert result.raw["reraise_fraction"] == expected_reraise_fraction
    assert result.raw["base_opener_open_fraction"] == (
        0.17 if opener_position == "utg" else 0.45
    )
    assert result.raw["opener_open_fraction"] == (
        0.17 if opener_position == "utg" else 0.45
    )


@pytest.mark.parametrize(
    (
        "opening_size",
        "amount_to_call",
        "pot_size",
        "expected_action",
        "expected_policy",
        "expected_continue_fraction",
    ),
    [
        (2.0, 1.0, 3.5, "call", "small", 0.44),
        (4.0, 3.0, 5.5, "fold", "very_large", 0.312),
    ],
)
def test_big_blind_continue_range_accounts_for_opening_size(
    opening_size: float,
    amount_to_call: float,
    pot_size: float,
    expected_action: str,
    expected_policy: str,
    expected_continue_fraction: float,
) -> None:
    result = solve_preflop_chart(
        request_for(
            ("7h", "6h"),
            position="big blind",
            current_bet=amount_to_call,
            pot_size=pot_size,
            facing_action="raise",
            action_context="Hero faces a button open",
            preflop_opener_position="button",
            preflop_open_size=opening_size,
        )
    )

    assert result is not None
    assert result.action == expected_action
    assert result.raw["open_size_policy"] == expected_policy
    assert result.raw["base_continue_fraction"] == 0.40
    assert result.raw["continue_fraction"] == expected_continue_fraction


@pytest.mark.parametrize(
    ("opening_size", "amount_to_call", "pot_size", "expected_action", "expected_fraction"),
    [
        (2.0, 1.0, 3.5, "raise", 0.126),
        (4.0, 3.0, 5.5, "call", 0.108),
    ],
)
def test_big_blind_reraise_range_accounts_for_opening_size(
    opening_size: float,
    amount_to_call: float,
    pot_size: float,
    expected_action: str,
    expected_fraction: float,
) -> None:
    result = solve_preflop_chart(
        request_for(
            ("Ah", "Jd"),
            position="big blind",
            current_bet=amount_to_call,
            pot_size=pot_size,
            facing_action="raise",
            action_context="Hero faces a button open",
            preflop_opener_position="button",
            preflop_open_size=opening_size,
        )
    )

    assert result is not None
    assert result.action == expected_action
    assert result.raw["base_reraise_fraction"] == 0.12
    assert result.raw["reraise_fraction"] == expected_fraction


@pytest.mark.parametrize(
    ("effective_stack", "expected_action", "expected_policy", "expected_fraction"),
    [
        (20, "fold", "short", 0.36),
        (100, "call", "standard", 0.40),
    ],
)
def test_big_blind_continue_range_accounts_for_stack_depth(
    effective_stack: float,
    expected_action: str,
    expected_policy: str,
    expected_fraction: float,
) -> None:
    result = solve_preflop_chart(
        request_for(
            ("7h", "6h"),
            position="big blind",
            current_bet=1.5,
            pot_size=4,
            effective_stack=effective_stack,
            facing_action="raise",
            preflop_opener_position="button",
            preflop_open_size=2.5,
        )
    )

    assert result is not None
    assert result.action == expected_action
    assert result.raw["stack_depth_policy"] == expected_policy
    assert result.raw["continue_fraction"] == expected_fraction
    assert result.raw["base_opener_open_fraction"] == 0.45
    assert result.raw["opener_open_fraction"] == (0.405 if effective_stack == 20 else 0.45)


@pytest.mark.parametrize(
    ("effective_stack", "expected_action", "expected_policy", "expected_fraction"),
    [
        (20, "raise", "short", 0.156),
        (100, "call", "standard", 0.12),
    ],
)
def test_big_blind_reraise_range_accounts_for_stack_depth(
    effective_stack: float,
    expected_action: str,
    expected_policy: str,
    expected_fraction: float,
) -> None:
    result = solve_preflop_chart(
        request_for(
            ("Ah", "Jd"),
            position="big blind",
            current_bet=1.5,
            pot_size=4,
            effective_stack=effective_stack,
            facing_action="raise",
            preflop_opener_position="button",
            preflop_open_size=2.5,
        )
    )

    assert result is not None
    assert result.action == expected_action
    assert result.raw["stack_depth_policy"] == expected_policy
    assert result.raw["reraise_fraction"] == expected_fraction


@pytest.mark.parametrize(
    ("effective_stack", "expected_action", "expected_sizing"),
    [
        (1.4, "call", None),
        (1.6, "raise", 2.6),
        (2.6, "raise", 3.6),
    ],
)
def test_short_stack_reraise_requires_a_total_above_the_open(
    effective_stack: float,
    expected_action: str,
    expected_sizing: float | None,
) -> None:
    result = solve_preflop_chart(
        request_for(
            ("Ah", "Jd"),
            position="big blind",
            current_bet=1.5,
            pot_size=4,
            effective_stack=effective_stack,
            facing_action="raise",
            preflop_opener_position="button",
            preflop_open_size=2.5,
        )
    )

    assert result is not None
    assert result.action == expected_action
    assert result.sizing == expected_sizing


def test_reraise_uses_opponent_total_when_hero_covers() -> None:
    result = solve_preflop_chart(
        request_for(
            ("Ah", "Jd"),
            position="big blind",
            current_bet=1.5,
            pot_size=4,
            hero_stack=10,
            effective_stack=1,
            facing_action="raise",
            preflop_opener_position="button",
            preflop_open_size=2.5,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 3.5
    assert result.raw["maximum_reraise_total"] == 3.5


def test_reraises_premium_hand_and_caps_size_to_effective_total() -> None:
    result = solve_preflop_chart(
        request_for(
            ("Kh", "Ks"),
            position="big blind",
            current_bet=2,
            pot_size=4.5,
            effective_stack=6,
            facing_action="raise",
            action_context="Button raises to 3 BB",
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 7
    assert result.raw["maximum_reraise_total"] == 7
    assert result.raw["chart_tier"] == "reraise"


@pytest.mark.parametrize(
    "action_context",
    [
        "Button opens to 2.5 BB",
        "Button raises; hero has 1.5 BB to call",
    ],
)
def test_sizes_blind_reraise_from_total_open(action_context: str) -> None:
    result = solve_preflop_chart(
        request_for(
            ("Kh", "Ks"),
            position="big blind",
            current_bet=1.5,
            pot_size=4,
            facing_action="raise",
            action_context=action_context,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 7.5


def test_supports_big_blind_defense_against_small_blind_open() -> None:
    result = solve_preflop_chart(
        request_for(
            ("Kh", "Ks"),
            position="big blind",
            current_bet=2,
            pot_size=4,
            facing_action="raise",
            action_context="Small blind opens to 3 BB",
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 9


def test_prefers_structured_preflop_opener_context() -> None:
    result = solve_preflop_chart(
        request_for(
            ("Kh", "Ks"),
            position="big blind",
            current_bet=1.5,
            pot_size=4,
            facing_action="raise",
            action_context="Hero faces 1.5 BB to call into a 4 BB pot",
            preflop_opener_position="button",
            preflop_open_size=2.5,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 7.5
    assert result.raw["opener_position"] == "button"
    assert result.raw["opening_raise_size"] == 2.5


def test_structured_single_open_takes_precedence_over_ambiguous_text() -> None:
    result = solve_preflop_chart(
        request_for(
            ("Ah", "Jd"),
            position="button",
            current_bet=2.5,
            pot_size=4,
            facing_action="raise",
            action_context="OCR could not identify the action",
            preflop_action_history=[
                PreflopAction(actor="cutoff", action="raise", amount=2.5)
            ],
        )
    )

    assert result is not None
    assert result.action == "call"
    assert result.raw["scenario"] == "facing_open_raise"
    assert result.raw["opener_position"] == "cutoff"


@pytest.mark.parametrize(
    ("cards", "expected_action", "expected_tier"),
    [
        (("Ah", "Ad"), "raise", "four_bet"),
        (("8h", "8s"), "call", "continue"),
        (("7h", "2d"), "fold", "fold"),
    ],
)
def test_structured_three_bet_history_routes_position_aware_response(
    cards: tuple[str, str],
    expected_action: str,
    expected_tier: str,
) -> None:
    result = solve_preflop_chart(structured_three_bet_request(cards))

    assert result is not None
    assert result.action == expected_action
    assert result.raw["scenario"] == "facing_three_bet"
    assert result.raw["chart_tier"] == expected_tier
    assert result.raw["opener_position"] == "cutoff"
    assert result.raw["three_bettor_position"] == "button"
    assert result.raw["opening_raise_size"] == 2.5
    assert result.raw["three_bet_size"] == 8
    assert result.raw["three_bet_to_open_ratio"] == 3.2


@pytest.mark.parametrize(
    ("cards", "expected_action", "expected_tier"),
    [
        (("Ah", "Ad"), "raise", "four_bet"),
        (("Th", "Ts"), "call", "continue"),
        (("7h", "2d"), "fold", "fold"),
    ],
)
def test_cold_three_bet_history_routes_conservative_response(
    cards: tuple[str, str],
    expected_action: str,
    expected_tier: str,
) -> None:
    result = solve_preflop_chart(structured_cold_three_bet_request(cards))

    assert result is not None
    assert result.action == expected_action
    assert result.raw["scenario"] == "facing_cold_three_bet"
    assert result.raw["chart_tier"] == expected_tier
    assert result.raw["opener_position"] == "utg"
    assert result.raw["three_bettor_position"] == "button"
    assert result.raw["opening_raise_size"] == 2.5
    assert result.raw["three_bet_size"] == 8
    assert result.raw["three_bet_to_open_ratio"] == 3.2
    assert result.raw["cold_three_bet_policy"] == COLD_THREE_BET_POLICY_NAME
    assert result.raw["policy_source"] == (
        "hero_opener_three_bettor_size_stack_matchup"
    )


def test_cold_four_bet_cap_uses_only_hero_posted_blind() -> None:
    result = solve_preflop_chart(
        structured_cold_three_bet_request(
            ("Ah", "Ad"),
            hero_stack=10,
            effective_stack=10,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 11
    assert result.raw["maximum_four_bet_total"] == 11


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 4),
        lambda state: setattr(state, "current_bet", 5.5),
        lambda state: setattr(state, "pot_size", 11),
        lambda state: setattr(state, "hero_stack", None),
        lambda state: setattr(state, "hero_stack", 6),
        lambda state: setattr(state, "effective_stack", 100),
        lambda state: setattr(state, "preflop_opener_position", "hijack"),
        lambda state: setattr(state, "preflop_open_size", 3),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="button", action="raise", amount=2.5),
                PreflopAction(actor="utg", action="raise", amount=8),
            ],
        ),
    ],
)
def test_declines_inconsistent_cold_three_bet_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_cold_three_bet_request(("Ah", "Ad"))
    mutation(request.state)

    assert solve_preflop_chart(request) is None


@pytest.mark.parametrize(
    ("cards", "expected_action", "expected_tier"),
    [
        (("Ah", "Ad"), "raise", "four_bet"),
        (("Th", "Ts"), "call", "continue"),
        (("7h", "2d"), "fold", "fold"),
    ],
)
def test_squeeze_response_history_routes_conservative_response(
    cards: tuple[str, str],
    expected_action: str,
    expected_tier: str,
) -> None:
    result = solve_preflop_chart(structured_squeeze_response_request(cards))

    assert result is not None
    assert result.action == expected_action
    assert result.raw["scenario"] == "facing_squeeze_after_call"
    assert result.raw["chart_tier"] == expected_tier
    assert result.raw["opener_position"] == "utg"
    assert result.raw["three_bettor_position"] == "small_blind"
    assert result.raw["opening_raise_size"] == 2.5
    assert result.raw["hero_prior_commitment"] == 2.5
    assert result.raw["three_bet_size"] == 10
    assert result.raw["three_bet_to_open_ratio"] == 4
    assert result.raw["squeeze_response_policy"] == (
        SQUEEZE_RESPONSE_POLICY_NAME
    )
    assert result.raw["policy_source"] == (
        "hero_opener_squeezer_size_stack_matchup"
    )


@pytest.mark.parametrize(
    ("opener_position", "hero_position", "squeezer_position"),
    tuple(SQUEEZE_DEFENSE_POLICIES),
)
def test_squeeze_response_routes_every_legal_position_order(
    opener_position: PreflopPosition,
    hero_position: PreflopPosition,
    squeezer_position: PreflopPosition,
) -> None:
    result = solve_preflop_chart(
        structured_squeeze_response_request(
            ("Ah", "Ad"),
            opener_position=opener_position,
            hero_position=hero_position,
            squeezer_position=squeezer_position,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.raw["opener_position"] == opener_position
    assert result.raw["position"] == hero_position
    assert result.raw["three_bettor_position"] == squeezer_position


def test_squeeze_response_reconstructs_blind_commitments() -> None:
    result = solve_preflop_chart(
        structured_squeeze_response_request(
            ("Ah", "Ad"),
            opener_position="cutoff",
            hero_position="small_blind",
            squeezer_position="big_blind",
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.raw["maximum_four_bet_total"] == 100


def test_squeeze_response_raise_cap_includes_hero_prior_call() -> None:
    result = solve_preflop_chart(
        structured_squeeze_response_request(
            ("Ah", "Ad"),
            hero_stack=10,
            effective_stack=10,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 12.5
    assert result.raw["maximum_four_bet_total"] == 12.5


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 3),
        lambda state: setattr(state, "current_bet", 7),
        lambda state: setattr(state, "pot_size", 13.5),
        lambda state: setattr(state, "hero_stack", None),
        lambda state: setattr(state, "hero_stack", 7),
        lambda state: setattr(state, "effective_stack", 98),
        lambda state: setattr(state, "preflop_opener_position", "hijack"),
        lambda state: setattr(state, "preflop_open_size", 3),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="cutoff", action="call", amount=2.5),
                PreflopAction(actor="small_blind", action="raise", amount=10),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="button", action="call", amount=2),
                PreflopAction(actor="small_blind", action="raise", amount=10),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="button", action="call", amount=2.5),
                PreflopAction(actor="cutoff", action="raise", amount=10),
            ],
        ),
    ],
)
def test_declines_inconsistent_squeeze_response_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_squeeze_response_request(("Ah", "Ad"))
    mutation(request.state)

    assert solve_preflop_chart(request) is None


@pytest.mark.parametrize("squeeze_size", [3.5, 13])
def test_declines_unsupported_squeeze_size(squeeze_size: float) -> None:
    request = structured_squeeze_response_request(
        ("Ah", "Ad"),
        squeeze_size=squeeze_size,
    )

    assert not supports_preflop_chart(request)
    assert solve_preflop_chart(request) is None


def test_declines_three_bet_larger_than_supported_size_band() -> None:
    request = structured_three_bet_request(
        ("Ah", "Ad"),
        three_bet_size=13,
    )

    assert not supports_preflop_chart(request)
    assert solve_preflop_chart(request) is None


def test_oversized_three_bet_does_not_require_chart_specific_hero_stack() -> None:
    request = structured_three_bet_request(
        ("Ah", "Ad"),
        three_bet_size=13,
        hero_stack=None,
    )

    assert not requires_hero_stack_for_preflop_chart(request.state)


@pytest.mark.parametrize(
    ("cards", "expected_action", "expected_tier"),
    [
        (("Ah", "Ad"), "raise", "five_bet_all_in"),
        (("Th", "Ts"), "call", "continue"),
        (("7h", "2d"), "fold", "fold"),
    ],
)
def test_four_bet_history_routes_conservative_response(
    cards: tuple[str, str],
    expected_action: str,
    expected_tier: str,
) -> None:
    result = solve_preflop_chart(structured_four_bet_request(cards))

    assert result is not None
    assert result.action == expected_action
    assert result.raw["scenario"] == "facing_four_bet"
    assert result.raw["chart_tier"] == expected_tier
    assert result.raw["opener_position"] == "cutoff"
    assert result.raw["three_bettor_position"] == "button"
    assert result.raw["three_bet_size"] == 8
    assert result.raw["four_bettor_position"] == "cutoff"
    assert result.raw["four_bet_size"] == 20
    assert result.raw["four_bet_to_three_bet_ratio"] == 2.5
    assert result.raw["policy_source"] == (
        "hero_opener_four_bet_size_stack_matchup"
    )


@pytest.mark.parametrize(
    ("opener_position", "hero_position"),
    tuple(FOUR_BET_DEFENSE_POLICIES),
)
def test_four_bet_history_routes_every_legal_position_matchup(
    opener_position: PreflopPosition,
    hero_position: PreflopPosition,
) -> None:
    result = solve_preflop_chart(
        structured_four_bet_request(
            ("Ah", "Ad"),
            opener_position=opener_position,
            hero_position=hero_position,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.raw["opener_position"] == opener_position
    assert result.raw["three_bettor_position"] == hero_position


@pytest.mark.parametrize(
    ("cards", "expected_action", "expected_tier"),
    [
        (("Ah", "Ad"), "raise", "five_bet_all_in"),
        (("Qh", "Qd"), "call", "continue"),
        (("7h", "2d"), "fold", "fold"),
    ],
)
def test_cold_four_bet_history_routes_conservative_response(
    cards: tuple[str, str],
    expected_action: str,
    expected_tier: str,
) -> None:
    result = solve_preflop_chart(structured_cold_four_bet_request(cards))

    assert result is not None
    assert result.action == expected_action
    assert result.raw["scenario"] == "facing_cold_four_bet"
    assert result.raw["chart_tier"] == expected_tier
    assert result.raw["opener_position"] == "utg"
    assert result.raw["three_bettor_position"] == "cutoff"
    assert result.raw["four_bettor_position"] == "button"
    assert result.raw["opening_raise_size"] == 2.5
    assert result.raw["three_bet_size"] == 8
    assert result.raw["four_bet_size"] == 20
    assert result.raw["four_bet_to_three_bet_ratio"] == 2.5
    assert result.raw["cold_four_bet_policy"] == COLD_FOUR_BET_POLICY_NAME
    assert result.raw["policy_source"] == (
        "hero_opener_cold_four_bettor_size_stack_matchup"
    )


@pytest.mark.parametrize(
    ("opener_position", "hero_position", "four_bettor_position"),
    tuple(COLD_FOUR_BET_DEFENSE_POLICIES),
)
def test_cold_four_bet_history_routes_every_legal_position_order(
    opener_position: PreflopPosition,
    hero_position: PreflopPosition,
    four_bettor_position: PreflopPosition,
) -> None:
    result = solve_preflop_chart(
        structured_cold_four_bet_request(
            ("Ah", "Ad"),
            opener_position=opener_position,
            hero_position=hero_position,
            four_bettor_position=four_bettor_position,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.raw["opener_position"] == opener_position
    assert result.raw["three_bettor_position"] == hero_position
    assert result.raw["four_bettor_position"] == four_bettor_position


def test_cold_four_bet_reconstructs_folded_opener_and_blinds() -> None:
    result = solve_preflop_chart(
        structured_cold_four_bet_request(
            ("Ah", "Ad"),
            opener_position="cutoff",
            hero_position="small_blind",
            four_bettor_position="big_blind",
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 100
    assert result.raw["maximum_five_bet_total"] == 100


def test_cold_four_bet_five_bet_uses_reconstructed_all_in_cap() -> None:
    result = solve_preflop_chart(
        structured_cold_four_bet_request(
            ("Ah", "Ad"),
            hero_stack=17,
            effective_stack=5,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 25
    assert result.raw["maximum_five_bet_total"] == 25


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 3),
        lambda state: setattr(state, "current_bet", 11),
        lambda state: setattr(state, "pot_size", 29.5),
        lambda state: setattr(state, "hero_stack", None),
        lambda state: setattr(state, "hero_stack", 11),
        lambda state: setattr(state, "effective_stack", 93),
        lambda state: setattr(state, "preflop_opener_position", "hijack"),
        lambda state: setattr(state, "preflop_open_size", 3),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="cutoff", action="raise", amount=8),
                PreflopAction(actor="hijack", action="raise", amount=20),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="cutoff", action="raise", amount=8),
                PreflopAction(actor="button", action="call", amount=20),
            ],
        ),
    ],
)
def test_declines_inconsistent_cold_four_bet_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_cold_four_bet_request(("Ah", "Ad"))
    mutation(request.state)

    assert solve_preflop_chart(request) is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"three_bet_size": 3.5},
        {"four_bet_size": 13},
        {"four_bet_size": 29},
    ],
)
def test_declines_unsupported_cold_four_bet_sizing(
    overrides: dict[str, float],
) -> None:
    request = structured_cold_four_bet_request(("Ah", "Ad"), **overrides)

    assert not supports_preflop_chart(request)
    assert solve_preflop_chart(request) is None


def test_declines_hero_open_with_two_later_raises() -> None:
    request = request_for(
        ("Ah", "Ad"),
        position="utg",
        current_bet=17.5,
        pot_size=31.5,
        hero_stack=97.5,
        effective_stack=80,
        players_in_hand=2,
        facing_action="raise",
        preflop_action_history=[
            PreflopAction(actor="utg", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
            PreflopAction(actor="small_blind", action="raise", amount=20),
        ],
    )

    assert solve_preflop_chart(request) is None


def test_five_bet_uses_reconstructed_all_in_cap() -> None:
    result = solve_preflop_chart(
        structured_four_bet_request(
            ("Ah", "Ad"),
            hero_stack=17,
            effective_stack=5,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 25
    assert result.raw["maximum_five_bet_total"] == 25


def test_calls_when_hero_has_no_legal_five_bet_above_four_bet() -> None:
    result = solve_preflop_chart(
        structured_four_bet_request(
            ("Ah", "Ad"),
            hero_stack=12,
            effective_stack=5,
        )
    )

    assert result is not None
    assert result.action == "call"
    assert result.sizing is None
    assert result.raw["maximum_five_bet_total"] == 20


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 3),
        lambda state: setattr(state, "current_bet", 11),
        lambda state: setattr(state, "pot_size", 28.5),
        lambda state: setattr(state, "hero_stack", None),
        lambda state: setattr(state, "hero_stack", 11),
        lambda state: setattr(state, "effective_stack", 93),
        lambda state: setattr(state, "preflop_opener_position", "hijack"),
        lambda state: setattr(state, "preflop_open_size", 3),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="cutoff", action="raise", amount=2.5),
                PreflopAction(actor="small_blind", action="raise", amount=8),
                PreflopAction(actor="cutoff", action="raise", amount=20),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="cutoff", action="raise", amount=2.5),
                PreflopAction(actor="button", action="raise", amount=8),
                PreflopAction(actor="small_blind", action="raise", amount=20),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="cutoff", action="raise", amount=2.5),
                PreflopAction(actor="button", action="raise", amount=8),
                PreflopAction(actor="cutoff", action="call", amount=20),
            ],
        ),
    ],
)
def test_declines_inconsistent_four_bet_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_four_bet_request(("Ah", "Ad"))
    mutation(request.state)

    assert solve_preflop_chart(request) is None


def test_declines_non_full_four_bet() -> None:
    result = solve_preflop_chart(
        structured_four_bet_request(("Ah", "Ad"), four_bet_size=13)
    )

    assert result is None


def test_declines_non_full_three_bet_in_four_bet_history() -> None:
    result = solve_preflop_chart(
        structured_four_bet_request(
            ("Ah", "Ad"),
            three_bet_size=3.5,
        )
    )

    assert result is None


def test_declines_four_bet_larger_than_supported_size_band() -> None:
    request = structured_four_bet_request(("Ah", "Ad"), four_bet_size=29)

    assert not supports_preflop_chart(request)
    assert solve_preflop_chart(request) is None


def test_oversized_four_bet_does_not_require_chart_specific_hero_stack() -> None:
    request = structured_four_bet_request(
        ("Ah", "Ad"),
        four_bet_size=29,
        hero_stack=None,
    )

    assert not requires_hero_stack_for_preflop_chart(request.state)


def test_four_bet_history_reconstructs_blind_commitments() -> None:
    result = solve_preflop_chart(
        structured_four_bet_request(
            ("Ah", "Ad"),
            opener_position="small_blind",
            hero_position="big_blind",
            opening_size=3,
            three_bet_size=9,
            four_bet_size=22.5,
            hero_stack=91,
            effective_stack=77.5,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 100
    assert result.raw["maximum_five_bet_total"] == 100


@pytest.mark.parametrize(
    ("cards", "expected_action", "expected_tier"),
    [
        (("Ah", "Ad"), "raise", "squeeze"),
        (("Ah", "Jh"), "call", "overcall"),
        (("Kh", "Qd"), "fold", "fold"),
    ],
)
def test_single_caller_history_routes_conservative_response(
    cards: tuple[str, str],
    expected_action: str,
    expected_tier: str,
) -> None:
    result = solve_preflop_chart(structured_called_open_request(cards))

    assert result is not None
    assert result.action == expected_action
    assert result.raw["scenario"] == "facing_open_with_caller"
    assert result.raw["chart_tier"] == expected_tier
    assert result.raw["opener_position"] == "utg"
    assert result.raw["caller_positions"] == ["hijack"]
    assert result.raw["caller_count"] == 1
    assert result.raw["caller_adjustment_policy"] == "single_caller_conservative"
    assert result.raw["policy_source"] == "hero_opener_caller_size_stack_matchup"


def test_single_caller_squeeze_uses_larger_raise_target() -> None:
    called = solve_preflop_chart(structured_called_open_request(("Ah", "Ad")))
    unopened_call = solve_preflop_chart(
        request_for(
            ("Ah", "Ad"),
            position="button",
            current_bet=2.5,
            pot_size=4,
            facing_action="raise",
            preflop_opener_position="utg",
            preflop_open_size=2.5,
        )
    )

    assert called is not None
    assert unopened_call is not None
    assert called.action == "raise"
    assert unopened_call.action == "raise"
    assert called.sizing == 10
    assert unopened_call.sizing == 7.5
    assert called.raw["squeeze_open_multiple"] == 4


def test_single_caller_tightens_boundary_hand_to_fold() -> None:
    called = solve_preflop_chart(structured_called_open_request(("Kh", "Qd")))
    heads_up = solve_preflop_chart(
        request_for(
            ("Kh", "Qd"),
            position="button",
            current_bet=2.5,
            pot_size=4,
            facing_action="raise",
            preflop_opener_position="utg",
            preflop_open_size=2.5,
        )
    )

    assert called is not None
    assert heads_up is not None
    assert called.action == "fold"
    assert heads_up.action == "call"
    assert called.raw["continue_fraction"] < heads_up.raw["continue_fraction"]


@pytest.mark.parametrize(
    ("cards", "expected_action", "expected_tier"),
    [
        (("Ah", "Ad"), "raise", "squeeze"),
        (("Ah", "Jh"), "call", "overcall"),
        (("Kh", "Qd"), "fold", "fold"),
    ],
)
def test_double_caller_history_routes_conservative_response(
    cards: tuple[str, str],
    expected_action: str,
    expected_tier: str,
) -> None:
    result = solve_preflop_chart(structured_double_called_open_request(cards))

    assert result is not None
    assert result.action == expected_action
    assert result.raw["scenario"] == "facing_open_with_callers"
    assert result.raw["chart_tier"] == expected_tier
    assert result.raw["opener_position"] == "utg"
    assert result.raw["caller_positions"] == ["hijack", "cutoff"]
    assert result.raw["caller_count"] == 2
    assert result.raw["caller_adjustment_policy"] == "double_caller_conservative"
    assert result.raw["policy_source"] == "hero_opener_callers_size_stack_matchup"


def test_double_caller_squeeze_uses_five_times_open_target() -> None:
    result = solve_preflop_chart(
        structured_double_called_open_request(("Ah", "Ad"))
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 12.5
    assert result.raw["squeeze_open_multiple"] == 5


def test_double_caller_history_reconstructs_blind_commitments() -> None:
    result = solve_preflop_chart(
        structured_double_called_open_request(
            ("Ah", "Ad"),
            caller_positions=("button", "small_blind"),
            hero_position="big_blind",
        )
    )

    assert result is not None
    assert result.raw["caller_positions"] == ["button", "small_blind"]
    assert result.raw["maximum_reraise_total"] == 101


@pytest.mark.parametrize(
    ("cards", "expected_action", "expected_tier"),
    [
        (("Ah", "Ad"), "raise", "squeeze"),
        (("Kh", "Qh"), "call", "overcall"),
        (("Kh", "Qd"), "fold", "fold"),
    ],
)
def test_triple_caller_history_routes_conservative_response(
    cards: tuple[str, str],
    expected_action: str,
    expected_tier: str,
) -> None:
    result = solve_preflop_chart(structured_triple_called_open_request(cards))

    assert result is not None
    assert result.action == expected_action
    assert result.raw["scenario"] == "facing_open_with_three_callers"
    assert result.raw["chart_tier"] == expected_tier
    assert result.raw["opener_position"] == "utg"
    assert result.raw["caller_positions"] == ["hijack", "cutoff", "button"]
    assert result.raw["caller_count"] == 3
    assert result.raw["caller_adjustment_policy"] == "triple_caller_conservative"
    assert result.raw["policy_source"] == "hero_opener_callers_size_stack_matchup"


def test_triple_caller_squeeze_uses_six_times_open_target() -> None:
    result = solve_preflop_chart(
        structured_triple_called_open_request(("Ah", "Ad"))
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 15
    assert result.raw["squeeze_open_multiple"] == 6


def test_triple_caller_history_reconstructs_blind_commitments() -> None:
    result = solve_preflop_chart(
        structured_triple_called_open_request(
            ("Ah", "Ad"),
            caller_positions=("hijack", "button", "small_blind"),
            hero_position="big_blind",
        )
    )

    assert result is not None
    assert result.raw["caller_positions"] == [
        "hijack",
        "button",
        "small_blind",
    ]
    assert result.raw["maximum_reraise_total"] == 101


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 4),
        lambda state: setattr(state, "players_in_hand", 6),
        lambda state: setattr(state, "current_bet", 1.5),
        lambda state: setattr(state, "pot_size", 13),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
                PreflopAction(actor="cutoff", action="call", amount=2.5),
                PreflopAction(actor="button", action="call", amount=2),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
                PreflopAction(actor="button", action="call", amount=2.5),
                PreflopAction(actor="cutoff", action="call", amount=2.5),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
                PreflopAction(actor="cutoff", action="call", amount=2.5),
                PreflopAction(actor="cutoff", action="call", amount=2.5),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
                PreflopAction(actor="cutoff", action="call", amount=2.5),
                PreflopAction(actor="button", action="raise", amount=8),
            ],
        ),
    ],
)
def test_declines_inconsistent_triple_caller_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_triple_called_open_request(("Ah", "Ad"))
    mutation(request.state)

    assert solve_preflop_chart(request) is None


@pytest.mark.parametrize(
    ("cards", "expected_action", "expected_tier"),
    [
        (("Ah", "Ad"), "raise", "squeeze"),
        (("Kh", "Qh"), "call", "overcall"),
        (("Kh", "Qd"), "fold", "fold"),
    ],
)
def test_four_caller_history_routes_terminal_full_table_response(
    cards: tuple[str, str],
    expected_action: str,
    expected_tier: str,
) -> None:
    result = solve_preflop_chart(structured_four_called_open_request(cards))

    assert result is not None
    assert result.action == expected_action
    assert result.raw["scenario"] == "facing_open_with_four_callers"
    assert result.raw["chart_tier"] == expected_tier
    assert result.raw["opener_position"] == "utg"
    assert result.raw["caller_positions"] == [
        "hijack",
        "cutoff",
        "button",
        "small_blind",
    ]
    assert result.raw["caller_count"] == 4
    assert result.raw["caller_adjustment_policy"] == "four_caller_conservative"
    assert result.raw["policy_source"] == "hero_opener_callers_size_stack_matchup"


def test_four_caller_squeeze_uses_seven_times_open_target() -> None:
    result = solve_preflop_chart(
        structured_four_called_open_request(("Ah", "Ad"))
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 17.5
    assert result.raw["squeeze_open_multiple"] == 7
    assert result.raw["maximum_reraise_total"] == 101


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 5),
        lambda state: setattr(state, "current_bet", 1),
        lambda state: setattr(state, "pot_size", 15),
        lambda state: setattr(state, "hero_position", "small_blind"),
        lambda state: setattr(state, "preflop_opener_position", "hijack"),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
                PreflopAction(actor="cutoff", action="call", amount=2.5),
                PreflopAction(actor="button", action="call", amount=2.5),
                PreflopAction(actor="small_blind", action="call", amount=2),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
                PreflopAction(actor="button", action="call", amount=2.5),
                PreflopAction(actor="cutoff", action="call", amount=2.5),
                PreflopAction(actor="small_blind", action="call", amount=2.5),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
                PreflopAction(actor="cutoff", action="call", amount=2.5),
                PreflopAction(actor="button", action="call", amount=2.5),
                PreflopAction(actor="button", action="call", amount=2.5),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
                PreflopAction(actor="cutoff", action="call", amount=2.5),
                PreflopAction(actor="button", action="call", amount=2.5),
                PreflopAction(actor="small_blind", action="raise", amount=8),
            ],
        ),
    ],
)
def test_declines_inconsistent_four_caller_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_four_called_open_request(("Ah", "Ad"))
    mutation(request.state)

    assert solve_preflop_chart(request) is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 3),
        lambda state: setattr(state, "players_in_hand", 5),
        lambda state: setattr(state, "current_bet", 2),
        lambda state: setattr(state, "pot_size", 8),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
                PreflopAction(actor="cutoff", action="call", amount=2),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="cutoff", action="call", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2.5),
                PreflopAction(actor="cutoff", action="raise", amount=8),
            ],
        ),
    ],
)
def test_declines_inconsistent_double_caller_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_double_called_open_request(("Ah", "Ad"))
    mutation(request.state)

    assert solve_preflop_chart(request) is None


def test_declines_five_callers_beyond_six_max_seat_capacity() -> None:
    request = structured_four_called_open_request(("Ah", "Ad"))
    request.state.preflop_action_history.append(
        PreflopAction(actor="big_blind", action="call", amount=2.5)
    )

    assert solve_preflop_chart(request) is None


@pytest.mark.parametrize(
    "tail",
    [
        [
            PreflopAction(actor="small_blind", action="call", amount=8),
            PreflopAction(actor="big_blind", action="call", amount=8),
        ],
        [
            PreflopAction(actor="button", action="call", amount=8),
            PreflopAction(actor="small_blind", action="call", amount=8),
            PreflopAction(actor="big_blind", action="call", amount=8),
        ],
    ],
)
def test_declines_long_history_when_second_action_is_not_a_call(
    tail: list[PreflopAction],
) -> None:
    request = structured_cold_three_bet_request(("Ah", "Ad"))
    request.state.preflop_action_history.extend(tail)

    assert solve_preflop_chart(request) is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 4),
        lambda state: setattr(state, "current_bet", 2),
        lambda state: setattr(state, "pot_size", 6),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="raise", amount=2.5),
                PreflopAction(actor="hijack", action="call", amount=2),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="hijack", action="raise", amount=2.5),
                PreflopAction(actor="utg", action="call", amount=2.5),
            ],
        ),
    ],
)
def test_declines_inconsistent_single_caller_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_called_open_request(("Ah", "Ad"))
    mutation(request.state)

    assert solve_preflop_chart(request) is None


def test_three_bet_size_tightens_continue_boundary() -> None:
    small = solve_preflop_chart(
        structured_three_bet_request(
            ("Ah", "Qd"),
            three_bet_size=6.5,
            effective_stack=93.5,
        )
    )
    very_large = solve_preflop_chart(
        structured_three_bet_request(
            ("Ah", "Qd"),
            three_bet_size=12,
            effective_stack=88,
        )
    )

    assert small is not None
    assert very_large is not None
    assert small.action == "call"
    assert very_large.action == "fold"
    assert small.raw["three_bet_size_policy"] == "small"
    assert very_large.raw["three_bet_size_policy"] == "very_large"
    assert small.raw["continue_fraction"] > very_large.raw["continue_fraction"]


def test_short_stack_moves_boundary_hand_into_four_bet_range() -> None:
    short = solve_preflop_chart(
        structured_three_bet_request(
            ("8h", "8s"),
            hero_stack=17.5,
            effective_stack=12,
        )
    )
    standard = solve_preflop_chart(structured_three_bet_request(("8h", "8s")))

    assert short is not None
    assert standard is not None
    assert short.action == "raise"
    assert standard.action == "call"
    assert short.raw["stack_depth_policy"] == "short"
    assert short.raw["four_bet_fraction"] > standard.raw["four_bet_fraction"]


def test_four_bet_size_is_capped_by_hero_total_stack() -> None:
    result = solve_preflop_chart(
        structured_three_bet_request(
            ("Ah", "Ad"),
            hero_stack=9.5,
            effective_stack=9.5,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 12
    assert result.raw["maximum_four_bet_total"] == 12


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "current_bet", 5),
        lambda state: setattr(state, "pot_size", 11),
        lambda state: setattr(state, "hero_stack", None),
        lambda state: setattr(state, "hero_stack", 5),
        lambda state: setattr(state, "effective_stack", 98),
        lambda state: setattr(state, "preflop_opener_position", "hijack"),
        lambda state: setattr(state, "preflop_open_size", 3),
    ],
)
def test_declines_inconsistent_structured_three_bet_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_three_bet_request(("Ah", "Ad"))
    mutation(request.state)

    assert solve_preflop_chart(request) is None


@pytest.mark.parametrize(
    "history",
    [
        [PreflopAction(actor="cutoff", action="call", amount=2.5)],
        [PreflopAction(actor="button", action="raise", amount=2.5)],
        [
            PreflopAction(actor="hijack", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
        ],
        [
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="hijack", action="raise", amount=8),
        ],
        [
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=3.5),
        ],
        [
            PreflopAction(actor="cutoff", action="raise", amount=2.5),
            PreflopAction(actor="button", action="raise", amount=8),
            PreflopAction(actor="small_blind", action="raise", amount=20),
        ],
    ],
)
def test_declines_unsupported_structured_preflop_histories(
    history: list[PreflopAction],
) -> None:
    request = structured_three_bet_request(("Ah", "Ad"))
    request.state.preflop_action_history = history

    assert solve_preflop_chart(request) is None


def test_declines_three_bet_larger_than_supported_size_band() -> None:
    result = solve_preflop_chart(
        structured_three_bet_request(
            ("Ah", "Ad"),
            three_bet_size=13,
            effective_stack=87,
        )
    )

    assert result is None


def test_checks_big_blind_when_no_amount_is_required() -> None:
    result = solve_preflop_chart(request_for(("7h", "2d"), position="BB"))

    assert result is not None
    assert result.action == "check"
    assert [candidate["action"] for candidate in result.raw["candidates"]] == ["check", "raise"]


@pytest.mark.parametrize(
    "recommendation_request",
    [
        request_for(("Ah", "Kd"), position=None),
        request_for(
            ("Ah", "Kd"),
            position="button",
            current_bet=0,
            pot_size=1.5,
            facing_action="raise",
            action_context="UTG raises",
        ),
        request_for(
            ("Ah", "Kd"),
            position="button",
            current_bet=0,
            pot_size=1.5,
            action_context="UTG opens to 2.5 BB",
        ),
        request_for(("Ah", "Kd"), position="button", players_in_hand=7),
        request_for(("Ah", "Ad"), position="button", effective_stack=0),
        request_for(
            ("Ah", "Ad"),
            position="button",
            preflop_opener_position="cutoff",
        ),
        request_for(("Ah", "Kd"), position="button", pot_size=2.5),
        request_for(("Ah", "Kd"), position="button", pot_size=4.5),
        request_for(("Ah", "Ad"), position="BB", pot_size=4.5),
        request_for(("Ah", "Ad"), position="BB", current_bet=2.5, pot_size=4.5),
        request_for(
            ("Ah", "Ad"),
            position="BB",
            current_bet=2.5,
            pot_size=4.5,
            facing_action="raise",
        ),
        request_for(
            ("Ah", "Ad"),
            position="BB",
            current_bet=2.5,
            pot_size=2.5,
            facing_action="raise",
            action_context="CO opens to 2.5 BB",
        ),
        request_for(
            ("Ah", "Ad"),
            position="button",
            current_bet=2.5,
            pot_size=6.5,
            facing_action="raise",
            action_context="UTG raises to 2.5 BB",
        ),
        request_for(
            ("Ah", "Ad"),
            position="big blind",
            current_bet=1.5,
            pot_size=4,
            facing_action="raise",
            preflop_opener_position="button",
            preflop_open_size=3,
        ),
        request_for(
            ("Ah", "Ad"),
            position="big blind",
            current_bet=1.5,
            pot_size=4,
            facing_action="raise",
            action_context="Button opens to 3 BB",
        ),
        request_for(
            ("Ah", "Ad"),
            position="big blind",
            current_bet=0.5,
            pot_size=3,
            facing_action="raise",
            preflop_opener_position="button",
            preflop_open_size=1.5,
        ),
        request_for(
            ("Ah", "Ad"),
            position="big blind",
            current_bet=3.5,
            pot_size=6,
            facing_action="raise",
            preflop_opener_position="button",
            preflop_open_size=4.5,
        ),
        request_for(
            ("Ah", "Ad"),
            position="BB",
            current_bet=2.5,
            pot_size=4.5,
            facing_action="raise",
            action_context="Opponent raises to 3 BB",
        ),
        request_for(
            ("Ah", "Ad"),
            position="UTG",
            current_bet=2.5,
            pot_size=4.5,
            facing_action="raise",
            action_context="Hijack raises to 3 BB",
        ),
        request_for(
            ("Ah", "Ad"),
            position="cutoff",
            current_bet=2.5,
            pot_size=4.5,
            facing_action="raise",
            action_context="Button raises to 3 BB",
        ),
        request_for(("Ah", "Kd"), position="button", action_context="UTG limp, hero to act"),
        request_for(
            ("Ah", "Kd"),
            position="button",
            current_bet=2.5,
            pot_size=6.5,
            facing_action="raise",
            action_context="UTG raises, CO calls, hero on button",
        ),
        request_for(
            ("Ah", "Kd"),
            position="button",
            current_bet=2.5,
            pot_size=6.5,
            facing_action="raise",
            action_context="UTG raises, CO call, hero on button",
        ),
        request_for(
            ("Ah", "Kd"),
            position="button",
            current_bet=2.5,
            pot_size=6.5,
            facing_action="raise",
            action_context="UTG raises, CO flatted, hero on button",
        ),
        request_for(
            ("Ah", "Kd"),
            position="BB",
            current_bet=3,
            pot_size=6.5,
            facing_action="raise",
            action_context="UTG raises, button raises to 4 BB",
        ),
        request_for(
            ("Ah", "Kd"),
            position="BB",
            current_bet=3,
            pot_size=6.5,
            facing_action="raise",
            action_context="UTG opens, button opens to 4 BB",
        ),
        request_for(
            ("Ah", "Kd"),
            position="BB",
            current_bet=2,
            pot_size=4.5,
            facing_action="raise",
            action_context="UTG raises all-in to 3 BB",
        ),
        request_for(
            ("Ah", "Kd"),
            position="BB",
            current_bet=3,
            pot_size=6.5,
            facing_action="raise",
            action_context="UTG raises, button squeezed to 4 BB",
        ),
        request_for(
            ("Ah", "Kd"),
            position="button",
            current_bet=8,
            pot_size=12,
            facing_action="raise",
            action_context="Hero faces a 3-bet",
        ),
        request_for(
            ("Ah", "Kd"),
            position="button",
            current_bet=8,
            pot_size=12,
            facing_action="raise",
            action_context="UTG raises to 9 BB",
        ),
        request_for(
            ("Ah", "Kd"),
            position="button",
            current_bet=24,
            pot_size=36,
            facing_action="raise",
            action_context="Hero faces a five-bet",
        ),
        request_for(
            ("Ah", "Kd"),
            position="button",
            current_bet=8,
            pot_size=12,
            facing_action="raise",
            action_context="Small blind re-raises, hero to act",
        ),
        request_for(
            ("Ah", "Kd"),
            position="BB",
            current_bet=3,
            pot_size=6,
            facing_action="raise",
            action_context="UTG raises, button reraised to 4 BB",
        ),
        request_for(
            ("Ah", "Kd"),
            position="BB",
            current_bet=3,
            pot_size=6,
            facing_action="raise",
            action_context="UTG raises, button re-raised to 4 BB",
        ),
    ],
)
def test_declines_ambiguous_preflop_states(
    recommendation_request: RecommendationRequest,
) -> None:
    assert solve_preflop_chart(recommendation_request) is None


def test_isolation_response_policies_cover_every_limper_raiser_order() -> None:
    expected_matchups = {
        (hero, raiser)
        for hero in POSITION_ACTION_ORDER
        for raiser in POSITION_ACTION_ORDER
        if POSITION_ACTION_ORDER[hero] < POSITION_ACTION_ORDER[raiser]
    }

    assert set(ISOLATION_RESPONSE_POLICIES) == expected_matchups
    assert all(
        0 < policy.reraise_fraction <= policy.continue_fraction <= 1
        for policy in ISOLATION_RESPONSE_POLICIES.values()
    )


def test_isolation_size_policies_tighten_as_raise_grows() -> None:
    assert ISOLATION_RAISE_SIZE_POLICIES[-1].maximum_size == (
        MAX_SUPPORTED_ISOLATION_RAISE_SIZE_BB
    )


@pytest.mark.parametrize(
    ("raise_size", "expected_policy"),
    [
        (2.0, "small"),
        (3.0, "small"),
        (3.01, "standard"),
        (4.0, "standard"),
        (4.01, "large"),
        (5.0, "large"),
    ],
)
def test_isolation_size_policy_boundaries(
    raise_size: float,
    expected_policy: str,
) -> None:
    policy = policy_for_isolation_raise_size(raise_size)

    assert policy is not None
    assert policy.name == expected_policy


def test_isolation_response_policies_remain_valid_after_adjustments() -> None:
    for base_policy in ISOLATION_RESPONSE_POLICIES.values():
        for size_policy in ISOLATION_RAISE_SIZE_POLICIES:
            for stack_policy in STACK_DEPTH_POLICIES:
                adjusted = adjusted_defense_policy(
                    base_policy,
                    size_policy,
                    stack_policy,
                )
                assert (
                    0
                    < adjusted.reraise_fraction
                    <= adjusted.continue_fraction
                    <= 1
                )
    assert [
        policy.maximum_size for policy in ISOLATION_RAISE_SIZE_POLICIES
    ] == sorted(policy.maximum_size for policy in ISOLATION_RAISE_SIZE_POLICIES)
    assert all(
        current.continue_multiplier >= following.continue_multiplier
        and current.reraise_multiplier >= following.reraise_multiplier
        for current, following in zip(
            ISOLATION_RAISE_SIZE_POLICIES,
            ISOLATION_RAISE_SIZE_POLICIES[1:],
        )
    )


@pytest.mark.parametrize(
    ("cards", "expected_action", "expected_tier"),
    [
        (("Ah", "Ad"), "raise", "limp_reraise"),
        (("9h", "9s"), "call", "continue"),
        (("7h", "2d"), "fold", "fold"),
    ],
)
def test_isolation_raise_history_routes_position_aware_response(
    cards: tuple[str, str],
    expected_action: str,
    expected_tier: str,
) -> None:
    result = solve_preflop_chart(structured_isolation_raise_request(cards))

    assert result is not None
    assert result.action == expected_action
    assert result.raw["scenario"] == "facing_isolation_raise_after_limp"
    assert result.raw["chart_tier"] == expected_tier
    assert result.raw["limper_position"] == "utg"
    assert result.raw["isolation_raiser_position"] == "button"
    assert result.raw["limp_size"] == 1
    assert result.raw["isolation_raise_size"] == 4
    assert result.raw["isolation_raise_to_limp_ratio"] == 4
    assert result.raw["isolation_raise_size_policy"] == "standard"
    assert result.raw["isolation_response_policy"] == (
        ISOLATION_RESPONSE_POLICY_NAME
    )
    assert result.raw["policy_source"] == (
        "hero_limper_isolation_raiser_size_stack_matchup"
    )
    assert "opener_position" not in result.raw
    assert "three_bettor_position" not in result.raw


@pytest.mark.parametrize(
    ("hero_position", "raiser_position"),
    tuple(ISOLATION_RESPONSE_POLICIES),
)
def test_isolation_response_routes_every_legal_position_order(
    hero_position: PreflopPosition,
    raiser_position: PreflopPosition,
) -> None:
    result = solve_preflop_chart(
        structured_isolation_raise_request(
            ("Ah", "Ad"),
            hero_position=hero_position,
            raiser_position=raiser_position,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.raw["position"] == hero_position
    assert result.raw["isolation_raiser_position"] == raiser_position


def test_isolation_response_accounts_for_raiser_position() -> None:
    hijack = solve_preflop_chart(
        structured_isolation_raise_request(
            ("Ah", "Js"),
            raiser_position="hijack",
        )
    )
    button = solve_preflop_chart(
        structured_isolation_raise_request(
            ("Ah", "Js"),
            raiser_position="button",
        )
    )

    assert hijack is not None
    assert button is not None
    assert hijack.action == "fold"
    assert button.action == "call"


def test_isolation_response_tightens_against_larger_raise() -> None:
    standard = solve_preflop_chart(
        structured_isolation_raise_request(("Ah", "Js"))
    )
    large = solve_preflop_chart(
        structured_isolation_raise_request(
            ("Ah", "Js"),
            isolation_raise_size=5,
        )
    )

    assert standard is not None
    assert large is not None
    assert standard.action == "call"
    assert large.action == "fold"
    assert standard.raw["continue_fraction"] > large.raw["continue_fraction"]


def test_isolation_response_accounts_for_stack_depth() -> None:
    short = solve_preflop_chart(
        structured_isolation_raise_request(
            ("Ah", "Ts"),
            hero_stack=19,
            effective_stack=19,
        )
    )
    standard = solve_preflop_chart(
        structured_isolation_raise_request(("Ah", "Ts"))
    )

    assert short is not None
    assert standard is not None
    assert short.action == "fold"
    assert standard.action == "call"


def test_isolation_limp_reraise_is_capped_by_available_total() -> None:
    result = solve_preflop_chart(
        structured_isolation_raise_request(
            ("Ah", "Ad"),
            hero_stack=5,
            effective_stack=5,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 6
    assert result.raw["maximum_reraise_total"] == 6


def test_isolation_response_calls_when_no_legal_reraise_total_remains() -> None:
    result = solve_preflop_chart(
        structured_isolation_raise_request(
            ("Ah", "Ad"),
            hero_stack=3,
            effective_stack=3,
        )
    )

    assert result is not None
    assert result.action == "call"
    assert result.sizing is None
    assert result.raw["maximum_reraise_total"] == 4


def test_isolation_response_identifies_missing_hero_stack() -> None:
    request = structured_isolation_raise_request(("Ah", "Ad"), hero_stack=None)

    assert requires_hero_stack_for_preflop_chart(request.state)
    assert solve_preflop_chart(request) is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 3),
        lambda state: setattr(state, "current_bet", 2),
        lambda state: setattr(state, "pot_size", 20),
        lambda state: setattr(state, "hero_stack", None),
        lambda state: setattr(state, "hero_stack", 2),
        lambda state: setattr(state, "effective_stack", 100),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="hijack", action="call", amount=1),
                PreflopAction(actor="button", action="raise", amount=4),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="call", amount=1.5),
                PreflopAction(actor="button", action="raise", amount=4),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="call", amount=1),
                PreflopAction(actor="button", action="call", amount=4),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="button", action="call", amount=1),
                PreflopAction(actor="utg", action="raise", amount=4),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="call", amount=1),
                PreflopAction(actor="button", action="raise", amount=1.5),
            ],
        ),
        lambda state: setattr(
            state,
            "preflop_action_history",
            [
                PreflopAction(actor="utg", action="call", amount=1),
                PreflopAction(actor="button", action="raise", amount=5.5),
            ],
        ),
        lambda state: state.preflop_action_history.append(
            PreflopAction(actor="big_blind", action="call", amount=4)
        ),
    ],
)
def test_declines_inconsistent_isolation_raise_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_isolation_raise_request(("Ah", "Ad"))
    mutation(request.state)

    assert solve_preflop_chart(request) is None


def test_isolation_response_ignores_stale_legacy_opener_fields() -> None:
    request = structured_isolation_raise_request(("9h", "9s"))
    request.state.preflop_opener_position = "cutoff"
    request.state.preflop_open_size = 2.5

    result = solve_preflop_chart(request)

    assert result is not None
    assert result.action == "call"
    assert result.raw["scenario"] == "facing_isolation_raise_after_limp"
    assert "opener_position" not in result.raw
    assert "opening_raise_size" not in result.raw


def test_limp_reraise_policies_cover_every_legal_position_order() -> None:
    expected_matchups = {
        (limper, hero)
        for limper in POSITION_ACTION_ORDER
        for hero in POSITION_ACTION_ORDER
        if POSITION_ACTION_ORDER[limper] < POSITION_ACTION_ORDER[hero]
    }

    assert set(LIMP_RERAISE_RESPONSE_POLICIES) == expected_matchups
    assert all(
        0 < policy.four_bet_fraction <= policy.continue_fraction <= 1
        for policy in LIMP_RERAISE_RESPONSE_POLICIES.values()
    )


def test_limp_reraise_policies_remain_valid_after_adjustments() -> None:
    for base_policy in LIMP_RERAISE_RESPONSE_POLICIES.values():
        for size_policy in LIMP_RERAISE_SIZE_POLICIES:
            for stack_policy in STACK_DEPTH_POLICIES:
                adjusted = adjusted_three_bet_defense_policy(
                    base_policy,
                    size_policy,
                    stack_policy,
                )
                assert (
                    0
                    < adjusted.four_bet_fraction
                    <= adjusted.continue_fraction
                    <= 1
                )
    assert [
        policy.maximum_ratio for policy in LIMP_RERAISE_SIZE_POLICIES
    ] == sorted(policy.maximum_ratio for policy in LIMP_RERAISE_SIZE_POLICIES)
    assert all(
        current.continue_multiplier >= following.continue_multiplier
        and current.four_bet_multiplier >= following.four_bet_multiplier
        for current, following in zip(
            LIMP_RERAISE_SIZE_POLICIES,
            LIMP_RERAISE_SIZE_POLICIES[1:],
        )
    )
    assert LIMP_RERAISE_SIZE_POLICIES[-1].maximum_ratio == (
        MAX_SUPPORTED_LIMP_RERAISE_TO_ISOLATION_RATIO
    )


@pytest.mark.parametrize(
    ("ratio", "expected_policy"),
    [
        (1.75, "small"),
        (2.25, "small"),
        (2.26, "standard"),
        (2.75, "standard"),
        (2.76, "large"),
        (3.25, "large"),
        (3.26, "very_large"),
        (4.0, "very_large"),
    ],
)
def test_limp_reraise_size_policy_boundaries(
    ratio: float,
    expected_policy: str,
) -> None:
    policy = policy_for_limp_reraise_size(ratio)

    assert policy is not None
    assert policy.name == expected_policy


@pytest.mark.parametrize(
    ("cards", "expected_action", "expected_tier"),
    [
        (("Ah", "Ad"), "raise", "four_bet"),
        (("Th", "Ts"), "call", "continue"),
        (("7h", "2d"), "fold", "fold"),
    ],
)
def test_limp_reraise_history_routes_position_aware_response(
    cards: tuple[str, str],
    expected_action: str,
    expected_tier: str,
) -> None:
    request = structured_limp_reraise_request(cards)

    assert supports_preflop_chart(request)
    result = solve_preflop_chart(request)

    assert result is not None
    assert result.action == expected_action
    assert result.raw["scenario"] == "facing_limp_reraise"
    assert result.raw["chart_tier"] == expected_tier
    assert result.raw["limper_position"] == "utg"
    assert result.raw["limp_size"] == 1
    assert result.raw["hero_isolation_raise_size"] == 4
    assert result.raw["limp_reraiser_position"] == "utg"
    assert result.raw["limp_reraise_size"] == 12
    assert result.raw["limp_reraise_to_isolation_ratio"] == 3
    assert result.raw["limp_reraise_size_policy"] == "large"
    assert result.raw["limp_reraise_response_policy"] == (
        LIMP_RERAISE_RESPONSE_POLICY_NAME
    )
    assert result.raw["policy_source"] == (
        "original_limper_hero_isolator_size_stack_matchup"
    )
    assert "opener_position" not in result.raw
    assert "three_bettor_position" not in result.raw


@pytest.mark.parametrize(
    ("limper_position", "hero_position"),
    tuple(LIMP_RERAISE_RESPONSE_POLICIES),
)
def test_limp_reraise_routes_every_legal_position_order(
    limper_position: PreflopPosition,
    hero_position: PreflopPosition,
) -> None:
    result = solve_preflop_chart(
        structured_limp_reraise_request(
            ("Ah", "Ad"),
            limper_position=limper_position,
            hero_position=hero_position,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.raw["position"] == hero_position
    assert result.raw["limp_reraiser_position"] == limper_position


def test_limp_reraise_response_accounts_for_positions() -> None:
    early = solve_preflop_chart(
        structured_limp_reraise_request(
            ("Ah", "Ks"),
            limper_position="utg",
            hero_position="hijack",
        )
    )
    blind_war = solve_preflop_chart(
        structured_limp_reraise_request(
            ("Ah", "Ks"),
            limper_position="small_blind",
            hero_position="big_blind",
        )
    )

    assert early is not None
    assert blind_war is not None
    assert early.action == "fold"
    assert blind_war.action == "call"


def test_limp_reraise_response_tightens_as_raise_grows() -> None:
    small = solve_preflop_chart(
        structured_limp_reraise_request(
            ("9h", "9s"),
            limp_reraise_size=8,
        )
    )
    very_large = solve_preflop_chart(
        structured_limp_reraise_request(
            ("9h", "9s"),
            limp_reraise_size=16,
        )
    )

    assert small is not None
    assert very_large is not None
    assert small.action == "call"
    assert very_large.action == "fold"
    assert small.raw["continue_fraction"] > very_large.raw["continue_fraction"]


def test_limp_reraise_response_accounts_for_stack_depth() -> None:
    short = solve_preflop_chart(
        structured_limp_reraise_request(
            ("Ah", "Ks"),
            limper_position="small_blind",
            hero_position="big_blind",
            effective_stack=20,
        )
    )
    standard = solve_preflop_chart(
        structured_limp_reraise_request(
            ("Ah", "Ks"),
            limper_position="small_blind",
            hero_position="big_blind",
        )
    )

    assert short is not None
    assert standard is not None
    assert short.action == "fold"
    assert standard.action == "call"


def test_limp_reraise_four_bet_is_capped_by_available_total() -> None:
    result = solve_preflop_chart(
        structured_limp_reraise_request(
            ("Ah", "Ad"),
            limp_reraise_size=7,
            hero_stack=10,
            effective_stack=8,
        )
    )

    assert result is not None
    assert result.action == "raise"
    assert result.sizing == 14
    assert result.raw["maximum_four_bet_total"] == 14


def test_limp_reraise_response_calls_when_no_raise_total_remains() -> None:
    result = solve_preflop_chart(
        structured_limp_reraise_request(
            ("Ah", "Ad"),
            limp_reraise_size=12,
            hero_stack=8,
            effective_stack=8,
        )
    )

    assert result is not None
    assert result.action == "call"
    assert result.sizing is None
    assert result.raw["maximum_four_bet_total"] == 12


def test_limp_reraise_response_identifies_missing_hero_stack() -> None:
    request = structured_limp_reraise_request(("Ah", "Ad"), hero_stack=None)

    assert requires_hero_stack_for_preflop_chart(request.state)
    assert solve_preflop_chart(request) is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda state: setattr(state, "players_in_hand", 3),
        lambda state: setattr(state, "current_bet", 7),
        lambda state: setattr(state, "pot_size", 30),
        lambda state: setattr(state, "hero_stack", None),
        lambda state: setattr(state, "hero_stack", 7),
        lambda state: setattr(state, "effective_stack", 100),
        lambda state: setattr(state.preflop_action_history[0], "amount", 1.5),
        lambda state: setattr(state.preflop_action_history[0], "actor", "button"),
        lambda state: setattr(state.preflop_action_history[1], "actor", "cutoff"),
        lambda state: setattr(state.preflop_action_history[1], "action", "call"),
        lambda state: setattr(state.preflop_action_history[1], "amount", 1.5),
        lambda state: setattr(state.preflop_action_history[1], "amount", 5.5),
        lambda state: setattr(state.preflop_action_history[2], "actor", "hijack"),
        lambda state: setattr(state.preflop_action_history[2], "action", "call"),
        lambda state: setattr(state.preflop_action_history[2], "amount", 6),
        lambda state: setattr(state.preflop_action_history[2], "amount", 17),
        lambda state: state.preflop_action_history.append(
            PreflopAction(actor="big_blind", action="call", amount=12)
        ),
    ],
)
def test_declines_inconsistent_limp_reraise_state(
    mutation: Callable[[CanonicalState], None],
) -> None:
    request = structured_limp_reraise_request(("Ah", "Ad"))
    mutation(request.state)

    assert solve_preflop_chart(request) is None


def test_limp_reraise_response_ignores_stale_legacy_opener_fields() -> None:
    request = structured_limp_reraise_request(("Th", "Ts"))
    request.state.preflop_opener_position = "cutoff"
    request.state.preflop_open_size = 2.5

    result = solve_preflop_chart(request)

    assert result is not None
    assert result.action == "call"
    assert result.raw["scenario"] == "facing_limp_reraise"
    assert "opener_position" not in result.raw
    assert "opening_raise_size" not in result.raw
