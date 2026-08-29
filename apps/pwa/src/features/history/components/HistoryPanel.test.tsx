import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HistoryPanel, type HistoryPanelProps } from "./HistoryPanel";
import type { HistoryItem } from "../lib/historyPresentation";
import type { CanonicalState } from "../../../shared/types/poker";
import type { JobRecord } from "../../../shared/types/jobs";

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-08-13T12:00:00Z"));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function canonicalState(): CanonicalState {
  return {
    hero_cards: [
      { rank: "A", suit: "clubs" },
      { rank: "J", suit: "hearts" },
    ],
    board_cards: [],
    pot_size: 3,
    current_bet: 0,
    hero_stack: 97,
    effective_stack: 97,
    players_in_hand: 2,
    hero_position: "button",
    preflop_opener_position: null,
    preflop_open_size: null,
    street: "flop",
    facing_action: null,
    action_context: null,
    user_approved: true,
  };
}

function jobRecord(overrides: Partial<JobRecord> = {}): JobRecord {
  return {
    id: "job-1",
    status: "approved",
    original_filename: "table.png",
    title: "Button versus blind",
    image_filename: "job-1.png",
    parser_provider: "ocr_cv",
    parser_result: null,
    approved_state: canonicalState(),
    benchmark_included: false,
    archived_at: "2026-08-13T11:55:00Z",
    error: null,
    created_at: "2026-08-13T10:00:00Z",
    updated_at: "2026-08-13T11:55:00Z",
    ...overrides,
  };
}

function historyItem(job = jobRecord()): HistoryItem {
  return {
    id: job.id,
    job,
    savedAt: job.archived_at ?? job.updated_at,
  };
}

function panelProps(
  overrides: Partial<HistoryPanelProps> = {},
): HistoryPanelProps {
  return {
    busy: false,
    items: [historyItem()],
    loading: false,
    onClearSearch: vi.fn(),
    onLoadOlder: vi.fn(),
    onManageJob: vi.fn(),
    onOpenItem: vi.fn(),
    onOpenSearch: vi.fn(),
    onRefresh: vi.fn(),
    onSearch: vi.fn(),
    onSearchInputChange: vi.fn(),
    searchActive: false,
    searchInput: "",
    searchOpen: false,
    searchTotal: 0,
    total: 3,
    ...overrides,
  };
}

describe("HistoryPanel", () => {
  it("renders saved hand context and delegates rail actions", async () => {
    const item = historyItem();
    const props = panelProps({ items: [item] });
    render(<HistoryPanel {...props} />);

    expect(screen.getByText("History · reopen")).toBeInTheDocument();
    expect(screen.getByText("Auto-saved")).toBeInTheDocument();
    expect(screen.getByText("A♣")).toBeInTheDocument();
    expect(screen.getByText("J♥")).toHaveClass("red-card");
    expect(screen.getByText("Button versus blind")).toHaveClass(
      "history-title",
    );
    expect(screen.getByText("5 min ago · approved")).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("Load 2 older")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );
    await userEvent.click(
      screen.getByRole("button", {
        name: "Manage history item 1: table.png",
      }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Load older history" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Refresh saved history" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Search saved history" }),
    );

    expect(props.onOpenItem).toHaveBeenCalledWith(item);
    expect(props.onManageJob).toHaveBeenCalledWith(item.job);
    expect(props.onLoadOlder).toHaveBeenCalledOnce();
    expect(props.onRefresh).toHaveBeenCalledOnce();
    expect(props.onOpenSearch).toHaveBeenCalledOnce();
  });

  it("delegates controlled search input, submission and closing", async () => {
    const props = panelProps({
      items: [],
      searchActive: true,
      searchInput: "ace",
      searchOpen: true,
      searchTotal: 1,
      total: 1,
    });
    render(<HistoryPanel {...props} />);

    expect(screen.getByText("History · 1 match")).toBeInTheDocument();
    expect(
      screen.getByText("No saved hands match this search."),
    ).toBeInTheDocument();
    await userEvent.type(
      screen.getByLabelText("History search query"),
      " king",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Run history search" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Close history search" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Refresh history search" }),
    );

    expect(props.onSearchInputChange).toHaveBeenCalled();
    expect(props.onSearch).toHaveBeenCalledOnce();
    expect(props.onClearSearch).toHaveBeenCalledOnce();
    expect(props.onRefresh).toHaveBeenCalledOnce();
  });

  it("shows status and missing-card fallbacks for an unfinished hand", () => {
    render(
      <HistoryPanel
        {...panelProps({
          items: [
            historyItem(
              jobRecord({
                approved_state: null,
                archived_at: "2026-08-13T10:00:00Z",
                original_filename: "unfinished.png",
                status: "parsed",
                title: null,
              }),
            ),
          ],
          total: 1,
        })}
      />,
    );

    expect(screen.getByText("No cards")).toBeInTheDocument();
    expect(screen.getByText("parsed")).toBeInTheDocument();
    expect(screen.getByText("2 hr ago")).toBeInTheDocument();
    expect(screen.getByText("P")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Load older history" }),
    ).not.toBeInTheDocument();
  });

  it("disables commands while history is loading", () => {
    render(
      <HistoryPanel
        {...panelProps({
          items: [],
          loading: true,
          searchOpen: true,
        })}
      />,
    );

    expect(screen.getByText("Loading saved history...")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Close history search" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Refresh saved history" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Run history search" }),
    ).toBeDisabled();
  });

  it("renders the default empty history message", () => {
    render(<HistoryPanel {...panelProps({ items: [], total: 0 })} />);

    expect(
      screen.getByText("Cleared reviewed hands will appear here."),
    ).toBeInTheDocument();
  });

  it("renders no input-context badge for saved hands", () => {
    render(<HistoryPanel {...panelProps()} />);

    expect(
      screen.queryByLabelText("Administrative OCR test input"),
    ).not.toBeInTheDocument();
  });
});
