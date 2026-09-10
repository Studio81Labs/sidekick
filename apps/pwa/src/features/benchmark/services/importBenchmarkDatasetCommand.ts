import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { importBenchmarkDataset } from "../../../domains/benchmarks/api/benchmarksApi";
import { benchmarkQueryKeys } from "../../../domains/benchmarks/api/benchmarksQueries";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import {
  assertQueryAccessGenerationCurrent,
  captureQueryAccessGeneration,
  supersedeLatestQueryResults,
} from "../../../shared/api/queryCache";

export type ImportBenchmarkDatasetCommand = {
  administratorToken: string;
  file: File;
  requestId: string;
};

export async function importBenchmarkDatasetCommand(
  queryClient: QueryClient,
  command: ImportBenchmarkDatasetCommand,
) {
  const accessGeneration = captureQueryAccessGeneration(queryClient);
  const result = await importBenchmarkDataset(
    command.file,
    command.requestId,
    command.administratorToken,
  );
  const detailKeys = [...new Set(result.job_ids)].map((jobId) =>
    jobQueryKeys.detail(jobId),
  );
  const cache = {
    invalidated: [
      ...detailKeys,
      jobQueryKeys.processing(),
      historyQueryKeys.all,
      benchmarkQueryKeys.overviews(),
    ] as readonly QueryKey[],
  };

  assertQueryAccessGenerationCurrent(queryClient, accessGeneration);
  await Promise.all(
    cache.invalidated.map((queryKey) =>
      queryClient.cancelQueries({ queryKey, exact: false }),
    ),
  );
  cache.invalidated.forEach((queryKey) =>
    supersedeLatestQueryResults(queryClient, queryKey),
  );
  assertQueryAccessGenerationCurrent(queryClient, accessGeneration);
  await Promise.all(
    cache.invalidated.map((queryKey) =>
      queryClient.invalidateQueries({ queryKey, refetchType: "none" }),
    ),
  );

  return { result, cache };
}
