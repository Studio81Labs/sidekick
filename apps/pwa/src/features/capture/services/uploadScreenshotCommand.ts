import type { QueryClient } from "@tanstack/react-query";

import { uploadScreenshot } from "../../../domains/jobs/api/jobsApi";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import {
  assertQueryAccessGenerationCurrent,
  captureQueryAccessGeneration,
  supersedeLatestQueryResults,
} from "../../../shared/api/queryCache";
import type { PipelineSelection } from "../../../shared/types/pipeline";

export type UploadScreenshotCommand = {
  administratorToken: string;
  file: File;
  pipeline?: PipelineSelection;
  requestId: string;
  signal?: AbortSignal;
};

export async function uploadScreenshotCommand(
  queryClient: QueryClient,
  command: UploadScreenshotCommand,
) {
  const accessGeneration = captureQueryAccessGeneration(queryClient);
  const job = await uploadScreenshot(
    command.file,
    command.requestId,
    command.administratorToken,
    command.signal,
    command.pipeline,
  );
  const cache = {
    updated: jobQueryKeys.detail(job.id),
    invalidated: [jobQueryKeys.processing()] as const,
  };
  const guarded = [cache.updated, ...cache.invalidated] as const;

  assertQueryAccessGenerationCurrent(queryClient, accessGeneration);
  await Promise.all(
    guarded.map((queryKey) =>
      queryClient.cancelQueries({ queryKey, exact: false }),
    ),
  );
  assertQueryAccessGenerationCurrent(queryClient, accessGeneration);
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
