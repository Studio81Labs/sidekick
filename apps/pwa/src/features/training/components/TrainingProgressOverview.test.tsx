import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TrainingProgressOverview } from "./TrainingProgressOverview";
import type { TrainingProgressOverviewProps } from "./TrainingProgressOverview";

afterEach(cleanup);

function overviewProgress(
  overrides: Partial<TrainingProgressOverviewProps["progress"]> = {},
): TrainingProgressOverviewProps["progress"] {
  return {
    action_accuracy: 0.75,
    average_ev_loss_bb: 0.0432,
    ev_compared_hands: 4,
    exact_accuracy: 0.5,
    needs_review_hands: 2,
    reviewed_hands: 8,
    trend: {
      action_accuracy_delta: 0.25,
      average_ev_loss_delta_bb: -1.2,
      exact_accuracy_delta: -0.5,
      previous_action_accuracy: 0.5,
      previous_average_ev_loss_bb: 1.4,
      previous_ev_compared_hands: 1,
      previous_exact_accuracy: 1,
      recent_action_accuracy: 0.75,
      recent_average_ev_loss_bb: 0.2,
      recent_ev_compared_hands: 1,
      recent_exact_accuracy: 0.5,
      window_hands: 2,
    },
    ...overrides,
  };
}

describe("TrainingProgressOverview", () => {
  it("renders aggregate metrics and EV-aware trend tones", () => {
    render(<TrainingProgressOverview progress={overviewProgress()} />);

    const summary = screen.getByLabelText("Training progress summary");
    expect(summary).toHaveClass("has-ev");
    expect(summary).toHaveTextContent("8reviewed");
    expect(summary).toHaveTextContent("75%action match");
    expect(summary).toHaveTextContent("50%exact line");
    expect(summary).toHaveTextContent("0.043 BBavg EV loss");
    expect(within(summary).getByText("2")).toHaveClass("needs-review");

    const trend = screen.getByRole("region", { name: "Recent trend" });
    expect(within(trend).getByText("Last 2 vs previous 2")).toBeInTheDocument();
    expect(within(trend).getByText("+25 pts")).toHaveClass("improving");
    expect(within(trend).getByText("-50 pts")).toHaveClass("declining");
    expect(within(trend).getByText("-1.2 BB")).toHaveClass("improving");
  });

  it("omits EV and trend fields when they are unavailable", () => {
    render(
      <TrainingProgressOverview
        progress={overviewProgress({
          average_ev_loss_bb: null,
          ev_compared_hands: 0,
          needs_review_hands: 0,
          trend: null,
        })}
      />,
    );

    const summary = screen.getByLabelText("Training progress summary");
    expect(summary).not.toHaveClass("has-ev");
    expect(within(summary).queryByText("avg EV loss")).not.toBeInTheDocument();
    expect(within(summary).getByText("0")).not.toHaveClass("needs-review");
    expect(
      screen.queryByRole("region", { name: "Recent trend" }),
    ).not.toBeInTheDocument();
  });
});
