import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TrainingStreetSummary } from "./TrainingStreetSummary";
import type { TrainingStreetSummary as TrainingStreetSummaryModel } from "../../../shared/types/training";

afterEach(cleanup);

const SUMMARIES: TrainingStreetSummaryModel[] = [
  {
    action_accuracy: 0.5,
    action_matches: 1,
    average_ev_loss_bb: 0.7,
    ev_compared_hands: 2,
    exact_accuracy: 0,
    exact_matches: 0,
    reviewed_hands: 2,
    street: "flop",
    trend: {
      action_accuracy_delta: 0.5,
      average_ev_loss_delta_bb: -0.2,
      exact_accuracy_delta: 0,
      previous_action_accuracy: 0,
      previous_average_ev_loss_bb: 0.9,
      previous_ev_compared_hands: 1,
      previous_exact_accuracy: 0,
      recent_action_accuracy: 0.5,
      recent_average_ev_loss_bb: 0.7,
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
    reviewed_hands: 1,
    street: "turn",
  },
];

describe("TrainingStreetSummary", () => {
  it("renders street performance and sends focus, drilldown, and review actions", () => {
    const onFilterChange = vi.fn();
    const onReview = vi.fn();
    render(
      <TrainingStreetSummary
        controlsDisabled={false}
        focus={{ reason: "Highest average EV loss: 0.7 BB", street: "flop" }}
        onFilterChange={onFilterChange}
        onReview={onReview}
        reviewCounts={{ flop: 2 }}
        showFocus
        summaries={SUMMARIES}
      />,
    );

    const section = screen.getByRole("region", { name: "By street" });
    expect(within(section).getByText("50%")).toBeInTheDocument();
    expect(within(section).getByText("0.7 BB")).toBeInTheDocument();
    expect(within(section).getAllByText("—")).toHaveLength(2);
    expect(
      within(section).getByLabelText(
        /action accuracy change \+50 percentage points/i,
      ),
    ).toBeInTheDocument();

    fireEvent.click(
      within(section).getByRole("button", {
        name: "Focus flop reviews: Highest average EV loss: 0.7 BB",
      }),
    );
    expect(onReview).toHaveBeenLastCalledWith("flop");

    fireEvent.click(
      within(section).getByRole("button", {
        name: "Show 1 hand played on turn",
      }),
    );
    expect(onFilterChange).toHaveBeenCalledWith({
      label: "Turn",
      street: "turn",
    });

    fireEvent.click(
      within(section).getByRole("button", {
        name: "Review flop street differences (2)",
      }),
    );
    expect(onReview).toHaveBeenLastCalledWith("flop");
  });

  it("hides focus outside recent view and disables all controls", () => {
    render(
      <TrainingStreetSummary
        controlsDisabled
        focus={{ reason: "Pending review", street: "flop" }}
        onFilterChange={vi.fn()}
        onReview={vi.fn()}
        reviewCounts={{ flop: 1 }}
        showFocus={false}
        summaries={SUMMARIES}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /Focus flop reviews/ }),
    ).not.toBeInTheDocument();
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
    }
  });
});
