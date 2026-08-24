import type { components } from "../../../shared/api/generated/openapi";
import { requestJson } from "../../../shared/api/transport";
import type {
  BenchmarkDatasetImportReceipt,
  BenchmarkOverview,
  BenchmarkReport,
} from "../../../shared/types/benchmarks";
import type { PipelineSelection } from "../../../shared/types/pipeline";

export type ParserPipeline = Pick<
  PipelineSelection,
  "parser_provider" | "parser_layout_profile"
>;

type BenchmarkOverviewResponse = components["schemas"]["BenchmarkOverview"];
type BenchmarkReportResponse = components["schemas"]["BenchmarkReport"];
type BenchmarkDatasetImportReceiptResponse =
  components["schemas"]["BenchmarkDatasetImportReceipt"];

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
