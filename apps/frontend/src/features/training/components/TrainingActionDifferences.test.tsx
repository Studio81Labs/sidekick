import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TrainingActionDifferences } from "./TrainingActionDifferences";
import type { TrainingActionDifference } from "../../../shared/types/training";

afterEach(cleanup);

const DIFFERENCES: TrainingActionDifference[] = [
  {
    average_ev_loss_bb: 0.8,
    decision_action: "fold",
    ev_compared_hands: 2,
    hands: 2,
    needs_review_hands: 2,
    recommended_action: "call",
  },
  {
    average_ev_loss_bb: null,
    decision_action: "check",
    ev_compared_hands: 0,
    hands: 1,
    needs_review_hands: 0,
    recommended_action: "bet",
  },
  {
    average_ev_loss_bb: 0.2,
    decision_action: "call",
    ev_compared_hands: 1,
    hands: 1,
    needs_review_hands: 1,
    recommended_action: "raise",
  },
  {
    average_ev_loss_bb: 0.1,
    decision_action: "bet",
    ev_compared_hands: 1,
    hands: 1,
    needs_review_hands: 1,
    recommended_action: "raise",
  },
];

const actionLabel = (action: string) =>
  `${action.slice(0, 1).toUpperCase()}${action.slice(1)}`;

describe("TrainingActionDifferences", () => {
  it("renders the top three differences and sends focus and review actions", () => {
    const onReview = vi.fn();
    render(
      <TrainingActionDifferences
        actionLabel={actionLabel}
        controlsDisabled={false}
        differences={DIFFERENCES}
        focus={{
          difference: {
            decision_action: "fold",
            recommended_action: "call",
          },
          label: "Fold to Call",
          reason: "Highest average EV loss: 0.8 BB",
        }}
        onReview={onReview}
        showFocus
      />,
    );

    const section = screen.getByRole("region", { name: "Common differences" });
    expect(within(section).getByText("0.8 BB avg loss")).toBeInTheDocument();
    expect(within(section).getByText("EV ungraded")).toBeInTheDocument();
    expect(
      within(section).queryByText("0.1 BB avg loss"),
    ).not.toBeInTheDocument();
    expect(
      within(section).getByLabelText("No pending Check to Bet reviews"),
    ).toHaveTextContent("—");

    fireEvent.click(
      within(section).getByRole("button", {
        name: "Focus Fold to Call differences: Highest average EV loss: 0.8 BB",
      }),
    );
    expect(onReview).toHaveBeenLastCalledWith({
      decision_action: "fold",
      recommended_action: "call",
    });

    fireEvent.click(
      within(section).getByRole("button", {
        name: "Review Fold to Call differences (2)",
      }),
    );
    expect(onReview).toHaveBeenLastCalledWith(DIFFERENCES[0]);
  });

  it("hides focus outside recent view and disables pending review controls", () => {
    render(
      <TrainingActionDifferences
        actionLabel={actionLabel}
        controlsDisabled
        differences={DIFFERENCES}
        focus={{
          difference: {
            decision_action: "fold",
            recommended_action: "call",
          },
          label: "Fold to Call",
          reason: "Pending review",
        }}
        onReview={vi.fn()}
        showFocus={false}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /Focus Fold to Call/ }),
    ).not.toBeInTheDocument();
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
    }
  });

  it("renders nothing without action differences", () => {
    const { container } = render(
      <TrainingActionDifferences
        actionLabel={actionLabel}
        controlsDisabled={false}
        differences={[]}
        focus={null}
        onReview={vi.fn()}
        showFocus
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
