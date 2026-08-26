import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  AnalyzerTestApp as App,
  canonicalState,
  deferredResponse,
  fetchMock,
  jsonResponse,
  processingQueueResponse,
  recommendation,
  recommendedJob,
} from "../../../test/analyzerHarness";

describe("Analyzer training progress", () => {
  it("continues through the filtered training review queue", async () => {
    const trainingDecision = {
      action: "call" as const,
      sizing: null,
      recorded_at: "2026-07-20T12:00:00Z",
    };
    const reviewedJob = {
      ...recommendedJob(),
      id: "review-job",
      original_filename: "review.png",
      image_filename: "original.png",
      training_decision: trainingDecision,
    };
    const completedReviewedJob = {
      ...reviewedJob,
      training_reviewed_at: "2026-07-20T12:05:00Z",
      training_review_note: "Prefer calling this raise size.",
    };
    const sizeJob = {
      ...recommendedJob(),
      id: "size-job",
      original_filename: "size.png",
      image_filename: "original.png",
      training_decision: {
        action: "fold" as const,
        sizing: null,
        recorded_at: "2026-07-20T11:00:00Z",
      },
      recommendation: {
        ...recommendation,
        action: "call" as const,
        sizing: null,
      },
    };
    const completedSizeJob = {
      ...sizeJob,
      training_reviewed_at: "2026-07-20T12:06:00Z",
      training_review_note: "Do not overfold the river.",
    };
    const exactHand = {
      job_id: "exact-job",
      original_filename: "exact.png",
      street: "flop" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "raise" as const,
      decision_sizing: 7.5,
      recommended_action: "raise" as const,
      recommended_sizing: 7.5,
      outcome: "match" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      decision_certainty: "low" as const,
      ev_loss_bb: 0,
    };
    const mixedHand = {
      ...exactHand,
      job_id: "mixed-job",
      original_filename: "mixed.png",
      decision_action: "raise" as const,
      decision_sizing: 8,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "mixed" as const,
      recorded_at: "2026-07-20T12:30:00Z",
      decision_certainty: "high" as const,
      review_note: "Prefer the lower-variance supported line.",
      ev_loss_bb: 0.01,
    };
    const reviewQueue = [
      {
        job_id: "review-job",
        original_filename: "review.png",
        street: "turn" as const,
        hero_cards: canonicalState().hero_cards,
        decision_action: "call" as const,
        decision_sizing: null,
        recommended_action: "raise" as const,
        recommended_sizing: 7.5,
        outcome: "different" as const,
        recorded_at: "2026-07-20T12:00:00Z",
        reviewed_at: null,
        ev_loss_bb: 0.12,
      },
      {
        job_id: "size-job",
        original_filename: "size.png",
        street: "river" as const,
        hero_cards: canonicalState().hero_cards,
        decision_action: "fold" as const,
        decision_sizing: null,
        recommended_action: "call" as const,
        recommended_sizing: null,
        outcome: "different" as const,
        recorded_at: "2026-07-20T11:00:00Z",
        reviewed_at: null,
        ev_loss_bb: null,
      },
    ];
    const streetTrend = {
      window_hands: 2,
      recent_action_accuracy: 0.75,
      previous_action_accuracy: 0.5,
      action_accuracy_delta: 0.25,
      recent_exact_accuracy: 0.25,
      previous_exact_accuracy: 0.75,
      exact_accuracy_delta: -0.5,
      recent_ev_compared_hands: 2,
      previous_ev_compared_hands: 2,
      recent_average_ev_loss_bb: 0.2,
      previous_average_ev_loss_bb: 0.6,
      average_ev_loss_delta_bb: -0.4,
    };
    const progress = {
      reviewed_hands: 4,
      action_matches: 3,
      exact_matches: 2,
      different_actions: 1,
      needs_review_hands: 2,
      action_accuracy: 3 / 4,
      exact_accuracy: 2 / 4,
      ev_compared_hands: 3,
      average_ev_loss_bb: 0.043333,
      certainty_summaries: [
        {
          certainty: "low" as const,
          hands: 1,
          action_matches: 1,
          exact_matches: 1,
          action_accuracy: 1,
          exact_accuracy: 1,
          ev_compared_hands: 1,
          average_ev_loss_bb: 0,
        },
        {
          certainty: "high" as const,
          hands: 1,
          action_matches: 1,
          exact_matches: 1,
          action_accuracy: 1,
          exact_accuracy: 1,
          ev_compared_hands: 1,
          average_ev_loss_bb: 0.01,
        },
      ],
      action_differences: [
        {
          decision_action: "fold" as const,
          recommended_action: "call" as const,
          hands: 2,
          needs_review_hands: 2,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
      ],
      street_summaries: [
        {
          street: "flop" as const,
          reviewed_hands: 4,
          action_matches: 3,
          exact_matches: 2,
          action_accuracy: 3 / 4,
          exact_accuracy: 2 / 4,
          ev_compared_hands: 2,
          average_ev_loss_bb: 0.005,
          trend: streetTrend,
        },
      ],
      position_summaries: [
        {
          position: "BTN",
          reviewed_hands: 2,
          action_matches: 1,
          exact_matches: 1,
          action_accuracy: 0.5,
          exact_accuracy: 0.5,
          ev_compared_hands: 1,
          average_ev_loss_bb: 0.12,
        },
        {
          position: "OOP",
          reviewed_hands: 1,
          action_matches: 1,
          exact_matches: 1,
          action_accuracy: 1,
          exact_accuracy: 1,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
      ],
      unpositioned_hands: 1,
      recent_hands: [exactHand, mixedHand],
      review_queue_hands: 2,
      review_queue: reviewQueue,
    };
    const nextProgress = {
      ...progress,
      needs_review_hands: 1,
      review_queue_hands: 1,
      review_queue: [reviewQueue[1]],
    };
    const completedProgress = {
      ...progress,
      needs_review_hands: 0,
      position_summaries: [],
      review_queue_hands: 0,
      review_queue: [],
      unpositioned_hands: 4,
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(reviewedJob))
      .mockResolvedValueOnce(jsonResponse(completedReviewedJob))
      .mockResolvedValueOnce(jsonResponse(nextProgress))
      .mockResolvedValueOnce(jsonResponse(sizeJob))
      .mockResolvedValueOnce(jsonResponse(completedSizeJob))
      .mockResolvedValueOnce(jsonResponse(completedProgress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    const summary = await within(dialog).findByLabelText(
      "Training progress summary",
    );
    expect(summary).toHaveTextContent("75%");
    expect(within(summary).getByText("50%")).toBeInTheDocument();
    expect(within(summary).getByText("0.043 BB")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("row", { name: /low 1 100% 100% 0 BB/i }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("row", { name: /high 1 100% 100% 0.01 BB/i }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("row", { name: /flop 4 75% 50% 0.005 BB/i }),
    ).toBeInTheDocument();
    const renderedStreetTrend = within(dialog).getByLabelText(
      "Last 2 hands vs previous 2: action accuracy change +25 percentage points, exact-line accuracy change -50 percentage points, average EV loss change -0.4 BB",
    );
    expect(within(renderedStreetTrend).getByText("+25 pts")).toHaveClass(
      "improving",
    );
    expect(within(renderedStreetTrend).getByText("-50 pts")).toHaveClass(
      "declining",
    );
    expect(within(renderedStreetTrend).getByText("-0.4 BB")).toHaveClass(
      "improving",
    );
    expect(
      within(dialog).getByRole("heading", { name: "By position" }),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("1 unrecorded")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("row", { name: /BTN 2 50% 50% 0.12 BB/i }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("row", { name: /OOP 1 100% 100%/i }),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("You: Raise 7.5 BB")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Solver: Raise 7.5 BB"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("EV loss: 0.01 BB")).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Note: Prefer the lower-variance supported line.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Exact match")).toBeInTheDocument();
    expect(within(dialog).getByText("Supported mix")).toBeInTheDocument();
    expect(fetchMock().mock.calls[0][0]).toBe(
      "http://localhost:8000/api/training/progress",
    );

    const reviewFoldToCall = within(dialog).getByRole("button", {
      name: "Review Fold to Call differences (2)",
    });
    expect(reviewFoldToCall).toHaveTextContent("2");
    await user.click(reviewFoldToCall);

    expect(
      within(dialog).getByRole("button", { name: "Needs review 2" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(dialog).queryByRole("button", {
        name: "Open exact.png training review",
      }),
    ).not.toBeInTheDocument();
    expect(within(dialog).getAllByText("Different action")).toHaveLength(2);
    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?review_decision_action=fold&review_recommended_action=call",
    );

    await user.click(
      within(dialog).getByRole("button", { name: "Review next" }),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Training progress" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByAltText("Uploaded poker table screenshot"),
    ).toHaveAttribute("src", "http://localhost:8000/api/jobs/review-job/image");
    expect(fetchMock().mock.calls[2][0]).toBe(
      "http://localhost:8000/api/jobs/review-job",
    );

    await user.type(
      await screen.findByLabelText("Training review note"),
      "Prefer calling this raise size.",
    );
    await user.click(
      screen.getByRole("button", { name: "Mark reviewed & next" }),
    );

    await waitFor(() =>
      expect(
        screen.getByAltText("Uploaded poker table screenshot"),
      ).toHaveAttribute("src", "http://localhost:8000/api/jobs/size-job/image"),
    );
    expect(fetchMock().mock.calls[3][0]).toBe(
      "http://localhost:8000/api/jobs/review-job/training-review",
    );
    expect(fetchMock().mock.calls[3][1]).toMatchObject({
      method: "PUT",
      body: JSON.stringify({ note: "Prefer calling this raise size." }),
    });
    expect(fetchMock().mock.calls[4][0]).toBe(
      "http://localhost:8000/api/training/progress?review_decision_action=fold&review_recommended_action=call",
    );
    expect(fetchMock().mock.calls[5][0]).toBe(
      "http://localhost:8000/api/jobs/size-job",
    );
    expect(
      await screen.findByText("Training review completed. Next hand ready"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Training review note")).toHaveValue("");

    await user.type(
      screen.getByLabelText("Training review note"),
      "Do not overfold the river.",
    );
    await user.click(
      screen.getByRole("button", { name: "Mark reviewed & next" }),
    );

    const completedDialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    expect(
      within(completedDialog).getByRole("button", { name: "Needs review 0" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(completedDialog).getByRole("heading", { name: "By position" }),
    ).toBeInTheDocument();
    expect(
      within(completedDialog).getByText("4 unrecorded"),
    ).toBeInTheDocument();
    expect(
      within(completedDialog).getByText(
        "No action or sizing differences need review.",
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Review queue completed"),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[6][0]).toBe(
      "http://localhost:8000/api/jobs/size-job/training-review",
    );
    expect(fetchMock().mock.calls[6][1]).toMatchObject({
      method: "PUT",
      body: JSON.stringify({ note: "Do not overfold the river." }),
    });
    expect(fetchMock().mock.calls[7][0]).toBe(
      "http://localhost:8000/api/training/progress?review_decision_action=fold&review_recommended_action=call",
    );
  });

  it("drills into recent training hands from a street summary", async () => {
    const flopHand = {
      job_id: "flop-job",
      original_filename: "flop.png",
      street: "flop" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "check" as const,
      decision_sizing: null,
      recommended_action: "check" as const,
      recommended_sizing: null,
      outcome: "match" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: 0,
    };
    const turnHand = {
      ...flopHand,
      job_id: "turn-job",
      original_filename: "turn.png",
      street: "turn" as const,
      recorded_at: "2026-07-20T12:00:00Z",
    };
    const progress = {
      reviewed_hands: 3,
      action_matches: 3,
      exact_matches: 3,
      different_actions: 0,
      needs_review_hands: 0,
      action_accuracy: 1,
      exact_accuracy: 1,
      ev_compared_hands: 2,
      average_ev_loss_bb: 0,
      street_summaries: [
        {
          street: "flop" as const,
          reviewed_hands: 2,
          action_matches: 2,
          exact_matches: 2,
          action_accuracy: 1,
          exact_accuracy: 1,
          ev_compared_hands: 1,
          average_ev_loss_bb: 0,
        },
        {
          street: "turn" as const,
          reviewed_hands: 1,
          action_matches: 1,
          exact_matches: 1,
          action_accuracy: 1,
          exact_accuracy: 1,
          ev_compared_hands: 1,
          average_ev_loss_bb: 0,
        },
      ],
      position_summaries: [],
      unpositioned_hands: 3,
      recent_matching_hands: 3,
      recent_hands: [flopHand, turnHand],
      review_queue_hands: 0,
      review_queue: [],
    };
    const flopProgress = {
      ...progress,
      recent_matching_hands: 2,
      recent_hands: [flopHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(flopProgress))
      .mockResolvedValueOnce(jsonResponse(progress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: "Show 2 hands played on flop",
      }),
    );

    const streetFilter = await within(dialog).findByLabelText(
      "Active street filter",
    );
    expect(within(streetFilter).getByText("Flop")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Showing 1 newest of 2 Flop hands."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open flop.png training review",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", {
        name: "Open turn.png training review",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?recent_street=flop",
    );

    await user.click(
      within(streetFilter).getByRole("button", {
        name: "Clear street filter",
      }),
    );
    await waitFor(() =>
      expect(
        within(dialog).queryByLabelText("Active street filter"),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock().mock.calls[2][0]).toBe(
      "http://localhost:8000/api/training/progress",
    );
  });

  it("drills into normalized position and unpositioned training hands", async () => {
    const buttonHand = {
      job_id: "button-job",
      original_filename: "button.png",
      street: "flop" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "check" as const,
      decision_sizing: null,
      recommended_action: "check" as const,
      recommended_sizing: null,
      outcome: "match" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: 0,
    };
    const unpositionedHand = {
      ...buttonHand,
      job_id: "unpositioned-job",
      original_filename: "unpositioned.png",
      recorded_at: "2026-07-20T12:00:00Z",
    };
    const positionTrend = {
      window_hands: 1,
      recent_action_accuracy: 1,
      previous_action_accuracy: 0,
      action_accuracy_delta: 1,
      recent_exact_accuracy: 1,
      previous_exact_accuracy: 0,
      exact_accuracy_delta: 1,
      recent_ev_compared_hands: 1,
      previous_ev_compared_hands: 1,
      recent_average_ev_loss_bb: 0.2,
      previous_average_ev_loss_bb: 0.6,
      average_ev_loss_delta_bb: -0.4,
    };
    const progress = {
      reviewed_hands: 3,
      action_matches: 3,
      exact_matches: 3,
      different_actions: 0,
      needs_review_hands: 0,
      action_accuracy: 1,
      exact_accuracy: 1,
      ev_compared_hands: 2,
      average_ev_loss_bb: 0,
      street_summaries: [],
      position_summaries: [
        {
          position: "BTN",
          reviewed_hands: 2,
          action_matches: 2,
          exact_matches: 2,
          action_accuracy: 1,
          exact_accuracy: 1,
          ev_compared_hands: 1,
          average_ev_loss_bb: 0,
          trend: positionTrend,
        },
      ],
      unpositioned_hands: 1,
      recent_matching_hands: 3,
      recent_hands: [buttonHand, unpositionedHand],
      review_queue_hands: 0,
      review_queue: [],
    };
    const buttonProgress = {
      ...progress,
      recent_matching_hands: 2,
      recent_hands: [buttonHand],
    };
    const unpositionedProgress = {
      ...progress,
      recent_matching_hands: 1,
      recent_hands: [unpositionedHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(buttonProgress))
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(unpositionedProgress))
      .mockResolvedValueOnce(jsonResponse(progress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    expect(
      within(dialog).getByText("Last 1 hand vs previous 1"),
    ).toBeInTheDocument();
    expect(within(dialog).getAllByText("+100 pts")).toHaveLength(2);
    expect(within(dialog).getByText("-0.4 BB")).toHaveClass("improving");
    await user.click(
      within(dialog).getByRole("button", {
        name: "Show 2 hands recorded at BTN. Last 1 hand vs previous 1: action accuracy change +100 percentage points, exact-line accuracy change +100 percentage points, average EV loss change -0.4 BB",
      }),
    );

    const buttonFilter = await within(dialog).findByLabelText(
      "Active position filter",
    );
    expect(within(buttonFilter).getByText("BTN")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Showing 1 newest of 2 BTN hands."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open button.png training review",
      }),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?recent_position=BTN",
    );

    await user.click(
      within(buttonFilter).getByRole("button", {
        name: "Clear position filter",
      }),
    );
    await waitFor(() =>
      expect(
        within(dialog).queryByLabelText("Active position filter"),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock().mock.calls[2][0]).toBe(
      "http://localhost:8000/api/training/progress",
    );

    await user.click(
      within(dialog).getByRole("button", {
        name: "Show 1 unpositioned hand",
      }),
    );

    const unpositionedFilter = await within(dialog).findByLabelText(
      "Active position filter",
    );
    expect(
      within(unpositionedFilter).getByText("Unpositioned"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open unpositioned.png training review",
      }),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[3][0]).toBe(
      "http://localhost:8000/api/training/progress?recent_unpositioned=true",
    );

    await user.click(
      within(unpositionedFilter).getByRole("button", {
        name: "Clear position filter",
      }),
    );
    await waitFor(() =>
      expect(
        within(dialog).queryByLabelText("Active position filter"),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock().mock.calls[4][0]).toBe(
      "http://localhost:8000/api/training/progress",
    );
  });

  it("opens pending reviews from street summaries", async () => {
    const flopHand = {
      job_id: "flop-review",
      original_filename: "flop-review.png",
      street: "flop" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "fold" as const,
      decision_sizing: null,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "different" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: 0.8,
    };
    const progress = {
      reviewed_hands: 2,
      action_matches: 1,
      exact_matches: 1,
      different_actions: 1,
      needs_review_hands: 1,
      action_accuracy: 0.5,
      exact_accuracy: 0.5,
      ev_compared_hands: 1,
      average_ev_loss_bb: 0.8,
      street_summaries: [
        {
          street: "flop" as const,
          reviewed_hands: 1,
          action_matches: 0,
          exact_matches: 0,
          action_accuracy: 0,
          exact_accuracy: 0,
          ev_compared_hands: 1,
          average_ev_loss_bb: 0.8,
        },
        {
          street: "turn" as const,
          reviewed_hands: 1,
          action_matches: 1,
          exact_matches: 1,
          action_accuracy: 1,
          exact_accuracy: 1,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
      ],
      position_summaries: [],
      recent_matching_hands: 2,
      recent_hands: [flopHand],
      review_street_counts: { flop: 1 },
      review_queue_hands: 1,
      review_queue: [flopHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(progress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    const reviewFlop = within(dialog).getByRole("button", {
      name: "Review flop street differences (1)",
    });
    expect(reviewFlop).toHaveTextContent("1");
    const turnRow = within(dialog).getByRole("row", {
      name: "turn 1 100% 100% — —",
    });
    expect(within(turnRow).getAllByRole("button")).toHaveLength(1);

    await user.click(reviewFlop);

    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?review_street=flop",
    );
    expect(
      await within(dialog).findByText("1 pending review hand on flop."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open flop-review.png training review",
      }),
    ).toBeInTheDocument();
  });

  it("opens pending reviews from position summaries", async () => {
    const buttonHand = {
      job_id: "button-review",
      original_filename: "button-review.png",
      street: "flop" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "fold" as const,
      decision_sizing: null,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "different" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: 1,
    };
    const unpositionedHand = {
      ...buttonHand,
      job_id: "unpositioned-review",
      original_filename: "unpositioned-review.png",
      recorded_at: "2026-07-20T12:00:00Z",
    };
    const progress = {
      reviewed_hands: 3,
      action_matches: 1,
      exact_matches: 1,
      different_actions: 2,
      needs_review_hands: 2,
      action_accuracy: 1 / 3,
      exact_accuracy: 1 / 3,
      ev_compared_hands: 2,
      average_ev_loss_bb: 1,
      street_summaries: [],
      position_summaries: [
        {
          position: "BTN",
          reviewed_hands: 2,
          action_matches: 1,
          exact_matches: 1,
          needs_review_hands: 1,
          action_accuracy: 0.5,
          exact_accuracy: 0.5,
          ev_compared_hands: 1,
          average_ev_loss_bb: 1,
        },
      ],
      unpositioned_hands: 1,
      unpositioned_needs_review_hands: 1,
      recent_matching_hands: 3,
      recent_hands: [buttonHand, unpositionedHand],
      review_queue_hands: 2,
      review_queue: [buttonHand, unpositionedHand],
    };
    const buttonProgress = {
      ...progress,
      review_queue_hands: 1,
      review_queue: [buttonHand],
    };
    const unpositionedProgress = {
      ...progress,
      review_queue_hands: 1,
      review_queue: [unpositionedHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(buttonProgress))
      .mockResolvedValueOnce(jsonResponse(buttonProgress))
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(unpositionedProgress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: "Review BTN position differences (1)",
      }),
    );

    const buttonFilter = await within(dialog).findByLabelText(
      "Active review position filter",
    );
    expect(within(buttonFilter).getByText("BTN")).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "1 pending review hand across all streets at BTN.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open button-review.png training review",
      }),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?review_position=BTN",
    );

    await user.selectOptions(
      within(dialog).getByLabelText("Review street"),
      "flop",
    );
    expect(
      await within(dialog).findByText("1 pending review hand on flop at BTN."),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[2][0]).toBe(
      "http://localhost:8000/api/training/progress?review_street=flop&review_position=BTN",
    );

    const filteredButtonPosition = within(dialog).getByLabelText(
      "Active review position filter",
    );
    await user.click(
      within(filteredButtonPosition).getByRole("button", {
        name: "Clear review position filter",
      }),
    );
    await waitFor(() =>
      expect(
        within(dialog).queryByLabelText("Active review position filter"),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock().mock.calls[3][0]).toBe(
      "http://localhost:8000/api/training/progress?review_street=flop",
    );

    await user.click(
      within(dialog).getByRole("button", {
        name: "Review unpositioned differences (1)",
      }),
    );

    const unpositionedFilter = await within(dialog).findByLabelText(
      "Active review position filter",
    );
    expect(
      within(unpositionedFilter).getByText("Unpositioned"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "1 pending review hand across all streets without a recorded position.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open unpositioned-review.png training review",
      }),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[4][0]).toBe(
      "http://localhost:8000/api/training/progress?review_unpositioned=true",
    );
  });

  it("suggests the highest-loss position review focus", async () => {
    const bigBlindHand = {
      job_id: "bb-focus-job",
      original_filename: "bb-focus.png",
      street: "turn" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "fold" as const,
      decision_sizing: null,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "different" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: 1.2,
    };
    const progress = {
      reviewed_hands: 4,
      action_matches: 0,
      exact_matches: 0,
      different_actions: 4,
      needs_review_hands: 4,
      action_accuracy: 0,
      exact_accuracy: 0,
      ev_compared_hands: 4,
      average_ev_loss_bb: 0.6,
      street_summaries: [],
      position_summaries: [
        {
          position: "BTN",
          reviewed_hands: 2,
          action_matches: 0,
          exact_matches: 0,
          needs_review_hands: 2,
          action_accuracy: 0,
          exact_accuracy: 0,
          ev_compared_hands: 2,
          average_ev_loss_bb: 0.4,
        },
        {
          position: "BB",
          reviewed_hands: 1,
          action_matches: 0,
          exact_matches: 0,
          needs_review_hands: 1,
          action_accuracy: 0,
          exact_accuracy: 0,
          ev_compared_hands: 1,
          average_ev_loss_bb: 1.2,
        },
      ],
      unpositioned_hands: 1,
      unpositioned_needs_review_hands: 1,
      recent_hands: [bigBlindHand],
      review_queue_hands: 4,
      review_queue: [bigBlindHand],
    };
    const focusedProgress = {
      ...progress,
      review_queue_hands: 1,
      review_queue: [bigBlindHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(focusedProgress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    const focus = within(dialog).getByRole("button", {
      name: "Focus BB position reviews: Highest average EV loss: 1.2 BB",
    });
    expect(focus).toHaveTextContent("Focus BB");

    await user.click(focus);

    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?review_position=BB",
    );
    expect(
      await within(dialog).findByText(
        "1 pending review hand across all streets at BB.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open bb-focus.png training review",
      }),
    ).toBeInTheDocument();
  });

  it("suggests unpositioned reviews when scored positions are clear", async () => {
    const unpositionedHand = {
      job_id: "unpositioned-focus-job",
      original_filename: "unpositioned-focus.png",
      street: "river" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "fold" as const,
      decision_sizing: null,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "different" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: null,
    };
    const progress = {
      reviewed_hands: 2,
      action_matches: 1,
      exact_matches: 1,
      different_actions: 1,
      needs_review_hands: 1,
      action_accuracy: 0.5,
      exact_accuracy: 0.5,
      ev_compared_hands: 0,
      average_ev_loss_bb: null,
      street_summaries: [],
      position_summaries: [
        {
          position: "BTN",
          reviewed_hands: 1,
          action_matches: 1,
          exact_matches: 1,
          needs_review_hands: 0,
          action_accuracy: 1,
          exact_accuracy: 1,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
      ],
      unpositioned_hands: 1,
      unpositioned_needs_review_hands: 1,
      recent_hands: [unpositionedHand],
      review_queue_hands: 1,
      review_queue: [unpositionedHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(progress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    const focus = within(dialog).getByRole("button", {
      name: "Focus unpositioned reviews: 1 unpositioned hand needs review",
    });
    expect(focus).toHaveTextContent("Focus Unpositioned");

    await user.click(focus);

    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?review_unpositioned=true",
    );
    expect(
      await within(dialog).findByText(
        "1 pending review hand across all streets without a recorded position.",
      ),
    ).toBeInTheDocument();
  });

  it("suggests the highest-loss action-difference review focus", async () => {
    const patternHand = {
      job_id: "raise-call-focus-job",
      original_filename: "raise-call-focus.png",
      street: "turn" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "raise" as const,
      decision_sizing: 8,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "different" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: 1.1,
    };
    const progress = {
      reviewed_hands: 9,
      action_matches: 0,
      exact_matches: 0,
      different_actions: 9,
      needs_review_hands: 7,
      action_accuracy: 0,
      exact_accuracy: 0,
      ev_compared_hands: 3,
      average_ev_loss_bb: 0.6,
      action_differences: [
        {
          decision_action: "fold" as const,
          recommended_action: "call" as const,
          hands: 4,
          needs_review_hands: 2,
          ev_compared_hands: 2,
          average_ev_loss_bb: 0.4,
        },
        {
          decision_action: "check" as const,
          recommended_action: "bet" as const,
          hands: 4,
          needs_review_hands: 4,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
        {
          decision_action: "raise" as const,
          recommended_action: "call" as const,
          hands: 1,
          needs_review_hands: 1,
          ev_compared_hands: 1,
          average_ev_loss_bb: 1.1,
        },
      ],
      street_summaries: [],
      position_summaries: [],
      recent_hands: [patternHand],
      review_queue_hands: 7,
      review_queue: [patternHand],
    };
    const focusedProgress = {
      ...progress,
      review_queue_hands: 1,
      review_queue: [patternHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(focusedProgress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    const focus = within(dialog).getByRole("button", {
      name: "Focus Raise to Call differences: Highest average EV loss: 1.1 BB",
    });
    expect(focus).toHaveTextContent("Focus Raise to Call");

    await user.click(focus);

    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?review_decision_action=raise&review_recommended_action=call",
    );
    expect(
      await within(dialog).findByText(
        "1 pending review hand for Raise to Call across all streets.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open raise-call-focus.png training review",
      }),
    ).toBeInTheDocument();
  });

  it("suggests the largest action-difference backlog when EV is ungraded", async () => {
    const patternHand = {
      job_id: "check-bet-focus-job",
      original_filename: "check-bet-focus.png",
      street: "flop" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "check" as const,
      decision_sizing: null,
      recommended_action: "bet" as const,
      recommended_sizing: 2,
      outcome: "different" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: null,
    };
    const progress = {
      reviewed_hands: 9,
      action_matches: 0,
      exact_matches: 0,
      different_actions: 9,
      needs_review_hands: 6,
      action_accuracy: 0,
      exact_accuracy: 0,
      ev_compared_hands: 0,
      average_ev_loss_bb: null,
      action_differences: [
        {
          decision_action: "fold" as const,
          recommended_action: "call" as const,
          hands: 5,
          needs_review_hands: 2,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
        {
          decision_action: "check" as const,
          recommended_action: "bet" as const,
          hands: 4,
          needs_review_hands: 4,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
        {
          decision_action: "raise" as const,
          recommended_action: "call" as const,
          hands: 2,
          needs_review_hands: 0,
          ev_compared_hands: 0,
          average_ev_loss_bb: null,
        },
      ],
      street_summaries: [],
      position_summaries: [],
      recent_hands: [patternHand],
      review_queue_hands: 6,
      review_queue: [patternHand],
    };
    const focusedProgress = {
      ...progress,
      review_queue_hands: 4,
      review_queue: [patternHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(focusedProgress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    const focus = within(dialog).getByRole("button", {
      name: "Focus Check to Bet differences: Largest backlog: 4 hands need review",
    });
    expect(focus).toHaveTextContent("Focus Check to Bet");
    expect(
      within(dialog).getByRole("button", {
        name: "Review Check to Bet differences (4)",
      }),
    ).toHaveTextContent("4");
    expect(
      within(dialog).getByLabelText("No pending Raise to Call reviews"),
    ).toHaveTextContent("—");

    await user.click(focus);

    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?review_decision_action=check&review_recommended_action=bet",
    );
    expect(
      await within(dialog).findByText(
        "Showing 1 newest of 4 review hands for Check to Bet across all streets.",
      ),
    ).toBeInTheDocument();
  });

  it("drills into solver engine, fallback, and unattributed coverage", async () => {
    const routeKey = "b".repeat(64);
    const fallbackKey = "a".repeat(64);
    const solverPerformanceTrend = {
      window_hands: 1,
      recent_action_accuracy: 1,
      previous_action_accuracy: 0,
      action_accuracy_delta: 1,
      recent_exact_accuracy: 1,
      previous_exact_accuracy: 0,
      exact_accuracy_delta: 1,
      recent_ev_compared_hands: 1,
      previous_ev_compared_hands: 1,
      recent_average_ev_loss_bb: 0.2,
      previous_average_ev_loss_bb: 0.6,
      average_ev_loss_delta_bb: -0.4,
    };
    const routeHand = {
      job_id: "route-job",
      original_filename: "engine.png",
      street: "flop" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "check" as const,
      decision_sizing: null,
      recommended_action: "check" as const,
      recommended_sizing: null,
      outcome: "match" as const,
      recorded_at: "2026-07-21T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: null,
    };
    const fallbackHand = {
      job_id: "fallback-job",
      original_filename: "fallback.png",
      street: "turn" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "call" as const,
      decision_sizing: null,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "match" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: null,
    };
    const unattributedHand = {
      job_id: "unattributed-job",
      original_filename: "legacy.png",
      street: "river" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "fold" as const,
      decision_sizing: null,
      recommended_action: "fold" as const,
      recommended_sizing: null,
      outcome: "match" as const,
      recorded_at: "2026-07-19T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: null,
    };
    const progress = {
      reviewed_hands: 6,
      action_matches: 5,
      exact_matches: 5,
      different_actions: 1,
      needs_review_hands: 1,
      action_accuracy: 5 / 6,
      exact_accuracy: 5 / 6,
      ev_compared_hands: 0,
      average_ev_loss_bb: null,
      solver_coverage: {
        total_hands: 6,
        tracked_hands: 5,
        unattributed_hands: 1,
        fallback_hands: 2,
        fallback_rate: 1 / 3,
        trend: {
          window_hands: 2,
          recent_attribution_rate: 0.75,
          previous_attribution_rate: 1,
          attribution_rate_delta: -0.25,
          recent_fallback_rate: 0,
          previous_fallback_rate: 0.5,
          fallback_rate_delta: -0.5,
        },
        routes: [
          {
            key: routeKey,
            engine: "local_ev_solver_v1",
            hands: 2,
            fallback_hands: 2,
            action_matches: 1,
            exact_matches: 1,
            action_accuracy: 0.5,
            exact_accuracy: 0.5,
            ev_compared_hands: 1,
            average_ev_loss_bb: 0.4,
            trend: solverPerformanceTrend,
            street_counts: { flop: 1, turn: 1 },
          },
          {
            key: "c".repeat(64),
            engine: "postflop_solver",
            hands: 2,
            fallback_hands: 0,
            action_matches: 2,
            exact_matches: 2,
            action_accuracy: 1,
            exact_accuracy: 1,
            ev_compared_hands: 0,
            average_ev_loss_bb: null,
            street_counts: { flop: 1, river: 1 },
          },
          {
            key: "d".repeat(64),
            engine: "preflop_chart_v1",
            hands: 1,
            fallback_hands: 0,
            action_matches: 1,
            exact_matches: 1,
            action_accuracy: 1,
            exact_accuracy: 1,
            ev_compared_hands: 0,
            average_ev_loss_bb: null,
            street_counts: { preflop: 1 },
          },
        ],
        fallback_reasons: [
          {
            key: fallbackKey,
            reason: "hero position must identify IP or OOP",
            hands: 2,
            action_matches: 1,
            exact_matches: 1,
            action_accuracy: 0.5,
            exact_accuracy: 0.5,
            ev_compared_hands: 1,
            average_ev_loss_bb: 0.4,
            trend: solverPerformanceTrend,
            street_counts: { flop: 1, turn: 1 },
          },
        ],
      },
      street_summaries: [],
      recent_matching_hands: 6,
      recent_hands: [],
      review_queue_hands: 0,
      review_queue: [],
    };
    const filteredProgress = {
      ...progress,
      recent_matching_hands: 2,
      recent_hands: [fallbackHand],
    };
    const routeFilteredProgress = {
      ...progress,
      recent_matching_hands: 2,
      recent_hands: [routeHand],
    };
    const unattributedFilteredProgress = {
      ...progress,
      recent_matching_hands: 1,
      recent_hands: [unattributedHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(routeFilteredProgress))
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(filteredProgress))
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(unattributedFilteredProgress))
      .mockResolvedValueOnce(jsonResponse(progress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    expect(
      within(dialog).getByRole("heading", { name: "Solver coverage" }),
    ).toBeInTheDocument();
    const solverTrend = within(dialog).getByLabelText("Solver coverage trend");
    expect(
      within(solverTrend).getByText("Last 2 vs previous 2"),
    ).toBeInTheDocument();
    expect(within(solverTrend).getByText("75%")).toBeInTheDocument();
    expect(within(solverTrend).getByText("0%")).toBeInTheDocument();
    expect(within(solverTrend).getByText("-25 pts")).toHaveClass("declining");
    expect(within(solverTrend).getByText("-50 pts")).toHaveClass("improving");
    const showUnattributedHands = within(dialog).getByRole("button", {
      name: "Show 1 unattributed hand",
    });
    expect(showUnattributedHands).toBeEnabled();
    const showEngineHands = within(dialog).getByRole("button", {
      name: "Show 2 hands handled by Local EV solver. Action accuracy 50%; exact-line accuracy 50%; average EV loss 0.4 BB; Last 1 hand vs previous 1: action accuracy change +100 percentage points, exact-line accuracy change +100 percentage points, average EV loss change -0.4 BB",
    });
    expect(showEngineHands).toBeEnabled();
    expect(within(showEngineHands).getByText("Action 50%")).toBeInTheDocument();
    expect(within(showEngineHands).getByText("Exact 50%")).toBeInTheDocument();
    expect(
      within(showEngineHands).getByText("0.4 BB EV loss"),
    ).toBeInTheDocument();
    expect(within(showEngineHands).getAllByText("+100 pts")).toHaveLength(2);
    expect(within(showEngineHands).getByText("-0.4 BB")).toHaveClass(
      "improving",
    );
    const showPostflopHands = within(dialog).getByRole("button", {
      name: "Show 2 hands handled by Postflop solver. Action accuracy 100%; exact-line accuracy 100%; EV loss ungraded",
    });
    expect(showPostflopHands).toBeEnabled();
    expect(
      within(showPostflopHands).getByText("EV ungraded"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Show 1 hand handled by Preflop chart. Action accuracy 100%; exact-line accuracy 100%; EV loss ungraded",
      }),
    ).toBeEnabled();
    const showFallbackHands = within(dialog).getByRole("button", {
      name: "Show 2 hands using fallback: hero position must identify IP or OOP. Action accuracy 50%; exact-line accuracy 50%; average EV loss 0.4 BB; Last 1 hand vs previous 1: action accuracy change +100 percentage points, exact-line accuracy change +100 percentage points, average EV loss change -0.4 BB",
    });
    expect(showFallbackHands).toBeEnabled();
    expect(
      within(showFallbackHands).getByText("Action 50%"),
    ).toBeInTheDocument();
    expect(
      within(showFallbackHands).getByText("Exact 50%"),
    ).toBeInTheDocument();
    expect(
      within(showFallbackHands).getByText("0.4 BB EV loss"),
    ).toBeInTheDocument();
    expect(within(showFallbackHands).getAllByText("+100 pts")).toHaveLength(2);
    expect(within(showFallbackHands).getByText("-0.4 BB")).toHaveClass(
      "improving",
    );

    await user.click(showEngineHands);

    expect(fetchMock().mock.calls[1][0]).toBe(
      `http://localhost:8000/api/training/progress?solver_route_key=${routeKey}`,
    );
    const activeRouteFilter = await within(dialog).findByLabelText(
      "Active solver filter",
    );
    expect(
      within(activeRouteFilter).getByText("Local EV solver"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open engine.png training review",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("Showing 1 newest of 2 engine hands."),
    ).toBeInTheDocument();

    await user.click(
      within(activeRouteFilter).getByRole("button", {
        name: "Clear solver filter",
      }),
    );

    await waitFor(() =>
      expect(
        within(dialog).queryByLabelText("Active solver filter"),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock().mock.calls[2][0]).toBe(
      "http://localhost:8000/api/training/progress",
    );

    const refreshedFallbackHands = within(dialog).getByRole("button", {
      name: "Show 2 hands using fallback: hero position must identify IP or OOP. Action accuracy 50%; exact-line accuracy 50%; average EV loss 0.4 BB; Last 1 hand vs previous 1: action accuracy change +100 percentage points, exact-line accuracy change +100 percentage points, average EV loss change -0.4 BB",
    });
    await waitFor(() => expect(refreshedFallbackHands).toBeEnabled());
    await user.click(refreshedFallbackHands);

    expect(fetchMock().mock.calls[3][0]).toBe(
      `http://localhost:8000/api/training/progress?solver_fallback_key=${fallbackKey}`,
    );
    const activeFilter = await within(dialog).findByLabelText(
      "Active solver filter",
    );
    expect(
      within(activeFilter).getByText("hero position must identify IP or OOP"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open fallback.png training review",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("Showing 1 newest of 2 fallback hands."),
    ).toBeInTheDocument();

    await user.click(
      within(activeFilter).getByRole("button", {
        name: "Clear solver filter",
      }),
    );

    await waitFor(() =>
      expect(
        within(dialog).queryByLabelText("Active solver filter"),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock().mock.calls[4][0]).toBe(
      "http://localhost:8000/api/training/progress",
    );

    const refreshedUnattributedHands = within(dialog).getByRole("button", {
      name: "Show 1 unattributed hand",
    });
    await waitFor(() => expect(refreshedUnattributedHands).toBeEnabled());
    await user.click(refreshedUnattributedHands);

    expect(fetchMock().mock.calls[5][0]).toBe(
      "http://localhost:8000/api/training/progress?solver_unattributed=true",
    );
    const activeUnattributedFilter = await within(dialog).findByLabelText(
      "Active solver filter",
    );
    expect(
      within(activeUnattributedFilter).getByText(
        "Unattributed recommendations",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open legacy.png training review",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("1 training hand has no engine attribution."),
    ).toBeInTheDocument();

    await user.click(
      within(activeUnattributedFilter).getByRole("button", {
        name: "Clear solver filter",
      }),
    );

    await waitFor(() =>
      expect(
        within(dialog).queryByLabelText("Active solver filter"),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock().mock.calls[6][0]).toBe(
      "http://localhost:8000/api/training/progress",
    );
  });

  it("shows entirely unattributed legacy recommendation coverage", async () => {
    const progress = {
      reviewed_hands: 3,
      action_matches: 2,
      exact_matches: 2,
      different_actions: 1,
      needs_review_hands: 1,
      action_accuracy: 2 / 3,
      exact_accuracy: 2 / 3,
      ev_compared_hands: 0,
      average_ev_loss_bb: null,
      solver_coverage: {
        total_hands: 3,
        tracked_hands: 0,
        unattributed_hands: 3,
        fallback_hands: 0,
        fallback_rate: 0,
        routes: [],
        fallback_reasons: [],
      },
      street_summaries: [],
      recent_hands: [],
      review_queue_hands: 0,
      review_queue: [],
    };
    fetchMock().mockResolvedValueOnce(jsonResponse(progress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    expect(
      within(dialog).getByRole("heading", { name: "Solver coverage" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Show 3 unattributed hands",
      }),
    ).toBeEnabled();
  });

  it("suggests a focus street and orders its reviews by EV loss", async () => {
    const lowHand = {
      job_id: "low-job",
      original_filename: "low.png",
      street: "flop" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "fold" as const,
      decision_sizing: null,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "different" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      ev_loss_bb: 0.2,
    };
    const highHand = {
      ...lowHand,
      job_id: "high-job",
      original_filename: "high.png",
      street: "turn" as const,
      recorded_at: "2026-07-20T12:00:00Z",
      ev_loss_bb: 1.4,
    };
    const recentProgress = {
      reviewed_hands: 2,
      action_matches: 0,
      exact_matches: 0,
      different_actions: 2,
      needs_review_hands: 2,
      action_accuracy: 0,
      exact_accuracy: 0,
      ev_compared_hands: 2,
      average_ev_loss_bb: 0.8,
      action_differences: [
        {
          decision_action: "fold" as const,
          recommended_action: "call" as const,
          hands: 2,
          needs_review_hands: 2,
          ev_compared_hands: 2,
          average_ev_loss_bb: 0.8,
        },
      ],
      trend: {
        window_hands: 1,
        recent_action_accuracy: 0,
        previous_action_accuracy: 0,
        action_accuracy_delta: 0,
        recent_exact_accuracy: 0,
        previous_exact_accuracy: 0,
        exact_accuracy_delta: 0,
        recent_ev_compared_hands: 1,
        previous_ev_compared_hands: 1,
        recent_average_ev_loss_bb: 0.2,
        previous_average_ev_loss_bb: 1.4,
        average_ev_loss_delta_bb: -1.2,
      },
      street_summaries: [
        {
          street: "flop" as const,
          reviewed_hands: 1,
          action_matches: 0,
          exact_matches: 0,
          action_accuracy: 0,
          exact_accuracy: 0,
          ev_compared_hands: 1,
          average_ev_loss_bb: 0.2,
        },
        {
          street: "turn" as const,
          reviewed_hands: 1,
          action_matches: 0,
          exact_matches: 0,
          action_accuracy: 0,
          exact_accuracy: 0,
          ev_compared_hands: 1,
          average_ev_loss_bb: 1.4,
        },
      ],
      recent_hands: [lowHand, highHand],
      review_street_counts: { flop: 1, turn: 1 },
      review_queue_hands: 2,
      review_queue: [lowHand, highHand],
    };
    const focusedProgress = {
      ...recentProgress,
      review_queue_hands: 1,
      review_queue: [highHand],
    };
    const pendingStreet = deferredResponse();
    const pendingOrder = deferredResponse();
    const highJob = {
      ...recommendedJob(),
      id: "high-job",
      original_filename: "high.png",
      training_decision: {
        action: "fold" as const,
        sizing: null,
        recorded_at: highHand.recorded_at,
      },
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(recentProgress))
      .mockResolvedValueOnce(jsonResponse(recentProgress))
      .mockResolvedValueOnce(jsonResponse(recentProgress))
      .mockReturnValueOnce(pendingStreet.promise)
      .mockReturnValueOnce(pendingOrder.promise)
      .mockResolvedValueOnce(jsonResponse(highJob));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    const trend = within(dialog).getByRole("region", { name: "Recent trend" });
    expect(within(trend).getByText("Last 1 vs previous 1")).toBeInTheDocument();
    expect(within(trend).getByText("0.2 BB")).toBeInTheDocument();
    expect(within(trend).getByText("-1.2 BB")).toHaveClass("improving");
    const differences = within(dialog).getByRole("region", {
      name: "Common differences",
    });
    expect(within(differences).getByText("Fold")).toBeInTheDocument();
    expect(within(differences).getByText("Call")).toBeInTheDocument();
    expect(within(differences).getByText("2 hands")).toBeInTheDocument();
    expect(
      within(differences).getByText("0.8 BB avg loss"),
    ).toBeInTheDocument();
    const reviewFoldToCall = within(differences).getByRole("button", {
      name: "Review Fold to Call differences (2)",
    });
    expect(reviewFoldToCall).toHaveTextContent("2");
    await user.click(reviewFoldToCall);
    expect(
      await within(dialog).findByLabelText("Active action-difference filter"),
    ).toHaveTextContent("FoldCall");
    expect(
      within(dialog).getByText(
        "2 pending review hands for Fold to Call across all streets.",
      ),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?review_decision_action=fold&review_recommended_action=call",
    );

    await user.click(
      within(dialog).getByRole("button", {
        name: "Clear action-difference filter",
      }),
    );
    await waitFor(() =>
      expect(
        within(dialog).queryByLabelText("Active action-difference filter"),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock().mock.calls[2][0]).toBe(
      "http://localhost:8000/api/training/progress",
    );

    await user.click(within(dialog).getByRole("button", { name: "Recent" }));
    await user.click(
      within(dialog).getByRole("button", { name: /Focus turn reviews/ }),
    );

    expect(
      within(dialog).getByText("Updating review queue..."),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", {
        name: "Open low.png training review",
      }),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", {
        name: "Open high.png training review",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock().mock.calls[3][0]).toBe(
      "http://localhost:8000/api/training/progress?review_street=turn",
    );

    pendingStreet.resolve(jsonResponse(focusedProgress));
    await waitFor(() =>
      expect(within(dialog).getByLabelText("Review street")).toHaveValue(
        "turn",
      ),
    );
    const reviewOrderSelect = within(dialog).getByLabelText("Review order");
    expect(reviewOrderSelect.parentElement).toHaveClass("select-control");
    expect(reviewOrderSelect.closest("label")?.firstElementChild).toHaveClass(
      "training-review-order-label",
    );
    expect(
      within(dialog).getByText("1 pending review hand on turn."),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", {
        name: "Open low.png training review",
      }),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open high.png training review",
      }),
    ).toBeEnabled();

    await user.selectOptions(reviewOrderSelect, "ev_loss");
    const reviewHighestLoss = within(dialog).getByRole("button", {
      name: "Review highest loss",
    });
    expect(reviewHighestLoss).toBeDisabled();
    expect(
      within(dialog).getByText("Updating review queue..."),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[4][0]).toBe(
      "http://localhost:8000/api/training/progress?review_order=ev_loss&review_street=turn",
    );

    pendingOrder.resolve(jsonResponse(focusedProgress));
    await waitFor(() => expect(reviewHighestLoss).toBeEnabled());
    expect(within(dialog).getByLabelText("Review order")).toHaveValue(
      "ev_loss",
    );
    await user.click(reviewHighestLoss);

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Training progress" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByAltText("Uploaded poker table screenshot"),
    ).toHaveAttribute("src", "http://localhost:8000/api/jobs/high-job/image");
    expect(fetchMock().mock.calls[5][0]).toBe(
      "http://localhost:8000/api/jobs/high-job",
    );
  });

  it("opens pending reviews from a certainty calibration row", async () => {
    const highHand = {
      job_id: "high-certainty-job",
      original_filename: "high-certainty.png",
      street: "turn" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "fold" as const,
      decision_sizing: null,
      decision_certainty: "high" as const,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "different" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: 0.8,
    };
    const certaintyTrend = {
      window_hands: 1,
      recent_action_accuracy: 0,
      previous_action_accuracy: 1,
      action_accuracy_delta: -1,
      recent_exact_accuracy: 0,
      previous_exact_accuracy: 1,
      exact_accuracy_delta: -1,
      recent_ev_compared_hands: 1,
      previous_ev_compared_hands: 1,
      recent_average_ev_loss_bb: 0.8,
      previous_average_ev_loss_bb: 0,
      average_ev_loss_delta_bb: 0.8,
    };
    const progress = {
      reviewed_hands: 2,
      action_matches: 1,
      exact_matches: 1,
      different_actions: 1,
      needs_review_hands: 1,
      action_accuracy: 0.5,
      exact_accuracy: 0.5,
      ev_compared_hands: 2,
      average_ev_loss_bb: 0.4,
      certainty_summaries: [
        {
          certainty: "high" as const,
          hands: 2,
          action_matches: 1,
          exact_matches: 1,
          needs_review_hands: 1,
          action_accuracy: 0.5,
          exact_accuracy: 0.5,
          ev_compared_hands: 2,
          average_ev_loss_bb: 0.4,
          trend: certaintyTrend,
        },
      ],
      street_summaries: [],
      recent_hands: [highHand],
      review_queue_hands: 1,
      review_queue: [highHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(progress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    const renderedCertaintyTrend = within(dialog).getByLabelText(
      "Last 1 hand vs previous 1: action accuracy change -100 percentage points, exact-line accuracy change -100 percentage points, average EV loss change +0.8 BB",
    );
    expect(
      within(renderedCertaintyTrend).getAllByText("-100 pts"),
    ).toHaveLength(2);
    expect(within(renderedCertaintyTrend).getByText("+0.8 BB")).toHaveClass(
      "declining",
    );
    const shortcut = within(dialog).getByRole("button", {
      name: "Review high certainty differences (1)",
    });
    expect(shortcut).toBeEnabled();

    await user.click(shortcut);

    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?review_certainty=high",
    );
    expect(
      await within(dialog).findByLabelText("Review certainty"),
    ).toHaveValue("high");
    expect(
      within(dialog).getByRole("button", { name: "Needs review 1" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(dialog).getByText(
        "1 pending review hand across all streets with high certainty.",
      ),
    ).toBeInTheDocument();
  });

  it("suggests the highest-loss certainty review focus", async () => {
    const lowHand = {
      job_id: "low-certainty-job",
      original_filename: "low-certainty.png",
      street: "turn" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "fold" as const,
      decision_sizing: null,
      decision_certainty: "low" as const,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "different" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: 1.2,
    };
    const highHand = {
      ...lowHand,
      job_id: "high-certainty-job",
      original_filename: "high-certainty.png",
      decision_certainty: "high" as const,
      recorded_at: "2026-07-20T12:00:00Z",
      ev_loss_bb: 0.4,
    };
    const progress = {
      reviewed_hands: 3,
      action_matches: 0,
      exact_matches: 0,
      different_actions: 3,
      needs_review_hands: 3,
      action_accuracy: 0,
      exact_accuracy: 0,
      ev_compared_hands: 3,
      average_ev_loss_bb: 0.67,
      certainty_summaries: [
        {
          certainty: "low" as const,
          hands: 1,
          action_matches: 0,
          exact_matches: 0,
          needs_review_hands: 1,
          action_accuracy: 0,
          exact_accuracy: 0,
          ev_compared_hands: 1,
          average_ev_loss_bb: 1.2,
        },
        {
          certainty: "high" as const,
          hands: 2,
          action_matches: 0,
          exact_matches: 0,
          needs_review_hands: 2,
          action_accuracy: 0,
          exact_accuracy: 0,
          ev_compared_hands: 2,
          average_ev_loss_bb: 0.4,
        },
      ],
      unrated_hands: 0,
      unrated_needs_review_hands: 0,
      street_summaries: [],
      recent_hands: [lowHand, highHand],
      review_queue_hands: 3,
      review_queue: [lowHand, highHand],
    };
    const focusedProgress = {
      ...progress,
      review_queue_hands: 1,
      review_queue: [lowHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(focusedProgress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    const focus = within(dialog).getByRole("button", {
      name: "Focus low certainty reviews: Highest average EV loss: 1.2 BB",
    });
    expect(focus).toHaveTextContent("Focus Low");

    await user.click(focus);

    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?review_certainty=low",
    );
    expect(
      await within(dialog).findByLabelText("Review certainty"),
    ).toHaveValue("low");
    expect(
      within(dialog).getByText(
        "1 pending review hand across all streets with low certainty.",
      ),
    ).toBeInTheDocument();
  });

  it("drills into rated and unrated certainty hands", async () => {
    const highHand = {
      job_id: "high-certainty-job",
      original_filename: "high-certainty.png",
      street: "turn" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "call" as const,
      decision_sizing: null,
      decision_certainty: "high" as const,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "match" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: 0,
    };
    const unratedHand = {
      ...highHand,
      job_id: "unrated-job",
      original_filename: "unrated.png",
      decision_certainty: null,
      recorded_at: "2026-07-20T12:00:00Z",
    };
    const progress = {
      reviewed_hands: 3,
      action_matches: 3,
      exact_matches: 3,
      different_actions: 0,
      needs_review_hands: 0,
      action_accuracy: 1,
      exact_accuracy: 1,
      ev_compared_hands: 3,
      average_ev_loss_bb: 0,
      certainty_summaries: [
        {
          certainty: "high" as const,
          hands: 2,
          action_matches: 2,
          exact_matches: 2,
          needs_review_hands: 0,
          action_accuracy: 1,
          exact_accuracy: 1,
          ev_compared_hands: 2,
          average_ev_loss_bb: 0,
        },
      ],
      unrated_hands: 1,
      unrated_needs_review_hands: 0,
      street_summaries: [],
      recent_matching_hands: 3,
      recent_hands: [highHand, unratedHand],
      review_queue_hands: 0,
      review_queue: [],
    };
    const highProgress = {
      ...progress,
      recent_matching_hands: 2,
      recent_hands: [highHand],
    };
    const unratedProgress = {
      ...progress,
      recent_matching_hands: 1,
      recent_hands: [unratedHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(highProgress))
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(unratedProgress))
      .mockResolvedValueOnce(jsonResponse(progress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: "Show 2 hands rated high certainty",
      }),
    );

    const highFilter = await within(dialog).findByLabelText(
      "Active certainty filter",
    );
    expect(within(highFilter).getByText("High")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Showing 1 newest of 2 High hands."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open high-certainty.png training review",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", {
        name: "Open unrated.png training review",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?recent_certainty=high",
    );

    await user.click(
      within(highFilter).getByRole("button", {
        name: "Clear certainty filter",
      }),
    );
    await waitFor(() =>
      expect(
        within(dialog).queryByLabelText("Active certainty filter"),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock().mock.calls[2][0]).toBe(
      "http://localhost:8000/api/training/progress",
    );

    await user.click(
      within(dialog).getByRole("button", {
        name: "Show 1 unrated hand",
      }),
    );

    const unratedFilter = await within(dialog).findByLabelText(
      "Active certainty filter",
    );
    expect(within(unratedFilter).getByText("Unrated")).toBeInTheDocument();
    expect(
      within(dialog).getByText("1 training hand has no certainty rating."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open unrated.png training review",
      }),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[3][0]).toBe(
      "http://localhost:8000/api/training/progress?recent_certainty=unrated",
    );

    await user.click(
      within(unratedFilter).getByRole("button", {
        name: "Clear certainty filter",
      }),
    );
    await waitFor(() =>
      expect(
        within(dialog).queryByLabelText("Active certainty filter"),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock().mock.calls[4][0]).toBe(
      "http://localhost:8000/api/training/progress",
    );
  });

  it("surfaces legacy unrated hands without treating them as calibrated", async () => {
    const unratedHand = {
      job_id: "unrated-job",
      original_filename: "unrated.png",
      street: "river" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "fold" as const,
      decision_sizing: null,
      decision_certainty: null,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "different" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: null,
    };
    const progress = {
      reviewed_hands: 1,
      action_matches: 0,
      exact_matches: 0,
      different_actions: 1,
      needs_review_hands: 1,
      action_accuracy: 0,
      exact_accuracy: 0,
      ev_compared_hands: 0,
      average_ev_loss_bb: null,
      certainty_summaries: [],
      unrated_hands: 1,
      unrated_needs_review_hands: 1,
      street_summaries: [],
      recent_hands: [unratedHand],
      review_queue_hands: 1,
      review_queue: [unratedHand],
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(progress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    expect(
      within(dialog).getByRole("button", {
        name: "Focus unrated reviews: 1 legacy hand needs review",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("row", {
        name: "Unrated 1 — — — 1",
      }),
    ).toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", {
        name: "Review unrated differences (1)",
      }),
    );

    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?review_certainty=unrated",
    );
    expect(
      await within(dialog).findByLabelText("Review certainty"),
    ).toHaveValue("unrated");
    expect(
      within(dialog).getByText(
        "1 pending review hand across all streets without a certainty rating.",
      ),
    ).toBeInTheDocument();
  });

  it("filters and continues training reviews by decision certainty", async () => {
    const highHand = {
      job_id: "high-certainty-job",
      original_filename: "high-certainty.png",
      street: "flop" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "fold" as const,
      decision_sizing: null,
      decision_certainty: "high" as const,
      recommended_action: "raise" as const,
      recommended_sizing: 7.5,
      outcome: "different" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: 1.1,
    };
    const unratedHand = {
      ...highHand,
      job_id: "unrated-job",
      original_filename: "unrated.png",
      decision_certainty: null,
      recorded_at: "2026-07-20T12:00:00Z",
      ev_loss_bb: 0.2,
    };
    const progress = {
      reviewed_hands: 2,
      action_matches: 0,
      exact_matches: 0,
      different_actions: 2,
      needs_review_hands: 2,
      action_accuracy: 0,
      exact_accuracy: 0,
      ev_compared_hands: 2,
      average_ev_loss_bb: 0.65,
      street_summaries: [],
      recent_hands: [highHand, unratedHand],
      review_queue_hands: 2,
      review_queue: [highHand, unratedHand],
    };
    const highProgress = {
      ...progress,
      review_queue_hands: 1,
      review_queue: [highHand],
    };
    const completedProgress = {
      ...progress,
      needs_review_hands: 1,
      review_queue_hands: 0,
      review_queue: [],
    };
    const highJob = recommendedJob();
    highJob.id = highHand.job_id;
    highJob.original_filename = highHand.original_filename;
    highJob.training_decision = {
      action: "fold",
      sizing: null,
      certainty: "high",
      recorded_at: highHand.recorded_at,
    };
    const reviewedHighJob = {
      ...highJob,
      training_reviewed_at: "2026-07-20T14:00:00Z",
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(highProgress))
      .mockResolvedValueOnce(jsonResponse(highJob))
      .mockResolvedValueOnce(jsonResponse(reviewedHighJob))
      .mockResolvedValueOnce(jsonResponse(completedProgress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    await user.click(
      within(dialog).getByRole("button", { name: "Needs review 2" }),
    );
    await user.selectOptions(
      within(dialog).getByLabelText("Review certainty"),
      "high",
    );

    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/training/progress?review_certainty=high",
    );
    expect(
      await within(dialog).findByText(
        "1 pending review hand across all streets with high certainty.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Open high-certainty.png training review",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", {
        name: "Open unrated.png training review",
      }),
    ).not.toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", { name: "Review next" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Mark reviewed & next" }),
    );

    const completedDialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    expect(
      within(completedDialog).getByLabelText("Review certainty"),
    ).toHaveValue("high");
    expect(
      within(completedDialog).getByText(
        "No pending review hands across all streets with high certainty.",
      ),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[4][0]).toBe(
      "http://localhost:8000/api/training/progress?review_certainty=high",
    );
  });

  it("falls back to action accuracy when suggesting an ungraded focus street", async () => {
    const hand = {
      job_id: "focus-job",
      original_filename: "focus.png",
      street: "flop" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "fold" as const,
      decision_sizing: null,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "different" as const,
      recorded_at: "2026-07-20T13:00:00Z",
      reviewed_at: null,
      ev_loss_bb: null,
    };
    fetchMock().mockResolvedValueOnce(
      jsonResponse({
        reviewed_hands: 3,
        action_matches: 1,
        exact_matches: 1,
        different_actions: 2,
        needs_review_hands: 2,
        action_accuracy: 1 / 3,
        exact_accuracy: 1 / 3,
        ev_compared_hands: 0,
        average_ev_loss_bb: null,
        trend: {
          window_hands: 1,
          recent_action_accuracy: 1,
          previous_action_accuracy: 0,
          action_accuracy_delta: 1,
          recent_exact_accuracy: 1,
          previous_exact_accuracy: 0,
          exact_accuracy_delta: 1,
          recent_ev_compared_hands: 0,
          previous_ev_compared_hands: 0,
          recent_average_ev_loss_bb: null,
          previous_average_ev_loss_bb: null,
          average_ev_loss_delta_bb: null,
        },
        street_summaries: [
          {
            street: "flop",
            reviewed_hands: 2,
            action_matches: 0,
            exact_matches: 0,
            action_accuracy: 0,
            exact_accuracy: 0,
            ev_compared_hands: 0,
            average_ev_loss_bb: null,
          },
          {
            street: "turn",
            reviewed_hands: 1,
            action_matches: 1,
            exact_matches: 1,
            action_accuracy: 1,
            exact_accuracy: 1,
            ev_compared_hands: 0,
            average_ev_loss_bb: null,
          },
        ],
        recent_hands: [hand],
        review_street_counts: { flop: 1, turn: 1 },
        review_queue_hands: 2,
        review_queue: [hand],
      }),
    );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    const trend = within(dialog).getByRole("region", { name: "Recent trend" });

    expect(
      within(dialog).getByRole("button", {
        name: "Focus flop reviews: Lowest action match: 0%",
      }),
    ).toBeInTheDocument();
    expect(within(trend).getAllByText("+100 pts")[0]).toHaveClass("improving");
    expect(within(trend).queryByText("Avg EV loss")).not.toBeInTheDocument();
  });

  it("reopens a completed review from recent training decisions", async () => {
    const trainingDecision = {
      action: "call" as const,
      sizing: null,
      recorded_at: "2026-07-20T12:00:00Z",
    };
    const reviewedAt = "2026-07-20T12:05:00Z";
    const reviewedHand = {
      job_id: "review-job",
      original_filename: "review.png",
      street: "turn" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "call" as const,
      decision_sizing: null,
      recommended_action: "raise" as const,
      recommended_sizing: 7.5,
      outcome: "different" as const,
      recorded_at: trainingDecision.recorded_at,
      reviewed_at: reviewedAt,
    };
    const reopenedHand = { ...reviewedHand, reviewed_at: null };
    const reviewedProgress = {
      reviewed_hands: 1,
      action_matches: 0,
      exact_matches: 0,
      different_actions: 1,
      needs_review_hands: 0,
      action_accuracy: 0,
      exact_accuracy: 0,
      street_summaries: [],
      recent_hands: [reviewedHand],
      review_queue: [],
    };
    const reopenedProgress = {
      ...reviewedProgress,
      needs_review_hands: 1,
      recent_hands: [reopenedHand],
      review_queue: [reopenedHand],
    };
    const reviewedJob = {
      ...recommendedJob(),
      id: "review-job",
      original_filename: "review.png",
      training_decision: trainingDecision,
      training_reviewed_at: reviewedAt,
    };
    const reopenedJob = {
      ...reviewedJob,
      training_reviewed_at: null,
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(reviewedProgress))
      .mockResolvedValueOnce(jsonResponse(reviewedJob))
      .mockResolvedValueOnce(jsonResponse(reopenedJob))
      .mockResolvedValueOnce(jsonResponse(reopenedProgress));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    expect(within(dialog).getByText("Reviewed")).toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", {
        name: "Reopen review.png training review",
      }),
    );

    expect(
      await within(dialog).findByRole("button", { name: "Needs review 1" }),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Different action")).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", {
        name: "Reopen review.png training review",
      }),
    ).not.toBeInTheDocument();
    expect(
      await screen.findByText("Training review reopened"),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/jobs/review-job",
    );
    expect(fetchMock().mock.calls[2][0]).toBe(
      "http://localhost:8000/api/jobs/review-job/training-review",
    );
    expect(fetchMock().mock.calls[2][1]).toMatchObject({ method: "DELETE" });
    expect(fetchMock().mock.calls[3][0]).toBe(
      "http://localhost:8000/api/training/progress",
    );
  });

  it("reconciles a lost progress-dialog reopen response", async () => {
    const jobId = "6".repeat(32);
    const reviewedAt = "2026-07-20T12:05:00Z";
    const trainingDecision = {
      action: "call" as const,
      sizing: null,
      certainty: "medium" as const,
      recorded_at: "2026-07-20T12:00:00Z",
    };
    const reviewedJob = {
      ...recommendedJob(),
      id: jobId,
      original_filename: "progress-reopen-lost.png",
      training_decision: trainingDecision,
      training_reviewed_at: reviewedAt,
      training_review_note: "Review this spot again.",
      updated_at: reviewedAt,
    };
    const reopenedJob = {
      ...reviewedJob,
      training_reviewed_at: null,
      training_review_note: null,
      updated_at: "2026-07-20T12:10:00Z",
    };
    const reviewedHand = {
      job_id: jobId,
      original_filename: reviewedJob.original_filename,
      street: "turn" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "call" as const,
      decision_sizing: null,
      recommended_action: "raise" as const,
      recommended_sizing: 7.5,
      outcome: "different" as const,
      recorded_at: trainingDecision.recorded_at,
      reviewed_at: reviewedAt,
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([reviewedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          reviewed_hands: 1,
          action_matches: 0,
          exact_matches: 0,
          different_actions: 1,
          needs_review_hands: 0,
          action_accuracy: 0,
          exact_accuracy: 0,
          street_summaries: [],
          recent_hands: [reviewedHand],
          review_queue: [],
        }),
      )
      .mockRejectedValueOnce(
        new TypeError("Connection lost after progress reopen"),
      )
      .mockResolvedValueOnce(
        processingQueueResponse(
          [reopenedJob],
          "progress-reopen-persisted-snapshot",
        ),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: "Reopen progress-reopen-lost.png training review",
      }),
    );

    expect(
      await screen.findByText("Connection lost after progress reopen"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([reopenedJob]),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");

    firstRender.unmount();
    render(<App />);

    const comparison = await screen.findByLabelText(
      "Training decision comparison",
    );
    expect(
      within(comparison).getByRole("button", {
        name: "Mark reviewed",
      }),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/training/progress",
      `http://localhost:8000/api/jobs/${jobId}/training-review`,
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("keeps completed review notes available in a dedicated lessons view", async () => {
    const recentHand = {
      job_id: "recent-job",
      original_filename: "recent.png",
      street: "flop" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "call" as const,
      decision_sizing: null,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "match" as const,
      recorded_at: "2026-07-20T12:00:00Z",
      reviewed_at: null,
      review_note: null,
      ev_loss_bb: null,
    };
    const lessonHand = {
      job_id: "lesson-job",
      original_filename: "lesson.png",
      street: "turn" as const,
      hero_cards: canonicalState().hero_cards,
      decision_action: "fold" as const,
      decision_sizing: null,
      recommended_action: "call" as const,
      recommended_sizing: null,
      outcome: "different" as const,
      recorded_at: "2026-07-19T12:00:00Z",
      reviewed_at: "2026-07-20T14:00:00Z",
      review_note: "Count the bluff combinations before folding.",
      ev_loss_bb: 0.5,
    };
    const olderLessonHand = {
      ...lessonHand,
      job_id: "older-lesson-job",
      original_filename: "older-lesson.png",
      recorded_at: "2026-07-18T12:00:00Z",
      reviewed_at: "2026-07-19T14:00:00Z",
      review_note: "Use the pot odds before choosing a line.",
      ev_loss_bb: 2,
    };
    const progress = {
      reviewed_hands: 3,
      action_matches: 1,
      exact_matches: 1,
      different_actions: 2,
      needs_review_hands: 0,
      action_accuracy: 1 / 3,
      exact_accuracy: 1 / 3,
      ev_compared_hands: 0,
      average_ev_loss_bb: null,
      street_summaries: [],
      recent_hands: [recentHand],
      lesson_count: 2,
      lesson_matching_hands: 2,
      lesson_hands: [lessonHand, olderLessonHand],
      review_queue_hands: 0,
      review_queue: [],
    };
    const turnProgress = {
      ...progress,
      lesson_matching_hands: 1,
      lesson_hands: [lessonHand],
    };
    const evOrderedProgress = {
      ...progress,
      lesson_hands: [olderLessonHand, lessonHand],
    };
    const lessonJob = {
      ...recommendedJob(),
      id: "lesson-job",
      original_filename: "lesson.png",
      training_decision: {
        action: "fold" as const,
        sizing: null,
        certainty: "high" as const,
        recorded_at: lessonHand.recorded_at,
      },
      training_reviewed_at: lessonHand.reviewed_at,
      training_review_note: lessonHand.review_note,
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(progress))
      .mockResolvedValueOnce(jsonResponse(evOrderedProgress))
      .mockResolvedValueOnce(jsonResponse(turnProgress))
      .mockResolvedValueOnce(jsonResponse(turnProgress))
      .mockResolvedValueOnce(jsonResponse(lessonJob));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Training progress" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Training progress",
    });
    await user.click(within(dialog).getByRole("button", { name: "Lessons 2" }));

    expect(
      within(dialog).getByRole("heading", { name: "Saved lessons" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("2 saved lesson notes."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Note: Count the bluff combinations before folding.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Note: Use the pot odds before choosing a line.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText("recent.png")).not.toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", {
        name: "Reopen lesson.png training review",
      }),
    ).not.toBeInTheDocument();

    await user.selectOptions(
      within(dialog).getByLabelText("Lesson order"),
      "ev_loss",
    );

    await waitFor(() =>
      expect(fetchMock().mock.calls[1][0]).toBe(
        "http://localhost:8000/api/training/progress?lesson_order=ev_loss",
      ),
    );
    expect(
      within(dialog).getAllByRole("button", {
        name: /Open .* training review/,
      })[0],
    ).toHaveAccessibleName("Open older-lesson.png training review");

    await user.selectOptions(
      within(dialog).getByLabelText("Lesson street"),
      "turn",
    );

    await waitFor(() =>
      expect(fetchMock().mock.calls[2][0]).toBe(
        "http://localhost:8000/api/training/progress?lesson_order=ev_loss&lesson_street=turn",
      ),
    );
    expect(
      within(dialog).getByText("1 lesson note matches these filters."),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByText(
        "Note: Use the pot odds before choosing a line.",
      ),
    ).not.toBeInTheDocument();

    await user.type(
      within(dialog).getByLabelText("Search saved lesson notes"),
      "bluff",
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Apply lesson search" }),
    );

    await waitFor(() =>
      expect(fetchMock().mock.calls[3][0]).toBe(
        "http://localhost:8000/api/training/progress?lesson_order=ev_loss&lesson_street=turn&lesson_query=bluff",
      ),
    );
    expect(
      within(dialog).getByText(
        "Note: Count the bluff combinations before folding.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("link", { name: "Export lessons" }),
    ).toHaveAttribute(
      "href",
      "http://localhost:8000/api/training/lessons/export?lesson_order=ev_loss&lesson_street=turn&lesson_query=bluff",
    );
    expect(
      within(dialog).getByRole("link", { name: "Export lessons" }),
    ).toHaveAttribute("download", "poker-hero-lessons.md");

    await user.click(
      within(dialog).getByRole("button", {
        name: "Open lesson.png training review",
      }),
    );

    expect(fetchMock().mock.calls[4][0]).toBe(
      "http://localhost:8000/api/jobs/lesson-job",
    );
    expect(
      await screen.findByLabelText("Saved training review note"),
    ).toHaveTextContent("Count the bluff combinations before folding.");
    expect(
      screen.getByRole("button", { name: "Reopen review" }),
    ).toBeInTheDocument();
  });
});
