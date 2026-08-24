import type { QueryClient, QueryKey } from "@tanstack/react-query";

const latestRequests = new WeakMap<QueryClient, Map<string, object>>();

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
  requestsByKey.set(queryHash, requestToken);

  try {
    const result = await request;
    if (requestsByKey.get(queryHash) === requestToken) {
      queryClient.setQueryData(queryKey, result);
    }
    return result;
  } finally {
    if (requestsByKey.get(queryHash) === requestToken) {
      requestsByKey.delete(queryHash);
    }
  }
}
