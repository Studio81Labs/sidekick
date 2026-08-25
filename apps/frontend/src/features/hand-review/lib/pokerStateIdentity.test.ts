import { describe, expect, it } from "vitest";

import {
  approvalKey,
  benchmarkApprovalKey,
  toCanonicalState,
} from "./canonicalPokerState";
import { CONFIDENCE_KEYS, EMPTY_STATE } from "./pokerStateConstants";
import { summarizeConfidences } from "./pokerStateConfidence";
import { normalizePreflopPosition } from "../../../domains/poker/model/preflopPosition";

describe("poker state identity and confidence", () => {
  it("normalizes common preflop position aliases", () => {
    expect(normalizePreflopPosition("Under_the-gun")).toBe("utg");
    expect(normalizePreflopPosition(" BTN ")).toBe("button");
    expect(normalizePreflopPosition("unknown")).toBeNull();
  });

  it("fills optional canonical fields for legacy detected state", () => {
    const state = toCanonicalState({
      hero_cards: [],
      board_cards: [],
      pot_size: 3,
      current_bet: 0,
      hero_stack: null,
      effective_stack: 100,
      players_in_hand: 2,
      hero_position: "button",
      preflop_opener_position: null,
      preflop_open_size: null,
      street: "flop",
      facing_action: null,
      action_context: null,
    });

    expect(state).toMatchObject({
      hero_stack: null,
      opponent_stack: null,
      opponent_wager: null,
      preflop_action_history: [],
      postflop_action_history: [],
      completed_postflop_streets: [],
      user_approved: false,
    });
  });

  it("keeps review identity stricter than benchmark corpus identity", () => {
    const base = {
      ...EMPTY_STATE,
      current_bet: 2,
      opponent_wager: 2,
    };
    const changed = { ...base, opponent_wager: 4 };

    expect(approvalKey(base)).not.toBe(approvalKey(changed));
    expect(benchmarkApprovalKey(base)).toBe(benchmarkApprovalKey(changed));
  });

  it("adds conditional wager and position fields to confidence summaries", () => {
    const state = {
      ...EMPTY_STATE,
      street: "flop" as const,
      current_bet: 2,
      players_in_hand: 2,
      hero_position: "cutoff",
    };
    const summary = summarizeConfidences(
      {
        hero_cards: 0.9,
        opponent_wager: 0.6,
        opponent_position: 0.8,
      },
      ["Review board"],
      state,
    );

    expect(summary).toEqual({
      averageConfidence: 77,
      detectedCount: 3,
      fieldTotal: CONFIDENCE_KEYS.length + 2,
      reviewCount: 2,
    });
  });
});
