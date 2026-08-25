import { benchmarkPercent } from "../../../shared/lib/metricPresentation";
import type {
  BenchmarkFieldMetric,
  BenchmarkOverview,
  BenchmarkParserPipelineSummary,
  BenchmarkReport,
  BenchmarkReportSummary,
} from "../../../shared/types/benchmarks";
import type { PipelineCapabilities } from "../../../shared/types/pipeline";
import { providerLabel } from "../../../domains/pipeline/model/pipelineSelection";

export interface BenchmarkComparisonProgress {
  parserId: string;
  completed: number;
  total: number;
}

export function benchmarkReportSummary(
  report: BenchmarkReport,
): BenchmarkReportSummary {
  return {
    id: report.id,
    parser_provider: report.parser_provider,
    layout_profile: report.layout_profile,
    corpus_fingerprint: report.corpus_fingerprint,
    created_at: report.created_at,
    total_cases: report.total_cases,
    failed_cases: report.failed_cases,
    accuracy: report.accuracy,
    field_metrics: report.field_metrics,
  };
}

export function benchmarkCorpusIsUnverified(
  reportFingerprint: string | null | undefined,
  currentFingerprint: string | null | undefined,
): boolean {
  return (
    !reportFingerprint ||
    !currentFingerprint ||
    reportFingerprint !== currentFingerprint
  );
}

export function benchmarkCorpusFingerprintAfterLayoutMutation(
  currentFingerprint: string | null | undefined,
  mutatedLayoutProfile: string | null | undefined,
  selectedLayoutProfile: string | null | undefined,
): string | null | undefined {
  return mutatedLayoutProfile &&
    selectedLayoutProfile &&
    mutatedLayoutProfile !== selectedLayoutProfile
    ? currentFingerprint
    : undefined;
}

export function benchmarkReportOption(
  summary: BenchmarkReportSummary,
  latestId: string | undefined,
  capabilities: PipelineCapabilities | null,
  parserPipelines: BenchmarkOverview["parser_pipelines"],
  currentCorpusFingerprint: string | null | undefined,
): string {
  const createdAt = new Date(summary.created_at);
  const dateLabel = Number.isNaN(createdAt.getTime())
    ? "Previous run"
    : createdAt.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
  const parserLabel =
    capabilities?.parser_providers.find(
      (option) => option.id === summary.parser_provider,
    )?.label ??
    parserPipelines?.find(
      (pipeline) => pipeline.parser.id === summary.parser_provider,
    )?.parser.label ??
    providerLabel(summary.parser_provider);
  const rawLayoutLabel =
    capabilities?.parser_layout_profiles.find(
      (option) => option.id === summary.layout_profile,
    )?.label ?? providerLabel(summary.layout_profile);
  const layoutLabel =
    rawLayoutLabel.charAt(0).toUpperCase() + rawLayoutLabel.slice(1);
  const staleLabel = benchmarkCorpusIsUnverified(
    summary.corpus_fingerprint,
    currentCorpusFingerprint,
  )
    ? " · rerun needed"
    : "";
  return `${summary.id === latestId ? "Latest" : dateLabel} · ${parserLabel} · ${layoutLabel} · ${benchmarkPercent(summary.accuracy)}${staleLabel}`;
}

export function previousComparableBenchmarkReport(
  report: BenchmarkReport | null,
  recentReports: BenchmarkReportSummary[],
  parserPipelines: BenchmarkOverview["parser_pipelines"],
): BenchmarkReportSummary | null {
  if (!report) {
    return null;
  }
  const currentIndex = recentReports.findIndex(
    (summary) => summary.id === report.id,
  );
  const recentMatch =
    currentIndex < 0
      ? null
      : (recentReports
          .slice(currentIndex + 1)
          .find(
            (summary) =>
              summary.parser_provider === report.parser_provider &&
              summary.layout_profile === report.layout_profile &&
              !benchmarkCorpusIsUnverified(
                summary.corpus_fingerprint,
                report.corpus_fingerprint,
              ),
          ) ?? null);
  if (recentMatch) {
    return recentMatch;
  }
  const pipeline = parserPipelines?.find(
    (candidate) =>
      candidate.parser.id === report.parser_provider &&
      candidate.layout_profile === report.layout_profile &&
      candidate.latest_report?.id === report.id,
  );
  const previous = pipeline?.previous_report;
  return previous &&
    previous.parser_provider === report.parser_provider &&
    previous.layout_profile === report.layout_profile &&
    !benchmarkCorpusIsUnverified(
      previous.corpus_fingerprint,
      report.corpus_fingerprint,
    )
    ? previous
    : null;
}

export function benchmarkPointChange(
  current: number,
  previous: number,
): number {
  return Math.round((current - previous) * 100);
}

export function benchmarkPipelinePointChange(
  pipeline: BenchmarkParserPipelineSummary,
  currentCorpusFingerprint: string | null | undefined,
): number | null {
  const latest = pipeline.latest_report;
  const previous = pipeline.previous_report;
  if (
    !latest ||
    !previous ||
    benchmarkCorpusIsUnverified(
      latest.corpus_fingerprint,
      currentCorpusFingerprint,
    ) ||
    benchmarkCorpusIsUnverified(
      previous.corpus_fingerprint,
      latest.corpus_fingerprint,
    )
  ) {
    return null;
  }
  return benchmarkPointChange(latest.accuracy, previous.accuracy);
}

export function previousBenchmarkFieldMetric(
  metric: BenchmarkFieldMetric,
  previousReport: BenchmarkReportSummary | null,
): BenchmarkFieldMetric | null {
  return (
    previousReport?.field_metrics?.find(
      (candidate) => candidate.field === metric.field,
    ) ?? null
  );
}

export function benchmarkReportsAreComparable(
  report: BenchmarkReport,
  previousReport: BenchmarkReport,
): boolean {
  return (
    previousReport.id !== report.id &&
    previousReport.parser_provider === report.parser_provider &&
    previousReport.layout_profile === report.layout_profile &&
    !benchmarkCorpusIsUnverified(
      previousReport.corpus_fingerprint,
      report.corpus_fingerprint,
    )
  );
}
