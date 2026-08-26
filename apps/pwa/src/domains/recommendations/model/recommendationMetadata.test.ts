import { describe, expect, it } from "vitest";

import {
  metadataExactString,
  metadataLabel,
  metadataNumber,
  metadataRatio,
  metadataRecord,
  metadataString,
  metadataStringList,
} from "./recommendationMetadata";

describe("recommendation metadata", () => {
  it("accepts only bounded values with the expected shape", () => {
    expect(metadataRecord({ engine: "local_solver" })).toEqual({
      engine: "local_solver",
    });
    expect(metadataRecord([])).toBeNull();
    expect(metadataNumber(12.5)).toBe(12.5);
    expect(metadataNumber(Number.POSITIVE_INFINITY)).toBeNull();
    expect(metadataRatio(0.4)).toBe(0.4);
    expect(metadataRatio(1.1)).toBeNull();
  });

  it("normalizes display strings without accepting blank metadata", () => {
    expect(metadataString("  local solver  ")).toBe("local solver");
    expect(metadataString("abcdef", 5)).toBe("ab...");
    expect(metadataExactString("  AA,KK  ")).toBe("AA,KK");
    expect(metadataExactString("   ")).toBeNull();
    expect(metadataLabel("hero_position")).toBe("Hero position");
    expect(metadataLabel("oop")).toBe("OOP");
  });

  it("limits and filters metadata lists", () => {
    expect(metadataStringList([" flop ", "", 7, "turn", "river"], 3)).toEqual([
      "flop",
    ]);
    expect(metadataStringList("flop")).toEqual([]);
  });
});
