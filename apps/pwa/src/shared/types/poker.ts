export type Rank =
  | "2"
  | "3"
  | "4"
  | "5"
  | "6"
  | "7"
  | "8"
  | "9"
  | "T"
  | "J"
  | "Q"
  | "K"
  | "A";

export type Suit = "clubs" | "diamonds" | "hearts" | "spades";
export type Street = "preflop" | "flop" | "turn" | "river";
export type FacingAction = "bet" | "raise";
export type PreflopPosition =
  | "utg"
  | "hijack"
  | "cutoff"
  | "button"
  | "small_blind"
  | "big_blind";
export type PreflopActionType = "call" | "raise";
export type PostflopActor = "oop" | "ip";
export type PostflopActionType = "check" | "bet" | "raise";
export type CompletedPostflopActionType = "check" | "bet" | "raise" | "call";
export type CompletedPostflopStreet = "flop" | "turn";

export interface Card {
  rank: Rank;
  suit: Suit;
}

export interface PostflopAction {
  actor: PostflopActor;
  action: PostflopActionType;
  amount: number | null;
}

export interface CompletedPostflopAction {
  actor: PostflopActor;
  action: CompletedPostflopActionType;
  amount: number | null;
}

export interface CompletedPostflopStreetHistory {
  street: CompletedPostflopStreet;
  actions: CompletedPostflopAction[];
}

export interface PreflopAction {
  actor: PreflopPosition;
  action: PreflopActionType;
  amount: number;
}

export interface DetectedState {
  hero_cards: Card[];
  board_cards: Card[];
  pot_size: number | null;
  current_bet: number | null;
  hero_stack: number | null;
  opponent_stack?: number | null;
  effective_stack: number | null;
  players_in_hand: number | null;
  opponents_at_current_bet?: number | null;
  opponent_wager?: number | null;
  opponent_commitment_total?: number | null;
  hero_position: string | null;
  opponent_position?: string | null;
  preflop_opener_position: string | null;
  preflop_open_size: number | null;
  preflop_action_history?: PreflopAction[];
  street: Street | null;
  facing_action: FacingAction | null;
  postflop_action_history?: PostflopAction[];
  completed_postflop_streets?: CompletedPostflopStreetHistory[];
  action_context: string | null;
}

export interface ParserResult {
  state: DetectedState;
  confidences: Record<string, number>;
  warnings: string[];
  raw: Record<string, unknown>;
}

export interface CanonicalState extends DetectedState {
  user_approved: boolean;
}
