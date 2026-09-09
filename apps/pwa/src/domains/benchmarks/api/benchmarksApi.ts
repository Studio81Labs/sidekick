import type { components } from "@poker-hero/openapi-client";
import { apiUrl, readJson } from "../../../shared/api/core";
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

function benchmarkDatasetPath(pipeline?: ParserPipeline): string {
  const url = "/api/admin/ocr/benchmarks/export";
  if (!pipeline) return url;
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
  pipeline: ParserPipeline | undefined,
  administratorToken: string,
  signal?: AbortSignal,
): Promise<BenchmarkOverview> {
  const search = new URLSearchParams();
  if (pipeline) {
    search.set("parser_provider", pipeline.parser_provider);
    search.set("parser_layout_profile", pipeline.parser_layout_profile);
  }
  const query = search.size > 0 ? `?${search.toString()}` : "";
  const response = await requestJson<BenchmarkOverviewResponse>(
    `/api/admin/ocr/benchmarks${query}`,
    {
      headers: { Authorization: `Bearer ${administratorToken}` },
      ...(signal ? { signal } : {}),
    },
  );
  return toBenchmarkOverview(response);
}

export async function getBenchmarkDatasetImport(
  requestId: string,
  administratorToken: string,
  signal?: AbortSignal,
): Promise<BenchmarkDatasetImportReceipt> {
  const response = await requestJson<BenchmarkDatasetImportReceiptResponse>(
    `/api/admin/ocr/benchmarks/imports/${encodeURIComponent(requestId)}`,
    {
      headers: { Authorization: `Bearer ${administratorToken}` },
      ...(signal ? { signal } : {}),
    },
  );
  return toBenchmarkDatasetImportReceipt(response);
}

export async function getBenchmarkReport(
  reportId: string,
  administratorToken: string,
  signal?: AbortSignal,
): Promise<BenchmarkReport> {
  const response = await requestJson<BenchmarkReportResponse>(
    `/api/admin/ocr/benchmarks/${encodeURIComponent(reportId)}`,
    {
      headers: { Authorization: `Bearer ${administratorToken}` },
      ...(signal ? { signal } : {}),
    },
  );
  return toBenchmarkReport(response);
}

export async function runParserBenchmark(
  pipeline: ParserPipeline | undefined,
  administratorToken: string,
): Promise<BenchmarkReport> {
  const request: JsonRequestOptions = {
    method: "POST",
    headers: { Authorization: `Bearer ${administratorToken}` },
  };
  if (pipeline) {
    request.headers = {
      ...request.headers,
      "Content-Type": "application/json",
    };
    request.body = JSON.stringify({
      parser_provider: pipeline.parser_provider,
      parser_layout_profile: pipeline.parser_layout_profile,
    });
  }
  const response = await requestJson<BenchmarkReportResponse>(
    "/api/admin/ocr/benchmarks/run",
    request,
  );
  return toBenchmarkReport(response);
}

export async function importBenchmarkDataset(
  file: File,
  requestId: string,
  administratorToken: string,
): Promise<BenchmarkDatasetImportResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await requestJson<BenchmarkDatasetImportResultResponse>(
    "/api/admin/ocr/benchmarks/import",
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${administratorToken}`,
        "X-Benchmark-Import-Request-ID": requestId,
      },
      body: form,
    },
  );
  return toBenchmarkDatasetImportResult(response);
}

export async function setBenchmarkInclusion(
  jobId: string,
  included: boolean,
  administratorToken: string,
): Promise<JobRecord> {
  const update: BenchmarkInclusionUpdate = { included };
  const response = await requestJson<JobRecordResponse>(
    `/api/admin/ocr/jobs/${encodeURIComponent(jobId)}/benchmark`,
    {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${administratorToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(update),
    },
  );
  return toJobRecord(response);
}

export async function downloadBenchmarkDataset(
  administratorToken: string,
  pipeline?: ParserPipeline,
): Promise<Blob> {
  const response = await fetch(apiUrl(benchmarkDatasetPath(pipeline)), {
    credentials: "include",
    headers: { Authorization: `Bearer ${administratorToken}` },
  });
  if (!response.ok) {
    await readJson<never>(response);
  }
  return response.blob();
}
