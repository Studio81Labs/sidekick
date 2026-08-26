import { queryOptions, useQuery } from "@tanstack/react-query";

import { getSystemInfo } from "./systemApi";

export const systemQueryKeys = {
  all: ["system"] as const,
  information: () => [...systemQueryKeys.all, "information"] as const,
};

export function systemInfoQueryOptions() {
  return queryOptions({
    gcTime: 30 * 60 * 1_000,
    queryFn: ({ signal }) => getSystemInfo(signal),
    queryKey: systemQueryKeys.information(),
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function useSystemInfoQuery(enabled: boolean) {
  return useQuery({ ...systemInfoQueryOptions(), enabled });
}
