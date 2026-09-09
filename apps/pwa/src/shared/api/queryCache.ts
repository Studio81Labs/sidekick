import type { QueryClient, QueryKey } from "@tanstack/react-query";

type LatestRequest = {
  queryKey: QueryKey;
  token: object;
};

const latestRequests = new WeakMap<QueryClient, Map<string, LatestRequest>>();
const latestWrites = new WeakMap<QueryClient, Map<string, LatestRequest>>();
const accessGenerations = new WeakMap<QueryClient, object>();

export class QueryAccessGenerationSupersededError extends Error {
  constructor() {
    super("Administrator access changed before this operation completed");
    this.name = "QueryAccessGenerationSupersededError";
  }
}

function currentAccessGeneration(queryClient: QueryClient): object {
  let generation = accessGenerations.get(queryClient);
  if (!generation) {
    generation = {};
    accessGenerations.set(queryClient, generation);
  }
  return generation;
}

/** Captures the administrator-access generation before an async mutation starts. */
export function captureQueryAccessGeneration(queryClient: QueryClient): object {
  return currentAccessGeneration(queryClient);
}

export function queryAccessGenerationIsCurrent(
  queryClient: QueryClient,
  generation: object,
): boolean {
  return currentAccessGeneration(queryClient) === generation;
}

/** Prevents prior administrator mutations from repopulating a cleared cache. */
export function supersedeQueryAccessGeneration(queryClient: QueryClient): void {
  accessGenerations.set(queryClient, {});
}

export function assertQueryAccessGenerationCurrent(
  queryClient: QueryClient,
  generation: object,
): void {
  if (!queryAccessGenerationIsCurrent(queryClient, generation)) {
    throw new QueryAccessGenerationSupersededError();
  }
}

export function isQueryAccessGenerationSuperseded(
  error: unknown,
): error is QueryAccessGenerationSupersededError {
  return error instanceof QueryAccessGenerationSupersededError;
}

function queryKeyStartsWith(
  queryKey: QueryKey,
  queryKeyPrefix: QueryKey,
): boolean {
  return (
    queryKeyPrefix.length <= queryKey.length &&
    queryKeyPrefix.every(
      (part, index) => JSON.stringify(part) === JSON.stringify(queryKey[index]),
    )
  );
}

export function supersedeLatestQueryResults(
  queryClient: QueryClient,
  queryKeyPrefix: QueryKey,
): void {
  const requestsByKey = latestRequests.get(queryClient);
  if (!requestsByKey) {
    return;
  }
  for (const [queryHash, request] of requestsByKey) {
    if (queryKeyStartsWith(request.queryKey, queryKeyPrefix)) {
      requestsByKey.delete(queryHash);
    }
  }
}

export function beginLatestQueryWrite(
  queryClient: QueryClient,
  queryKey: QueryKey,
): object {
  let writesByKey = latestWrites.get(queryClient);
  if (!writesByKey) {
    writesByKey = new Map();
    latestWrites.set(queryClient, writesByKey);
  }
  const token = {};
  writesByKey.set(JSON.stringify(queryKey), { queryKey, token });
  return token;
}

export function latestQueryWriteIsCurrent(
  queryClient: QueryClient,
  queryKey: QueryKey,
  token: object,
): boolean {
  return (
    latestWrites.get(queryClient)?.get(JSON.stringify(queryKey))?.token ===
    token
  );
}

export function finishLatestQueryWrite(
  queryClient: QueryClient,
  queryKey: QueryKey,
  token: object,
): void {
  const writesByKey = latestWrites.get(queryClient);
  const queryHash = JSON.stringify(queryKey);
  if (writesByKey?.get(queryHash)?.token === token) {
    writesByKey.delete(queryHash);
  }
}

export function supersedeLatestQueryWrites(
  queryClient: QueryClient,
  queryKeyPrefix: QueryKey,
): void {
  const writesByKey = latestWrites.get(queryClient);
  if (!writesByKey) {
    return;
  }
  for (const [queryHash, write] of writesByKey) {
    if (queryKeyStartsWith(write.queryKey, queryKeyPrefix)) {
      writesByKey.delete(queryHash);
    }
  }
}

export async function cacheLatestQueryResult<T>(
  queryClient: QueryClient,
  queryKey: QueryKey,
  request: Promise<T>,
): Promise<T> {
  const accessGeneration = captureQueryAccessGeneration(queryClient);
  let requestsByKey = latestRequests.get(queryClient);
  if (!requestsByKey) {
    requestsByKey = new Map();
    latestRequests.set(queryClient, requestsByKey);
  }
  const queryHash = JSON.stringify(queryKey);
  const requestToken = {};
  requestsByKey.set(queryHash, { queryKey, token: requestToken });

  try {
    const result = await request;
    assertQueryAccessGenerationCurrent(queryClient, accessGeneration);
    if (requestsByKey.get(queryHash)?.token === requestToken) {
      queryClient.setQueryData(queryKey, result);
    }
    return result;
  } finally {
    if (requestsByKey.get(queryHash)?.token === requestToken) {
      requestsByKey.delete(queryHash);
    }
  }
}
