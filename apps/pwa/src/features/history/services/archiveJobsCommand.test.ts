import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { approvedJob } from "../../../test/analyzerHarness";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { archiveJobsCommand } from "./archiveJobsCommand";

afterEach(resetApiMocks);
const ADMINISTRATOR_TOKEN = "administrator-token";

describe("archive jobs command", () => {
  it("returns explicit detail and projection cache outcomes", async () => {
    const queryClient = createQueryClient();
    const job = {
      ...approvedJob(),
      id: "d".repeat(32),
      archived_at: "2026-08-25T00:00:00Z",
    };
    const history = { jobs: [job], total: 1, snapshot_version: "archive-1" };
    const detailKey = jobQueryKeys.detail(job.id);
    const processingKey = jobQueryKeys.processingPage(0);
    const olderHistoryKey = historyQueryKeys.page(24);
    queryClient.setQueryData(detailKey, { ...job, archived_at: null });
    queryClient.setQueryData(processingKey, {
      jobs: [{ ...job, archived_at: null }],
      total: 1,
    });
    queryClient.setQueryData(olderHistoryKey, { jobs: [], total: 0 });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(history)),
    );

    const outcome = await archiveJobsCommand(
      queryClient,
      [job.id],
      ADMINISTRATOR_TOKEN,
    );

    expect(outcome).toEqual({
      history,
      cache: {
        invalidated: [
          detailKey,
          jobQueryKeys.processing(),
          historyQueryKeys.pages(),
        ],
        replaced: historyQueryKeys.page(),
        superseded: [
          detailKey,
          jobQueryKeys.processing(),
          historyQueryKeys.pages(),
        ],
        updated: [detailKey],
      },
    });
    expect(queryClient.getQueryData(detailKey)).toEqual(job);
    expect(queryClient.getQueryState(processingKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(olderHistoryKey)?.isInvalidated).toBe(
      true,
    );
    expect(queryClient.getQueryData(historyQueryKeys.page())).toEqual(history);
    expect(
      queryClient.getQueryState(historyQueryKeys.page())?.isInvalidated,
    ).toBe(false);
  });

  it("leaves cache untouched when archive transport fails", async () => {
    const queryClient = createQueryClient();
    const job = approvedJob();
    const detailKey = jobQueryKeys.detail(job.id);
    queryClient.setQueryData(detailKey, job);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Archive failed" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(
      archiveJobsCommand(queryClient, [job.id], ADMINISTRATOR_TOKEN),
    ).rejects.toThrow("Archive failed");
    expect(queryClient.getQueryData(detailKey)).toEqual(job);
    expect(queryClient.getQueryState(detailKey)?.isInvalidated).toBe(false);
  });
});
