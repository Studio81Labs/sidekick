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
    canRecommend: true,
    children: <div>Decision slot</div>,
    editor: {} as HandStateEditorProps,
    job: {
      id: "job-1",
      status: "parsed",
      original_filename: "table.png",
      image_filename: "job-1.png",
      parser_provider: "mock",
      recommendation_provider: "mock",
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
      training_decision: null,
      recommendation: null,
      recommendation_pending: false,
      training_reviewed_at: null,
      training_review_note: null,
      benchmark_included: false,
      archived_at: null,
      error: null,
      created_at: "2026-08-14T00:00:00Z",
      updated_at: "2026-08-14T00:00:00Z",
    } satisfies JobRecord,
    onApprove: vi.fn(),
    onRecommend: vi.fn(),
    onResetToParser: vi.fn(),
    ...overrides,
  };
}

describe("HandReviewPanel", () => {
  it("connects the review actions to the page coordinator", async () => {
    const props = panelProps();
    render(<HandReviewPanel {...props} />);

    expect(screen.getByText("Hand state editor")).toBeInTheDocument();
    expect(screen.getByText("Decision slot")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Approve state" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Reset to parser" }),
    );

    expect(props.onApprove).toHaveBeenCalledOnce();
    expect(props.onRecommend).toHaveBeenCalledOnce();
    expect(props.onResetToParser).toHaveBeenCalledOnce();
  });
});
