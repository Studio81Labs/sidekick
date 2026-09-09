import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "@poker-hero/openapi-client";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import {
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
const ADMINISTRATOR_TOKEN = "administrator-token";

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

  it("runs only the selected parser and layout", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: "benchmark-1" }));
    vi.stubGlobal("fetch", fetchMock);

    await runParserBenchmark(
      {
        parser_provider: "ocr_cv",
        parser_layout_profile: "fortuna_nations",
      },
      ADMINISTRATOR_TOKEN,
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/admin/ocr/benchmarks/run",
      {
        method: "POST",
        headers: {
          Authorization: "Bearer administrator-token",
          "Content-Type": "application/json",
        },
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

    await getBenchmarkOverview(
      {
        parser_provider: "ocr_cv",
        parser_layout_profile: "fortuna_nations",
      },
      ADMINISTRATOR_TOKEN,
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/admin/ocr/benchmarks?parser_provider=ocr_cv&parser_layout_profile=fortuna_nations",
      {
        credentials: "include",
        headers: { Authorization: "Bearer administrator-token" },
      },
    );
  });

  it("reads report and encoded import-receipt resources", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(reportResponse))
      .mockResolvedValueOnce(jsonResponse(receiptResponse));
    vi.stubGlobal("fetch", fetchMock);

    await getBenchmarkReport("report-1", ADMINISTRATOR_TOKEN);
    await getBenchmarkDatasetImport("request/1", ADMINISTRATOR_TOKEN);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/api/admin/ocr/benchmarks/report-1",
      {
        credentials: "include",
        headers: { Authorization: "Bearer administrator-token" },
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/api/admin/ocr/benchmarks/imports/request%2F1",
      {
        credentials: "include",
        headers: { Authorization: "Bearer administrator-token" },
      },
    );
  });

  it("updates benchmark inclusion through the generated request contract", async () => {
    const jobId = "a".repeat(32);
    const jobResponse = { id: jobId } as components["schemas"]["JobRecord"];
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(jobResponse));
    vi.stubGlobal("fetch", fetchMock);

    const result = await setBenchmarkInclusion(
      jobId,
      true,
      ADMINISTRATOR_TOKEN,
    );

    expect(result).toEqual(jobResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/api/admin/ocr/jobs/${jobId}/benchmark`,
      {
        method: "PUT",
        headers: {
          Authorization: "Bearer administrator-token",
          "Content-Type": "application/json",
        },
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

    await expect(
      importBenchmarkDataset(file, "request-1", "administrator-token"),
    ).resolves.toEqual(importResult);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/admin/ocr/benchmarks/import",
      expect.objectContaining({
        method: "POST",
        headers: {
          Authorization: "Bearer administrator-token",
          "X-Benchmark-Import-Request-ID": "request-1",
        },
        credentials: "include",
      }),
    );
    const form = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(form.get("file")).toBe(file);
  });
});
