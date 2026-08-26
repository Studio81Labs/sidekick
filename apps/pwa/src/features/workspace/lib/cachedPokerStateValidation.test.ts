import { describe, expect, it } from "vitest";

import { detectedState } from "../../../test/analyzerHarness";
import {
  isCachedCanonicalState,
  isCachedDetectedState,
} from "./cachedPokerStateValidation";

describe("cached poker-state validation", () => {
  it("accepts canonical state only with an explicit approval flag", () => {
    expect(
      isCachedCanonicalState({ ...detectedState, user_approved: true }),
    ).toBe(true);
    expect(isCachedCanonicalState(detectedState)).toBe(false);
  });

  it("rejects duplicate cards and invalid preflop actors", () => {
    expect(
      isCachedDetectedState({
        ...detectedState,
        board_cards: [detectedState.hero_cards[0]],
      }),
    ).toBe(false);
    expect(
      isCachedDetectedState({
        ...detectedState,
        preflop_action_history: [
          { actor: "dealer", action: "raise", amount: 2.5 },
        ],
      }),
    ).toBe(false);
  });

  it("validates completed history against the current street", () => {
    const completedFlop = {
      street: "flop",
      actions: [
        { actor: "oop", action: "check", amount: null },
        { actor: "ip", action: "check", amount: null },
      ],
    };

    expect(
      isCachedDetectedState({
        ...detectedState,
        street: "turn",
        completed_postflop_streets: [completedFlop],
      }),
    ).toBe(true);
    expect(
      isCachedDetectedState({
        ...detectedState,
        street: "flop",
        completed_postflop_streets: [completedFlop],
      }),
    ).toBe(false);
  });
});
