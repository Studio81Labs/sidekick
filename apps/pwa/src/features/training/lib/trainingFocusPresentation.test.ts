import { describe, expect, it } from "vitest";

import type { TrainingProgress } from "../../../shared/types/training";
import {
  suggestedActionDifferenceFocus,
  suggestedCertaintyFocus,
  suggestedPositionFocus,
  suggestedTrainingFocus,
} from "./trainingFocusPresentation";

function progress(overrides: Partial<TrainingProgress> = {}): TrainingProgress {
  return {
    reviewed_hands: 0,
    action_matches: 0,
    exact_matches: 0,
    different_actions: 0,
    needs_review_hands: 0,
    action_accuracy: 0,
    exact_accuracy: 0,
    ev_compared_hands: 0,
    average_ev_loss_bb: null,
    street_summaries: [],
    recent_hands: [],
    review_queue_hands: 0,
    review_queue: [],
    ...overrides,
  };
}

describe("training focus presentation", () => {
  it("prioritizes the pending street with the highest measured EV loss", () => {
    const focus = suggestedTrainingFocus(
      progress({
        review_street_counts: { flop: 2, turn: 1 },
        street_summaries: [
          {
            street: "flop",
            reviewed_hands: 4,
            action_matches: 3,
            exact_matches: 2,
            action_accuracy: 0.75,
            exact_accuracy: 0.5,
            ev_compared_hands: 4,
            average_ev_loss_bb: 0.2,
          },
          {
            street: "turn",
            reviewed_hands: 2,
            action_matches: 1,
            exact_matches: 1,
            action_accuracy: 0.5,
            exact_accuracy: 0.5,
            ev_compared_hands: 2,
            average_ev_loss_bb: 0.7,
          },
        ],
      }),
    );

    expect(focus).toMatchObject({
      street: "turn",
      reason: "Highest average EV loss: 0.7 BB",
    });
  });

  it("selects certainty, position, and action-difference backlogs", () => {
    const trainingProgress = progress({
      certainty_summaries: [
        {
          certainty: "high",
          hands: 2,
          action_matches: 2,
          exact_matches: 2,
          needs_review_hands: 1,
          action_accuracy: 1,
          exact_accuracy: 1,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
        {
          certainty: "low",
          hands: 3,
          action_matches: 1,
          exact_matches: 1,
          needs_review_hands: 2,
          action_accuracy: 0.33,
          exact_accuracy: 0.33,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
      ],
      position_summaries: [
        {
          position: "BTN",
          reviewed_hands: 2,
          action_matches: 1,
          exact_matches: 1,
          needs_review_hands: 1,
          action_accuracy: 0.5,
          exact_accuracy: 0.5,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
        {
          position: "BB",
          reviewed_hands: 3,
          action_matches: 1,
          exact_matches: 1,
          needs_review_hands: 2,
          action_accuracy: 0.33,
          exact_accuracy: 0.33,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
      ],
      action_differences: [
        {
          decision_action: "call",
          recommended_action: "raise",
          hands: 3,
          needs_review_hands: 3,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
      ],
    });

    expect(suggestedCertaintyFocus(trainingProgress)?.certainty).toBe("low");
    expect(suggestedPositionFocus(trainingProgress)?.label).toBe("BB");
    expect(suggestedActionDifferenceFocus(trainingProgress)?.label).toBe(
      "Call to Raise",
    );
  });
});
