import { CODE_BY_SUIT } from "../../../shared/lib/cardPresentation";
import type { CanonicalState, Rank } from "../../../shared/types/poker";

export const RANK_VALUES: readonly Rank[] = [
  "2",
  "3",
  "4",
  "5",
  "6",
  "7",
  "8",
  "9",
  "T",
  "J",
  "Q",
  "K",
  "A",
];

export const RANKS = new Set<string>(RANK_VALUES);

export const SUITS = new Set<string>(Object.keys(CODE_BY_SUIT));

export const STREETS = new Set<string>(["preflop", "flop", "turn", "river"]);

export const FACING_ACTIONS = new Set<string>(["bet", "raise"]);

export const EMPTY_STATE: CanonicalState = {
  hero_cards: [],
  board_cards: [],
  pot_size: null,
  current_bet: null,
  hero_stack: null,
  opponent_stack: null,
  effective_stack: null,
  players_in_hand: null,
  opponents_at_current_bet: null,
  opponent_wager: null,
  opponent_commitment_total: null,
  hero_position: null,
  opponent_position: null,
  preflop_opener_position: null,
  preflop_open_size: null,
  preflop_action_history: [],
  street: null,
  facing_action: null,
  postflop_action_history: [],
  completed_postflop_streets: [],
  action_context: null,
  user_approved: false,
};

export const CONFIDENCE_KEYS = [
  "hero_cards",
  "board_cards",
  "street",
  "pot_size",
  "current_bet",
  "hero_stack",
  "effective_stack",
  "players_in_hand",
  "hero_position",
  "facing_action",
  "action_context",
] as const;
