import { describe, expect, it } from "vitest";

import {
  formatCards,
  parseCards,
  parseOptionalInteger,
  parseOptionalNumber,
  validateCardState,
} from "./pokerStateParsing";

describe("poker state parsing", () => {
  it("parses compact and ten-prefixed card codes", () => {
    const cards = parseCards("As, 10h kd", "Cards");

    expect(cards).toEqual([
      { rank: "A", suit: "spades" },
      { rank: "T", suit: "hearts" },
      { rank: "K", suit: "diamonds" },
    ]);
    expect(formatCards(cards)).toBe("As Th Kd");
  });

  it("rejects invalid and duplicate cards", () => {
    expect(() => parseCards("1s", "Hero cards")).toThrow(
      "Hero cards contains an invalid card code: 1s",
    );
    expect(() =>
      validateCardState(parseCards("As Kd", "Hero"), parseCards("As", "Board")),
    ).toThrow("Duplicate card in state: As");
  });

  it("parses optional non-negative numbers and positive integers", () => {
    expect(parseOptionalNumber("", "Pot")).toBeNull();
    expect(parseOptionalNumber("12.5", "Pot")).toBe(12.5);
    expect(() => parseOptionalNumber("-1", "Pot")).toThrow(
      "Pot must be a non-negative number",
    );
    expect(parseOptionalInteger("3", "Players")).toBe(3);
    expect(() => parseOptionalInteger("2.5", "Players")).toThrow(
      "Players must be a whole number",
    );
    expect(() => parseOptionalInteger("0", "Players")).toThrow(
      "Players must be at least 1",
    );
  });
});
