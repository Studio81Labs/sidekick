import { StateMessage } from "../../../shared/components/StateMessage";
import { benchmarkPercent } from "../../../shared/lib/metricPresentation";
import type {
  BenchmarkReport,
  BenchmarkReportSummary,
} from "../../../shared/types/benchmarks";
import { providerLabel } from "../../../domains/pipeline/model/pipelineSelection";
import {
  benchmarkParserRouteSummary,
  benchmarkPointChange,
  previousBenchmarkFieldMetric,
} from "../lib/benchmarkPresentation";
import { BenchmarkCaseResults } from "./BenchmarkCaseResults";

export interface BenchmarkReportResultsProps {
  comparisonReport: BenchmarkReport | null;
  comparisonReportLoading: boolean;
  onReviewCase: (jobId: string) => void | Promise<void>;
  operationsLocked: boolean;
  previousReport: BenchmarkReportSummary | null;
  report: BenchmarkReport;
  reviewJobId: string | null;
}

export function BenchmarkReportResults({
  comparisonReport,
  comparisonReportLoading,
  onReviewCase,
  operationsLocked,
  previousReport,
  report,
  reviewJobId,
}: BenchmarkReportResultsProps) {
  const parserRoutes = benchmarkParserRouteSummary(report);

  return (
    <div className="benchmark-results-scroll">
      {report.parser_provider === "auto" ? (
        <section
          className="benchmark-result-section"
          aria-labelledby="benchmark-routes-title"
        >
          <h3 id="benchmark-routes-title">Parser routes</h3>
          {parserRoutes.routes.length > 0 ? (
            <div className="benchmark-route-list">
              {parserRoutes.routes.map((route) => (
                <div
                  key={route.provider}
                  aria-label={`${providerLabel(route.provider)} parser route`}
                >
                  <span>
                    <strong>{providerLabel(route.provider)}</strong>
                    <small>
                      {route.cases} {route.cases === 1 ? "case" : "cases"}
                      {` · ${route.correctFields}/${route.evaluatedFields} fields`}
                      {route.fallbackCases > 0
                        ? ` · ${route.fallbackCases} ${route.fallbackCases === 1 ? "fallback" : "fallbacks"}`
                        : ""}
                      {route.failedCases > 0
                        ? ` · ${route.failedCases} failed`
                        : ""}
                    </small>
                  </span>
                  <strong
                    className={route.failedCases > 0 ? "needs-review" : ""}
                  >
                    {benchmarkPercent(route.accuracy)}
                  </strong>
                </div>
              ))}
            </div>
          ) : (
            <StateMessage
              as="p"
              className="benchmark-route-empty"
              size="compact"
            >
              No parser routes were recorded for this report.
            </StateMessage>
          )}
          <p className="benchmark-route-coverage">
            {parserRoutes.attributedCases} of {report.total_cases} cases
            attributed
          </p>
        </section>
      ) : null}

      <section
        className="benchmark-result-section"
        aria-labelledby="benchmark-fields-title"
      >
        <h3 id="benchmark-fields-title">Field accuracy</h3>
        <div className="benchmark-field-list">
          {report.field_metrics.map((metric) => {
            const previousMetric = previousBenchmarkFieldMetric(
              metric,
              previousReport,
            );
            const fieldDelta = previousMetric
              ? benchmarkPointChange(metric.accuracy, previousMetric.accuracy)
              : null;
            const trendLabel = previousReport?.field_metrics?.length
              ? fieldDelta === null
                ? "New"
                : `${fieldDelta > 0 ? "+" : ""}${fieldDelta} pts`
              : null;

            return (
              <div
                key={metric.field}
                className={trendLabel ? "has-trend" : undefined}
              >
                <span>{metric.field.replace(/_/g, " ")}</span>
                <small>
                  {metric.correct}/{metric.total}
                </small>
                <strong>{benchmarkPercent(metric.accuracy)}</strong>
                {trendLabel ? (
                  <small
                    className={`benchmark-field-trend${fieldDelta !== null && fieldDelta < 0 ? " negative" : ""}`}
                    aria-label={`${metric.field.replace(/_/g, " ")} change ${trendLabel}`}
                  >
                    {trendLabel}
                  </small>
                ) : null}
              </div>
            );
          })}
        </div>
      </section>

      <BenchmarkCaseResults
        comparisonReport={comparisonReport}
        comparisonReportLoading={comparisonReportLoading}
        onReviewCase={onReviewCase}
        operationsLocked={operationsLocked}
        previousReport={previousReport}
        report={report}
        reviewJobId={reviewJobId}
      />
    </div>
  );
}
