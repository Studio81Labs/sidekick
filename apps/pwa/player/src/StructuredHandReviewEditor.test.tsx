import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { StructuredHandReviewEditor } from "./StructuredHandReviewEditor";
import type {
  ImportedHandSourceEvidence,
  ImportedHandState,
} from "./playerApi";

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

function immutableEvidenceOptions(): ImportedHandSourceEvidence[] {
  const action = recordedState().streets[0]?.actions[0];
  return action ? [...action.evidence, ...action.origin.evidence] : [];
}

describe("StructuredHandReviewEditor", () => {
  it("preserves decimal text and explicit nullable/list result values", () => {
    const onChange = vi.fn();
    render(
      <StructuredHandReviewEditor
        disabled={false}
        evidenceOptions={immutableEvidenceOptions()}
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
        evidenceOptions={immutableEvidenceOptions()}
        errors={[]}
        state={state}
        onChange={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("combobox", { name: "Hero cards 1 suit" }),
    ).toHaveValue("spades");
  });

  it("keeps a new player identity editable while it is entered", () => {
    const onChange = vi.fn();
    const state = recordedState();
    state.seats.push({
      seat_number: 3,
      player_id: "",
      display_name: null,
      starting_stack: null,
      participation: "unknown",
      position: null,
    });
    const { rerender } = render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        immutablePlayerIds={["hero", "villain"]}
        state={state}
        onChange={onChange}
      />,
    );

    const playerIdentity = screen.getByRole("textbox", {
      name: "Player identity",
    });
    playerIdentity.focus();
    fireEvent.change(playerIdentity, { target: { value: "N" } });
    const updated = onChange.mock.lastCall?.[0] as ImportedHandState;
    expect(updated.seats[2]?.player_id).toBe("N");

    rerender(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        immutablePlayerIds={["hero", "villain"]}
        state={updated}
        onChange={onChange}
      />,
    );
    const continuedPlayerIdentity = screen.getByRole("textbox", {
      name: "Player identity",
    });
    expect(continuedPlayerIdentity).toHaveFocus();
    fireEvent.change(continuedPlayerIdentity, {
      target: { value: "New Player" },
    });
    expect(
      (onChange.mock.lastCall?.[0] as ImportedHandState).seats[2]?.player_id,
    ).toBe("New Player");
  });

  it("keeps a detected seat row focused while its number is corrected", () => {
    const onChange = vi.fn();
    const state = recordedState();
    state.seats[0].seat_number = 9;
    const { rerender } = render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        immutablePlayerIds={["hero", "villain"]}
        state={state}
        onChange={onChange}
      />,
    );

    const seatNumber = screen.getAllByRole("spinbutton", {
      name: "Seat number",
    })[0];
    seatNumber.focus();
    fireEvent.change(seatNumber, { target: { value: "1" } });
    const updated = onChange.mock.lastCall?.[0] as ImportedHandState;

    rerender(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        immutablePlayerIds={["hero", "villain"]}
        state={updated}
        onChange={onChange}
      />,
    );
    const continuedSeatNumber = screen.getAllByRole("spinbutton", {
      name: "Seat number",
    })[0];
    expect(continuedSeatNumber).toHaveFocus();
    fireEvent.change(continuedSeatNumber, { target: { value: "10" } });
    expect(
      (onChange.mock.lastCall?.[0] as ImportedHandState).seats[0]?.seat_number,
    ).toBe(10);
  });

  it("preserves text whitespace while editing and normalizes it on blur", () => {
    const onChange = vi.fn();
    const state = recordedState();
    const { rerender } = render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={state}
        onChange={onChange}
      />,
    );

    const displayName = screen.getAllByRole("textbox", {
      name: "Display name",
    })[0];
    fireEvent.change(displayName, { target: { value: "Alice Example " } });
    let updated = onChange.mock.lastCall?.[0] as ImportedHandState;
    expect(updated.seats[0]?.display_name).toBe("Alice Example ");

    rerender(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={updated}
        onChange={onChange}
      />,
    );
    fireEvent.blur(screen.getAllByRole("textbox", { name: "Display name" })[0]);
    updated = onChange.mock.lastCall?.[0] as ImportedHandState;
    expect(updated.seats[0]?.display_name).toBe("Alice Example");
  });

  it("keeps an action amount focused while it is entered", () => {
    const onChange = vi.fn();
    const state = recordedState();
    const { rerender } = render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={state}
        onChange={onChange}
      />,
    );

    const amount = screen.getByRole("textbox", { name: "Amount" });
    amount.focus();
    fireEvent.change(amount, { target: { value: "1" } });
    const updated = onChange.mock.lastCall?.[0] as ImportedHandState;

    rerender(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={updated}
        onChange={onChange}
      />,
    );
    const continuedAmount = screen.getByRole("textbox", { name: "Amount" });
    expect(continuedAmount).toHaveFocus();
    fireEvent.change(continuedAmount, { target: { value: "12" } });
    expect(
      (onChange.mock.lastCall?.[0] as ImportedHandState).streets[0]?.actions[0]
        ?.amount,
    ).toBe("12");
  });

  it("clears derived positions when the button seat changes", () => {
    const onChange = vi.fn();
    render(
      <StructuredHandReviewEditor
        disabled={false}
        evidenceOptions={immutableEvidenceOptions()}
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

  it("allows removing only the final street", () => {
    const onChange = vi.fn();
    const state = recordedState();
    state.streets.push(
      { street: "flop", board_cards: [], actions: [] },
      { street: "turn", board_cards: [], actions: [] },
    );
    render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={state}
        onChange={onChange}
      />,
    );

    const removeStreet = screen.getByRole("button", { name: "Remove street" });
    fireEvent.click(removeStreet);

    expect((onChange.mock.lastCall?.[0] as ImportedHandState).streets).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ street: "preflop" }),
        expect.objectContaining({ street: "flop" }),
      ]),
    );
    expect(
      (onChange.mock.lastCall?.[0] as ImportedHandState).streets,
    ).toHaveLength(2);
  });

  it("binds newly added action rows to a retained source locator", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <StructuredHandReviewEditor
        disabled={false}
        evidenceOptions={immutableEvidenceOptions()}
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
        evidenceOptions={immutableEvidenceOptions()}
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
        evidenceOptions={immutableEvidenceOptions()}
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
        evidenceOptions={immutableEvidenceOptions()}
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
        evidenceOptions={immutableEvidenceOptions()}
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
        evidenceOptions={immutableEvidenceOptions()}
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
    const confirmationActionCandidates = [
      structuredClone(state.streets[0].actions),
    ];
    render(
      <StructuredHandReviewEditor
        confirmationActionCandidates={confirmationActionCandidates}
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

  it("keeps a confirmation reference with its action when actions are reordered", () => {
    const onChange = vi.fn();
    const state = recordedState();
    const sourceAction = state.streets[0].actions[0];
    const unknownOrigin = {
      ...sourceAction.origin,
      kind: "unknown" as const,
      basis: "unresolved" as const,
      confidence: null,
      semantics_revision: null,
    };
    state.streets[0].actions = [
      {
        ...sourceAction,
        action_type: "check",
        amount: null,
        total_committed: "0",
        origin: unknownOrigin,
      },
      {
        ...sourceAction,
        sequence: 1,
        actor_id: "villain",
        action_type: "call",
        amount: "1.00",
        total_committed: "1.00",
        origin: structuredClone(unknownOrigin),
        evidence: structuredClone(sourceAction.evidence),
      },
    ];
    const confirmationActionCandidates = [
      structuredClone(state.streets[0].actions),
    ];
    const { rerender } = render(
      <StructuredHandReviewEditor
        confirmationActionCandidates={confirmationActionCandidates}
        disabled={false}
        errors={[]}
        state={state}
        onChange={onChange}
      />,
    );

    fireEvent.change(
      screen.getAllByRole("textbox", {
        name: "Origin confirmation reference",
      })[1],
      { target: { value: "review-villain" } },
    );
    const secondAction = screen.getByText("Action 2").closest("article");
    if (!secondAction) throw new Error("Expected the second action row");
    fireEvent.click(
      within(secondAction).getByRole("button", { name: "Move earlier" }),
    );
    const reordered = onChange.mock.lastCall?.[0] as ImportedHandState;

    rerender(
      <StructuredHandReviewEditor
        confirmationActionCandidates={confirmationActionCandidates}
        disabled={false}
        errors={[]}
        state={reordered}
        onChange={onChange}
      />,
    );
    expect(screen.getAllByRole("combobox", { name: "Actor" })[0]).toHaveValue(
      "villain",
    );
    expect(
      screen.getAllByRole("textbox", {
        name: "Origin confirmation reference",
      })[0],
    ).toHaveValue("review-villain");

    fireEvent.click(
      screen.getAllByRole("button", {
        name: "Confirm player-selected origin",
      })[0],
    );
    expect(
      (onChange.mock.lastCall?.[0] as ImportedHandState).streets[0]?.actions[0],
    ).toMatchObject({
      actor_id: "villain",
      origin: {
        kind: "player_selected",
        basis: "user_confirmed",
        review_reference: "review-villain",
      },
    });
  });

  it("does not offer confirmation when the matching detected action is on another street", () => {
    const onChange = vi.fn();
    const state = recordedState();
    const unresolved = {
      ...state.streets[0].actions[0],
      action_type: "check" as const,
      amount: null,
      total_committed: "0",
      origin: {
        ...state.streets[0].actions[0].origin,
        kind: "unknown" as const,
        basis: "unresolved" as const,
        confidence: null,
        semantics_revision: null,
      },
    };
    state.streets[0].actions[0] = unresolved;
    state.streets.push({
      ...structuredClone(state.streets[0]),
      street: "flop",
      board_cards: [],
      actions: [
        {
          ...structuredClone(unresolved),
          origin: {
            ...structuredClone(unresolved.origin),
            kind: "forced_system",
            basis: "explicit_marker",
          },
        },
      ],
    });
    render(
      <StructuredHandReviewEditor
        confirmationActionCandidates={[[], [structuredClone(unresolved)]]}
        disabled={false}
        errors={[]}
        state={state}
        onChange={onChange}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Confirm player-selected origin" }),
    ).toBeNull();
  });

  it("never promotes an editable draft locator into a correction option", () => {
    const onChange = vi.fn();
    const state = recordedState();
    const draftOnlyEvidence = {
      raw_source_id: "draft-only-source",
      line_start: 99,
      line_end: 99,
      marker: "draft-only-marker",
    };
    state.streets[0].actions[0].evidence = [draftOnlyEvidence];
    state.streets[0].actions[0].origin.evidence = [draftOnlyEvidence];
    const { rerender } = render(
      <StructuredHandReviewEditor
        disabled={false}
        evidenceOptions={immutableEvidenceOptions()}
        errors={[]}
        state={state}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Add action" }));
    rerender(
      <StructuredHandReviewEditor
        disabled={false}
        evidenceOptions={immutableEvidenceOptions()}
        errors={[]}
        state={onChange.mock.lastCall?.[0] as ImportedHandState}
        onChange={onChange}
      />,
    );

    expect(
      screen.getByRole("option", { name: /source-1/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /draft-only-source/ }),
    ).toBeNull();
  });

  it("keeps a user-selected source line unresolved even when a draft resembles a detected action", () => {
    const onChange = vi.fn();
    const state = recordedState();
    const sourceLineEvidence = {
      raw_source_id: "source-1",
      line_start: 4,
      line_end: 4,
      marker: "review-source-line/v1",
    };
    state.streets[0].actions[0].origin = {
      ...state.streets[0].actions[0].origin,
      kind: "unknown",
      basis: "unresolved",
      confidence: null,
      semantics_revision: null,
      evidence: [sourceLineEvidence],
    };
    state.streets[0].actions[0].evidence = [sourceLineEvidence];
    render(
      <StructuredHandReviewEditor
        confirmationActionCandidates={[
          structuredClone(state.streets[0].actions),
        ]}
        disabled={false}
        errors={[]}
        state={state}
        onChange={onChange}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Confirm player-selected origin" }),
    ).toBeNull();
  });

  it("lets a reviewer return a non-forced automatic classification to unresolved", () => {
    const onChange = vi.fn();
    const state = recordedState();
    state.streets[0].actions[0] = {
      ...state.streets[0].actions[0],
      action_type: "check",
      origin: {
        ...state.streets[0].actions[0].origin,
        kind: "client_automatic",
        basis: "explicit_marker",
        confidence: "1.00",
        automatic_reason: "timeout",
        semantics_revision: "pokerstars-timeout/v1",
      },
    };
    render(
      <StructuredHandReviewEditor
        disabled={false}
        errors={[]}
        state={state}
        onChange={onChange}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Keep origin unresolved" }),
    );
    expect(
      (onChange.mock.lastCall?.[0] as ImportedHandState).streets[0].actions[0]
        .origin,
    ).toMatchObject({
      kind: "unknown",
      basis: "unresolved",
      confidence: null,
      automatic_reason: null,
      semantics_revision: null,
      review_reference: null,
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
