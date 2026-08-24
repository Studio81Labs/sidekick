import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { approveState } from "../../../domains/jobs/api/jobsApi";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { requestRecommendation } from "../../../domains/recommendations/api/recommendationsApi";
import { trainingQueryKeys } from "../../../domains/training/api/trainingQueries";
import { supersedeLatestQueryResults } from "../../../shared/api/queryCache";
import type { JobRecord } from "../../../shared/types/jobs";
import type { CanonicalState } from "../../../shared/types/poker";

export type ApproveStateCommand = {
  jobId: string;
  signal?: AbortSignal;
  state: CanonicalState;
};

export type RequestRecommendationCommand = {
  jobId: string;
  requestId: string;
  signal?: AbortSignal;
};

function preserveNewerCachedMetadata(
  incoming: JobRecord,
  current: JobRecord | undefined,
): JobRecord {
  const currentUpdatedAt = current
    ? Date.parse(current.updated_at)
    : Number.NaN;
  const incomingUpdatedAt = Date.parse(incoming.updated_at);
  return current &&
    Number.isFinite(currentUpdatedAt) &&
    (!Number.isFinite(incomingUpdatedAt) ||
      currentUpdatedAt > incomingUpdatedAt)
    ? {
        ...incoming,
        title: current.title ?? null,
        notes: current.notes ?? null,
        tags: current.tags,
        updated_at: current.updated_at,
      }
    : incoming;
}

async function applyHandWorkflowCacheOutcome(
  queryClient: QueryClient,
  job: JobRecord,
  invalidateTraining: boolean,
) {
  const invalidated: QueryKey[] = [
    jobQueryKeys.processing(),
    historyQueryKeys.all,
  ];
  if (invalidateTraining) {
    invalidated.push(trainingQueryKeys.all);
  }
  const cache = {
    updated: jobQueryKeys.detail(job.id),
    invalidated,
  };
  const guarded = [cache.updated, ...cache.invalidated];

  await Promise.all(
    guarded.map((queryKey) =>
      queryClient.cancelQueries({ queryKey, exact: false }),
    ),
  );
  guarded.forEach((queryKey) =>
    supersedeLatestQueryResults(queryClient, queryKey),
  );
  const cachedJob = queryClient.getQueryData<JobRecord>(cache.updated);
  queryClient.setQueryData(
    cache.updated,
    preserveNewerCachedMetadata(job, cachedJob),
  );
  await Promise.all(
    cache.invalidated.map((queryKey) =>
      queryClient.invalidateQueries({ queryKey, refetchType: "none" }),
    ),
  );

  return { job, cache };
}

export async function approveStateCommand(
  queryClient: QueryClient,
  command: ApproveStateCommand,
) {
  const job = await approveState(command.jobId, command.state, command.signal);
  return applyHandWorkflowCacheOutcome(queryClient, job, true);
}

export async function requestRecommendationCommand(
  queryClient: QueryClient,
  command: RequestRecommendationCommand,
) {
  const job = await requestRecommendation(
    command.jobId,
    command.requestId,
    command.signal,
  );
  return applyHandWorkflowCacheOutcome(queryClient, job, true);
}
