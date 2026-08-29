import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { JobRecord } from "../../../shared/types/jobs";
import { HandReviewPanel, type HandReviewPanelProps } from "./HandReviewPanel";
import type { HandStateEditorProps } from "./HandStateEditor";

vi.mock("./HandStateEditor", () => ({
  HandStateEditor: () => <div>Hand state editor</div>,
}));

afterEach(cleanup);

function panelProps(
  overrides: Partial<HandReviewPanelProps> = {},
): HandReviewPanelProps {
  return {
    busy: false,
    canApprove: true,
    editor: {} as HandStateEditorProps,
    job: {
      id: "job-1",
      status: "parsed",
      original_filename: "table.png",
      image_filename: "job-1.png",
      parser_provider: "mock",
      parser_result: {
        state: {
          hero_cards: [],
          board_cards: [],
          pot_size: null,
          current_bet: null,
          hero_stack: null,
          effective_stack: null,
          players_in_hand: null,
          hero_position: null,
          preflop_opener_position: null,
          preflop_open_size: null,
          street: null,
          facing_action: null,
          action_context: null,
        },
        confidences: {},
        warnings: [],
        raw: {},
      },
      approved_state: null,
      benchmark_included: false,
      archived_at: null,
      error: null,
      created_at: "2026-08-14T00:00:00Z",
      updated_at: "2026-08-14T00:00:00Z",
    } satisfies JobRecord,
    onApprove: vi.fn(),
    onResetToParser: vi.fn(),
    ...overrides,
  };
}

describe("HandReviewPanel", () => {
  it("connects the review actions to the page coordinator", async () => {
    const props = panelProps();
    render(<HandReviewPanel {...props} />);

    expect(screen.getByText("Hand state editor")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Approve state" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Reset to parser" }),
    );

    expect(props.onApprove).toHaveBeenCalledOnce();
    expect(props.onResetToParser).toHaveBeenCalledOnce();
  });

  it("shows the job status and offers no learning actions", () => {
    render(
      <HandReviewPanel
        {...panelProps({
          job: { ...panelProps().job!, status: "approved" },
        })}
      />,
    );

    expect(screen.getByText("approved")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Request recommendation" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Administrative OCR test input"),
    ).not.toBeInTheDocument();
  });
});
