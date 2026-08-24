import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import {
  completeTrainingReview,
  recordTrainingDecision,
  reopenTrainingReview,
  type TrainingDecisionUpdate,
  type TrainingReviewUpdate,
} from "../../../domains/training/api/trainingApi";
import { trainingQueryKeys } from "../../../domains/training/api/trainingQueries";
import { supersedeLatestQueryResults } from "../../../shared/api/queryCache";
import type { JobRecord } from "../../../shared/types/jobs";

export type RecordTrainingDecisionCommand = TrainingDecisionUpdate & {
  jobId: string;
};

export type CompleteTrainingReviewCommand = TrainingReviewUpdate & {
  jobId: string;
};

export type ReopenTrainingReviewCommand = {
  jobId: string;
};

async function applyTrainingJobCacheOutcome(
  queryClient: QueryClient,
  job: JobRecord,
) {
  const cache = {
    updated: jobQueryKeys.detail(job.id),
    invalidated: [
      jobQueryKeys.processing(),
      historyQueryKeys.all,
      trainingQueryKeys.all,
    ] as const,
  };
  const guardedKeys: readonly QueryKey[] = [
    cache.updated,
    ...cache.invalidated,
  ];

  await Promise.all(
    guardedKeys.map((queryKey) =>
      queryClient.cancelQueries({ queryKey, exact: false }),
    ),
  );
  guardedKeys.forEach((queryKey) =>
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

export async function recordTrainingDecisionCommand(
  queryClient: QueryClient,
  command: RecordTrainingDecisionCommand,
) {
  const job = await recordTrainingDecision(
    command.jobId,
    command.action,
    command.sizing,
    command.certainty,
  );
  return applyTrainingJobCacheOutcome(queryClient, job);
}

export async function completeTrainingReviewCommand(
  queryClient: QueryClient,
  command: CompleteTrainingReviewCommand,
) {
  const job = await completeTrainingReview(command.jobId, command.note);
  return applyTrainingJobCacheOutcome(queryClient, job);
}

export async function reopenTrainingReviewCommand(
  queryClient: QueryClient,
  command: ReopenTrainingReviewCommand,
) {
  const job = await reopenTrainingReview(command.jobId);
  return applyTrainingJobCacheOutcome(queryClient, job);
}
