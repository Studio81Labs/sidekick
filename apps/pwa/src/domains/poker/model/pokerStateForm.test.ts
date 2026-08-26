import { describe, expect, it } from "vitest";

import { requiresOpponentPosition } from "./pokerStateForm";

describe("requiresOpponentPosition", () => {
  it.each([
    ["flop", "2", "cutoff", true],
    ["river", 2, "small_blind", true],
    ["flop", "2", "button", false],
    ["turn", 2, "in-position", false],
    ["preflop", 2, "cutoff", false],
    ["flop", 3, "cutoff", false],
    [null, 2, "cutoff", false],
  ] as const)(
    "returns %s/%s/%s visibility as %s",
    (street, playersInHand, heroPosition, expected) => {
      expect(
        requiresOpponentPosition({
          street,
          players_in_hand: playersInHand,
          hero_position: heroPosition,
        }),
      ).toBe(expected);
    },
  );
});
