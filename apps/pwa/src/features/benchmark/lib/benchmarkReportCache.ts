import type { QueryClient } from "@tanstack/react-query";

import {
  benchmarkQueryKeys,
  benchmarkReportQueryOptions,
} from "../../../domains/benchmarks/api/benchmarksQueries";
import type { BenchmarkReport } from "../../../shared/types/benchmarks";

export const BENCHMARK_REPORT_CACHE_LIMIT = 20;

export function cacheBenchmarkReport(
  cache: Map<string, BenchmarkReport>,
  report: BenchmarkReport,
  queryClient?: QueryClient,
): BenchmarkReport {
  cache.delete(report.id);
  cache.set(report.id, report);
  while (cache.size > BENCHMARK_REPORT_CACHE_LIMIT) {
    const oldestId = cache.keys().next().value;
    if (oldestId === undefined) {
      break;
    }
    cache.delete(oldestId);
    queryClient?.removeQueries({
      queryKey: benchmarkQueryKeys.report(oldestId),
      exact: true,
    });
  }
  return report;
}

export function loadCachedBenchmarkReport(
  reportId: string,
  cache: Map<string, BenchmarkReport>,
  pendingRequests: Map<string, Promise<BenchmarkReport>>,
  queryClient: QueryClient,
): Promise<BenchmarkReport> {
  const cached = cache.get(reportId);
  if (cached) {
    return Promise.resolve(cacheBenchmarkReport(cache, cached, queryClient));
  }
  const pending = pendingRequests.get(reportId);
  if (pending) {
    return pending;
  }
  const request = queryClient
    .fetchQuery(benchmarkReportQueryOptions(reportId, false))
    .then((report) => cacheBenchmarkReport(cache, report, queryClient))
    .finally(() => {
      if (pendingRequests.get(reportId) === request) {
        pendingRequests.delete(reportId);
      }
    });
  pendingRequests.set(reportId, request);
  return request;
}
