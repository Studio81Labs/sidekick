import type { JobRecord } from "../../../shared/types/jobs";
import type { HistoryItem } from "../../../domains/history/model/historyItem";
import { isPristineBenchmarkImport } from "./cachedJobValidation";
import { PERSISTED_JOB_ID_PATTERN } from "../../../shared/lib/jobIdentity";

export const LOCAL_UPLOAD_RECONCILIATION_WINDOW_MS = 2 * 60 * 1000;

export function mergeHistoryItems(
  current: HistoryItem[],
  incoming: HistoryItem[],
): HistoryItem[] {
  const currentIds = new Set(current.map((item) => item.id));
  const incomingById = new Map(incoming.map((item) => [item.id, item]));
  return [
    ...current.map((item) => {
      const incomingItem = incomingById.get(item.id);
      return incomingItem ? newerHistoryItem(item, incomingItem) : item;
    }),
    ...incoming.filter((item) => !currentIds.has(item.id)),
  ];
}

export function newerHistoryItem(
  current: HistoryItem,
  incoming: HistoryItem,
): HistoryItem {
  return newerJob(current.job, incoming.job) === current.job
    ? current
    : incoming;
}

export function newerJob(current: JobRecord, incoming: JobRecord): JobRecord {
  const currentUpdatedAt = Date.parse(current.updated_at);
  const incomingUpdatedAt = Date.parse(incoming.updated_at);
  return Number.isFinite(currentUpdatedAt) &&
    (!Number.isFinite(incomingUpdatedAt) ||
      currentUpdatedAt >= incomingUpdatedAt)
    ? current
    : incoming;
}

export function preserveUploadRequestId(
  incoming: JobRecord,
  current: JobRecord | undefined,
): JobRecord {
  return incoming.upload_request_id || !current?.upload_request_id
    ? incoming
    : { ...incoming, upload_request_id: current.upload_request_id };
}

export function localUploadMatchDistance(
  localJob: JobRecord,
  incomingJob: JobRecord,
): number | null {
  const matchingPersistedFailure =
    incomingJob.status === "error" &&
    localJob.error !== null &&
    incomingJob.error !== null &&
    (localJob.error === incomingJob.error ||
      localJob.error.endsWith(`: ${incomingJob.error}`));
  const matchingPersistedSuccess =
    incomingJob.status === "parsed" || incomingJob.status === "approved";
  if (
    !localJob.id.startsWith("local-error-") ||
    localJob.parser_provider !== "client" ||
    localJob.status !== "error" ||
    !PERSISTED_JOB_ID_PATTERN.test(incomingJob.id) ||
    (!matchingPersistedFailure && !matchingPersistedSuccess)
  ) {
    return null;
  }
  if (localJob.upload_request_id) {
    return incomingJob.upload_request_id === localJob.upload_request_id
      ? 0
      : null;
  }
  if (localJob.original_filename !== incomingJob.original_filename) {
    return null;
  }

  const localUpdatedAt = Date.parse(localJob.updated_at);
  const incomingUpdatedAt = Date.parse(incomingJob.updated_at);
  if (!Number.isFinite(localUpdatedAt) || !Number.isFinite(incomingUpdatedAt)) {
    return null;
  }
  const distance = Math.abs(localUpdatedAt - incomingUpdatedAt);
  return distance <= LOCAL_UPLOAD_RECONCILIATION_WINDOW_MS ? distance : null;
}

export function isLocalUploadError(job: JobRecord): boolean {
  return (
    job.id.startsWith("local-error-") &&
    job.parser_provider === "client" &&
    job.status === "error"
  );
}

export function restoredLocalUploadIds(
  current: JobRecord[],
  incoming: JobRecord[],
  currentById: Map<string, JobRecord>,
): Set<string> {
  const localErrors = current.filter(isLocalUploadError);
  const matchedIds = new Set<string>();

  for (const incomingJob of incoming) {
    if (currentById.has(incomingJob.id)) {
      continue;
    }
    let closestMatch: JobRecord | null = null;
    let closestDistance = Number.POSITIVE_INFINITY;
    for (const localJob of localErrors) {
      if (matchedIds.has(localJob.id)) {
        continue;
      }
      const distance = localUploadMatchDistance(localJob, incomingJob);
      if (distance !== null && distance < closestDistance) {
        closestMatch = localJob;
        closestDistance = distance;
      }
    }
    if (closestMatch !== null) {
      matchedIds.add(closestMatch.id);
    }
  }

  return matchedIds;
}

export function reconcileProcessingJobs(
  current: JobRecord[],
  incoming: JobRecord[],
  cachedIds: Set<string>,
  removalCandidateIds: ReadonlySet<string>,
): JobRecord[] {
  const currentById = new Map(current.map((job) => [job.id, job]));
  const incomingIds = new Set(incoming.map((job) => job.id));
  const restoredUploadIds = restoredLocalUploadIds(
    current,
    incoming,
    currentById,
  );
  return [
    ...incoming,
    ...current.filter((job) => {
      if (job.archived_at !== null || isPristineBenchmarkImport(job)) {
        return !incomingIds.has(job.id) && !removalCandidateIds.has(job.id);
      }
      return (
        isLocalUploadError(job) &&
        !cachedIds.has(job.id) &&
        !incomingIds.has(job.id) &&
        !removalCandidateIds.has(job.id) &&
        !restoredUploadIds.has(job.id)
      );
    }),
  ];
}

export function reconcileHistoryItems(
  current: HistoryItem[],
  incoming: HistoryItem[],
): HistoryItem[] {
  const currentById = new Map(current.map((item) => [item.id, item]));
  return incoming.map((item) => {
    const currentItem = currentById.get(item.id);
    return currentItem ? newerHistoryItem(currentItem, item) : item;
  });
}
