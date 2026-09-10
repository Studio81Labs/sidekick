import {
  type QueryClient,
  queryOptions,
  useQuery,
} from "@tanstack/react-query";

import { cacheLatestQueryResult } from "../../../shared/api/queryCache";
import { getJob, getProcessingJobs } from "./jobsApi";

export const jobQueryKeys = {
  all: ["jobs"] as const,
  details: () => [...jobQueryKeys.all, "detail"] as const,
  detail: (jobId: string) => [...jobQueryKeys.details(), jobId] as const,
  processing: () => [...jobQueryKeys.all, "processing"] as const,
  processingPage: (offset: number) =>
    [...jobQueryKeys.processing(), { offset }] as const,
};

export function jobQueryOptions(jobId: string, administratorToken: string) {
  return queryOptions({
    queryFn: ({ signal }) => getJob(jobId, administratorToken, signal),
    queryKey: jobQueryKeys.detail(jobId),
    staleTime: 0,
  });
}

export function processingJobsQueryOptions(
  administratorToken: string,
  offset = 0,
) {
  return queryOptions({
    queryFn: ({ signal }) =>
      getProcessingJobs(offset, administratorToken, signal),
    queryKey: jobQueryKeys.processingPage(offset),
    staleTime: 0,
  });
}

export function fetchJobQuery(
  queryClient: QueryClient,
  jobId: string,
  administratorToken: string,
) {
  return cacheLatestQueryResult(
    queryClient,
    jobQueryKeys.detail(jobId),
    getJob(jobId, administratorToken),
  );
}

export function fetchProcessingJobsQuery(
  queryClient: QueryClient,
  administratorToken: string,
  offset = 0,
) {
  return cacheLatestQueryResult(
    queryClient,
    jobQueryKeys.processingPage(offset),
    getProcessingJobs(offset, administratorToken),
  );
}

export function useJobQuery(
  jobId: string,
  administratorToken: string,
  enabled: boolean,
) {
  return useQuery({ ...jobQueryOptions(jobId, administratorToken), enabled });
}

export function useProcessingJobsQuery(
  administratorToken: string,
  offset = 0,
  enabled = true,
) {
  return useQuery({
    ...processingJobsQueryOptions(administratorToken, offset),
    enabled,
  });
}
