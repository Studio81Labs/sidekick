from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.domain.poker import Card
from app.models import RecommendationAction, RecommendationRequest, RecommendationResult
from app.providers.rule_based import _starting_hand_score
from app.solvers.preflop_context import (
    MAX_SUPPORTED_ISOLATION_RAISE_SIZE_BB,
    MAX_SUPPORTED_FOUR_BET_TO_THREE_BET_RATIO,
    MAX_SUPPORTED_LIMP_RERAISE_TO_ISOLATION_RATIO,
    MAX_SUPPORTED_THREE_BET_TO_OPEN_RATIO,
    POSTED_BLIND_BB,
    PreflopChartContext,
    Position,
    normalize_position,
    resolve_preflop_chart_context,
)

RANKS = tuple("AKQJT98765432")
RANK_INDEX = {rank: index for index, rank in enumerate(RANKS)}


@dataclass(frozen=True)
class PositionPolicy:
    open_fraction: float


@dataclass(frozen=True)
class LimpResponsePolicy:
    raise_fraction: float


@dataclass(frozen=True)
class DefensePolicy:
    continue_fraction: float
    reraise_fraction: float


@dataclass(frozen=True)
class CallerAdjustmentPolicy:
    name: str
    continue_multiplier: float
    reraise_multiplier: float
    squeeze_open_multiple: float


@dataclass(frozen=True)
class ThreeBetDefensePolicy:
    continue_fraction: float
    four_bet_fraction: float


@dataclass(frozen=True)
class FourBetDefensePolicy:
    continue_fraction: float
    five_bet_fraction: float


@dataclass(frozen=True)
class OpenSizePolicy:
    name: str
    maximum_size: float
    continue_multiplier: float
    reraise_multiplier: float


@dataclass(frozen=True)
class ThreeBetSizePolicy:
    name: str
    maximum_ratio: float
    continue_multiplier: float
    four_bet_multiplier: float


@dataclass(frozen=True)
class FourBetSizePolicy:
    name: str
    maximum_ratio: float
    continue_multiplier: float
    five_bet_multiplier: float


@dataclass(frozen=True)
class StackDepthPolicy:
    name: str
    maximum_stack: float | None
    open_multiplier: float
    continue_multiplier: float
    reraise_multiplier: float
    opening_size: float


POSITION_POLICIES: dict[Position, PositionPolicy] = {
    "utg": PositionPolicy(0.17),
    "hijack": PositionPolicy(0.22),
    "cutoff": PositionPolicy(0.30),
    "button": PositionPolicy(0.45),
    "small_blind": PositionPolicy(0.40),
    "big_blind": PositionPolicy(0.0),
}

LIMP_RESPONSE_POLICY_NAME = "heads_up_single_limper"
LIMP_RESPONSE_POLICIES: dict[Position, LimpResponsePolicy] = {
    "utg": LimpResponsePolicy(0.20),
    "hijack": LimpResponsePolicy(0.24),
    "cutoff": LimpResponsePolicy(0.28),
    "button": LimpResponsePolicy(0.36),
    "small_blind": LimpResponsePolicy(0.44),
}

TWO_LIMPER_RESPONSE_POLICY_NAME = "big_blind_two_limpers"
TWO_LIMPER_RESPONSE_POLICIES: dict[
    tuple[Position, Position], LimpResponsePolicy
] = {
    ("utg", "hijack"): LimpResponsePolicy(0.14),
    ("utg", "cutoff"): LimpResponsePolicy(0.15),
    ("utg", "button"): LimpResponsePolicy(0.16),
    ("utg", "small_blind"): LimpResponsePolicy(0.17),
    ("hijack", "cutoff"): LimpResponsePolicy(0.16),
    ("hijack", "button"): LimpResponsePolicy(0.17),
    ("hijack", "small_blind"): LimpResponsePolicy(0.18),
    ("cutoff", "button"): LimpResponsePolicy(0.19),
    ("cutoff", "small_blind"): LimpResponsePolicy(0.20),
    ("button", "small_blind"): LimpResponsePolicy(0.22),
}

THREE_LIMPER_RESPONSE_POLICY_NAME = "big_blind_three_limpers"
THREE_LIMPER_RESPONSE_POLICIES: dict[
    tuple[Position, Position, Position], LimpResponsePolicy
] = {
    ("utg", "hijack", "cutoff"): LimpResponsePolicy(0.10),
    ("utg", "hijack", "button"): LimpResponsePolicy(0.11),
    ("utg", "hijack", "small_blind"): LimpResponsePolicy(0.12),
    ("utg", "cutoff", "button"): LimpResponsePolicy(0.12),
    ("utg", "cutoff", "small_blind"): LimpResponsePolicy(0.13),
    ("utg", "button", "small_blind"): LimpResponsePolicy(0.14),
    ("hijack", "cutoff", "button"): LimpResponsePolicy(0.13),
    ("hijack", "cutoff", "small_blind"): LimpResponsePolicy(0.14),
    ("hijack", "button", "small_blind"): LimpResponsePolicy(0.15),
    ("cutoff", "button", "small_blind"): LimpResponsePolicy(0.16),
}

FOUR_LIMPER_RESPONSE_POLICY_NAME = "big_blind_four_limpers"
FOUR_LIMPER_RESPONSE_POLICIES: dict[
    tuple[Position, Position, Position, Position], LimpResponsePolicy
] = {
    ("utg", "hijack", "cutoff", "button"): LimpResponsePolicy(0.075),
    ("utg", "hijack", "cutoff", "small_blind"): LimpResponsePolicy(0.085),
    ("utg", "hijack", "button", "small_blind"): LimpResponsePolicy(0.095),
    ("utg", "cutoff", "button", "small_blind"): LimpResponsePolicy(0.105),
    ("hijack", "cutoff", "button", "small_blind"): LimpResponsePolicy(0.115),
}

FIVE_LIMPER_RESPONSE_POLICY_NAME = "big_blind_five_limpers"
FIVE_LIMPER_RESPONSE_POLICIES: dict[
    tuple[Position, Position, Position, Position, Position], LimpResponsePolicy
] = {
    (
        "utg",
        "hijack",
        "cutoff",
        "button",
        "small_blind",
    ): LimpResponsePolicy(0.06),
}

ISOLATION_RESPONSE_POLICY_NAME = "heads_up_after_hero_limp"
ISOLATION_RESPONSE_POLICIES: dict[
    tuple[Position, Position], DefensePolicy
] = {
    ("utg", "hijack"): DefensePolicy(0.12, 0.035),
    ("utg", "cutoff"): DefensePolicy(0.13, 0.040),
    ("utg", "button"): DefensePolicy(0.14, 0.045),
    ("utg", "small_blind"): DefensePolicy(0.13, 0.040),
    ("utg", "big_blind"): DefensePolicy(0.15, 0.045),
    ("hijack", "cutoff"): DefensePolicy(0.14, 0.040),
    ("hijack", "button"): DefensePolicy(0.15, 0.045),
    ("hijack", "small_blind"): DefensePolicy(0.14, 0.040),
    ("hijack", "big_blind"): DefensePolicy(0.16, 0.050),
    ("cutoff", "button"): DefensePolicy(0.16, 0.050),
    ("cutoff", "small_blind"): DefensePolicy(0.15, 0.045),
    ("cutoff", "big_blind"): DefensePolicy(0.17, 0.055),
    ("button", "small_blind"): DefensePolicy(0.17, 0.055),
    ("button", "big_blind"): DefensePolicy(0.19, 0.060),
    ("small_blind", "big_blind"): DefensePolicy(0.21, 0.070),
}

# Original-limper reraises represent a substantially stronger range than an
# ordinary 3-bet. These boundaries are shares of all 169 starting-hand classes
# and are keyed by (original limper, hero isolator).
LIMP_RERAISE_RESPONSE_POLICY_NAME = "heads_up_original_limper_reraise"
LIMP_RERAISE_RESPONSE_POLICIES: dict[
    tuple[Position, Position], ThreeBetDefensePolicy
] = {
    ("utg", "hijack"): ThreeBetDefensePolicy(0.045, 0.020),
    ("utg", "cutoff"): ThreeBetDefensePolicy(0.048, 0.021),
    ("utg", "button"): ThreeBetDefensePolicy(0.050, 0.022),
    ("utg", "small_blind"): ThreeBetDefensePolicy(0.052, 0.023),
    ("utg", "big_blind"): ThreeBetDefensePolicy(0.055, 0.024),
    ("hijack", "cutoff"): ThreeBetDefensePolicy(0.052, 0.023),
    ("hijack", "button"): ThreeBetDefensePolicy(0.055, 0.024),
    ("hijack", "small_blind"): ThreeBetDefensePolicy(0.057, 0.025),
    ("hijack", "big_blind"): ThreeBetDefensePolicy(0.060, 0.026),
    ("cutoff", "button"): ThreeBetDefensePolicy(0.060, 0.026),
    ("cutoff", "small_blind"): ThreeBetDefensePolicy(0.063, 0.027),
    ("cutoff", "big_blind"): ThreeBetDefensePolicy(0.066, 0.028),
    ("button", "small_blind"): ThreeBetDefensePolicy(0.070, 0.030),
    ("button", "big_blind"): ThreeBetDefensePolicy(0.074, 0.032),
    ("small_blind", "big_blind"): ThreeBetDefensePolicy(0.080, 0.035),
}

# Conservative six-max response boundaries keyed by (opener, hero). Later
# openers permit wider continues and reraises, while cold-call-sensitive blind
# matchups remain tighter than big-blind closes-action defense.
DEFENSE_POLICIES: dict[tuple[Position, Position], DefensePolicy] = {
    ("utg", "hijack"): DefensePolicy(0.10, 0.04),
    ("utg", "cutoff"): DefensePolicy(0.12, 0.05),
    ("utg", "button"): DefensePolicy(0.14, 0.05),
    ("utg", "small_blind"): DefensePolicy(0.12, 0.05),
    ("utg", "big_blind"): DefensePolicy(0.20, 0.06),
    ("hijack", "cutoff"): DefensePolicy(0.14, 0.05),
    ("hijack", "button"): DefensePolicy(0.17, 0.06),
    ("hijack", "small_blind"): DefensePolicy(0.14, 0.06),
    ("hijack", "big_blind"): DefensePolicy(0.23, 0.07),
    ("cutoff", "button"): DefensePolicy(0.22, 0.08),
    ("cutoff", "small_blind"): DefensePolicy(0.18, 0.08),
    ("cutoff", "big_blind"): DefensePolicy(0.30, 0.09),
    ("button", "small_blind"): DefensePolicy(0.24, 0.10),
    ("button", "big_blind"): DefensePolicy(0.40, 0.12),
    ("small_blind", "big_blind"): DefensePolicy(0.48, 0.13),
}

# Hero-open responses to one later-position 3-bet. Fractions are shares of all
# starting hands, not shares of the opening range, which keeps them comparable
# with the chart's existing 169-class ranking.
THREE_BET_DEFENSE_POLICIES: dict[
    tuple[Position, Position], ThreeBetDefensePolicy
] = {
    ("utg", "hijack"): ThreeBetDefensePolicy(0.075, 0.025),
    ("utg", "cutoff"): ThreeBetDefensePolicy(0.080, 0.030),
    ("utg", "button"): ThreeBetDefensePolicy(0.085, 0.030),
    ("utg", "small_blind"): ThreeBetDefensePolicy(0.090, 0.035),
    ("utg", "big_blind"): ThreeBetDefensePolicy(0.095, 0.035),
    ("hijack", "cutoff"): ThreeBetDefensePolicy(0.090, 0.035),
    ("hijack", "button"): ThreeBetDefensePolicy(0.100, 0.040),
    ("hijack", "small_blind"): ThreeBetDefensePolicy(0.105, 0.040),
    ("hijack", "big_blind"): ThreeBetDefensePolicy(0.110, 0.045),
    ("cutoff", "button"): ThreeBetDefensePolicy(0.120, 0.045),
    ("cutoff", "small_blind"): ThreeBetDefensePolicy(0.130, 0.050),
    ("cutoff", "big_blind"): ThreeBetDefensePolicy(0.135, 0.050),
    ("button", "small_blind"): ThreeBetDefensePolicy(0.160, 0.060),
    ("button", "big_blind"): ThreeBetDefensePolicy(0.180, 0.065),
    ("small_blind", "big_blind"): ThreeBetDefensePolicy(0.200, 0.070),
}

# Cold 3-bet responses are deliberately narrower than hero-open defense. The
# explicit three-seat keys prevent a generic range from leaking into ambiguous
# multiway action and keep each supported six-max action order auditable.
COLD_THREE_BET_POLICY_NAME = "conservative_three_player"
COLD_THREE_BET_DEFENSE_POLICIES: dict[
    tuple[Position, Position, Position], ThreeBetDefensePolicy
] = {
    ("utg", "hijack", "cutoff"): ThreeBetDefensePolicy(0.045, 0.020),
    ("utg", "hijack", "button"): ThreeBetDefensePolicy(0.045, 0.020),
    ("utg", "hijack", "small_blind"): ThreeBetDefensePolicy(0.045, 0.020),
    ("utg", "hijack", "big_blind"): ThreeBetDefensePolicy(0.050, 0.020),
    ("utg", "cutoff", "button"): ThreeBetDefensePolicy(0.050, 0.020),
    ("utg", "cutoff", "small_blind"): ThreeBetDefensePolicy(0.050, 0.022),
    ("utg", "cutoff", "big_blind"): ThreeBetDefensePolicy(0.055, 0.022),
    ("utg", "button", "small_blind"): ThreeBetDefensePolicy(0.055, 0.022),
    ("utg", "button", "big_blind"): ThreeBetDefensePolicy(0.060, 0.025),
    ("utg", "small_blind", "big_blind"): ThreeBetDefensePolicy(0.060, 0.025),
    ("hijack", "cutoff", "button"): ThreeBetDefensePolicy(0.055, 0.022),
    ("hijack", "cutoff", "small_blind"): ThreeBetDefensePolicy(0.055, 0.025),
    ("hijack", "cutoff", "big_blind"): ThreeBetDefensePolicy(0.060, 0.025),
    ("hijack", "button", "small_blind"): ThreeBetDefensePolicy(0.060, 0.025),
    ("hijack", "button", "big_blind"): ThreeBetDefensePolicy(0.065, 0.028),
    ("hijack", "small_blind", "big_blind"): ThreeBetDefensePolicy(0.065, 0.028),
    ("cutoff", "button", "small_blind"): ThreeBetDefensePolicy(0.070, 0.030),
    ("cutoff", "button", "big_blind"): ThreeBetDefensePolicy(0.075, 0.032),
    ("cutoff", "small_blind", "big_blind"): ThreeBetDefensePolicy(0.080, 0.035),
    ("button", "small_blind", "big_blind"): ThreeBetDefensePolicy(0.090, 0.040),
}

# Responses after hero cold-calls an open, a later player squeezes, and the
# opener folds. Explicit seat triples keep the capped calling range and dead
# opener money visible instead of treating this as an ordinary heads-up 3-bet.
SQUEEZE_RESPONSE_POLICY_NAME = "conservative_heads_up_squeeze"
SQUEEZE_DEFENSE_POLICIES: dict[
    tuple[Position, Position, Position], ThreeBetDefensePolicy
] = {
    ("utg", "hijack", "cutoff"): ThreeBetDefensePolicy(0.035, 0.016),
    ("utg", "hijack", "button"): ThreeBetDefensePolicy(0.036, 0.016),
    ("utg", "hijack", "small_blind"): ThreeBetDefensePolicy(0.037, 0.017),
    ("utg", "hijack", "big_blind"): ThreeBetDefensePolicy(0.038, 0.017),
    ("utg", "cutoff", "button"): ThreeBetDefensePolicy(0.040, 0.018),
    ("utg", "cutoff", "small_blind"): ThreeBetDefensePolicy(0.041, 0.018),
    ("utg", "cutoff", "big_blind"): ThreeBetDefensePolicy(0.043, 0.019),
    ("utg", "button", "small_blind"): ThreeBetDefensePolicy(0.045, 0.020),
    ("utg", "button", "big_blind"): ThreeBetDefensePolicy(0.047, 0.021),
    ("utg", "small_blind", "big_blind"): ThreeBetDefensePolicy(0.050, 0.022),
    ("hijack", "cutoff", "button"): ThreeBetDefensePolicy(0.043, 0.019),
    ("hijack", "cutoff", "small_blind"): ThreeBetDefensePolicy(0.044, 0.020),
    ("hijack", "cutoff", "big_blind"): ThreeBetDefensePolicy(0.046, 0.021),
    ("hijack", "button", "small_blind"): ThreeBetDefensePolicy(0.050, 0.022),
    ("hijack", "button", "big_blind"): ThreeBetDefensePolicy(0.052, 0.023),
    ("hijack", "small_blind", "big_blind"): ThreeBetDefensePolicy(0.055, 0.024),
    ("cutoff", "button", "small_blind"): ThreeBetDefensePolicy(0.055, 0.024),
    ("cutoff", "button", "big_blind"): ThreeBetDefensePolicy(0.058, 0.025),
    ("cutoff", "small_blind", "big_blind"): ThreeBetDefensePolicy(0.062, 0.027),
    ("button", "small_blind", "big_blind"): ThreeBetDefensePolicy(0.070, 0.030),
}

# Hero 3-bet responses to a 4-bet from the original opener. These are shares of
# all 169 starting-hand classes and remain intentionally tighter than the
# corresponding 3-bet ranges.
FOUR_BET_DEFENSE_POLICIES: dict[
    tuple[Position, Position], FourBetDefensePolicy
] = {
    ("utg", "hijack"): FourBetDefensePolicy(0.030, 0.018),
    ("utg", "cutoff"): FourBetDefensePolicy(0.032, 0.020),
    ("utg", "button"): FourBetDefensePolicy(0.035, 0.020),
    ("utg", "small_blind"): FourBetDefensePolicy(0.038, 0.022),
    ("utg", "big_blind"): FourBetDefensePolicy(0.040, 0.022),
    ("hijack", "cutoff"): FourBetDefensePolicy(0.038, 0.022),
    ("hijack", "button"): FourBetDefensePolicy(0.042, 0.024),
    ("hijack", "small_blind"): FourBetDefensePolicy(0.045, 0.025),
    ("hijack", "big_blind"): FourBetDefensePolicy(0.047, 0.026),
    ("cutoff", "button"): FourBetDefensePolicy(0.050, 0.028),
    ("cutoff", "small_blind"): FourBetDefensePolicy(0.055, 0.030),
    ("cutoff", "big_blind"): FourBetDefensePolicy(0.058, 0.032),
    ("button", "small_blind"): FourBetDefensePolicy(0.065, 0.035),
    ("button", "big_blind"): FourBetDefensePolicy(0.070, 0.038),
    ("small_blind", "big_blind"): FourBetDefensePolicy(0.080, 0.042),
}

# Responses after hero 3-bets and a later third player cold 4-bets while the
# original opener folds. Explicit three-seat keys keep dead-money and range
# assumptions tied to the represented action order.
COLD_FOUR_BET_POLICY_NAME = "conservative_heads_up_after_opener_folds"
COLD_FOUR_BET_DEFENSE_POLICIES: dict[
    tuple[Position, Position, Position], FourBetDefensePolicy
] = {
    ("utg", "hijack", "cutoff"): FourBetDefensePolicy(0.022, 0.014),
    ("utg", "hijack", "button"): FourBetDefensePolicy(0.024, 0.015),
    ("utg", "hijack", "small_blind"): FourBetDefensePolicy(0.025, 0.015),
    ("utg", "hijack", "big_blind"): FourBetDefensePolicy(0.026, 0.016),
    ("utg", "cutoff", "button"): FourBetDefensePolicy(0.027, 0.016),
    ("utg", "cutoff", "small_blind"): FourBetDefensePolicy(0.028, 0.017),
    ("utg", "cutoff", "big_blind"): FourBetDefensePolicy(0.030, 0.018),
    ("utg", "button", "small_blind"): FourBetDefensePolicy(0.032, 0.019),
    ("utg", "button", "big_blind"): FourBetDefensePolicy(0.034, 0.020),
    ("utg", "small_blind", "big_blind"): FourBetDefensePolicy(0.036, 0.021),
    ("hijack", "cutoff", "button"): FourBetDefensePolicy(0.030, 0.018),
    ("hijack", "cutoff", "small_blind"): FourBetDefensePolicy(0.031, 0.019),
    ("hijack", "cutoff", "big_blind"): FourBetDefensePolicy(0.033, 0.020),
    ("hijack", "button", "small_blind"): FourBetDefensePolicy(0.035, 0.021),
    ("hijack", "button", "big_blind"): FourBetDefensePolicy(0.037, 0.022),
    ("hijack", "small_blind", "big_blind"): FourBetDefensePolicy(0.040, 0.024),
    ("cutoff", "button", "small_blind"): FourBetDefensePolicy(0.040, 0.024),
    ("cutoff", "button", "big_blind"): FourBetDefensePolicy(0.043, 0.026),
    ("cutoff", "small_blind", "big_blind"): FourBetDefensePolicy(0.047, 0.028),
    ("button", "small_blind", "big_blind"): FourBetDefensePolicy(0.055, 0.032),
}

# The standard band preserves the 2.5 BB matchup chart. Adjacent bands make
# modest, monotonic changes instead of pretending to solve a continuous tree.
OPEN_SIZE_POLICIES: tuple[OpenSizePolicy, ...] = (
    OpenSizePolicy("small", 2.25, 1.10, 1.05),
    OpenSizePolicy("standard", 2.75, 1.00, 1.00),
    OpenSizePolicy("large", 3.25, 0.90, 0.95),
    OpenSizePolicy("very_large", 4.00, 0.78, 0.90),
)

ISOLATION_RAISE_SIZE_POLICIES: tuple[OpenSizePolicy, ...] = (
    OpenSizePolicy("small", 3.0, 1.08, 1.05),
    OpenSizePolicy("standard", 4.0, 1.00, 1.00),
    OpenSizePolicy(
        "large",
        MAX_SUPPORTED_ISOLATION_RAISE_SIZE_BB,
        0.88,
        0.92,
    ),
)

LIMP_RERAISE_SIZE_POLICIES: tuple[ThreeBetSizePolicy, ...] = (
    ThreeBetSizePolicy("small", 2.25, 1.05, 1.05),
    ThreeBetSizePolicy("standard", 2.75, 1.00, 1.00),
    ThreeBetSizePolicy("large", 3.25, 0.90, 0.95),
    ThreeBetSizePolicy(
        "very_large",
        MAX_SUPPORTED_LIMP_RERAISE_TO_ISOLATION_RATIO,
        0.80,
        0.90,
    ),
)

SINGLE_CALLER_POLICY = CallerAdjustmentPolicy(
    name="single_caller_conservative",
    continue_multiplier=0.90,
    reraise_multiplier=0.90,
    squeeze_open_multiple=4.0,
)

DOUBLE_CALLER_POLICY = CallerAdjustmentPolicy(
    name="double_caller_conservative",
    continue_multiplier=0.80,
    reraise_multiplier=0.85,
    squeeze_open_multiple=5.0,
)

TRIPLE_CALLER_POLICY = CallerAdjustmentPolicy(
    name="triple_caller_conservative",
    continue_multiplier=0.70,
    reraise_multiplier=0.80,
    squeeze_open_multiple=6.0,
)

FOUR_CALLER_POLICY = CallerAdjustmentPolicy(
    name="four_caller_conservative",
    continue_multiplier=0.60,
    reraise_multiplier=0.75,
    squeeze_open_multiple=7.0,
)

CALLER_ADJUSTMENT_POLICIES: dict[int, CallerAdjustmentPolicy] = {
    1: SINGLE_CALLER_POLICY,
    2: DOUBLE_CALLER_POLICY,
    3: TRIPLE_CALLER_POLICY,
    4: FOUR_CALLER_POLICY,
}

THREE_BET_SIZE_POLICIES: tuple[ThreeBetSizePolicy, ...] = (
    ThreeBetSizePolicy("small", 2.75, 1.05, 1.05),
    ThreeBetSizePolicy("standard", 3.50, 1.00, 1.00),
    ThreeBetSizePolicy("large", 4.25, 0.90, 0.95),
    ThreeBetSizePolicy(
        "very_large",
        MAX_SUPPORTED_THREE_BET_TO_OPEN_RATIO,
        0.80,
        0.90,
    ),
)

FOUR_BET_SIZE_POLICIES: tuple[FourBetSizePolicy, ...] = (
    FourBetSizePolicy("small", 2.10, 1.05, 1.05),
    FourBetSizePolicy("standard", 2.50, 1.00, 1.00),
    FourBetSizePolicy("large", 3.00, 0.90, 0.95),
    FourBetSizePolicy(
        "very_large",
        MAX_SUPPORTED_FOUR_BET_TO_THREE_BET_RATIO,
        0.80,
        0.90,
    ),
)

# Stack bands keep the chart explicit and deterministic. Shorter stacks trim
# speculative opens/calls and move more of the continuing range into reraises.
STACK_DEPTH_POLICIES: tuple[StackDepthPolicy, ...] = (
    StackDepthPolicy("short", 20.0, 0.90, 0.90, 1.30, 2.20),
    StackDepthPolicy("medium", 50.0, 0.95, 0.95, 1.15, 2.30),
    StackDepthPolicy("standard", 150.0, 1.00, 1.00, 1.00, 2.50),
    StackDepthPolicy("deep", None, 1.03, 1.05, 0.90, 2.50),
)

POSITION_LABELS: dict[Position, str] = {
    "utg": "UTG",
    "hijack": "hijack",
    "cutoff": "cutoff",
    "button": "button",
    "small_blind": "small blind",
    "big_blind": "big blind",
}


def solve_preflop_chart(request: RecommendationRequest) -> RecommendationResult | None:
    state = request.state
    context = resolve_preflop_chart_context(request)
    if context is None:
        return None

    position = context.hero_position

    hand_class = canonical_hand_class(state.hero_cards)
    top_fraction = hand_top_fraction(state.hero_cards)
    policy = POSITION_POLICIES[position]
    effective_stack = state.effective_stack or 0
    stack_policy = policy_for_stack_depth(effective_stack)
    if stack_policy is None:
        return None

    if context.scenario == "heads_up_limp_big_blind":
        return _solve_heads_up_limp_big_blind(
            request=request,
            context=context,
            hand_class=hand_class,
            top_fraction=top_fraction,
            stack_policy=stack_policy,
        )

    if context.scenario in {
        "two_limpers_big_blind",
        "three_limpers_big_blind",
        "four_limpers_big_blind",
        "five_limpers_big_blind",
    }:
        return _solve_multiple_limpers_big_blind(
            request=request,
            context=context,
            hand_class=hand_class,
            top_fraction=top_fraction,
            stack_policy=stack_policy,
        )

    if context.scenario == "facing_isolation_raise_after_limp":
        return _solve_facing_isolation_raise(
            request=request,
            context=context,
            hand_class=hand_class,
            top_fraction=top_fraction,
            stack_policy=stack_policy,
        )

    if context.scenario == "facing_limp_reraise":
        return _solve_facing_limp_reraise(
            request=request,
            context=context,
            hand_class=hand_class,
            top_fraction=top_fraction,
            stack_policy=stack_policy,
        )

    if context.scenario in {"first_in", "big_blind_option"}:
        if (state.pot_size or 0) > 2.5:
            return None
        if context.scenario == "big_blind_option":
            return _result(
                action="check",
                sizing=None,
                confidence=0.78,
                hand_class=hand_class,
                top_fraction=top_fraction,
                position=position,
                scenario="big_blind_option",
                tier="check_option",
                policy_fraction=None,
                assumptions=[
                    "No amount is required to continue.",
                    "No limper or prior raise is represented in the approved state.",
                    stack_assumption(effective_stack, stack_policy),
                ],
                effective_stack=effective_stack,
                stack_policy=stack_policy,
            )
        open_fraction = adjusted_open_fraction(policy, stack_policy)
        should_open = top_fraction <= open_fraction
        action: RecommendationAction = "raise" if should_open else "fold"
        sizing = _open_size(effective_stack, stack_policy) if should_open else None
        return _result(
            action=action,
            sizing=sizing,
            confidence=_boundary_confidence(top_fraction, open_fraction),
            hand_class=hand_class,
            top_fraction=top_fraction,
            position=position,
            scenario="first_in",
            tier="open" if should_open else "fold",
            policy_fraction=open_fraction,
            assumptions=[
                "The pot is treated as unopened with no limpers or prior hero action.",
                stack_assumption(effective_stack, stack_policy),
                "The chart models a six-max chip-EV training spot before rake.",
            ],
            effective_stack=effective_stack,
            base_open_fraction=policy.open_fraction,
            stack_policy=stack_policy,
        )

    if context.scenario in {
        "facing_three_bet",
        "facing_cold_three_bet",
        "facing_squeeze_after_call",
    }:
        return _solve_facing_three_bet(
            request=request,
            context=context,
            hand_class=hand_class,
            top_fraction=top_fraction,
            stack_policy=stack_policy,
        )
    if context.scenario in {"facing_four_bet", "facing_cold_four_bet"}:
        return _solve_facing_four_bet(
            request=request,
            context=context,
            hand_class=hand_class,
            top_fraction=top_fraction,
            stack_policy=stack_policy,
        )

    opener_position = context.opener_position
    opener_size = context.opening_raise_size
    if opener_position is None or opener_size is None:
        return None
    base_defense_policy = DEFENSE_POLICIES.get((opener_position, position))
    if base_defense_policy is None:
        return None
    base_opener_open_fraction = POSITION_POLICIES[opener_position].open_fraction
    opener_open_fraction = adjusted_open_fraction(
        POSITION_POLICIES[opener_position],
        stack_policy,
    )
    size_policy = policy_for_open_size(opener_size)
    if size_policy is None:
        return None
    defense_policy = adjusted_defense_policy(
        base_defense_policy,
        size_policy,
        stack_policy,
    )
    caller_policy = CALLER_ADJUSTMENT_POLICIES.get(len(context.caller_positions))
    if caller_policy is not None:
        defense_policy = adjusted_caller_defense_policy(
            defense_policy,
            caller_policy,
        )
    maximum_reraise_total = _maximum_reraise_total(
        effective_stack=effective_stack,
        hero_stack=state.hero_stack,
        hero_position=position,
        opener_size=opener_size,
    )
    reraise_size = _reraise_size(
        opener_size,
        state.pot_size or 0,
        maximum_reraise_total,
        caller_policy.squeeze_open_multiple if caller_policy is not None else None,
    )

    can_reraise = (
        reraise_size > opener_size
        and top_fraction <= defense_policy.reraise_fraction
    )
    if can_reraise:
        action = "raise"
        sizing = reraise_size
        tier = "squeeze" if caller_policy is not None else "reraise"
        boundary = defense_policy.reraise_fraction
    elif top_fraction <= defense_policy.continue_fraction:
        action = "call"
        sizing = None
        tier = "overcall" if caller_policy is not None else "defend"
        boundary = defense_policy.continue_fraction
    else:
        action = "fold"
        sizing = None
        tier = "fold"
        boundary = defense_policy.continue_fraction

    if caller_policy is not None:
        caller_labels = [
            POSITION_LABELS[caller_position]
            for caller_position in context.caller_positions
        ]
        if len(caller_labels) == 1:
            scenario = "facing_open_with_caller"
            action_assumptions = [
                "The structured preflop history contains one open and one call with no other active player.",
                f"The caller is attributed to {caller_labels[0]}.",
                "The conservative single-caller adjustment tightens both continuing and squeezing ranges.",
            ]
        elif len(caller_labels) == 2:
            scenario = "facing_open_with_callers"
            action_assumptions = [
                "The structured preflop history contains one open and exactly two calls with no other active player.",
                f"The callers are attributed to {caller_labels[0]} and {caller_labels[1]}.",
                "The conservative double-caller adjustment further tightens continuing and squeezing ranges.",
            ]
        elif len(caller_labels) == 3:
            scenario = "facing_open_with_three_callers"
            action_assumptions = [
                "The structured preflop history contains one open and exactly three calls with no other active player.",
                f"The callers are attributed to {', '.join(caller_labels[:-1])}, and {caller_labels[-1]}.",
                "The conservative triple-caller adjustment further tightens continuing and squeezing ranges.",
            ]
        else:
            scenario = "facing_open_with_four_callers"
            action_assumptions = [
                "The structured preflop history contains one open and exactly four calls with no other active player.",
                f"The callers are attributed to {', '.join(caller_labels[:-1])}, and {caller_labels[-1]}.",
                "The conservative four-caller adjustment applies the tightest full-table continuing and squeezing ranges.",
            ]
    else:
        scenario = "facing_open_raise"
        action_assumptions = [
            "The approved state represents one open raise with no callers or prior hero action.",
        ]

    return _result(
        action=action,
        sizing=sizing,
        confidence=_boundary_confidence(top_fraction, boundary),
        hand_class=hand_class,
        top_fraction=top_fraction,
        position=position,
        scenario=scenario,
        tier=tier,
        policy_fraction=boundary,
        assumptions=[
            *action_assumptions,
            f"The opening raise is attributed to {POSITION_LABELS[opener_position]}.",
            f"The defense chart uses matchup-specific {POSITION_LABELS[position]}-versus-"
            f"{POSITION_LABELS[opener_position]} boundaries.",
            f"The opener model adjusts the {POSITION_LABELS[opener_position]}'s "
            f"{base_opener_open_fraction:.0%} base first-in range to "
            f"{opener_open_fraction:.1%} for this stack depth.",
            f"The {opener_size:g} BB opening size uses the {size_policy.name.replace('_', ' ')} "
            "open adjustment.",
            stack_assumption(effective_stack, stack_policy),
            "The chart models a six-max chip-EV training spot before rake.",
        ],
        effective_stack=effective_stack,
        opener_position=opener_position,
        base_opener_open_fraction=base_opener_open_fraction,
        opener_open_fraction=opener_open_fraction,
        opening_raise_size=opener_size,
        maximum_reraise_total=maximum_reraise_total,
        caller_positions=context.caller_positions,
        caller_adjustment_policy=caller_policy,
        base_defense_policy=base_defense_policy,
        defense_policy=defense_policy,
        size_policy=size_policy,
        stack_policy=stack_policy,
    )


def _solve_heads_up_limp_big_blind(
    *,
    request: RecommendationRequest,
    context: PreflopChartContext,
    hand_class: str,
    top_fraction: float,
    stack_policy: StackDepthPolicy,
) -> RecommendationResult | None:
    state = request.state
    limper_position = context.limper_position
    limp_size = context.limp_size
    if (
        limper_position is None
        or limp_size is None
        or state.effective_stack is None
    ):
        return None
    policy = LIMP_RESPONSE_POLICIES.get(limper_position)
    if policy is None:
        return None

    raise_fraction = adjusted_limp_raise_fraction(policy, stack_policy)
    maximum_raise_total = round(state.effective_stack + 1.0, 2)
    target_raise_size = round(max(4.0, (state.pot_size or 0) * 1.5), 2)
    raise_size = round(min(target_raise_size, maximum_raise_total), 2)
    should_raise = raise_size > 1.0 and top_fraction <= raise_fraction
    action: RecommendationAction = "raise" if should_raise else "check"
    sizing = raise_size if should_raise else None

    return _result(
        action=action,
        sizing=sizing,
        confidence=_boundary_confidence(top_fraction, raise_fraction),
        hand_class=hand_class,
        top_fraction=top_fraction,
        position="big_blind",
        scenario="heads_up_limp_big_blind",
        tier="isolation_raise" if should_raise else "check_option",
        policy_fraction=raise_fraction,
        assumptions=[
            (
                "The structured preflop history contains one 1 BB limp and "
                "no raise."
            ),
            "Exactly two players remain active and hero has the big-blind option.",
            f"The limp is attributed to {POSITION_LABELS[limper_position]}.",
            stack_assumption(state.effective_stack, stack_policy),
            "The chart models a six-max chip-EV training spot before rake.",
        ],
        effective_stack=state.effective_stack,
        limper_position=limper_position,
        limp_size=limp_size,
        base_limp_raise_fraction=policy.raise_fraction,
        limp_raise_fraction=raise_fraction,
        target_limp_raise_size=target_raise_size,
        maximum_limp_raise_total=maximum_raise_total,
        limp_response_policy=LIMP_RESPONSE_POLICY_NAME,
        stack_policy=stack_policy,
    )


def _solve_multiple_limpers_big_blind(
    *,
    request: RecommendationRequest,
    context: PreflopChartContext,
    hand_class: str,
    top_fraction: float,
    stack_policy: StackDepthPolicy,
) -> RecommendationResult | None:
    state = request.state
    limper_positions = context.limper_positions
    if state.effective_stack is None:
        return None
    if context.scenario == "two_limpers_big_blind" and len(limper_positions) == 2:
        policy = TWO_LIMPER_RESPONSE_POLICIES.get(
            (limper_positions[0], limper_positions[1])
        )
        response_policy_name = TWO_LIMPER_RESPONSE_POLICY_NAME
        minimum_target = 5.0
    elif (
        context.scenario == "three_limpers_big_blind"
        and len(limper_positions) == 3
    ):
        policy = THREE_LIMPER_RESPONSE_POLICIES.get(
            (
                limper_positions[0],
                limper_positions[1],
                limper_positions[2],
            )
        )
        response_policy_name = THREE_LIMPER_RESPONSE_POLICY_NAME
        minimum_target = 6.0
    elif (
        context.scenario == "four_limpers_big_blind"
        and len(limper_positions) == 4
    ):
        policy = FOUR_LIMPER_RESPONSE_POLICIES.get(
            (
                limper_positions[0],
                limper_positions[1],
                limper_positions[2],
                limper_positions[3],
            )
        )
        response_policy_name = FOUR_LIMPER_RESPONSE_POLICY_NAME
        minimum_target = 7.0
    elif (
        context.scenario == "five_limpers_big_blind"
        and len(limper_positions) == 5
    ):
        policy = FIVE_LIMPER_RESPONSE_POLICIES.get(
            (
                limper_positions[0],
                limper_positions[1],
                limper_positions[2],
                limper_positions[3],
                limper_positions[4],
            )
        )
        response_policy_name = FIVE_LIMPER_RESPONSE_POLICY_NAME
        minimum_target = 8.0
    else:
        return None
    if policy is None:
        return None

    raise_fraction = adjusted_limp_raise_fraction(policy, stack_policy)
    maximum_raise_total = round(state.effective_stack + 1.0, 2)
    target_raise_size = round(
        max(minimum_target, (state.pot_size or 0) * 1.5),
        2,
    )
    raise_size = round(min(target_raise_size, maximum_raise_total), 2)
    should_raise = raise_size > 1.0 and top_fraction <= raise_fraction
    action: RecommendationAction = "raise" if should_raise else "check"
    sizing = raise_size if should_raise else None

    limper_labels = " and ".join(
        POSITION_LABELS[position] for position in limper_positions
    )
    return _result(
        action=action,
        sizing=sizing,
        confidence=_boundary_confidence(top_fraction, raise_fraction),
        hand_class=hand_class,
        top_fraction=top_fraction,
        position="big_blind",
        scenario=context.scenario,
        tier="isolation_raise" if should_raise else "check_option",
        policy_fraction=raise_fraction,
        assumptions=[
            (
                "The structured preflop history contains exactly "
                f"{len(limper_positions)} ordered 1 BB limps and no raise."
            ),
            (
                f"Exactly {len(limper_positions) + 1} players remain active "
                "and hero has the big-blind option."
            ),
            f"The limps are attributed to {limper_labels}.",
            stack_assumption(state.effective_stack, stack_policy),
            "The chart models a six-max chip-EV training spot before rake.",
        ],
        effective_stack=state.effective_stack,
        limper_positions=limper_positions,
        limp_size=context.limp_size,
        base_multi_limp_raise_fraction=policy.raise_fraction,
        multi_limp_raise_fraction=raise_fraction,
        target_multi_limp_raise_size=target_raise_size,
        maximum_multi_limp_raise_total=maximum_raise_total,
        multi_limp_response_policy=response_policy_name,
        stack_policy=stack_policy,
    )


def _solve_facing_isolation_raise(
    *,
    request: RecommendationRequest,
    context: PreflopChartContext,
    hand_class: str,
    top_fraction: float,
    stack_policy: StackDepthPolicy,
) -> RecommendationResult | None:
    state = request.state
    hero_position = context.hero_position
    isolation_raiser_position = context.latest_aggressor_position
    isolation_raise_size = context.latest_raise_size
    hero_commitment = context.hero_prior_commitment
    if (
        isolation_raiser_position is None
        or isolation_raise_size is None
        or hero_commitment is None
        or state.hero_stack is None
        or state.effective_stack is None
    ):
        return None
    base_policy = ISOLATION_RESPONSE_POLICIES.get(
        (hero_position, isolation_raiser_position)
    )
    size_policy = policy_for_isolation_raise_size(isolation_raise_size)
    if base_policy is None or size_policy is None:
        return None
    defense_policy = adjusted_defense_policy(
        base_policy,
        size_policy,
        stack_policy,
    )
    maximum_reraise_total = min(
        state.hero_stack + hero_commitment,
        state.effective_stack + isolation_raise_size,
    )
    reraise_size = _reraise_size(
        isolation_raise_size,
        state.pot_size or 0,
        maximum_reraise_total,
    )
    can_reraise = (
        reraise_size > isolation_raise_size
        and top_fraction <= defense_policy.reraise_fraction
    )
    if can_reraise:
        action: RecommendationAction = "raise"
        sizing = reraise_size
        tier = "limp_reraise"
        boundary = defense_policy.reraise_fraction
    elif top_fraction <= defense_policy.continue_fraction:
        action = "call"
        sizing = None
        tier = "continue"
        boundary = defense_policy.continue_fraction
    else:
        action = "fold"
        sizing = None
        tier = "fold"
        boundary = defense_policy.continue_fraction

    return _result(
        action=action,
        sizing=sizing,
        confidence=_boundary_confidence(top_fraction, boundary),
        hand_class=hand_class,
        top_fraction=top_fraction,
        position=hero_position,
        scenario="facing_isolation_raise_after_limp",
        tier=tier,
        policy_fraction=boundary,
        assumptions=[
            "The structured preflop history contains one 1 BB hero limp and one later-position isolation raise.",
            "Exactly two players remain active, so all other players are treated as folded and action has returned to hero.",
            f"The isolation raise is attributed to {POSITION_LABELS[isolation_raiser_position]}.",
            f"The {isolation_raise_size:g} BB isolation size uses the {size_policy.name.replace('_', ' ')} response adjustment.",
            stack_assumption(state.effective_stack, stack_policy),
            "The chart models a six-max chip-EV training spot before rake.",
        ],
        effective_stack=state.effective_stack,
        limper_position=hero_position,
        limp_size=hero_commitment,
        isolation_raiser_position=isolation_raiser_position,
        isolation_raise_size=isolation_raise_size,
        maximum_reraise_total=round(maximum_reraise_total, 2),
        base_defense_policy=base_policy,
        defense_policy=defense_policy,
        isolation_size_policy=size_policy,
        isolation_response_policy=ISOLATION_RESPONSE_POLICY_NAME,
        stack_policy=stack_policy,
    )


def _solve_facing_limp_reraise(
    *,
    request: RecommendationRequest,
    context: PreflopChartContext,
    hand_class: str,
    top_fraction: float,
    stack_policy: StackDepthPolicy,
) -> RecommendationResult | None:
    state = request.state
    hero_position = context.hero_position
    limper_position = context.limper_position
    hero_isolation_raise_size = context.hero_isolation_raise_size
    limp_reraise_size = context.latest_raise_size
    if (
        limper_position is None
        or hero_isolation_raise_size is None
        or limp_reraise_size is None
        or state.hero_stack is None
        or state.effective_stack is None
    ):
        return None
    base_policy = LIMP_RERAISE_RESPONSE_POLICIES.get(
        (limper_position, hero_position)
    )
    size_policy = policy_for_limp_reraise_size(
        limp_reraise_size / hero_isolation_raise_size
    )
    if base_policy is None or size_policy is None:
        return None
    defense_policy = adjusted_three_bet_defense_policy(
        base_policy,
        size_policy,
        stack_policy,
    )
    maximum_four_bet_total = min(
        state.hero_stack + hero_isolation_raise_size,
        state.effective_stack + limp_reraise_size,
    )
    four_bet_size = round(
        min(
            max(limp_reraise_size * 2.2, (state.pot_size or 0) * 0.9),
            maximum_four_bet_total,
        ),
        2,
    )
    can_four_bet = (
        four_bet_size > limp_reraise_size
        and top_fraction <= defense_policy.four_bet_fraction
    )
    if can_four_bet:
        action: RecommendationAction = "raise"
        sizing = four_bet_size
        tier = "four_bet"
        boundary = defense_policy.four_bet_fraction
    elif top_fraction <= defense_policy.continue_fraction:
        action = "call"
        sizing = None
        tier = "continue"
        boundary = defense_policy.continue_fraction
    else:
        action = "fold"
        sizing = None
        tier = "fold"
        boundary = defense_policy.continue_fraction

    ratio = limp_reraise_size / hero_isolation_raise_size
    return _result(
        action=action,
        sizing=sizing,
        confidence=_boundary_confidence(top_fraction, boundary),
        hand_class=hand_class,
        top_fraction=top_fraction,
        position=hero_position,
        scenario="facing_limp_reraise",
        tier=tier,
        policy_fraction=boundary,
        assumptions=[
            (
                "The structured preflop history contains one opponent limp, "
                "one hero isolation raise, and a reraise by the original limper."
            ),
            (
                "Exactly two players remain active, so all other players are "
                "treated as folded and action has returned to hero."
            ),
            f"The original limp and reraise are attributed to {POSITION_LABELS[limper_position]}.",
            (
                f"The {limp_reraise_size:g} BB limp-reraise is {ratio:.2f}x "
                "hero's isolation raise and uses the "
                f"{size_policy.name.replace('_', ' ')} response adjustment."
            ),
            stack_assumption(state.effective_stack, stack_policy),
            "The chart models a six-max chip-EV training spot before rake.",
        ],
        effective_stack=state.effective_stack,
        limper_position=limper_position,
        limp_size=context.limp_size,
        hero_isolation_raise_size=hero_isolation_raise_size,
        limp_reraiser_position=limper_position,
        limp_reraise_size=limp_reraise_size,
        maximum_four_bet_total=round(maximum_four_bet_total, 2),
        base_limp_reraise_defense_policy=base_policy,
        limp_reraise_defense_policy=defense_policy,
        limp_reraise_size_policy=size_policy,
        limp_reraise_response_policy=LIMP_RERAISE_RESPONSE_POLICY_NAME,
        stack_policy=stack_policy,
    )


def _solve_facing_three_bet(
    *,
    request: RecommendationRequest,
    context: PreflopChartContext,
    hand_class: str,
    top_fraction: float,
    stack_policy: StackDepthPolicy,
) -> RecommendationResult | None:
    state = request.state
    hero_position = context.hero_position
    opener_position = context.opener_position
    three_bettor_position = context.latest_aggressor_position
    opener_size = context.opening_raise_size
    three_bet_size = context.latest_raise_size
    if (
        opener_position is None
        or three_bettor_position is None
        or opener_size is None
        or three_bet_size is None
        or state.hero_stack is None
        or state.effective_stack is None
    ):
        return None
    squeeze_after_call = context.scenario == "facing_squeeze_after_call"
    cold_three_bet = context.scenario == "facing_cold_three_bet"
    if squeeze_after_call:
        if context.hero_prior_commitment is None:
            return None
        base_policy = SQUEEZE_DEFENSE_POLICIES.get(
            (opener_position, hero_position, three_bettor_position)
        )
        hero_committed = context.hero_prior_commitment
        policy_source = "hero_opener_squeezer_size_stack_matchup"
    elif cold_three_bet:
        base_policy = COLD_THREE_BET_DEFENSE_POLICIES.get(
            (opener_position, three_bettor_position, hero_position)
        )
        hero_committed = POSTED_BLIND_BB[hero_position]
        policy_source = "hero_opener_three_bettor_size_stack_matchup"
    else:
        base_policy = THREE_BET_DEFENSE_POLICIES.get(
            (hero_position, three_bettor_position)
        )
        hero_committed = opener_size
        policy_source = "hero_three_bettor_size_stack_matchup"
    if base_policy is None:
        return None
    size_policy = policy_for_three_bet_size(three_bet_size / opener_size)
    if size_policy is None:
        return None
    defense_policy = adjusted_three_bet_defense_policy(
        base_policy,
        size_policy,
        stack_policy,
    )
    maximum_four_bet_total = min(
        state.hero_stack + hero_committed,
        state.effective_stack + three_bet_size,
    )
    four_bet_size = round(
        min(
            max(three_bet_size * 2.2, (state.pot_size or 0) * 0.9),
            maximum_four_bet_total,
        ),
        2,
    )
    can_four_bet = (
        four_bet_size > three_bet_size
        and top_fraction <= defense_policy.four_bet_fraction
    )
    if can_four_bet:
        action: RecommendationAction = "raise"
        sizing = four_bet_size
        tier = "four_bet"
        boundary = defense_policy.four_bet_fraction
    elif top_fraction <= defense_policy.continue_fraction:
        action = "call"
        sizing = None
        tier = "continue"
        boundary = defense_policy.continue_fraction
    else:
        action = "fold"
        sizing = None
        tier = "fold"
        boundary = defense_policy.continue_fraction

    if squeeze_after_call:
        scenario = "facing_squeeze_after_call"
        action_assumptions = [
            (
                "The structured preflop history contains one opponent open, "
                "one hero cold-call, and one later-position squeeze."
            ),
            (
                "Exactly two players remain active, so the original opener "
                "is treated as folded."
            ),
            (
                "The conservative squeeze-response chart uses the "
                f"{POSITION_LABELS[opener_position]}-"
                f"{POSITION_LABELS[hero_position]}-"
                f"{POSITION_LABELS[three_bettor_position]} seat order."
            ),
        ]
    elif cold_three_bet:
        scenario = "facing_cold_three_bet"
        action_assumptions = [
            "The structured preflop history contains one opponent open and one opponent 3-bet before hero acts.",
            "Exactly three players remain active and no caller is represented.",
            f"The conservative cold 3-bet chart uses the {POSITION_LABELS[opener_position]}-"
            f"{POSITION_LABELS[three_bettor_position]}-{POSITION_LABELS[hero_position]} seat order.",
        ]
    else:
        scenario = "facing_three_bet"
        action_assumptions = [
            "The structured preflop history contains one hero open and one later-position 3-bet with no callers.",
            f"The chart uses matchup-specific {POSITION_LABELS[hero_position]}-versus-"
            f"{POSITION_LABELS[three_bettor_position]} 3-bet defense boundaries.",
        ]

    return _result(
        action=action,
        sizing=sizing,
        confidence=_boundary_confidence(top_fraction, boundary),
        hand_class=hand_class,
        top_fraction=top_fraction,
        position=hero_position,
        scenario=scenario,
        tier=tier,
        policy_fraction=boundary,
        assumptions=[
            *action_assumptions,
            f"The opening raise is attributed to {POSITION_LABELS[opener_position]}.",
            f"The 3-bet is attributed to {POSITION_LABELS[three_bettor_position]}.",
            f"The {three_bet_size:g} BB 3-bet is {three_bet_size / opener_size:.2f}x the open "
            f"and uses the {size_policy.name.replace('_', ' ')} size adjustment.",
            stack_assumption(state.effective_stack, stack_policy),
            "The chart models a six-max chip-EV training spot before rake.",
        ],
        effective_stack=state.effective_stack,
        opener_position=opener_position,
        opening_raise_size=opener_size,
        three_bettor_position=three_bettor_position,
        three_bet_size=three_bet_size,
        maximum_four_bet_total=maximum_four_bet_total,
        base_three_bet_defense_policy=base_policy,
        three_bet_defense_policy=defense_policy,
        three_bet_size_policy=size_policy,
        three_bet_policy_source=policy_source,
        cold_three_bet_policy=(
            COLD_THREE_BET_POLICY_NAME if cold_three_bet else None
        ),
        hero_prior_commitment=(
            context.hero_prior_commitment if squeeze_after_call else None
        ),
        squeeze_response_policy=(
            SQUEEZE_RESPONSE_POLICY_NAME if squeeze_after_call else None
        ),
        stack_policy=stack_policy,
    )


def _solve_facing_four_bet(
    *,
    request: RecommendationRequest,
    context: PreflopChartContext,
    hand_class: str,
    top_fraction: float,
    stack_policy: StackDepthPolicy,
) -> RecommendationResult | None:
    state = request.state
    hero_position = context.hero_position
    opener_position = context.opener_position
    hero_three_bet_size = context.hero_three_bet_size
    four_bettor_position = context.latest_aggressor_position
    four_bet_size = context.latest_raise_size
    if (
        opener_position is None
        or hero_three_bet_size is None
        or four_bettor_position is None
        or four_bet_size is None
        or state.hero_stack is None
        or state.effective_stack is None
    ):
        return None
    cold_four_bet = context.scenario == "facing_cold_four_bet"
    if cold_four_bet:
        base_policy = COLD_FOUR_BET_DEFENSE_POLICIES.get(
            (opener_position, hero_position, four_bettor_position)
        )
        policy_source = "hero_opener_cold_four_bettor_size_stack_matchup"
    else:
        base_policy = FOUR_BET_DEFENSE_POLICIES.get(
            (opener_position, hero_position)
        )
        policy_source = "hero_opener_four_bet_size_stack_matchup"
    if base_policy is None:
        return None
    size_policy = policy_for_four_bet_size(four_bet_size / hero_three_bet_size)
    if size_policy is None:
        return None
    defense_policy = adjusted_four_bet_defense_policy(
        base_policy,
        size_policy,
        stack_policy,
    )
    maximum_five_bet_total = min(
        state.hero_stack + hero_three_bet_size,
        state.effective_stack + four_bet_size,
    )
    can_five_bet = (
        maximum_five_bet_total > four_bet_size
        and top_fraction <= defense_policy.five_bet_fraction
    )
    if can_five_bet:
        action: RecommendationAction = "raise"
        sizing = round(maximum_five_bet_total, 2)
        tier = "five_bet_all_in"
        boundary = defense_policy.five_bet_fraction
    elif top_fraction <= defense_policy.continue_fraction:
        action = "call"
        sizing = None
        tier = "continue"
        boundary = defense_policy.continue_fraction
    else:
        action = "fold"
        sizing = None
        tier = "fold"
        boundary = defense_policy.continue_fraction

    if cold_four_bet:
        scenario = "facing_cold_four_bet"
        action_assumptions = [
            (
                "The structured preflop history contains one opponent open, "
                "one hero 3-bet, and one later-position cold 4-bet."
            ),
            (
                "Exactly two players remain active, so the original opener "
                "is treated as folded."
            ),
            (
                "The conservative cold 4-bet chart uses the "
                f"{POSITION_LABELS[opener_position]}-"
                f"{POSITION_LABELS[hero_position]}-"
                f"{POSITION_LABELS[four_bettor_position]} seat order."
            ),
        ]
    else:
        scenario = "facing_four_bet"
        action_assumptions = [
            (
                "The structured preflop history contains one opponent open, "
                "one hero 3-bet, and one opener 4-bet."
            ),
            "Exactly two players remain active and action has returned to hero.",
            f"The chart uses matchup-specific {POSITION_LABELS[hero_position]}-versus-"
            f"{POSITION_LABELS[opener_position]} 4-bet response boundaries.",
        ]

    return _result(
        action=action,
        sizing=sizing,
        confidence=_boundary_confidence(top_fraction, boundary),
        hand_class=hand_class,
        top_fraction=top_fraction,
        position=hero_position,
        scenario=scenario,
        tier=tier,
        policy_fraction=boundary,
        assumptions=[
            *action_assumptions,
            (
                "The 4-bet is attributed to "
                f"{POSITION_LABELS[four_bettor_position]}."
            ),
            f"The {four_bet_size:g} BB 4-bet is "
            f"{four_bet_size / hero_three_bet_size:.2f}x the hero 3-bet and uses the "
            f"{size_policy.name.replace('_', ' ')} size adjustment.",
            stack_assumption(state.effective_stack, stack_policy),
            "Five-bets are modeled as all-in training actions.",
            "The chart models a six-max chip-EV training spot before rake.",
        ],
        effective_stack=state.effective_stack,
        opener_position=opener_position,
        opening_raise_size=context.opening_raise_size,
        three_bettor_position=hero_position,
        three_bet_size=hero_three_bet_size,
        four_bettor_position=four_bettor_position,
        four_bet_size=four_bet_size,
        maximum_five_bet_total=maximum_five_bet_total,
        base_four_bet_defense_policy=base_policy,
        four_bet_defense_policy=defense_policy,
        four_bet_size_policy=size_policy,
        four_bet_policy_source=policy_source,
        cold_four_bet_policy=(
            COLD_FOUR_BET_POLICY_NAME if cold_four_bet else None
        ),
        stack_policy=stack_policy,
    )


def canonical_hand_class(cards: list[Card]) -> str:
    if len(cards) != 2:
        raise ValueError("A preflop hand class requires exactly two cards")
    first, second = sorted(cards, key=lambda card: RANK_INDEX[card.rank])
    if first.rank == second.rank:
        return f"{first.rank}{second.rank}"
    suited = "s" if first.suit == second.suit else "o"
    return f"{first.rank}{second.rank}{suited}"


@lru_cache(maxsize=169)
def _top_fraction_for_class(hand_class: str) -> float:
    scores = _class_scores()
    target = scores[hand_class]
    at_least_as_strong = sum(1 for score in scores.values() if score >= target)
    return round(at_least_as_strong / len(scores), 4)


def hand_top_fraction(cards: list[Card]) -> float:
    return _top_fraction_for_class(canonical_hand_class(cards))


def hand_classes_in_policy_band(
    maximum_fraction: float,
    *,
    minimum_exclusive: float = 0,
) -> tuple[str, ...]:
    if not 0 <= minimum_exclusive < maximum_fraction <= 1:
        raise ValueError("A hand-class policy band must satisfy 0 <= minimum < maximum <= 1")
    return tuple(
        sorted(
            (
                hand_class
                for hand_class in _class_scores()
                if minimum_exclusive
                < _top_fraction_for_class(hand_class)
                <= maximum_fraction
            ),
            key=lambda hand_class: (
                _top_fraction_for_class(hand_class),
                hand_class,
            ),
        )
    )


@lru_cache(maxsize=1)
def _class_scores() -> dict[str, float]:
    scores: dict[str, float] = {}
    for high_index, high_rank in enumerate(RANKS):
        pair = [Card(rank=high_rank, suit="hearts"), Card(rank=high_rank, suit="spades")]
        scores[f"{high_rank}{high_rank}"] = _chart_score(pair)
        for low_rank in RANKS[high_index + 1 :]:
            suited = [Card(rank=high_rank, suit="hearts"), Card(rank=low_rank, suit="hearts")]
            offsuit = [Card(rank=high_rank, suit="hearts"), Card(rank=low_rank, suit="spades")]
            scores[f"{high_rank}{low_rank}s"] = _chart_score(suited)
            scores[f"{high_rank}{low_rank}o"] = _chart_score(offsuit)
    return scores


def _chart_score(cards: list[Card]) -> float:
    score = _starting_hand_score(cards)
    high, low = sorted((14 - RANK_INDEX[card.rank] for card in cards), reverse=True)
    suited = cards[0].suit == cards[1].suit
    if suited and high == 14 and low <= 5:
        score += 12
    if suited and high != low and high - low <= 2:
        score += 6
    return score


def _open_size(effective_stack: float, stack_policy: StackDepthPolicy) -> float:
    return round(min(stack_policy.opening_size, effective_stack), 2)


def _maximum_reraise_total(
    *,
    effective_stack: float,
    hero_stack: float | None,
    hero_position: Position,
    opener_size: float,
) -> float:
    hero_blind = POSTED_BLIND_BB[hero_position]
    if hero_stack is None:
        return effective_stack + hero_blind
    hero_total = hero_stack + hero_blind
    opponent_total = effective_stack + opener_size
    return min(hero_total, opponent_total)


def _reraise_size(
    opener_size: float,
    pot_size: float,
    maximum_total: float,
    squeeze_open_multiple: float | None = None,
) -> float:
    target = max(opener_size * (squeeze_open_multiple or 3), pot_size * 1.1)
    return round(min(target, maximum_total), 2)


def _boundary_confidence(top_fraction: float, boundary: float) -> float:
    distance = abs(top_fraction - boundary)
    return round(min(0.84, 0.62 + distance * 0.8), 2)


def policy_for_open_size(opening_size: float) -> OpenSizePolicy | None:
    return next(
        (policy for policy in OPEN_SIZE_POLICIES if opening_size <= policy.maximum_size),
        None,
    )


def policy_for_isolation_raise_size(
    isolation_raise_size: float,
) -> OpenSizePolicy | None:
    return next(
        (
            policy
            for policy in ISOLATION_RAISE_SIZE_POLICIES
            if isolation_raise_size <= policy.maximum_size
        ),
        None,
    )


def policy_for_limp_reraise_size(
    limp_reraise_to_isolation_ratio: float,
) -> ThreeBetSizePolicy | None:
    return next(
        (
            policy
            for policy in LIMP_RERAISE_SIZE_POLICIES
            if limp_reraise_to_isolation_ratio <= policy.maximum_ratio
        ),
        None,
    )


def policy_for_stack_depth(effective_stack: float) -> StackDepthPolicy | None:
    return next(
        (
            policy
            for policy in STACK_DEPTH_POLICIES
            if policy.maximum_stack is None or effective_stack <= policy.maximum_stack
        ),
        None,
    )


def policy_for_three_bet_size(
    three_bet_to_open_ratio: float,
) -> ThreeBetSizePolicy | None:
    return next(
        (
            policy
            for policy in THREE_BET_SIZE_POLICIES
            if three_bet_to_open_ratio <= policy.maximum_ratio
        ),
        None,
    )


def policy_for_four_bet_size(
    four_bet_to_three_bet_ratio: float,
) -> FourBetSizePolicy | None:
    return next(
        (
            policy
            for policy in FOUR_BET_SIZE_POLICIES
            if four_bet_to_three_bet_ratio <= policy.maximum_ratio
        ),
        None,
    )


def adjusted_open_fraction(
    position_policy: PositionPolicy,
    stack_policy: StackDepthPolicy,
) -> float:
    return round(
        min(1.0, position_policy.open_fraction * stack_policy.open_multiplier),
        4,
    )


def adjusted_limp_raise_fraction(
    policy: LimpResponsePolicy,
    stack_policy: StackDepthPolicy,
) -> float:
    return round(
        min(1.0, policy.raise_fraction * stack_policy.reraise_multiplier),
        4,
    )


def adjusted_defense_policy(
    base_policy: DefensePolicy,
    size_policy: OpenSizePolicy,
    stack_policy: StackDepthPolicy,
) -> DefensePolicy:
    return DefensePolicy(
        continue_fraction=round(
            min(
                1.0,
                base_policy.continue_fraction
                * size_policy.continue_multiplier
                * stack_policy.continue_multiplier,
            ),
            4,
        ),
        reraise_fraction=round(
            min(
                1.0,
                base_policy.reraise_fraction
                * size_policy.reraise_multiplier
                * stack_policy.reraise_multiplier,
            ),
            4,
        ),
    )


def adjusted_caller_defense_policy(
    defense_policy: DefensePolicy,
    caller_policy: CallerAdjustmentPolicy,
) -> DefensePolicy:
    return DefensePolicy(
        continue_fraction=round(
            defense_policy.continue_fraction * caller_policy.continue_multiplier,
            4,
        ),
        reraise_fraction=round(
            defense_policy.reraise_fraction * caller_policy.reraise_multiplier,
            4,
        ),
    )


def adjusted_three_bet_defense_policy(
    base_policy: ThreeBetDefensePolicy,
    size_policy: ThreeBetSizePolicy,
    stack_policy: StackDepthPolicy,
) -> ThreeBetDefensePolicy:
    return ThreeBetDefensePolicy(
        continue_fraction=round(
            min(
                1.0,
                base_policy.continue_fraction
                * size_policy.continue_multiplier
                * stack_policy.continue_multiplier,
            ),
            4,
        ),
        four_bet_fraction=round(
            min(
                1.0,
                base_policy.four_bet_fraction
                * size_policy.four_bet_multiplier
                * stack_policy.reraise_multiplier,
            ),
            4,
        ),
    )


def adjusted_four_bet_defense_policy(
    base_policy: FourBetDefensePolicy,
    size_policy: FourBetSizePolicy,
    stack_policy: StackDepthPolicy,
) -> FourBetDefensePolicy:
    continue_fraction = round(
        min(
            1.0,
            base_policy.continue_fraction
            * size_policy.continue_multiplier
            * stack_policy.continue_multiplier,
        ),
        4,
    )
    return FourBetDefensePolicy(
        continue_fraction=continue_fraction,
        five_bet_fraction=round(
            min(
                continue_fraction,
                base_policy.five_bet_fraction
                * size_policy.five_bet_multiplier
                * stack_policy.reraise_multiplier,
            ),
            4,
        ),
    )


def stack_assumption(
    effective_stack: float,
    stack_policy: StackDepthPolicy,
) -> str:
    return (
        f"The {effective_stack:g} BB effective stack uses the "
        f"{stack_policy.name} stack-depth adjustment."
    )


def _result(
    *,
    action: RecommendationAction,
    sizing: float | None,
    confidence: float,
    hand_class: str,
    top_fraction: float,
    position: Position,
    scenario: str,
    tier: str,
    policy_fraction: float | None,
    assumptions: list[str],
    effective_stack: float | None = None,
    base_open_fraction: float | None = None,
    limper_position: Position | None = None,
    limper_positions: tuple[Position, ...] = (),
    limp_size: float | None = None,
    base_limp_raise_fraction: float | None = None,
    limp_raise_fraction: float | None = None,
    target_limp_raise_size: float | None = None,
    maximum_limp_raise_total: float | None = None,
    limp_response_policy: str | None = None,
    base_multi_limp_raise_fraction: float | None = None,
    multi_limp_raise_fraction: float | None = None,
    target_multi_limp_raise_size: float | None = None,
    maximum_multi_limp_raise_total: float | None = None,
    multi_limp_response_policy: str | None = None,
    isolation_raiser_position: Position | None = None,
    isolation_raise_size: float | None = None,
    isolation_size_policy: OpenSizePolicy | None = None,
    isolation_response_policy: str | None = None,
    hero_isolation_raise_size: float | None = None,
    limp_reraiser_position: Position | None = None,
    limp_reraise_size: float | None = None,
    base_limp_reraise_defense_policy: ThreeBetDefensePolicy | None = None,
    limp_reraise_defense_policy: ThreeBetDefensePolicy | None = None,
    limp_reraise_size_policy: ThreeBetSizePolicy | None = None,
    limp_reraise_response_policy: str | None = None,
    opener_position: Position | None = None,
    base_opener_open_fraction: float | None = None,
    opener_open_fraction: float | None = None,
    opening_raise_size: float | None = None,
    maximum_reraise_total: float | None = None,
    caller_positions: tuple[Position, ...] = (),
    caller_adjustment_policy: CallerAdjustmentPolicy | None = None,
    three_bettor_position: Position | None = None,
    three_bet_size: float | None = None,
    maximum_four_bet_total: float | None = None,
    base_defense_policy: DefensePolicy | None = None,
    defense_policy: DefensePolicy | None = None,
    size_policy: OpenSizePolicy | None = None,
    base_three_bet_defense_policy: ThreeBetDefensePolicy | None = None,
    three_bet_defense_policy: ThreeBetDefensePolicy | None = None,
    three_bet_size_policy: ThreeBetSizePolicy | None = None,
    three_bet_policy_source: str | None = None,
    cold_three_bet_policy: str | None = None,
    hero_prior_commitment: float | None = None,
    squeeze_response_policy: str | None = None,
    four_bettor_position: Position | None = None,
    four_bet_size: float | None = None,
    maximum_five_bet_total: float | None = None,
    base_four_bet_defense_policy: FourBetDefensePolicy | None = None,
    four_bet_defense_policy: FourBetDefensePolicy | None = None,
    four_bet_size_policy: FourBetSizePolicy | None = None,
    four_bet_policy_source: str | None = None,
    cold_four_bet_policy: str | None = None,
    stack_policy: StackDepthPolicy | None = None,
) -> RecommendationResult:
    position_label = POSITION_LABELS[position]
    size_text = f" to {sizing:g} BB" if sizing is not None else ""
    range_text = (
        f" against a {policy_fraction:.0%} chart boundary" if policy_fraction is not None else ""
    )
    assumption_text = " ".join(assumptions)
    if scenario in {
        "big_blind_option",
        "heads_up_limp_big_blind",
        "two_limpers_big_blind",
        "three_limpers_big_blind",
        "four_limpers_big_blind",
        "five_limpers_big_blind",
    }:
        actions = ("check", "raise")
    else:
        actions = ("fold", "call", "raise")
    candidates = [
        {
            "action": candidate,
            "sizing": sizing if candidate == action and candidate == "raise" else None,
            "frequency": 1.0 if candidate == action else 0.0,
        }
        for candidate in actions
    ]
    raw: dict[str, object] = {
        "provider": "local_solver",
        "engine": "preflop_chart_v1",
        "stage": "preflop",
        "hand_class": hand_class,
        "position": position,
        "scenario": scenario,
        "chart_tier": tier,
        "hand_top_fraction": top_fraction,
        "policy_fraction": policy_fraction,
        "ranking_method": "starting_hand_score_with_playability_adjustments",
        "assumptions": assumptions,
        "candidates": candidates,
        "process_boundary": "stdin_stdout_json",
    }
    if limper_position is not None:
        raw["limper_position"] = limper_position
    if limper_positions:
        raw.update(
            {
                "limper_positions": list(limper_positions),
                "limper_count": len(limper_positions),
            }
        )
    if limp_size is not None:
        raw["limp_size"] = limp_size
    if (
        base_limp_raise_fraction is not None
        and limp_raise_fraction is not None
    ):
        raw.update(
            {
                "policy_source": "limper_position_stack_matchup",
                "base_limp_raise_fraction": base_limp_raise_fraction,
                "limp_raise_fraction": limp_raise_fraction,
            }
        )
    if target_limp_raise_size is not None:
        raw["target_limp_raise_size"] = target_limp_raise_size
    if maximum_limp_raise_total is not None:
        raw["maximum_limp_raise_total"] = maximum_limp_raise_total
    if limp_response_policy is not None:
        raw["limp_response_policy"] = limp_response_policy
    if (
        base_multi_limp_raise_fraction is not None
        and multi_limp_raise_fraction is not None
    ):
        raw.update(
            {
                "policy_source": "limper_positions_stack_matchup",
                "base_multi_limp_raise_fraction": (
                    base_multi_limp_raise_fraction
                ),
                "multi_limp_raise_fraction": multi_limp_raise_fraction,
            }
        )
    if target_multi_limp_raise_size is not None:
        raw["target_multi_limp_raise_size"] = target_multi_limp_raise_size
    if maximum_multi_limp_raise_total is not None:
        raw["maximum_multi_limp_raise_total"] = maximum_multi_limp_raise_total
    if multi_limp_response_policy is not None:
        raw["multi_limp_response_policy"] = multi_limp_response_policy
    if isolation_raiser_position is not None:
        raw["isolation_raiser_position"] = isolation_raiser_position
    if isolation_raise_size is not None:
        raw["isolation_raise_size"] = isolation_raise_size
        if limp_size is not None:
            raw["isolation_raise_to_limp_ratio"] = round(
                isolation_raise_size / limp_size,
                4,
            )
    if isolation_response_policy is not None:
        raw["isolation_response_policy"] = isolation_response_policy
    if hero_isolation_raise_size is not None:
        raw["hero_isolation_raise_size"] = hero_isolation_raise_size
    if limp_reraiser_position is not None:
        raw["limp_reraiser_position"] = limp_reraiser_position
    if limp_reraise_size is not None:
        raw["limp_reraise_size"] = limp_reraise_size
        if hero_isolation_raise_size is not None:
            raw["limp_reraise_to_isolation_ratio"] = round(
                limp_reraise_size / hero_isolation_raise_size,
                4,
            )
    if limp_reraise_response_policy is not None:
        raw["limp_reraise_response_policy"] = limp_reraise_response_policy
    if opener_position is not None:
        raw["opener_position"] = opener_position
    if opening_raise_size is not None:
        raw["opening_raise_size"] = opening_raise_size
    if maximum_reraise_total is not None:
        raw["maximum_reraise_total"] = maximum_reraise_total
    if caller_positions:
        raw.update(
            {
                "caller_positions": list(caller_positions),
                "caller_count": len(caller_positions),
            }
        )
    if caller_adjustment_policy is not None:
        raw.update(
            {
                "caller_adjustment_policy": caller_adjustment_policy.name,
                "caller_continue_multiplier": (
                    caller_adjustment_policy.continue_multiplier
                ),
                "caller_reraise_multiplier": (
                    caller_adjustment_policy.reraise_multiplier
                ),
                "squeeze_open_multiple": (
                    caller_adjustment_policy.squeeze_open_multiple
                ),
            }
        )
    if three_bettor_position is not None:
        raw["three_bettor_position"] = three_bettor_position
    if three_bet_size is not None:
        raw["three_bet_size"] = three_bet_size
        if opening_raise_size is not None:
            raw["three_bet_to_open_ratio"] = round(
                three_bet_size / opening_raise_size,
                4,
            )
    if maximum_four_bet_total is not None:
        raw["maximum_four_bet_total"] = maximum_four_bet_total
    if cold_three_bet_policy is not None:
        raw["cold_three_bet_policy"] = cold_three_bet_policy
    if hero_prior_commitment is not None:
        raw["hero_prior_commitment"] = hero_prior_commitment
    if squeeze_response_policy is not None:
        raw["squeeze_response_policy"] = squeeze_response_policy
    if four_bettor_position is not None:
        raw["four_bettor_position"] = four_bettor_position
    if four_bet_size is not None:
        raw["four_bet_size"] = four_bet_size
        if three_bet_size is not None:
            raw["four_bet_to_three_bet_ratio"] = round(
                four_bet_size / three_bet_size,
                4,
            )
    if maximum_five_bet_total is not None:
        raw["maximum_five_bet_total"] = maximum_five_bet_total
    if cold_four_bet_policy is not None:
        raw["cold_four_bet_policy"] = cold_four_bet_policy
    if effective_stack is not None and stack_policy is not None:
        raw.update(
            {
                "effective_stack": effective_stack,
                "stack_depth_policy": stack_policy.name,
                "open_stack_multiplier": stack_policy.open_multiplier,
                "continue_stack_multiplier": stack_policy.continue_multiplier,
                "reraise_stack_multiplier": stack_policy.reraise_multiplier,
            }
        )
    if base_open_fraction is not None and stack_policy is not None:
        raw.update(
            {
                "policy_source": "hero_position_stack",
                "base_open_fraction": base_open_fraction,
                "open_fraction": policy_fraction,
                "target_open_size": stack_policy.opening_size,
            }
        )
    if (
        isolation_raiser_position is not None
        and base_defense_policy is not None
        and defense_policy is not None
        and isolation_size_policy is not None
        and stack_policy is not None
    ):
        raw.update(
            {
                "policy_source": "hero_limper_isolation_raiser_size_stack_matchup",
                "base_continue_fraction": base_defense_policy.continue_fraction,
                "base_reraise_fraction": base_defense_policy.reraise_fraction,
                "continue_fraction": defense_policy.continue_fraction,
                "reraise_fraction": defense_policy.reraise_fraction,
                "isolation_raise_size_policy": isolation_size_policy.name,
                "continue_size_multiplier": isolation_size_policy.continue_multiplier,
                "reraise_size_multiplier": isolation_size_policy.reraise_multiplier,
            }
        )
    if (
        limp_reraiser_position is not None
        and base_limp_reraise_defense_policy is not None
        and limp_reraise_defense_policy is not None
        and limp_reraise_size_policy is not None
        and stack_policy is not None
    ):
        raw.update(
            {
                "policy_source": (
                    "original_limper_hero_isolator_size_stack_matchup"
                ),
                "base_continue_fraction": (
                    base_limp_reraise_defense_policy.continue_fraction
                ),
                "base_four_bet_fraction": (
                    base_limp_reraise_defense_policy.four_bet_fraction
                ),
                "continue_fraction": (
                    limp_reraise_defense_policy.continue_fraction
                ),
                "four_bet_fraction": (
                    limp_reraise_defense_policy.four_bet_fraction
                ),
                "limp_reraise_size_policy": limp_reraise_size_policy.name,
                "continue_size_multiplier": (
                    limp_reraise_size_policy.continue_multiplier
                ),
                "four_bet_size_multiplier": (
                    limp_reraise_size_policy.four_bet_multiplier
                ),
            }
        )
    if (
        opener_position is not None
        and base_opener_open_fraction is not None
        and opener_open_fraction is not None
        and base_defense_policy is not None
        and defense_policy is not None
        and size_policy is not None
        and stack_policy is not None
    ):
        raw.update(
            {
                "policy_source": "hero_opener_size_stack_matchup",
                "base_opener_open_fraction": base_opener_open_fraction,
                "opener_open_fraction": opener_open_fraction,
                "base_continue_fraction": base_defense_policy.continue_fraction,
                "base_reraise_fraction": base_defense_policy.reraise_fraction,
                "continue_fraction": defense_policy.continue_fraction,
                "reraise_fraction": defense_policy.reraise_fraction,
                "open_size_policy": size_policy.name,
                "continue_size_multiplier": size_policy.continue_multiplier,
                "reraise_size_multiplier": size_policy.reraise_multiplier,
            }
        )
        if caller_adjustment_policy is not None:
            raw["policy_source"] = (
                "hero_opener_caller_size_stack_matchup"
                if len(caller_positions) == 1
                else "hero_opener_callers_size_stack_matchup"
            )
    if (
        three_bettor_position is not None
        and base_three_bet_defense_policy is not None
        and three_bet_defense_policy is not None
        and three_bet_size_policy is not None
        and stack_policy is not None
    ):
        raw.update(
            {
                "policy_source": (
                    three_bet_policy_source
                    or "hero_three_bettor_size_stack_matchup"
                ),
                "base_continue_fraction": (
                    base_three_bet_defense_policy.continue_fraction
                ),
                "base_four_bet_fraction": (
                    base_three_bet_defense_policy.four_bet_fraction
                ),
                "continue_fraction": three_bet_defense_policy.continue_fraction,
                "four_bet_fraction": three_bet_defense_policy.four_bet_fraction,
                "three_bet_size_policy": three_bet_size_policy.name,
                "continue_size_multiplier": (
                    three_bet_size_policy.continue_multiplier
                ),
                "four_bet_size_multiplier": (
                    three_bet_size_policy.four_bet_multiplier
                ),
            }
        )
    if (
        four_bettor_position is not None
        and base_four_bet_defense_policy is not None
        and four_bet_defense_policy is not None
        and four_bet_size_policy is not None
        and stack_policy is not None
    ):
        raw.update(
            {
                "policy_source": (
                    four_bet_policy_source
                    or "hero_opener_four_bet_size_stack_matchup"
                ),
                "base_continue_fraction": (
                    base_four_bet_defense_policy.continue_fraction
                ),
                "base_five_bet_fraction": (
                    base_four_bet_defense_policy.five_bet_fraction
                ),
                "continue_fraction": four_bet_defense_policy.continue_fraction,
                "five_bet_fraction": four_bet_defense_policy.five_bet_fraction,
                "four_bet_size_policy": four_bet_size_policy.name,
                "continue_size_multiplier": (
                    four_bet_size_policy.continue_multiplier
                ),
                "five_bet_size_multiplier": (
                    four_bet_size_policy.five_bet_multiplier
                ),
            }
        )

    return RecommendationResult(
        action=action,
        sizing=sizing,
        confidence=confidence,
        explanation=(
            f"The position-aware preflop chart recommends {action}{size_text} with {hand_class} "
            f"from {position_label}. Its 169-hand ranking places this hand in the top "
            f"{top_fraction:.1%}{range_text}. {assumption_text} This is a transparent training "
            "chart, not a solved preflop game tree."
        ),
        raw=raw,
    )
