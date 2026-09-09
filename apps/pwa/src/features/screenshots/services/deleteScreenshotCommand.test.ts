import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import {
  fetchHistoryPageQuery,
  historyQueryKeys,
} from "../../../domains/history/api/historyQueries";
import {
  fetchJobQuery,
  fetchProcessingJobsQuery,
  jobQueryKeys,
} from "../../../domains/jobs/api/jobsQueries";
import { jobRecord } from "../../../test/analyzerHarness";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import {
  beginLatestQueryWrite,
  finishLatestQueryWrite,
  latestQueryWriteIsCurrent,
} from "../../../shared/api/queryCache";
import { deleteScreenshotCommand } from "./deleteScreenshotCommand";

afterEach(resetApiMocks);
const ADMINISTRATOR_TOKEN = "administrator-token";

describe("delete screenshot command", () => {
  it("returns an explicit outcome and removes only affected cache data", async () => {
    const queryClient = createQueryClient();
    const job = jobRecord({ id: "b".repeat(32) });
    const processingKey = jobQueryKeys.processingPage(0);
    const historyKey = historyQueryKeys.page();
    queryClient.setQueryData(jobQueryKeys.detail(job.id), job);
    queryClient.setQueryData(processingKey, { jobs: [job], total: 1 });
    queryClient.setQueryData(historyKey, { jobs: [job], total: 1 });
    let resolveDetail!: (response: Response) => void;
    let resolveProcessing!: (response: Response) => void;
    let resolveHistory!: (response: Response) => void;
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveDetail = resolve;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveProcessing = resolve;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            resolveHistory = resolve;
          }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const detailKey = jobQueryKeys.detail(job.id);
    const pendingWrite = beginLatestQueryWrite(queryClient, detailKey);
    const staleReads = [
      fetchJobQuery(queryClient, job.id, ADMINISTRATOR_TOKEN),
      fetchProcessingJobsQuery(queryClient, ADMINISTRATOR_TOKEN),
      fetchHistoryPageQuery(queryClient, ADMINISTRATOR_TOKEN),
    ];

    const outcome = await deleteScreenshotCommand(
      queryClient,
      job.id,
      ADMINISTRATOR_TOKEN,
    );
    resolveDetail(jsonResponse(job));
    resolveProcessing(jsonResponse({ jobs: [job], total: 1 }));
    resolveHistory(jsonResponse({ jobs: [job], total: 1 }));
    await Promise.all(staleReads);

    expect(
      latestQueryWriteIsCurrent(queryClient, detailKey, pendingWrite),
    ).toBe(false);
    finishLatestQueryWrite(queryClient, detailKey, pendingWrite);
    expect(outcome).toEqual({
      jobId: job.id,
      cache: {
        removed: jobQueryKeys.detail(job.id),
        invalidated: [jobQueryKeys.processing(), historyQueryKeys.all],
        superseded: [
          jobQueryKeys.detail(job.id),
          jobQueryKeys.processing(),
          historyQueryKeys.all,
        ],
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

    await expect(
      deleteScreenshotCommand(queryClient, job.id, ADMINISTRATOR_TOKEN),
    ).rejects.toThrow("Delete failed");
    expect(queryClient.getQueryData(detailKey)).toEqual(job);
    expect(queryClient.getQueryState(processingKey)?.isInvalidated).toBe(false);
  });
});
