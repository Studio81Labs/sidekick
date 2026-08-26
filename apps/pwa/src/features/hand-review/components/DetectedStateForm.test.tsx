import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DetectedStateForm,
  type DetectedStateFormProps,
} from "./DetectedStateForm";
import type { StateForm } from "../../../domains/poker/model/pokerStateForm";

afterEach(cleanup);

function stateForm(overrides: Partial<StateForm> = {}): StateForm {
  return {
    hero_cards: "Ac Jh",
    board_cards: "4s Th Qd",
    pot_size: "5.5",
    current_bet: "0",
    hero_stack: "94.5",
    opponent_stack: "",
    effective_stack: "94.5",
    players_in_hand: "2",
    opponents_at_current_bet: "",
    opponent_wager: "",
    opponent_commitment_total: "",
    hero_position: "cutoff",
    opponent_position: "button",
    preflop_opener_position: "",
    preflop_open_size: "",
    preflop_action_history: [],
    street: "flop",
    facing_action: "",
    postflop_action_history: [],
    completed_postflop_actions: [],
    action_context: "Checked to hero",
    ...overrides,
  };
}

function formProps(
  overrides: Partial<DetectedStateFormProps> = {},
): DetectedStateFormProps {
  return {
    confidences: {
      hero_cards: 0.91,
      board_cards: 0.82,
      street: 0.96,
      pot_size: 0.76,
    },
    disabled: false,
    form: stateForm(),
    onChange: vi.fn(),
    warnings: [],
    ...overrides,
  };
}

describe("DetectedStateForm", () => {
  it("renders core detected fields and delegates scalar edits", async () => {
    const props = formProps();
    render(<DetectedStateForm {...props} />);

    expect(
      screen.getByRole("textbox", { name: /^Hero cards\s*91%$/ }),
    ).toHaveValue("Ac Jh");
    expect(
      screen.getByRole("combobox", { name: /^Street\s*96%$/ }),
    ).toHaveValue("flop");
    expect(
      screen.getByRole("textbox", { name: /^Opponent position/ }),
    ).toHaveValue("button");
    expect(
      screen.queryByRole("textbox", { name: /^Opponent wager total/ }),
    ).not.toBeInTheDocument();

    await userEvent.clear(
      screen.getByRole("textbox", { name: /^Hero cards\s*91%$/ }),
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: /^Hero cards\s*91%$/ }),
      "As Ks",
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: /^Street\s*96%$/ }),
      "turn",
    );

    expect(props.onChange).toHaveBeenCalledWith("hero_cards", "");
    expect(props.onChange).toHaveBeenCalledWith("street", "turn");
  });

  it("shows multiway wager fields and parser warnings", () => {
    render(
      <DetectedStateForm
        {...formProps({
          form: stateForm({
            current_bet: "2.5",
            facing_action: "raise",
            players_in_hand: "4",
            street: "turn",
          }),
          warnings: ["Pot needs review", "Position was not detected"],
        })}
      />,
    );

    expect(screen.getByText("Pot needs review")).toBeInTheDocument();
    expect(screen.getByText("Position was not detected")).toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: /^Opponents at wager\s*manual$/ }),
    ).toHaveAttribute("max", "3");
    expect(
      screen.getByRole("textbox", { name: /^Opponent wager total/ }),
    ).toHaveAttribute("min", "2.5");
    expect(
      screen.getByRole("textbox", {
        name: /^Opponent commitments total\s*manual$/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: /^Opponent stack\s*manual$/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /^Opponent position/ }),
    ).not.toBeInTheDocument();
  });

  it("shows preflop commitments without a wager", () => {
    render(
      <DetectedStateForm
        {...formProps({ form: stateForm({ street: "preflop" }) })}
      />,
    );

    expect(
      screen.getByRole("textbox", {
        name: /^Opponent commitments total\s*manual$/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /^Opponent position/ }),
    ).not.toBeInTheDocument();
  });

  it("renders action editors in the field grid and disables controls", () => {
    render(
      <DetectedStateForm {...formProps({ disabled: true })}>
        <div data-testid="action-editors">Action editors</div>
      </DetectedStateForm>,
    );

    const child = screen.getByTestId("action-editors");
    expect(child.parentElement).toHaveClass("field-grid");
    expect(child.nextElementSibling).toContainElement(
      screen.getByRole("textbox", { name: /^Action context/ }),
    );
    expect(
      screen.getByRole("textbox", { name: /^Hero cards\s*91%$/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("textbox", { name: /^Action context/ }),
    ).toBeDisabled();
  });
});
