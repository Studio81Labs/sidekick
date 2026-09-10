import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { benchmarkQueryKeys } from "../../../domains/benchmarks/api/benchmarksQueries";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { jobRecord } from "../../../test/analyzerHarness";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { importBenchmarkDatasetCommand } from "./importBenchmarkDatasetCommand";

afterEach(resetApiMocks);

describe("import benchmark dataset command", () => {
  it("preserves the request ID and invalidates only imported corpus state", async () => {
    const queryClient = createQueryClient();
    const importedJob = jobRecord({ id: "a".repeat(32) });
    const detailKey = jobQueryKeys.detail(importedJob.id);
    const processingKey = jobQueryKeys.processingPage(0);
    const historyKey = historyQueryKeys.page();
    const overviewKey = benchmarkQueryKeys.overview();
    const reportKey = benchmarkQueryKeys.report("report-1");
    queryClient.setQueryData(detailKey, importedJob);
    queryClient.setQueryData(processingKey, { jobs: [importedJob], total: 1 });
    queryClient.setQueryData(historyKey, { jobs: [], total: 0 });
    queryClient.setQueryData(overviewKey, { included_cases: 0 });
    queryClient.setQueryData(reportKey, { id: "report-1" });
    const result = {
      imported_cases: 1,
      reused_cases: 0,
      included_cases: 1,
      included_cases_by_layout: { pokerstars: 1 },
      job_ids: [importedJob.id, importedJob.id],
    };
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(result));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["dataset"], "dataset.zip");

    const outcome = await importBenchmarkDatasetCommand(queryClient, {
      administratorToken: "administrator-token",
      file,
      requestId: "request-1",
    });

    expect(outcome).toEqual({
      result,
      cache: {
        invalidated: [
          detailKey,
          jobQueryKeys.processing(),
          historyQueryKeys.all,
          benchmarkQueryKeys.overviews(),
        ],
      },
    });
    expect(queryClient.getQueryState(detailKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(processingKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(historyKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(overviewKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(reportKey)?.isInvalidated).toBe(false);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/admin/ocr/benchmarks/import",
      expect.objectContaining({
        headers: {
          Authorization: "Bearer administrator-token",
          "X-Benchmark-Import-Request-ID": "request-1",
        },
      }),
    );
    const form = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(form.get("file")).toBe(file);
  });

  it("leaves Query state untouched when import transport fails", async () => {
    const queryClient = createQueryClient();
    const processingKey = jobQueryKeys.processingPage(0);
    const overviewKey = benchmarkQueryKeys.overview();
    const processing = { jobs: [], total: 0 };
    const overview = { included_cases: 0 };
    queryClient.setQueryData(processingKey, processing);
    queryClient.setQueryData(overviewKey, overview);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValueOnce(new TypeError("offline")),
    );

    await expect(
      importBenchmarkDatasetCommand(queryClient, {
        administratorToken: "administrator-token",
        file: new File(["dataset"], "dataset.zip"),
        requestId: "request-2",
      }),
    ).rejects.toThrow("offline");

    expect(queryClient.getQueryData(processingKey)).toBe(processing);
    expect(queryClient.getQueryData(overviewKey)).toBe(overview);
    expect(queryClient.getQueryState(processingKey)?.isInvalidated).toBe(false);
    expect(queryClient.getQueryState(overviewKey)?.isInvalidated).toBe(false);
  });
});
