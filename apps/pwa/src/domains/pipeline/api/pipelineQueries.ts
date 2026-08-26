import { queryOptions, useQuery } from "@tanstack/react-query";

import { getPipelineCapabilities } from "./pipelineApi";

export const pipelineQueryKeys = {
  all: ["pipeline"] as const,
  capabilities: () => [...pipelineQueryKeys.all, "capabilities"] as const,
};

export function pipelineCapabilitiesQueryOptions() {
  return queryOptions({
    gcTime: 30 * 60 * 1_000,
    queryFn: ({ signal }) => getPipelineCapabilities(signal),
    queryKey: pipelineQueryKeys.capabilities(),
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function usePipelineCapabilitiesQuery(enabled: boolean) {
  return useQuery({ ...pipelineCapabilitiesQueryOptions(), enabled });
}
