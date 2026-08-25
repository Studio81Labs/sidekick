import type {
  CanonicalState,
  Card,
  DetectedState,
  PreflopAction,
} from "../../../shared/types/poker";
import { PREFLOP_POSITIONS } from "../../../domains/poker/model/preflopPosition";
import {
  FACING_ACTIONS,
  RANKS,
  STREETS,
  SUITS,
} from "../../hand-review/lib/pokerState";
import {
  isCachedCompletedPostflopHistory,
  isCachedPostflopAction,
} from "./cachedPostflopValidation";
import {
  isNullableCachedNumber,
  isNullableCachedString,
} from "./cacheValidationPrimitives";

export function isCachedCard(value: unknown): value is Card {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const card = value as Partial<Card>;
  return (
    typeof card.rank === "string" &&
    RANKS.has(card.rank) &&
    typeof card.suit === "string" &&
    SUITS.has(card.suit)
  );
}

export function isCachedPreflopAction(value: unknown): value is PreflopAction {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const action = value as Partial<PreflopAction>;
  return (
    PREFLOP_POSITIONS.some((position) => position.value === action.actor) &&
    (action.action === "call" || action.action === "raise") &&
    typeof action.amount === "number" &&
    Number.isFinite(action.amount) &&
    action.amount > 0
  );
}

export function isCachedDetectedState(value: unknown): value is DetectedState {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const state = value as Partial<DetectedState>;
  if (
    !Array.isArray(state.hero_cards) ||
    !state.hero_cards.every(isCachedCard) ||
    state.hero_cards.length > 2 ||
    !Array.isArray(state.board_cards) ||
    !state.board_cards.every(isCachedCard) ||
    state.board_cards.length > 5
  ) {
    return false;
  }
  const cardCodes = [...state.hero_cards, ...state.board_cards].map(
    (card) => `${card.rank}:${card.suit}`,
  );
  return (
    new Set(cardCodes).size === cardCodes.length &&
    isNullableCachedNumber(state.pot_size, 0) &&
    isNullableCachedNumber(state.current_bet, 0) &&
    isNullableCachedNumber(state.hero_stack, 0) &&
    (state.opponent_stack === undefined ||
      isNullableCachedNumber(state.opponent_stack, 0)) &&
    isNullableCachedNumber(state.effective_stack, 0) &&
    (state.players_in_hand === null ||
      (typeof state.players_in_hand === "number" &&
        Number.isInteger(state.players_in_hand) &&
        state.players_in_hand >= 1)) &&
    (state.opponents_at_current_bet === undefined ||
      state.opponents_at_current_bet === null ||
      (typeof state.opponents_at_current_bet === "number" &&
        Number.isInteger(state.opponents_at_current_bet) &&
        state.opponents_at_current_bet >= 1 &&
        typeof state.current_bet === "number" &&
        state.current_bet > 0 &&
        typeof state.players_in_hand === "number" &&
        state.opponents_at_current_bet < state.players_in_hand)) &&
    (state.opponent_wager === undefined ||
      state.opponent_wager === null ||
      (typeof state.opponent_wager === "number" &&
        Number.isFinite(state.opponent_wager) &&
        state.opponent_wager > 0 &&
        typeof state.current_bet === "number" &&
        state.current_bet > 0 &&
        state.opponent_wager >= state.current_bet)) &&
    (state.opponent_commitment_total === undefined ||
      state.opponent_commitment_total === null ||
      (typeof state.opponent_commitment_total === "number" &&
        Number.isFinite(state.opponent_commitment_total) &&
        state.opponent_commitment_total > 0 &&
        (typeof state.pot_size !== "number" ||
          state.opponent_commitment_total <= state.pot_size + 0.000001) &&
        (typeof state.opponent_wager !== "number" ||
          state.opponent_commitment_total + 0.000001 >=
            state.opponent_wager *
              (typeof state.opponents_at_current_bet === "number"
                ? state.opponents_at_current_bet
                : 1)))) &&
    isNullableCachedString(state.hero_position) &&
    (state.opponent_position === undefined ||
      isNullableCachedString(state.opponent_position)) &&
    isNullableCachedString(state.preflop_opener_position) &&
    isNullableCachedNumber(state.preflop_open_size, 0, false) &&
    (state.preflop_action_history === undefined ||
      (Array.isArray(state.preflop_action_history) &&
        state.preflop_action_history.length <= 8 &&
        state.preflop_action_history.every(isCachedPreflopAction))) &&
    (state.street === null ||
      (typeof state.street === "string" && STREETS.has(state.street))) &&
    (state.facing_action === null ||
      (typeof state.facing_action === "string" &&
        FACING_ACTIONS.has(state.facing_action))) &&
    (state.postflop_action_history === undefined ||
      (Array.isArray(state.postflop_action_history) &&
        state.postflop_action_history.length <= 8 &&
        state.postflop_action_history.every(isCachedPostflopAction))) &&
    isCachedCompletedPostflopHistory(
      state.completed_postflop_streets,
      state.street,
    ) &&
    isNullableCachedString(state.action_context)
  );
}

export function isCachedCanonicalState(
  value: unknown,
): value is CanonicalState {
  return (
    isCachedDetectedState(value) &&
    typeof (value as Partial<CanonicalState>).user_approved === "boolean"
  );
}
