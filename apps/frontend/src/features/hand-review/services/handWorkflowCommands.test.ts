import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { trainingQueryKeys } from "../../../domains/training/api/trainingQueries";
import { canonicalState, jobRecord } from "../../../test/analyzerHarness";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { supersedeLatestQueryWrites } from "../../../shared/api/queryCache";
import {
  approveStateCommand,
  requestRecommendationCommand,
} from "./handWorkflowCommands";

afterEach(resetApiMocks);

function seedCaches(jobId: string) {
  const queryClient = createQueryClient();
  const job = jobRecord({ id: jobId });
  const processingKey = jobQueryKeys.processingPage(0);
  const historyKey = historyQueryKeys.page();
  const trainingKey = trainingQueryKeys.progress();
  queryClient.setQueryData(jobQueryKeys.detail(jobId), job);
  queryClient.setQueryData(processingKey, { jobs: [job], total: 1 });
  queryClient.setQueryData(historyKey, { jobs: [], total: 0 });
  queryClient.setQueryData(trainingKey, { reviewed_hands: 0 });
  return { queryClient, job, processingKey, historyKey, trainingKey };
}

describe("hand workflow commands", () => {
  it("approves state and invalidates training progress that may lose a prior result", async () => {
    const seeded = seedCaches("a".repeat(32));
    const state = { ...canonicalState(), user_approved: false };
    const approved = jobRecord({ ...seeded.job, approved_state: state });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(approved)),
    );

    const outcome = await approveStateCommand(seeded.queryClient, {
      jobId: seeded.job.id,
      state,
    });

    expect(outcome).toEqual({
      job: approved,
      cache: {
        updated: jobQueryKeys.detail(approved.id),
        invalidated: [
          jobQueryKeys.processing(),
          historyQueryKeys.all,
          trainingQueryKeys.all,
        ],
        detailSeeded: true,
      },
    });
    expect(
      seeded.queryClient.getQueryState(seeded.processingKey)?.isInvalidated,
    ).toBe(true);
    expect(
      seeded.queryClient.getQueryState(seeded.historyKey)?.isInvalidated,
    ).toBe(true);
    expect(
      seeded.queryClient.getQueryState(seeded.trainingKey)?.isInvalidated,
    ).toBe(true);
  });

  it("preserves recommendation identity, abort signal, and training invalidation", async () => {
    const seeded = seedCaches("b".repeat(32));
    const recommended = jobRecord({ ...seeded.job, status: "recommended" });
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(recommended));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    const outcome = await requestRecommendationCommand(seeded.queryClient, {
      jobId: seeded.job.id,
      requestId: "recommendation-1",
      signal: controller.signal,
    });

    expect(outcome.cache.invalidated).toEqual([
      jobQueryKeys.processing(),
      historyQueryKeys.all,
      trainingQueryKeys.all,
    ]);
    expect(
      seeded.queryClient.getQueryState(seeded.trainingKey)?.isInvalidated,
    ).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/api/jobs/${seeded.job.id}/recommend`,
      expect.objectContaining({
        headers: { "X-Recommendation-Request-ID": "recommendation-1" },
        signal: controller.signal,
      }),
    );
  });

  it("preserves metadata cached by a newer concurrent save", async () => {
    const seeded = seedCaches("d".repeat(32));
    const current = jobRecord({
      ...seeded.job,
      title: "Updated title",
      notes: "Updated notes",
      tags: ["updated"],
      updated_at: "2026-08-25T04:00:00Z",
    });
    const staleRecommendation = jobRecord({
      ...seeded.job,
      title: "Old title",
      notes: "Old notes",
      tags: ["old"],
      status: "recommended",
      updated_at: "2026-08-25T03:00:00Z",
    });
    seeded.queryClient.setQueryData(
      jobQueryKeys.detail(seeded.job.id),
      current,
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(staleRecommendation)),
    );

    const outcome = await requestRecommendationCommand(seeded.queryClient, {
      jobId: seeded.job.id,
      requestId: "recommendation-3",
    });

    expect(outcome.job).toEqual(staleRecommendation);
    expect(
      seeded.queryClient.getQueryData(jobQueryKeys.detail(seeded.job.id)),
    ).toEqual({
      ...staleRecommendation,
      title: current.title,
      notes: current.notes,
      tags: current.tags,
      updated_at: current.updated_at,
    });
  });

  it("does not reseed job detail after concurrent permanent deletion", async () => {
    const seeded = seedCaches("e".repeat(32));
    const detailKey = jobQueryKeys.detail(seeded.job.id);
    const recommended = jobRecord({
      ...seeded.job,
      status: "recommended",
    });
    let resolveRecommendation!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveRecommendation = resolve;
          }),
      ),
    );

    const recommendation = requestRecommendationCommand(seeded.queryClient, {
      jobId: seeded.job.id,
      requestId: "recommendation-4",
    });
    supersedeLatestQueryWrites(seeded.queryClient, detailKey);
    seeded.queryClient.removeQueries({ queryKey: detailKey, exact: true });
    resolveRecommendation(jsonResponse(recommended));

    const outcome = await recommendation;

    expect(outcome.cache.detailSeeded).toBe(false);
    expect(seeded.queryClient.getQueryState(detailKey)).toBeUndefined();
  });

  it.each([
    [
      "approval",
      approveStateCommand,
      { state: { ...canonicalState(), user_approved: false } },
    ],
    [
      "recommendation",
      requestRecommendationCommand,
      { requestId: "recommendation-2" },
    ],
  ] as const)(
    "leaves caches untouched when %s transport fails",
    async (_name, command, payload) => {
      const seeded = seedCaches("c".repeat(32));
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockRejectedValueOnce(new DOMException("Aborted", "AbortError")),
      );

      await expect(
        command(seeded.queryClient, {
          jobId: seeded.job.id,
          ...payload,
        } as never),
      ).rejects.toThrow("Aborted");

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
