import { describe, expect, it } from "vitest";

import type { StateForm } from "./pokerStateForm";
import { EMPTY_STATE } from "./pokerStateConstants";
import { formToCanonical, stateToForm } from "./pokerStateConversion";

function emptyForm(overrides: Partial<StateForm> = {}): StateForm {
  return {
    hero_cards: "",
    board_cards: "",
    pot_size: "",
    current_bet: "",
    hero_stack: "",
    opponent_stack: "",
    effective_stack: "",
    players_in_hand: "",
    opponents_at_current_bet: "",
    opponent_wager: "",
    opponent_commitment_total: "",
    hero_position: "",
    opponent_position: "",
    preflop_opener_position: "",
    preflop_open_size: "",
    preflop_action_history: [],
    street: "",
    facing_action: "",
    postflop_action_history: [],
    completed_postflop_actions: [],
    action_context: "",
    ...overrides,
  };
}

describe("poker state conversion", () => {
  it("converts a heads-up postflop form into canonical state", () => {
    const state = formToCanonical(
      emptyForm({
        hero_cards: "As Kd",
        board_cards: "Qh Jc 2s",
        pot_size: "10",
        current_bet: "2",
        hero_stack: "95",
        effective_stack: "80",
        players_in_hand: "2",
        opponent_wager: "2",
        hero_position: "cutoff",
        opponent_position: "button",
        street: "flop",
        facing_action: "bet",
        action_context: "Opponent bets flop",
      }),
    );

    expect(state).toMatchObject({
      pot_size: 10,
      current_bet: 2,
      players_in_hand: 2,
      opponent_wager: 2,
      hero_position: "cutoff",
      opponent_position: "button",
      street: "flop",
      facing_action: "bet",
      action_context: "Opponent bets flop",
      user_approved: false,
    });
    expect(state.hero_cards).toEqual([
      { rank: "A", suit: "spades" },
      { rank: "K", suit: "diamonds" },
    ]);
  });

  it("normalizes legacy opener positions when building the form", () => {
    const form = stateToForm({
      ...EMPTY_STATE,
      street: "preflop",
      preflop_opener_position: "CO",
      preflop_open_size: 2.5,
    });

    expect(form.preflop_opener_position).toBe("cutoff");
    expect(form.preflop_open_size).toBe("2.5");
  });

  it("rejects opponent commitments that cannot fit in the pot", () => {
    expect(() =>
      formToCanonical(
        emptyForm({
          pot_size: "5",
          current_bet: "2",
          players_in_hand: "3",
          opponents_at_current_bet: "2",
          opponent_wager: "2",
          opponent_commitment_total: "6",
          street: "flop",
        }),
      ),
    ).toThrow("Opponent commitments total cannot exceed the pot");
  });
});
