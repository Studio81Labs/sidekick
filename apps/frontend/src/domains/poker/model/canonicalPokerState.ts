import { cardToCode } from "../../../shared/lib/cardPresentation";
import type {
  CanonicalState,
  DetectedState,
} from "../../../shared/types/poker";
import type { JobRecord } from "../../../shared/types/jobs";
import { EMPTY_STATE } from "./pokerStateConstants";

export function toCanonicalState(
  state: DetectedState | CanonicalState,
): CanonicalState {
  return {
    hero_cards: state.hero_cards,
    board_cards: state.board_cards,
    pot_size: state.pot_size,
    current_bet: state.current_bet,
    hero_stack: state.hero_stack ?? null,
    opponent_stack: state.opponent_stack ?? null,
    effective_stack: state.effective_stack,
    players_in_hand: state.players_in_hand,
    opponents_at_current_bet: state.opponents_at_current_bet ?? null,
    opponent_wager: state.opponent_wager ?? null,
    opponent_commitment_total: state.opponent_commitment_total ?? null,
    hero_position: state.hero_position,
    opponent_position: state.opponent_position ?? null,
    preflop_opener_position: state.preflop_opener_position ?? null,
    preflop_open_size: state.preflop_open_size ?? null,
    preflop_action_history: state.preflop_action_history ?? [],
    street: state.street,
    facing_action: state.facing_action ?? null,
    postflop_action_history: state.postflop_action_history ?? [],
    completed_postflop_streets: state.completed_postflop_streets ?? [],
    action_context: state.action_context,
    user_approved: "user_approved" in state ? state.user_approved : false,
  };
}

export function stateFromJob(job: JobRecord): CanonicalState {
  if (job.approved_state) {
    return toCanonicalState(job.approved_state);
  }
  if (job.parser_result) {
    return toCanonicalState(job.parser_result.state);
  }
  return EMPTY_STATE;
}

export function approvalKey(state: CanonicalState): string {
  return JSON.stringify({
    hero_cards: state.hero_cards.map(cardToCode),
    board_cards: state.board_cards.map(cardToCode),
    pot_size: state.pot_size,
    current_bet: state.current_bet,
    hero_stack: state.hero_stack ?? null,
    opponent_stack: state.opponent_stack ?? null,
    effective_stack: state.effective_stack,
    players_in_hand: state.players_in_hand,
    opponents_at_current_bet: state.opponents_at_current_bet ?? null,
    opponent_wager: state.opponent_wager ?? null,
    opponent_commitment_total: state.opponent_commitment_total ?? null,
    hero_position: state.hero_position,
    opponent_position: state.opponent_position ?? null,
    preflop_opener_position: state.preflop_opener_position ?? null,
    preflop_open_size: state.preflop_open_size ?? null,
    preflop_action_history: state.preflop_action_history ?? [],
    street: state.street,
    facing_action: state.facing_action ?? null,
    postflop_action_history: state.postflop_action_history ?? [],
    completed_postflop_streets: state.completed_postflop_streets ?? [],
    action_context: state.action_context,
  });
}

export function benchmarkApprovalKey(state: CanonicalState): string {
  return JSON.stringify({
    hero_cards: state.hero_cards.map(cardToCode),
    board_cards: state.board_cards.map(cardToCode),
    street: state.street,
    pot_size: state.pot_size,
    current_bet: state.current_bet,
    hero_stack: state.hero_stack ?? null,
    opponent_stack: state.opponent_stack ?? null,
    effective_stack: state.effective_stack,
    players_in_hand: state.players_in_hand,
    hero_position: state.hero_position,
    opponent_position: state.opponent_position ?? null,
    preflop_opener_position: state.preflop_opener_position ?? null,
    preflop_open_size: state.preflop_open_size ?? null,
    preflop_action_history: state.preflop_action_history ?? [],
    facing_action: state.facing_action ?? null,
    postflop_action_history: state.postflop_action_history ?? [],
    completed_postflop_streets: state.completed_postflop_streets ?? [],
    action_context: state.action_context,
  });
}
