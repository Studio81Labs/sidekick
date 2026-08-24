import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { jobRecord } from "../../../test/analyzerHarness";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { updateScreenshotMetadataCommand } from "./updateScreenshotMetadataCommand";

afterEach(resetApiMocks);

describe("update screenshot metadata command", () => {
  it("returns an explicit outcome and updates only affected query families", async () => {
    const queryClient = createQueryClient();
    const currentJob = jobRecord({ id: "a".repeat(32) });
    const updatedJob = jobRecord({
      ...currentJob,
      title: "Turn bluff",
      notes: "Review the sizing.",
      tags: ["turn", "bluff"],
      updated_at: "2026-08-24T01:00:00Z",
    });
    const processingKey = jobQueryKeys.processingPage(0);
    const historyKey = historyQueryKeys.page();
    queryClient.setQueryData(jobQueryKeys.detail(currentJob.id), currentJob);
    queryClient.setQueryData(processingKey, {
      jobs: [currentJob],
      total: 1,
    });
    queryClient.setQueryData(historyKey, {
      jobs: [currentJob],
      total: 1,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(updatedJob)),
    );

    const outcome = await updateScreenshotMetadataCommand(queryClient, {
      jobId: currentJob.id,
      metadata: {
        title: "Turn bluff",
        notes: "Review the sizing.",
        tags: ["turn", "bluff"],
      },
    });

    expect(outcome).toEqual({
      job: updatedJob,
      cache: {
        updated: jobQueryKeys.detail(currentJob.id),
        invalidated: [jobQueryKeys.processing(), historyQueryKeys.all],
      },
    });
    expect(
      queryClient.getQueryData(jobQueryKeys.detail(currentJob.id)),
    ).toEqual(updatedJob);
    expect(queryClient.getQueryState(processingKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(historyKey)?.isInvalidated).toBe(true);
  });
});
