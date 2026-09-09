import {
  downloadBenchmarkDataset,
  type ParserPipeline,
} from "../../../domains/benchmarks/api/benchmarksApi";

/** Fetch the protected parser corpus before handing it to the browser download API. */
export function downloadBenchmarkDatasetCommand(
  administratorToken: string,
  pipeline?: ParserPipeline,
): Promise<Blob> {
  return downloadBenchmarkDataset(administratorToken, pipeline);
}
