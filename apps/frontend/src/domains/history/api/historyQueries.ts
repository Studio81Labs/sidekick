import {
  type QueryClient,
  queryOptions,
  useQuery,
} from "@tanstack/react-query";

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
  includeSignal = true,
) {
  return queryOptions({
    queryKey: historyQueryKeys.page(offset, query, limit),
    queryFn: ({ signal }) =>
      includeSignal
        ? getHistory(offset, query, limit, signal)
        : getHistory(offset, query, limit),
    ...(includeSignal ? {} : { retry: false }),
    staleTime: 0,
  });
}

export function fetchHistoryPageQuery(
  queryClient: QueryClient,
  offset = 0,
  query = "",
  limit?: number,
) {
  const options = historyPageQueryOptions(offset, query, limit, false);
  queryClient.removeQueries({ queryKey: options.queryKey, exact: true });
  return queryClient.fetchQuery(options);
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
