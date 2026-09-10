import type { QueryClient } from "@tanstack/react-query";

import {
  type BenchmarkInclusionUpdate,
  setBenchmarkInclusion,
} from "../../../domains/benchmarks/api/benchmarksApi";
import { benchmarkQueryKeys } from "../../../domains/benchmarks/api/benchmarksQueries";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import {
  assertQueryAccessGenerationCurrent,
  captureQueryAccessGeneration,
} from "../../../shared/api/queryCache";

export type SetBenchmarkInclusionCommand = BenchmarkInclusionUpdate & {
  administratorToken: string;
  jobId: string;
};

export async function setBenchmarkInclusionCommand(
  queryClient: QueryClient,
  command: SetBenchmarkInclusionCommand,
) {
  const accessGeneration = captureQueryAccessGeneration(queryClient);
  const job = await setBenchmarkInclusion(
    command.jobId,
    command.included,
    command.administratorToken,
  );
  const cache = {
    updated: jobQueryKeys.detail(job.id),
    invalidated: [
      jobQueryKeys.processing(),
      historyQueryKeys.all,
      benchmarkQueryKeys.overviews(),
    ] as const,
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
