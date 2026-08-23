from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
import re
from typing import Literal

from app.domain.poker import PreflopPosition
from app.models import CanonicalState, RecommendationRequest

Position = PreflopPosition

POSITION_ALIASES: dict[str, Position] = {
    "utg": "utg",
    "under the gun": "utg",
    "ep": "utg",
    "early": "utg",
    "early position": "utg",
    "hj": "hijack",
    "hijack": "hijack",
    "mp": "hijack",
    "middle": "hijack",
    "middle position": "hijack",
    "co": "cutoff",
    "cutoff": "cutoff",
    "btn": "button",
    "button": "button",
    "dealer": "button",
    "sb": "small_blind",
    "small blind": "small_blind",
    "bb": "big_blind",
    "big blind": "big_blind",
}
POSITION_ACTION_ORDER: dict[Position, int] = {
    "utg": 0,
    "hijack": 1,
    "cutoff": 2,
    "button": 3,
    "small_blind": 4,
    "big_blind": 5,
}
POSTED_BLIND_BB: dict[Position, float] = {
    "utg": 0.0,
    "hijack": 0.0,
    "cutoff": 0.0,
    "button": 0.0,
    "small_blind": 0.5,
    "big_blind": 1.0,
}

POSITION_REFERENCE = (
    r"under the gun|early position|middle position|small blind|big blind|"
    r"utg|ep|hijack|hj|mp|cutoff|co|button|btn|dealer|sb|bb"
)
OPEN_RAISE_ACTION_REFERENCE = r"(?:open(?:s|ed)?|(?:open\s+)?rais(?:e|es|ed))"
POSITION_OPEN_RAISE_PATTERNS = (
    re.compile(
        rf"\b(?P<position>{POSITION_REFERENCE})\b\s+{OPEN_RAISE_ACTION_REFERENCE}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\brais(?:e|es|ed)\b\s+from\s+(?P<position>{POSITION_REFERENCE})\b",
        re.IGNORECASE,
    ),
)
POSITION_OPEN_RAISE_SIZE_PATTERN = re.compile(
    rf"\b(?:{POSITION_REFERENCE})\b\s+{OPEN_RAISE_ACTION_REFERENCE}\b\s+to\s+"
    r"(?P<size>\d+(?:\.\d+)?)\s*bb\b",
    re.IGNORECASE,
)
CALLER_ACTION_PATTERN = re.compile(
    rf"\b(?:{POSITION_REFERENCE})\b\s+call\b|"
    r"\b(?:calls|called|callers?|overcall(?:s|ed|ing)?|"
    r"cold call(?:s|ed|ing)?|flat(?:s|ted|ting)?)\b",
    re.IGNORECASE,
)
LATER_RAISE_PATTERN = re.compile(
    r"\b(?:(?:[3-9]|\d{2,})|three|four|five|six|seven|eight|nine)\s*bets?\b"
    r"|\bre\s*rais(?:e|es|ed)\b",
    re.IGNORECASE,
)
RAISE_ACTION_PATTERN = re.compile(
    r"\b(?:open\s+rais(?:e|es|ed)|open(?:s|ed)?|rais(?:e|es|ed))\b",
    re.IGNORECASE,
)
NON_OPEN_AGGRESSION_PATTERN = re.compile(
    r"\ball\s*in\b|\bjam(?:s|med|ming)?\b|\bshov(?:e|es|ed|ing)\b|"
    r"\bsqueez(?:e|es|ed|ing)\b",
    re.IGNORECASE,
)
MIN_BLIND_ONLY_POT_BB = 1.25
MAX_BLIND_ONLY_POT_BB = 1.75
MIN_SINGLE_OPEN_SIZE_BB = 2.0
MAX_SINGLE_OPEN_SIZE_BB = 4.0
MAX_SUPPORTED_ISOLATION_RAISE_SIZE_BB = 5.0
MAX_SUPPORTED_LIMP_RERAISE_TO_ISOLATION_RATIO = 4.0
MAX_SUPPORTED_THREE_BET_TO_OPEN_RATIO = 5.0
MAX_SUPPORTED_FOUR_BET_TO_THREE_BET_RATIO = 3.5
MONEY_TOLERANCE_BB = 0.05

PreflopChartScenario = Literal[
    "first_in",
    "big_blind_option",
    "heads_up_limp_big_blind",
    "two_limpers_big_blind",
    "three_limpers_big_blind",
    "four_limpers_big_blind",
    "five_limpers_big_blind",
    "facing_isolation_raise_after_limp",
    "facing_limp_reraise",
    "facing_open_raise",
    "facing_open_with_caller",
    "facing_open_with_callers",
    "facing_open_with_three_callers",
    "facing_open_with_four_callers",
    "facing_three_bet",
    "facing_cold_three_bet",
    "facing_squeeze_after_call",
    "facing_four_bet",
    "facing_cold_four_bet",
]


@dataclass(frozen=True)
class PreflopChartContext:
    scenario: PreflopChartScenario
    hero_position: Position
    limper_position: Position | None = None
    limper_positions: tuple[Position, ...] = ()
    limp_size: float | None = None
    opener_position: Position | None = None
    opening_raise_size: float | None = None
    latest_aggressor_position: Position | None = None
    latest_raise_size: float | None = None
    caller_positions: tuple[Position, ...] = ()
    hero_prior_commitment: float | None = None
    hero_isolation_raise_size: float | None = None
    hero_three_bet_size: float | None = None


def supports_preflop_chart(request: RecommendationRequest) -> bool:
    return resolve_preflop_chart_context(request) is not None


def requires_hero_stack_for_preflop_chart(state: CanonicalState) -> bool:
    """Return whether hero_stack is the only missing chart-specific input."""
    if (
        state.hero_stack is not None
        or len(state.preflop_action_history) not in {2, 3}
    ):
        return False

    assumed_hero_stack = max(
        state.effective_stack or 0,
        state.current_bet or 0,
        1.0,
    )
    candidate = RecommendationRequest(
        state=state.model_copy(update={"hero_stack": assumed_hero_stack}),
        provider="local_solver",
    )
    context = resolve_preflop_chart_context(candidate)
    return context is not None and context.scenario in {
        "facing_three_bet",
        "facing_cold_three_bet",
        "facing_squeeze_after_call",
        "facing_isolation_raise_after_limp",
        "facing_limp_reraise",
        "facing_four_bet",
        "facing_cold_four_bet",
    }


def resolve_preflop_chart_context(
    request: RecommendationRequest,
) -> PreflopChartContext | None:
    state = request.state
    if state.street != "preflop" or len(state.hero_cards) != 2 or state.board_cards:
        return None
    if state.players_in_hand is None or not 2 <= state.players_in_hand <= 6:
        return None
    if state.effective_stack is None or state.effective_stack <= 0:
        return None
    position = normalize_position(state.hero_position)
    if position is None:
        return None

    current_bet = state.current_bet or 0
    if current_bet <= 0:
        if state.preflop_action_history:
            return _structured_big_blind_limp_context(state, position)
        if (
            state.facing_action is not None
            or state.preflop_opener_position is not None
            or state.preflop_open_size is not None
            or _has_raise_action(state.action_context)
            or _has_unsupported_action_history(state.action_context)
        ):
            return None
        pot_size = state.pot_size or 0
        if not MIN_BLIND_ONLY_POT_BB <= pot_size <= MAX_BLIND_ONLY_POT_BB:
            return None
        return PreflopChartContext(
            scenario=(
                "big_blind_option"
                if position == "big_blind"
                else "first_in"
            ),
            hero_position=position,
        )
    if state.facing_action != "raise":
        return None

    if state.preflop_action_history:
        return _structured_preflop_context(request, position)
    if _has_unsupported_action_history(state.action_context):
        return None

    opener_position = opening_raise_position(
        state.action_context,
        state.preflop_opener_position,
    )
    if opener_position is None:
        return None
    if POSITION_ACTION_ORDER[opener_position] >= POSITION_ACTION_ORDER[position]:
        return None
    opener_size = resolve_opening_raise_size(
        action_context=state.action_context,
        explicit_size=state.preflop_open_size,
        amount_to_call=current_bet,
        hero_position=position,
    )
    expected_open_size = current_bet + POSTED_BLIND_BB[position]
    if not MIN_SINGLE_OPEN_SIZE_BB <= opener_size <= MAX_SINGLE_OPEN_SIZE_BB:
        return None
    if abs(opener_size - expected_open_size) > MONEY_TOLERANCE_BB:
        return None

    pot_size = state.pot_size or 0
    dead_money = pot_size - current_bet
    blind_adjustment = POSTED_BLIND_BB[position] - POSTED_BLIND_BB[opener_position]
    if not (
        MIN_BLIND_ONLY_POT_BB + blind_adjustment
        <= dead_money
        <= MAX_BLIND_ONLY_POT_BB + blind_adjustment
    ):
        return None
    return PreflopChartContext(
        scenario="facing_open_raise",
        hero_position=position,
        opener_position=opener_position,
        opening_raise_size=opener_size,
        latest_aggressor_position=opener_position,
        latest_raise_size=opener_size,
    )


def _structured_big_blind_limp_context(
    state: CanonicalState,
    hero_position: Position,
) -> PreflopChartContext | None:
    history = state.preflop_action_history
    if (
        hero_position != "big_blind"
        or state.facing_action is not None
        or state.preflop_opener_position is not None
        or state.preflop_open_size is not None
        or len(history) not in {1, 2, 3, 4, 5}
        or state.players_in_hand != len(history) + 1
    ):
        return None

    limper_positions: tuple[Position, ...] = tuple(
        action.actor for action in history
    )
    if (
        len(set(limper_positions)) != len(limper_positions)
        or any(action.action != "call" for action in history)
        or any(
            POSITION_ACTION_ORDER[position]
            >= POSITION_ACTION_ORDER[hero_position]
            for position in limper_positions
        )
        or any(
            POSITION_ACTION_ORDER[before]
            >= POSITION_ACTION_ORDER[after]
            for before, after in pairwise(limper_positions)
        )
        or any(
            abs(action.amount - 1.0) > MONEY_TOLERANCE_BB
            for action in history
        )
        or not _pot_matches_actions(
            state.pot_size,
            tuple((action.actor, action.amount) for action in history),
        )
    ):
        return None
    limp_scenarios: dict[int, PreflopChartScenario] = {
        1: "heads_up_limp_big_blind",
        2: "two_limpers_big_blind",
        3: "three_limpers_big_blind",
        4: "four_limpers_big_blind",
        5: "five_limpers_big_blind",
    }
    return PreflopChartContext(
        scenario=limp_scenarios[len(history)],
        hero_position=hero_position,
        limper_position=(limper_positions[0] if len(history) == 1 else None),
        limper_positions=limper_positions,
        limp_size=history[0].amount,
    )


def _structured_preflop_context(
    request: RecommendationRequest,
    hero_position: Position,
) -> PreflopChartContext | None:
    state = request.state
    history = state.preflop_action_history
    if len(history) not in {1, 2, 3, 4, 5}:
        return None
    if history[0].action == "call":
        return _structured_isolation_raise_context(state, hero_position)
    if history[0].action != "raise":
        return None

    opener = history[0]
    opener_position: Position = opener.actor
    opener_size = opener.amount
    if not MIN_SINGLE_OPEN_SIZE_BB <= opener_size <= MAX_SINGLE_OPEN_SIZE_BB:
        return None
    if (
        state.preflop_opener_position is not None
        and normalize_position(state.preflop_opener_position) != opener_position
    ):
        return None
    if (
        state.preflop_open_size is not None
        and abs(state.preflop_open_size - opener_size) > MONEY_TOLERANCE_BB
    ):
        return None

    if len(history) == 1:
        if (
            opener_position == hero_position
            or POSITION_ACTION_ORDER[opener_position]
            >= POSITION_ACTION_ORDER[hero_position]
        ):
            return None
        if not _amount_to_call_matches(
            state.current_bet,
            opener_size - POSTED_BLIND_BB[hero_position],
        ):
            return None
        if not _pot_matches_actions(
            state.pot_size,
            ((opener_position, opener_size),),
        ):
            return None
        return PreflopChartContext(
            scenario="facing_open_raise",
            hero_position=hero_position,
            opener_position=opener_position,
            opening_raise_size=opener_size,
            latest_aggressor_position=opener_position,
            latest_raise_size=opener_size,
        )

    second_action = history[1]
    if second_action.action == "call":
        if len(history) == 3 and history[2].action == "raise":
            hero_call = second_action
            squeeze = history[2]
            squeezer_position: Position = squeeze.actor
            minimum_squeeze = opener_size + max(1.0, opener_size - 1.0)
            represented_positions = (
                opener_position,
                hero_position,
                squeezer_position,
            )
            if (
                state.players_in_hand != 2
                or hero_call.actor != hero_position
                or len(set(represented_positions)) != len(represented_positions)
                or any(
                    POSITION_ACTION_ORDER[before]
                    >= POSITION_ACTION_ORDER[after]
                    for before, after in pairwise(represented_positions)
                )
                or abs(hero_call.amount - opener_size) > MONEY_TOLERANCE_BB
                or squeeze.amount + MONEY_TOLERANCE_BB < minimum_squeeze
                or squeeze.amount > (
                    opener_size * MAX_SUPPORTED_THREE_BET_TO_OPEN_RATIO
                    + MONEY_TOLERANCE_BB
                )
                or not _amount_to_call_matches(
                    state.current_bet,
                    squeeze.amount - hero_call.amount,
                )
                or not _stack_state_supports_raise_response(state)
                or not _pot_matches_actions(
                    state.pot_size,
                    (
                        (opener_position, opener_size),
                        (hero_position, hero_call.amount),
                        (squeezer_position, squeeze.amount),
                    ),
                )
            ):
                return None
            return PreflopChartContext(
                scenario="facing_squeeze_after_call",
                hero_position=hero_position,
                opener_position=opener_position,
                opening_raise_size=opener_size,
                latest_aggressor_position=squeezer_position,
                latest_raise_size=squeeze.amount,
                hero_prior_commitment=hero_call.amount,
            )
        caller_actions = history[1:]
        caller_positions: tuple[Position, ...] = tuple(
            action.actor for action in caller_actions
        )
        represented_positions = (
            opener_position,
            *caller_positions,
            hero_position,
        )
        if (
            len(caller_actions) not in {1, 2, 3, 4}
            or any(action.action != "call" for action in caller_actions)
            or state.players_in_hand != len(caller_actions) + 2
            or opener_position == hero_position
            or len(set(represented_positions)) != len(represented_positions)
            or any(
                POSITION_ACTION_ORDER[before]
                >= POSITION_ACTION_ORDER[after]
                for before, after in pairwise(represented_positions)
            )
            or any(
                abs(action.amount - opener_size) > MONEY_TOLERANCE_BB
                for action in caller_actions
            )
        ):
            return None
        if not _amount_to_call_matches(
            state.current_bet,
            opener_size - POSTED_BLIND_BB[hero_position],
        ):
            return None
        if not _pot_matches_actions(
            state.pot_size,
            (
                (opener_position, opener_size),
                *(
                    (action.actor, action.amount)
                    for action in caller_actions
                ),
            ),
        ):
            return None
        caller_scenarios: dict[int, PreflopChartScenario] = {
            1: "facing_open_with_caller",
            2: "facing_open_with_callers",
            3: "facing_open_with_three_callers",
            4: "facing_open_with_four_callers",
        }
        return PreflopChartContext(
            scenario=caller_scenarios[len(caller_positions)],
            hero_position=hero_position,
            opener_position=opener_position,
            opening_raise_size=opener_size,
            latest_aggressor_position=opener_position,
            latest_raise_size=opener_size,
            caller_positions=caller_positions,
        )
    if len(history) >= 4:
        return None
    if second_action.action != "raise":
        return None

    three_bet = second_action
    three_bettor_position: Position = three_bet.actor
    minimum_full_raise = opener_size + max(1.0, opener_size - 1.0)
    if (
        three_bet.amount + MONEY_TOLERANCE_BB < minimum_full_raise
        or three_bet.amount > (
            opener_size * MAX_SUPPORTED_THREE_BET_TO_OPEN_RATIO
            + MONEY_TOLERANCE_BB
        )
    ):
        return None

    if len(history) == 3:
        four_bet = history[2]
        four_bettor_position: Position = four_bet.actor
        minimum_four_bet = three_bet.amount + (three_bet.amount - opener_size)
        cold_four_bet = four_bettor_position != opener_position
        if cold_four_bet:
            valid_four_bettor = (
                POSITION_ACTION_ORDER[hero_position]
                < POSITION_ACTION_ORDER[four_bettor_position]
            )
            pot_commitments = (
                (opener_position, opener_size),
                (hero_position, three_bet.amount),
                (four_bettor_position, four_bet.amount),
            )
        else:
            valid_four_bettor = True
            pot_commitments = (
                (hero_position, three_bet.amount),
                (opener_position, four_bet.amount),
            )
        if (
            state.players_in_hand != 2
            or opener_position == hero_position
            or three_bettor_position != hero_position
            or POSITION_ACTION_ORDER[opener_position]
            >= POSITION_ACTION_ORDER[hero_position]
            or four_bet.action != "raise"
            or four_bettor_position == hero_position
            or not valid_four_bettor
            or four_bet.amount + MONEY_TOLERANCE_BB < minimum_four_bet
            or four_bet.amount > (
                three_bet.amount * MAX_SUPPORTED_FOUR_BET_TO_THREE_BET_RATIO
                + MONEY_TOLERANCE_BB
            )
            or not _amount_to_call_matches(
                state.current_bet,
                four_bet.amount - three_bet.amount,
            )
            or not _stack_state_supports_raise_response(state)
            or not _pot_matches_actions(state.pot_size, pot_commitments)
        ):
            return None
        return PreflopChartContext(
            scenario=(
                "facing_cold_four_bet"
                if cold_four_bet
                else "facing_four_bet"
            ),
            hero_position=hero_position,
            opener_position=opener_position,
            opening_raise_size=opener_size,
            latest_aggressor_position=four_bettor_position,
            latest_raise_size=four_bet.amount,
            hero_three_bet_size=three_bet.amount,
        )

    if opener_position == hero_position:
        if (
            three_bettor_position == hero_position
            or POSITION_ACTION_ORDER[three_bettor_position]
            <= POSITION_ACTION_ORDER[hero_position]
        ):
            return None
        scenario: PreflopChartScenario = "facing_three_bet"
        expected_call = three_bet.amount - opener_size
    else:
        if (
            state.players_in_hand != 3
            or POSITION_ACTION_ORDER[opener_position]
            >= POSITION_ACTION_ORDER[three_bettor_position]
            or POSITION_ACTION_ORDER[three_bettor_position]
            >= POSITION_ACTION_ORDER[hero_position]
        ):
            return None
        scenario = "facing_cold_three_bet"
        expected_call = three_bet.amount - POSTED_BLIND_BB[hero_position]

    if not _amount_to_call_matches(state.current_bet, expected_call):
        return None
    if not _stack_state_supports_raise_response(state):
        return None
    if not _pot_matches_actions(
        state.pot_size,
        (
            (opener_position, opener_size),
            (three_bettor_position, three_bet.amount),
        ),
    ):
        return None
    return PreflopChartContext(
        scenario=scenario,
        hero_position=hero_position,
        opener_position=opener_position,
        opening_raise_size=opener_size,
        latest_aggressor_position=three_bettor_position,
        latest_raise_size=three_bet.amount,
    )


def _structured_isolation_raise_context(
    state: CanonicalState,
    hero_position: Position,
) -> PreflopChartContext | None:
    history = state.preflop_action_history
    if len(history) == 3:
        return _structured_limp_reraise_context(state, hero_position)
    if len(history) != 2 or state.players_in_hand != 2:
        return None

    limp, isolation_raise = history
    raiser_position: Position = isolation_raise.actor
    if (
        limp.actor != hero_position
        or limp.action != "call"
        or abs(limp.amount - 1.0) > MONEY_TOLERANCE_BB
        or isolation_raise.action != "raise"
        or raiser_position == hero_position
        or POSITION_ACTION_ORDER[raiser_position]
        <= POSITION_ACTION_ORDER[hero_position]
        or isolation_raise.amount + MONEY_TOLERANCE_BB < 2.0
        or isolation_raise.amount
        > MAX_SUPPORTED_ISOLATION_RAISE_SIZE_BB + MONEY_TOLERANCE_BB
        or not _amount_to_call_matches(
            state.current_bet,
            isolation_raise.amount - limp.amount,
        )
        or not _stack_state_supports_raise_response(state)
        or not _pot_matches_actions(
            state.pot_size,
            (
                (hero_position, limp.amount),
                (raiser_position, isolation_raise.amount),
            ),
        )
    ):
        return None
    return PreflopChartContext(
        scenario="facing_isolation_raise_after_limp",
        hero_position=hero_position,
        limper_position=hero_position,
        limp_size=limp.amount,
        latest_aggressor_position=raiser_position,
        latest_raise_size=isolation_raise.amount,
        hero_prior_commitment=limp.amount,
    )


def _structured_limp_reraise_context(
    state: CanonicalState,
    hero_position: Position,
) -> PreflopChartContext | None:
    limp, isolation_raise, limp_reraise = state.preflop_action_history
    limper_position: Position = limp.actor
    isolation_raise_size = isolation_raise.amount
    limp_reraise_size = limp_reraise.amount
    minimum_limp_reraise = isolation_raise_size + max(
        1.0,
        isolation_raise_size - limp.amount,
    )
    if (
        state.players_in_hand != 2
        or limp.action != "call"
        or limper_position == hero_position
        or POSITION_ACTION_ORDER[limper_position]
        >= POSITION_ACTION_ORDER[hero_position]
        or abs(limp.amount - 1.0) > MONEY_TOLERANCE_BB
        or isolation_raise.actor != hero_position
        or isolation_raise.action != "raise"
        or isolation_raise_size + MONEY_TOLERANCE_BB < 2.0
        or isolation_raise_size
        > MAX_SUPPORTED_ISOLATION_RAISE_SIZE_BB + MONEY_TOLERANCE_BB
        or limp_reraise.actor != limper_position
        or limp_reraise.action != "raise"
        or limp_reraise_size + MONEY_TOLERANCE_BB < minimum_limp_reraise
        or limp_reraise_size
        > (
            isolation_raise_size
            * MAX_SUPPORTED_LIMP_RERAISE_TO_ISOLATION_RATIO
            + MONEY_TOLERANCE_BB
        )
        or not _amount_to_call_matches(
            state.current_bet,
            limp_reraise_size - isolation_raise_size,
        )
        or not _stack_state_supports_raise_response(state)
        or not _pot_matches_actions(
            state.pot_size,
            (
                (hero_position, isolation_raise_size),
                (limper_position, limp_reraise_size),
            ),
        )
    ):
        return None
    return PreflopChartContext(
        scenario="facing_limp_reraise",
        hero_position=hero_position,
        limper_position=limper_position,
        limp_size=limp.amount,
        latest_aggressor_position=limper_position,
        latest_raise_size=limp_reraise_size,
        hero_prior_commitment=isolation_raise_size,
        hero_isolation_raise_size=isolation_raise_size,
    )


def _stack_state_supports_raise_response(state: CanonicalState) -> bool:
    return (
        state.hero_stack is not None
        and state.hero_stack > 0
        and state.effective_stack is not None
        and state.effective_stack <= state.hero_stack + MONEY_TOLERANCE_BB
        and (state.current_bet or 0) <= state.hero_stack + MONEY_TOLERANCE_BB
    )


def _amount_to_call_matches(actual: float | None, expected: float) -> bool:
    return actual is not None and abs(actual - expected) <= MONEY_TOLERANCE_BB


def _pot_matches_actions(
    pot_size: float | None,
    commitments: tuple[tuple[Position, float], ...],
) -> bool:
    if pot_size is None:
        return False
    replaced_blinds = sum(POSTED_BLIND_BB[position] for position, _ in commitments)
    committed = sum(amount for _, amount in commitments)
    minimum = MIN_BLIND_ONLY_POT_BB - replaced_blinds + committed
    maximum = MAX_BLIND_ONLY_POT_BB - replaced_blinds + committed
    return minimum - MONEY_TOLERANCE_BB <= pot_size <= maximum + MONEY_TOLERANCE_BB


def pot_matches_preflop_actions(
    pot_size: float | None,
    commitments: tuple[tuple[Position, float], ...],
) -> bool:
    return _pot_matches_actions(pot_size, commitments)


def normalize_position(value: str | None) -> Position | None:
    if value is None:
        return None
    normalized = " ".join(value.lower().replace("_", " ").replace("-", " ").split())
    return POSITION_ALIASES.get(normalized)


def opening_raise_size(action_context: str | None) -> float | None:
    if action_context is None:
        return None
    normalized = " ".join(action_context.lower().replace("-", " ").split())
    match = POSITION_OPEN_RAISE_SIZE_PATTERN.search(normalized)
    return float(match.group("size")) if match is not None else None


def resolve_opening_raise_size(
    *,
    action_context: str | None,
    explicit_size: float | None,
    amount_to_call: float,
    hero_position: Position,
) -> float:
    if explicit_size is not None:
        return explicit_size
    parsed_size = opening_raise_size(action_context)
    if parsed_size is not None:
        return parsed_size
    return amount_to_call + POSTED_BLIND_BB[hero_position]


def _has_unsupported_action_history(action_context: str | None) -> bool:
    if action_context is None:
        return False
    normalized = " ".join(action_context.lower().replace("-", " ").split())
    raise_count = len(RAISE_ACTION_PATTERN.findall(normalized))
    return "limp" in normalized or raise_count > 1 or bool(
        CALLER_ACTION_PATTERN.search(normalized)
        or LATER_RAISE_PATTERN.search(normalized)
        or NON_OPEN_AGGRESSION_PATTERN.search(normalized)
    )


def opening_raise_position(
    action_context: str | None,
    explicit_position: str | None = None,
) -> Position | None:
    if explicit_position is not None:
        return normalize_position(explicit_position)
    if action_context is None:
        return None
    normalized = " ".join(action_context.lower().replace("-", " ").split())
    for pattern in POSITION_OPEN_RAISE_PATTERNS:
        match = pattern.search(normalized)
        if match is not None:
            return normalize_position(match.group("position"))
    return None


def _has_raise_action(action_context: str | None) -> bool:
    if action_context is None:
        return False
    normalized = " ".join(action_context.lower().replace("-", " ").split())
    return bool(RAISE_ACTION_PATTERN.search(normalized))
