import type { components } from "@poker-hero/openapi-client";
import { apiUrl } from "../../../shared/api/core";
import {
  type JsonRequestOptions,
  requestJson,
} from "../../../shared/api/transport";
import type {
  BenchmarkDatasetImportResult,
  BenchmarkDatasetImportReceipt,
  BenchmarkOverview,
  BenchmarkReport,
} from "../../../shared/types/benchmarks";
import type { JobRecord } from "../../../shared/types/jobs";
import type { PipelineSelection } from "../../../shared/types/pipeline";
import { toJobRecord } from "../../jobs/api/jobsApi";

export type ParserPipeline = Pick<
  PipelineSelection,
  "parser_provider" | "parser_layout_profile"
>;

export function benchmarkDatasetUrl(pipeline?: ParserPipeline): string {
  const url = apiUrl("/api/benchmarks/export");
  if (!pipeline) {
    return url;
  }
  const search = new URLSearchParams({
    parser_provider: pipeline.parser_provider,
    parser_layout_profile: pipeline.parser_layout_profile,
  });
  return `${url}?${search.toString()}`;
}

type BenchmarkOverviewResponse = components["schemas"]["BenchmarkOverview"];
type BenchmarkReportResponse = components["schemas"]["BenchmarkReport"];
type BenchmarkDatasetImportReceiptResponse =
  components["schemas"]["BenchmarkDatasetImportReceipt"];
type BenchmarkDatasetImportResultResponse =
  components["schemas"]["BenchmarkDatasetImportResult"];
type JobRecordResponse = components["schemas"]["JobRecord"];
export type BenchmarkInclusionUpdate = Required<
  Pick<components["schemas"]["BenchmarkSelectionRequest"], "included">
>;

export function toBenchmarkOverview(
  response: BenchmarkOverviewResponse,
): BenchmarkOverview {
  return response as unknown as BenchmarkOverview;
}

export function toBenchmarkReport(
  response: BenchmarkReportResponse,
): BenchmarkReport {
  return response as unknown as BenchmarkReport;
}

export function toBenchmarkDatasetImportReceipt(
  response: BenchmarkDatasetImportReceiptResponse,
): BenchmarkDatasetImportReceipt {
  return response as unknown as BenchmarkDatasetImportReceipt;
}

export function toBenchmarkDatasetImportResult(
  response: BenchmarkDatasetImportResultResponse,
): BenchmarkDatasetImportResult {
  return response as BenchmarkDatasetImportResult;
}

export async function getBenchmarkOverview(
  pipeline?: ParserPipeline,
  signal?: AbortSignal,
): Promise<BenchmarkOverview> {
  const search = new URLSearchParams();
  if (pipeline) {
    search.set("parser_provider", pipeline.parser_provider);
    search.set("parser_layout_profile", pipeline.parser_layout_profile);
  }
  const query = search.size > 0 ? `?${search.toString()}` : "";
  const response = await requestJson<BenchmarkOverviewResponse>(
    `/api/benchmarks${query}`,
    signal ? { signal } : undefined,
  );
  return toBenchmarkOverview(response);
}

export async function getBenchmarkDatasetImport(
  requestId: string,
  signal?: AbortSignal,
): Promise<BenchmarkDatasetImportReceipt> {
  const response = await requestJson<BenchmarkDatasetImportReceiptResponse>(
    `/api/benchmarks/imports/${encodeURIComponent(requestId)}`,
    signal ? { signal } : undefined,
  );
  return toBenchmarkDatasetImportReceipt(response);
}

export async function getBenchmarkReport(
  reportId: string,
  signal?: AbortSignal,
): Promise<BenchmarkReport> {
  const response = await requestJson<BenchmarkReportResponse>(
    `/api/benchmarks/${reportId}`,
    signal ? { signal } : undefined,
  );
  return toBenchmarkReport(response);
}

export async function runParserBenchmark(
  pipeline?: ParserPipeline,
): Promise<BenchmarkReport> {
  const request: JsonRequestOptions = { method: "POST" };
  if (pipeline) {
    request.headers = { "Content-Type": "application/json" };
    request.body = JSON.stringify({
      parser_provider: pipeline.parser_provider,
      parser_layout_profile: pipeline.parser_layout_profile,
    });
  }
  const response = await requestJson<BenchmarkReportResponse>(
    "/api/benchmarks/run",
    request,
  );
  return toBenchmarkReport(response);
}

export async function importBenchmarkDataset(
  file: File,
  requestId: string,
): Promise<BenchmarkDatasetImportResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await requestJson<BenchmarkDatasetImportResultResponse>(
    "/api/benchmarks/import",
    {
      method: "POST",
      headers: { "X-Benchmark-Import-Request-ID": requestId },
      body: form,
    },
  );
  return toBenchmarkDatasetImportResult(response);
}

export async function setBenchmarkInclusion(
  jobId: string,
  included: boolean,
): Promise<JobRecord> {
  const update: BenchmarkInclusionUpdate = { included };
  const response = await requestJson<JobRecordResponse>(
    `/api/jobs/${jobId}/benchmark`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    },
  );
  return toJobRecord(response);
}
