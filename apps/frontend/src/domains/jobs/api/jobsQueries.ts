import {
  type QueryClient,
  queryOptions,
  useQuery,
} from "@tanstack/react-query";

import { getJob, getProcessingJobs } from "./jobsApi";

export const jobQueryKeys = {
  all: ["jobs"] as const,
  details: () => [...jobQueryKeys.all, "detail"] as const,
  detail: (jobId: string) => [...jobQueryKeys.details(), jobId] as const,
  processing: () => [...jobQueryKeys.all, "processing"] as const,
  processingPage: (offset: number) =>
    [...jobQueryKeys.processing(), { offset }] as const,
};

export function jobQueryOptions(jobId: string, includeSignal = true) {
  return queryOptions({
    queryFn: ({ signal }) =>
      includeSignal ? getJob(jobId, signal) : getJob(jobId),
    queryKey: jobQueryKeys.detail(jobId),
    ...(includeSignal ? {} : { retry: false }),
    staleTime: 0,
  });
}

export function processingJobsQueryOptions(offset = 0, includeSignal = true) {
  return queryOptions({
    queryFn: ({ signal }) =>
      includeSignal
        ? getProcessingJobs(offset, signal)
        : getProcessingJobs(offset),
    queryKey: jobQueryKeys.processingPage(offset),
    ...(includeSignal ? {} : { retry: false }),
    staleTime: 0,
  });
}

export function fetchJobQuery(queryClient: QueryClient, jobId: string) {
  const options = jobQueryOptions(jobId, false);
  queryClient.removeQueries({ queryKey: options.queryKey, exact: true });
  return queryClient.fetchQuery(options);
}

export function fetchProcessingJobsQuery(queryClient: QueryClient, offset = 0) {
  const options = processingJobsQueryOptions(offset, false);
  queryClient.removeQueries({ queryKey: options.queryKey, exact: true });
  return queryClient.fetchQuery(options);
}

export function useJobQuery(jobId: string, enabled: boolean) {
  return useQuery({ ...jobQueryOptions(jobId), enabled });
}

export function useProcessingJobsQuery(offset = 0, enabled = true) {
  return useQuery({ ...processingJobsQueryOptions(offset), enabled });
}
