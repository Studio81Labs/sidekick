import type { QueryClient } from "@tanstack/react-query";

import {
  type ParserPipeline,
  runParserBenchmark,
} from "../../../domains/benchmarks/api/benchmarksApi";
import { benchmarkQueryKeys } from "../../../domains/benchmarks/api/benchmarksQueries";

export type RunParserBenchmarkCommand = {
  pipeline?: ParserPipeline;
};

export async function runParserBenchmarkCommand(
  queryClient: QueryClient,
  command: RunParserBenchmarkCommand,
) {
  const report = await runParserBenchmark(command.pipeline);
  const cache = { invalidated: [benchmarkQueryKeys.overviews()] as const };

  await Promise.all(
    cache.invalidated.map((queryKey) =>
      queryClient.invalidateQueries({ queryKey, refetchType: "none" }),
    ),
  );

  return { report, cache };
}
