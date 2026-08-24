import { describe, expect, it } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { benchmarkQueryKeys } from "../../../domains/benchmarks/api/benchmarksQueries";
import type { BenchmarkReport } from "../../../shared/types";
import {
  BENCHMARK_REPORT_CACHE_LIMIT,
  cacheBenchmarkReport,
  loadCachedBenchmarkReport,
} from "./benchmarkReportCache";

function report(id: string): BenchmarkReport {
  return {
    id,
    parser_provider: "ocr_cv",
    layout_profile: "fortuna",
    created_at: "2026-08-15T08:00:00Z",
    total_cases: 0,
    successful_cases: 0,
    failed_cases: 0,
    correct_fields: 0,
    evaluated_fields: 0,
    accuracy: 0,
    field_metrics: [],
    cases: [],
  };
}

describe("benchmark report cache", () => {
  it("keeps the most recently used bounded report set", async () => {
    const cache = new Map<string, BenchmarkReport>();
    for (let index = 0; index <= BENCHMARK_REPORT_CACHE_LIMIT; index += 1) {
      cacheBenchmarkReport(cache, report(`report-${index}`));
    }

    expect(cache).toHaveLength(BENCHMARK_REPORT_CACHE_LIMIT);
    expect(cache.has("report-0")).toBe(false);
    const cached = cache.get("report-1");
    expect(cached).toBeDefined();
    await expect(
      loadCachedBenchmarkReport(
        "report-1",
        cache,
        new Map(),
        createQueryClient(),
      ),
    ).resolves.toBe(cached);
    const cachedIds = [...cache.keys()];
    expect(cachedIds[cachedIds.length - 1]).toBe("report-1");
  });

  it("removes evicted reports from the query cache", () => {
    const cache = new Map<string, BenchmarkReport>();
    const queryClient = createQueryClient();

    for (let index = 0; index <= BENCHMARK_REPORT_CACHE_LIMIT; index += 1) {
      const value = report(`report-${index}`);
      queryClient.setQueryData(benchmarkQueryKeys.report(value.id), value);
      cacheBenchmarkReport(cache, value, queryClient);
    }

    expect(
      queryClient.getQueryData(benchmarkQueryKeys.report("report-0")),
    ).toBeUndefined();
    expect(
      queryClient.getQueryData(
        benchmarkQueryKeys.report(`report-${BENCHMARK_REPORT_CACHE_LIMIT}`),
      ),
    ).toBeDefined();
  });

  it("reuses an in-flight request", () => {
    const pendingReport = report("pending");
    const pending = Promise.resolve(pendingReport);
    const pendingRequests = new Map([["pending", pending]]);

    expect(
      loadCachedBenchmarkReport(
        "pending",
        new Map(),
        pendingRequests,
        createQueryClient(),
      ),
    ).toBe(pending);
  });
});
