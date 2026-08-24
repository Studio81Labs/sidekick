import { afterEach, describe, expect, it, vi } from "vitest";

import {
  getBenchmarkDatasetImport as getDomainBenchmarkDatasetImport,
  getBenchmarkOverview as getDomainBenchmarkOverview,
  getBenchmarkReport as getDomainBenchmarkReport,
} from "../../domains/benchmarks/api/benchmarksApi";
import { jsonResponse, resetApiMocks } from "../../test/api";
import {
  benchmarkDatasetUrl,
  getBenchmarkDatasetImport,
  getBenchmarkOverview,
  getBenchmarkReport,
  runParserBenchmark,
} from "./benchmarks";

afterEach(resetApiMocks);

describe("benchmark read compatibility", () => {
  it("preserves domain adapter export identities", () => {
    expect(getBenchmarkOverview).toBe(getDomainBenchmarkOverview);
    expect(getBenchmarkReport).toBe(getDomainBenchmarkReport);
    expect(getBenchmarkDatasetImport).toBe(getDomainBenchmarkDatasetImport);
  });
});

describe("benchmarkDatasetUrl", () => {
  it("keeps the deployment-default export URL when no pipeline is selected", () => {
    expect(benchmarkDatasetUrl()).toBe(
      "http://localhost:8000/api/benchmarks/export",
    );
  });

  it("exports the selected parser layout corpus", () => {
    expect(
      benchmarkDatasetUrl({
        parser_provider: "llm_vision",
        parser_layout_profile: "pokerstars",
      }),
    ).toBe(
      "http://localhost:8000/api/benchmarks/export?parser_provider=llm_vision&parser_layout_profile=pokerstars",
    );
  });
});

describe("runParserBenchmark", () => {
  it("sends only the selected parser and layout", async () => {
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
});

describe("getBenchmarkOverview", () => {
  it("keeps the deployment-default request backward compatible", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        included_cases: 0,
        latest_report: null,
        recent_reports: [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getBenchmarkOverview();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/benchmarks",
      { credentials: "include" },
    );
  });

  it("scopes report history to the selected parser and layout", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        included_cases: 0,
        latest_report: null,
        recent_reports: [],
      }),
    );
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
});
