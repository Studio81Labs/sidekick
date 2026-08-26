import type { ReactNode } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  HandReviewWorkspace,
  type HandReviewWorkspaceProps,
} from "./HandReviewWorkspace";

vi.mock("../../../features/hand-review/components/HandReviewPanel", () => ({
  HandReviewPanel: ({ children }: { children?: ReactNode }) => (
    <div>Hand review shell{children}</div>
  ),
}));
vi.mock(
  "../../../features/recommendation/components/RecommendationPanel",
  () => ({
    RecommendationPanel: () => <div>Recommendation slot</div>,
  }),
);
vi.mock("../../../features/training/components/TrainingDecisionPanel", () => ({
  TrainingDecisionPanel: () => <div>Training decision slot</div>,
}));

afterEach(cleanup);

describe("HandReviewWorkspace", () => {
  it("composes decision features inside the hand-review shell", () => {
    render(
      <HandReviewWorkspace
        panel={{} as HandReviewWorkspaceProps["panel"]}
        recommendation={{} as HandReviewWorkspaceProps["recommendation"]}
        trainingDecision={{} as HandReviewWorkspaceProps["trainingDecision"]}
      />,
    );

    expect(screen.getByText("Hand review shell")).toBeInTheDocument();
    expect(screen.getByText("Recommendation slot")).toBeInTheDocument();
    expect(screen.getByText("Training decision slot")).toBeInTheDocument();
  });
});
