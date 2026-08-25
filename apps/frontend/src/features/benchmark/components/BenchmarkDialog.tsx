import type { ChangeEvent, Ref } from "react";
import "./BenchmarkDialog.css";

import { DialogFrame } from "../../../shared/components/DialogFrame";
import { DialogHeader } from "../../../shared/components/DialogHeader";
import { StateMessage } from "../../../shared/components/StateMessage";
import { ToggleControl } from "../../../shared/components/ToggleControl";
import type {
  BenchmarkOverview,
  BenchmarkParserPipelineSummary,
  BenchmarkReport,
  BenchmarkReportSummary,
} from "../../../shared/types/benchmarks";
import type { JobRecord } from "../../../shared/types/jobs";
import type {
  PipelineCapabilities,
  PipelineSelection,
} from "../../../shared/types/pipeline";
import type { BenchmarkComparisonProgress } from "../lib/benchmarkPresentation";
import { BenchmarkDialogActions } from "./BenchmarkDialogActions";
import { BenchmarkPipelineComparison } from "./BenchmarkPipelineComparison";
import { BenchmarkReportOverview } from "./BenchmarkReportOverview";
import { BenchmarkReportResults } from "./BenchmarkReportResults";

export interface BenchmarkDialogProps {
  busy: boolean;
  comparisonProgress: BenchmarkComparisonProgress | null;
  comparisonReport: BenchmarkReport | null;
  comparisonReportLoading: boolean;
  currentJob: JobRecord | null;
  datasetExportDisabled: boolean;
  datasetInputRef: Ref<HTMLInputElement>;
  importInProgress: boolean;
  includedCases: number;
  loading: boolean;
  onClose: () => void;
  onChooseDatasetImport: () => void;
  onDatasetImport: (
    event: ChangeEvent<HTMLInputElement>,
  ) => void | Promise<void>;
  onReviewCase: (jobId: string) => void | Promise<void>;
  onRun: () => void | Promise<void>;
  onRunComparison: () => void | Promise<void>;
  onSelectPipeline: (parserProvider: string) => void | Promise<void>;
  onSelectReport: (reportId: string) => void | Promise<void>;
  onToggleInclusion: () => void | Promise<void>;
  operationsLocked: boolean;
  overview: BenchmarkOverview | null;
  parserPipelines: BenchmarkParserPipelineSummary[];
  pipelineCapabilities: PipelineCapabilities | null;
  pipelineLoading: boolean;
  pipelineSelection: PipelineSelection | null;
  previousReport: BenchmarkReportSummary | null;
  recentReports: BenchmarkReportSummary[];
  report: BenchmarkReport | null;
  reportLoading: boolean;
  reportParserLabel: string | null;
  reportStale: boolean;
  reviewJobId: string | null;
  running: boolean;
  targetLayoutLabel: string | null;
  updating: boolean;
}

export function BenchmarkDialog({
  comparisonProgress,
  comparisonReport,
  comparisonReportLoading,
  currentJob,
  datasetExportDisabled,
  datasetInputRef,
  importInProgress,
  includedCases,
  loading,
  onClose,
  onChooseDatasetImport,
  onDatasetImport,
  onReviewCase,
  onRun,
  onRunComparison,
  onSelectPipeline,
  onSelectReport,
  onToggleInclusion,
  operationsLocked,
  overview,
  parserPipelines,
  pipelineCapabilities,
  pipelineLoading,
  pipelineSelection,
  previousReport,
  recentReports,
  report,
  reportLoading,
  reportParserLabel,
  reportStale,
  reviewJobId,
  running,
  targetLayoutLabel,
  updating,
}: BenchmarkDialogProps) {
  const closeDisabled =
    running ||
    updating ||
    importInProgress ||
    reportLoading ||
    reviewJobId !== null;

  return (
    <DialogFrame className="benchmark-dialog" titleId="benchmark-dialog-title">
      <DialogHeader
        titleId="benchmark-dialog-title"
        title="Parser benchmark"
        subtitle={
          report
            ? `${reportParserLabel} · ${report.layout_profile}`
            : "Ground-truth recognition checks"
        }
        closeLabel="Close parser benchmark"
        closeDisabled={closeDisabled}
        onClose={onClose}
      />

      <div className="benchmark-dialog-body">
        <ToggleControl
          className="benchmark-ground-truth"
          checked={currentJob?.benchmark_included ?? false}
          title="Use current hand as ground truth"
          description={
            currentJob?.approved_state
              ? currentJob.original_filename
              : currentJob?.benchmark_included
                ? "Previous approved state remains included"
                : "Approve the current hand first"
          }
          onClick={() => void onToggleInclusion()}
          disabled={
            (!currentJob?.approved_state && !currentJob?.benchmark_included) ||
            operationsLocked
          }
        />

        {!loading && parserPipelines.length > 1 ? (
          <BenchmarkPipelineComparison
            comparisonProgress={comparisonProgress}
            includedCases={includedCases}
            onRunComparison={onRunComparison}
            onSelectPipeline={onSelectPipeline}
            operationsLocked={operationsLocked}
            overview={overview}
            parserPipelines={parserPipelines}
            pipelineLoading={pipelineLoading}
            pipelineSelection={pipelineSelection}
            report={report}
          />
        ) : null}

        {loading ? (
          <StateMessage centered className="benchmark-empty">
            Reading benchmark results...
          </StateMessage>
        ) : report ? (
          <>
            <BenchmarkReportOverview
              onSelectReport={onSelectReport}
              operationsLocked={operationsLocked}
              overview={overview}
              pipelineCapabilities={pipelineCapabilities}
              previousReport={previousReport}
              recentReports={recentReports}
              report={report}
              reportStale={reportStale}
            />
            <BenchmarkReportResults
              comparisonReport={comparisonReport}
              comparisonReportLoading={comparisonReportLoading}
              onReviewCase={onReviewCase}
              operationsLocked={operationsLocked}
              previousReport={previousReport}
              report={report}
              reviewJobId={reviewJobId}
            />
          </>
        ) : (
          <StateMessage centered className="benchmark-empty">
            No benchmark has been run yet.
          </StateMessage>
        )}
      </div>

      <BenchmarkDialogActions
        closeDisabled={closeDisabled}
        datasetExportDisabled={datasetExportDisabled}
        datasetInputRef={datasetInputRef}
        importInProgress={importInProgress}
        includedCases={includedCases}
        onChooseDatasetImport={onChooseDatasetImport}
        onClose={onClose}
        onDatasetImport={onDatasetImport}
        onRun={onRun}
        operationsLocked={operationsLocked}
        pipelineSelection={pipelineSelection}
        running={running}
        targetLayoutLabel={targetLayoutLabel}
      />
    </DialogFrame>
  );
}
