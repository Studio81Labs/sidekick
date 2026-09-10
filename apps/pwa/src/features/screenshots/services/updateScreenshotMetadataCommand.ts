import type { QueryClient } from "@tanstack/react-query";

import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import {
  type JobMetadataUpdate,
  updateJobMetadata,
} from "../../../domains/jobs/api/jobsApi";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import {
  assertQueryAccessGenerationCurrent,
  captureQueryAccessGeneration,
} from "../../../shared/api/queryCache";

export type UpdateScreenshotMetadataCommand = {
  administratorToken: string;
  jobId: string;
  metadata: JobMetadataUpdate;
};

export async function updateScreenshotMetadataCommand(
  queryClient: QueryClient,
  command: UpdateScreenshotMetadataCommand,
) {
  const accessGeneration = captureQueryAccessGeneration(queryClient);
  const job = await updateJobMetadata(
    command.jobId,
    command.metadata,
    command.administratorToken,
  );
  const cache = {
    updated: jobQueryKeys.detail(job.id),
    invalidated: [jobQueryKeys.processing(), historyQueryKeys.all] as const,
  };

  assertQueryAccessGenerationCurrent(queryClient, accessGeneration);
  queryClient.setQueryData(cache.updated, job);
  await Promise.all(
    cache.invalidated.map((queryKey) =>
      queryClient.invalidateQueries({ queryKey, refetchType: "none" }),
    ),
  );

  return { job, cache };
}
