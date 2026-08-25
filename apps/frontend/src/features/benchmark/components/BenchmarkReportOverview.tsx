import { AlertTriangle } from "lucide-react";

import {
  FormField,
  SelectControl,
} from "../../../shared/components/FormControls";
import { SummaryMetric } from "../../../shared/components/SummaryMetric";
import { benchmarkPercent } from "../../../shared/lib/metricPresentation";
import type {
  BenchmarkOverview,
  BenchmarkReport,
  BenchmarkReportSummary,
} from "../../../shared/types/benchmarks";
import type { PipelineCapabilities } from "../../../shared/types/pipeline";
import {
  benchmarkPointChange,
  benchmarkReportOption,
} from "../lib/benchmarkReportPresentation";

export interface BenchmarkReportOverviewProps {
  onSelectReport: (reportId: string) => void | Promise<void>;
  operationsLocked: boolean;
  overview: BenchmarkOverview | null;
  pipelineCapabilities: PipelineCapabilities | null;
  previousReport: BenchmarkReportSummary | null;
  recentReports: BenchmarkReportSummary[];
  report: BenchmarkReport;
  reportStale: boolean;
}

export function BenchmarkReportOverview({
  onSelectReport,
  operationsLocked,
  overview,
  pipelineCapabilities,
  previousReport,
  recentReports,
  report,
  reportStale,
}: BenchmarkReportOverviewProps) {
  const accuracyDelta = previousReport
    ? benchmarkPointChange(report.accuracy, previousReport.accuracy)
    : null;

  return (
    <>
      <div className="benchmark-report-toolbar">
        <FormField label="Report" labelClassName="benchmark-report-label">
          <SelectControl
            aria-label="Benchmark report"
            value={report.id}
            onChange={(event) => void onSelectReport(event.target.value)}
            disabled={operationsLocked}
          >
            {recentReports.map((summary) => (
              <option key={summary.id} value={summary.id}>
                {benchmarkReportOption(
                  summary,
                  overview?.latest_report?.id,
                  pipelineCapabilities,
                  overview?.parser_pipelines,
                  overview?.corpus_fingerprint,
                )}
              </option>
            ))}
          </SelectControl>
        </FormField>
        {accuracyDelta !== null ? (
          <strong className={accuracyDelta < 0 ? "negative" : ""}>
            {accuracyDelta > 0 ? "+" : ""}
            {accuracyDelta} pts vs previous
          </strong>
        ) : (
          <span>No comparable earlier run</span>
        )}
      </div>
      {reportStale ? (
        <div className="benchmark-corpus-warning" role="status">
          <AlertTriangle size={14} aria-hidden="true" />
          <span>
            <strong>
              This run is not verified against the current ground truth.
            </strong>
            Run the benchmark again before comparing its accuracy.
          </span>
        </div>
      ) : null}
      <div className="benchmark-summary" aria-label="Benchmark summary">
        <SummaryMetric label="cases" value={report.total_cases} />
        <SummaryMetric
          label="fields correct"
          value={`${report.correct_fields}/${report.evaluated_fields}`}
        />
        <SummaryMetric
          label="accuracy"
          value={benchmarkPercent(report.accuracy)}
        />
        <SummaryMetric
          attention={report.failed_cases > 0}
          label="failed"
          value={report.failed_cases}
        />
      </div>
    </>
  );
}
