import type { QueryClient } from "@tanstack/react-query";

import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { deleteJob } from "../../../domains/jobs/api/jobsApi";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";

export async function deleteScreenshotCommand(
  queryClient: QueryClient,
  jobId: string,
) {
  await deleteJob(jobId);
  const cache = {
    removed: jobQueryKeys.detail(jobId),
    invalidated: [jobQueryKeys.processing(), historyQueryKeys.all] as const,
  };

  queryClient.removeQueries({ queryKey: cache.removed, exact: true });
  await Promise.all(
    cache.invalidated.map((queryKey) =>
      queryClient.invalidateQueries({ queryKey, refetchType: "none" }),
    ),
  );

  return { jobId, cache };
}
