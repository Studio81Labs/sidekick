import type { PipelineOption } from "./pipeline";

export interface BenchmarkFieldComparison {
  field: string;
  expected: unknown;
  detected: unknown;
  matched: boolean;
  confidence: number | null;
}

export interface BenchmarkCaseResult {
  job_id: string;
  original_filename: string;
  status: "completed" | "error";
  correct_fields: number;
  evaluated_fields: number;
  accuracy: number;
  warnings: string[];
  error: string | null;
  parser_routing?: {
    provider: string;
    selected_provider: string;
    layout_profile: string;
    fallback_from: string | null;
    fallback_reason: string | null;
  } | null;
  comparisons: BenchmarkFieldComparison[];
}

export interface BenchmarkFieldMetric {
  field: string;
  correct: number;
  total: number;
  accuracy: number;
}

export interface BenchmarkReport {
  id: string;
  parser_provider: string;
  layout_profile: string;
  corpus_fingerprint?: string | null;
  created_at: string;
  total_cases: number;
  successful_cases: number;
  failed_cases: number;
  correct_fields: number;
  evaluated_fields: number;
  accuracy: number;
  field_metrics: BenchmarkFieldMetric[];
  cases: BenchmarkCaseResult[];
}

export interface BenchmarkReportSummary {
  id: string;
  parser_provider: string;
  layout_profile: string;
  corpus_fingerprint?: string | null;
  created_at: string;
  total_cases: number;
  failed_cases: number;
  accuracy: number;
  field_metrics?: BenchmarkFieldMetric[];
}

export interface BenchmarkParserPipelineSummary {
  parser: PipelineOption;
  layout_profile: string;
  latest_report: BenchmarkReportSummary | null;
  previous_report?: BenchmarkReportSummary | null;
}

export interface BenchmarkOverview {
  included_cases: number;
  included_cases_by_layout?: Record<string, number>;
  corpus_fingerprint?: string | null;
  default_layout_profile?: string;
  latest_report: BenchmarkReport | null;
  recent_reports: BenchmarkReportSummary[];
  parser_pipelines?: BenchmarkParserPipelineSummary[];
}

export interface BenchmarkDatasetImportResult {
  imported_cases: number;
  reused_cases: number;
  included_cases: number;
  included_cases_by_layout?: Record<string, number> | null;
  job_ids: string[];
}

export interface BenchmarkDatasetImportReceipt {
  request_id: string;
  archive_sha256: string;
  status: "pending" | "completed" | "failed";
  result: BenchmarkDatasetImportResult | null;
  error: string | null;
  error_status: number | null;
}
