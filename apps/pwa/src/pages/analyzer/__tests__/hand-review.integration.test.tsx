import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { DetectedState } from "../../../shared/types/poker";
import type { RecommendationResult } from "../../../shared/types/recommendations";
import {
  AnalyzerTestApp as App,
  approvedJob,
  canonicalState,
  deferredResponse,
  detectedState,
  fetchMock,
  jobRecord,
  jsonResponse,
  processingQueueResponse,
  recommendation,
  recommendedJob,
  uploadScreenshot,
} from "../../../test/analyzerHarness";

describe("Analyzer hand review", () => {
  it("clears stale recommendation access after edits until the current form is re-approved", async () => {
    const editedState = canonicalState({ pot_size: 18 });
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()))
      .mockResolvedValueOnce(jsonResponse(recommendedJob()))
      .mockResolvedValueOnce(jsonResponse(approvedJob(editedState)))
      .mockResolvedValueOnce(jsonResponse(recommendedJob(editedState)));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(
      await screen.findByRole("button", { name: "Approve state" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Request recommendation" }),
      ).toBeEnabled(),
    );

    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );
    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Request recommendation" }),
    ).toBeDisabled();

    const potInput = screen.getByLabelText(/Pot/);
    await user.clear(potInput);
    await user.type(potInput, "18");

    expect(screen.queryByLabelText("Recommendation")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Request recommendation" }),
    ).toBeDisabled();
    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );
    expect(fetchMock()).toHaveBeenCalledTimes(4);

    await user.click(screen.getByRole("button", { name: "Approve state" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Request recommendation" }),
      ).toBeEnabled(),
    );

    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(6));

    await user.click(screen.getByRole("button", { name: "Reset to parser" }));
    expect(screen.queryByLabelText("Recommendation")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve state" })).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Request recommendation" }),
    ).toBeDisabled();
  });

  it("locks a training answer before reveal and compares it with the recommendation", async () => {
    const trainingDecision = {
      action: "raise" as const,
      sizing: 7.5,
      certainty: "high" as const,
      recorded_at: "2026-07-20T12:00:00Z",
    };
    const decisionJob = {
      ...approvedJob(),
      training_decision: trainingDecision,
    };
    const revealedJob = {
      ...recommendedJob(),
      training_decision: trainingDecision,
    };
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()))
      .mockResolvedValueOnce(jsonResponse(decisionJob))
      .mockResolvedValueOnce(jsonResponse(revealedJob));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(
      await screen.findByRole("button", { name: "Approve state" }),
    );
    const decisionPanel = await screen.findByLabelText(
      "Your training decision",
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "raise" }),
    );
    await user.type(
      within(decisionPanel).getByLabelText("Decision sizing in BB"),
      "7.5",
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "high" }),
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "Lock answer" }),
    );

    expect(
      await within(decisionPanel).findByText("Answer locked"),
    ).toBeInTheDocument();
    expect(
      within(decisionPanel).getByText("Saved before reveal"),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[3][0]).toBe(
      "http://localhost:8000/api/jobs/job-123/decision",
    );
    expect(fetchMock().mock.calls[3][1]).toMatchObject({
      method: "PUT",
      body: JSON.stringify({ action: "raise", sizing: 7.5, certainty: "high" }),
    });

    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );

    const comparison = await screen.findByLabelText(
      "Training decision comparison",
    );
    expect(within(comparison).getByText("Raise 7.5 BB")).toBeInTheDocument();
    expect(within(comparison).getByText("High certainty")).toBeInTheDocument();
    expect(within(comparison).getByText("Matched solver")).toBeInTheDocument();
    expect(
      within(comparison).queryByRole("button", { name: "Mark reviewed" }),
    ).not.toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(5);
  });

  it("rejects a zero-sized wager before locking the training answer", async () => {
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(
      await screen.findByRole("button", { name: "Approve state" }),
    );
    const decisionPanel = await screen.findByLabelText(
      "Your training decision",
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "raise" }),
    );
    await user.type(
      within(decisionPanel).getByLabelText("Decision sizing in BB"),
      "0",
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "Lock answer" }),
    );

    expect(
      await screen.findByText("Enter a valid positive decision size"),
    ).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(3);
  });

  it.each([
    {
      title: "keeps sizing at the match-tolerance boundary reviewable",
      decisionSizing: 7.51,
      expectedLabel: "Same action, different size",
      needsReview: true,
    },
    {
      title: "preserves high-precision sizing below the tolerance",
      decisionSizing: 7.5099999995,
      expectedLabel: "Matched solver",
      needsReview: false,
    },
  ])("$title", async ({ decisionSizing, expectedLabel, needsReview }) => {
    const trainingDecision = {
      action: "raise" as const,
      sizing: decisionSizing,
      certainty: "high" as const,
      recorded_at: "2026-07-20T12:00:00Z",
    };
    const decisionJob = {
      ...approvedJob(),
      training_decision: trainingDecision,
    };
    const revealedJob = {
      ...recommendedJob(),
      training_decision: trainingDecision,
    };
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()))
      .mockResolvedValueOnce(jsonResponse(decisionJob))
      .mockResolvedValueOnce(jsonResponse(revealedJob));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(
      await screen.findByRole("button", { name: "Approve state" }),
    );
    const decisionPanel = await screen.findByLabelText(
      "Your training decision",
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "raise" }),
    );
    await user.type(
      within(decisionPanel).getByLabelText("Decision sizing in BB"),
      String(decisionSizing),
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "high" }),
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "Lock answer" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );

    const comparison = await screen.findByLabelText(
      "Training decision comparison",
    );
    expect(within(comparison).getByText(expectedLabel)).toBeInTheDocument();
    if (needsReview) {
      expect(
        within(comparison).getByRole("button", { name: "Mark reviewed" }),
      ).toBeInTheDocument();
    } else {
      expect(
        within(comparison).queryByRole("button", { name: "Mark reviewed" }),
      ).not.toBeInTheDocument();
    }
  });

  it.each(
    [
      {
        title: "accepts an alternate line at the policy-support boundary",
        frequency: 0.05,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Solver-supported mix",
        hasEvLoss: true,
        includeRecommendedCandidate: true,
        needsReview: false,
      },
      {
        title: "rejects an alternate line below the policy-support boundary",
        frequency: 0.049999,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Different action",
        hasEvLoss: true,
        includeRecommendedCandidate: true,
        needsReview: true,
      },
      {
        title:
          "rejects policy support with malformed frequency but still grades EV",
        frequency: "20%",
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Different action",
        hasEvLoss: true,
        includeRecommendedCandidate: true,
        needsReview: true,
      },
      {
        title:
          "rejects policy support above the frequency maximum but still grades EV",
        frequency: 1.000001,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Different action",
        hasEvLoss: true,
        includeRecommendedCandidate: true,
        needsReview: true,
      },
      {
        title: "accepts policy support at the frequency maximum",
        frequency: 1,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Solver-supported mix",
        hasEvLoss: true,
        includeRecommendedCandidate: true,
        needsReview: false,
      },
      {
        title:
          "rejects policy support without explicit frequency but still grades EV",
        frequency: 0.2,
        includeCandidateFrequency: false,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Different action",
        hasEvLoss: true,
        includeRecommendedCandidate: true,
        needsReview: true,
      },
      {
        title: "rejects an alternate raise without valid sizing",
        frequency: 0.2,
        candidateSizing: null,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Different action",
        hasEvLoss: false,
        includeRecommendedCandidate: true,
        needsReview: true,
      },
      {
        title: "rejects an alternate raise with zero sizing",
        frequency: 0.2,
        candidateSizing: 0,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Different action",
        hasEvLoss: false,
        includeRecommendedCandidate: true,
        needsReview: true,
      },
      {
        title: "does not grade EV when candidates omit the recommended line",
        frequency: 0.2,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Solver-supported mix",
        hasEvLoss: false,
        includeRecommendedCandidate: false,
        needsReview: false,
      },
      {
        title: "does not grade EV when the recommended line omits sizing",
        frequency: 0.2,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Solver-supported mix",
        hasEvLoss: false,
        includeRecommendedCandidate: true,
        includeRecommendedSizing: false,
        needsReview: false,
      },
      {
        title: "does not grade EV when the recommended line has invalid sizing",
        frequency: 0.2,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Solver-supported mix",
        hasEvLoss: false,
        includeRecommendedCandidate: true,
        recommendedCandidateSizing: 2.5,
        needsReview: false,
      },
      {
        title: "grades EV when the recommended line omits frequency",
        frequency: 0.2,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Solver-supported mix",
        hasEvLoss: true,
        includeRecommendedCandidate: true,
        includeRecommendedFrequency: false,
        needsReview: false,
      },
      {
        title: "grades EV when the recommended line has malformed frequency",
        frequency: 0.2,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: 0,
        expectedLabel: "Solver-supported mix",
        hasEvLoss: true,
        includeRecommendedCandidate: true,
        recommendedFrequency: "84%",
        needsReview: false,
      },
      {
        title: "keeps a supported alternate with nonnumeric EV ungraded",
        frequency: 0.2,
        candidateSizing: 8,
        candidateEv: "2.74",
        unrelatedEv: 0,
        expectedLabel: "Solver-supported mix",
        hasEvLoss: false,
        includeRecommendedCandidate: true,
        needsReview: false,
      },
      {
        title:
          "grades valid lines when an unrelated candidate has nonnumeric EV",
        frequency: 0.2,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: "99",
        expectedLabel: "Solver-supported mix",
        hasEvLoss: true,
        includeRecommendedCandidate: true,
        needsReview: false,
      },
      {
        title: "leaves EV ungraded when the recommended line is nonnumeric",
        frequency: 0.2,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedEv: 0,
        recommendedEv: "2.75",
        expectedLabel: "Solver-supported mix",
        hasEvLoss: false,
        includeRecommendedCandidate: true,
        needsReview: false,
      },
      {
        title: "ignores high EV on an unrelated candidate with invalid sizing",
        frequency: 0.2,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedAction: "bet",
        unrelatedEv: 99,
        unrelatedSizing: -1,
        expectedLabel: "Solver-supported mix",
        hasEvLoss: true,
        includeRecommendedCandidate: true,
        needsReview: false,
      },
      {
        title: "ignores high EV on an unrelated candidate with invalid action",
        frequency: 0.2,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedAction: "jam",
        unrelatedEv: 99,
        unrelatedSizing: null,
        expectedLabel: "Solver-supported mix",
        hasEvLoss: true,
        includeRecommendedCandidate: true,
        needsReview: false,
      },
      {
        title: "grades EV candidates without valid frequency metadata",
        frequency: 0.2,
        candidateSizing: 8,
        candidateEv: 2.74,
        unrelatedAction: "bet",
        unrelatedEv: 3,
        unrelatedFrequency: "20%",
        unrelatedSizing: 6,
        expectedEvLoss: "0.26 BB EV loss",
        expectedLabel: "Solver-supported mix",
        hasEvLoss: true,
        includeRecommendedCandidate: true,
        needsReview: false,
      },
    ].map((testCase) => ({
      expectedEvLoss: testCase.hasEvLoss ? "0.01 BB EV loss" : null,
      includeCandidateFrequency: true,
      recommendedEv: 2.75,
      includeRecommendedSizing: true,
      includeRecommendedFrequency: true,
      recommendedFrequency: 0.84,
      recommendedCandidateSizing: null,
      unrelatedAction: "fold",
      unrelatedFrequency: 0.02,
      unrelatedSizing: null,
      ...testCase,
    })),
  )(
    "$title",
    async ({
      frequency,
      candidateSizing,
      candidateEv,
      expectedEvLoss,
      includeCandidateFrequency,
      unrelatedAction,
      unrelatedEv,
      unrelatedFrequency,
      unrelatedSizing,
      recommendedEv,
      expectedLabel,
      includeRecommendedCandidate,
      includeRecommendedSizing,
      includeRecommendedFrequency,
      recommendedFrequency,
      recommendedCandidateSizing,
      needsReview,
    }) => {
      const trainingDecision = {
        action: "raise" as const,
        sizing: 8,
        recorded_at: "2026-07-20T12:00:00Z",
      };
      const alternateCandidate = {
        action: "raise",
        ev: candidateEv,
        ...(includeCandidateFrequency ? { frequency } : {}),
        ...(candidateSizing === null ? {} : { sizing: candidateSizing }),
      };
      const mixedRecommendation: RecommendationResult = {
        action: "call",
        sizing: null,
        confidence: 0.87,
        explanation: "Call most often and mix in a raise.",
        raw: {
          provider: "local_solver",
          engine: "postflop_solver",
          candidates: [
            ...(includeRecommendedCandidate
              ? [
                  {
                    action: "call",
                    ev: recommendedEv,
                    ...(includeRecommendedFrequency
                      ? { frequency: recommendedFrequency }
                      : {}),
                    ...(includeRecommendedSizing
                      ? { sizing: recommendedCandidateSizing }
                      : {}),
                  },
                ]
              : []),
            alternateCandidate,
            {
              action: unrelatedAction,
              sizing: unrelatedSizing,
              ev: unrelatedEv,
              frequency: unrelatedFrequency,
            },
          ],
        },
      };
      const created = jobRecord();
      fetchMock()
        .mockResolvedValueOnce(jsonResponse(created, 201))
        .mockResolvedValueOnce(processingQueueResponse([created]))
        .mockResolvedValueOnce(jsonResponse(approvedJob()))
        .mockResolvedValueOnce(
          jsonResponse({
            ...approvedJob(),
            training_decision: trainingDecision,
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            ...recommendedJob(),
            training_decision: trainingDecision,
            recommendation: mixedRecommendation,
          }),
        );
      render(<App />);

      const user = await uploadScreenshot();
      await user.click(
        await screen.findByRole("button", { name: "Approve state" }),
      );
      const decisionPanel = await screen.findByLabelText(
        "Your training decision",
      );
      await user.click(
        within(decisionPanel).getByRole("button", { name: "raise" }),
      );
      await user.type(
        within(decisionPanel).getByLabelText("Decision sizing in BB"),
        "8",
      );
      await user.click(
        screen.getByRole("button", { name: "Request recommendation" }),
      );

      const comparison = await screen.findByLabelText(
        "Training decision comparison",
      );
      expect(within(comparison).getByText(expectedLabel)).toBeInTheDocument();
      if (expectedEvLoss !== null) {
        expect(
          within(comparison).getByText(expectedEvLoss),
        ).toBeInTheDocument();
      } else {
        expect(
          within(comparison).queryByText(/BB EV loss/),
        ).not.toBeInTheDocument();
      }
      if (needsReview) {
        expect(
          within(comparison).getByRole("button", { name: "Mark reviewed" }),
        ).toBeInTheDocument();
      } else {
        expect(
          within(comparison).queryByRole("button", { name: "Mark reviewed" }),
        ).not.toBeInTheDocument();
      }
    },
  );

  it.each([
    {
      title: "does not grade EV from only the recommended candidate line",
      candidates: [{ action: "raise", sizing: 8, ev: 1.4, frequency: 1 }],
      expectedEvLoss: null,
    },
    {
      title: "does not grade EV from duplicate recommended candidate lines",
      candidates: [
        { action: "raise", sizing: 8, ev: 1.4, frequency: 1 },
        { action: "raise", sizing: 8.001, ev: 1.3, frequency: 0 },
      ],
      expectedEvLoss: null,
    },
    {
      title:
        "does not grade EV from a large tolerance-equivalent candidate set",
      candidates: Array.from({ length: 1_000 }, (_, index) => ({
        action: "raise",
        sizing: 8 + index / 200_000,
        ev: 1.4,
        frequency: 1,
      })),
      expectedEvLoss: null,
    },
    {
      title: "grades EV from an alternate at the sizing-tolerance boundary",
      candidates: [
        { action: "raise", sizing: 8, ev: 1.4, frequency: 1 },
        { action: "raise", sizing: 8.01, ev: 1.3, frequency: 0 },
      ],
      expectedEvLoss: "0 BB EV loss",
    },
    {
      title: "grades tolerance-bridged lines when the bridge is first",
      candidates: [
        { action: "raise", sizing: 8.009, ev: 1.3, frequency: 0 },
        { action: "raise", sizing: 8, ev: 1.4, frequency: 1 },
        { action: "raise", sizing: 8.018, ev: 1.3, frequency: 0 },
      ],
      expectedEvLoss: "0 BB EV loss",
    },
    {
      title: "grades tolerance-bridged lines when the endpoints are first",
      candidates: [
        { action: "raise", sizing: 8, ev: 1.4, frequency: 1 },
        { action: "raise", sizing: 8.018, ev: 1.3, frequency: 0 },
        { action: "raise", sizing: 8.009, ev: 1.3, frequency: 0 },
      ],
      expectedEvLoss: "0 BB EV loss",
    },
  ])("$title", async ({ candidates, expectedEvLoss }) => {
    const trainingDecision = {
      action: "raise" as const,
      sizing: 8,
      recorded_at: "2026-07-20T12:00:00Z",
    };
    const singleLineRecommendation: RecommendationResult = {
      action: "raise",
      sizing: 8,
      confidence: 0.87,
      explanation: "Raise is the only modeled line.",
      raw: {
        provider: "local_solver",
        engine: "postflop_solver",
        candidates,
      },
    };
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()))
      .mockResolvedValueOnce(
        jsonResponse({
          ...approvedJob(),
          training_decision: trainingDecision,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          ...recommendedJob(),
          training_decision: trainingDecision,
          recommendation: singleLineRecommendation,
        }),
      );
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(
      await screen.findByRole("button", { name: "Approve state" }),
    );
    const decisionPanel = await screen.findByLabelText(
      "Your training decision",
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "raise" }),
    );
    await user.type(
      within(decisionPanel).getByLabelText("Decision sizing in BB"),
      "8",
    );
    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );

    const comparison = await screen.findByLabelText(
      "Training decision comparison",
    );
    expect(within(comparison).getByText("Matched solver")).toBeInTheDocument();
    if (expectedEvLoss) {
      expect(within(comparison).getByText(expectedEvLoss)).toBeInTheDocument();
    } else {
      expect(
        within(comparison).queryByText(/BB EV loss/),
      ).not.toBeInTheDocument();
    }
    expect(
      within(comparison).queryByRole("button", {
        name: "Mark reviewed",
      }),
    ).not.toBeInTheDocument();
  });

  it("marks a differing training decision reviewed", async () => {
    const trainingDecision = {
      action: "call" as const,
      sizing: null,
      recorded_at: "2026-07-20T12:00:00Z",
    };
    const decisionJob = {
      ...approvedJob(),
      training_decision: trainingDecision,
    };
    const revealedJob = {
      ...recommendedJob(),
      training_decision: trainingDecision,
    };
    const completedReviewJob = {
      ...revealedJob,
      training_reviewed_at: "2026-07-20T12:05:00Z",
      training_review_note: "Call needs less equity than the raise.",
    };
    const updatedReviewJob = {
      ...completedReviewJob,
      training_review_note: "Count the bluff combinations before raising.",
    };
    const clearedReviewJob = {
      ...completedReviewJob,
      training_review_note: null,
    };
    const reopenedReviewJob = {
      ...revealedJob,
      training_reviewed_at: null,
      training_review_note: null,
    };
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()))
      .mockResolvedValueOnce(jsonResponse(decisionJob))
      .mockResolvedValueOnce(jsonResponse(revealedJob))
      .mockResolvedValueOnce(jsonResponse(completedReviewJob))
      .mockResolvedValueOnce(jsonResponse(updatedReviewJob))
      .mockResolvedValueOnce(jsonResponse(clearedReviewJob))
      .mockResolvedValueOnce(jsonResponse(reopenedReviewJob));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(
      await screen.findByRole("button", { name: "Approve state" }),
    );
    const decisionPanel = await screen.findByLabelText(
      "Your training decision",
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "call" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );

    const comparison = await screen.findByLabelText(
      "Training decision comparison",
    );
    await user.type(
      screen.getByLabelText("Training review note"),
      "Call needs less equity than the raise.",
    );
    await user.click(
      within(comparison).getByRole("button", { name: "Mark reviewed" }),
    );

    expect(await within(comparison).findByText("Reviewed")).toBeInTheDocument();
    expect(
      within(comparison).queryByRole("button", { name: "Mark reviewed" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByLabelText("Saved training review note"),
    ).toHaveTextContent("Call needs less equity than the raise.");
    expect(
      await screen.findByText("Training review completed"),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[5][0]).toBe(
      "http://localhost:8000/api/jobs/job-123/training-review",
    );
    expect(fetchMock().mock.calls[5][1]).toMatchObject({
      method: "PUT",
      body: JSON.stringify({ note: "Call needs less equity than the raise." }),
    });

    await user.click(
      screen.getByRole("button", { name: "Edit training review note" }),
    );
    const editNote = screen.getByLabelText("Edit training review note");
    expect(
      within(comparison).getByRole("button", { name: "Reopen review" }),
    ).toBeDisabled();
    await user.clear(editNote);
    await user.type(editNote, "Count the bluff combinations before raising.");
    await user.click(screen.getByRole("button", { name: "Save note" }));

    expect(await screen.findByText("Lesson note updated")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Saved training review note"),
    ).toHaveTextContent("Count the bluff combinations before raising.");
    expect(within(comparison).getByText("Reviewed")).toBeInTheDocument();
    expect(fetchMock().mock.calls[6][0]).toBe(
      "http://localhost:8000/api/jobs/job-123/training-review",
    );
    expect(fetchMock().mock.calls[6][1]).toMatchObject({
      method: "PUT",
      body: JSON.stringify({
        note: "Count the bluff combinations before raising.",
      }),
    });

    await user.click(
      screen.getByRole("button", { name: "Edit training review note" }),
    );
    await user.clear(screen.getByLabelText("Edit training review note"));
    await user.click(screen.getByRole("button", { name: "Save note" }));

    expect(await screen.findByText("Lesson note removed")).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Saved training review note"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add lesson note" }),
    ).toBeInTheDocument();
    expect(within(comparison).getByText("Reviewed")).toBeInTheDocument();
    expect(fetchMock().mock.calls[7][0]).toBe(
      "http://localhost:8000/api/jobs/job-123/training-review",
    );
    expect(fetchMock().mock.calls[7][1]).toMatchObject({
      method: "PUT",
      body: JSON.stringify({ note: null }),
    });

    await user.click(
      within(comparison).getByRole("button", { name: "Reopen review" }),
    );

    expect(
      await within(comparison).findByRole("button", { name: "Mark reviewed" }),
    ).toBeInTheDocument();
    expect(within(comparison).queryByText("Reviewed")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Training review note")).toHaveValue("");
    expect(
      await screen.findByText("Training review reopened"),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[8][0]).toBe(
      "http://localhost:8000/api/jobs/job-123/training-review",
    );
    expect(fetchMock().mock.calls[8][1]).toMatchObject({ method: "DELETE" });
  });

  it.each([
    { operation: "complete" as const },
    { operation: "reopen" as const },
    { operation: "note" as const },
  ])(
    "reconciles a lost training-review $operation response",
    async ({ operation }) => {
      const jobId = "2".repeat(32);
      const baseJob = {
        ...recommendedJob(),
        id: jobId,
        original_filename: `${operation}-review-response-lost.png`,
        image_filename: `${jobId}.png`,
        training_decision: {
          action: "call" as const,
          sizing: null,
          certainty: "medium" as const,
          recorded_at: "2026-07-20T12:00:00Z",
        },
        updated_at: "2026-07-20T12:00:00Z",
      };
      const initialJob =
        operation === "complete"
          ? baseJob
          : {
              ...baseJob,
              training_reviewed_at: "2026-07-20T12:05:00Z",
              training_review_note: "Original lesson note.",
            };
      const persistedJob =
        operation === "complete"
          ? {
              ...baseJob,
              training_reviewed_at: "2026-07-20T12:10:00Z",
              training_review_note: "Persisted lesson note.",
              updated_at: "2026-07-20T12:10:00Z",
            }
          : operation === "reopen"
            ? {
                ...baseJob,
                training_reviewed_at: null,
                training_review_note: null,
                updated_at: "2026-07-20T12:10:00Z",
              }
            : {
                ...baseJob,
                training_reviewed_at: "2026-07-20T12:05:00Z",
                training_review_note: "Persisted updated lesson.",
                updated_at: "2026-07-20T12:10:00Z",
              };
      window.localStorage.setItem(
        "poker-training-processing-v1",
        JSON.stringify([initialJob]),
      );
      window.localStorage.setItem("poker-training-processing-total-v1", "1");
      fetchMock()
        .mockRejectedValueOnce(
          new TypeError(`Connection lost after ${operation}`),
        )
        .mockResolvedValueOnce(
          processingQueueResponse(
            [persistedJob],
            `${operation}-review-persisted-snapshot`,
          ),
        );
      const firstRender = render(<App />);
      const user = userEvent.setup();
      const comparison = await screen.findByLabelText(
        "Training decision comparison",
      );

      if (operation === "complete") {
        await user.type(
          screen.getByLabelText("Training review note"),
          "Persisted lesson note.",
        );
        await user.click(
          within(comparison).getByRole("button", {
            name: "Mark reviewed",
          }),
        );
      } else if (operation === "reopen") {
        await user.click(
          within(comparison).getByRole("button", {
            name: "Reopen review",
          }),
        );
      } else {
        await user.click(
          screen.getByRole("button", {
            name: "Edit training review note",
          }),
        );
        const noteInput = screen.getByLabelText("Edit training review note");
        await user.clear(noteInput);
        await user.type(noteInput, "Persisted updated lesson.");
        await user.click(screen.getByRole("button", { name: "Save note" }));
      }

      expect(
        await screen.findByText(`Connection lost after ${operation}`),
      ).toBeInTheDocument();
      await waitFor(() =>
        expect(
          JSON.parse(
            String(window.localStorage.getItem("poker-training-processing-v1")),
          ),
        ).toEqual([persistedJob]),
      );
      if (operation === "reopen") {
        expect(
          await within(comparison).findByRole("button", {
            name: "Mark reviewed",
          }),
        ).toBeInTheDocument();
        expect(screen.getByLabelText("Training review note")).toHaveValue("");
      } else {
        expect(
          await within(comparison).findByText("Reviewed"),
        ).toBeInTheDocument();
        expect(
          screen.getByLabelText("Saved training review note"),
        ).toHaveTextContent(persistedJob.training_review_note ?? "");
      }
      expect(
        window.sessionStorage.getItem("poker-training-processing-synced"),
      ).toBe("true");

      firstRender.unmount();
      render(<App />);

      const restoredComparison = await screen.findByLabelText(
        "Training decision comparison",
      );
      if (operation === "reopen") {
        expect(
          within(restoredComparison).getByRole("button", {
            name: "Mark reviewed",
          }),
        ).toBeInTheDocument();
      } else {
        expect(
          within(restoredComparison).getByText("Reviewed"),
        ).toBeInTheDocument();
        expect(
          screen.getByLabelText("Saved training review note"),
        ).toHaveTextContent(persistedJob.training_review_note ?? "");
      }
      expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
        `http://localhost:8000/api/jobs/${jobId}/training-review`,
        "http://localhost:8000/api/jobs",
      ]);
    },
  );

  it("records a selected answer automatically when recommendation is requested", async () => {
    const trainingDecision = {
      action: "call" as const,
      sizing: null,
      certainty: "medium" as const,
      recorded_at: "2026-07-20T12:00:00Z",
    };
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()))
      .mockResolvedValueOnce(
        jsonResponse({ ...approvedJob(), training_decision: trainingDecision }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          ...recommendedJob(),
          training_decision: trainingDecision,
        }),
      );
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(
      await screen.findByRole("button", { name: "Approve state" }),
    );
    const decisionPanel = await screen.findByLabelText(
      "Your training decision",
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "call" }),
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "medium" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );

    const comparison = await screen.findByLabelText(
      "Training decision comparison",
    );
    expect(within(comparison).getByText("Call")).toBeInTheDocument();
    expect(
      within(comparison).getByText("Medium certainty"),
    ).toBeInTheDocument();
    expect(
      within(comparison).getByText("Different action"),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[3][0]).toBe(
      "http://localhost:8000/api/jobs/job-123/decision",
    );
    expect(fetchMock().mock.calls[3][1]).toMatchObject({
      method: "PUT",
      body: JSON.stringify({
        action: "call",
        sizing: null,
        certainty: "medium",
      }),
    });
    expect(fetchMock().mock.calls[4][0]).toBe(
      "http://localhost:8000/api/jobs/job-123/recommend",
    );
  });

  it("clears an unlocked training answer when the approved state is edited", async () => {
    const editedState = canonicalState({ pot_size: 18 });
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()))
      .mockResolvedValueOnce(jsonResponse(approvedJob(editedState)))
      .mockResolvedValueOnce(jsonResponse(recommendedJob(editedState)));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(
      await screen.findByRole("button", { name: "Approve state" }),
    );
    const originalDecisionPanel = await screen.findByLabelText(
      "Your training decision",
    );
    await user.click(
      within(originalDecisionPanel).getByRole("button", { name: "call" }),
    );
    expect(
      within(originalDecisionPanel).getByRole("button", { name: "call" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(originalDecisionPanel).getByText("Ready to lock"),
    ).toBeInTheDocument();

    const potInput = screen.getByLabelText(/Pot/);
    await user.clear(potInput);
    await user.type(potInput, "18");
    expect(
      screen.queryByLabelText("Your training decision"),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Approve state" }));
    const updatedDecisionPanel = await screen.findByLabelText(
      "Your training decision",
    );
    expect(
      within(updatedDecisionPanel).getByRole("button", { name: "call" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(
      within(updatedDecisionPanel).getByRole("button", { name: "Lock answer" }),
    ).toBeDisabled();

    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );
    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(5);
    expect(fetchMock().mock.calls[4][0]).toBe(
      "http://localhost:8000/api/jobs/job-123/recommend",
    );
  });

  it("displays backend upload errors as queue attention items", async () => {
    const validJob = jobRecord({ original_filename: "valid.png" });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(validJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([validJob]))
      .mockResolvedValueOnce(
        jsonResponse(
          { detail: "Upload must contain supported image data" },
          400,
        ),
      )
      .mockResolvedValueOnce(processingQueueResponse([validJob]));
    render(<App />);

    await uploadScreenshot("valid.png");
    expect(await screen.findByDisplayValue("Ah Kd")).toBeInTheDocument();
    expect(
      screen.getByAltText("Uploaded poker table screenshot"),
    ).toBeInTheDocument();

    await uploadScreenshot("broken.png");

    expect(
      await screen.findByText(
        "1 screenshot need attention. Check the highlighted queue items.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open screenshot 1: valid.png" }),
    ).toBeInTheDocument();
    const failedItem = screen.getByRole("button", {
      name: "Open screenshot 2: broken.png",
    });
    expect(within(failedItem).getByText("error")).toBeInTheDocument();
    expect(
      within(failedItem).getByText("Upload must contain supported image data"),
    ).toBeInTheDocument();
    await waitFor(() => expect(failedItem).toHaveClass("active"));
  });

  it("sends corrected approval payload with user_approved forced true", async () => {
    const correctedState = canonicalState({
      current_bet: 3.5,
      opponent_wager: null,
      facing_action: null,
      action_context: null,
    });
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob(correctedState)));
    render(<App />);

    const user = await uploadScreenshot();
    const currentBetInput = await screen.findByLabelText(/Current bet/);
    await user.clear(currentBetInput);
    await user.type(currentBetInput, "3.5");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const approveOptions = fetchMock().mock.calls[2][1];
    const payload = JSON.parse(String(approveOptions?.body));

    expect(fetchMock().mock.calls[2][0]).toBe(
      "http://localhost:8000/api/jobs/job-123/approve",
    );
    expect(payload.current_bet).toBe(3.5);
    expect(payload.opponent_wager).toBeNull();
    expect(payload.facing_action).toBeNull();
    expect(payload.action_context).toBeNull();
    expect(payload.user_approved).toBe(true);
  });

  it("submits structured opener context for preflop raise states", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 4,
      current_bet: 1.5,
      hero_position: "big blind",
      street: "preflop",
      facing_action: "raise",
      action_context: "Hero faces 1.5 BB to call into a 4 BB pot",
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    const approvedState = canonicalState({
      ...preflopState,
      preflop_opener_position: "button",
      preflop_open_size: 2.5,
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]))
      .mockResolvedValueOnce(jsonResponse(approvedJob(approvedState)));
    render(<App />);

    const user = await uploadScreenshot();
    await user.selectOptions(
      await screen.findByLabelText(/Opener position/),
      "button",
    );
    await user.type(screen.getByLabelText(/Opening size/), "2.5");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.preflop_opener_position).toBe("button");
    expect(payload.preflop_open_size).toBe(2.5);
  });

  it("submits structured preflop history and synchronizes opener context", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 12,
      current_bet: 5.5,
      hero_stack: 97.5,
      effective_stack: 92,
      players_in_hand: 6,
      hero_position: "cutoff",
      street: "preflop",
      facing_action: "raise",
      action_context: "Hero faces a 3-bet",
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(
      screen.getByRole("button", { name: "Add preflop action" }),
    );
    await user.type(screen.getByLabelText("Preflop action 1 amount"), "2.5");
    await user.click(
      screen.getByRole("button", { name: "Add preflop action" }),
    );
    await user.type(screen.getByLabelText("Preflop action 2 amount"), "8");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.preflop_opener_position).toBe("cutoff");
    expect(payload.preflop_open_size).toBe(2.5);
    expect(payload.preflop_action_history).toEqual([
      { actor: "cutoff", action: "raise", amount: 2.5 },
      { actor: "button", action: "raise", amount: 8 },
    ]);
  });

  it("clears stale opener context for call-first structured history", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 6.5,
      current_bet: 3,
      hero_stack: 99,
      effective_stack: 90,
      players_in_hand: 2,
      hero_position: "utg",
      preflop_opener_position: "cutoff",
      preflop_open_size: 2.5,
      preflop_action_history: [
        { actor: "utg", action: "call", amount: 1 },
        { actor: "button", action: "raise", amount: 4 },
      ],
      street: "preflop",
      facing_action: "raise",
      action_context: "Hero limped and faces an isolation raise",
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.preflop_opener_position).toBeNull();
    expect(payload.preflop_open_size).toBeNull();
    expect(payload.preflop_action_history).toEqual([
      { actor: "utg", action: "call", amount: 1 },
      { actor: "button", action: "raise", amount: 4 },
    ]);
  });

  it("loads structured preflop history into editable controls", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 12,
      current_bet: 5.5,
      hero_stack: 97.5,
      effective_stack: 92,
      players_in_hand: 6,
      hero_position: "cutoff",
      preflop_opener_position: "cutoff",
      preflop_open_size: 2.5,
      preflop_action_history: [
        { actor: "cutoff", action: "raise", amount: 2.5 },
        { actor: "button", action: "raise", amount: 8 },
      ],
      street: "preflop",
      facing_action: "raise",
      action_context: "Hero faces a 3-bet",
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]));
    render(<App />);

    await uploadScreenshot();

    expect(await screen.findByLabelText("Preflop action 1 actor")).toHaveValue(
      "cutoff",
    );
    expect(screen.getByLabelText("Preflop action 1 amount")).toHaveValue("2.5");
    expect(screen.getByLabelText("Preflop action 2 actor")).toHaveValue(
      "button",
    );
    expect(screen.getByLabelText("Preflop action 2 amount")).toHaveValue("8");
    expect(screen.queryByLabelText(/Opener position/)).not.toBeInTheDocument();
  });

  it("preserves hidden preflop history when approving a postflop state", async () => {
    const postflopState: DetectedState = {
      ...detectedState,
      opponent_stack: 90,
      preflop_opener_position: "cutoff",
      preflop_open_size: 2.5,
      preflop_action_history: [
        { actor: "cutoff", action: "raise", amount: 2.5 },
        { actor: "button", action: "raise", amount: 8 },
      ],
      facing_action: "raise",
      postflop_action_history: [
        { actor: "oop", action: "bet", amount: 2.5 },
        { actor: "ip", action: "raise", amount: 7.5 },
      ],
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: postflopState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    expect(
      screen.queryByRole("button", { name: "Add preflop action" }),
    ).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/Street/), "turn");
    await user.selectOptions(screen.getByLabelText(/Facing action/), "bet");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.preflop_opener_position).toBe("cutoff");
    expect(payload.preflop_open_size).toBe(2.5);
    expect(payload.preflop_action_history).toEqual([
      { actor: "cutoff", action: "raise", amount: 2.5 },
      { actor: "button", action: "raise", amount: 8 },
    ]);
  });

  it("submits structured postflop history for a raised decision", async () => {
    const raisedState: DetectedState = {
      ...detectedState,
      pot_size: 19,
      current_bet: 5,
      hero_stack: 98,
      effective_stack: 93,
      players_in_hand: 2,
      hero_position: "OOP",
      facing_action: "raise",
      action_context: "Hero bet 2 BB and faces a raise to 7 BB",
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: raisedState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    await user.type(await screen.findByLabelText(/Opponent stack/), "93");
    await user.click(screen.getByRole("button", { name: "Add action" }));
    await user.selectOptions(screen.getByLabelText("Action 1 type"), "bet");
    await user.type(screen.getByLabelText("Action 1 amount"), "2");
    await user.click(screen.getByRole("button", { name: "Add action" }));
    await user.selectOptions(screen.getByLabelText("Action 2 type"), "raise");
    await user.type(screen.getByLabelText("Action 2 amount"), "7");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.opponent_stack).toBe(93);
    expect(payload.postflop_action_history).toEqual([
      { actor: "oop", action: "bet", amount: 2 },
      { actor: "ip", action: "raise", amount: 7 },
    ]);
  });

  it("loads and submits completed street history for a turn decision", async () => {
    const turnState: DetectedState = {
      ...detectedState,
      board_cards: [
        ...detectedState.board_cards,
        { rank: "2", suit: "diamonds" },
      ],
      pot_size: 9.5,
      current_bet: 0,
      hero_stack: 95.5,
      opponent_stack: 95.5,
      effective_stack: 95.5,
      players_in_hand: 2,
      hero_position: "OOP",
      opponent_position: "IP",
      street: "turn",
      facing_action: null,
      completed_postflop_streets: [
        {
          street: "flop",
          actions: [
            { actor: "oop", action: "bet", amount: 2 },
            { actor: "ip", action: "call", amount: 2 },
          ],
        },
      ],
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: turnState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    expect(
      await screen.findByLabelText("Completed action 1 street"),
    ).toHaveValue("flop");
    expect(screen.getByLabelText("Completed action 1 actor")).toHaveValue(
      "oop",
    );
    expect(screen.getByLabelText("Completed action 1 type")).toHaveValue("bet");
    expect(screen.getByLabelText("Completed action 1 amount")).toHaveValue("2");
    expect(screen.getByLabelText("Completed action 2 actor")).toHaveValue("ip");
    expect(screen.getByLabelText("Completed action 2 type")).toHaveValue(
      "call",
    );
    expect(screen.getByLabelText(/Opponent stack/)).toHaveValue("95.5");

    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.completed_postflop_streets).toEqual([
      {
        street: "flop",
        actions: [
          { actor: "oop", action: "bet", amount: 2 },
          { actor: "ip", action: "call", amount: 2 },
        ],
      },
    ]);
  });

  it("adds river history actions to a street with remaining capacity", async () => {
    const riverState: DetectedState = {
      ...detectedState,
      board_cards: [
        ...detectedState.board_cards,
        { rank: "2", suit: "diamonds" },
        { rank: "3", suit: "clubs" },
      ],
      street: "river",
      facing_action: null,
      completed_postflop_streets: [
        {
          street: "flop",
          actions: [
            { actor: "oop", action: "bet", amount: 1 },
            { actor: "ip", action: "raise", amount: 2 },
            { actor: "oop", action: "raise", amount: 3 },
            { actor: "ip", action: "raise", amount: 4 },
            { actor: "oop", action: "raise", amount: 5 },
            { actor: "ip", action: "raise", amount: 6 },
            { actor: "oop", action: "raise", amount: 7 },
            { actor: "ip", action: "call", amount: 7 },
          ],
        },
      ],
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: riverState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(screen.getByRole("button", { name: "Add action" }));

    const addedStreet = screen.getByLabelText("Completed action 9 street");
    expect(addedStreet).toHaveValue("turn");
    expect(
      within(addedStreet).getByRole("option", { name: "Flop" }),
    ).toBeDisabled();
  });

  it("prevents field edits while approval is pending", async () => {
    const pendingApproval = deferredResponse();
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockReturnValueOnce(pendingApproval.promise);
    render(<App />);

    const user = await uploadScreenshot();
    const heroCardsInput = await screen.findByLabelText(/Hero cards/);
    const potInput = screen.getByLabelText(/Pot/);
    const streetSelect = screen.getByLabelText(/Street/);
    const actionContextInput = screen.getByLabelText(/Action context/);

    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(potInput).toBeDisabled());
    expect(heroCardsInput).toBeDisabled();
    expect(streetSelect).toBeDisabled();
    expect(actionContextInput).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Parser benchmark" }),
    ).toBeDisabled();

    await user.type(potInput, "18");
    expect(potInput).toHaveValue("12.5");

    pendingApproval.resolve(jsonResponse(approvedJob()));

    await waitFor(() => expect(potInput).toBeEnabled());
    expect(
      screen.getByRole("button", { name: "Parser benchmark" }),
    ).toBeEnabled();
    expect(potInput).toHaveValue("12.5");
    expect(
      screen.getByRole("button", { name: "Request recommendation" }),
    ).toBeEnabled();
  });
});
