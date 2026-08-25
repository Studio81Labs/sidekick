import { describe, expect, it } from "vitest";

import type { RecommendationResult } from "../../../shared/types/recommendations";
import { recommendationCandidatesFromRaw } from "./recommendationCandidates";
import { recommendationEvidenceFromRaw } from "./recommendationEvidence";

const recommendation: RecommendationResult = {
  action: "raise",
  sizing: 12,
  confidence: 0.8,
  explanation: "Training example",
  raw: {},
};

describe("recommendation evidence", () => {
  it("combines solver metrics, preflop context, postflop ranges, and candidates", () => {
    const evidence = recommendationEvidenceFromRaw(
      {
        engine: "postflop_solver",
        equity: { equity: 0.62 },
        realized_equity: 0.58,
        required_equity: 0.25,
        stack_depth_policy: "deep",
        effective_stack: 100,
        opponents_at_current_bet: 1,
        opponent_wager: 4,
        hero_position: "ip",
        modeled_history: ["check", "bet"],
        tree: {
          starting_pot: 10,
          effective_stack: 90,
          max_iterations: 100,
          compressed_memory_mb: 12,
        },
        range_source: "preflop_chart_single_raised_pot",
        range_context: {
          stack_depth_policy: "standard",
          starting_effective_stack_bb: 100,
          stack_depth_source: "reconstructed",
          opener_position: "utg",
          caller_position: "ip",
          opening_size_bb: 2.5,
          opener_fraction: 0.2,
          caller_continue_fraction: 0.3,
          caller_reraise_fraction: 0.05,
        },
        ranges: { oop: "AA,KK", ip: "AKs,AQs" },
        candidates: [
          { action: "fold", ev: 5, frequency: 0.1 },
          { action: "check", ev: 4, frequency: 0.2 },
          { action: "call", ev: 3, frequency: 0.3 },
          { action: "bet", sizing: 8, ev: 2, frequency: 0.2 },
          { action: "raise", sizing: 12, ev: 1, frequency: 0.2 },
        ],
      },
      recommendation,
    );

    expect(evidence).not.toBeNull();
    expect(evidence?.engine).toBe("Postflop solver");
    expect(evidence?.metrics).toContainEqual({
      label: "Range equity",
      value: 0.62,
      unit: "percent",
    });
    expect(evidence?.details).toContainEqual({
      label: "Stack depth",
      value: "Deep · 100 BB",
    });
    expect(evidence?.details).toContainEqual({
      label: "Range source",
      value: "Preflop chart · single-raised pot",
    });
    expect(evidence?.details).toContainEqual({
      label: "Range actors",
      value: "UTG opens 2.5 BB · IP calls",
    });
    expect(evidence?.ranges).toEqual([
      { label: "OOP", value: "AA,KK" },
      { label: "IP", value: "AKs,AQs" },
    ]);
    expect(evidence?.candidates.map(({ action }) => action)).toEqual([
      "fold",
      "check",
      "call",
      "raise",
    ]);
  });

  it("returns no evidence when metadata has nothing presentable", () => {
    expect(recommendationEvidenceFromRaw({}, recommendation)).toBeNull();
  });

  it("keeps the chosen action visible when it ranks below the first page", () => {
    const candidates = recommendationCandidatesFromRaw(
      {
        candidates: [
          { action: "fold", ev: 5 },
          { action: "check", ev: 4 },
          { action: "call", ev: 3 },
          { action: "bet", sizing: 8, ev: 2 },
          { action: "raise", sizing: 12, ev: 1 },
        ],
      },
      recommendation,
    );

    expect(candidates.map(({ action }) => action)).toEqual([
      "fold",
      "check",
      "call",
      "raise",
    ]);
  });
});
