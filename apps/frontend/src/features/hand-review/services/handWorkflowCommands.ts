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
  queryClient.setQueryData(cache.updated, job);
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
  return applyHandWorkflowCacheOutcome(queryClient, job, false);
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
