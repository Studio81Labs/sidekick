import type { QueryClient } from "@tanstack/react-query";

import { uploadScreenshot } from "../../../domains/jobs/api/jobsApi";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { supersedeLatestQueryResults } from "../../../shared/api/queryCache";
import type { PipelineSelection } from "../../../shared/types/pipeline";

export type UploadScreenshotCommand = {
  file: File;
  pipeline?: PipelineSelection;
  requestId: string;
  signal?: AbortSignal;
};

export async function uploadScreenshotCommand(
  queryClient: QueryClient,
  command: UploadScreenshotCommand,
) {
  const job = await uploadScreenshot(
    command.file,
    command.requestId,
    command.signal,
    command.pipeline,
  );
  const cache = {
    updated: jobQueryKeys.detail(job.id),
    invalidated: [jobQueryKeys.processing()] as const,
  };
  const guarded = [cache.updated, ...cache.invalidated] as const;

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
