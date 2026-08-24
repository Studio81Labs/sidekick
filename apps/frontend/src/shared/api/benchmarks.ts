import type {
  BenchmarkDatasetImportResult,
  BenchmarkReport,
} from "../types/benchmarks";
import type { JobRecord } from "../types/jobs";
import type { PipelineSelection } from "../types/pipeline";
import { apiUrl, readJson } from "./core";

export {
  getBenchmarkDatasetImport,
  getBenchmarkOverview,
  getBenchmarkReport,
} from "../../domains/benchmarks/api/benchmarksApi";

type ParserPipeline = Pick<
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

export async function importBenchmarkDataset(
  file: File,
  requestId: string,
): Promise<BenchmarkDatasetImportResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(apiUrl("/api/benchmarks/import"), {
    method: "POST",
    headers: { "X-Benchmark-Import-Request-ID": requestId },
    body: form,
    credentials: "include",
  });
  return readJson<BenchmarkDatasetImportResult>(response);
}

export async function setBenchmarkInclusion(
  jobId: string,
  included: boolean,
): Promise<JobRecord> {
  const response = await fetch(apiUrl(`/api/jobs/${jobId}/benchmark`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ included }),
    credentials: "include",
  });
  return readJson<JobRecord>(response);
}

export async function runParserBenchmark(
  pipeline?: ParserPipeline,
): Promise<BenchmarkReport> {
  const request: RequestInit = {
    method: "POST",
    credentials: "include",
  };
  if (pipeline) {
    request.headers = { "Content-Type": "application/json" };
    request.body = JSON.stringify({
      parser_provider: pipeline.parser_provider,
      parser_layout_profile: pipeline.parser_layout_profile,
    });
  }
  const response = await fetch(apiUrl("/api/benchmarks/run"), request);
  return readJson<BenchmarkReport>(response);
}
