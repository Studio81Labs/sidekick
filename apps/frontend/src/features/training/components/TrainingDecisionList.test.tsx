import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  TrainingDecisionList,
  type TrainingDecisionListProps,
} from "./TrainingDecisionList";
import type { RecommendationAction } from "../../../shared/types/recommendations";
import type { TrainingRecentHand } from "../../../shared/types/training";

afterEach(cleanup);

const HANDS: TrainingRecentHand[] = [
  {
    decision_action: "fold",
    decision_certainty: "high",
    decision_sizing: null,
    ev_loss_bb: 0.8,
    hero_cards: [
      { rank: "A", suit: "spades" },
      { rank: "K", suit: "hearts" },
    ],
    job_id: "reviewed-hand",
    original_filename: "reviewed.png",
    outcome: "different",
    recommended_action: "call",
    recommended_sizing: null,
    recorded_at: "2026-08-14T08:00:00Z",
    review_note: "Defend this combo.",
    reviewed_at: "2026-08-14T09:00:00Z",
    street: "river",
  },
  {
    decision_action: "check",
    decision_certainty: null,
    decision_sizing: null,
    ev_loss_bb: null,
    hero_cards: [],
    job_id: "mixed-hand",
    original_filename: "mixed.png",
    outcome: "mixed",
    recommended_action: "bet",
    recommended_sizing: 2.5,
    recorded_at: "2026-08-14T07:00:00Z",
    review_note: null,
    reviewed_at: null,
    street: null,
  },
];

const decisionLabel = (action: RecommendationAction, sizing: number | null) =>
  `${action}${sizing === null ? "" : ` ${sizing}`}`;

const defaultProps = {
  certaintyLabel: (certainty: string) => certainty.toUpperCase(),
  decisionLabel,
  lessonFiltersActive: false,
  onOpen: vi.fn(),
  onReopen: vi.fn(),
  openDisabled: false,
  positionFilter: null,
  reopenDisabled: false,
  solverFilter: null,
  streetFilter: null,
  view: "recent" as const,
};

const EMPTY_CASES: Array<[Partial<TrainingDecisionListProps>, string]> = [
  [
    { view: "lessons", lessonFiltersActive: false },
    "No saved lesson notes yet.",
  ],
  [
    { view: "lessons", lessonFiltersActive: true },
    "No saved lesson notes match these filters.",
  ],
  [{ view: "review" }, "No action or sizing differences need review."],
  [
    { solverFilter: { kind: "route", key: "local", label: "Local" } },
    "No training hands were handled by this engine.",
  ],
  [
    { solverFilter: { kind: "fallback", key: "rule", label: "Rule" } },
    "No training hands use this fallback.",
  ],
  [
    { solverFilter: { kind: "unattributed", label: "Unattributed" } },
    "No training hands are missing engine attribution.",
  ],
  [
    {
      positionFilter: { kind: "position", position: "BTN", label: "BTN" },
    },
    "No training hands were recorded at BTN.",
  ],
  [
    { positionFilter: { kind: "unpositioned", label: "Unpositioned" } },
    "No training hands have a recorded position.",
  ],
  [
    { streetFilter: { street: "turn", label: "Turn" } },
    "No training hands were played on Turn.",
  ],
  [{}, "No recent training decisions."],
];

describe("TrainingDecisionList", () => {
  it("renders hand details and sends open and reopen actions", () => {
    const onOpen = vi.fn();
    const onReopen = vi.fn();
    render(
      <TrainingDecisionList
        {...defaultProps}
        hands={HANDS}
        onOpen={onOpen}
        onReopen={onReopen}
      />,
    );

    const reviewed = screen.getByRole("button", {
      name: "Open reviewed.png training review",
    });
    expect(reviewed).toHaveTextContent("A♠ K♥");
    expect(reviewed).toHaveTextContent("river · reviewed.png · HIGH certainty");
    expect(reviewed).toHaveTextContent("You: fold");
    expect(reviewed).toHaveTextContent("Solver: call");
    expect(reviewed).toHaveTextContent("EV loss: 0.8 BB");
    expect(reviewed).toHaveTextContent("Note: Defend this combo.");
    expect(reviewed).toHaveTextContent("Reviewed");

    const mixed = screen.getByRole("button", {
      name: "Open mixed.png training review",
    });
    expect(mixed).toHaveTextContent("Unknown cards");
    expect(mixed).toHaveTextContent("Unknown street · mixed.png");
    expect(mixed).toHaveTextContent("Supported mix");

    fireEvent.click(reviewed);
    expect(onOpen).toHaveBeenCalledWith("reviewed-hand", false);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Reopen reviewed.png training review",
      }),
    );
    expect(onReopen).toHaveBeenCalledWith("reviewed-hand");
  });

  it("continues the review queue, disables controls, and hides reopen in lessons", () => {
    const onOpen = vi.fn();
    const { rerender } = render(
      <TrainingDecisionList
        {...defaultProps}
        hands={[HANDS[0]]}
        onOpen={onOpen}
        openDisabled
        reopenDisabled
        view="review"
      />,
    );

    const open = screen.getByRole("button", {
      name: "Open reviewed.png training review",
    });
    const reopen = screen.getByRole("button", {
      name: "Reopen reviewed.png training review",
    });
    expect(open).toBeDisabled();
    expect(reopen).toBeDisabled();

    rerender(
      <TrainingDecisionList
        {...defaultProps}
        hands={[HANDS[0]]}
        onOpen={onOpen}
        view="review"
      />,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Open reviewed.png training review",
      }),
    );
    expect(onOpen).toHaveBeenCalledWith("reviewed-hand", true);

    rerender(
      <TrainingDecisionList
        {...defaultProps}
        hands={[HANDS[0]]}
        view="lessons"
      />,
    );
    expect(
      screen.queryByRole("button", {
        name: "Reopen reviewed.png training review",
      }),
    ).not.toBeInTheDocument();
  });

  it.each(EMPTY_CASES)(
    "renders the expected empty state for %o",
    (overrides, message) => {
      render(
        <TrainingDecisionList {...defaultProps} {...overrides} hands={[]} />,
      );

      expect(screen.getByText(message)).toBeInTheDocument();
    },
  );
});
