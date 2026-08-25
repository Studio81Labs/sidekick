import type {
  CanonicalState,
  CompletedPostflopAction,
  CompletedPostflopStreet,
  CompletedPostflopStreetHistory,
  DetectedState,
  PostflopAction,
  PreflopAction,
} from "../../../shared/types/poker";
import { normalizePreflopPosition } from "./preflopPosition";
import {
  formatCards,
  parseCards,
  parseOptionalInteger,
  parseOptionalNumber,
  validateCardState,
} from "./pokerStateParsing";
import {
  type CompletedPostflopActionForm,
  type PreflopActionForm,
  requiresOpponentPosition,
  type StateForm,
} from "./pokerStateForm";

export function stateToForm(state: DetectedState | CanonicalState): StateForm {
  const showPostflopHistory =
    state.street !== null &&
    state.street !== "preflop" &&
    state.facing_action === "raise";
  const showOpponentStack =
    showPostflopHistory || state.street === "turn" || state.street === "river";
  const showOpponentPosition = requiresOpponentPosition(state);
  const preflopActionHistory: PreflopActionForm[] = (
    state.preflop_action_history ?? []
  ).map((action) => ({
    actor: action.actor,
    action: action.action,
    amount: String(action.amount),
  }));
  const structuredOpener =
    preflopActionHistory[0]?.action === "raise"
      ? preflopActionHistory[0]
      : null;
  const completedPostflopActions: CompletedPostflopActionForm[] = (
    state.completed_postflop_streets ?? []
  ).flatMap((history) =>
    history.actions.map((action) => ({
      street: history.street,
      actor: action.actor,
      action: action.action,
      amount: action.amount === null ? "" : String(action.amount),
    })),
  );
  return {
    hero_cards: formatCards(state.hero_cards),
    board_cards: formatCards(state.board_cards),
    pot_size: state.pot_size === null ? "" : String(state.pot_size),
    current_bet: state.current_bet === null ? "" : String(state.current_bet),
    hero_stack: state.hero_stack == null ? "" : String(state.hero_stack),
    opponent_stack:
      showOpponentStack && state.opponent_stack != null
        ? String(state.opponent_stack)
        : "",
    effective_stack:
      state.effective_stack === null ? "" : String(state.effective_stack),
    players_in_hand:
      state.players_in_hand === null ? "" : String(state.players_in_hand),
    opponents_at_current_bet:
      state.opponents_at_current_bet == null
        ? ""
        : String(state.opponents_at_current_bet),
    opponent_wager:
      state.opponent_wager == null ? "" : String(state.opponent_wager),
    opponent_commitment_total:
      state.opponent_commitment_total == null
        ? ""
        : String(state.opponent_commitment_total),
    hero_position: state.hero_position ?? "",
    opponent_position: showOpponentPosition
      ? (state.opponent_position ?? "")
      : "",
    preflop_opener_position:
      structuredOpener?.actor ??
      normalizePreflopPosition(state.preflop_opener_position) ??
      "",
    preflop_open_size:
      structuredOpener !== null
        ? structuredOpener.amount
        : state.preflop_open_size !== null &&
            state.preflop_open_size !== undefined
          ? String(state.preflop_open_size)
          : "",
    preflop_action_history: preflopActionHistory,
    street: state.street ?? "",
    facing_action: state.facing_action ?? "",
    postflop_action_history: showPostflopHistory
      ? (state.postflop_action_history ?? []).map((action) => ({
          actor: action.actor,
          action: action.action,
          amount: action.amount === null ? "" : String(action.amount),
        }))
      : [],
    completed_postflop_actions: completedPostflopActions,
    action_context: state.action_context ?? "",
  };
}

export function formToCanonical(form: StateForm): CanonicalState {
  const heroCards = parseCards(form.hero_cards, "Hero cards");
  const boardCards = parseCards(form.board_cards, "Board cards");
  validateCardState(heroCards, boardCards);
  const showPostflopHistory =
    form.street !== "" &&
    form.street !== "preflop" &&
    form.facing_action === "raise";
  const showOpponentStack =
    showPostflopHistory || form.street === "turn" || form.street === "river";
  const legacyPreflopOpenSize =
    form.preflop_action_history.length === 0
      ? parseOptionalNumber(form.preflop_open_size, "Opening size")
      : null;
  if (legacyPreflopOpenSize !== null && legacyPreflopOpenSize <= 0) {
    throw new Error("Opening size must be greater than 0");
  }
  const preflopActionHistory: PreflopAction[] = form.preflop_action_history.map(
    (item, index) => {
      const amount = parseOptionalNumber(
        item.amount,
        `Preflop action ${index + 1} amount`,
      );
      if (amount === null || amount <= 0) {
        throw new Error(
          `Preflop action ${index + 1} amount must be greater than 0`,
        );
      }
      return { actor: item.actor, action: item.action, amount };
    },
  );
  const structuredOpener =
    preflopActionHistory[0]?.action === "raise"
      ? preflopActionHistory[0]
      : null;
  const preserveLegacyOpener = preflopActionHistory.length === 0;
  const postflopActionHistory: PostflopAction[] = showPostflopHistory
    ? form.postflop_action_history.map((item, index) => {
        const amount =
          item.action === "check"
            ? null
            : parseOptionalNumber(item.amount, `Action ${index + 1} amount`);
        if (item.action !== "check" && (amount === null || amount <= 0)) {
          throw new Error(`Action ${index + 1} amount must be greater than 0`);
        }
        return { actor: item.actor, action: item.action, amount };
      })
    : [];
  const completedPostflopActions: Array<
    CompletedPostflopAction & { street: CompletedPostflopStreet }
  > =
    form.street === "turn" || form.street === "river"
      ? form.completed_postflop_actions.map((item, index) => {
          const amount =
            item.action === "check"
              ? null
              : parseOptionalNumber(
                  item.amount,
                  `Completed action ${index + 1} amount`,
                );
          if (item.action !== "check" && (amount === null || amount <= 0)) {
            throw new Error(
              `Completed action ${index + 1} amount must be greater than 0`,
            );
          }
          return {
            street: item.street,
            actor: item.actor,
            action: item.action,
            amount,
          };
        })
      : [];
  const completedPostflopStreets: CompletedPostflopStreetHistory[] = (
    ["flop", "turn"] as const
  ).flatMap((street) => {
    const actions = completedPostflopActions
      .filter((action) => action.street === street)
      .map(({ actor, action, amount }) => ({ actor, action, amount }));
    return actions.length > 0 ? [{ street, actions }] : [];
  });
  const potSize = parseOptionalNumber(form.pot_size, "Pot");
  const playersInHand = parseOptionalInteger(
    form.players_in_hand,
    "Players in hand",
  );
  const currentBet = parseOptionalNumber(form.current_bet, "Current bet");
  const usesOpponentPosition = requiresOpponentPosition({
    street: form.street,
    players_in_hand: playersInHand,
    hero_position: form.hero_position,
  });
  const needsCommittedOpponentCount =
    (currentBet ?? 0) > 0 && (playersInHand ?? 0) > 2;
  const opponentsAtCurrentBet = needsCommittedOpponentCount
    ? parseOptionalInteger(
        form.opponents_at_current_bet,
        "Opponents at current bet",
      )
    : null;
  const opponentWager =
    (currentBet ?? 0) > 0
      ? parseOptionalNumber(form.opponent_wager, "Opponent wager total")
      : null;
  const usesOpponentCommitmentTotal =
    ((currentBet ?? 0) <= 0 && form.street === "preflop") ||
    ((currentBet ?? 0) > 0 && (playersInHand ?? 0) > 2);
  const opponentCommitmentTotal = usesOpponentCommitmentTotal
    ? parseOptionalNumber(
        form.opponent_commitment_total,
        "Opponent commitments total",
      )
    : null;
  if (
    opponentsAtCurrentBet !== null &&
    playersInHand !== null &&
    opponentsAtCurrentBet >= playersInHand
  ) {
    throw new Error(
      "Opponents at current bet must be lower than players in hand",
    );
  }
  if (opponentWager !== null && opponentWager <= 0) {
    throw new Error("Opponent wager total must be greater than 0");
  }
  if (
    opponentWager !== null &&
    currentBet !== null &&
    opponentWager < currentBet
  ) {
    throw new Error("Opponent wager total must be at least the current bet");
  }
  if (opponentCommitmentTotal !== null && opponentCommitmentTotal <= 0) {
    throw new Error("Opponent commitments total must be greater than 0");
  }
  if (
    opponentCommitmentTotal !== null &&
    potSize !== null &&
    opponentCommitmentTotal > potSize + 0.000001
  ) {
    throw new Error("Opponent commitments total cannot exceed the pot");
  }
  const recordedWagers =
    form.street === "preflop"
      ? preflopActionHistory.map((action) => action.amount)
      : form.street !== ""
        ? postflopActionHistory.flatMap((action) =>
            action.amount === null ? [] : [action.amount],
          )
        : [];
  const knownOpponentWager =
    opponentWager ?? Math.max(currentBet ?? 0, ...recordedWagers);
  const minimumOpponentCommitments =
    knownOpponentWager > 0
      ? knownOpponentWager * (opponentsAtCurrentBet ?? 1)
      : null;
  if (
    opponentCommitmentTotal !== null &&
    minimumOpponentCommitments !== null &&
    opponentCommitmentTotal + 0.000001 < minimumOpponentCommitments
  ) {
    throw new Error(
      "Opponent commitments total must cover opponents at the current wager",
    );
  }
  const knownLatestWager = opponentWager ?? Math.max(0, ...recordedWagers);
  const maximumOpponentCommitments =
    knownLatestWager > 0 && playersInHand !== null
      ? knownLatestWager * (playersInHand - 1)
      : null;
  if (
    opponentCommitmentTotal !== null &&
    maximumOpponentCommitments !== null &&
    opponentCommitmentTotal > maximumOpponentCommitments + 0.000001
  ) {
    throw new Error(
      "Opponent commitments total cannot exceed the latest wager across active opponents",
    );
  }

  return {
    hero_cards: heroCards,
    board_cards: boardCards,
    pot_size: potSize,
    current_bet: currentBet,
    hero_stack: parseOptionalNumber(form.hero_stack, "Hero stack"),
    opponent_stack: showOpponentStack
      ? parseOptionalNumber(form.opponent_stack, "Opponent stack")
      : null,
    effective_stack: parseOptionalNumber(
      form.effective_stack,
      "Effective stack",
    ),
    players_in_hand: playersInHand,
    opponents_at_current_bet: needsCommittedOpponentCount
      ? opponentsAtCurrentBet
      : null,
    opponent_wager: opponentWager,
    opponent_commitment_total: opponentCommitmentTotal,
    hero_position:
      form.hero_position.trim() === "" ? null : form.hero_position.trim(),
    opponent_position:
      usesOpponentPosition && form.opponent_position.trim() !== ""
        ? form.opponent_position.trim()
        : null,
    preflop_opener_position:
      structuredOpener?.actor ??
      (preserveLegacyOpener && form.preflop_opener_position !== ""
        ? form.preflop_opener_position
        : null),
    preflop_open_size:
      structuredOpener?.amount ??
      (preserveLegacyOpener ? legacyPreflopOpenSize : null),
    preflop_action_history: preflopActionHistory,
    street: form.street === "" ? null : form.street,
    facing_action: form.facing_action === "" ? null : form.facing_action,
    postflop_action_history: postflopActionHistory,
    completed_postflop_streets: completedPostflopStreets,
    action_context:
      form.action_context.trim() === "" ? null : form.action_context.trim(),
    user_approved: false,
  };
}
