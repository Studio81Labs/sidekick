import type { BenchmarkReport } from "../types/benchmarks";
import type { PipelineSelection } from "../types/pipeline";
import { apiUrl, readJson } from "./core";

export {
  getBenchmarkDatasetImport,
  getBenchmarkOverview,
  getBenchmarkReport,
  importBenchmarkDataset,
  setBenchmarkInclusion,
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
