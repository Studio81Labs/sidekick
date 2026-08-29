import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ScreenshotQueuePanel,
  type ScreenshotQueuePanelProps,
} from "./ScreenshotQueuePanel";
import type { JobRecord } from "../../../shared/types/jobs";
import type { ParserResult } from "../../../shared/types/poker";

afterEach(cleanup);

function jobRecord(overrides: Partial<JobRecord> = {}): JobRecord {
  return {
    id: "job-1",
    status: "parsed",
    original_filename: "table.png",
    image_filename: "job-1.png",
    parser_provider: "ocr_cv",
    parser_result: null,
    approved_state: null,
    benchmark_included: false,
    archived_at: null,
    error: null,
    created_at: "2026-08-13T10:00:00Z",
    updated_at: "2026-08-13T10:00:00Z",
    ...overrides,
  };
}

function panelProps(
  overrides: Partial<ScreenshotQueuePanelProps> = {},
): ScreenshotQueuePanelProps {
  return {
    activeJobId: null,
    attentionByJobId: {},
    busy: false,
    clearDisabled: false,
    count: 1,
    jobs: [jobRecord()],
    onClearReviewed: vi.fn(),
    onManageJob: vi.fn(),
    onOpenJob: vi.fn(),
    pendingFilesLabel: null,
    ...overrides,
  };
}

function parserResult(overrides: Partial<ParserResult> = {}): ParserResult {
  return {
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
      street: "turn",
      facing_action: null,
      action_context: null,
    },
    confidences: {},
    warnings: [],
    raw: {},
    ...overrides,
  };
}

describe("ScreenshotQueuePanel", () => {
  it("renders queue details and delegates queue actions", async () => {
    const activeJob = jobRecord({ title: "  River decision  " });
    const attentionJob = jobRecord({
      id: "job-2",
      original_filename: "turn.png",
      status: "error",
      error: '{"missing_fields":["opponent_wager"]}',
    });
    const props = panelProps({
      activeJobId: activeJob.id,
      attentionByJobId: { [attentionJob.id]: "Check the opponent wager" },
      count: 2,
      jobs: [activeJob, attentionJob],
    });
    render(<ScreenshotQueuePanel {...props} />);

    expect(screen.getByText("2 screenshots")).toHaveClass("sr-only");
    expect(screen.getByText("River decision")).toBeInTheDocument();
    expect(screen.getByText("Check the opponent wager")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open screenshot 1: table.png" })
        .parentElement,
    ).toHaveClass("active");
    expect(
      screen.getByRole("button", { name: "Open screenshot 2: turn.png" })
        .parentElement,
    ).toHaveClass("attention");

    await userEvent.click(
      screen.getByRole("button", { name: "Open screenshot 1: table.png" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Manage screenshot 2: turn.png" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Clear reviewed" }),
    );

    expect(props.onOpenJob).toHaveBeenCalledWith(activeJob);
    expect(props.onManageJob).toHaveBeenCalledWith(attentionJob);
    expect(props.onClearReviewed).toHaveBeenCalledOnce();
  });

  it("uses human-readable error, warning and processing details", () => {
    render(
      <ScreenshotQueuePanel
        {...panelProps({
          count: 4,
          jobs: [
            jobRecord({ status: "created" }),
            jobRecord({
              id: "job-3",
              original_filename: "error.png",
              status: "error",
              error: '{"missing_fields":["opponent_wager"]}',
            }),
            jobRecord({
              id: "job-4",
              original_filename: "warning.png",
              parser_result: parserResult({ warnings: ["Low confidence"] }),
            }),
            jobRecord({
              id: "job-5",
              original_filename: "turn.png",
              parser_result: parserResult(),
            }),
          ],
        })}
      />,
    );

    expect(screen.getByText("Parsing screenshot")).toBeInTheDocument();
    expect(screen.getByText("Review warnings")).toBeInTheDocument();
    expect(screen.getByText("turn")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Complete the required table details before approving the state: Opponent wager total. Edit the listed fields, then approve again.",
      ),
    ).toBeInTheDocument();
  });

  it("shows pending uploads when the queue is empty", () => {
    render(
      <ScreenshotQueuePanel
        {...panelProps({
          clearDisabled: true,
          count: 2,
          jobs: [],
          pendingFilesLabel: "2 screenshots selected",
        })}
      />,
    );

    expect(screen.getByText("2 screenshots selected")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Clear reviewed" }),
    ).toBeDisabled();
  });

  it("prevents opening another screenshot while the workspace is busy", () => {
    render(<ScreenshotQueuePanel {...panelProps({ busy: true })} />);

    expect(
      screen.getByRole("button", { name: "Open screenshot 1: table.png" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Manage screenshot 1: table.png" }),
    ).toBeEnabled();
  });

  it("renders no input-context badge for queued frames", () => {
    render(<ScreenshotQueuePanel {...panelProps()} />);

    expect(
      screen.queryByLabelText("Administrative OCR test input"),
    ).not.toBeInTheDocument();
  });
});
