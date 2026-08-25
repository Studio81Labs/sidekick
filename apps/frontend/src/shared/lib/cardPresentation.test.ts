import { describe, expect, it } from "vitest";

import {
  cardToCode,
  cardToDisplay,
  CODE_BY_SUIT,
  isRedSuit,
  SUIT_BY_CODE,
} from "./cardPresentation";
import type { Card } from "../types/poker";

describe("card presentation", () => {
  it.each([
    [{ rank: "A", suit: "clubs" }, "Ac", "A♣", false],
    [{ rank: "K", suit: "diamonds" }, "Kd", "K♦", true],
    [{ rank: "Q", suit: "hearts" }, "Qh", "Q♥", true],
    [{ rank: "J", suit: "spades" }, "Js", "J♠", false],
  ] satisfies Array<[Card, string, string, boolean]>)(
    "formats $suit cards",
    (card, code, display, red) => {
      expect(cardToCode(card)).toBe(code);
      expect(cardToDisplay(card)).toBe(display);
      expect(isRedSuit(card)).toBe(red);
    },
  );

  it("keeps parsing and formatting suit maps reciprocal", () => {
    for (const [suit, code] of Object.entries(CODE_BY_SUIT)) {
      expect(SUIT_BY_CODE[code]).toBe(suit);
    }
  });
});
