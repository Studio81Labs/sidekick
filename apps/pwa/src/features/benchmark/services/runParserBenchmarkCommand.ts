import type { QueryClient } from "@tanstack/react-query";

import {
  type ParserPipeline,
  runParserBenchmark,
} from "../../../domains/benchmarks/api/benchmarksApi";
import { benchmarkQueryKeys } from "../../../domains/benchmarks/api/benchmarksQueries";
import {
  assertQueryAccessGenerationCurrent,
  captureQueryAccessGeneration,
} from "../../../shared/api/queryCache";

export type RunParserBenchmarkCommand = {
  administratorToken: string;
  pipeline?: ParserPipeline;
};

export async function runParserBenchmarkCommand(
  queryClient: QueryClient,
  command: RunParserBenchmarkCommand,
) {
  const accessGeneration = captureQueryAccessGeneration(queryClient);
  const report = await runParserBenchmark(
    command.pipeline,
    command.administratorToken,
  );
  const cache = { invalidated: [benchmarkQueryKeys.overviews()] as const };

  assertQueryAccessGenerationCurrent(queryClient, accessGeneration);
  await Promise.all(
    cache.invalidated.map((queryKey) =>
      queryClient.invalidateQueries({ queryKey, refetchType: "none" }),
    ),
  );

  return { report, cache };
}
