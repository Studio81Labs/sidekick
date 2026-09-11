import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StructuredHandReviewEditor } from "./StructuredHandReviewEditor";
import type { ImportedHandState } from "./playerApi";

afterEach(() => cleanup());

function recordedState(): ImportedHandState {
  const evidence = {
    raw_source_id: "source-1",
    line_start: 4,
    line_end: 4,
    marker: "forced-post",
  };
  return {
    identity: {
      namespace: "site-hand-id/v1",
      site: "pokerstars",
      source_hand_id: "123456789",
    },
    chronology: {
      played_at: "2026-09-11T12:00:00Z",
      source_timezone: "Europe/Prague",
      source_session_id: "session-1",
      source_file_id: "source-1",
      hand_ordinal: 1,
    },
    game: {
      variant: "texas_holdem",
      betting_limit: "no_limit",
      table_size: 2,
      blinds: {
        small_blind: "0.50",
        big_blind: "1.00",
        ante: null,
        ante_mode: "unknown",
        straddle: null,
      },
      economics: { kind: "cash", currency: "USD", rake: null },
    },
    button_seat: 1,
    seats: [
      {
        seat_number: 1,
        player_id: "hero",
        display_name: "Hero",
        starting_stack: "100.00",
        participation: "dealt_in",
        position: {
          dealt_in_player_count: 2,
          action_index: 0,
          button_distance: 0,
          display_label: "BTN/SB",
        },
      },
      {
        seat_number: 2,
        player_id: "villain",
        display_name: "Villain",
        starting_stack: "100.00",
        participation: "dealt_in",
        position: {
          dealt_in_player_count: 2,
          action_index: 1,
          button_distance: 1,
          display_label: "BB",
        },
      },
    ],
    hero_player_id: "hero",
    hero_cards: [],
    streets: [
      {
        street: "preflop",
        board_cards: [],
        actions: [
          {
            sequence: 0,
            actor_id: "hero",
            action_type: "post_small_blind",
            amount: "0.50",
            total_committed: "0.50",
            all_in: false,
            origin: {
              kind: "forced_system",
              basis: "explicit_marker",
              confidence: "1.00",
              evidence: [evidence],
              semantics_revision: "pokerstars-v1",
              automatic_reason: null,
              review_reference: null,
            },
            evidence: [evidence],
          },
        ],
      },
    ],
    results: {
      stated_pot: {
        gross_total: null,
        rake: null,
        net_total: null,
        gross_pots: [],
      },
      showdown: [],
      awards: [],
      players: [],
    },
  };
}

describe("StructuredHandReviewEditor", () => {
  it("preserves decimal text and explicit nullable/list result values", () => {
    const onChange = vi.fn();
    render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={recordedState()}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByRole("textbox", { name: /Small blind/ }), {
      target: { value: "0.500" },
    });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        game: expect.objectContaining({
          blinds: expect.objectContaining({ small_blind: "0.500" }),
        }),
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Add amount" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        results: expect.objectContaining({
          stated_pot: expect.objectContaining({ gross_pots: [""] }),
          showdown: [],
          awards: [],
          players: [],
        }),
      }),
    );
  });

  it("renders canonical card suits in the editable selectors", () => {
    const state = recordedState();
    state.hero_cards = [{ rank: "A", suit: "spades" }];
    render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={state}
        onChange={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("combobox", { name: "Hero cards 1 suit" }),
    ).toHaveValue("spades");
  });

  it("clears derived positions when the button seat changes", () => {
    const onChange = vi.fn();
    render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={recordedState()}
        onChange={onChange}
      />,
    );

    const buttonSeat = screen
      .getByText("Button seat")
      .closest("label")
      ?.querySelector("input");
    if (!buttonSeat) throw new Error("Expected a button-seat control");
    fireEvent.change(buttonSeat, { target: { value: "2" } });
    expect(onChange).toHaveBeenCalled();

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        seats: [
          expect.objectContaining({
            position: null,
          }),
          expect.objectContaining({ position: null }),
        ],
      }),
    );
  });

  it("binds newly added action rows to a retained source locator", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={recordedState()}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Add action" }));
    const withNewAction = onChange.mock.lastCall?.[0] as ImportedHandState;
    rerender(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={withNewAction}
        onChange={onChange}
      />,
    );

    const evidenceSelect = screen.getByRole("combobox", {
      name: "Bind retained source evidence",
    });
    const sourceOption = screen.getByRole("option", { name: /source-1/ });
    fireEvent.change(evidenceSelect, {
      target: { value: sourceOption.getAttribute("value") },
    });

    const boundState = onChange.mock.lastCall?.[0] as ImportedHandState;
    const boundActions = boundState.streets[0].actions;
    const boundAction = boundActions[boundActions.length - 1];
    expect(boundAction?.evidence).toEqual([
      expect.objectContaining({ raw_source_id: "source-1", line_start: 4 }),
    ]);
    expect(boundAction?.origin.evidence).toEqual(boundAction?.evidence);
  });

  it("binds newly added showdown and award rows to retained source locators", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={recordedState()}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Add showdown" }));
    let reviewedState = onChange.mock.lastCall?.[0] as ImportedHandState;
    rerender(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={reviewedState}
        onChange={onChange}
      />,
    );
    const sourceOption = screen.getByRole("option", { name: /source-1/ });
    fireEvent.change(
      screen.getByRole("combobox", { name: "Bind retained source evidence" }),
      { target: { value: sourceOption.getAttribute("value") } },
    );

    reviewedState = onChange.mock.lastCall?.[0] as ImportedHandState;
    rerender(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={reviewedState}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Add award" }));
    reviewedState = onChange.mock.lastCall?.[0] as ImportedHandState;
    rerender(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={reviewedState}
        onChange={onChange}
      />,
    );
    fireEvent.change(
      screen.getByRole("combobox", { name: "Bind retained source evidence" }),
      { target: { value: sourceOption.getAttribute("value") } },
    );

    const boundState = onChange.mock.lastCall?.[0] as ImportedHandState;
    expect(boundState.results?.showdown[0].evidence).toEqual([
      expect.objectContaining({ raw_source_id: "source-1" }),
    ]);
    expect(boundState.results?.awards[0].evidence).toEqual([
      expect.objectContaining({ raw_source_id: "source-1" }),
    ]);
  });

  it("confirms an unresolved origin only with its retained evidence and review reference", () => {
    const onChange = vi.fn();
    const state = recordedState();
    state.streets[0].actions[0].origin = {
      ...state.streets[0].actions[0].origin,
      kind: "unknown",
      basis: "unresolved",
      confidence: null,
      semantics_revision: null,
    };
    render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={state}
        onChange={onChange}
      />,
    );

    fireEvent.change(
      screen.getByRole("textbox", { name: "Origin confirmation reference" }),
      { target: { value: "review-action-1" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm player-selected origin" }),
    );

    const confirmedState = onChange.mock.lastCall?.[0] as ImportedHandState;
    expect(confirmedState.streets[0].actions[0].origin).toMatchObject({
      kind: "player_selected",
      basis: "user_confirmed",
      review_reference: "review-action-1",
      evidence: [expect.objectContaining({ raw_source_id: "source-1" })],
    });
  });

  it("keeps origin classification compatible with an action-type correction", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={recordedState()}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Action type" }), {
      target: { value: "fold" },
    });
    let correctedState = onChange.mock.lastCall?.[0] as ImportedHandState;
    expect(correctedState.streets[0].actions[0].origin).toMatchObject({
      kind: "unknown",
      basis: "unresolved",
    });

    rerender(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={correctedState}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByRole("combobox", { name: "Action type" }), {
      target: { value: "post_big_blind" },
    });
    correctedState = onChange.mock.lastCall?.[0] as ImportedHandState;
    expect(correctedState.streets[0].actions[0].origin).toMatchObject({
      kind: "forced_system",
      basis: "explicit_marker",
    });
  });
});
