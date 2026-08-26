import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TrainingProgressControls } from "./TrainingProgressControls";

afterEach(cleanup);

const callbacks = () => ({
  onLessonOrderChange: vi.fn(),
  onLessonSearchChange: vi.fn(),
  onLessonSearchSubmit: vi.fn(),
  onLessonStreetChange: vi.fn(),
  onReviewCertaintyChange: vi.fn(),
  onReviewOrderChange: vi.fn(),
  onReviewStreetChange: vi.fn(),
  onViewChange: vi.fn(),
});

const defaultProps = {
  controlsDisabled: false,
  lessonCount: 3,
  lessonOrder: "recent" as const,
  lessonQuery: "",
  lessonSearch: "",
  lessonStreet: "all" as const,
  needsReviewHands: 2,
  reviewCertainty: "all" as const,
  reviewOrder: "recent" as const,
  reviewStreet: "all" as const,
};

describe("TrainingProgressControls", () => {
  it("shows view counts and delegates view selection", () => {
    const handlers = callbacks();
    render(
      <TrainingProgressControls
        {...defaultProps}
        {...handlers}
        view="recent"
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Recent decisions" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Needs review 2" }));
    fireEvent.click(screen.getByRole("button", { name: "Lessons 3" }));
    expect(handlers.onViewChange).toHaveBeenNthCalledWith(1, "review");
    expect(handlers.onViewChange).toHaveBeenNthCalledWith(2, "lessons");
  });

  it("delegates review order, street, and certainty changes", () => {
    const handlers = callbacks();
    render(
      <TrainingProgressControls
        {...defaultProps}
        {...handlers}
        view="review"
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Needs review" }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Review order"), {
      target: { value: "ev_loss" },
    });
    fireEvent.change(screen.getByLabelText("Review street"), {
      target: { value: "turn" },
    });
    fireEvent.change(screen.getByLabelText("Review certainty"), {
      target: { value: "high" },
    });
    expect(handlers.onReviewOrderChange).toHaveBeenCalledWith("ev_loss");
    expect(handlers.onReviewStreetChange).toHaveBeenCalledWith("turn");
    expect(handlers.onReviewCertaintyChange).toHaveBeenCalledWith("high");
  });

  it("delegates lesson search and ordering controls", () => {
    const handlers = callbacks();
    render(
      <TrainingProgressControls
        {...defaultProps}
        {...handlers}
        lessonSearch="river call"
        view="lessons"
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Saved lessons" }),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search saved lesson notes"), {
      target: { value: "turn raise" },
    });
    fireEvent.submit(screen.getByRole("search"));
    fireEvent.change(screen.getByLabelText("Lesson order"), {
      target: { value: "ev_loss" },
    });
    fireEvent.change(screen.getByLabelText("Lesson street"), {
      target: { value: "river" },
    });
    expect(handlers.onLessonSearchChange).toHaveBeenCalledWith("turn raise");
    expect(handlers.onLessonSearchSubmit).toHaveBeenCalledOnce();
    expect(handlers.onLessonOrderChange).toHaveBeenCalledWith("ev_loss");
    expect(handlers.onLessonStreetChange).toHaveBeenCalledWith("river");
  });

  it("disables visible controls and unchanged lesson searches", () => {
    const handlers = callbacks();
    const { rerender } = render(
      <TrainingProgressControls
        {...defaultProps}
        {...handlers}
        controlsDisabled
        view="review"
      />,
    );

    for (const control of screen.getAllByRole("combobox")) {
      expect(control).toBeDisabled();
    }

    rerender(
      <TrainingProgressControls
        {...defaultProps}
        {...handlers}
        lessonQuery="river"
        lessonSearch=" river "
        view="lessons"
      />,
    );
    expect(
      screen.getByRole("button", { name: "Apply lesson search" }),
    ).toBeDisabled();
  });
});
