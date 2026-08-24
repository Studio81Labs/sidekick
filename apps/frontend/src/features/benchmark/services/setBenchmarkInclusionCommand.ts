import type { QueryClient } from "@tanstack/react-query";

import {
  type BenchmarkInclusionUpdate,
  setBenchmarkInclusion,
} from "../../../domains/benchmarks/api/benchmarksApi";
import { benchmarkQueryKeys } from "../../../domains/benchmarks/api/benchmarksQueries";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";

export type SetBenchmarkInclusionCommand = BenchmarkInclusionUpdate & {
  jobId: string;
};

export async function setBenchmarkInclusionCommand(
  queryClient: QueryClient,
  command: SetBenchmarkInclusionCommand,
) {
  const job = await setBenchmarkInclusion(command.jobId, {
    included: command.included,
  });
  const cache = {
    updated: jobQueryKeys.detail(job.id),
    invalidated: [
      jobQueryKeys.processing(),
      historyQueryKeys.all,
      benchmarkQueryKeys.overviews(),
    ] as const,
  };

  queryClient.setQueryData(cache.updated, job);
  await Promise.all(
    cache.invalidated.map((queryKey) =>
      queryClient.invalidateQueries({ queryKey, refetchType: "none" }),
    ),
  );

  return { job, cache };
}
