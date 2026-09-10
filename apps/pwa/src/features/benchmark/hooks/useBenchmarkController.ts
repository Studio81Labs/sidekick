import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getJob } from "../../../domains/jobs/api/jobsApi";
import {
  assertQueryAccessGenerationCurrent,
  captureQueryAccessGeneration,
  isQueryAccessGenerationSuperseded,
} from "../../../shared/api/queryCache";
import {
  type BenchmarkComparisonProgress,
  benchmarkCorpusIsUnverified,
} from "../lib/benchmarkReportPresentation";
import {
  providerLabel,
  reconcilePipelineSelection,
} from "../../../domains/pipeline/model/pipelineSelection";
import { messageFromError } from "../../../shared/lib/errors";
import type { BenchmarkOverview } from "../../../shared/types/benchmarks";
import type { JobRecord } from "../../../shared/types/jobs";
import type {
  PipelineCapabilities,
  PipelineSelection,
} from "../../../shared/types/pipeline";
import { useBenchmarkReportState } from "./useBenchmarkReportState";
import { runParserBenchmarkCommand } from "../services/runParserBenchmarkCommand";

interface UseBenchmarkControllerOptions {
  administratorToken: string;
  busy: boolean;
  importRecoveryPending: boolean;
  mutationRecoveryPending: () => boolean;
  onAdministrativeDenial: (failure: unknown) => boolean;
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
  administratorToken,
  busy,
  importRecoveryPending,
  mutationRecoveryPending,
  onAdministrativeDenial,
  onError,
  onOpenJob,
  pipelineCapabilities,
  pipelineLoading,
  pipelineSelection,
  loadPipelineCapabilities,
  setPipelineSelection,
}: UseBenchmarkControllerOptions) {
  const queryClient = useQueryClient();
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
  } = useBenchmarkReportState({
    administratorToken,
    dialogOpen,
    onAdministrativeDenial,
    onError,
  });
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
      const { report: latestReport } = await runParserBenchmarkCommand(
        queryClient,
        {
          administratorToken,
          pipeline: pipelineSelection ?? undefined,
        },
      );
      applyReport(latestReport, true);
      if (latestReport.corpus_fingerprint) {
        await revalidateAfterRun(pipelineSelection);
      }
    } catch (error) {
      if (!onAdministrativeDenial(error)) {
        onError(messageFromError(error, "Parser benchmark failed"));
      }
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
          const { report: nextReport } = await runParserBenchmarkCommand(
            queryClient,
            {
              administratorToken,
              pipeline: {
                parser_provider: pipeline.parser.id,
                parser_layout_profile: pipeline.layout_profile,
              },
            },
          );
          applyReport(nextReport, pipeline.parser.id === selectedParser);
          successfulRuns += 1;
          corpusRevalidationRequired ||= Boolean(nextReport.corpus_fingerprint);
        } catch (error) {
          if (onAdministrativeDenial(error)) {
            return;
          }
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
    const accessGeneration = captureQueryAccessGeneration(queryClient);
    setReviewJobId(jobId);
    onError(null);
    try {
      const job = await getJob(jobId, administratorToken);
      assertQueryAccessGenerationCurrent(queryClient, accessGeneration);
      onOpenJob(job);
      closeDialog();
    } catch (error) {
      if (
        !isQueryAccessGenerationSuperseded(error) &&
        !onAdministrativeDenial(error)
      ) {
        onError(messageFromError(error, "Could not open benchmark hand"));
      }
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
