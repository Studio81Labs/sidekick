import { describe, expect, it } from "vitest";

import type { RecommendationResult } from "../../../shared/types/recommendations";
import {
  parseTrainingSizing,
  recommendationEvLossBb,
  recommendationPolicySupport,
  trainingDecisionComparison,
  trainingSizingMatches,
} from "./trainingDecision";

const recommendation: RecommendationResult = {
  action: "bet",
  sizing: 5,
  confidence: 0.8,
  explanation: "Training example",
  raw: {
    candidates: [
      { action: "check", sizing: null, ev: 1.1, frequency: 0.25 },
      { action: "bet", sizing: 5, ev: 1.4, frequency: 0.65 },
      { action: "bet", sizing: 8, ev: 1.2, frequency: 0.1 },
    ],
  },
};

describe("training decision presentation", () => {
  it("distinguishes exact, mixed, and differently sized solver lines", () => {
    expect(trainingDecisionComparison("bet", 5, recommendation)).toMatchObject({
      label: "Matched solver",
      tone: "match",
      evLossBb: 0,
    });
    expect(
      trainingDecisionComparison("check", null, recommendation),
    ).toMatchObject({
      label: "Solver-supported mix",
      tone: "match",
      evLossBb: 0.3,
    });
    expect(trainingDecisionComparison("bet", 6, recommendation)).toMatchObject({
      label: "Same action, different size",
      tone: "partial",
      evLossBb: null,
    });
  });

  it("requires supported frequency and valid action sizing", () => {
    expect(recommendationPolicySupport("check", null, recommendation)).toBe(
      "line",
    );
    expect(recommendationPolicySupport("bet", 6, recommendation)).toBe(
      "action",
    );
    expect(recommendationPolicySupport("raise", 12, recommendation)).toBeNull();
    expect(recommendationEvLossBb("check", null, recommendation)).toBe(0.3);
  });

  it("compares decimal sizing at the strict tolerance boundary", () => {
    expect(trainingSizingMatches(10, 10.009)).toBe(true);
    expect(trainingSizingMatches(10, 10.01)).toBe(false);
    expect(trainingSizingMatches(null, null)).toBe(true);
    expect(trainingSizingMatches(Number.NaN, Number.NaN)).toBe(false);
  });

  it("parses sizing only for aggressive actions", () => {
    expect(parseTrainingSizing("call", "12")).toEqual({
      sizing: null,
      error: null,
    });
    expect(parseTrainingSizing("raise", "12.5")).toEqual({
      sizing: 12.5,
      error: null,
    });
    expect(parseTrainingSizing("bet", "0")).toEqual({
      sizing: null,
      error: "Enter a valid positive decision size",
    });
  });
});
