import { useState } from "react";
import { toast } from "sonner";
import { getJob } from "../../../domains/jobs/api/jobsApi";
import { runParserBenchmark } from "../../../shared/api/client";
import {
  type BenchmarkComparisonProgress,
  benchmarkCorpusIsUnverified,
} from "../lib/benchmarkPresentation";
import {
  providerLabel,
  reconcilePipelineSelection,
} from "../../pipeline/lib/pipelineSelection";
import { messageFromError } from "../../workspace/lib/workflow";
import type {
  BenchmarkOverview,
  JobRecord,
  PipelineCapabilities,
  PipelineSelection,
} from "../../../shared/types";
import { useBenchmarkReportState } from "./useBenchmarkReportState";

interface UseBenchmarkControllerOptions {
  busy: boolean;
  importRecoveryPending: boolean;
  mutationRecoveryPending: () => boolean;
  onError: (message: string | null) => void;
  onOpenJob: (job: JobRecord) => void;
  pipelineCapabilities: PipelineCapabilities | null;
  pipelineLoading: boolean;
  pipelineSelection: PipelineSelection | null;
  loadPipelineCapabilities: () => Promise<PipelineCapabilities | null>;
  setPipelineSelection: (selection: PipelineSelection) => void;
}

interface RefreshBenchmarkOptions {
  failureMessage: string;
  selection?: PipelineSelection | null;
}

export function useBenchmarkController({
  busy,
  importRecoveryPending,
  mutationRecoveryPending,
  onError,
  onOpenJob,
  pipelineCapabilities,
  pipelineLoading,
  pipelineSelection,
  loadPipelineCapabilities,
  setPipelineSelection,
}: UseBenchmarkControllerOptions) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [running, setRunning] = useState(false);
  const [comparisonProgress, setComparisonProgress] =
    useState<BenchmarkComparisonProgress | null>(null);
  const [updating, setUpdating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [reviewJobId, setReviewJobId] = useState<string | null>(null);
  const {
    applyReport,
    cancelLoads,
    comparisonReport,
    comparisonReportLoading,
    loadOverview,
    loading,
    overview,
    previousReport,
    recentReports,
    refreshOverview: refreshReportOverview,
    report,
    reportLoading,
    reset: resetReportState,
    selectReport,
    setOverview,
  } = useBenchmarkReportState({ dialogOpen, onError });
  const reportStale = Boolean(
    report &&
    benchmarkCorpusIsUnverified(
      report.corpus_fingerprint,
      overview?.corpus_fingerprint,
    ),
  );
  const reportParserLabel = report
    ? (pipelineCapabilities?.parser_providers.find(
        (option) => option.id === report.parser_provider,
      )?.label ??
      overview?.parser_pipelines?.find(
        (pipeline) => pipeline.parser.id === report.parser_provider,
      )?.parser.label ??
      providerLabel(report.parser_provider))
    : null;
  const operationsLocked =
    loading ||
    reportLoading ||
    running ||
    updating ||
    importing ||
    importRecoveryPending ||
    reviewJobId !== null ||
    busy;
  const targetLayoutProfile =
    pipelineSelection?.parser_layout_profile ??
    overview?.default_layout_profile ??
    null;
  const hasLayoutCounts = Boolean(
    overview?.included_cases_by_layout &&
    (overview.included_cases === 0 ||
      Object.keys(overview.included_cases_by_layout).length > 0),
  );
  const includedCases =
    targetLayoutProfile && hasLayoutCounts && overview?.included_cases_by_layout
      ? (overview.included_cases_by_layout[targetLayoutProfile] ?? 0)
      : (overview?.included_cases ?? 0);
  const targetLayoutLabel =
    pipelineCapabilities?.parser_layout_profiles.find(
      (option) => option.id === targetLayoutProfile,
    )?.label ?? targetLayoutProfile;
  const datasetExportDisabled = operationsLocked || includedCases === 0;
  const parserPipelines = overview?.parser_pipelines ?? [];
  const runnablePipelines = parserPipelines.filter(
    (pipeline) => pipeline.parser.available,
  );

  async function refreshOverview({
    failureMessage,
    selection = pipelineSelection,
  }: RefreshBenchmarkOptions): Promise<BenchmarkOverview | null> {
    return refreshReportOverview({ failureMessage, selection });
  }

  function openDialog() {
    setDialogOpen(true);
    loadOverview(pipelineSelection);
  }

  function closeDialog() {
    cancelLoads();
    setDialogOpen(false);
  }

  function reset() {
    resetReportState();
  }

  async function revalidateAfterRun(selection: PipelineSelection | null) {
    await refreshOverview({
      failureMessage:
        "Benchmark completed, but the current corpus could not be verified",
      selection,
    });
  }

  async function run() {
    if (operationsLocked || mutationRecoveryPending()) {
      return;
    }
    setRunning(true);
    onError(null);
    try {
      const latestReport = await runParserBenchmark(
        pipelineSelection ?? undefined,
      );
      applyReport(latestReport, true);
      if (latestReport.corpus_fingerprint) {
        await revalidateAfterRun(pipelineSelection);
      }
    } catch (error) {
      onError(messageFromError(error, "Parser benchmark failed"));
    } finally {
      setRunning(false);
    }
  }

  async function runComparison() {
    if (
      operationsLocked ||
      runnablePipelines.length < 2 ||
      mutationRecoveryPending()
    ) {
      return;
    }
    const selectedParser =
      pipelineSelection?.parser_provider ??
      report?.parser_provider ??
      runnablePipelines[0]?.parser.id;
    const failures: string[] = [];
    let successfulRuns = 0;
    let corpusRevalidationRequired = false;
    setRunning(true);
    onError(null);
    try {
      for (const [index, pipeline] of runnablePipelines.entries()) {
        setComparisonProgress({
          parserId: pipeline.parser.id,
          completed: index,
          total: runnablePipelines.length,
        });
        try {
          const nextReport = await runParserBenchmark({
            parser_provider: pipeline.parser.id,
            parser_layout_profile: pipeline.layout_profile,
          });
          applyReport(nextReport, pipeline.parser.id === selectedParser);
          successfulRuns += 1;
          corpusRevalidationRequired ||= Boolean(nextReport.corpus_fingerprint);
        } catch (error) {
          failures.push(
            `${pipeline.parser.label}: ${messageFromError(error, "Benchmark failed")}`,
          );
        }
      }
      if (successfulRuns > 0 && corpusRevalidationRequired) {
        await revalidateAfterRun(pipelineSelection);
      }
      if (successfulRuns === runnablePipelines.length) {
        toast.success(`Benchmark comparison ready: ${successfulRuns} parsers`);
      } else if (successfulRuns > 0) {
        toast.warning(
          `Benchmark comparison completed for ${successfulRuns} of ${runnablePipelines.length} parsers. ${failures.join(" ")}`,
        );
      } else {
        onError(`No parser benchmark completed. ${failures.join(" ")}`);
      }
    } finally {
      setComparisonProgress(null);
      setRunning(false);
    }
  }

  async function selectParserPipeline(parserProvider: string) {
    if (
      operationsLocked ||
      pipelineLoading ||
      parserProvider === pipelineSelection?.parser_provider
    ) {
      return;
    }
    onError(null);
    const capabilities =
      pipelineCapabilities ?? (await loadPipelineCapabilities());
    if (!capabilities) return;
    const currentSelection = reconcilePipelineSelection(
      capabilities,
      pipelineSelection ?? capabilities.defaults,
    );
    const nextSelection = reconcilePipelineSelection(capabilities, {
      ...currentSelection,
      parser_provider: parserProvider,
    });
    if (
      nextSelection.parser_provider !== parserProvider ||
      nextSelection.parser_layout_profile !==
        currentSelection.parser_layout_profile
    ) {
      onError("That parser is not available for the selected table layout");
      return;
    }
    setPipelineSelection(nextSelection);
    loadOverview(nextSelection, true);
  }

  async function reviewCase(jobId: string) {
    setReviewJobId(jobId);
    onError(null);
    try {
      onOpenJob(await getJob(jobId));
      closeDialog();
    } catch (error) {
      onError(messageFromError(error, "Could not open benchmark hand"));
    } finally {
      setReviewJobId(null);
    }
  }

  return {
    closeDialog,
    comparisonProgress,
    comparisonReport,
    comparisonReportLoading,
    datasetExportDisabled,
    dialogOpen,
    importing,
    includedCases,
    loadOverview,
    loading,
    openDialog,
    operationsLocked,
    overview,
    parserPipelines,
    previousReport,
    recentReports,
    refreshOverview,
    report,
    reportLoading,
    reportParserLabel,
    reportStale,
    reset,
    reviewCase,
    reviewJobId,
    run,
    runComparison,
    running,
    selectParserPipeline,
    selectReport,
    setImporting,
    setOverview,
    setUpdating,
    targetLayoutLabel,
    targetLayoutProfile,
    updating,
  };
}
