import { describe, expect, it } from "vitest";

import { benchmarkFieldLabel, benchmarkPercent } from "./metricPresentation";

describe("metric presentation", () => {
  it("formats benchmark accuracy as whole percent", () => {
    expect(benchmarkPercent(0.754)).toBe("75%");
    expect(benchmarkPercent(1)).toBe("100%");
  });

  it("humanizes benchmark field names", () => {
    expect(benchmarkFieldLabel("hero_cards")).toBe("hero cards");
  });
});
