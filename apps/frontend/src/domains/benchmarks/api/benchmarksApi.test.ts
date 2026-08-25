import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../shared/api/generated/openapi";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import {
  benchmarkDatasetUrl,
  getBenchmarkDatasetImport,
  getBenchmarkOverview,
  getBenchmarkReport,
  importBenchmarkDataset,
  runParserBenchmark,
  setBenchmarkInclusion,
  toBenchmarkDatasetImportReceipt,
  toBenchmarkDatasetImportResult,
  toBenchmarkOverview,
  toBenchmarkReport,
} from "./benchmarksApi";

type BenchmarkOverviewResponse = components["schemas"]["BenchmarkOverview"];
type BenchmarkReportResponse = components["schemas"]["BenchmarkReport"];
type BenchmarkDatasetImportReceiptResponse =
  components["schemas"]["BenchmarkDatasetImportReceipt"];
type BenchmarkDatasetImportResultResponse =
  components["schemas"]["BenchmarkDatasetImportResult"];

const overviewResponse = {} as BenchmarkOverviewResponse;
const reportResponse = {} as BenchmarkReportResponse;
const receiptResponse = {} as BenchmarkDatasetImportReceiptResponse;
const importResultResponse = {} as BenchmarkDatasetImportResultResponse;

afterEach(resetApiMocks);

describe("benchmark API adapter", () => {
  it("preserves generated response objects and JSON shape", () => {
    expect(toBenchmarkOverview(overviewResponse)).toBe(overviewResponse);
    expect(toBenchmarkReport(reportResponse)).toBe(reportResponse);
    expect(toBenchmarkDatasetImportReceipt(receiptResponse)).toBe(
      receiptResponse,
    );
    expect(toBenchmarkDatasetImportResult(importResultResponse)).toBe(
      importResultResponse,
    );
  });

  it("builds default and pipeline-scoped dataset export URLs", () => {
    expect(benchmarkDatasetUrl()).toBe(
      "http://localhost:8000/api/benchmarks/export",
    );
    expect(
      benchmarkDatasetUrl({
        parser_provider: "llm_vision",
        parser_layout_profile: "pokerstars",
      }),
    ).toBe(
      "http://localhost:8000/api/benchmarks/export?parser_provider=llm_vision&parser_layout_profile=pokerstars",
    );
  });

  it("runs only the selected parser and layout", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: "benchmark-1" }));
    vi.stubGlobal("fetch", fetchMock);

    await runParserBenchmark({
      parser_provider: "ocr_cv",
      parser_layout_profile: "fortuna_nations",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/benchmarks/run",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          parser_provider: "ocr_cv",
          parser_layout_profile: "fortuna_nations",
        }),
        credentials: "include",
      },
    );
  });

  it("scopes overview reads to the selected parser pipeline", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(overviewResponse));
    vi.stubGlobal("fetch", fetchMock);

    await getBenchmarkOverview({
      parser_provider: "ocr_cv",
      parser_layout_profile: "fortuna_nations",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/benchmarks?parser_provider=ocr_cv&parser_layout_profile=fortuna_nations",
      { credentials: "include" },
    );
  });

  it("reads report and encoded import-receipt resources", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(reportResponse))
      .mockResolvedValueOnce(jsonResponse(receiptResponse));
    vi.stubGlobal("fetch", fetchMock);

    await getBenchmarkReport("report-1");
    await getBenchmarkDatasetImport("request/1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/api/benchmarks/report-1",
      { credentials: "include" },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/api/benchmarks/imports/request%2F1",
      { credentials: "include" },
    );
  });

  it("updates benchmark inclusion through the generated request contract", async () => {
    const jobId = "a".repeat(32);
    const jobResponse = { id: jobId } as components["schemas"]["JobRecord"];
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(jobResponse));
    vi.stubGlobal("fetch", fetchMock);

    const result = await setBenchmarkInclusion(jobId, true);

    expect(result).toEqual(jobResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/api/jobs/${jobId}/benchmark`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ included: true }),
        credentials: "include",
      },
    );
  });

  it("imports a multipart dataset with the caller-owned request ID", async () => {
    const file = new File(["dataset"], "dataset.zip", {
      type: "application/zip",
    });
    const importResult = {
      imported_cases: 1,
      reused_cases: 0,
      included_cases: 1,
      job_ids: ["b".repeat(32)],
    } as BenchmarkDatasetImportResultResponse;
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(importResult));
    vi.stubGlobal("fetch", fetchMock);

    await expect(importBenchmarkDataset(file, "request-1")).resolves.toEqual(
      importResult,
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/benchmarks/import",
      expect.objectContaining({
        method: "POST",
        headers: { "X-Benchmark-Import-Request-ID": "request-1" },
        credentials: "include",
      }),
    );
    const form = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(form.get("file")).toBe(file);
  });
});
