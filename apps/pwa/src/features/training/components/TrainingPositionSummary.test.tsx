import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TrainingPositionSummary } from "./TrainingPositionSummary";
import type { TrainingPositionSummary as TrainingPositionSummaryModel } from "../../../shared/types/training";

afterEach(cleanup);

const SUMMARIES: TrainingPositionSummaryModel[] = [
  {
    action_accuracy: 0.5,
    action_matches: 1,
    average_ev_loss_bb: 0.4,
    ev_compared_hands: 2,
    exact_accuracy: 0,
    exact_matches: 0,
    needs_review_hands: 2,
    position: "BTN",
    reviewed_hands: 2,
    trend: {
      action_accuracy_delta: 0.5,
      average_ev_loss_delta_bb: -0.2,
      exact_accuracy_delta: 0,
      previous_action_accuracy: 0,
      previous_average_ev_loss_bb: 0.6,
      previous_ev_compared_hands: 1,
      previous_exact_accuracy: 0,
      recent_action_accuracy: 0.5,
      recent_average_ev_loss_bb: 0.4,
      recent_ev_compared_hands: 1,
      recent_exact_accuracy: 0,
      window_hands: 1,
    },
  },
  {
    action_accuracy: 1,
    action_matches: 1,
    average_ev_loss_bb: null,
    ev_compared_hands: 0,
    exact_accuracy: 1,
    exact_matches: 1,
    needs_review_hands: 0,
    position: "BB",
    reviewed_hands: 1,
  },
];

describe("TrainingPositionSummary", () => {
  it("renders position performance and sends every drilldown and review filter", () => {
    const onFilterChange = vi.fn();
    const onReview = vi.fn();
    render(
      <TrainingPositionSummary
        controlsDisabled={false}
        focus={{
          filter: { kind: "position", label: "BTN", position: "BTN" },
          label: "BTN",
          reason: "Highest average EV loss: 0.4 BB",
        }}
        onFilterChange={onFilterChange}
        onReview={onReview}
        progress={{
          position_summaries: SUMMARIES,
          unpositioned_hands: 3,
          unpositioned_needs_review_hands: 1,
        }}
        showFocus
      />,
    );

    const section = screen.getByRole("region", { name: "By position" });
    expect(within(section).getByText("50%")).toBeInTheDocument();
    expect(within(section).getByText("0.4 BB")).toBeInTheDocument();
    expect(within(section).getAllByText("—")).toHaveLength(2);
    expect(section.querySelector(".training-summary-trend")).toHaveAttribute(
      "aria-hidden",
      "true",
    );

    fireEvent.click(
      within(section).getByRole("button", {
        name: "Focus BTN position reviews: Highest average EV loss: 0.4 BB",
      }),
    );
    expect(onReview).toHaveBeenLastCalledWith({
      kind: "position",
      label: "BTN",
      position: "BTN",
    });

    fireEvent.click(
      within(section).getByRole("button", {
        name: /Show 2 hands recorded at BTN\. Last 1 hand vs previous 1/i,
      }),
    );
    expect(onFilterChange).toHaveBeenLastCalledWith({
      kind: "position",
      label: "BTN",
      position: "BTN",
    });

    fireEvent.click(
      within(section).getByRole("button", {
        name: "Review BTN position differences (2)",
      }),
    );
    expect(onReview).toHaveBeenLastCalledWith({
      kind: "position",
      label: "BTN",
      position: "BTN",
    });

    fireEvent.click(
      within(section).getByRole("button", {
        name: "Show 3 unpositioned hands",
      }),
    );
    expect(onFilterChange).toHaveBeenLastCalledWith({
      kind: "unpositioned",
      label: "Unpositioned",
    });

    fireEvent.click(
      within(section).getByRole("button", {
        name: "Review unpositioned differences (1)",
      }),
    );
    expect(onReview).toHaveBeenLastCalledWith({
      kind: "unpositioned",
      label: "Unpositioned",
    });
  });

  it("keeps unpositioned controls visible outside recent view and disables controls", () => {
    render(
      <TrainingPositionSummary
        controlsDisabled
        focus={{
          filter: { kind: "unpositioned", label: "Unpositioned" },
          label: "Unpositioned",
          reason: "One hand needs review",
        }}
        onFilterChange={vi.fn()}
        onReview={vi.fn()}
        progress={{
          position_summaries: [],
          unpositioned_hands: 1,
          unpositioned_needs_review_hands: 1,
        }}
        showFocus={false}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /Focus unpositioned reviews/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Show 1 unpositioned hand" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", {
        name: "Review unpositioned differences (1)",
      }),
    ).toBeDisabled();
  });

  it("renders nothing without positioned or unpositioned hands", () => {
    const { container } = render(
      <TrainingPositionSummary
        controlsDisabled={false}
        focus={null}
        onFilterChange={vi.fn()}
        onReview={vi.fn()}
        progress={{ position_summaries: [], unpositioned_hands: 0 }}
        showFocus
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
