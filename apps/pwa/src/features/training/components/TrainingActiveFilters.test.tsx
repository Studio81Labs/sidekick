import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TrainingActiveFilters } from "./TrainingActiveFilters";

afterEach(cleanup);

const callbacks = () => ({
  onClearCertainty: vi.fn(),
  onClearPosition: vi.fn(),
  onClearReviewDifference: vi.fn(),
  onClearReviewPosition: vi.fn(),
  onClearSolver: vi.fn(),
  onClearStreet: vi.fn(),
});

const defaultProps = {
  actionLabel: (action: string) => action.toUpperCase(),
  certaintyFilter: null,
  controlsDisabled: false,
  positionFilter: null,
  reviewDifference: null,
  reviewPosition: null,
  solverFilter: null,
  streetFilter: null,
} as const;

describe("TrainingActiveFilters", () => {
  it("renders and clears both review filters", () => {
    const handlers = callbacks();
    render(
      <TrainingActiveFilters
        {...defaultProps}
        {...handlers}
        reviewDifference={{
          decision_action: "fold",
          recommended_action: "call",
        }}
        reviewPosition={{ kind: "position", label: "BTN", position: "BTN" }}
        view="review"
      />,
    );

    expect(
      screen.getByLabelText("Active action-difference filter"),
    ).toHaveTextContent("FOLDCALL");
    expect(
      screen.getByLabelText("Active review position filter"),
    ).toHaveTextContent("BTN");
    fireEvent.click(
      screen.getByRole("button", { name: "Clear action-difference filter" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Clear review position filter" }),
    );
    expect(handlers.onClearReviewDifference).toHaveBeenCalledOnce();
    expect(handlers.onClearReviewPosition).toHaveBeenCalledOnce();
  });

  it("renders and clears every recent filter", () => {
    const handlers = callbacks();
    render(
      <TrainingActiveFilters
        {...defaultProps}
        {...handlers}
        certaintyFilter={{ certainty: "high", label: "High" }}
        positionFilter={{ kind: "unpositioned", label: "Unpositioned" }}
        solverFilter={{ kind: "fallback", key: "rule", label: "Rule fallback" }}
        streetFilter={{ street: "turn", label: "Turn" }}
        view="recent"
      />,
    );

    const solver = screen.getByLabelText("Active solver filter");
    expect(solver).toHaveTextContent("Rule fallback");
    expect(solver.querySelector(".lucide-triangle-alert")).toBeInTheDocument();
    expect(screen.getByLabelText("Active position filter")).toHaveTextContent(
      "Unpositioned",
    );
    expect(screen.getByLabelText("Active street filter")).toHaveTextContent(
      "Turn",
    );
    expect(screen.getByLabelText("Active certainty filter")).toHaveTextContent(
      "High",
    );

    for (const label of [
      "Clear solver filter",
      "Clear position filter",
      "Clear street filter",
      "Clear certainty filter",
    ]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
    }
    expect(handlers.onClearSolver).toHaveBeenCalledOnce();
    expect(handlers.onClearPosition).toHaveBeenCalledOnce();
    expect(handlers.onClearStreet).toHaveBeenCalledOnce();
    expect(handlers.onClearCertainty).toHaveBeenCalledOnce();
  });

  it("uses solver-specific icons, disables controls, and hides filters in lessons", () => {
    const handlers = callbacks();
    const { rerender } = render(
      <TrainingActiveFilters
        {...defaultProps}
        {...handlers}
        controlsDisabled
        solverFilter={{ kind: "unattributed", label: "Unattributed" }}
        view="recent"
      />,
    );

    expect(
      screen
        .getByLabelText("Active solver filter")
        .querySelector(".lucide-info"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Clear solver filter" }),
    ).toBeDisabled();

    rerender(
      <TrainingActiveFilters
        {...defaultProps}
        {...handlers}
        solverFilter={{ kind: "route", key: "local", label: "Local" }}
        view="recent"
      />,
    );
    expect(
      screen
        .getByLabelText("Active solver filter")
        .querySelector(".lucide-target"),
    ).toBeInTheDocument();

    rerender(
      <TrainingActiveFilters
        {...defaultProps}
        {...handlers}
        solverFilter={{ kind: "route", key: "local", label: "Local" }}
        view="lessons"
      />,
    );
    expect(
      screen.queryByLabelText("Active solver filter"),
    ).not.toBeInTheDocument();
  });

  it("renders nothing when the current view has no active filters", () => {
    const { container } = render(
      <TrainingActiveFilters
        {...defaultProps}
        {...callbacks()}
        view="recent"
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
