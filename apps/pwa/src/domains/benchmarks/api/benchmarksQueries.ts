import {
  type QueryClient,
  queryOptions,
  useQuery,
} from "@tanstack/react-query";

import { cacheLatestQueryResult } from "../../../shared/api/queryCache";
import {
  getBenchmarkDatasetImport,
  getBenchmarkOverview,
  getBenchmarkReport,
  type ParserPipeline,
} from "./benchmarksApi";

function pipelineKey(pipeline?: ParserPipeline) {
  return pipeline
    ? {
        parserProvider: pipeline.parser_provider,
        parserLayoutProfile: pipeline.parser_layout_profile,
      }
    : null;
}

export const benchmarkQueryKeys = {
  all: ["benchmarks"] as const,
  overviews: () => [...benchmarkQueryKeys.all, "overview"] as const,
  overview: (pipeline?: ParserPipeline) =>
    [...benchmarkQueryKeys.overviews(), pipelineKey(pipeline)] as const,
  reports: () => [...benchmarkQueryKeys.all, "report"] as const,
  report: (reportId: string) =>
    [...benchmarkQueryKeys.reports(), reportId] as const,
  imports: () => [...benchmarkQueryKeys.all, "import"] as const,
  importReceipt: (requestId: string) =>
    [...benchmarkQueryKeys.imports(), requestId] as const,
};

export function benchmarkOverviewQueryOptions(
  administratorToken: string,
  pipeline: ParserPipeline | undefined,
  includeSignal = true,
) {
  return queryOptions({
    queryKey: benchmarkQueryKeys.overview(pipeline),
    queryFn: ({ signal }) =>
      getBenchmarkOverview(
        pipeline,
        administratorToken,
        includeSignal ? signal : undefined,
      ),
    ...(includeSignal ? {} : { retry: false }),
    staleTime: 0,
  });
}

export function benchmarkReportQueryOptions(
  reportId: string,
  administratorToken: string,
  includeSignal = true,
) {
  return queryOptions({
    queryKey: benchmarkQueryKeys.report(reportId),
    queryFn: ({ signal }) =>
      getBenchmarkReport(
        reportId,
        administratorToken,
        includeSignal ? signal : undefined,
      ),
    ...(includeSignal ? {} : { retry: false }),
    staleTime: 0,
  });
}

export function benchmarkImportReceiptQueryOptions(
  requestId: string,
  administratorToken: string,
  includeSignal = true,
) {
  return queryOptions({
    queryKey: benchmarkQueryKeys.importReceipt(requestId),
    queryFn: ({ signal }) =>
      getBenchmarkDatasetImport(
        requestId,
        administratorToken,
        includeSignal ? signal : undefined,
      ),
    ...(includeSignal ? {} : { retry: false }),
    staleTime: 0,
  });
}

export function fetchBenchmarkImportReceiptQuery(
  queryClient: QueryClient,
  requestId: string,
  administratorToken: string,
) {
  return cacheLatestQueryResult(
    queryClient,
    benchmarkQueryKeys.importReceipt(requestId),
    getBenchmarkDatasetImport(requestId, administratorToken),
  );
}

export function useBenchmarkOverviewQuery(
  administratorToken: string,
  pipeline: ParserPipeline | undefined,
  enabled = true,
) {
  return useQuery({
    ...benchmarkOverviewQueryOptions(administratorToken, pipeline),
    enabled,
  });
}

export function useBenchmarkReportQuery(
  reportId: string,
  administratorToken: string,
  enabled = true,
) {
  return useQuery({
    ...benchmarkReportQueryOptions(reportId, administratorToken),
    enabled,
  });
}

export function useBenchmarkImportReceiptQuery(
  requestId: string,
  administratorToken: string,
  enabled = true,
) {
  return useQuery({
    ...benchmarkImportReceiptQueryOptions(requestId, administratorToken),
    enabled,
  });
}
