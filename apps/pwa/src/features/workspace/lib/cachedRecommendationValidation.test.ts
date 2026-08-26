import { describe, expect, it } from "vitest";

import { recommendation } from "../../../test/analyzerHarness";
import {
  isCachedActionSizing,
  isCachedRecommendation,
  isCachedTrainingDecision,
} from "./cachedRecommendationValidation";

describe("cached recommendation validation", () => {
  it("matches sizing to the action", () => {
    expect(isCachedActionSizing("raise", 7.5)).toBe(true);
    expect(isCachedActionSizing("raise", null)).toBe(true);
    expect(isCachedActionSizing("call", null)).toBe(true);
    expect(isCachedActionSizing("call", 2.5)).toBe(false);
  });

  it("requires bounded confidence and object evidence", () => {
    expect(isCachedRecommendation(recommendation)).toBe(true);
    expect(
      isCachedRecommendation({ ...recommendation, confidence: 1.01 }),
    ).toBe(false);
    expect(isCachedRecommendation({ ...recommendation, raw: [] })).toBe(false);
  });

  it("accepts only known certainty values in training decisions", () => {
    const decision = {
      action: "call",
      sizing: null,
      certainty: "high",
      recorded_at: "2026-08-15T00:00:00Z",
    };

    expect(isCachedTrainingDecision(decision)).toBe(true);
    expect(
      isCachedTrainingDecision({ ...decision, certainty: "certain" }),
    ).toBe(false);
  });
});
