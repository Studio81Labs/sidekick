import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../shared/api/generated/openapi";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import {
  getBenchmarkDatasetImport,
  getBenchmarkOverview,
  getBenchmarkReport,
  toBenchmarkDatasetImportReceipt,
  toBenchmarkOverview,
  toBenchmarkReport,
} from "./benchmarksApi";

type BenchmarkOverviewResponse = components["schemas"]["BenchmarkOverview"];
type BenchmarkReportResponse = components["schemas"]["BenchmarkReport"];
type BenchmarkDatasetImportReceiptResponse =
  components["schemas"]["BenchmarkDatasetImportReceipt"];

const overviewResponse = {} as BenchmarkOverviewResponse;
const reportResponse = {} as BenchmarkReportResponse;
const receiptResponse = {} as BenchmarkDatasetImportReceiptResponse;

afterEach(resetApiMocks);

describe("benchmark API adapter", () => {
  it("preserves generated response objects and JSON shape", () => {
    expect(toBenchmarkOverview(overviewResponse)).toBe(overviewResponse);
    expect(toBenchmarkReport(reportResponse)).toBe(reportResponse);
    expect(toBenchmarkDatasetImportReceipt(receiptResponse)).toBe(
      receiptResponse,
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
});
