import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { jobRecord } from "../../../test/analyzerHarness";
import { resetApiMocks } from "../../../test/api";
import { deleteScreenshotCommand } from "./deleteScreenshotCommand";

afterEach(resetApiMocks);

describe("delete screenshot command", () => {
  it("returns an explicit outcome and removes only affected cache data", async () => {
    const queryClient = createQueryClient();
    const job = jobRecord({ id: "b".repeat(32) });
    const processingKey = jobQueryKeys.processingPage(0);
    const historyKey = historyQueryKeys.page();
    queryClient.setQueryData(jobQueryKeys.detail(job.id), job);
    queryClient.setQueryData(processingKey, { jobs: [job], total: 1 });
    queryClient.setQueryData(historyKey, { jobs: [job], total: 1 });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(new Response(null, { status: 204 })),
    );

    const outcome = await deleteScreenshotCommand(queryClient, job.id);

    expect(outcome).toEqual({
      jobId: job.id,
      cache: {
        removed: jobQueryKeys.detail(job.id),
        invalidated: [jobQueryKeys.processing(), historyQueryKeys.all],
      },
    });
    expect(
      queryClient.getQueryData(jobQueryKeys.detail(job.id)),
    ).toBeUndefined();
    expect(queryClient.getQueryState(processingKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(historyKey)?.isInvalidated).toBe(true);
  });

  it("leaves cache state untouched when deletion fails", async () => {
    const queryClient = createQueryClient();
    const job = jobRecord({ id: "c".repeat(32) });
    const detailKey = jobQueryKeys.detail(job.id);
    const processingKey = jobQueryKeys.processingPage(0);
    queryClient.setQueryData(detailKey, job);
    queryClient.setQueryData(processingKey, { jobs: [job], total: 1 });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Delete failed" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(deleteScreenshotCommand(queryClient, job.id)).rejects.toThrow(
      "Delete failed",
    );
    expect(queryClient.getQueryData(detailKey)).toEqual(job);
    expect(queryClient.getQueryState(processingKey)?.isInvalidated).toBe(false);
  });
});
