import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  TrainingProgressDialog,
  type TrainingProgressDialogProps,
} from "./TrainingProgressDialog";

afterEach(cleanup);

function dialogProps(
  overrides: Partial<TrainingProgressDialogProps> = {},
): TrainingProgressDialogProps {
  return {
    actionDifferenceFocus: null,
    busy: false,
    certaintyFilter: null,
    certaintyFocus: null,
    lessonOrder: "recent",
    lessonQuery: "",
    lessonSearch: "",
    lessonStreet: "all",
    lessonsExportDisabled: true,
    nextReviewHand: null,
    onCertaintyFilterChange: vi.fn(),
    onClose: vi.fn(),
    onFocusActionDifference: vi.fn(),
    onFocusCertainty: vi.fn(),
    onFocusPosition: vi.fn(),
    onFocusStreet: vi.fn(),
    onLessonFiltersChange: vi.fn(),
    onLessonSearchChange: vi.fn(),
    onOpenHand: vi.fn(),
    onPositionFilterChange: vi.fn(),
    onReopenHand: vi.fn(),
    onReviewQueueChange: vi.fn(),
    onSolverFilterChange: vi.fn(),
    onStreetFilterChange: vi.fn(),
    onViewChange: vi.fn(),
    positionFilter: null,
    positionFocus: null,
    progress: null,
    progressLoading: false,
    reviewCertainty: "all",
    reviewDifference: null,
    reviewJobId: null,
    reviewOrder: "recent",
    reviewPosition: null,
    reviewQueueStatus: "No hands waiting for review",
    reviewStreet: "all",
    solverFilter: null,
    streetFilter: null,
    streetFocus: null,
    view: "recent",
    visibleHands: [],
    ...overrides,
  };
}

describe("TrainingProgressDialog", () => {
  it("shows the onboarding state and closes from the footer", async () => {
    const props = dialogProps();
    render(<TrainingProgressDialog {...props} />);

    expect(
      screen.getByRole("dialog", { name: "Training progress" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Lock an answer before revealing a recommendation/),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(props.onClose).toHaveBeenCalledOnce();
  });
});
