from __future__ import annotations

import argparse
import hashlib
import random
import sys
from dataclasses import dataclass
from itertools import combinations
from math import comb
from typing import Iterable

from pydantic import ValidationError

from app.domain.poker import Card
from app.domain.recommendations import (
    RecommendationAction,
    RecommendationRequest,
    RecommendationResult,
)
from app.providers.rule_based import (
    DECK_CODES,
    HAND_CATEGORY_LABELS,
    PostflopAnalysis,
    _best_hand_score,
    _draw_raw,
    _postflop_analysis,
    _pot_odds,
    _score_key,
    _starting_hand_score,
)
from app.solvers.preflop_chart import solve_preflop_chart
from app.solvers.wager_context import (
    resolve_hero_wager,
    resolve_opponent_commitment_total,
    resolve_opponent_wager,
)

MAX_EXACT_CASES = 140_000


class SolverInputError(ValueError):
    pass


@dataclass(frozen=True)
class WeightedCombo:
    cards: tuple[Card, Card]
    weight: float
    score: float


@dataclass(frozen=True)
class EquityEstimate:
    equity: float
    win_rate: float
    tie_rate: float
    iterations: int
    opponents: int
    method: str
    opponent_combos: int
    range_fraction: float


@dataclass(frozen=True)
class ContinuationBranch:
    callers: int
    probability: float
    called_equity: float
    existing_wager_adjustment: float
    final_pot: float
    ev: float


@dataclass(frozen=True)
class Candidate:
    action: RecommendationAction
    sizing: float | None
    ev: float
    fold_equity: float | None = None
    called_equity: float | None = None
    per_opponent_fold_equity: float | None = None
    continuations: tuple[ContinuationBranch, ...] = ()


def recommend(raw_request: str, *, preflop_chart_enabled: bool = False) -> RecommendationResult:
    request = RecommendationRequest.model_validate_json(raw_request)
    return solve(request, preflop_chart_enabled=preflop_chart_enabled)


def solve(
    request: RecommendationRequest, *, preflop_chart_enabled: bool = False
) -> RecommendationResult:
    state = request.state
    hero_cards = state.hero_cards
    board_cards = state.board_cards
    street = state.street or "preflop"
    pot_size = state.pot_size or 0
    current_bet = state.current_bet or 0
    players = max(2, min(state.players_in_hand or 2, 6))
    effective_stack = max(0.0, state.effective_stack or max(20.0, pot_size * 8))
    facing_bet = current_bet > 0

    if preflop_chart_enabled and street == "preflop":
        chart_result = solve_preflop_chart(request)
        if chart_result is not None:
            return chart_result

    opponents_at_current_bet = _opponents_at_current_bet(
        players=players,
        current_bet=current_bet,
        configured=state.opponents_at_current_bet,
    )
    opponent_wager = resolve_opponent_wager(state)
    if current_bet > 0 and opponent_wager is None:
        raise SolverInputError(
            "opponent_wager is required when the total opponent commitment "
            "cannot be derived"
        )
    hero_wager = resolve_hero_wager(
        state,
        opponent_wager=opponent_wager or 0,
    )
    opponent_commitment_total = resolve_opponent_commitment_total(
        state,
        opponent_wager=opponent_wager or 0,
        opponents_at_current_bet=opponents_at_current_bet,
        hero_wager=hero_wager,
    )
    if opponent_commitment_total is None:
        raise SolverInputError(
            "opponent_commitment_total is required when active opponents have "
            "different commitments that cannot be derived"
        )

    analysis = _postflop_analysis(hero_cards, board_cards) if street != "preflop" else None
    equity_by_opponents = _estimate_range_equities(
        hero_cards=hero_cards,
        board_cards=board_cards,
        players_in_hand=players,
        street=street,
        facing_bet=facing_bet,
    )
    equity = equity_by_opponents[max(equity_by_opponents)]
    realized_equity = _realized_equity(equity.equity, hero_cards, analysis, players, facing_bet, street)
    continuation_equities = _continuation_equities(
        equity_by_opponents=equity_by_opponents,
        street=street,
        facing_bet=facing_bet,
        analysis=analysis,
        hero_cards=hero_cards,
    )
    required_equity = _pot_odds(current_bet, pot_size) if facing_bet else None

    candidates = _action_candidates(
        pot_size=pot_size,
        current_bet=current_bet,
        effective_stack=effective_stack,
        players=players,
        street=street,
        facing_bet=facing_bet,
        realized_equity=realized_equity,
        continuation_equities=continuation_equities,
        analysis=analysis,
        hero_cards=hero_cards,
        opponent_commitment_total=opponent_commitment_total,
        hero_wager=hero_wager,
    )
    best = max(candidates, key=lambda candidate: (candidate.ev, _action_rank(candidate.action)))
    second_best = sorted(candidates, key=lambda candidate: candidate.ev, reverse=True)[1] if len(candidates) > 1 else best
    confidence = _confidence(best, second_best, pot_size, equity.method)

    return RecommendationResult(
        action=best.action,
        sizing=best.sizing,
        confidence=confidence,
        explanation=_explanation(best, equity, realized_equity, required_equity, analysis, street, facing_bet),
        raw={
            "provider": "local_solver",
            "engine": "local_ev_solver_v1",
            "stage": street,
            "equity": _equity_raw(equity),
            "realized_equity": realized_equity,
            "required_equity": required_equity,
            "opponents_at_current_bet": opponents_at_current_bet,
            "opponent_wager": opponent_wager,
            "opponent_commitment_total": opponent_commitment_total,
            "hero_wager": hero_wager,
            "hand_category": _hand_category_label(analysis),
            "draws": _draw_raw(analysis.draws) if analysis is not None else None,
            "wet_board": analysis.wet_board if analysis is not None else None,
            "candidates": [_candidate_raw(candidate) for candidate in candidates],
            "process_boundary": "stdin_stdout_json",
        },
    )


def _estimate_range_equities(
    *,
    hero_cards: list[Card],
    board_cards: list[Card],
    players_in_hand: int,
    street: str,
    facing_bet: bool,
) -> dict[int, EquityEstimate]:
    opponents = max(1, min(players_in_hand - 1, 5))
    known_codes = {card.code for card in [*hero_cards, *board_cards]}
    deck = [Card.from_code(code) for code in DECK_CODES if code not in known_codes]
    board_needed = max(0, 5 - len(board_cards))
    if len(hero_cards) < 2 or board_needed + opponents * 2 > len(deck):
        return {
            count: EquityEstimate(0, 0, 0, 0, count, "unavailable", 0, 0)
            for count in range(1, opponents + 1)
        }

    combos, range_fraction = _opponent_range(deck, board_cards, street, facing_bet, players_in_hand)
    if not combos:
        combos = [WeightedCombo(tuple(combo), 1.0, 0.0) for combo in combinations(deck, 2)]
        range_fraction = 1.0

    exact_cases = len(combos) * (comb(max(0, len(deck) - 2), board_needed) if board_needed else 1)
    if opponents == 1 and exact_cases <= MAX_EXACT_CASES:
        return {
            1: _exact_single_opponent_equity(
                hero_cards, board_cards, deck, combos, board_needed, range_fraction
            )
        }

    return _monte_carlo_equities(
        hero_cards=hero_cards,
        board_cards=board_cards,
        deck=deck,
        combos=combos,
        board_needed=board_needed,
        opponents=opponents,
        street=street,
        facing_bet=facing_bet,
        players_in_hand=players_in_hand,
        range_fraction=range_fraction,
    )


def _continuation_equities(
    *,
    equity_by_opponents: dict[int, EquityEstimate],
    street: str,
    facing_bet: bool,
    analysis: PostflopAnalysis | None,
    hero_cards: list[Card],
) -> dict[int, float]:
    equities: dict[int, float] = {}
    for callers, estimate in equity_by_opponents.items():
        equities[callers] = _realized_equity(
            estimate.equity,
            hero_cards,
            analysis,
            callers + 1,
            facing_bet,
            street,
        )
    return equities


def _opponent_range(
    deck: list[Card],
    board_cards: list[Card],
    street: str,
    facing_bet: bool,
    players_in_hand: int,
) -> tuple[list[WeightedCombo], float]:
    all_combos = [tuple(combo) for combo in combinations(deck, 2)]
    scored = [
        WeightedCombo(cards=cast_combo(combo), weight=1.0, score=_opponent_combo_score(combo, board_cards, street))
        for combo in all_combos
    ]
    scored.sort(key=lambda combo: combo.score, reverse=True)
    fraction = _range_fraction(street, facing_bet, players_in_hand)
    keep_count = max(40, min(len(scored), round(len(scored) * fraction)))
    kept = scored[:keep_count]
    max_score = max((combo.score for combo in kept), default=1.0)
    weighted = [
        WeightedCombo(
            cards=combo.cards,
            score=combo.score,
            weight=max(0.08, (combo.score / max_score) ** 1.45),
        )
        for combo in kept
    ]
    return weighted, round(keep_count / len(scored), 3) if scored else 0


def cast_combo(combo: Iterable[Card]) -> tuple[Card, Card]:
    first, second = tuple(combo)
    return first, second


def _range_fraction(street: str, facing_bet: bool, players_in_hand: int) -> float:
    multiway_tighten = max(0, players_in_hand - 2) * 0.04
    if street == "preflop":
        return max(0.18, (0.36 if facing_bet else 0.68) - multiway_tighten)
    if street == "river":
        return max(0.22, (0.42 if facing_bet else 0.72) - multiway_tighten)
    if street == "turn":
        return max(0.24, (0.46 if facing_bet else 0.76) - multiway_tighten)
    return max(0.26, (0.52 if facing_bet else 0.82) - multiway_tighten)


def _opponent_combo_score(combo: tuple[Card, Card], board_cards: list[Card], street: str) -> float:
    if street == "preflop" or not board_cards:
        return _starting_hand_score(list(combo))

    analysis = _postflop_analysis(list(combo), board_cards)
    score = analysis.made_hand.category * 30
    score += max(analysis.made_hand.tiebreakers, default=0) * 1.2
    if analysis.top_pair_or_better:
        score += 18
    if analysis.overpair:
        score += 16
    if analysis.draws.flush_draw:
        score += 10
    if analysis.draws.open_ended_straight_draw:
        score += 8
    if analysis.draws.gutshot_straight_draw:
        score += 4
    score += analysis.draws.overcards * 2
    return score


def _exact_single_opponent_equity(
    hero_cards: list[Card],
    board_cards: list[Card],
    deck: list[Card],
    combos: list[WeightedCombo],
    board_needed: int,
    range_fraction: float,
) -> EquityEstimate:
    equity_total = 0.0
    weighted_cases = 0.0
    win_weight = 0.0
    tie_weight = 0.0
    iterations = 0

    for combo in combos:
        used = {card.code for card in combo.cards}
        runout_deck = [card for card in deck if card.code not in used]
        runouts = combinations(runout_deck, board_needed) if board_needed else [()]
        for runout in runouts:
            final_board = [*board_cards, *runout]
            outcome = _hero_outcome(hero_cards, [list(combo.cards)], final_board)
            weighted_cases += combo.weight
            equity_total += combo.weight * outcome
            if outcome == 1:
                win_weight += combo.weight
            elif outcome > 0:
                tie_weight += combo.weight
            iterations += 1

    if weighted_cases == 0:
        return EquityEstimate(0, 0, 0, 0, 1, "exact_single_opponent", len(combos), range_fraction)

    return EquityEstimate(
        equity=round(equity_total / weighted_cases, 3),
        win_rate=round(win_weight / weighted_cases, 3),
        tie_rate=round(tie_weight / weighted_cases, 3),
        iterations=iterations,
        opponents=1,
        method="exact_single_opponent",
        opponent_combos=len(combos),
        range_fraction=range_fraction,
    )


def _monte_carlo_equities(
    *,
    hero_cards: list[Card],
    board_cards: list[Card],
    deck: list[Card],
    combos: list[WeightedCombo],
    board_needed: int,
    opponents: int,
    street: str,
    facing_bet: bool,
    players_in_hand: int,
    range_fraction: float,
) -> dict[int, EquityEstimate]:
    iterations = _sample_budget(street, opponents)
    rng = random.Random(_seed(hero_cards, board_cards, players_in_hand, street, facing_bet))
    equity_totals = [0.0] * (opponents + 1)
    wins = [0] * (opponents + 1)
    ties = [0] * (opponents + 1)
    completed = 0

    for _ in range(iterations):
        used = {card.code for card in [*hero_cards, *board_cards]}
        opponent_hands: list[list[Card]] = []
        for _opponent_index in range(opponents):
            combo = _weighted_choice_available(combos, used, rng)
            if combo is None:
                available = [card for card in deck if card.code not in used]
                if len(available) < 2:
                    break
                chosen = rng.sample(available, 2)
            else:
                chosen = list(combo.cards)
            opponent_hands.append(chosen)
            used.update(card.code for card in chosen)

        if len(opponent_hands) != opponents:
            continue

        board_deck = [card for card in deck if card.code not in used]
        if len(board_deck) < board_needed:
            continue
        outcomes = _sample_prefix_outcomes(
            hero_cards=hero_cards,
            board_cards=board_cards,
            deck=deck,
            opponent_hands=opponent_hands,
            board_needed=board_needed,
            rng=rng,
        )
        for opponent_count, outcome in outcomes.items():
            equity_totals[opponent_count] += outcome
            if outcome == 1:
                wins[opponent_count] += 1
            elif outcome > 0:
                ties[opponent_count] += 1
        completed += 1

    if completed == 0:
        return {
            count: EquityEstimate(
                0,
                0,
                0,
                0,
                count,
                "monte_carlo_range",
                len(combos),
                range_fraction,
            )
            for count in range(1, opponents + 1)
        }

    return {
        count: EquityEstimate(
            equity=round(equity_totals[count] / completed, 3),
            win_rate=round(wins[count] / completed, 3),
            tie_rate=round(ties[count] / completed, 3),
            iterations=completed,
            opponents=count,
            method="monte_carlo_range",
            opponent_combos=len(combos),
            range_fraction=range_fraction,
        )
        for count in range(1, opponents + 1)
    }


def _sample_prefix_outcomes(
    *,
    hero_cards: list[Card],
    board_cards: list[Card],
    deck: list[Card],
    opponent_hands: list[list[Card]],
    board_needed: int,
    rng: random.Random,
) -> dict[int, float]:
    used = {card.code for card in [*hero_cards, *board_cards]}
    outcomes: dict[int, float] = {}

    for opponent_count, opponent_hand in enumerate(opponent_hands, start=1):
        used.update(card.code for card in opponent_hand)
        board_deck = [card for card in deck if card.code not in used]
        final_board = [*board_cards, *rng.sample(board_deck, board_needed)]
        outcomes[opponent_count] = _hero_outcome(
            hero_cards,
            opponent_hands[:opponent_count],
            final_board,
        )

    return outcomes


def _sample_budget(street: str, opponents: int) -> int:
    if street == "preflop":
        base = 3600
    elif street == "flop":
        base = 3400
    elif street == "turn":
        base = 3000
    else:
        base = 2400
    return max(1600, round(base * max(0.62, 1 - (opponents - 1) * 0.1)))


def _weighted_choice_available(
    combos: list[WeightedCombo], used_codes: set[str], rng: random.Random
) -> WeightedCombo | None:
    available = [combo for combo in combos if all(card.code not in used_codes for card in combo.cards)]
    total = sum(combo.weight for combo in available)
    if total <= 0:
        return None
    target = rng.random() * total
    cursor = 0.0
    for combo in available:
        cursor += combo.weight
        if cursor >= target:
            return combo
    return available[-1] if available else None


def _hero_outcome(hero_cards: list[Card], opponent_hands: list[list[Card]], final_board: list[Card]) -> float:
    return _hero_outcomes(hero_cards, opponent_hands, final_board)[len(opponent_hands)]


def _hero_outcomes(
    hero_cards: list[Card], opponent_hands: list[list[Card]], final_board: list[Card]
) -> dict[int, float]:
    hero_score = _score_key(_best_hand_score([*hero_cards, *final_board]))
    opponent_scores = [_score_key(_best_hand_score([*hand, *final_board])) for hand in opponent_hands]
    outcomes: dict[int, float] = {}
    best_score = hero_score
    tied_opponents = 0
    for opponent_count, opponent_score in enumerate(opponent_scores, start=1):
        if opponent_score > best_score:
            best_score = opponent_score
            tied_opponents = 1
        elif opponent_score == best_score:
            tied_opponents += 1
        outcomes[opponent_count] = (
            1 / (tied_opponents + 1) if hero_score == best_score else 0.0
        )
    return outcomes


def _realized_equity(
    equity: float,
    hero_cards: list[Card],
    analysis: PostflopAnalysis | None,
    players: int,
    facing_bet: bool,
    street: str,
) -> float:
    if street == "preflop":
        hand_score = _starting_hand_score(hero_cards)
        if hand_score >= 82:
            factor = 0.96
        elif hand_score >= 68:
            factor = 0.9
        elif hand_score >= 54:
            factor = 0.82
        elif hand_score >= 42:
            factor = 0.72
        else:
            factor = 0.62
        if len(hero_cards) == 2 and hero_cards[0].suit == hero_cards[1].suit:
            factor += 0.04
        if facing_bet:
            factor -= 0.04
    else:
        factor = 0.94
        if analysis is not None:
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
    return round(equity * min(1.0, max(0.52, factor)), 3)


def _action_candidates(
    *,
    pot_size: float,
    current_bet: float,
    effective_stack: float,
    players: int,
    street: str,
    facing_bet: bool,
    realized_equity: float,
    continuation_equities: dict[int, float],
    analysis: PostflopAnalysis | None,
    hero_cards: list[Card],
    opponent_commitment_total: float,
    hero_wager: float,
) -> list[Candidate]:
    if facing_bet:
        candidates = [
            Candidate("fold", None, 0.0),
            Candidate("call", None, round(realized_equity * (pot_size + current_bet) - current_bet, 3)),
        ]
        for raise_size in _raise_sizes(current_bet, pot_size, effective_stack):
            per_opponent_fold_equity = _per_opponent_fold_equity(
                raise_size, pot_size, street, facing_bet, analysis
            )
            fold_equity = _field_fold_equity(per_opponent_fold_equity, players)
            continuations = _continuation_branches(
                size=raise_size,
                pot_size=pot_size,
                players=players,
                per_opponent_fold_equity=per_opponent_fold_equity,
                continuation_equities=continuation_equities,
                analysis=analysis,
                opponent_commitment_total=opponent_commitment_total,
                existing_hero_wager=hero_wager,
            )
            ev = fold_equity * pot_size + sum(
                branch.probability * branch.ev for branch in continuations
            )
            candidates.append(
                Candidate(
                    "raise",
                    raise_size,
                    round(ev, 3),
                    round(fold_equity, 6),
                    continuations[-1].called_equity,
                    per_opponent_fold_equity,
                    continuations,
                )
            )
        return candidates

    candidates = [Candidate("check", None, round(realized_equity * pot_size, 3))]
    for bet_size in _bet_sizes(pot_size, effective_stack, street, hero_cards):
        per_opponent_fold_equity = _per_opponent_fold_equity(
            bet_size, pot_size, street, facing_bet, analysis
        )
        fold_equity = _field_fold_equity(per_opponent_fold_equity, players)
        continuations = _continuation_branches(
            size=bet_size,
            pot_size=pot_size,
            players=players,
            per_opponent_fold_equity=per_opponent_fold_equity,
            continuation_equities=continuation_equities,
            analysis=analysis,
            opponent_commitment_total=opponent_commitment_total,
            existing_hero_wager=hero_wager,
        )
        ev = fold_equity * pot_size + sum(
            branch.probability * branch.ev for branch in continuations
        )
        candidates.append(
            Candidate(
                "bet",
                bet_size,
                round(ev, 3),
                round(fold_equity, 6),
                continuations[-1].called_equity,
                per_opponent_fold_equity,
                continuations,
            )
        )
    return candidates


def _bet_sizes(pot_size: float, effective_stack: float, street: str, hero_cards: list[Card]) -> list[float]:
    if street == "preflop":
        sizes = [max(2.5, pot_size * 0.65), max(3.0, pot_size * 0.9)]
    else:
        sizes = [max(1.0, pot_size * fraction) for fraction in (0.5, 0.7, 1.0)]
    return _unique_sizes(min(size, effective_stack) for size in sizes if size > 0)


def _raise_sizes(current_bet: float, pot_size: float, effective_stack: float) -> list[float]:
    sizes = [
        max(current_bet * 2.7, pot_size * 0.65),
        max(current_bet * 3.4, pot_size * 0.9),
    ]
    return _unique_sizes(min(size, effective_stack) for size in sizes if size > current_bet)


def _unique_sizes(sizes: Iterable[float]) -> list[float]:
    unique = sorted({round(size, 2) for size in sizes if size > 0})
    return unique[:3]


def _per_opponent_fold_equity(
    size: float,
    pot_size: float,
    street: str,
    facing_bet: bool,
    analysis: PostflopAnalysis | None,
) -> float:
    fraction = size / pot_size if pot_size > 0 else 1.0
    base = 0.22 + min(0.22, fraction * 0.16)
    if facing_bet:
        base -= 0.08
    if street == "river":
        base += 0.04
    if analysis is not None:
        if analysis.wet_board:
            base -= 0.04
        if analysis.made_hand.category >= 2 or analysis.overpair:
            base -= 0.04
        elif analysis.draws.has_strong_draw:
            base += 0.02
    return round(min(0.58, max(0.04, base)), 3)


def _field_fold_equity(per_opponent_fold_equity: float, players: int) -> float:
    opponents = max(1, min(players - 1, 5))
    return per_opponent_fold_equity**opponents


def _opponents_at_current_bet(
    *, players: int, current_bet: float, configured: int | None
) -> int:
    if current_bet <= 0:
        return 0
    opponents = max(1, min(players - 1, 5))
    if opponents == 1:
        return 1
    if configured is None:
        raise SolverInputError(
            "opponents_at_current_bet is required for multiway facing-bet estimates"
        )
    return max(1, min(configured, opponents))


def _continuation_branches(
    *,
    size: float,
    pot_size: float,
    players: int,
    per_opponent_fold_equity: float,
    continuation_equities: dict[int, float],
    analysis: PostflopAnalysis | None,
    opponent_commitment_total: float,
    existing_hero_wager: float,
) -> tuple[ContinuationBranch, ...]:
    opponents = max(1, min(players - 1, 5))
    call_probability = 1 - per_opponent_fold_equity
    branches: list[ContinuationBranch] = []
    for callers in range(1, opponents + 1):
        probability = (
            comb(opponents, callers)
            * call_probability**callers
            * per_opponent_fold_equity ** (opponents - callers)
        )
        called_equity = _called_equity(
            continuation_equities[callers], size, pot_size, analysis
        )
        expected_opponent_wager = (
            opponent_commitment_total * callers / opponents
        )
        additional_caller_contribution = (
            callers * (size + existing_hero_wager)
            - expected_opponent_wager
        )
        existing_wager_adjustment = (
            expected_opponent_wager - callers * existing_hero_wager
        )
        final_pot = pot_size + size + additional_caller_contribution
        branches.append(
            ContinuationBranch(
                callers=callers,
                probability=probability,
                called_equity=called_equity,
                existing_wager_adjustment=existing_wager_adjustment,
                final_pot=final_pot,
                ev=called_equity * final_pot - size,
            )
        )
    return tuple(branches)


def _called_equity(
    realized_equity: float, size: float, pot_size: float, analysis: PostflopAnalysis | None
) -> float:
    fraction = size / pot_size if pot_size > 0 else 1.0
    penalty = 0.04 + min(0.08, fraction * 0.05)
    if analysis is not None:
        if analysis.made_hand.category >= 3:
            penalty -= 0.05
        elif analysis.made_hand.category >= 2 or analysis.overpair:
            penalty -= 0.03
        elif analysis.draws.has_strong_draw:
            penalty -= 0.01
    return round(min(0.98, max(0.02, realized_equity - penalty)), 3)


def _confidence(best: Candidate, second_best: Candidate, pot_size: float, method: str) -> float:
    ev_gap = max(0.0, best.ev - second_best.ev)
    denominator = max(1.0, pot_size)
    base = 0.56 + min(0.26, ev_gap / denominator)
    if method.startswith("exact"):
        base += 0.04
    return round(min(0.86, max(0.5, base)), 2)


def _explanation(
    best: Candidate,
    equity: EquityEstimate,
    realized_equity: float,
    required_equity: float | None,
    analysis: PostflopAnalysis | None,
    street: str,
    facing_bet: bool,
) -> str:
    label = _hand_category_label(analysis)
    if facing_bet and required_equity is not None:
        context = (
            f"Range equity is {equity.equity:.1%} ({realized_equity:.1%} realized) "
            f"against a weighted opponent range; the call price needs {required_equity:.1%}."
        )
    else:
        context = (
            f"Range equity is {equity.equity:.1%} ({realized_equity:.1%} realized) "
            "against a weighted opponent range."
        )
    size_text = f" {best.sizing:g} BB" if best.sizing is not None else ""
    hand_text = f" with {label}" if label else ""
    field_text = (
        " Multiway fold equity requires every opponent to fold and uses "
        "independent equal-response estimates."
        if equity.opponents > 1
        else ""
    )
    return (
        f"Solver compared candidate actions and chose {best.action}{size_text}{hand_text}. "
        f"{context}{field_text} This is a local range/EV estimate, not a full GTO tree solve."
    )


def _hand_category_label(analysis: PostflopAnalysis | None) -> str | None:
    if analysis is None:
        return None
    return HAND_CATEGORY_LABELS[analysis.made_hand.category]


def _equity_raw(equity: EquityEstimate) -> dict[str, object]:
    return {
        "equity": equity.equity,
        "win_rate": equity.win_rate,
        "tie_rate": equity.tie_rate,
        "iterations": equity.iterations,
        "opponents": equity.opponents,
        "method": equity.method,
        "opponent_combos": equity.opponent_combos,
        "range_fraction": equity.range_fraction,
    }


def _candidate_raw(candidate: Candidate) -> dict[str, object]:
    return {
        "action": candidate.action,
        "sizing": candidate.sizing,
        "ev": candidate.ev,
        "fold_equity": candidate.fold_equity,
        "per_opponent_fold_equity": candidate.per_opponent_fold_equity,
        "called_equity": candidate.called_equity,
        "continuations": [
            {
                "callers": branch.callers,
                "probability": round(branch.probability, 6),
                "called_equity": branch.called_equity,
                "existing_wager_adjustment": round(
                    branch.existing_wager_adjustment, 3
                ),
                "final_pot": round(branch.final_pot, 3),
                "ev": round(branch.ev, 3),
            }
            for branch in candidate.continuations
        ],
    }


def _action_rank(action: RecommendationAction) -> int:
    return {"fold": 0, "check": 1, "call": 2, "bet": 3, "raise": 4}[action]


def _seed(
    hero_cards: list[Card],
    board_cards: list[Card],
    players_in_hand: int,
    street: str,
    facing_bet: bool,
) -> int:
    seed_text = "|".join(
        [
            ",".join(sorted(card.code for card in hero_cards)),
            ",".join(sorted(card.code for card in board_cards)),
            str(players_in_hand),
            street,
            str(facing_bet),
            "local_ev_solver_v1",
        ]
    )
    return int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:8], "big")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bundled local range/EV engine")
    parser.add_argument(
        "--preflop-chart",
        action="store_true",
        help="route eligible preflop states through the position-aware chart",
    )
    args = parser.parse_args()
    try:
        result = recommend(sys.stdin.read(), preflop_chart_enabled=args.preflop_chart)
    except (SolverInputError, ValidationError) as exc:
        print(f"Invalid solver request: {exc}", file=sys.stderr)
        return 2

    print(result.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
