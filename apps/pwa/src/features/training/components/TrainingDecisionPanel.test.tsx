import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  TrainingDecisionPanel,
  type TrainingDecisionPanelProps,
} from "./TrainingDecisionPanel";

afterEach(cleanup);

function panelProps(
  overrides: Partial<TrainingDecisionPanelProps> = {},
): TrainingDecisionPanelProps {
  return {
    action: "raise",
    busy: false,
    certainty: "medium",
    decision: null,
    onActionChange: vi.fn(),
    onCertaintyChange: vi.fn(),
    onSave: vi.fn(),
    onSizingChange: vi.fn(),
    sizing: "7.5",
    ...overrides,
  };
}

describe("TrainingDecisionPanel", () => {
  it("edits and locks a sized decision", async () => {
    const props = panelProps();
    render(<TrainingDecisionPanel {...props} />);

    await userEvent.click(screen.getByRole("button", { name: "call" }));
    await userEvent.clear(
      screen.getByRole("textbox", { name: "Decision sizing in BB" }),
    );
    await userEvent.type(
      screen.getByRole("textbox", { name: "Decision sizing in BB" }),
      "9",
    );
    await userEvent.click(screen.getByRole("button", { name: "Lock answer" }));

    expect(props.onActionChange).toHaveBeenCalledWith("call");
    expect(props.onSizingChange).toHaveBeenCalled();
    expect(props.onSave).toHaveBeenCalledOnce();
  });
});
