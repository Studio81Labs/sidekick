from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.domain.poker import CanonicalState
from app.solvers.preflop_context import (
    MAX_SUPPORTED_FOUR_BET_TO_THREE_BET_RATIO,
    MAX_SUPPORTED_ISOLATION_RAISE_SIZE_BB,
    MAX_SUPPORTED_LIMP_RERAISE_TO_ISOLATION_RATIO,
    MAX_SUPPORTED_THREE_BET_TO_OPEN_RATIO,
    MAX_SINGLE_OPEN_SIZE_BB,
    MIN_SINGLE_OPEN_SIZE_BB,
    MONEY_TOLERANCE_BB,
    POSITION_ACTION_ORDER,
    Position,
    normalize_position,
    pot_matches_preflop_actions,
)


RangeSource = Literal[
    "configured",
    "preflop_chart_limped_pot",
    "preflop_chart_isolation_raised_pot",
    "preflop_chart_limp_reraised_pot",
    "preflop_chart_single_raised_pot",
    "preflop_chart_three_bet_pot",
    "preflop_chart_cold_three_bet_pot",
    "preflop_chart_squeeze_pot",
    "preflop_chart_four_bet_pot",
    "preflop_chart_cold_four_bet_pot",
]
StackDepthSource = Literal["reconstructed", "standard_assumption"]

STANDARD_CONTEXTUAL_STACK_BB = 100.0
POSTFLOP_POSITION_ORDER: dict[Position, int] = {
    "small_blind": 0,
    "big_blind": 1,
    "utg": 2,
    "hijack": 3,
    "cutoff": 4,
    "button": 5,
}


@dataclass(frozen=True)
class PostflopRangeSelection:
    oop_range: str
    ip_range: str
    source: RangeSource = "configured"
    context: dict[str, str | float] = field(default_factory=dict)


def select_postflop_ranges(
    state: CanonicalState,
    *,
    hero_relative_position: Literal["ip", "oop"] | None,
    configured_oop_range: str,
    configured_ip_range: str,
    contextual_enabled: bool,
) -> PostflopRangeSelection:
    configured = PostflopRangeSelection(
        oop_range=configured_oop_range,
        ip_range=configured_ip_range,
    )
    if (
        not contextual_enabled
        or hero_relative_position is None
        or state.street not in {"flop", "turn", "river"}
    ):
        return configured

    limped_context = _limped_pot_context(
        state,
        hero_relative_position,
    )
    if limped_context is not None:
        selection = _limped_pot_selection(
            state,
            hero_relative_position,
            limped_context,
        )
        if selection is not None:
            return selection

    isolation_raised_context = _isolation_raised_pot_context(
        state,
        hero_relative_position,
    )
    if isolation_raised_context is not None:
        selection = _isolation_raised_pot_selection(
            state,
            hero_relative_position,
            isolation_raised_context,
        )
        if selection is not None:
            return selection

    limp_reraised_context = _limp_reraised_pot_context(
        state,
        hero_relative_position,
    )
    if limp_reraised_context is not None:
        selection = _limp_reraised_pot_selection(
            state,
            hero_relative_position,
            limp_reraised_context,
        )
        if selection is not None:
            return selection

    single_raised_context = _single_raised_pot_context(
        state,
        hero_relative_position,
    )
    if single_raised_context is not None:
        selection = _single_raised_pot_selection(
            state,
            hero_relative_position,
            single_raised_context,
        )
        if selection is not None:
            return selection

    three_bet_context = _three_bet_pot_context(
        state,
        hero_relative_position,
    )
    if three_bet_context is not None:
        selection = _three_bet_pot_selection(
            state,
            hero_relative_position,
            three_bet_context,
        )
        if selection is not None:
            return selection

    cold_three_bet_context = _cold_three_bet_pot_context(
        state,
        hero_relative_position,
    )
    if cold_three_bet_context is not None:
        selection = _cold_three_bet_pot_selection(
            state,
            hero_relative_position,
            cold_three_bet_context,
        )
        if selection is not None:
            return selection

    squeeze_context = _squeeze_pot_context(
        state,
        hero_relative_position,
    )
    if squeeze_context is not None:
        selection = _squeeze_pot_selection(
            state,
            hero_relative_position,
            squeeze_context,
        )
        if selection is not None:
            return selection

    cold_four_bet_context = _cold_four_bet_pot_context(
        state,
        hero_relative_position,
    )
    if cold_four_bet_context is not None:
        selection = _cold_four_bet_pot_selection(
            state,
            hero_relative_position,
            cold_four_bet_context,
        )
        if selection is not None:
            return selection

    four_bet_context = _four_bet_pot_context(
        state,
        hero_relative_position,
    )
    if four_bet_context is not None:
        selection = _four_bet_pot_selection(
            state,
            hero_relative_position,
            four_bet_context,
        )
        if selection is not None:
            return selection
    return configured


def resolve_squeeze_pot_relative_position(
    state: CanonicalState,
) -> Literal["ip", "oop"] | None:
    """Resolve an otherwise ambiguous blind pair from an exact squeeze line."""
    hero_position = normalize_position(state.hero_position)
    opponent_position = normalize_position(state.opponent_position)
    if {hero_position, opponent_position} != {"small_blind", "big_blind"}:
        return None

    hero_relative_position: Literal["ip", "oop"] = (
        "ip" if hero_position == "big_blind" else "oop"
    )
    if _squeeze_pot_context(state, hero_relative_position) is None:
        return None
    return hero_relative_position


def resolve_isolation_raised_pot_relative_position(
    state: CanonicalState,
) -> Literal["ip", "oop"] | None:
    """Resolve a blind pair from an exact six-max isolation-raised line."""
    hero_position = normalize_position(state.hero_position)
    opponent_position = normalize_position(state.opponent_position)
    if {hero_position, opponent_position} != {"small_blind", "big_blind"}:
        return None

    hero_relative_position: Literal["ip", "oop"] = (
        "ip" if hero_position == "big_blind" else "oop"
    )
    if _isolation_raised_pot_context(state, hero_relative_position) is None:
        return None
    return hero_relative_position


def resolve_limp_reraised_pot_relative_position(
    state: CanonicalState,
) -> Literal["ip", "oop"] | None:
    """Resolve relative position from an exact called limp-reraise line."""
    if len(state.preflop_action_history) != 4:
        return None
    limp_action, isolation_action, _, _ = state.preflop_action_history
    limper = normalize_position(limp_action.actor)
    isolation_raiser = normalize_position(isolation_action.actor)
    if limper is None or isolation_raiser is None or limper == isolation_raiser:
        return None
    ordered_positions = _ordered_postflop_positions(
        limper,
        isolation_raiser,
    )
    reviewed_positions = _reviewed_positions_for_exact_order(
        state,
        *ordered_positions,
    )
    if reviewed_positions is None:
        return None
    _, _, hero_relative_position = reviewed_positions
    if _limp_reraised_pot_context(state, hero_relative_position) is None:
        return None
    return hero_relative_position


def resolve_cold_four_bet_pot_relative_position(
    state: CanonicalState,
) -> Literal["ip", "oop"] | None:
    """Resolve an otherwise ambiguous blind pair from an exact cold 4-bet line."""
    hero_position = normalize_position(state.hero_position)
    opponent_position = normalize_position(state.opponent_position)
    if {hero_position, opponent_position} != {"small_blind", "big_blind"}:
        return None

    hero_relative_position: Literal["ip", "oop"] = (
        "ip" if hero_position == "big_blind" else "oop"
    )
    if _cold_four_bet_pot_context(state, hero_relative_position) is None:
        return None
    return hero_relative_position


def _limped_pot_selection(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    context: tuple[Position, float, tuple[Position, Position]],
) -> PostflopRangeSelection | None:
    limper, limp_size, participant_positions = context
    from app.solvers.preflop_chart import (
        LIMP_RESPONSE_POLICIES,
        LIMP_RESPONSE_POLICY_NAME,
        POSITION_POLICIES,
        adjusted_limp_raise_fraction,
        adjusted_open_fraction,
        policy_for_stack_depth,
    )

    limper_policy = POSITION_POLICIES.get(limper)
    big_blind_policy = LIMP_RESPONSE_POLICIES.get(limper)
    starting_effective_stack, stack_depth_source = _contextual_stack_depth(
        state,
        hero_relative_position,
        final_preflop_commitment=limp_size,
    )
    stack_policy = policy_for_stack_depth(starting_effective_stack)
    if (
        limper_policy is None
        or limper_policy.open_fraction <= 0
        or big_blind_policy is None
        or stack_policy is None
    ):
        return None

    limper_fraction = adjusted_open_fraction(limper_policy, stack_policy)
    big_blind_raise_fraction = adjusted_limp_raise_fraction(
        big_blind_policy,
        stack_policy,
    )
    limper_range = _range_for_policy_band(limper_fraction)
    big_blind_check_range = _range_for_policy_band(
        1.0,
        minimum_exclusive=big_blind_raise_fraction,
    )
    if not limper_range or not big_blind_check_range:
        return None

    return _selection_for_ranges(
        state,
        hero_relative_position,
        ranges_by_position={
            limper: limper_range,
            "big_blind": big_blind_check_range,
        },
        source="preflop_chart_limped_pot",
        participant_positions=participant_positions,
        context={
            "scenario": "limped_pot",
            "limper_position": limper,
            "big_blind_position": "big_blind",
            "limp_size_bb": limp_size,
            "limper_range_model": "stack_adjusted_first_in_proxy",
            "limp_response_policy": LIMP_RESPONSE_POLICY_NAME,
            "stack_depth_policy": stack_policy.name,
            "starting_effective_stack_bb": starting_effective_stack,
            "stack_depth_source": stack_depth_source,
            "limper_base_fraction": limper_policy.open_fraction,
            "limper_fraction": limper_fraction,
            "big_blind_base_raise_fraction": big_blind_policy.raise_fraction,
            "big_blind_raise_fraction": big_blind_raise_fraction,
        },
    )


def _single_raised_pot_selection(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    context: tuple[Position, Position, float],
) -> PostflopRangeSelection | None:
    opener, caller, opening_size = context
    from app.solvers.preflop_chart import (
        DEFENSE_POLICIES,
        POSITION_POLICIES,
        adjusted_defense_policy,
        adjusted_open_fraction,
        policy_for_open_size,
        policy_for_stack_depth,
    )

    opener_policy = POSITION_POLICIES[opener]
    base_opener_fraction = opener_policy.open_fraction
    base_defense = DEFENSE_POLICIES.get((opener, caller))
    size_policy = policy_for_open_size(opening_size)
    starting_effective_stack, stack_depth_source = _contextual_stack_depth(
        state,
        hero_relative_position,
        final_preflop_commitment=opening_size,
    )
    stack_policy = policy_for_stack_depth(starting_effective_stack)
    if (
        base_opener_fraction <= 0
        or base_defense is None
        or size_policy is None
        or stack_policy is None
    ):
        return None
    opener_fraction = adjusted_open_fraction(opener_policy, stack_policy)
    defense = adjusted_defense_policy(
        base_defense,
        size_policy,
        stack_policy,
    )

    opener_range = _range_for_policy_band(opener_fraction)
    caller_range = _range_for_policy_band(
        defense.continue_fraction,
        minimum_exclusive=defense.reraise_fraction,
    )
    if not opener_range or not caller_range:
        return None

    return _selection_for_ranges(
        state,
        hero_relative_position,
        ranges_by_position={opener: opener_range, caller: caller_range},
        source="preflop_chart_single_raised_pot",
        context={
            "scenario": "single_raised_pot",
            "opener_position": opener,
            "caller_position": caller,
            "opening_size_bb": opening_size,
            "open_size_policy": size_policy.name,
            "stack_depth_policy": stack_policy.name,
            "starting_effective_stack_bb": starting_effective_stack,
            "stack_depth_source": stack_depth_source,
            "opener_base_fraction": base_opener_fraction,
            "opener_fraction": opener_fraction,
            "caller_base_continue_fraction": base_defense.continue_fraction,
            "caller_base_reraise_fraction": base_defense.reraise_fraction,
            "caller_continue_fraction": defense.continue_fraction,
            "caller_reraise_fraction": defense.reraise_fraction,
        },
    )


def _isolation_raised_pot_selection(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    context: tuple[Position, float, float, tuple[Position, Position]],
) -> PostflopRangeSelection | None:
    limper, limp_size, isolation_raise_size, participant_positions = context
    from app.solvers.preflop_chart import (
        ISOLATION_RESPONSE_POLICIES,
        ISOLATION_RESPONSE_POLICY_NAME,
        LIMP_RESPONSE_POLICIES,
        LIMP_RESPONSE_POLICY_NAME,
        adjusted_defense_policy,
        adjusted_limp_raise_fraction,
        policy_for_isolation_raise_size,
        policy_for_stack_depth,
    )

    base_isolation_policy = LIMP_RESPONSE_POLICIES.get(limper)
    base_limper_defense = ISOLATION_RESPONSE_POLICIES.get(
        (limper, "big_blind")
    )
    size_policy = policy_for_isolation_raise_size(isolation_raise_size)
    starting_effective_stack, stack_depth_source = _contextual_stack_depth(
        state,
        hero_relative_position,
        final_preflop_commitment=isolation_raise_size,
    )
    stack_policy = policy_for_stack_depth(starting_effective_stack)
    if (
        base_isolation_policy is None
        or base_limper_defense is None
        or size_policy is None
        or stack_policy is None
    ):
        return None

    isolation_fraction = adjusted_limp_raise_fraction(
        base_isolation_policy,
        stack_policy,
    )
    limper_defense = adjusted_defense_policy(
        base_limper_defense,
        size_policy,
        stack_policy,
    )
    isolation_range = _range_for_policy_band(isolation_fraction)
    limper_call_range = _range_for_policy_band(
        limper_defense.continue_fraction,
        minimum_exclusive=limper_defense.reraise_fraction,
    )
    if not isolation_range or not limper_call_range:
        return None

    return _selection_for_ranges(
        state,
        hero_relative_position,
        ranges_by_position={
            limper: limper_call_range,
            "big_blind": isolation_range,
        },
        source="preflop_chart_isolation_raised_pot",
        participant_positions=participant_positions,
        context={
            "scenario": "isolation_raised_pot",
            "limper_position": limper,
            "isolation_raiser_position": "big_blind",
            "limp_size_bb": limp_size,
            "isolation_raise_size_bb": isolation_raise_size,
            "limp_response_policy": LIMP_RESPONSE_POLICY_NAME,
            "isolation_response_policy": ISOLATION_RESPONSE_POLICY_NAME,
            "isolation_raise_size_policy": size_policy.name,
            "stack_depth_policy": stack_policy.name,
            "starting_effective_stack_bb": starting_effective_stack,
            "stack_depth_source": stack_depth_source,
            "isolation_raiser_base_fraction": (
                base_isolation_policy.raise_fraction
            ),
            "isolation_raiser_fraction": isolation_fraction,
            "limper_base_continue_fraction": (
                base_limper_defense.continue_fraction
            ),
            "limper_base_reraise_fraction": (
                base_limper_defense.reraise_fraction
            ),
            "limper_continue_fraction": limper_defense.continue_fraction,
            "limper_reraise_fraction": limper_defense.reraise_fraction,
        },
    )


def _limp_reraised_pot_selection(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    context: tuple[
        Position,
        Position,
        float,
        float,
        float,
        tuple[Position, Position],
    ],
) -> PostflopRangeSelection | None:
    (
        limper,
        isolation_raiser,
        limp_size,
        isolation_raise_size,
        limp_reraise_size,
        participant_positions,
    ) = context
    from app.solvers.preflop_chart import (
        ISOLATION_RESPONSE_POLICIES,
        ISOLATION_RESPONSE_POLICY_NAME,
        LIMP_RERAISE_RESPONSE_POLICIES,
        LIMP_RERAISE_RESPONSE_POLICY_NAME,
        adjusted_defense_policy,
        adjusted_three_bet_defense_policy,
        policy_for_isolation_raise_size,
        policy_for_limp_reraise_size,
        policy_for_stack_depth,
    )

    base_limper_defense = ISOLATION_RESPONSE_POLICIES.get(
        (limper, isolation_raiser)
    )
    base_isolation_raiser_defense = LIMP_RERAISE_RESPONSE_POLICIES.get(
        (limper, isolation_raiser)
    )
    isolation_size_policy = policy_for_isolation_raise_size(
        isolation_raise_size
    )
    limp_reraise_size_policy = policy_for_limp_reraise_size(
        limp_reraise_size / isolation_raise_size
    )
    starting_effective_stack, stack_depth_source = _contextual_stack_depth(
        state,
        hero_relative_position,
        final_preflop_commitment=limp_reraise_size,
    )
    stack_policy = policy_for_stack_depth(starting_effective_stack)
    if (
        base_limper_defense is None
        or base_isolation_raiser_defense is None
        or isolation_size_policy is None
        or limp_reraise_size_policy is None
        or stack_policy is None
    ):
        return None

    limper_defense = adjusted_defense_policy(
        base_limper_defense,
        isolation_size_policy,
        stack_policy,
    )
    isolation_raiser_defense = adjusted_three_bet_defense_policy(
        base_isolation_raiser_defense,
        limp_reraise_size_policy,
        stack_policy,
    )
    limper_reraise_range = _range_for_policy_band(
        limper_defense.reraise_fraction
    )
    isolation_raiser_call_range = _range_for_policy_band(
        isolation_raiser_defense.continue_fraction,
        minimum_exclusive=isolation_raiser_defense.four_bet_fraction,
    )
    if not limper_reraise_range or not isolation_raiser_call_range:
        return None

    return _selection_for_ranges(
        state,
        hero_relative_position,
        ranges_by_position={
            limper: limper_reraise_range,
            isolation_raiser: isolation_raiser_call_range,
        },
        source="preflop_chart_limp_reraised_pot",
        participant_positions=participant_positions,
        context={
            "scenario": "limp_reraised_pot",
            "limper_position": limper,
            "isolation_raiser_position": isolation_raiser,
            "limp_reraiser_position": limper,
            "limp_size_bb": limp_size,
            "isolation_raise_size_bb": isolation_raise_size,
            "limp_reraise_size_bb": limp_reraise_size,
            "limp_reraise_to_isolation_ratio": (
                limp_reraise_size / isolation_raise_size
            ),
            "isolation_response_policy": ISOLATION_RESPONSE_POLICY_NAME,
            "limp_reraise_response_policy": (
                LIMP_RERAISE_RESPONSE_POLICY_NAME
            ),
            "isolation_raise_size_policy": isolation_size_policy.name,
            "limp_reraise_size_policy": limp_reraise_size_policy.name,
            "stack_depth_policy": stack_policy.name,
            "starting_effective_stack_bb": starting_effective_stack,
            "stack_depth_source": stack_depth_source,
            "limper_base_reraise_fraction": (
                base_limper_defense.reraise_fraction
            ),
            "limper_reraise_fraction": limper_defense.reraise_fraction,
            "isolation_raiser_base_continue_fraction": (
                base_isolation_raiser_defense.continue_fraction
            ),
            "isolation_raiser_base_four_bet_fraction": (
                base_isolation_raiser_defense.four_bet_fraction
            ),
            "isolation_raiser_continue_fraction": (
                isolation_raiser_defense.continue_fraction
            ),
            "isolation_raiser_four_bet_fraction": (
                isolation_raiser_defense.four_bet_fraction
            ),
        },
    )


def _three_bet_pot_selection(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    context: tuple[Position, Position, float, float],
) -> PostflopRangeSelection | None:
    opener, three_bettor, opening_size, three_bet_size = context
    # Keep provider imports acyclic: preflop_chart depends on rule_based through
    # the provider package, while this resolver is called by the local provider.
    from app.solvers.preflop_chart import (
        DEFENSE_POLICIES,
        THREE_BET_DEFENSE_POLICIES,
        adjusted_defense_policy,
        adjusted_three_bet_defense_policy,
        policy_for_open_size,
        policy_for_stack_depth,
        policy_for_three_bet_size,
    )

    base_three_bettor = DEFENSE_POLICIES.get((opener, three_bettor))
    base_opener = THREE_BET_DEFENSE_POLICIES.get((opener, three_bettor))
    open_size_policy = policy_for_open_size(opening_size)
    three_bet_size_policy = policy_for_three_bet_size(
        three_bet_size / opening_size
    )
    starting_effective_stack, stack_depth_source = _contextual_stack_depth(
        state,
        hero_relative_position,
        final_preflop_commitment=three_bet_size,
    )
    stack_policy = policy_for_stack_depth(starting_effective_stack)
    if (
        base_three_bettor is None
        or base_opener is None
        or open_size_policy is None
        or three_bet_size_policy is None
        or stack_policy is None
    ):
        return None

    three_bettor_policy = adjusted_defense_policy(
        base_three_bettor,
        open_size_policy,
        stack_policy,
    )
    opener_policy = adjusted_three_bet_defense_policy(
        base_opener,
        three_bet_size_policy,
        stack_policy,
    )
    three_bettor_range = _range_for_policy_band(
        three_bettor_policy.reraise_fraction
    )
    opener_call_range = _range_for_policy_band(
        opener_policy.continue_fraction,
        minimum_exclusive=opener_policy.four_bet_fraction,
    )
    if not three_bettor_range or not opener_call_range:
        return None

    return _selection_for_ranges(
        state,
        hero_relative_position,
        ranges_by_position={
            opener: opener_call_range,
            three_bettor: three_bettor_range,
        },
        source="preflop_chart_three_bet_pot",
        context={
            "scenario": "three_bet_pot",
            "opener_position": opener,
            "three_bettor_position": three_bettor,
            "opening_size_bb": opening_size,
            "three_bet_size_bb": three_bet_size,
            "open_size_policy": open_size_policy.name,
            "three_bet_size_policy": three_bet_size_policy.name,
            "stack_depth_policy": stack_policy.name,
            "starting_effective_stack_bb": starting_effective_stack,
            "stack_depth_source": stack_depth_source,
            "three_bettor_base_fraction": base_three_bettor.reraise_fraction,
            "three_bettor_fraction": three_bettor_policy.reraise_fraction,
            "opener_base_continue_fraction": base_opener.continue_fraction,
            "opener_base_four_bet_fraction": base_opener.four_bet_fraction,
            "opener_continue_fraction": opener_policy.continue_fraction,
            "opener_four_bet_fraction": opener_policy.four_bet_fraction,
        },
    )


def _four_bet_pot_selection(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    context: tuple[Position, Position, float, float, float],
) -> PostflopRangeSelection | None:
    opener, three_bettor, opening_size, three_bet_size, four_bet_size = context
    from app.solvers.preflop_chart import (
        FOUR_BET_DEFENSE_POLICIES,
        THREE_BET_DEFENSE_POLICIES,
        adjusted_four_bet_defense_policy,
        adjusted_three_bet_defense_policy,
        policy_for_four_bet_size,
        policy_for_stack_depth,
        policy_for_three_bet_size,
    )

    base_opener = THREE_BET_DEFENSE_POLICIES.get((opener, three_bettor))
    base_three_bettor = FOUR_BET_DEFENSE_POLICIES.get((opener, three_bettor))
    three_bet_size_policy = policy_for_three_bet_size(
        three_bet_size / opening_size
    )
    four_bet_size_policy = policy_for_four_bet_size(
        four_bet_size / three_bet_size
    )
    starting_effective_stack, stack_depth_source = _contextual_stack_depth(
        state,
        hero_relative_position,
        final_preflop_commitment=four_bet_size,
    )
    stack_policy = policy_for_stack_depth(starting_effective_stack)
    if (
        base_opener is None
        or base_three_bettor is None
        or three_bet_size_policy is None
        or four_bet_size_policy is None
        or stack_policy is None
    ):
        return None

    opener_policy = adjusted_three_bet_defense_policy(
        base_opener,
        three_bet_size_policy,
        stack_policy,
    )
    three_bettor_policy = adjusted_four_bet_defense_policy(
        base_three_bettor,
        four_bet_size_policy,
        stack_policy,
    )
    opener_four_bet_range = _range_for_policy_band(
        opener_policy.four_bet_fraction
    )
    three_bettor_call_range = _range_for_policy_band(
        three_bettor_policy.continue_fraction,
        minimum_exclusive=three_bettor_policy.five_bet_fraction,
    )
    if not opener_four_bet_range or not three_bettor_call_range:
        return None

    return _selection_for_ranges(
        state,
        hero_relative_position,
        ranges_by_position={
            opener: opener_four_bet_range,
            three_bettor: three_bettor_call_range,
        },
        source="preflop_chart_four_bet_pot",
        context={
            "scenario": "four_bet_pot",
            "opener_position": opener,
            "three_bettor_position": three_bettor,
            "opening_size_bb": opening_size,
            "three_bet_size_bb": three_bet_size,
            "four_bet_size_bb": four_bet_size,
            "three_bet_size_policy": three_bet_size_policy.name,
            "four_bet_size_policy": four_bet_size_policy.name,
            "stack_depth_policy": stack_policy.name,
            "starting_effective_stack_bb": starting_effective_stack,
            "stack_depth_source": stack_depth_source,
            "opener_base_four_bet_fraction": base_opener.four_bet_fraction,
            "opener_four_bet_fraction": opener_policy.four_bet_fraction,
            "three_bettor_base_continue_fraction": (
                base_three_bettor.continue_fraction
            ),
            "three_bettor_base_five_bet_fraction": (
                base_three_bettor.five_bet_fraction
            ),
            "three_bettor_continue_fraction": (
                three_bettor_policy.continue_fraction
            ),
            "three_bettor_five_bet_fraction": (
                three_bettor_policy.five_bet_fraction
            ),
        },
    )


def _cold_four_bet_pot_selection(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    context: tuple[Position, Position, Position, float, float, float],
) -> PostflopRangeSelection | None:
    (
        folded_opener,
        three_bettor,
        cold_four_bettor,
        opening_size,
        three_bet_size,
        four_bet_size,
    ) = context
    from app.solvers.preflop_chart import (
        COLD_FOUR_BET_DEFENSE_POLICIES,
        COLD_FOUR_BET_POLICY_NAME,
        COLD_THREE_BET_DEFENSE_POLICIES,
        COLD_THREE_BET_POLICY_NAME,
        adjusted_four_bet_defense_policy,
        adjusted_three_bet_defense_policy,
        policy_for_four_bet_size,
        policy_for_stack_depth,
        policy_for_three_bet_size,
    )

    base_cold_four_bettor = COLD_THREE_BET_DEFENSE_POLICIES.get(
        (folded_opener, three_bettor, cold_four_bettor)
    )
    base_three_bettor = COLD_FOUR_BET_DEFENSE_POLICIES.get(
        (folded_opener, three_bettor, cold_four_bettor)
    )
    three_bet_size_policy = policy_for_three_bet_size(
        three_bet_size / opening_size
    )
    four_bet_size_policy = policy_for_four_bet_size(
        four_bet_size / three_bet_size
    )
    starting_effective_stack, stack_depth_source = _contextual_stack_depth(
        state,
        hero_relative_position,
        final_preflop_commitment=four_bet_size,
    )
    stack_policy = policy_for_stack_depth(starting_effective_stack)
    if (
        base_cold_four_bettor is None
        or base_three_bettor is None
        or three_bet_size_policy is None
        or four_bet_size_policy is None
        or stack_policy is None
    ):
        return None

    cold_four_bettor_policy = adjusted_three_bet_defense_policy(
        base_cold_four_bettor,
        three_bet_size_policy,
        stack_policy,
    )
    three_bettor_policy = adjusted_four_bet_defense_policy(
        base_three_bettor,
        four_bet_size_policy,
        stack_policy,
    )
    cold_four_bettor_range = _range_for_policy_band(
        cold_four_bettor_policy.four_bet_fraction
    )
    three_bettor_call_range = _range_for_policy_band(
        three_bettor_policy.continue_fraction,
        minimum_exclusive=three_bettor_policy.five_bet_fraction,
    )
    if not cold_four_bettor_range or not three_bettor_call_range:
        return None

    return _selection_for_ranges(
        state,
        hero_relative_position,
        ranges_by_position={
            three_bettor: three_bettor_call_range,
            cold_four_bettor: cold_four_bettor_range,
        },
        source="preflop_chart_cold_four_bet_pot",
        context={
            "scenario": "cold_four_bet_pot",
            "folded_opener_position": folded_opener,
            "folded_opener_commitment_bb": opening_size,
            "three_bettor_position": three_bettor,
            "cold_four_bettor_position": cold_four_bettor,
            "opening_size_bb": opening_size,
            "three_bet_size_bb": three_bet_size,
            "four_bet_size_bb": four_bet_size,
            "three_bet_size_policy": three_bet_size_policy.name,
            "four_bet_size_policy": four_bet_size_policy.name,
            "stack_depth_policy": stack_policy.name,
            "starting_effective_stack_bb": starting_effective_stack,
            "stack_depth_source": stack_depth_source,
            "cold_four_bettor_base_four_bet_fraction": (
                base_cold_four_bettor.four_bet_fraction
            ),
            "cold_four_bettor_four_bet_fraction": (
                cold_four_bettor_policy.four_bet_fraction
            ),
            "cold_four_bettor_range_policy": COLD_THREE_BET_POLICY_NAME,
            "three_bettor_base_continue_fraction": (
                base_three_bettor.continue_fraction
            ),
            "three_bettor_base_five_bet_fraction": (
                base_three_bettor.five_bet_fraction
            ),
            "three_bettor_continue_fraction": (
                three_bettor_policy.continue_fraction
            ),
            "three_bettor_five_bet_fraction": (
                three_bettor_policy.five_bet_fraction
            ),
            "cold_four_bet_policy": COLD_FOUR_BET_POLICY_NAME,
        },
    )


def _cold_three_bet_pot_selection(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    context: tuple[Position, Position, Position, float, float],
) -> PostflopRangeSelection | None:
    (
        folded_opener,
        three_bettor,
        cold_caller,
        opening_size,
        three_bet_size,
    ) = context
    from app.solvers.preflop_chart import (
        COLD_THREE_BET_DEFENSE_POLICIES,
        COLD_THREE_BET_POLICY_NAME,
        DEFENSE_POLICIES,
        adjusted_defense_policy,
        adjusted_three_bet_defense_policy,
        policy_for_open_size,
        policy_for_stack_depth,
        policy_for_three_bet_size,
    )

    base_three_bettor = DEFENSE_POLICIES.get(
        (folded_opener, three_bettor)
    )
    base_cold_caller = COLD_THREE_BET_DEFENSE_POLICIES.get(
        (folded_opener, three_bettor, cold_caller)
    )
    open_size_policy = policy_for_open_size(opening_size)
    three_bet_size_policy = policy_for_three_bet_size(
        three_bet_size / opening_size
    )
    starting_effective_stack, stack_depth_source = _contextual_stack_depth(
        state,
        hero_relative_position,
        final_preflop_commitment=three_bet_size,
    )
    stack_policy = policy_for_stack_depth(starting_effective_stack)
    if (
        base_three_bettor is None
        or base_cold_caller is None
        or open_size_policy is None
        or three_bet_size_policy is None
        or stack_policy is None
    ):
        return None

    three_bettor_policy = adjusted_defense_policy(
        base_three_bettor,
        open_size_policy,
        stack_policy,
    )
    cold_caller_policy = adjusted_three_bet_defense_policy(
        base_cold_caller,
        three_bet_size_policy,
        stack_policy,
    )
    three_bettor_range = _range_for_policy_band(
        three_bettor_policy.reraise_fraction
    )
    cold_caller_range = _range_for_policy_band(
        cold_caller_policy.continue_fraction,
        minimum_exclusive=cold_caller_policy.four_bet_fraction,
    )
    if not three_bettor_range or not cold_caller_range:
        return None

    return _selection_for_ranges(
        state,
        hero_relative_position,
        ranges_by_position={
            three_bettor: three_bettor_range,
            cold_caller: cold_caller_range,
        },
        source="preflop_chart_cold_three_bet_pot",
        context={
            "scenario": "cold_three_bet_pot",
            "folded_opener_position": folded_opener,
            "folded_opener_commitment_bb": opening_size,
            "three_bettor_position": three_bettor,
            "cold_caller_position": cold_caller,
            "opening_size_bb": opening_size,
            "three_bet_size_bb": three_bet_size,
            "open_size_policy": open_size_policy.name,
            "three_bet_size_policy": three_bet_size_policy.name,
            "stack_depth_policy": stack_policy.name,
            "starting_effective_stack_bb": starting_effective_stack,
            "stack_depth_source": stack_depth_source,
            "three_bettor_base_fraction": (
                base_three_bettor.reraise_fraction
            ),
            "three_bettor_fraction": three_bettor_policy.reraise_fraction,
            "cold_caller_base_continue_fraction": (
                base_cold_caller.continue_fraction
            ),
            "cold_caller_base_four_bet_fraction": (
                base_cold_caller.four_bet_fraction
            ),
            "cold_caller_continue_fraction": (
                cold_caller_policy.continue_fraction
            ),
            "cold_caller_four_bet_fraction": (
                cold_caller_policy.four_bet_fraction
            ),
            "cold_three_bet_policy": COLD_THREE_BET_POLICY_NAME,
        },
    )


def _squeeze_pot_selection(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    context: tuple[Position, Position, Position, float, float],
) -> PostflopRangeSelection | None:
    (
        folded_opener,
        caller,
        squeezer,
        opening_size,
        squeeze_size,
    ) = context
    from app.solvers.preflop_chart import (
        DEFENSE_POLICIES,
        SINGLE_CALLER_POLICY,
        SQUEEZE_DEFENSE_POLICIES,
        SQUEEZE_RESPONSE_POLICY_NAME,
        adjusted_caller_defense_policy,
        adjusted_defense_policy,
        adjusted_three_bet_defense_policy,
        policy_for_open_size,
        policy_for_stack_depth,
        policy_for_three_bet_size,
    )

    base_squeezer = DEFENSE_POLICIES.get((folded_opener, squeezer))
    base_caller = SQUEEZE_DEFENSE_POLICIES.get(
        (folded_opener, caller, squeezer)
    )
    open_size_policy = policy_for_open_size(opening_size)
    squeeze_size_policy = policy_for_three_bet_size(
        squeeze_size / opening_size
    )
    starting_effective_stack, stack_depth_source = _contextual_stack_depth(
        state,
        hero_relative_position,
        final_preflop_commitment=squeeze_size,
    )
    stack_policy = policy_for_stack_depth(starting_effective_stack)
    if (
        base_squeezer is None
        or base_caller is None
        or open_size_policy is None
        or squeeze_size_policy is None
        or stack_policy is None
    ):
        return None

    squeezer_policy = adjusted_caller_defense_policy(
        adjusted_defense_policy(
            base_squeezer,
            open_size_policy,
            stack_policy,
        ),
        SINGLE_CALLER_POLICY,
    )
    caller_policy = adjusted_three_bet_defense_policy(
        base_caller,
        squeeze_size_policy,
        stack_policy,
    )
    squeezer_range = _range_for_policy_band(
        squeezer_policy.reraise_fraction
    )
    caller_range = _range_for_policy_band(
        caller_policy.continue_fraction,
        minimum_exclusive=caller_policy.four_bet_fraction,
    )
    if not squeezer_range or not caller_range:
        return None

    return _selection_for_ranges(
        state,
        hero_relative_position,
        ranges_by_position={
            caller: caller_range,
            squeezer: squeezer_range,
        },
        source="preflop_chart_squeeze_pot",
        context={
            "scenario": "squeeze_pot",
            "folded_opener_position": folded_opener,
            "folded_opener_commitment_bb": opening_size,
            "caller_position": caller,
            "squeezer_position": squeezer,
            "opening_size_bb": opening_size,
            "squeeze_size_bb": squeeze_size,
            "open_size_policy": open_size_policy.name,
            "squeeze_size_policy": squeeze_size_policy.name,
            "caller_adjustment_policy": SINGLE_CALLER_POLICY.name,
            "stack_depth_policy": stack_policy.name,
            "starting_effective_stack_bb": starting_effective_stack,
            "stack_depth_source": stack_depth_source,
            "squeezer_base_fraction": base_squeezer.reraise_fraction,
            "squeezer_fraction": squeezer_policy.reraise_fraction,
            "caller_base_continue_fraction": base_caller.continue_fraction,
            "caller_base_four_bet_fraction": base_caller.four_bet_fraction,
            "caller_continue_fraction": caller_policy.continue_fraction,
            "caller_four_bet_fraction": caller_policy.four_bet_fraction,
            "squeeze_response_policy": SQUEEZE_RESPONSE_POLICY_NAME,
        },
    )


def _selection_for_ranges(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    *,
    ranges_by_position: dict[Position, str],
    source: RangeSource,
    context: dict[str, str | float],
    participant_positions: tuple[Position, Position] | None = None,
) -> PostflopRangeSelection | None:
    if participant_positions is None:
        hero_position = normalize_position(state.hero_position)
        opponent_position = normalize_position(state.opponent_position)
    else:
        hero_position, opponent_position = participant_positions
    if (
        hero_position not in ranges_by_position
        or opponent_position not in ranges_by_position
    ):
        return None
    hero_range = ranges_by_position[hero_position]
    opponent_range = ranges_by_position[opponent_position]
    oop_range, ip_range = (
        (hero_range, opponent_range)
        if hero_relative_position == "oop"
        else (opponent_range, hero_range)
    )
    resolved_context = context
    if state.street in {"turn", "river"}:
        resolved_context = {
            **context,
            "decision_street": state.street,
            "completed_street_count": float(
                len(state.completed_postflop_streets)
            ),
        }
    return PostflopRangeSelection(
        oop_range=oop_range,
        ip_range=ip_range,
        source=source,
        context=resolved_context,
    )


def _limped_pot_context(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
) -> tuple[Position, float, tuple[Position, Position]] | None:
    if state.players_in_hand != 2 or len(state.preflop_action_history) != 1:
        return None
    limp_action = state.preflop_action_history[0]
    if (
        limp_action.action != "call"
        or abs(limp_action.amount - 1.0) > MONEY_TOLERANCE_BB
        or state.preflop_opener_position is not None
        or state.preflop_open_size is not None
    ):
        return None

    limper = normalize_position(limp_action.actor)
    if (
        limper is None
        or limper == "big_blind"
        or POSITION_ACTION_ORDER[limper]
        >= POSITION_ACTION_ORDER["big_blind"]
    ):
        return None
    participant_positions = _limped_pot_participant_positions(
        state,
        hero_relative_position,
        limper,
    )
    if participant_positions is None:
        return None
    flop_root_pot = _flop_root_pot(state, hero_relative_position)
    if not pot_matches_preflop_actions(
        flop_root_pot,
        ((limper, limp_action.amount),),
    ):
        return None
    return limper, limp_action.amount, participant_positions


def _limped_pot_participant_positions(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    limper: Position,
) -> tuple[Position, Position] | None:
    expected_positions = {limper, "big_blind"}
    hero_position = _limped_pot_participant_position(state.hero_position, limper)
    opponent_position = _limped_pot_participant_position(
        state.opponent_position,
        limper,
    )
    participant_positions: tuple[Position, Position] | None = None
    if (
        hero_position in expected_positions
        and opponent_position in expected_positions
        and hero_position != opponent_position
    ):
        participant_positions = hero_position, opponent_position

    hero_relative_label = _relative_position_label(state.hero_position)
    opponent_relative_label = _relative_position_label(state.opponent_position)
    if (
        participant_positions is None
        and hero_position in expected_positions
        and opponent_relative_label is not None
    ):
        inferred_hero_relative = (
            "oop" if opponent_relative_label == "ip" else "ip"
        )
        if inferred_hero_relative == hero_relative_position:
            opponent = limper if hero_position == "big_blind" else "big_blind"
            participant_positions = hero_position, opponent
    if (
        participant_positions is None
        and opponent_position in expected_positions
        and hero_relative_label is not None
    ):
        if hero_relative_label == hero_relative_position:
            hero = limper if opponent_position == "big_blind" else "big_blind"
            participant_positions = hero, opponent_position
    if participant_positions is None:
        return None

    resolved_hero_position, _ = participant_positions
    if limper != "small_blind":
        expected_hero_relative = (
            "oop" if resolved_hero_position == "big_blind" else "ip"
        )
        if hero_relative_position != expected_hero_relative:
            return None
    return participant_positions


def _limped_pot_participant_position(
    value: str | None,
    limper: Position,
) -> Position | None:
    position = normalize_position(value)
    if limper == "small_blind" and position == "button":
        return "small_blind"
    return position


def _relative_position_label(value: str | None) -> Literal["ip", "oop"] | None:
    if value is None:
        return None
    normalized = " ".join(
        value.lower().replace("_", " ").replace("-", " ").split()
    )
    if normalized in {"ip", "in position"}:
        return "ip"
    if normalized in {"oop", "out of position"}:
        return "oop"
    return None


def _single_raised_pot_context(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
) -> tuple[Position, Position, float] | None:
    if state.players_in_hand != 2 or len(state.preflop_action_history) != 2:
        return None
    opening_action, calling_action = state.preflop_action_history
    if opening_action.action != "raise" or calling_action.action != "call":
        return None
    if (
        abs(opening_action.amount - calling_action.amount) > MONEY_TOLERANCE_BB
        or not MIN_SINGLE_OPEN_SIZE_BB
        <= opening_action.amount
        <= MAX_SINGLE_OPEN_SIZE_BB
    ):
        return None

    opener = normalize_position(opening_action.actor)
    caller = normalize_position(calling_action.actor)
    hero_position = normalize_position(state.hero_position)
    opponent_position = normalize_position(state.opponent_position)
    if (
        opener is None
        or caller is None
        or opener == caller
        or hero_position is None
        or opponent_position is None
        or hero_position == opponent_position
        or {opener, caller} != {hero_position, opponent_position}
    ):
        return None
    if (
        state.preflop_opener_position is not None
        and normalize_position(state.preflop_opener_position) != opener
    ):
        return None
    if (
        state.preflop_open_size is not None
        and abs(state.preflop_open_size - opening_action.amount)
        > MONEY_TOLERANCE_BB
    ):
        return None
    flop_root_pot = _flop_root_pot(state, hero_relative_position)
    if not pot_matches_preflop_actions(
        flop_root_pot,
        (
            (opener, opening_action.amount),
            (caller, calling_action.amount),
        ),
    ):
        return None
    return opener, caller, opening_action.amount


def _isolation_raised_pot_context(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
) -> tuple[Position, float, float, tuple[Position, Position]] | None:
    if state.players_in_hand != 2 or len(state.preflop_action_history) != 3:
        return None
    limp_action, isolation_action, calling_action = (
        state.preflop_action_history
    )
    if (
        limp_action.action != "call"
        or abs(limp_action.amount - 1.0) > MONEY_TOLERANCE_BB
        or isolation_action.action != "raise"
        or isolation_action.actor != "big_blind"
        or calling_action.action != "call"
        or calling_action.actor != limp_action.actor
        or abs(calling_action.amount - isolation_action.amount)
        > MONEY_TOLERANCE_BB
    ):
        return None

    isolation_raise_size = isolation_action.amount
    if not (
        2.0 - MONEY_TOLERANCE_BB
        <= isolation_raise_size
        <= MAX_SUPPORTED_ISOLATION_RAISE_SIZE_BB + MONEY_TOLERANCE_BB
    ):
        return None
    limper = normalize_position(limp_action.actor)
    if (
        limper is None
        or limper == "big_blind"
        or POSITION_ACTION_ORDER[limper]
        >= POSITION_ACTION_ORDER["big_blind"]
    ):
        return None
    participant_positions = _isolation_raised_pot_participant_positions(
        state,
        hero_relative_position,
        limper,
    )
    if participant_positions is None:
        return None
    flop_root_pot = _flop_root_pot(state, hero_relative_position)
    if not pot_matches_preflop_actions(
        flop_root_pot,
        (
            (limper, calling_action.amount),
            ("big_blind", isolation_raise_size),
        ),
    ):
        return None
    return (
        limper,
        limp_action.amount,
        isolation_raise_size,
        participant_positions,
    )


def _isolation_raised_pot_participant_positions(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    limper: Position,
) -> tuple[Position, Position] | None:
    big_blind_relative: Literal["ip", "oop"] = (
        "ip" if limper == "small_blind" else "oop"
    )
    limper_relative: Literal["ip", "oop"] = (
        "oop" if big_blind_relative == "ip" else "ip"
    )
    participant_positions = _limped_pot_participant_positions(
        state,
        hero_relative_position,
        limper,
    )
    if participant_positions is not None:
        hero_position, opponent_position = participant_positions
        expected_hero_relative = (
            big_blind_relative
            if hero_position == "big_blind"
            else limper_relative
        )
        expected_opponent_relative = (
            big_blind_relative
            if opponent_position == "big_blind"
            else limper_relative
        )
        hero_relative_label = _relative_position_label(state.hero_position)
        opponent_relative_label = _relative_position_label(
            state.opponent_position
        )
        if (
            hero_relative_position != expected_hero_relative
            or (
                hero_relative_label is not None
                and hero_relative_label != expected_hero_relative
            )
            or (
                opponent_relative_label is not None
                and opponent_relative_label != expected_opponent_relative
            )
        ):
            return None
        return participant_positions

    hero_relative_label = _relative_position_label(state.hero_position)
    opponent_relative_label = _relative_position_label(
        state.opponent_position
    )
    expected_opponent_relative: Literal["ip", "oop"] = (
        "oop" if hero_relative_position == "ip" else "ip"
    )
    if (
        hero_relative_label != hero_relative_position
        or opponent_relative_label != expected_opponent_relative
    ):
        return None

    hero_position: Position = (
        "big_blind"
        if hero_relative_position == big_blind_relative
        else limper
    )
    opponent_position = (
        limper if hero_position == "big_blind" else "big_blind"
    )
    return hero_position, opponent_position


def _limp_reraised_pot_context(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
) -> tuple[
    Position,
    Position,
    float,
    float,
    float,
    tuple[Position, Position],
] | None:
    if state.players_in_hand != 2 or len(state.preflop_action_history) != 4:
        return None
    limp_action, isolation_action, limp_reraise_action, calling_action = (
        state.preflop_action_history
    )
    if (
        limp_action.action != "call"
        or abs(limp_action.amount - 1.0) > MONEY_TOLERANCE_BB
        or isolation_action.action != "raise"
        or limp_reraise_action.action != "raise"
        or limp_reraise_action.actor != limp_action.actor
        or calling_action.action != "call"
        or calling_action.actor != isolation_action.actor
        or abs(calling_action.amount - limp_reraise_action.amount)
        > MONEY_TOLERANCE_BB
    ):
        return None

    limper = normalize_position(limp_action.actor)
    isolation_raiser = normalize_position(isolation_action.actor)
    isolation_raise_size = isolation_action.amount
    limp_reraise_size = limp_reraise_action.amount
    minimum_limp_reraise = isolation_raise_size + max(
        1.0,
        isolation_raise_size - limp_action.amount,
    )
    if (
        limper is None
        or isolation_raiser is None
        or limper == isolation_raiser
        or POSITION_ACTION_ORDER[limper]
        >= POSITION_ACTION_ORDER[isolation_raiser]
        or isolation_raise_size < 2.0 - MONEY_TOLERANCE_BB
        or isolation_raise_size
        > MAX_SUPPORTED_ISOLATION_RAISE_SIZE_BB + MONEY_TOLERANCE_BB
        or limp_reraise_size + MONEY_TOLERANCE_BB < minimum_limp_reraise
        or limp_reraise_size
        > (
            isolation_raise_size
            * MAX_SUPPORTED_LIMP_RERAISE_TO_ISOLATION_RATIO
            + MONEY_TOLERANCE_BB
        )
    ):
        return None

    ordered_positions = _ordered_postflop_positions(
        limper,
        isolation_raiser,
    )
    reviewed_positions = _reviewed_positions_for_exact_order(
        state,
        *ordered_positions,
    )
    if (
        reviewed_positions is None
        or reviewed_positions[2] != hero_relative_position
    ):
        return None
    participant_positions = reviewed_positions[:2]

    flop_root_pot = _flop_root_pot(state, hero_relative_position)
    if not pot_matches_preflop_actions(
        flop_root_pot,
        (
            (limper, limp_reraise_size),
            (isolation_raiser, calling_action.amount),
        ),
    ):
        return None
    return (
        limper,
        isolation_raiser,
        limp_action.amount,
        isolation_raise_size,
        limp_reraise_size,
        participant_positions,
    )


def _ordered_postflop_positions(
    first_position: Position,
    second_position: Position,
) -> tuple[Position, Position]:
    if (
        POSTFLOP_POSITION_ORDER[first_position]
        < POSTFLOP_POSITION_ORDER[second_position]
    ):
        return first_position, second_position
    return second_position, first_position


def _reviewed_positions_for_exact_order(
    state: CanonicalState,
    oop_position: Position,
    ip_position: Position,
) -> tuple[Position, Position, Literal["ip", "oop"]] | None:
    blind_pair = {oop_position, ip_position} == {"small_blind", "big_blind"}
    reviewed_dealer = blind_pair and any(
        normalize_position(value) == "button"
        for value in (state.hero_position, state.opponent_position)
    )
    if reviewed_dealer:
        oop_position, ip_position = "big_blind", "small_blind"

    def reviewed_actor(value: str | None) -> Position | None:
        relative_label = _relative_position_label(value)
        if relative_label == "oop":
            return oop_position
        if relative_label == "ip":
            return ip_position
        position = normalize_position(value)
        if reviewed_dealer and position == "button":
            position = "small_blind"
        if position in {oop_position, ip_position}:
            return position
        return None

    hero_position = reviewed_actor(state.hero_position)
    opponent_position = reviewed_actor(state.opponent_position)
    if (
        hero_position is None
        or opponent_position is None
        or hero_position == opponent_position
        or {hero_position, opponent_position} != {oop_position, ip_position}
    ):
        return None
    hero_relative_position: Literal["ip", "oop"] = (
        "oop" if hero_position == oop_position else "ip"
    )
    return hero_position, opponent_position, hero_relative_position


def _three_bet_pot_context(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
) -> tuple[Position, Position, float, float] | None:
    if state.players_in_hand != 2 or len(state.preflop_action_history) != 3:
        return None
    opening_action, three_bet_action, calling_action = (
        state.preflop_action_history
    )
    if (
        opening_action.action != "raise"
        or three_bet_action.action != "raise"
        or calling_action.action != "call"
        or calling_action.actor != opening_action.actor
        or abs(calling_action.amount - three_bet_action.amount)
        > MONEY_TOLERANCE_BB
        or not MIN_SINGLE_OPEN_SIZE_BB
        <= opening_action.amount
        <= MAX_SINGLE_OPEN_SIZE_BB
    ):
        return None

    opener = normalize_position(opening_action.actor)
    three_bettor = normalize_position(three_bet_action.actor)
    hero_position = normalize_position(state.hero_position)
    opponent_position = normalize_position(state.opponent_position)
    minimum_full_raise = opening_action.amount + max(
        1.0,
        opening_action.amount - 1.0,
    )
    if (
        opener is None
        or three_bettor is None
        or opener == three_bettor
        or hero_position is None
        or opponent_position is None
        or hero_position == opponent_position
        or {opener, three_bettor} != {hero_position, opponent_position}
        or POSITION_ACTION_ORDER[opener]
        >= POSITION_ACTION_ORDER[three_bettor]
        or three_bet_action.amount + MONEY_TOLERANCE_BB < minimum_full_raise
        or three_bet_action.amount
        > opening_action.amount * MAX_SUPPORTED_THREE_BET_TO_OPEN_RATIO
        + MONEY_TOLERANCE_BB
    ):
        return None
    if (
        state.preflop_opener_position is not None
        and normalize_position(state.preflop_opener_position) != opener
    ):
        return None
    if (
        state.preflop_open_size is not None
        and abs(state.preflop_open_size - opening_action.amount)
        > MONEY_TOLERANCE_BB
    ):
        return None
    flop_root_pot = _flop_root_pot(state, hero_relative_position)
    if not pot_matches_preflop_actions(
        flop_root_pot,
        (
            (opener, calling_action.amount),
            (three_bettor, three_bet_action.amount),
        ),
    ):
        return None
    return (
        opener,
        three_bettor,
        opening_action.amount,
        three_bet_action.amount,
    )


def _cold_three_bet_pot_context(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
) -> tuple[Position, Position, Position, float, float] | None:
    if state.players_in_hand != 2 or len(state.preflop_action_history) != 3:
        return None
    opening_action, three_bet_action, calling_action = (
        state.preflop_action_history
    )
    if (
        opening_action.action != "raise"
        or three_bet_action.action != "raise"
        or calling_action.action != "call"
        or calling_action.actor in {
            opening_action.actor,
            three_bet_action.actor,
        }
        or abs(calling_action.amount - three_bet_action.amount)
        > MONEY_TOLERANCE_BB
        or not MIN_SINGLE_OPEN_SIZE_BB
        <= opening_action.amount
        <= MAX_SINGLE_OPEN_SIZE_BB
    ):
        return None

    folded_opener = normalize_position(opening_action.actor)
    three_bettor = normalize_position(three_bet_action.actor)
    cold_caller = normalize_position(calling_action.actor)
    hero_position = normalize_position(state.hero_position)
    opponent_position = normalize_position(state.opponent_position)
    minimum_full_raise = opening_action.amount + max(
        1.0,
        opening_action.amount - 1.0,
    )
    if (
        folded_opener is None
        or three_bettor is None
        or cold_caller is None
        or len({folded_opener, three_bettor, cold_caller}) != 3
        or hero_position is None
        or opponent_position is None
        or hero_position == opponent_position
        or {three_bettor, cold_caller}
        != {hero_position, opponent_position}
        or not POSITION_ACTION_ORDER[folded_opener]
        < POSITION_ACTION_ORDER[three_bettor]
        < POSITION_ACTION_ORDER[cold_caller]
        or three_bet_action.amount + MONEY_TOLERANCE_BB < minimum_full_raise
        or three_bet_action.amount
        > opening_action.amount * MAX_SUPPORTED_THREE_BET_TO_OPEN_RATIO
        + MONEY_TOLERANCE_BB
    ):
        return None
    if (
        state.preflop_opener_position is not None
        and normalize_position(state.preflop_opener_position)
        != folded_opener
    ):
        return None
    if (
        state.preflop_open_size is not None
        and abs(state.preflop_open_size - opening_action.amount)
        > MONEY_TOLERANCE_BB
    ):
        return None
    flop_root_pot = _flop_root_pot(state, hero_relative_position)
    if not pot_matches_preflop_actions(
        flop_root_pot,
        (
            (folded_opener, opening_action.amount),
            (three_bettor, three_bet_action.amount),
            (cold_caller, calling_action.amount),
        ),
    ):
        return None
    return (
        folded_opener,
        three_bettor,
        cold_caller,
        opening_action.amount,
        three_bet_action.amount,
    )


def _squeeze_pot_context(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
) -> tuple[Position, Position, Position, float, float] | None:
    if state.players_in_hand != 2 or len(state.preflop_action_history) != 4:
        return None
    opening_action, first_call, squeeze_action, final_call = (
        state.preflop_action_history
    )
    if (
        opening_action.action != "raise"
        or first_call.action != "call"
        or squeeze_action.action != "raise"
        or final_call.action != "call"
        or final_call.actor != first_call.actor
        or abs(first_call.amount - opening_action.amount)
        > MONEY_TOLERANCE_BB
        or abs(final_call.amount - squeeze_action.amount)
        > MONEY_TOLERANCE_BB
        or not MIN_SINGLE_OPEN_SIZE_BB
        <= opening_action.amount
        <= MAX_SINGLE_OPEN_SIZE_BB
    ):
        return None

    folded_opener = normalize_position(opening_action.actor)
    caller = normalize_position(first_call.actor)
    squeezer = normalize_position(squeeze_action.actor)
    hero_position = normalize_position(state.hero_position)
    opponent_position = normalize_position(state.opponent_position)
    minimum_squeeze = opening_action.amount + max(
        1.0,
        opening_action.amount - 1.0,
    )
    if (
        folded_opener is None
        or caller is None
        or squeezer is None
        or len({folded_opener, caller, squeezer}) != 3
        or hero_position is None
        or opponent_position is None
        or hero_position == opponent_position
        or {caller, squeezer} != {hero_position, opponent_position}
        or not POSITION_ACTION_ORDER[folded_opener]
        < POSITION_ACTION_ORDER[caller]
        < POSITION_ACTION_ORDER[squeezer]
        or squeeze_action.amount + MONEY_TOLERANCE_BB < minimum_squeeze
        or squeeze_action.amount
        > opening_action.amount * MAX_SUPPORTED_THREE_BET_TO_OPEN_RATIO
        + MONEY_TOLERANCE_BB
    ):
        return None
    if (
        state.preflop_opener_position is not None
        and normalize_position(state.preflop_opener_position)
        != folded_opener
    ):
        return None
    if (
        state.preflop_open_size is not None
        and abs(state.preflop_open_size - opening_action.amount)
        > MONEY_TOLERANCE_BB
    ):
        return None
    flop_root_pot = _flop_root_pot(state, hero_relative_position)
    if not pot_matches_preflop_actions(
        flop_root_pot,
        (
            (folded_opener, opening_action.amount),
            (caller, final_call.amount),
            (squeezer, squeeze_action.amount),
        ),
    ):
        return None
    return (
        folded_opener,
        caller,
        squeezer,
        opening_action.amount,
        squeeze_action.amount,
    )


def _four_bet_pot_context(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
) -> tuple[Position, Position, float, float, float] | None:
    if state.players_in_hand != 2 or len(state.preflop_action_history) != 4:
        return None
    opening_action, three_bet_action, four_bet_action, calling_action = (
        state.preflop_action_history
    )
    if (
        opening_action.action != "raise"
        or three_bet_action.action != "raise"
        or four_bet_action.action != "raise"
        or calling_action.action != "call"
        or four_bet_action.actor != opening_action.actor
        or calling_action.actor != three_bet_action.actor
        or abs(calling_action.amount - four_bet_action.amount)
        > MONEY_TOLERANCE_BB
        or not MIN_SINGLE_OPEN_SIZE_BB
        <= opening_action.amount
        <= MAX_SINGLE_OPEN_SIZE_BB
    ):
        return None

    opener = normalize_position(opening_action.actor)
    three_bettor = normalize_position(three_bet_action.actor)
    hero_position = normalize_position(state.hero_position)
    opponent_position = normalize_position(state.opponent_position)
    minimum_three_bet = opening_action.amount + max(
        1.0,
        opening_action.amount - 1.0,
    )
    minimum_four_bet = three_bet_action.amount + (
        three_bet_action.amount - opening_action.amount
    )
    if (
        opener is None
        or three_bettor is None
        or opener == three_bettor
        or hero_position is None
        or opponent_position is None
        or hero_position == opponent_position
        or {opener, three_bettor} != {hero_position, opponent_position}
        or POSITION_ACTION_ORDER[opener]
        >= POSITION_ACTION_ORDER[three_bettor]
        or three_bet_action.amount + MONEY_TOLERANCE_BB < minimum_three_bet
        or three_bet_action.amount
        > opening_action.amount * MAX_SUPPORTED_THREE_BET_TO_OPEN_RATIO
        + MONEY_TOLERANCE_BB
        or four_bet_action.amount + MONEY_TOLERANCE_BB < minimum_four_bet
        or four_bet_action.amount
        > three_bet_action.amount * MAX_SUPPORTED_FOUR_BET_TO_THREE_BET_RATIO
        + MONEY_TOLERANCE_BB
    ):
        return None
    if (
        state.preflop_opener_position is not None
        and normalize_position(state.preflop_opener_position) != opener
    ):
        return None
    if (
        state.preflop_open_size is not None
        and abs(state.preflop_open_size - opening_action.amount)
        > MONEY_TOLERANCE_BB
    ):
        return None
    flop_root_pot = _flop_root_pot(state, hero_relative_position)
    if not pot_matches_preflop_actions(
        flop_root_pot,
        (
            (opener, four_bet_action.amount),
            (three_bettor, calling_action.amount),
        ),
    ):
        return None
    return (
        opener,
        three_bettor,
        opening_action.amount,
        three_bet_action.amount,
        four_bet_action.amount,
    )


def _cold_four_bet_pot_context(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
) -> tuple[Position, Position, Position, float, float, float] | None:
    if state.players_in_hand != 2 or len(state.preflop_action_history) != 4:
        return None
    opening_action, three_bet_action, four_bet_action, calling_action = (
        state.preflop_action_history
    )
    if (
        opening_action.action != "raise"
        or three_bet_action.action != "raise"
        or four_bet_action.action != "raise"
        or calling_action.action != "call"
        or four_bet_action.actor in {
            opening_action.actor,
            three_bet_action.actor,
        }
        or calling_action.actor != three_bet_action.actor
        or abs(calling_action.amount - four_bet_action.amount)
        > MONEY_TOLERANCE_BB
        or not MIN_SINGLE_OPEN_SIZE_BB
        <= opening_action.amount
        <= MAX_SINGLE_OPEN_SIZE_BB
    ):
        return None

    folded_opener = normalize_position(opening_action.actor)
    three_bettor = normalize_position(three_bet_action.actor)
    cold_four_bettor = normalize_position(four_bet_action.actor)
    hero_position = normalize_position(state.hero_position)
    opponent_position = normalize_position(state.opponent_position)
    minimum_three_bet = opening_action.amount + max(
        1.0,
        opening_action.amount - 1.0,
    )
    minimum_four_bet = three_bet_action.amount + (
        three_bet_action.amount - opening_action.amount
    )
    if (
        folded_opener is None
        or three_bettor is None
        or cold_four_bettor is None
        or len({folded_opener, three_bettor, cold_four_bettor}) != 3
        or hero_position is None
        or opponent_position is None
        or hero_position == opponent_position
        or {three_bettor, cold_four_bettor}
        != {hero_position, opponent_position}
        or not POSITION_ACTION_ORDER[folded_opener]
        < POSITION_ACTION_ORDER[three_bettor]
        < POSITION_ACTION_ORDER[cold_four_bettor]
        or three_bet_action.amount + MONEY_TOLERANCE_BB < minimum_three_bet
        or three_bet_action.amount
        > opening_action.amount * MAX_SUPPORTED_THREE_BET_TO_OPEN_RATIO
        + MONEY_TOLERANCE_BB
        or four_bet_action.amount + MONEY_TOLERANCE_BB < minimum_four_bet
        or four_bet_action.amount
        > three_bet_action.amount * MAX_SUPPORTED_FOUR_BET_TO_THREE_BET_RATIO
        + MONEY_TOLERANCE_BB
    ):
        return None
    if (
        state.preflop_opener_position is not None
        and normalize_position(state.preflop_opener_position) != folded_opener
    ):
        return None
    if (
        state.preflop_open_size is not None
        and abs(state.preflop_open_size - opening_action.amount)
        > MONEY_TOLERANCE_BB
    ):
        return None
    flop_root_pot = _flop_root_pot(state, hero_relative_position)
    if not pot_matches_preflop_actions(
        flop_root_pot,
        (
            (folded_opener, opening_action.amount),
            (three_bettor, calling_action.amount),
            (cold_four_bettor, four_bet_action.amount),
        ),
    ):
        return None
    return (
        folded_opener,
        three_bettor,
        cold_four_bettor,
        opening_action.amount,
        three_bet_action.amount,
        four_bet_action.amount,
    )


def _contextual_stack_depth(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    *,
    final_preflop_commitment: float,
) -> tuple[float, StackDepthSource]:
    reconstructed = _reconstructed_starting_effective_stack(
        state,
        hero_relative_position,
        final_preflop_commitment=final_preflop_commitment,
    )
    if reconstructed is not None:
        return reconstructed, "reconstructed"
    return STANDARD_CONTEXTUAL_STACK_BB, "standard_assumption"


def _reconstructed_starting_effective_stack(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
    *,
    final_preflop_commitment: float,
) -> float | None:
    if state.effective_stack is None:
        return None
    contributions = _postflop_contributions(
        state,
        hero_relative_position,
    )
    if contributions is None:
        return None

    visible_stacks = (state.hero_stack, state.opponent_stack)
    if all(stack is not None for stack in visible_stacks):
        visible_effective = min(
            stack for stack in visible_stacks if stack is not None
        )
        if (
            abs(state.effective_stack - visible_effective)
            > MONEY_TOLERANCE_BB
        ):
            return None

    if all(amount <= MONEY_TOLERANCE_BB for amount in contributions.values()):
        return round(state.effective_stack + final_preflop_commitment, 4)
    if state.hero_stack is None or state.opponent_stack is None:
        return None

    hero_actor = hero_relative_position
    opponent_actor: Literal["ip", "oop"] = (
        "oop" if hero_actor == "ip" else "ip"
    )
    effective_before_postflop = min(
        state.hero_stack + contributions[hero_actor],
        state.opponent_stack + contributions[opponent_actor],
    )
    return round(effective_before_postflop + final_preflop_commitment, 4)


def _current_street_contributions(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
) -> dict[Literal["ip", "oop"], float] | None:
    contributions: dict[Literal["ip", "oop"], float] = {
        "oop": 0.0,
        "ip": 0.0,
    }
    current_bet = state.current_bet or 0
    if not state.postflop_action_history:
        if current_bet <= MONEY_TOLERANCE_BB:
            return contributions if state.facing_action is None else None
        if state.facing_action != "bet":
            return None
        opponent_actor: Literal["ip", "oop"] = (
            "oop" if hero_relative_position == "ip" else "ip"
        )
        contributions[opponent_actor] = current_bet
        return contributions

    next_actor: Literal["ip", "oop"] = "oop"
    last_aggression: Literal["bet", "raise"] | None = None
    for action in state.postflop_action_history:
        if action.actor != next_actor:
            return None
        opponent_actor: Literal["ip", "oop"] = (
            "oop" if action.actor == "ip" else "ip"
        )
        if action.action == "check":
            if (
                abs(
                    contributions[action.actor]
                    - contributions[opponent_actor]
                )
                > MONEY_TOLERANCE_BB
            ):
                return None
        elif action.action == "bet":
            if (
                abs(
                    contributions[action.actor]
                    - contributions[opponent_actor]
                )
                > MONEY_TOLERANCE_BB
                or action.amount is None
            ):
                return None
            contributions[action.actor] = action.amount
            last_aggression = "bet"
        else:
            if (
                contributions[action.actor]
                >= contributions[opponent_actor] - MONEY_TOLERANCE_BB
                or action.amount is None
                or action.amount
                <= contributions[opponent_actor] + MONEY_TOLERANCE_BB
            ):
                return None
            contributions[action.actor] = action.amount
            last_aggression = "raise"
        next_actor = opponent_actor

    if next_actor != hero_relative_position:
        return None
    opponent_actor = "oop" if hero_relative_position == "ip" else "ip"
    expected_call = (
        contributions[opponent_actor] - contributions[hero_relative_position]
    )
    if (
        expected_call < -MONEY_TOLERANCE_BB
        or abs(max(0.0, expected_call) - current_bet) > MONEY_TOLERANCE_BB
    ):
        return None
    expected_facing_action = (
        last_aggression if expected_call > MONEY_TOLERANCE_BB else None
    )
    if state.facing_action != expected_facing_action:
        return None
    return contributions


def _postflop_contributions(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
) -> dict[Literal["ip", "oop"], float] | None:
    expected_completed = {
        "flop": (),
        "turn": ("flop",),
        "river": ("flop", "turn"),
    }.get(state.street)
    if expected_completed is None:
        return None

    completed_streets = tuple(
        history.street for history in state.completed_postflop_streets
    )
    if completed_streets != expected_completed:
        return None

    contributions: dict[Literal["ip", "oop"], float] = {
        "oop": 0.0,
        "ip": 0.0,
    }
    for history in state.completed_postflop_streets:
        street_contributions: dict[Literal["ip", "oop"], float] = {
            "oop": 0.0,
            "ip": 0.0,
        }
        for action in history.actions:
            if action.amount is not None:
                street_contributions[action.actor] = action.amount
        for actor, amount in street_contributions.items():
            contributions[actor] += amount

    current = _current_street_contributions(state, hero_relative_position)
    if current is None:
        return None
    for actor, amount in current.items():
        contributions[actor] += amount
    return contributions


def _flop_root_pot(
    state: CanonicalState,
    hero_relative_position: Literal["ip", "oop"],
) -> float | None:
    if state.pot_size is None:
        return None
    contributions = _postflop_contributions(state, hero_relative_position)
    if contributions is None:
        return None
    root_pot = state.pot_size - sum(contributions.values())
    return root_pot if root_pot > 0 else None


def _range_for_policy_band(
    maximum_fraction: float,
    *,
    minimum_exclusive: float = 0,
) -> str:
    from app.solvers.preflop_chart import hand_classes_in_policy_band

    return ",".join(
        hand_classes_in_policy_band(
            maximum_fraction,
            minimum_exclusive=minimum_exclusive,
        )
    )
