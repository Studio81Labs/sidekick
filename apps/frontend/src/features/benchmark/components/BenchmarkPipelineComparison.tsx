import { Play } from "lucide-react";

import { ButtonControl } from "../../../shared/components/FormControls";
import { benchmarkPercent } from "../../../shared/lib/metricPresentation";
import type {
  BenchmarkOverview,
  BenchmarkParserPipelineSummary,
  BenchmarkReport,
} from "../../../shared/types/benchmarks";
import type { PipelineSelection } from "../../../shared/types/pipeline";
import type { BenchmarkComparisonProgress } from "../lib/benchmarkPresentation";
import {
  benchmarkCorpusIsUnverified,
  benchmarkPipelinePointChange,
} from "../lib/benchmarkPresentation";

export interface BenchmarkPipelineComparisonProps {
  comparisonProgress: BenchmarkComparisonProgress | null;
  includedCases: number;
  onRunComparison: () => void | Promise<void>;
  onSelectPipeline: (parserProvider: string) => void | Promise<void>;
  operationsLocked: boolean;
  overview: BenchmarkOverview | null;
  parserPipelines: BenchmarkParserPipelineSummary[];
  pipelineLoading: boolean;
  pipelineSelection: PipelineSelection | null;
  report: BenchmarkReport | null;
}

export function BenchmarkPipelineComparison({
  comparisonProgress,
  includedCases,
  onRunComparison,
  onSelectPipeline,
  operationsLocked,
  overview,
  parserPipelines,
  pipelineLoading,
  pipelineSelection,
  report,
}: BenchmarkPipelineComparisonProps) {
  const runnablePipelines = parserPipelines.filter(
    (pipeline) => pipeline.parser.available,
  );

  return (
    <section
      className="benchmark-pipeline-comparison"
      aria-labelledby="benchmark-pipeline-comparison-title"
    >
      <div className="benchmark-pipeline-comparison-heading">
        <h3 id="benchmark-pipeline-comparison-title">Parser comparison</h3>
        <div>
          <span>Latest saved run</span>
          {runnablePipelines.length > 1 ? (
            <ButtonControl
              variant="secondary"
              className="benchmark-comparison-run"
              onClick={() => void onRunComparison()}
              disabled={operationsLocked || includedCases === 0}
            >
              <Play size={12} aria-hidden="true" />
              {comparisonProgress
                ? `${comparisonProgress.completed + 1}/${comparisonProgress.total}`
                : "Run comparison"}
            </ButtonControl>
          ) : null}
        </div>
      </div>
      <div className="benchmark-pipeline-list">
        {parserPipelines.map((pipeline) => {
          const selected =
            pipeline.parser.id ===
            (pipelineSelection?.parser_provider ??
              report?.parser_provider ??
              parserPipelines[0]?.parser.id);
          const pipelineReport = pipeline.latest_report;
          const pipelineRunning =
            comparisonProgress?.parserId === pipeline.parser.id;
          const stale = Boolean(
            pipelineReport &&
            benchmarkCorpusIsUnverified(
              pipelineReport.corpus_fingerprint,
              overview?.corpus_fingerprint,
            ),
          );
          const pipelineDelta = benchmarkPipelinePointChange(
            pipeline,
            overview?.corpus_fingerprint,
          );
          const trendLabel =
            pipelineDelta === null
              ? null
              : `${pipelineDelta > 0 ? "+" : ""}${pipelineDelta} pts`;
          let status = "No benchmark run";
          if (pipelineRunning) {
            status = "Running benchmark...";
          } else if (!pipeline.parser.available) {
            status =
              pipeline.parser.unavailable_reason ?? "Parser is unavailable";
          } else if (stale) {
            status = "Current corpus not verified · rerun";
          } else if (pipelineReport) {
            status = `${pipelineReport.total_cases} ${pipelineReport.total_cases === 1 ? "case" : "cases"}${pipelineReport.failed_cases > 0 ? ` · ${pipelineReport.failed_cases} failed` : ""}`;
          }

          return (
            <ButtonControl
              key={pipeline.parser.id}
              variant="ghost"
              className={
                [
                  selected ? "active" : "",
                  pipelineRunning ? "running" : "",
                  stale ? "stale" : "",
                ]
                  .filter(Boolean)
                  .join(" ") || undefined
              }
              onClick={() => void onSelectPipeline(pipeline.parser.id)}
              disabled={
                selected ||
                pipelineLoading ||
                !pipeline.parser.available ||
                operationsLocked
              }
              aria-current={selected ? "true" : undefined}
              aria-label={`Use ${pipeline.parser.label} benchmark pipeline`}
              title={
                pipeline.parser.unavailable_reason ??
                (stale
                  ? "This benchmark is not verified against the current ground truth"
                  : undefined)
              }
            >
              <span>
                <strong>{pipeline.parser.label}</strong>
                <small>
                  {status}
                  {trendLabel ? (
                    <span
                      className={`benchmark-pipeline-trend${pipelineDelta !== null && pipelineDelta > 0 ? " positive" : pipelineDelta !== null && pipelineDelta < 0 ? " negative" : ""}`}
                    >
                      {` · ${trendLabel}`}
                    </span>
                  ) : null}
                </small>
              </span>
              <strong
                className={
                  pipelineReport?.failed_cases || stale
                    ? "needs-review"
                    : undefined
                }
              >
                {pipelineReport
                  ? benchmarkPercent(pipelineReport.accuracy)
                  : "--"}
              </strong>
            </ButtonControl>
          );
        })}
      </div>
    </section>
  );
}
