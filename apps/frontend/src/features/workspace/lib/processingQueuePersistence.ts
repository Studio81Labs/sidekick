import type { QueryClient } from "@tanstack/react-query";

import { fetchProcessingJobsQuery } from "../../../domains/jobs/api/jobsQueries";
import type { JobQueue, JobRecord } from "../../../shared/types/jobs";
import {
  isCachedJobRecord,
  isPristineBenchmarkImport,
} from "./cachedJobValidation";
import { PERSISTED_JOB_ID_PATTERN } from "./cacheValidationPrimitives";
import { readPersistedMutationLease } from "./mutationLeaseStorage";
import { newerJob } from "./reconciliation";

export const PROCESSING_QUEUE_SESSION_SYNC_KEY =
  "poker-training-processing-synced";
export const PROCESSING_QUEUE_STORAGE_KEY = "poker-training-processing-v1";
export const PROCESSING_QUEUE_TOTAL_STORAGE_KEY =
  "poker-training-processing-total-v1";
export const PROCESSING_QUEUE_CACHE_LIMIT = 100;
export const PROCESSING_QUEUE_SNAPSHOT_RETRY_LIMIT = 3;
export const PROCESSING_QUEUE_REVALIDATION_INTERVAL_MS = 250;

export type ProcessingQueueRestore = JobQueue & {
  revalidatedLeaseJob?: JobRecord;
  revalidatedArchiveJobs?: JobRecord[];
};

export function readProcessingQueue(): JobRecord[] | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(PROCESSING_QUEUE_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return null;
    }
    return parsed
      .filter(isCachedJobRecord)
      .filter((job) => !isPristineBenchmarkImport(job));
  } catch {
    return null;
  }
}

export function processingJobsForCache(jobs: JobRecord[]): JobRecord[] {
  return jobs.filter(
    (job) =>
      PERSISTED_JOB_ID_PATTERN.test(job.id) &&
      job.archived_at === null &&
      !isPristineBenchmarkImport(job),
  );
}

export function readStoredProcessingQueueTotal(): number | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(PROCESSING_QUEUE_TOTAL_STORAGE_KEY);
    if (raw === null) {
      return null;
    }
    const parsed = Number(raw);
    return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null;
  } catch {
    return null;
  }
}

export function writeProcessingQueue(
  jobs: JobRecord[],
  preserveKnownTotal = false,
  authoritativeJobIds: ReadonlySet<string> = new Set(),
): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const cachedJobsById = new Map(
    (readProcessingQueue() ?? []).map((job) => [job.id, job]),
  );
  const processingJobs = processingJobsForCache(jobs).map((job) => {
    if (authoritativeJobIds.has(job.id)) {
      return job;
    }
    const cachedJob = cachedJobsById.get(job.id);
    return cachedJob ? newerJob(job, cachedJob) : job;
  });
  const storedTotal = preserveKnownTotal
    ? readStoredProcessingQueueTotal()
    : null;
  const total =
    storedTotal === null
      ? processingJobs.length
      : Math.max(storedTotal, processingJobs.length);
  try {
    const serializedJobs = JSON.stringify(
      processingJobs.slice(0, PROCESSING_QUEUE_CACHE_LIMIT),
    );
    if (
      window.localStorage.getItem(PROCESSING_QUEUE_STORAGE_KEY) !==
      serializedJobs
    ) {
      window.localStorage.setItem(PROCESSING_QUEUE_STORAGE_KEY, serializedJobs);
    }
    const serializedTotal = String(total);
    if (
      window.localStorage.getItem(PROCESSING_QUEUE_TOTAL_STORAGE_KEY) !==
      serializedTotal
    ) {
      window.localStorage.setItem(
        PROCESSING_QUEUE_TOTAL_STORAGE_KEY,
        serializedTotal,
      );
    }
    return true;
  } catch {
    markProcessingQueueSessionUnsynced();
    return false;
  }
}

export function readCachedProcessingQueueTotal(
  cachedJobs: JobRecord[] | null,
): number | null {
  if (cachedJobs === null || typeof window === "undefined") {
    return null;
  }
  const storedTotal = readStoredProcessingQueueTotal();
  if (
    storedTotal === null ||
    cachedJobs.length !== storedTotal ||
    cachedJobs.length > PROCESSING_QUEUE_CACHE_LIMIT
  ) {
    return null;
  }
  return storedTotal;
}

export function markProcessingQueueSessionSynced(): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    if (readPersistedMutationLease("processing") !== null) {
      window.sessionStorage.removeItem(PROCESSING_QUEUE_SESSION_SYNC_KEY);
      return;
    }
    window.sessionStorage.setItem(PROCESSING_QUEUE_SESSION_SYNC_KEY, "true");
  } catch {
    // Persisted jobs remain available when browser session storage is unavailable.
  }
}

export function markProcessingQueueSessionUnsynced(): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.sessionStorage.removeItem(PROCESSING_QUEUE_SESSION_SYNC_KEY);
  } catch {
    // Blocked session storage already forces the app to reconcile on reload.
  }
}

export function processingQueueSessionSynced(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    return (
      window.sessionStorage.getItem(PROCESSING_QUEUE_SESSION_SYNC_KEY) ===
      "true"
    );
  } catch {
    return false;
  }
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
