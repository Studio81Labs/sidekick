import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { trainingQueryKeys } from "../../../domains/training/api/trainingQueries";
import { jobRecord } from "../../../test/analyzerHarness";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import {
  completeTrainingReviewCommand,
  recordTrainingDecisionCommand,
  reopenTrainingReviewCommand,
} from "./trainingReviewCommands";

afterEach(resetApiMocks);

function seedAffectedCaches(jobId: string) {
  const queryClient = createQueryClient();
  const job = jobRecord({ id: jobId });
  const processingKey = jobQueryKeys.processingPage(0);
  const historyKey = historyQueryKeys.page();
  const trainingKey = trainingQueryKeys.progress();
  queryClient.setQueryData(jobQueryKeys.detail(jobId), job);
  queryClient.setQueryData(processingKey, { jobs: [job], total: 1 });
  queryClient.setQueryData(historyKey, { jobs: [job], total: 1 });
  queryClient.setQueryData(trainingKey, { reviewed_hands: 0 });
  return { queryClient, job, processingKey, historyKey, trainingKey };
}

function expectSuccessfulCacheOutcome(
  seeded: ReturnType<typeof seedAffectedCaches>,
  updatedJob: ReturnType<typeof jobRecord>,
  outcome: Awaited<ReturnType<typeof recordTrainingDecisionCommand>>,
) {
  expect(outcome).toEqual({
    job: updatedJob,
    cache: {
      updated: jobQueryKeys.detail(updatedJob.id),
      invalidated: [
        jobQueryKeys.processing(),
        historyQueryKeys.all,
        trainingQueryKeys.all,
      ],
    },
  });
  expect(
    seeded.queryClient.getQueryData(jobQueryKeys.detail(updatedJob.id)),
  ).toEqual(updatedJob);
  expect(
    seeded.queryClient.getQueryState(seeded.processingKey)?.isInvalidated,
  ).toBe(true);
  expect(
    seeded.queryClient.getQueryState(seeded.historyKey)?.isInvalidated,
  ).toBe(true);
  expect(
    seeded.queryClient.getQueryState(seeded.trainingKey)?.isInvalidated,
  ).toBe(true);
}

describe("training review commands", () => {
  it("records a decision and returns explicit cache effects", async () => {
    const seeded = seedAffectedCaches("a".repeat(32));
    const updatedJob = jobRecord({
      ...seeded.job,
      training_decision: {
        action: "raise",
        sizing: 12.5,
        certainty: "high",
        recorded_at: "2026-08-25T02:00:00Z",
      },
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(updatedJob));
    vi.stubGlobal("fetch", fetchMock);

    const outcome = await recordTrainingDecisionCommand(seeded.queryClient, {
      jobId: seeded.job.id,
      action: "raise",
      sizing: 12.5,
      certainty: "high",
    });

    expectSuccessfulCacheOutcome(seeded, updatedJob, outcome);
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/api/jobs/${seeded.job.id}/decision`,
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          action: "raise",
          sizing: 12.5,
          certainty: "high",
        }),
      }),
    );
  });

  it("completes a review and returns the shared cache outcome", async () => {
    const seeded = seedAffectedCaches("b".repeat(32));
    const updatedJob = jobRecord({
      ...seeded.job,
      training_reviewed_at: "2026-08-25T03:00:00Z",
      training_review_note: "Count combinations.",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(updatedJob)),
    );

    const outcome = await completeTrainingReviewCommand(seeded.queryClient, {
      jobId: seeded.job.id,
      note: "Count combinations.",
    });

    expectSuccessfulCacheOutcome(seeded, updatedJob, outcome);
  });

  it("reopens a review and returns the shared cache outcome", async () => {
    const seeded = seedAffectedCaches("c".repeat(32));
    const updatedJob = jobRecord({
      ...seeded.job,
      training_reviewed_at: null,
      training_review_note: null,
    });
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(updatedJob));
    vi.stubGlobal("fetch", fetchMock);

    const outcome = await reopenTrainingReviewCommand(seeded.queryClient, {
      jobId: seeded.job.id,
    });

    expectSuccessfulCacheOutcome(seeded, updatedJob, outcome);
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/api/jobs/${seeded.job.id}/training-review`,
      { method: "DELETE", credentials: "include" },
    );
  });

  it.each([
    [
      "decision",
      recordTrainingDecisionCommand,
      { action: "call", sizing: null, certainty: null },
    ],
    ["complete", completeTrainingReviewCommand, { note: null }],
    ["reopen", reopenTrainingReviewCommand, {}],
  ] as const)(
    "leaves caches untouched when %s transport fails",
    async (_name, command, payload) => {
      const seeded = seedAffectedCaches("d".repeat(32));
      vi.stubGlobal(
        "fetch",
        vi.fn().mockRejectedValueOnce(new TypeError("offline")),
      );

      await expect(
        command(seeded.queryClient, {
          jobId: seeded.job.id,
          ...payload,
        } as never),
      ).rejects.toThrow("offline");

      expect(
        seeded.queryClient.getQueryData(jobQueryKeys.detail(seeded.job.id)),
      ).toBe(seeded.job);
      expect(
        seeded.queryClient.getQueryState(seeded.processingKey)?.isInvalidated,
      ).toBe(false);
      expect(
        seeded.queryClient.getQueryState(seeded.historyKey)?.isInvalidated,
      ).toBe(false);
      expect(
        seeded.queryClient.getQueryState(seeded.trainingKey)?.isInvalidated,
      ).toBe(false);
    },
  );
});
