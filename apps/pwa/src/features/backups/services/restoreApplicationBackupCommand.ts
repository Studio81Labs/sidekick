import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { restoreApplicationBackup } from "../../../domains/backups/api/backupsApi";
import { benchmarkQueryKeys } from "../../../domains/benchmarks/api/benchmarksQueries";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import {
  assertQueryAccessGenerationCurrent,
  captureQueryAccessGeneration,
  supersedeLatestQueryResults,
} from "../../../shared/api/queryCache";

export type RestoreApplicationBackupCommand = {
  administratorToken: string;
  file: File;
};

export async function restoreApplicationBackupCommand(
  queryClient: QueryClient,
  command: RestoreApplicationBackupCommand,
) {
  const accessGeneration = captureQueryAccessGeneration(queryClient);
  const result = await restoreApplicationBackup(
    command.file,
    command.administratorToken,
  );
  const cache = {
    removed: [
      jobQueryKeys.all,
      historyQueryKeys.all,
      benchmarkQueryKeys.all,
    ] as readonly QueryKey[],
  };

  await Promise.all(
    cache.removed.map((queryKey) =>
      queryClient.cancelQueries({ queryKey, exact: false }),
    ),
  );
  assertQueryAccessGenerationCurrent(queryClient, accessGeneration);
  cache.removed.forEach((queryKey) => {
    supersedeLatestQueryResults(queryClient, queryKey);
    queryClient.removeQueries({ queryKey, exact: false });
  });

  return { result, cache };
}
