import { describe, expect, it } from "vitest";

import { unitIntervalPercentage } from "./playerDecimal";

describe("unitIntervalPercentage", () => {
  it("formats decimal and scientific unit-interval values without coercion", () => {
    expect(unitIntervalPercentage("0.05")).toBe("5");
    expect(unitIntervalPercentage("1E-7")).toBe("0.00001");
    expect(unitIntervalPercentage("1.000")).toBe("100");
    expect(unitIntervalPercentage("0E-7")).toBe("0");
  });

  it("does not present invalid unit-interval values as percentages", () => {
    expect(unitIntervalPercentage("1.0001")).toBeNull();
    expect(unitIntervalPercentage("-0.01")).toBeNull();
    expect(unitIntervalPercentage("not-a-decimal")).toBeNull();
  });
});
