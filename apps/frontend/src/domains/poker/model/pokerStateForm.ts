import type {
  CompletedPostflopActionType,
  CompletedPostflopStreet,
  FacingAction,
  PostflopActionType,
  PostflopActor,
  PreflopActionType,
  PreflopPosition,
  Street,
} from "../../../shared/types/poker";

export type StreetOption = "" | Street;
export type FacingActionOption = "" | FacingAction;

export interface StateForm {
  hero_cards: string;
  board_cards: string;
  pot_size: string;
  current_bet: string;
  hero_stack: string;
  opponent_stack: string;
  effective_stack: string;
  players_in_hand: string;
  opponents_at_current_bet: string;
  opponent_wager: string;
  opponent_commitment_total: string;
  hero_position: string;
  opponent_position: string;
  preflop_opener_position: string;
  preflop_open_size: string;
  preflop_action_history: PreflopActionForm[];
  street: StreetOption;
  facing_action: FacingActionOption;
  postflop_action_history: PostflopActionForm[];
  completed_postflop_actions: CompletedPostflopActionForm[];
  action_context: string;
}

export interface PostflopActionForm {
  actor: PostflopActor;
  action: PostflopActionType;
  amount: string;
}

export interface CompletedPostflopActionForm {
  street: CompletedPostflopStreet;
  actor: PostflopActor;
  action: CompletedPostflopActionType;
  amount: string;
}

export interface PreflopActionForm {
  actor: PreflopPosition;
  action: PreflopActionType;
  amount: string;
}

export type StateFormChange = <K extends keyof StateForm>(
  field: K,
  value: StateForm[K],
) => void;

export function requiresOpponentPosition(state: {
  street: StreetOption | null;
  players_in_hand: number | string | null;
  hero_position: string | null | undefined;
}): boolean {
  if (
    state.street === null ||
    state.street === "" ||
    state.street === "preflop" ||
    Number(state.players_in_hand) !== 2
  ) {
    return false;
  }
  const normalizedHeroPosition = (state.hero_position ?? "")
    .toLowerCase()
    .replace(/[_-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return ![
    "ip",
    "in position",
    "oop",
    "out of position",
    "button",
    "btn",
    "dealer",
  ].includes(normalizedHeroPosition);
}
