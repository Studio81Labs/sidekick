import type { QueryClient } from "@tanstack/react-query";

import { fetchHistoryPageQuery } from "../../../domains/history/api/historyQueries";
import { fetchProcessingJobsQuery } from "../../../domains/jobs/api/jobsQueries";
import type {
  JobHistory,
  JobQueue,
  JobRecord,
} from "../../../shared/types/jobs";

const HISTORY_SEARCH_PAGE_LIMIT = 100;
const HISTORY_SNAPSHOT_RETRY_LIMIT = 3;
const PROCESSING_QUEUE_SNAPSHOT_RETRY_LIMIT = 3;

export { fetchBenchmarkImportReceiptQuery } from "../../../domains/benchmarks/api/benchmarksQueries";
export { fetchHistoryPageQuery };
export { fetchJobQuery } from "../../../domains/jobs/api/jobsQueries";
export { fetchTrainingProgressQuery } from "../../../domains/training/api/trainingQueries";

export async function getHistorySearchExtent(
  queryClient: QueryClient,
  query: string,
  loadedCount: number,
): Promise<JobHistory> {
  for (let attempt = 0; attempt < HISTORY_SNAPSHOT_RETRY_LIMIT; attempt += 1) {
    const jobs: JobRecord[] = [];
    let snapshotVersion: string | null = null;
    let snapshotChanged = false;
    let total = 0;

    do {
      const page = await fetchHistoryPageQuery(
        queryClient,
        jobs.length,
        query,
        Math.min(HISTORY_SEARCH_PAGE_LIMIT, loadedCount - jobs.length),
      );
      if (
        snapshotVersion !== null &&
        page.snapshot_version !== undefined &&
        page.snapshot_version !== snapshotVersion
      ) {
        snapshotChanged = true;
        break;
      }
      snapshotVersion ??= page.snapshot_version ?? null;
      total = page.total;
      jobs.push(...page.jobs);
      if (page.jobs.length === 0) {
        break;
      }
    } while (jobs.length < Math.min(loadedCount, total));

    if (!snapshotChanged) {
      return {
        total,
        jobs: jobs.slice(0, Math.min(loadedCount, total)),
        snapshot_version: snapshotVersion ?? undefined,
      };
    }
  }

  throw new Error("Saved history changed repeatedly while loading");
}

export async function getProcessingQueueExtent(
  queryClient: QueryClient,
): Promise<JobQueue> {
  for (
    let attempt = 0;
    attempt < PROCESSING_QUEUE_SNAPSHOT_RETRY_LIMIT;
    attempt += 1
  ) {
    const jobs: JobRecord[] = [];
    let snapshotVersion: string | null = null;
    let snapshotChanged = false;
    let total = 0;

    do {
      const page = await fetchProcessingJobsQuery(queryClient, jobs.length);
      if (
        snapshotVersion !== null &&
        page.snapshot_version !== undefined &&
        page.snapshot_version !== snapshotVersion
      ) {
        snapshotChanged = true;
        break;
      }
      snapshotVersion ??= page.snapshot_version ?? null;
      total = page.total;
      jobs.push(...page.jobs);
      if (page.jobs.length === 0) {
        break;
      }
    } while (jobs.length < total);

    if (!snapshotChanged && jobs.length >= total) {
      return {
        total,
        jobs: jobs.slice(0, total),
        snapshot_version: snapshotVersion ?? undefined,
      };
    }
  }

  throw new Error("Processing queue changed repeatedly while loading");
}
