import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { StateForm } from "../../../domains/poker/model/pokerStateForm";
import { HandStateEditor, type HandStateEditorProps } from "./HandStateEditor";

afterEach(cleanup);

function stateForm(overrides: Partial<StateForm> = {}): StateForm {
  return {
    hero_cards: "Ac Jh",
    board_cards: "4s Th Qd 9h",
    pot_size: "12.5",
    current_bet: "0",
    hero_stack: "92",
    opponent_stack: "90",
    effective_stack: "90",
    players_in_hand: "2",
    opponents_at_current_bet: "",
    opponent_wager: "",
    opponent_commitment_total: "",
    hero_position: "button",
    opponent_position: "cutoff",
    preflop_opener_position: "",
    preflop_open_size: "",
    preflop_action_history: [],
    street: "turn",
    facing_action: "",
    postflop_action_history: [],
    completed_postflop_actions: [],
    action_context: "Checked to hero",
    ...overrides,
  };
}

function editorProps(
  overrides: Partial<HandStateEditorProps> = {},
): HandStateEditorProps {
  return {
    completedPostflopActionCounts: { flop: 0, turn: 0 },
    completedPostflopActionsAtLimit: false,
    confidences: {},
    disabled: false,
    form: stateForm(),
    onAddCompletedPostflopAction: vi.fn(),
    onAddPostflopAction: vi.fn(),
    onAddPreflopAction: vi.fn(),
    onChange: vi.fn(),
    onRemoveCompletedPostflopAction: vi.fn(),
    onRemovePostflopAction: vi.fn(),
    onRemovePreflopAction: vi.fn(),
    onUpdateCompletedPostflopAction: vi.fn(),
    onUpdatePostflopAction: vi.fn(),
    onUpdatePreflopAction: vi.fn(),
    warnings: ["Pot needs manual review"],
    ...overrides,
  };
}

describe("HandStateEditor", () => {
  it("composes detected fields with completed-street action editing", async () => {
    const props = editorProps();
    render(<HandStateEditor {...props} />);

    expect(screen.getByText("Pot needs manual review")).toBeInTheDocument();
    expect(
      screen.getByText("Completed streets (total BB)"),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Add action" }));
    expect(props.onAddCompletedPostflopAction).toHaveBeenCalledOnce();
  });
});
