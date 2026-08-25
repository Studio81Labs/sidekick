import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  TrainingCertaintyCalibration,
  type TrainingCertaintyCalibrationProps,
} from "./TrainingCertaintyCalibration";
import type { TrainingTrend } from "../../../shared/types/training";

afterEach(cleanup);

const TREND: TrainingTrend = {
  action_accuracy_delta: 0.25,
  average_ev_loss_delta_bb: -0.3,
  exact_accuracy_delta: -0.5,
  previous_action_accuracy: 0.5,
  previous_average_ev_loss_bb: 0.5,
  previous_ev_compared_hands: 2,
  previous_exact_accuracy: 1,
  recent_action_accuracy: 0.75,
  recent_average_ev_loss_bb: 0.2,
  recent_ev_compared_hands: 2,
  recent_exact_accuracy: 0.5,
  window_hands: 2,
};

function progress(
  overrides: Partial<TrainingCertaintyCalibrationProps["progress"]> = {},
): TrainingCertaintyCalibrationProps["progress"] {
  return {
    certainty_summaries: [
      {
        action_accuracy: 0.75,
        action_matches: 3,
        average_ev_loss_bb: 0.2,
        certainty: "high",
        ev_compared_hands: 2,
        exact_accuracy: 0.5,
        exact_matches: 2,
        hands: 4,
        needs_review_hands: 1,
        trend: TREND,
      },
    ],
    unrated_hands: 1,
    unrated_needs_review_hands: 1,
    ...overrides,
  };
}

describe("TrainingCertaintyCalibration", () => {
  it("renders calibrated and legacy rows and sends their drill-down actions", () => {
    const onFilterChange = vi.fn();
    const onReview = vi.fn();
    render(
      <TrainingCertaintyCalibration
        certaintyLabel={(certainty) =>
          `${certainty[0].toUpperCase()}${certainty.slice(1)}`
        }
        controlsDisabled={false}
        focus={{
          certainty: "high",
          label: "High",
          reason: "Highest action accuracy gap",
        }}
        onFilterChange={onFilterChange}
        onReview={onReview}
        progress={progress()}
        showFocus
      />,
    );

    const section = screen.getByRole("region", {
      name: "Confidence calibration",
    });
    expect(within(section).getByText("0.2 BB")).toBeInTheDocument();
    expect(
      within(section).getByText("Last 2 hands vs previous 2"),
    ).toBeInTheDocument();

    fireEvent.click(
      within(section).getByRole("button", {
        name: "Focus high certainty reviews: Highest action accuracy gap",
      }),
    );
    expect(onReview).toHaveBeenLastCalledWith("high");

    fireEvent.click(
      within(section).getByRole("button", {
        name: /Show 4 hands rated high certainty/,
      }),
    );
    expect(onFilterChange).toHaveBeenLastCalledWith({
      certainty: "high",
      label: "High",
    });

    fireEvent.click(
      within(section).getByRole("button", {
        name: "Review high certainty differences (1)",
      }),
    );
    expect(onReview).toHaveBeenLastCalledWith("high");

    fireEvent.click(
      within(section).getByRole("button", { name: "Show 1 unrated hand" }),
    );
    expect(onFilterChange).toHaveBeenLastCalledWith({
      certainty: "unrated",
      label: "Unrated",
    });

    fireEvent.click(
      within(section).getByRole("button", {
        name: "Review unrated differences (1)",
      }),
    );
    expect(onReview).toHaveBeenLastCalledWith("unrated");
  });

  it("shows context instead of focus outside the recent view and disables controls", () => {
    render(
      <TrainingCertaintyCalibration
        certaintyLabel={(certainty) => certainty}
        controlsDisabled
        focus={{ certainty: "high", label: "High", reason: "Pending review" }}
        onFilterChange={vi.fn()}
        onReview={vi.fn()}
        progress={progress()}
        showFocus={false}
      />,
    );

    expect(screen.getByText("Self-rated before reveal")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Focus high certainty reviews/ }),
    ).not.toBeInTheDocument();
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
    }
  });

  it("renders nothing without rated or unrated hands", () => {
    const { container } = render(
      <TrainingCertaintyCalibration
        certaintyLabel={(certainty) => certainty}
        controlsDisabled={false}
        focus={null}
        onFilterChange={vi.fn()}
        onReview={vi.fn()}
        progress={progress({ certainty_summaries: [], unrated_hands: 0 })}
        showFocus
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
