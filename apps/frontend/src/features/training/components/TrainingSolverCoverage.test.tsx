import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TrainingSolverCoverage } from "./TrainingSolverCoverage";
import type {
  TrainingSolverCoverage as TrainingSolverCoverageModel,
  TrainingTrend,
} from "../../../shared/types/training";

afterEach(cleanup);

const PERFORMANCE_TREND: TrainingTrend = {
  action_accuracy_delta: 0.1,
  average_ev_loss_delta_bb: -0.2,
  exact_accuracy_delta: -0.1,
  previous_action_accuracy: 0.65,
  previous_average_ev_loss_bb: 0.4,
  previous_ev_compared_hands: 2,
  previous_exact_accuracy: 0.6,
  recent_action_accuracy: 0.75,
  recent_average_ev_loss_bb: 0.2,
  recent_ev_compared_hands: 2,
  recent_exact_accuracy: 0.5,
  window_hands: 2,
};

function solverCoverage(
  overrides: Partial<TrainingSolverCoverageModel> = {},
): TrainingSolverCoverageModel {
  return {
    fallback_hands: 2,
    fallback_rate: 0.25,
    fallback_reasons: [
      {
        action_accuracy: 0.5,
        average_ev_loss_bb: null,
        ev_compared_hands: 0,
        exact_accuracy: 0.5,
        hands: 2,
        key: "ambiguous_position",
        reason: "Ambiguous position",
        street_counts: { flop: 2 },
      },
    ],
    routes: [
      {
        action_accuracy: 0.75,
        average_ev_loss_bb: 0.2,
        engine: "local_solver",
        ev_compared_hands: 4,
        exact_accuracy: 0.5,
        fallback_hands: 1,
        hands: 6,
        key: "local_solver:postflop",
        street_counts: { flop: 4, turn: 2 },
        trend: PERFORMANCE_TREND,
      },
    ],
    total_hands: 10,
    tracked_hands: 8,
    trend: {
      attribution_rate_delta: 0.1,
      fallback_rate_delta: -0.05,
      previous_attribution_rate: 0.7,
      previous_fallback_rate: 0.3,
      recent_attribution_rate: 0.8,
      recent_fallback_rate: 0.25,
      window_hands: 5,
    },
    unattributed_hands: 2,
    ...overrides,
  };
}

describe("TrainingSolverCoverage", () => {
  it("renders coverage evidence and sends drill-down filters", () => {
    const onFilterChange = vi.fn();
    render(
      <TrainingSolverCoverage
        controlsDisabled={false}
        coverage={solverCoverage()}
        engineLabel={(engine) =>
          engine === "local_solver" ? "Local solver" : engine
        }
        onFilterChange={onFilterChange}
      />,
    );

    const trend = screen.getByLabelText("Solver coverage trend");
    expect(within(trend).getByText("80%")).toBeInTheDocument();
    expect(within(trend).getByText("+10 pts")).toHaveClass("improving");
    expect(within(trend).getByText("-5 pts")).toHaveClass("improving");
    expect(screen.getByText("F 4 · T 2")).toBeInTheDocument();
    expect(screen.getByText("0.2 BB EV loss")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /Show 2 unattributed hands/ }),
    );
    expect(onFilterChange).toHaveBeenLastCalledWith({
      kind: "unattributed",
      label: "Unattributed recommendations",
    });

    fireEvent.click(
      screen.getByRole("button", { name: /handled by Local solver/ }),
    );
    expect(onFilterChange).toHaveBeenLastCalledWith({
      kind: "route",
      key: "local_solver:postflop",
      label: "Local solver",
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: /using fallback: Ambiguous position/,
      }),
    );
    expect(onFilterChange).toHaveBeenLastCalledWith({
      kind: "fallback",
      key: "ambiguous_position",
      label: "Ambiguous position",
    });
  });

  it("disables every drill-down while the parent is busy", () => {
    render(
      <TrainingSolverCoverage
        controlsDisabled
        coverage={solverCoverage()}
        engineLabel={(engine) => engine}
        onFilterChange={vi.fn()}
      />,
    );

    expect(screen.getAllByRole("button")).toHaveLength(3);
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
    }
  });

  it("renders nothing when no solver coverage has been recorded", () => {
    const { container } = render(
      <TrainingSolverCoverage
        controlsDisabled={false}
        coverage={solverCoverage({ total_hands: 0 })}
        engineLabel={(engine) => engine}
        onFilterChange={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
