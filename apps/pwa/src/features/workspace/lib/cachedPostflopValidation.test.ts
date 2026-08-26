import { describe, expect, it } from "vitest";

import {
  isCachedCompletedPostflopHistory,
  isCachedCompletedPostflopStreet,
  isCachedPostflopAction,
} from "./cachedPostflopValidation";

describe("cached postflop validation", () => {
  it("accepts terminal check and bet-call lines", () => {
    expect(
      isCachedCompletedPostflopStreet({
        street: "flop",
        actions: [
          { actor: "oop", action: "check", amount: null },
          { actor: "ip", action: "check", amount: null },
        ],
      }),
    ).toBe(true);
    expect(
      isCachedCompletedPostflopStreet({
        street: "turn",
        actions: [
          { actor: "oop", action: "bet", amount: 3 },
          { actor: "ip", action: "call", amount: 3 },
        ],
      }),
    ).toBe(true);
  });

  it("rejects out-of-order and non-terminal completed lines", () => {
    expect(
      isCachedCompletedPostflopStreet({
        street: "flop",
        actions: [
          { actor: "ip", action: "check", amount: null },
          { actor: "oop", action: "check", amount: null },
        ],
      }),
    ).toBe(false);
    expect(
      isCachedCompletedPostflopStreet({
        street: "flop",
        actions: [
          { actor: "oop", action: "bet", amount: 3 },
          { actor: "ip", action: "raise", amount: 8 },
        ],
      }),
    ).toBe(false);
  });

  it("requires completed streets to precede the current street in order", () => {
    const flop = {
      street: "flop",
      actions: [
        { actor: "oop", action: "check", amount: null },
        { actor: "ip", action: "check", amount: null },
      ],
    };

    expect(isCachedCompletedPostflopHistory([flop], "turn")).toBe(true);
    expect(isCachedCompletedPostflopHistory([flop], "river")).toBe(true);
    expect(isCachedCompletedPostflopHistory([flop], "flop")).toBe(false);
  });

  it("allows only current-street check, bet, and raise actions", () => {
    expect(
      isCachedPostflopAction({ actor: "oop", action: "check", amount: null }),
    ).toBe(true);
    expect(
      isCachedPostflopAction({ actor: "ip", action: "call", amount: 3 }),
    ).toBe(false);
  });
});
