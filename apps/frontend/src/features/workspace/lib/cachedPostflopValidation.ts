import type {
  CompletedPostflopAction,
  CompletedPostflopActionType,
  CompletedPostflopStreetHistory,
  PostflopAction,
  PostflopActor,
} from "../../../shared/types/poker";
import { SIZING_MATCH_TOLERANCE } from "../../../domains/training/model/trainingOptions";

export function isCachedPostflopAction(
  value: unknown,
): value is PostflopAction {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const action = value as Partial<PostflopAction>;
  return (
    (action.actor === "oop" || action.actor === "ip") &&
    (action.action === "check" ||
      action.action === "bet" ||
      action.action === "raise") &&
    (action.action === "check"
      ? action.amount === null
      : typeof action.amount === "number" &&
        Number.isFinite(action.amount) &&
        action.amount > 0)
  );
}

export function isCachedCompletedPostflopAction(
  value: unknown,
): value is CompletedPostflopAction {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const action = value as Partial<CompletedPostflopAction>;
  return (
    (action.actor === "oop" || action.actor === "ip") &&
    (action.action === "check" ||
      action.action === "bet" ||
      action.action === "raise" ||
      action.action === "call") &&
    (action.action === "check"
      ? action.amount === null
      : typeof action.amount === "number" &&
        Number.isFinite(action.amount) &&
        action.amount > 0)
  );
}

export function isCachedCompletedPostflopStreet(
  value: unknown,
): value is CompletedPostflopStreetHistory {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const history = value as Partial<CompletedPostflopStreetHistory>;
  if (
    !(
      (history.street === "flop" || history.street === "turn") &&
      Array.isArray(history.actions) &&
      history.actions.length >= 2 &&
      history.actions.length <= 8 &&
      history.actions.every(isCachedCompletedPostflopAction)
    )
  ) {
    return false;
  }

  const contributions: Record<PostflopActor, number> = { oop: 0, ip: 0 };
  let nextActor: PostflopActor = "oop";
  let previousAction: CompletedPostflopActionType | null = null;
  let terminal = false;
  for (let index = 0; index < history.actions.length; index += 1) {
    const action = history.actions[index];
    if (terminal || action.actor !== nextActor) {
      return false;
    }
    const opponent: PostflopActor = action.actor === "oop" ? "ip" : "oop";
    const actorTotal = contributions[action.actor];
    const opponentTotal = contributions[opponent];
    const amount = action.amount ?? 0;
    if (action.action === "check") {
      if (Math.abs(actorTotal - opponentTotal) > SIZING_MATCH_TOLERANCE) {
        return false;
      }
      terminal = previousAction === "check";
    } else if (action.action === "bet") {
      if (
        Math.abs(actorTotal - opponentTotal) > SIZING_MATCH_TOLERANCE ||
        actorTotal > SIZING_MATCH_TOLERANCE
      ) {
        return false;
      }
      contributions[action.actor] = amount;
    } else if (action.action === "raise") {
      if (
        actorTotal >= opponentTotal - SIZING_MATCH_TOLERANCE ||
        amount <= opponentTotal + SIZING_MATCH_TOLERANCE
      ) {
        return false;
      }
      contributions[action.actor] = amount;
    } else {
      if (
        actorTotal >= opponentTotal - SIZING_MATCH_TOLERANCE ||
        Math.abs(amount - opponentTotal) > SIZING_MATCH_TOLERANCE
      ) {
        return false;
      }
      contributions[action.actor] = opponentTotal;
      terminal = true;
    }
    if (terminal && index !== history.actions.length - 1) {
      return false;
    }
    previousAction = action.action;
    nextActor = opponent;
  }
  return terminal;
}

export function isCachedCompletedPostflopHistory(
  value: unknown,
  currentStreet: unknown,
): value is CompletedPostflopStreetHistory[] | undefined {
  if (value === undefined) {
    return true;
  }
  if (
    !Array.isArray(value) ||
    value.length > 2 ||
    !value.every(isCachedCompletedPostflopStreet)
  ) {
    return false;
  }
  const expected =
    currentStreet === "turn"
      ? ["flop"]
      : currentStreet === "river"
        ? ["flop", "turn"]
        : [];
  return value.every((history, index) => history.street === expected[index]);
}
