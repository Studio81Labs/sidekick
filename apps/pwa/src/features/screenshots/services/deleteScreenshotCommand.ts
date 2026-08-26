import type { QueryClient } from "@tanstack/react-query";

import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { deleteJob } from "../../../domains/jobs/api/jobsApi";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import {
  supersedeLatestQueryResults,
  supersedeLatestQueryWrites,
} from "../../../shared/api/queryCache";

export async function deleteScreenshotCommand(
  queryClient: QueryClient,
  jobId: string,
) {
  await deleteJob(jobId);
  const cache = {
    removed: jobQueryKeys.detail(jobId),
    invalidated: [jobQueryKeys.processing(), historyQueryKeys.all] as const,
  };
  const superseded = [cache.removed, ...cache.invalidated] as const;

  supersedeLatestQueryWrites(queryClient, cache.removed);
  for (const queryKey of superseded) {
    supersedeLatestQueryResults(queryClient, queryKey);
  }
  await Promise.all([
    queryClient.cancelQueries({ queryKey: cache.removed, exact: true }),
    ...cache.invalidated.map((queryKey) =>
      queryClient.cancelQueries({ queryKey }),
    ),
  ]);

  queryClient.removeQueries({ queryKey: cache.removed, exact: true });
  await Promise.all(
    cache.invalidated.map((queryKey) =>
      queryClient.invalidateQueries({ queryKey, refetchType: "none" }),
    ),
  );

  return { jobId, cache: { ...cache, superseded } };
}
