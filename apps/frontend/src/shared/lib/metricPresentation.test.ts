import { describe, expect, it } from "vitest";

import {
  accessiblePointDelta,
  benchmarkFieldLabel,
  benchmarkPercent,
  formatAccuracyDelta,
  formatCandidateValue,
  formatEvLossBb,
  formatEvLossDeltaBb,
  trainingTrendWindowLabel,
  trainingTrendTone,
} from "./metricPresentation";

describe("metric presentation", () => {
  it("rounds candidate values and percentages consistently", () => {
    expect(formatCandidateValue(1.23456)).toBe("1.235");
    expect(formatCandidateValue(2)).toBe("2");
    expect(benchmarkPercent(0.754)).toBe("75%");
    expect(benchmarkFieldLabel("hero_cards")).toBe("hero cards");
    expect(formatEvLossBb(0.0432)).toBe("0.043 BB");
  });

  it("formats signed training deltas", () => {
    expect(formatAccuracyDelta(0.251)).toBe("+25 pts");
    expect(formatAccuracyDelta(-0.5)).toBe("-50 pts");
    expect(formatEvLossDeltaBb(0.4)).toBe("+0.4 BB");
    expect(formatEvLossDeltaBb(-1.2)).toBe("-1.2 BB");
    expect(accessiblePointDelta(0.01)).toBe("+1 percentage point");
    expect(accessiblePointDelta(-0.02)).toBe("-2 percentage points");
    expect(trainingTrendWindowLabel({ window_hands: 1 })).toBe(
      "Last 1 hand vs previous 1",
    );
  });

  it("accounts for whether higher or lower metrics are better", () => {
    expect(trainingTrendTone(0.1)).toBe("improving");
    expect(trainingTrendTone(-0.1)).toBe("declining");
    expect(trainingTrendTone(-0.1, true)).toBe("improving");
    expect(trainingTrendTone(0.1, true)).toBe("declining");
    expect(trainingTrendTone(0)).toBe("neutral");
  });
});
