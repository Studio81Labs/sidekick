import type { QueryClient, QueryKey } from "@tanstack/react-query";

type LatestRequest = {
  queryKey: QueryKey;
  token: object;
};

const latestRequests = new WeakMap<QueryClient, Map<string, LatestRequest>>();

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

export async function cacheLatestQueryResult<T>(
  queryClient: QueryClient,
  queryKey: QueryKey,
  request: Promise<T>,
): Promise<T> {
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
