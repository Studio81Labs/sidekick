import { describe, expect, it } from "vitest";

import {
  benchmarkComparisonValue,
  benchmarkMismatchLabel,
  benchmarkPostflopActionValue,
  benchmarkPreflopActionValue,
} from "./benchmarkValuePresentation";

describe("benchmark value presentation", () => {
  it("formats reviewed preflop and postflop actions", () => {
    expect(
      benchmarkPreflopActionValue({
        actor: "button",
        action: "raise",
        amount: 2.5,
      }),
    ).toBe("Button raise to 2.5 BB");
    expect(
      benchmarkPostflopActionValue({ actor: "oop", action: "check" }),
    ).toBe("OOP check");
    expect(
      benchmarkComparisonValue([
        { actor: "button", action: "call", amount: 2 },
        { actor: "ip", action: "bet", amount: 4 },
      ]),
    ).toBe("Button call 2 BB; IP bet 4 BB");
  });

  it("keeps missing values and mismatch counts readable", () => {
    expect(benchmarkComparisonValue(null)).toBe("Not detected");
    expect(benchmarkComparisonValue([])).toBe("None");
    expect(
      benchmarkMismatchLabel([
        {
          field: "pot_bb",
          expected: 10,
          detected: 8,
          matched: false,
          confidence: 0.8,
        },
      ]),
    ).toBe("1 mismatch");
  });
});
