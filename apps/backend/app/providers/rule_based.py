from __future__ import annotations

import hashlib
import random
from collections import Counter
from dataclasses import dataclass
from itertools import combinations

from app.domain.poker import Card
from app.domain.recommendations import (
    RecommendationAction,
    RecommendationRequest,
    RecommendationResult,
)
from app.providers.base import ProviderGradingContextBinding

RANK_VALUE = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "T": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14,
}

HAND_CATEGORY_LABELS = {
    0: "high card",
    1: "one pair",
    2: "two pair",
    3: "three of a kind",
    4: "straight",
    5: "flush",
    6: "full house",
    7: "four of a kind",
    8: "straight flush",
}

DECK_CODES = tuple(f"{rank}{suit}" for rank in RANK_VALUE for suit in ("c", "d", "h", "s"))


@dataclass(frozen=True)
class HandScore:
    category: int
    tiebreakers: tuple[int, ...]


@dataclass(frozen=True)
class DrawInfo:
    flush_draw: bool
    open_ended_straight_draw: bool
    gutshot_straight_draw: bool
    overcards: int

    @property
    def has_strong_draw(self) -> bool:
        return self.flush_draw or self.open_ended_straight_draw


@dataclass(frozen=True)
class PostflopAnalysis:
    made_hand: HandScore
    pair_rank: int | None
    top_pair_kicker: int | None
    top_pair_or_better: bool
    overpair: bool
    wet_board: bool
    draws: DrawInfo


@dataclass(frozen=True)
class EquityEstimate:
    equity: float
    win_rate: float
    tie_rate: float
    iterations: int
    opponents: int


class RuleBasedTrainingProvider:
    name = "rule_based"
    required_fields = ["hero_cards", "street"]

    def required_fields_for(self, state: CanonicalState) -> list[str]:
        return self.required_fields

    def grading_context_binding_for(
        self,
        state: CanonicalState,
    ) -> ProviderGradingContextBinding | None:
        return None

    def recommend(self, request: RecommendationRequest) -> RecommendationResult:
        state = request.state
        if state.street == "preflop":
            decision = _preflop_decision(request)
        else:
            decision = _postflop_decision(request)

        return RecommendationResult(
            action=decision.action,
            sizing=decision.sizing,
            confidence=decision.confidence,
            explanation=decision.explanation,
            raw={
                "provider": self.name,
                "engine": "rule_based_training_v2",
                **decision.raw,
            },
        )


@dataclass(frozen=True)
class Decision:
    action: RecommendationAction
    sizing: float | None
    confidence: float
    explanation: str
    raw: dict[str, object]


def _preflop_decision(request: RecommendationRequest) -> Decision:
    state = request.state
    hero_cards = state.hero_cards
    hand_score = _starting_hand_score(hero_cards)
    current_bet = state.current_bet or 0
    pot_size = state.pot_size or 0
    pot_odds = _pot_odds(current_bet, pot_size)
    players = state.players_in_hand or 2
    facing_bet = current_bet > 0
    equity = _estimate_equity(hero_cards, [], players, "preflop")
    realized_equity = _realized_preflop_equity(equity.equity, hand_score, hero_cards, players, facing_bet)
    required_equity = pot_odds or 0

    if facing_bet:
        if hand_score >= 82 and realized_equity >= required_equity - 0.06:
            sizing = _raise_sizing(current_bet, pot_size)
            return _decision(
                "raise",
                sizing,
                0.72,
                "Premium preflop hand with enough estimated equity: raise for value.",
                stage="preflop",
                hand_score=hand_score,
                equity=_equity_raw(equity),
                realized_equity=realized_equity,
                required_equity=required_equity,
                pot_odds=pot_odds,
            )
        if realized_equity >= required_equity + 0.05 and hand_score >= 54:
            return _decision(
                "call",
                None,
                0.66,
                "Estimated realized equity is comfortably above the call price, so continue.",
                stage="preflop",
                hand_score=hand_score,
                equity=_equity_raw(equity),
                realized_equity=realized_equity,
                required_equity=required_equity,
                pot_odds=pot_odds,
            )
        if players <= 2 and realized_equity >= required_equity + 0.06 and hand_score >= 42:
            return _decision(
                "call",
                None,
                0.6,
                "Heads-up preflop defense: estimated realized equity clears the call price.",
                stage="preflop",
                hand_score=hand_score,
                equity=_equity_raw(equity),
                realized_equity=realized_equity,
                required_equity=required_equity,
                pot_odds=pot_odds,
            )
        if realized_equity >= required_equity + 0.02 and hand_score >= 48 and players <= 3:
            return _decision(
                "call",
                None,
                0.58,
                "Close preflop call: equity is near the price and the hand has enough playability.",
                stage="preflop",
                hand_score=hand_score,
                equity=_equity_raw(equity),
                realized_equity=realized_equity,
                required_equity=required_equity,
                pot_odds=pot_odds,
            )
        return _decision(
            "fold",
            None,
            0.7,
            "Estimated realized equity does not clear the call price after playability discounts.",
            stage="preflop",
            hand_score=hand_score,
            equity=_equity_raw(equity),
            realized_equity=realized_equity,
            required_equity=required_equity,
            pot_odds=pot_odds,
        )

    if hand_score >= 68 or realized_equity >= 0.48:
        sizing = _open_sizing(pot_size)
        return _decision(
            "raise",
            sizing,
            0.67,
            "Strong preflop equity with no bet faced; raise for value.",
            stage="preflop",
            hand_score=hand_score,
            equity=_equity_raw(equity),
            realized_equity=realized_equity,
            required_equity=required_equity,
            pot_odds=pot_odds,
        )
    if hand_score >= 48 or realized_equity >= 0.34:
        return _decision(
            "call",
            None,
            0.56,
            "Playable but not premium preflop hand; continue cautiously.",
            stage="preflop",
            hand_score=hand_score,
            equity=_equity_raw(equity),
            realized_equity=realized_equity,
            required_equity=required_equity,
            pot_odds=pot_odds,
        )
    return _decision(
        "check",
        None,
        0.6,
        "No bet faced and the hand is weak; take the free option.",
        stage="preflop",
        hand_score=hand_score,
        equity=_equity_raw(equity),
        realized_equity=realized_equity,
        required_equity=required_equity,
        pot_odds=pot_odds,
    )


def _postflop_decision(request: RecommendationRequest) -> Decision:
    state = request.state
    analysis = _postflop_analysis(state.hero_cards, state.board_cards)
    current_bet = state.current_bet or 0
    pot_size = state.pot_size or 0
    pot_odds = _pot_odds(current_bet, pot_size)
    facing_bet = current_bet > 0
    players = state.players_in_hand or 2
    equity = _estimate_equity(state.hero_cards, state.board_cards, players, state.street or "flop")
    realized_equity = _realized_postflop_equity(equity.equity, analysis, players, facing_bet)
    required_equity = pot_odds or 0
    category = analysis.made_hand.category
    hand_label = HAND_CATEGORY_LABELS[category]
    analysis_raw = {
        "stage": "postflop",
        "hand_category": hand_label,
        "pot_odds": pot_odds,
        "equity": _equity_raw(equity),
        "realized_equity": realized_equity,
        "required_equity": required_equity,
        "draws": _draw_raw(analysis.draws),
        "pair_rank": analysis.pair_rank,
        "top_pair_kicker": analysis.top_pair_kicker,
        "top_pair_or_better": analysis.top_pair_or_better,
        "overpair": analysis.overpair,
        "wet_board": analysis.wet_board,
    }

    if facing_bet:
        if category >= 3:
            sizing = _raise_sizing(current_bet, pot_size)
            return _decision(
                "raise",
                sizing,
                0.72,
                f"Strong made hand ({hand_label}); raise for value.",
                **analysis_raw,
            )
        if category == 2:
            if realized_equity >= required_equity + 0.16:
                return _decision(
                    "raise",
                    _raise_sizing(current_bet, pot_size),
                    0.68,
                    "Two pair has a large equity edge over the price; raise for value.",
                    **analysis_raw,
                )
            return _decision(
                "call",
                None,
                0.64,
                "Two pair is strong enough to continue, but the equity edge is not large enough to force a raise.",
                **analysis_raw,
            )
        if realized_equity >= required_equity + 0.08:
            return _decision(
                "call",
                None,
                0.62,
                "Estimated realized equity is above the call price, so continue.",
                **analysis_raw,
            )
        if (analysis.top_pair_or_better or analysis.overpair) and realized_equity >= required_equity - 0.04:
            return _decision(
                "call",
                None,
                0.58,
                "Pair strength is enough to continue at this price, but not strong enough to raise.",
                **analysis_raw,
            )
        if analysis.draws.has_strong_draw and realized_equity >= required_equity - 0.02:
            return _decision(
                "call",
                None,
                0.58,
                "Strong draw is close enough to the call price to continue.",
                **analysis_raw,
            )
        return _decision(
            "fold",
            None,
            0.7,
            f"Only {hand_label}; estimated realized equity does not clear the call price.",
            **analysis_raw,
        )

    if category >= 3:
        sizing = _value_bet_sizing(pot_size)
        return _decision(
            "bet",
            sizing,
            0.73,
            f"Strong made hand ({hand_label}); bet for value.",
            **analysis_raw,
        )
    if category == 2 or analysis.overpair:
        sizing = _thin_value_sizing(pot_size)
        return _decision(
            "bet",
            sizing,
            0.65,
            "Made pair strength and equity can bet for value and protection.",
            **analysis_raw,
        )
    if analysis.top_pair_or_better:
        if _should_pot_control_top_pair(analysis, players):
            return _decision(
                "check",
                None,
                0.64,
                "Top pair has showdown value, but the kicker and board texture favor pot control.",
                **analysis_raw,
            )
        sizing = _thin_value_sizing(pot_size)
        return _decision(
            "bet",
            sizing,
            0.63,
            "Top pair is strong enough to bet for value and protection.",
            **analysis_raw,
        )
    if analysis.draws.has_strong_draw and realized_equity >= 0.3:
        sizing = _semi_bluff_sizing(pot_size)
        return _decision(
            "bet",
            sizing,
            0.58,
            "Strong draw can semi-bluff when checked to.",
            **analysis_raw,
        )
    return _decision(
        "check",
        None,
        0.71,
        f"Only {hand_label} with limited realized equity; take the free card/check option.",
        **analysis_raw,
    )


def _decision(
    action: RecommendationAction,
    sizing: float | None,
    confidence: float,
    explanation: str,
    **raw: object,
) -> Decision:
    return Decision(
        action=action,
        sizing=round(sizing, 2) if sizing is not None else None,
        confidence=confidence,
        explanation=f"{explanation} This is a rule-based training recommendation, not a solver output.",
        raw=raw,
    )


def _starting_hand_score(cards: list[Card]) -> float:
    if len(cards) < 2:
        return 0
    first, second = cards[:2]
    high, low = sorted((RANK_VALUE[first.rank], RANK_VALUE[second.rank]), reverse=True)
    suited = first.suit == second.suit
    pair = high == low
    gap = high - low

    if pair:
        return 52 + high * 3.2

    score = high * 3 + low * 1.15
    if suited:
        score += 5.5
    if gap == 1:
        score += 5
    elif gap == 2:
        score += 2.5
    elif gap >= 5:
        score -= min(10, gap * 1.3)
    if high == 14:
        score += 4
    if high >= 12 and low >= 10:
        score += 8
    if low <= 5 and gap >= 5:
        score -= 6
    return max(0, round(score, 2))


def _estimate_equity(
    hero_cards: list[Card],
    board_cards: list[Card],
    players_in_hand: int,
    street: str | None,
) -> EquityEstimate:
    opponents = max(1, min(players_in_hand - 1, 5))
    known_codes = {card.code for card in [*hero_cards, *board_cards]}
    deck = [Card.from_code(code) for code in DECK_CODES if code not in known_codes]
    board_needed = max(0, 5 - len(board_cards))
    draw_count = board_needed + opponents * 2
    if len(hero_cards) < 2 or draw_count > len(deck):
        return EquityEstimate(equity=0, win_rate=0, tie_rate=0, iterations=0, opponents=opponents)

    iterations = _equity_iterations(street, opponents)
    rng = random.Random(_equity_seed(hero_cards, board_cards, players_in_hand, street))
    equity_total = 0.0
    wins = 0
    ties = 0

    for _ in range(iterations):
        drawn_cards = rng.sample(deck, draw_count)
        final_board = [*board_cards, *drawn_cards[:board_needed]]
        opponent_cards = drawn_cards[board_needed:]
        scores = [_best_hand_score([*hero_cards, *final_board])]
        for offset in range(0, len(opponent_cards), 2):
            opponent_hand = opponent_cards[offset : offset + 2]
            scores.append(_best_hand_score([*opponent_hand, *final_board]))

        score_keys = [_score_key(score) for score in scores]
        best_score = max(score_keys)
        winner_count = sum(1 for score in score_keys if score == best_score)
        if score_keys[0] == best_score:
            equity_total += 1 / winner_count
            if winner_count == 1:
                wins += 1
            else:
                ties += 1

    return EquityEstimate(
        equity=round(equity_total / iterations, 3),
        win_rate=round(wins / iterations, 3),
        tie_rate=round(ties / iterations, 3),
        iterations=iterations,
        opponents=opponents,
    )


def _equity_iterations(street: str | None, opponents: int) -> int:
    if street == "preflop":
        base = 900
    elif street == "flop":
        base = 1200
    elif street == "turn":
        base = 1000
    else:
        base = 800
    return max(500, int(base * max(0.55, 1 - (opponents - 1) * 0.08)))


def _equity_seed(
    hero_cards: list[Card],
    board_cards: list[Card],
    players_in_hand: int,
    street: str | None,
) -> int:
    seed_text = "|".join(
        [
            ",".join(sorted(card.code for card in hero_cards)),
            ",".join(sorted(card.code for card in board_cards)),
            str(players_in_hand),
            street or "",
        ]
    )
    return int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:8], "big")


def _realized_preflop_equity(
    raw_equity: float,
    hand_score: float,
    hero_cards: list[Card],
    players: int,
    facing_bet: bool,
) -> float:
    if hand_score >= 82:
        factor = 0.96
    elif hand_score >= 68:
        factor = 0.88
    elif hand_score >= 54:
        factor = 0.8
    elif hand_score >= 42:
        factor = 0.7
    else:
        factor = 0.62

    if len(hero_cards) == 2 and hero_cards[0].suit == hero_cards[1].suit:
        factor += 0.04
    if len(hero_cards) == 2:
        gap = abs(RANK_VALUE[hero_cards[0].rank] - RANK_VALUE[hero_cards[1].rank])
        if gap <= 2:
            factor += 0.03
        elif gap >= 5:
            factor -= 0.04
    if facing_bet:
        factor -= 0.04
    factor -= max(0, players - 2) * 0.04
    return round(raw_equity * min(0.98, max(0.5, factor)), 3)


def _realized_postflop_equity(
    raw_equity: float,
    analysis: PostflopAnalysis,
    players: int,
    facing_bet: bool,
) -> float:
    factor = 0.92
    if analysis.made_hand.category >= 2:
        factor += 0.05
    elif analysis.top_pair_or_better or analysis.overpair:
        factor += 0.02
    elif analysis.draws.has_strong_draw:
        factor += 0.03
    elif analysis.made_hand.category == 0:
        factor -= 0.08

    if facing_bet:
        factor -= 0.03
    factor -= max(0, players - 2) * 0.04
    return round(raw_equity * min(1.0, max(0.55, factor)), 3)


def _equity_raw(equity: EquityEstimate) -> dict[str, object]:
    return {
        "equity": equity.equity,
        "win_rate": equity.win_rate,
        "tie_rate": equity.tie_rate,
        "iterations": equity.iterations,
        "opponents": equity.opponents,
    }


def _postflop_analysis(hero_cards: list[Card], board_cards: list[Card]) -> PostflopAnalysis:
    all_cards = [*hero_cards, *board_cards]
    made_hand = _best_hand_score(all_cards)
    pair_rank = _made_pair_rank(hero_cards, board_cards)
    board_high = max((RANK_VALUE[card.rank] for card in board_cards), default=0)
    hero_pair = len(hero_cards) == 2 and hero_cards[0].rank == hero_cards[1].rank
    overpair = hero_pair and RANK_VALUE[hero_cards[0].rank] > board_high
    top_pair_or_better = made_hand.category >= 2 or overpair or (pair_rank is not None and pair_rank >= board_high)
    return PostflopAnalysis(
        made_hand=made_hand,
        pair_rank=pair_rank,
        top_pair_kicker=_top_pair_kicker_rank(hero_cards, board_cards, pair_rank),
        top_pair_or_better=top_pair_or_better,
        overpair=overpair,
        wet_board=_board_is_wet(board_cards),
        draws=_draw_info(hero_cards, board_cards),
    )


def _should_pot_control_top_pair(analysis: PostflopAnalysis, players: int) -> bool:
    if analysis.top_pair_kicker is None:
        return False
    weak_kicker = analysis.top_pair_kicker <= RANK_VALUE["T"]
    medium_kicker = analysis.top_pair_kicker <= RANK_VALUE["J"]
    if weak_kicker and players >= 3:
        return True
    if weak_kicker and analysis.wet_board:
        return True
    return medium_kicker and players >= 4 and analysis.wet_board


def _top_pair_kicker_rank(
    hero_cards: list[Card], board_cards: list[Card], pair_rank: int | None
) -> int | None:
    if pair_rank is None or not board_cards:
        return None
    board_high = max(RANK_VALUE[card.rank] for card in board_cards)
    if pair_rank != board_high:
        return None
    hero_ranks = [RANK_VALUE[card.rank] for card in hero_cards]
    kickers = [rank for rank in hero_ranks if rank != pair_rank]
    return max(kickers, default=None)


def _board_is_wet(board_cards: list[Card]) -> bool:
    if len(board_cards) < 3:
        return False
    suit_counts = Counter(card.suit for card in board_cards)
    if max(suit_counts.values(), default=0) >= 2:
        return True
    ranks = sorted(set(_rank_values(board_cards)))
    if 14 in ranks:
        ranks = sorted({*ranks, 1})
    for combo in combinations(ranks, min(3, len(ranks))):
        if max(combo) - min(combo) <= 4:
            return True
    return False


def _best_hand_score(cards: list[Card]) -> HandScore:
    if len(cards) < 5:
        return HandScore(category=0, tiebreakers=tuple(sorted(_rank_values(cards), reverse=True)))
    return max((_evaluate_five_card(list(combo)) for combo in combinations(cards, 5)), key=_score_key)


def _evaluate_five_card(cards: list[Card]) -> HandScore:
    ranks = sorted(_rank_values(cards), reverse=True)
    counts = Counter(ranks)
    flush = len({card.suit for card in cards}) == 1
    straight_high = _straight_high(ranks)
    if flush and straight_high:
        return HandScore(8, (straight_high,))

    count_groups = sorted(((count, rank) for rank, count in counts.items()), reverse=True)
    if count_groups[0][0] == 4:
        quad_rank = count_groups[0][1]
        kicker = max(rank for rank in ranks if rank != quad_rank)
        return HandScore(7, (quad_rank, kicker))
    if count_groups[0][0] == 3 and count_groups[1][0] == 2:
        return HandScore(6, (count_groups[0][1], count_groups[1][1]))
    if flush:
        return HandScore(5, tuple(ranks))
    if straight_high:
        return HandScore(4, (straight_high,))
    if count_groups[0][0] == 3:
        trips = count_groups[0][1]
        kickers = tuple(rank for rank in ranks if rank != trips)
        return HandScore(3, (trips, *kickers))
    pairs = sorted((rank for rank, count in counts.items() if count == 2), reverse=True)
    if len(pairs) >= 2:
        kicker = max(rank for rank in ranks if rank not in pairs[:2])
        return HandScore(2, (*pairs[:2], kicker))
    if len(pairs) == 1:
        pair = pairs[0]
        kickers = tuple(rank for rank in ranks if rank != pair)
        return HandScore(1, (pair, *kickers))
    return HandScore(0, tuple(ranks))


def _score_key(score: HandScore) -> tuple[int, tuple[int, ...]]:
    return score.category, score.tiebreakers


def _rank_values(cards: list[Card]) -> list[int]:
    return [RANK_VALUE[card.rank] for card in cards]


def _straight_high(ranks: list[int]) -> int | None:
    unique = set(ranks)
    if 14 in unique:
        unique.add(1)
    for high in range(14, 4, -1):
        if all(rank in unique for rank in range(high - 4, high + 1)):
            return high
    return None


def _made_pair_rank(hero_cards: list[Card], board_cards: list[Card]) -> int | None:
    if not hero_cards or not board_cards:
        return None
    counts = Counter(_rank_values([*hero_cards, *board_cards]))
    paired_ranks = [rank for rank, count in counts.items() if count >= 2]
    hero_ranks = set(_rank_values(hero_cards))
    hero_paired_ranks = [rank for rank in paired_ranks if rank in hero_ranks]
    if not hero_paired_ranks:
        return None
    return max(hero_paired_ranks)


def _draw_info(hero_cards: list[Card], board_cards: list[Card]) -> DrawInfo:
    all_cards = [*hero_cards, *board_cards]
    suit_counts = Counter(card.suit for card in all_cards)
    hero_suits = {card.suit for card in hero_cards}
    flush_draw = any(count >= 4 and suit in hero_suits for suit, count in suit_counts.items())
    open_ended, gutshot = _straight_draws(hero_cards, board_cards)
    board_high = max((RANK_VALUE[card.rank] for card in board_cards), default=0)
    overcards = sum(1 for card in hero_cards if RANK_VALUE[card.rank] > board_high)
    return DrawInfo(
        flush_draw=flush_draw,
        open_ended_straight_draw=open_ended,
        gutshot_straight_draw=gutshot,
        overcards=overcards,
    )


def _straight_draws(hero_cards: list[Card], board_cards: list[Card]) -> tuple[bool, bool]:
    ranks = set(_rank_values([*hero_cards, *board_cards]))
    hero_ranks = set(_rank_values(hero_cards))
    if 14 in ranks:
        ranks.add(1)
    if 14 in hero_ranks:
        hero_ranks.add(1)

    open_ended = False
    gutshot = False
    for low in range(1, 11):
        sequence = set(range(low, low + 5))
        present = sequence & ranks
        missing = sequence - ranks
        hero_involved = bool(sequence & hero_ranks)
        if len(present) == 4 and len(missing) == 1 and hero_involved:
            missing_rank = next(iter(missing))
            if missing_rank in {low, low + 4}:
                open_ended = True
            else:
                gutshot = True
    return open_ended, gutshot


def _pot_odds(current_bet: float, pot_size: float) -> float | None:
    if current_bet <= 0:
        return None
    return round(current_bet / (pot_size + current_bet), 3) if pot_size + current_bet > 0 else None


def _raise_sizing(current_bet: float, pot_size: float) -> float:
    if current_bet <= 0:
        return _value_bet_sizing(pot_size)
    return max(current_bet * 3, pot_size * 0.75)


def _open_sizing(pot_size: float) -> float:
    return max(2.5, pot_size * 0.65)


def _value_bet_sizing(pot_size: float) -> float:
    return max(1.0, pot_size * 0.7)


def _thin_value_sizing(pot_size: float) -> float:
    return max(1.0, pot_size * 0.55)


def _semi_bluff_sizing(pot_size: float) -> float:
    return max(1.0, pot_size * 0.5)


def _draw_raw(draws: DrawInfo) -> dict[str, object]:
    return {
        "flush_draw": draws.flush_draw,
        "open_ended_straight_draw": draws.open_ended_straight_draw,
        "gutshot_straight_draw": draws.gutshot_straight_draw,
        "overcards": draws.overcards,
    }
