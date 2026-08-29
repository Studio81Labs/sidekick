import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { canonicalState, jobRecord } from "../../../test/analyzerHarness";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { supersedeLatestQueryWrites } from "../../../shared/api/queryCache";
import { approveStateCommand } from "./handWorkflowCommands";

afterEach(resetApiMocks);

function seedCaches(jobId: string) {
  const queryClient = createQueryClient();
  const job = jobRecord({ id: jobId });
  const processingKey = jobQueryKeys.processingPage(0);
  const historyKey = historyQueryKeys.page();
  queryClient.setQueryData(jobQueryKeys.detail(jobId), job);
  queryClient.setQueryData(processingKey, { jobs: [job], total: 1 });
  queryClient.setQueryData(historyKey, { jobs: [], total: 0 });
  return { queryClient, job, processingKey, historyKey };
}

describe("hand workflow commands", () => {
  it("approves state and invalidates the queue and history projections", async () => {
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
        invalidated: [jobQueryKeys.processing(), historyQueryKeys.all],
        detailSeeded: true,
      },
    });
    expect(
      seeded.queryClient.getQueryState(seeded.processingKey)?.isInvalidated,
    ).toBe(true);
    expect(
      seeded.queryClient.getQueryState(seeded.historyKey)?.isInvalidated,
    ).toBe(true);
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
    const staleApproval = jobRecord({
      ...seeded.job,
      title: "Old title",
      notes: "Old notes",
      tags: ["old"],
      status: "approved",
      approved_state: canonicalState(),
      updated_at: "2026-08-25T03:00:00Z",
    });
    seeded.queryClient.setQueryData(
      jobQueryKeys.detail(seeded.job.id),
      current,
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(staleApproval)),
    );

    const outcome = await approveStateCommand(seeded.queryClient, {
      jobId: seeded.job.id,
      state: canonicalState(),
    });

    expect(outcome.job).toEqual(staleApproval);
    expect(
      seeded.queryClient.getQueryData(jobQueryKeys.detail(seeded.job.id)),
    ).toEqual({
      ...staleApproval,
      title: current.title,
      notes: current.notes,
      tags: current.tags,
      updated_at: current.updated_at,
    });
  });

  it("does not reseed job detail after concurrent permanent deletion", async () => {
    const seeded = seedCaches("e".repeat(32));
    const detailKey = jobQueryKeys.detail(seeded.job.id);
    const approved = jobRecord({
      ...seeded.job,
      status: "approved",
      approved_state: canonicalState(),
    });
    let resolveApproval!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveApproval = resolve;
          }),
      ),
    );

    const approval = approveStateCommand(seeded.queryClient, {
      jobId: seeded.job.id,
      state: canonicalState(),
    });
    supersedeLatestQueryWrites(seeded.queryClient, detailKey);
    seeded.queryClient.removeQueries({ queryKey: detailKey, exact: true });
    resolveApproval(jsonResponse(approved));

    const outcome = await approval;

    expect(outcome.cache.detailSeeded).toBe(false);
    expect(seeded.queryClient.getQueryState(detailKey)).toBeUndefined();
  });

  it("leaves caches untouched when approval transport fails", async () => {
    const seeded = seedCaches("c".repeat(32));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValueOnce(new DOMException("Aborted", "AbortError")),
    );

    await expect(
      approveStateCommand(seeded.queryClient, {
        jobId: seeded.job.id,
        state: { ...canonicalState(), user_approved: false },
      }),
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
  });
});
