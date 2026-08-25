import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  TrainingPerformanceTrend,
  trainingPerformanceTrendAccessibleLabel,
} from "./TrainingPerformanceTrend";
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

describe("TrainingPerformanceTrend", () => {
  it("renders signed deltas with an equivalent accessible label", () => {
    render(<TrainingPerformanceTrend trend={TREND} />);

    const trend = screen.getByLabelText(
      trainingPerformanceTrendAccessibleLabel(TREND),
    );
    expect(trend).toHaveTextContent("Last 2 hands vs previous 2");
    expect(screen.getByText("+25 pts")).toHaveClass("improving");
    expect(screen.getByText("-50 pts")).toHaveClass("declining");
    expect(screen.getByText("-0.3 BB")).toHaveClass("improving");
  });

  it("can hide duplicated trend content from assistive technology", () => {
    const { container } = render(
      <TrainingPerformanceTrend hiddenFromAssistiveTechnology trend={TREND} />,
    );

    expect(container.querySelector(".training-summary-trend")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(
      screen.queryByLabelText(/action accuracy change/i),
    ).not.toBeInTheDocument();
  });
});
