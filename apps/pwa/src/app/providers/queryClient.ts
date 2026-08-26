import { QueryClient } from "@tanstack/react-query";

export const queryClientDefaults = {
  mutations: {
    retry: false,
  },
  queries: {
    gcTime: 5 * 60 * 1_000,
    refetchOnReconnect: true,
    refetchOnWindowFocus: true,
    retry: 1,
    staleTime: 30 * 1_000,
  },
} as const;

export function createQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: queryClientDefaults });
}
