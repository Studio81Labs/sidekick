import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { benchmarkQueryKeys } from "../../../domains/benchmarks/api/benchmarksQueries";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { jobRecord } from "../../../test/analyzerHarness";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { setBenchmarkInclusionCommand } from "./setBenchmarkInclusionCommand";

afterEach(resetApiMocks);
const ADMINISTRATOR_TOKEN = "administrator-token";

describe("set benchmark inclusion command", () => {
  it("returns the updated job and invalidates only affected query families", async () => {
    const queryClient = createQueryClient();
    const currentJob = jobRecord({
      id: "a".repeat(32),
      benchmark_included: false,
    });
    const updatedJob = jobRecord({
      ...currentJob,
      benchmark_included: true,
      updated_at: "2026-08-25T01:00:00Z",
    });
    const processingKey = jobQueryKeys.processingPage(0);
    const historyKey = historyQueryKeys.page();
    const overviewKey = benchmarkQueryKeys.overview();
    const reportKey = benchmarkQueryKeys.report("report-1");
    queryClient.setQueryData(jobQueryKeys.detail(currentJob.id), currentJob);
    queryClient.setQueryData(processingKey, { jobs: [currentJob], total: 1 });
    queryClient.setQueryData(historyKey, { jobs: [currentJob], total: 1 });
    queryClient.setQueryData(overviewKey, {
      included_cases: 0,
      latest_report: null,
      recent_reports: [],
    });
    queryClient.setQueryData(reportKey, { id: "report-1" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(jsonResponse(updatedJob)),
    );

    const outcome = await setBenchmarkInclusionCommand(queryClient, {
      administratorToken: ADMINISTRATOR_TOKEN,
      jobId: currentJob.id,
      included: true,
    });

    expect(outcome).toEqual({
      job: updatedJob,
      cache: {
        updated: jobQueryKeys.detail(currentJob.id),
        invalidated: [
          jobQueryKeys.processing(),
          historyQueryKeys.all,
          benchmarkQueryKeys.overviews(),
        ],
      },
    });
    expect(
      queryClient.getQueryData(jobQueryKeys.detail(currentJob.id)),
    ).toEqual(updatedJob);
    expect(queryClient.getQueryState(processingKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(historyKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(overviewKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(reportKey)?.isInvalidated).toBe(false);
  });

  it("leaves query state untouched when transport fails", async () => {
    const queryClient = createQueryClient();
    const currentJob = jobRecord({ id: "b".repeat(32) });
    const detailKey = jobQueryKeys.detail(currentJob.id);
    const overviewKey = benchmarkQueryKeys.overview();
    queryClient.setQueryData(detailKey, currentJob);
    queryClient.setQueryData(overviewKey, { included_cases: 0 });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValueOnce(new TypeError("offline")),
    );

    await expect(
      setBenchmarkInclusionCommand(queryClient, {
        administratorToken: ADMINISTRATOR_TOKEN,
        jobId: currentJob.id,
        included: true,
      }),
    ).rejects.toThrow("offline");

    expect(queryClient.getQueryData(detailKey)).toBe(currentJob);
    expect(queryClient.getQueryState(detailKey)?.isInvalidated).toBe(false);
    expect(queryClient.getQueryState(overviewKey)?.isInvalidated).toBe(false);
  });
});
