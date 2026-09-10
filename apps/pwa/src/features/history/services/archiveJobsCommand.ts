import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { archiveJobs } from "../../../domains/history/api/historyApi";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import {
  assertQueryAccessGenerationCurrent,
  captureQueryAccessGeneration,
  supersedeLatestQueryResults,
} from "../../../shared/api/queryCache";

export async function archiveJobsCommand(
  queryClient: QueryClient,
  jobIds: string[],
  administratorToken: string,
) {
  const accessGeneration = captureQueryAccessGeneration(queryClient);
  const history = await archiveJobs(jobIds, administratorToken);
  const detailKeys = jobIds.map((jobId) => jobQueryKeys.detail(jobId));
  const projectionKeys = [
    jobQueryKeys.processing(),
    historyQueryKeys.pages(),
  ] as const;
  const invalidated: QueryKey[] = [...detailKeys, ...projectionKeys];

  assertQueryAccessGenerationCurrent(queryClient, accessGeneration);
  for (const queryKey of invalidated) {
    supersedeLatestQueryResults(queryClient, queryKey);
  }
  await Promise.all(
    invalidated.map((queryKey, index) =>
      queryClient.cancelQueries({
        queryKey,
        exact: index < detailKeys.length,
      }),
    ),
  );
  assertQueryAccessGenerationCurrent(queryClient, accessGeneration);
  await Promise.all(
    invalidated.map((queryKey, index) =>
      queryClient.invalidateQueries({
        queryKey,
        exact: index < detailKeys.length,
        refetchType: "none",
      }),
    ),
  );

  assertQueryAccessGenerationCurrent(queryClient, accessGeneration);
  const updated = history.jobs.map((job) => jobQueryKeys.detail(job.id));
  for (const job of history.jobs) {
    queryClient.setQueryData(jobQueryKeys.detail(job.id), job);
  }
  const replaced = historyQueryKeys.page();
  queryClient.setQueryData(replaced, history);

  return {
    history,
    cache: {
      invalidated,
      replaced,
      superseded: invalidated,
      updated,
    },
  };
}
