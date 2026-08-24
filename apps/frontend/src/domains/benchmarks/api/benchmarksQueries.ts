import { queryOptions, useQuery } from "@tanstack/react-query";

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
  pipeline?: ParserPipeline,
  includeSignal = true,
) {
  return queryOptions({
    queryKey: benchmarkQueryKeys.overview(pipeline),
    queryFn: ({ signal }) =>
      getBenchmarkOverview(pipeline, includeSignal ? signal : undefined),
    ...(includeSignal ? {} : { retry: false }),
    staleTime: 0,
  });
}

export function benchmarkReportQueryOptions(
  reportId: string,
  includeSignal = true,
) {
  return queryOptions({
    queryKey: benchmarkQueryKeys.report(reportId),
    queryFn: ({ signal }) =>
      getBenchmarkReport(reportId, includeSignal ? signal : undefined),
    ...(includeSignal ? {} : { retry: false }),
    staleTime: 0,
  });
}

export function benchmarkImportReceiptQueryOptions(
  requestId: string,
  includeSignal = true,
) {
  return queryOptions({
    queryKey: benchmarkQueryKeys.importReceipt(requestId),
    queryFn: ({ signal }) =>
      getBenchmarkDatasetImport(requestId, includeSignal ? signal : undefined),
    ...(includeSignal ? {} : { retry: false }),
    staleTime: 0,
  });
}

export function useBenchmarkOverviewQuery(
  pipeline?: ParserPipeline,
  enabled = true,
) {
  return useQuery({
    ...benchmarkOverviewQueryOptions(pipeline),
    enabled,
  });
}

export function useBenchmarkReportQuery(reportId: string, enabled = true) {
  return useQuery({
    ...benchmarkReportQueryOptions(reportId),
    enabled,
  });
}

export function useBenchmarkImportReceiptQuery(
  requestId: string,
  enabled = true,
) {
  return useQuery({
    ...benchmarkImportReceiptQueryOptions(requestId),
    enabled,
  });
}
