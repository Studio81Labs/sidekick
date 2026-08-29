import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  HandReviewWorkspace,
  type HandReviewWorkspaceProps,
} from "./HandReviewWorkspace";

vi.mock("../../../features/hand-review/components/HandReviewPanel", () => ({
  HandReviewPanel: () => <div>Hand review shell</div>,
}));

afterEach(cleanup);

describe("HandReviewWorkspace", () => {
  it("renders the hand-review shell without decision features", () => {
    render(
      <HandReviewWorkspace panel={{} as HandReviewWorkspaceProps["panel"]} />,
    );

    expect(screen.getByText("Hand review shell")).toBeInTheDocument();
    expect(screen.queryByText("Recommendation slot")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Training decision slot"),
    ).not.toBeInTheDocument();
  });
});
