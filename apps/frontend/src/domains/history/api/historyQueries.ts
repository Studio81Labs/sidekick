import {
  type QueryClient,
  queryOptions,
  useQuery,
} from "@tanstack/react-query";

import { cacheLatestQueryResult } from "../../../shared/api/queryCache";
import { getHistory } from "./historyApi";

export const historyQueryKeys = {
  all: ["history"] as const,
  pages: () => [...historyQueryKeys.all, "page"] as const,
  page: (offset = 0, query = "", limit?: number) =>
    [
      ...historyQueryKeys.pages(),
      { offset, query: query.trim(), limit: limit ?? null },
    ] as const,
};

export function historyPageQueryOptions(
  offset = 0,
  query = "",
  limit?: number,
) {
  return queryOptions({
    queryKey: historyQueryKeys.page(offset, query, limit),
    queryFn: ({ signal }) => getHistory(offset, query, limit, signal),
    staleTime: 0,
  });
}

export function fetchHistoryPageQuery(
  queryClient: QueryClient,
  offset = 0,
  query = "",
  limit?: number,
) {
  return cacheLatestQueryResult(
    queryClient,
    historyQueryKeys.page(offset, query, limit),
    getHistory(offset, query, limit),
  );
}

export function useHistoryPageQuery(
  offset = 0,
  query = "",
  limit?: number,
  enabled = true,
) {
  return useQuery({
    ...historyPageQueryOptions(offset, query, limit),
    enabled,
  });
}
