import { getBenchmarkReport } from "../../../domains/benchmarks/api/benchmarksApi";
import type { BenchmarkReport } from "../../../shared/types";

export const BENCHMARK_REPORT_CACHE_LIMIT = 20;

export function cacheBenchmarkReport(
  cache: Map<string, BenchmarkReport>,
  report: BenchmarkReport,
): BenchmarkReport {
  cache.delete(report.id);
  cache.set(report.id, report);
  while (cache.size > BENCHMARK_REPORT_CACHE_LIMIT) {
    const oldestId = cache.keys().next().value;
    if (oldestId === undefined) {
      break;
    }
    cache.delete(oldestId);
  }
  return report;
}

export function loadCachedBenchmarkReport(
  reportId: string,
  cache: Map<string, BenchmarkReport>,
  pendingRequests: Map<string, Promise<BenchmarkReport>>,
): Promise<BenchmarkReport> {
  const cached = cache.get(reportId);
  if (cached) {
    return Promise.resolve(cacheBenchmarkReport(cache, cached));
  }
  const pending = pendingRequests.get(reportId);
  if (pending) {
    return pending;
  }
  const request = getBenchmarkReport(reportId)
    .then((report) => cacheBenchmarkReport(cache, report))
    .finally(() => {
      if (pendingRequests.get(reportId) === request) {
        pendingRequests.delete(reportId);
      }
    });
  pendingRequests.set(reportId, request);
  return request;
}
