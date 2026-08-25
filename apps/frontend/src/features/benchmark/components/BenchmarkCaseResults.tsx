import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Eye } from "lucide-react";

import { humanReadableMessage } from "../../../shared/api/client";
import { ButtonControl } from "../../../shared/components/FormControls";
import { SegmentedControl } from "../../../shared/components/SegmentedControl";
import { StateMessage } from "../../../shared/components/StateMessage";
import { benchmarkPercent } from "../../../shared/lib/metricPresentation";
import type {
  BenchmarkCaseResult,
  BenchmarkReport,
  BenchmarkReportSummary,
} from "../../../shared/types/benchmarks";
import { providerLabel } from "../../pipeline/lib/pipelineSelection";
import { parserRoutingEvidence } from "../../recommendation/lib/recommendationPresentation";
import {
  type BenchmarkCaseFilter,
  benchmarkCaseChanges,
  benchmarkCaseTrendMap,
  benchmarkComparisonValue,
  benchmarkMismatchLabel,
  benchmarkReportsAreComparable,
} from "../lib/benchmarkPresentation";

export interface BenchmarkCaseResultsProps {
  comparisonReport: BenchmarkReport | null;
  comparisonReportLoading: boolean;
  onReviewCase: (jobId: string) => void | Promise<void>;
  operationsLocked: boolean;
  previousReport: BenchmarkReportSummary | null;
  report: BenchmarkReport;
  reviewJobId: string | null;
}

export function BenchmarkCaseResults({
  comparisonReport,
  comparisonReportLoading,
  onReviewCase,
  operationsLocked,
  previousReport,
  report,
  reviewJobId,
}: BenchmarkCaseResultsProps) {
  const [caseFilter, setCaseFilter] = useState<BenchmarkCaseFilter>("all");
  const [expandedCaseId, setExpandedCaseId] = useState<string | null>(null);

  useEffect(() => {
    setCaseFilter("all");
    setExpandedCaseId(null);
  }, [report.id]);

  const caseTrends = useMemo(
    () =>
      benchmarkCaseTrendMap(
        report,
        comparisonReport?.id === previousReport?.id ? comparisonReport : null,
      ),
    [comparisonReport, previousReport?.id, report],
  );
  const comparisonCases = useMemo(() => {
    if (
      !comparisonReport ||
      !benchmarkReportsAreComparable(report, comparisonReport) ||
      comparisonReport.id !== previousReport?.id
    ) {
      return new Map<string, BenchmarkCaseResult>();
    }
    return new Map(
      comparisonReport.cases.map((benchmarkCase) => [
        benchmarkCase.job_id,
        benchmarkCase,
      ]),
    );
  }, [comparisonReport, previousReport?.id, report]);
  const caseTrendCounts = useMemo(() => {
    const counts = { regressed: 0, recovered: 0, mixed: 0 };
    for (const trend of caseTrends.values()) {
      if (trend !== "unchanged") counts[trend] += 1;
    }
    return counts;
  }, [caseTrends]);
  const visibleCases =
    caseFilter === "all"
      ? report.cases
      : report.cases.filter(
          (benchmarkCase) =>
            caseTrends.get(benchmarkCase.job_id) === caseFilter,
        );

  return (
    <section
      className="benchmark-result-section"
      aria-labelledby="benchmark-cases-title"
    >
      <div className="benchmark-case-heading">
        <h3 id="benchmark-cases-title">Cases</h3>
        {comparisonReportLoading ? (
          <span role="status">Comparing cases...</span>
        ) : caseTrends.size > 0 ? (
          <SegmentedControl
            ariaLabel="Benchmark case filter"
            className="benchmark-case-filter"
            options={[
              { value: "all", label: `All ${report.cases.length}` },
              {
                value: "regressed",
                label: `Regressed ${caseTrendCounts.regressed}`,
              },
              {
                value: "recovered",
                label: `Recovered ${caseTrendCounts.recovered}`,
              },
              { value: "mixed", label: `Mixed ${caseTrendCounts.mixed}` },
            ]}
            value={caseFilter}
            onChange={(filter) => {
              setCaseFilter(filter);
              setExpandedCaseId(null);
            }}
          />
        ) : null}
      </div>
      <div className="benchmark-case-list">
        {visibleCases.map((benchmarkCase) => {
          const expanded = expandedCaseId === benchmarkCase.job_id;
          const mismatches = benchmarkCase.comparisons.filter(
            (comparison) => !comparison.matched,
          );
          const parserRoute = parserRoutingEvidence(
            benchmarkCase.parser_routing,
          );
          const caseTrend = caseTrends.get(benchmarkCase.job_id);
          const previousCase = comparisonCases.get(benchmarkCase.job_id);
          const caseChanges =
            expanded && previousCase
              ? benchmarkCaseChanges(benchmarkCase, previousCase)
              : [];
          const detailId = `benchmark-case-${benchmarkCase.job_id}`;

          return (
            <div
              key={benchmarkCase.job_id}
              className={`benchmark-case-row${caseTrend && caseTrend !== "unchanged" ? ` ${caseTrend}` : ""}`}
            >
              <ButtonControl
                variant="ghost"
                className="benchmark-case-summary"
                onClick={() =>
                  setExpandedCaseId((current) =>
                    current === benchmarkCase.job_id
                      ? null
                      : benchmarkCase.job_id,
                  )
                }
                aria-expanded={expanded}
                aria-controls={detailId}
                aria-label={`Toggle ${benchmarkCase.original_filename} benchmark details${caseTrend && caseTrend !== "unchanged" ? `, ${caseTrend}` : ""}`}
              >
                <span>
                  <strong>
                    {benchmarkCase.original_filename}
                    {caseTrend && caseTrend !== "unchanged" ? (
                      <em className={`benchmark-case-trend ${caseTrend}`}>
                        {caseTrend}
                      </em>
                    ) : null}
                  </strong>
                  <small>
                    {parserRoute
                      ? `${providerLabel(parserRoute.selectedProvider)} · `
                      : ""}
                    {benchmarkCase.error
                      ? humanReadableMessage(
                          benchmarkCase.error,
                          "Benchmark failed",
                        )
                      : benchmarkMismatchLabel(benchmarkCase.comparisons)}
                  </small>
                </span>
                <strong
                  className={
                    benchmarkCase.status === "error" || mismatches.length > 0
                      ? "needs-review"
                      : ""
                  }
                >
                  {benchmarkCase.status === "error"
                    ? "Error"
                    : benchmarkPercent(benchmarkCase.accuracy)}
                </strong>
                <ChevronDown size={15} aria-hidden="true" />
              </ButtonControl>
              {expanded ? (
                <div id={detailId} className="benchmark-case-details">
                  {parserRoute ? (
                    <div
                      className="benchmark-case-routing"
                      aria-label="Parser routing"
                    >
                      <strong>
                        {providerLabel(parserRoute.selectedProvider)}
                      </strong>
                      <span>
                        via {providerLabel(parserRoute.provider)}
                        {parserRoute.fallbackFrom
                          ? ` · fallback from ${providerLabel(parserRoute.fallbackFrom)}`
                          : ""}
                      </span>
                      {parserRoute.fallbackReason ? (
                        <small>{parserRoute.fallbackReason}</small>
                      ) : null}
                    </div>
                  ) : null}
                  {benchmarkCase.error ? (
                    <p className="benchmark-case-error">
                      {humanReadableMessage(
                        benchmarkCase.error,
                        "Benchmark failed",
                      )}
                    </p>
                  ) : null}
                  {caseChanges.length > 0 ? (
                    <div
                      className="benchmark-case-changes"
                      aria-label={`${benchmarkCase.original_filename} changes since previous run`}
                    >
                      <strong className="benchmark-case-changes-title">
                        Changes since previous run
                      </strong>
                      {caseChanges.map((change) => (
                        <div
                          key={change.key}
                          className={`benchmark-case-change ${change.trend}`}
                          aria-label={`${change.label} ${change.trend}`}
                        >
                          <span className="benchmark-case-change-field">
                            <strong>{change.label}</strong>
                            <em>{change.trend}</em>
                          </span>
                          <span>
                            <small>Previous</small>
                            <code>
                              {benchmarkComparisonValue(change.previousValue)}
                            </code>
                          </span>
                          <span>
                            <small>Current</small>
                            <code>
                              {benchmarkComparisonValue(change.currentValue)}
                            </code>
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {mismatches.length > 0 ? (
                    <div className="benchmark-mismatch-list">
                      {mismatches.map((comparison) => (
                        <div key={comparison.field}>
                          <strong>{comparison.field.replace(/_/g, " ")}</strong>
                          <span>
                            <small>Expected</small>
                            <code>
                              {benchmarkComparisonValue(comparison.expected)}
                            </code>
                          </span>
                          <span>
                            <small>Detected</small>
                            <code>
                              {benchmarkComparisonValue(comparison.detected)}
                            </code>
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : benchmarkCase.error ? null : (
                    <p className="benchmark-case-matched">
                      Every labeled field matched the approved state.
                    </p>
                  )}
                  <div className="benchmark-case-actions">
                    <ButtonControl
                      variant="secondary"
                      onClick={() => void onReviewCase(benchmarkCase.job_id)}
                      disabled={operationsLocked}
                    >
                      <Eye size={14} aria-hidden="true" />
                      {reviewJobId === benchmarkCase.job_id
                        ? "Opening..."
                        : "Review hand"}
                    </ButtonControl>
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
        {visibleCases.length === 0 ? (
          <StateMessage
            as="p"
            centered
            className="benchmark-case-empty"
            size="compact"
          >
            {caseFilter === "all"
              ? "No benchmark cases in this report."
              : `No ${caseFilter} cases in this comparison.`}
          </StateMessage>
        ) : null}
      </div>
    </section>
  );
}
