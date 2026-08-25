import { type ChangeEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import type {
  AnalyzerRouteNavigation,
  AnalyzerRouteState,
} from "./analyzerRouteState";
import { useAnalyzerRouteRestore } from "./useAnalyzerRouteRestore";
import { selectedFilesLabel } from "../../features/capture/components/InputSourcePanel";
import { shareModeLabel } from "../../features/capture/lib/captureSource";
import { type HistoryItem } from "../../features/history/lib/historyPresentation";
import {
  parseScreenshotTags,
  screenshotTags,
} from "../../features/screenshots/lib/screenshotMetadata";
import { screenshotLabel } from "../../shared/lib/screenshotPresentation";
import { useAutomationSettings } from "../../features/automation/hooks/useAutomationSettings";
import { useBenchmarkController } from "../../features/benchmark/hooks/useBenchmarkController";
import {
  applicationBackupUrl,
  restoreApplicationBackupCommand,
} from "../../features/backups/services/restoreApplicationBackupCommand";
import { useCaptureSource } from "../../features/capture/hooks/useCaptureSource";
import { uploadScreenshotCommand } from "../../features/capture/services/uploadScreenshotCommand";
import { useHandReviewState } from "../../features/hand-review/hooks/useHandReviewState";
import {
  approveStateCommand,
  requestRecommendationCommand,
} from "../../features/hand-review/services/handWorkflowCommands";
import { usePipelineSelection } from "../../features/pipeline/hooks/usePipelineSelection";
import { useScreenshotDetails } from "../../features/screenshots/hooks/useScreenshotDetails";
import { updateScreenshotMetadataCommand } from "../../features/screenshots/services/updateScreenshotMetadataCommand";
import { deleteScreenshotCommand } from "../../features/screenshots/services/deleteScreenshotCommand";
import { useSystemInfoDialog } from "../../features/system/hooks/useSystemInfoDialog";
import { useTrainingProgress } from "../../features/training/hooks/useTrainingProgress";
import {
  completeTrainingReviewCommand,
  recordTrainingDecisionCommand,
  reopenTrainingReviewCommand,
} from "../../features/training/services/trainingReviewCommands";
import {
  AnalyzerWorkflowProvider,
  useAnalyzerActiveSelection,
  useAnalyzerMutationLeases,
  useAnalyzerQueueWorkflow,
  useAnalyzerRecoveryWorkflow,
  useAnalyzerWorkflowProjections,
} from "../../features/workspace/hooks/useAnalyzerWorkflow";
import { useAnalyzerRecoveryRuntimeServices } from "../../features/workspace/hooks/useAnalyzerRecoveryRuntimeServices";
import { useAnalyzerRequestRuntimeServices } from "../../features/workspace/hooks/useAnalyzerRequestRuntimeServices";
import { archiveJobsCommand } from "../../features/history/services/archiveJobsCommand";
import {
  fetchBenchmarkImportReceiptQuery,
  fetchHistoryPageQuery,
  fetchJobQuery,
  fetchTrainingProgressQuery,
} from "../../features/workspace/lib/queryReads";
import { ApiResponseError, humanReadableMessage } from "../../shared/api/core";
import {
  ERROR_TOAST_ID,
  isAbortError,
  messageFromError,
  mutationFailureMayHavePersistedSideEffect,
  recommendationAttemptMayHavePersistedSideEffect,
} from "../../shared/lib/errors";
import type { BenchmarkDatasetImportResult } from "../../shared/types/benchmarks";
import type { CanonicalState } from "../../shared/types/poker";
import type { JobHistory, JobRecord } from "../../shared/types/jobs";
import { benchmarkCorpusFingerprintAfterLayoutMutation } from "../../features/benchmark/lib/benchmarkPresentation";
import { importBenchmarkDatasetCommand } from "../../features/benchmark/services/importBenchmarkDatasetCommand";
import { setBenchmarkInclusionCommand } from "../../features/benchmark/services/setBenchmarkInclusionCommand";
import {
  HISTORY_CACHE_LIMIT,
  type JobMutationExpectation,
  type JobMutationLease,
  PERSISTED_JOB_ID_PATTERN,
  PERSISTED_MUTATION_LEASE_MS,
  PROCESSING_QUEUE_REVALIDATION_INTERVAL_MS,
  type PersistedJobMutationScope,
  type PersistedMutationLease,
  type ProjectionMutationLease,
  type ProjectionMutationTarget,
  benchmarkImportLeaseRequestId,
  createMutationRequestId,
  getHistorySearchExtent,
  getProcessingQueueExtent,
  historyItemsFromPage,
  isBenchmarkImportLease,
  isLocalUploadError,
  isPristineBenchmarkImport,
  jobMutationExpectationReached,
  matchingArchiveLeaseTargets,
  mergeHistoryItems,
  mutationLeaseJobIds,
  mutationLeaseTargetsJob,
  newerHistoryJob,
  preserveUploadRequestId,
  processingJobsForCache,
  projectionMutationLeaseTargetReached,
  projectionMutationTarget,
  projectionMutationTargetReached,
  reconcileHistoryItems,
  reconcileProcessingJobs,
} from "../../features/workspace/lib/persistence";
import {
  approvalKey,
  benchmarkApprovalKey,
  stateToForm,
} from "../../features/hand-review/lib/pokerState";
import { parserRoutingFromRaw } from "../../features/recommendation/lib/recommendationPresentation";
import {
  suggestedActionDifferenceFocus,
  suggestedCertaintyFocus,
  suggestedPositionFocus,
  suggestedTrainingFocus,
} from "../../features/training/lib/trainingFocusPresentation";
import { trainingReviewQueueStatus } from "../../features/training/lib/trainingQueuePresentation";
import {
  autoApprovalState,
  createLocalErrorJob,
  isHistoryReady,
  isProcessingJobInProgress,
} from "../../features/workspace/lib/workflow";

type JobNavigationMode = "push" | "replace" | false;

export type AnalyzerWorkspaceControllerProps = {
  mutationOwnerId: string;
  navigation: AnalyzerRouteNavigation;
  route: AnalyzerRouteState;
};

export function useAnalyzerWorkspaceController({
  mutationOwnerId,
  navigation,
  route,
}: AnalyzerWorkspaceControllerProps) {
  const queryClient = useQueryClient();
  const routeRef = useRef(route);
  routeRef.current = route;
  const {
    finishRecovery,
    mutationLeaseRestoreRequest,
    processingRestoreRequest,
    requestMutationLeaseRevalidation,
    requestProcessingRecovery,
    scheduleRecoveryRetry,
    startRecovery,
  } = useAnalyzerRecoveryWorkflow();
  const { activeJobId, selectActiveJob } = useAnalyzerActiveSelection();
  const {
    attentionByJobId: jobAttention,
    clearJobAttention: clearWorkflowJobAttention,
    markJobAttention,
    queueProgress,
    requestQueueAbort,
    setQueueProgress,
  } = useAnalyzerQueueWorkflow();
  const { mutationLeases, setMutationLease: setWorkflowMutationLease } =
    useAnalyzerMutationLeases();
  const initialProcessingMutationLease = mutationLeases.processing;
  const initialHistoryMutationLease = mutationLeases.history;
  const {
    clearPersistedMutationLease,
    historySessionSynced,
    isProcessingQueueStorageEvent,
    markHistorySessionSynced,
    markHistorySessionUnsynced,
    markProcessingQueueSessionSynced,
    markProcessingQueueSessionUnsynced,
    processingQueueSessionSynced,
    readCachedHistoryTotal,
    readCachedProcessingQueueTotal,
    readHistory,
    readHistoryTotal,
    readPersistedMutationLease,
    readProcessingQueue,
    replacePersistedMutationLease,
    startArchiveMutationLease,
    startPersistedMutationLease,
    startProjectionMutationLease,
    writeHistory,
    writeHistoryTotal,
    writeProcessingQueue,
  } = useAnalyzerWorkflowProjections();
  const {
    benchmarkImportRecoveryPromiseRef,
    historyFullRestoreRequestedRef,
    historyJobRestoreActiveIdsRef,
    historyJobRestoreIdsRef,
    historyJobRestorePromiseRef,
    historyJobRestoreRetryTimerRef,
    historyRestorePromiseRef,
    historyRestoreRetryRequestedRef,
    legacyHistoryArchivePromiseRef,
    processingRestorePromiseRef,
    processingRestoreRetryRequestedRef,
    processingStorageRestoreScheduledRef,
  } = useAnalyzerRecoveryRuntimeServices();
  const {
    activeRecommendationRequestsRef,
    appMountedRef,
    historySearchRequestRef,
    queueAbortControllerRef,
    queueAbortRequestedRef,
  } = useAnalyzerRequestRuntimeServices();
  const [jobs, setJobs] = useState<JobRecord[]>(
    () => readProcessingQueue() ?? [],
  );
  const [helpDialogOpen, setHelpDialogOpen] = useState(false);
  const [backupRestoring, setBackupRestoring] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>(
    () => readHistory() ?? [],
  );
  const [historyTotal, setHistoryTotal] = useState(readHistoryTotal);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historySearchOpen, setHistorySearchOpen] = useState(false);
  const [historySearchInput, setHistorySearchInput] = useState("");
  const [historySearchQuery, setHistorySearchQuery] = useState("");
  const [historySearchResults, setHistorySearchResults] = useState<
    HistoryItem[] | null
  >(null);
  const [historySearchTotal, setHistorySearchTotal] = useState(0);
  const [historySearchSnapshotVersion, setHistorySearchSnapshotVersion] =
    useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setErrorMessage] = useState<string | null>(null);
  const [errorSequence, setErrorSequence] = useState(0);
  const {
    activeJobIdRef,
    addCompletedPostflopAction,
    addPostflopAction,
    addPreflopAction,
    alignWorkspaceToJob,
    canApprove,
    canRecommend,
    cancelTrainingReviewNoteEdit,
    completedPostflopActionCounts,
    completedPostflopActionsAtLimit,
    confidenceSummary,
    confidences,
    currentStateApproved,
    decisionComparison,
    decisionEvidence,
    form,
    formBaselineRef,
    formDirtyRef,
    job,
    parseTrainingSizing,
    recommendation: activeRecommendation,
    removeCompletedPostflopAction,
    removePostflopAction,
    removePreflopAction,
    resetToParser,
    screenshotUrl,
    setActiveJobId,
    setApprovedStateKey,
    setForm,
    setTrainingAction,
    setTrainingCertainty,
    setTrainingReviewNote,
    setTrainingReviewNoteEditing,
    setTrainingSizing,
    startTrainingReviewNoteEdit,
    trainingAction,
    trainingCertainty,
    trainingDecision: activeTrainingDecision,
    trainingReviewNote,
    trainingReviewNoteEditing,
    trainingSizing,
    updateCompletedPostflopAction,
    updateForm,
    updatePostflopAction,
    updatePreflopAction,
    validation,
    warnings,
  } = useHandReviewState({
    activeJobId,
    jobs,
    onActiveJobChange: selectActiveJob,
    onError: setError,
  });
  const {
    certaintyFilter: trainingCertaintyFilter,
    dialogOpen: trainingDialogOpen,
    focusActionDifference: focusTrainingActionDifference,
    focusReviewCertainty: focusTrainingReviewCertainty,
    focusReviewPosition: focusTrainingReviewPosition,
    focusReviewStreet: focusTrainingReviewStreet,
    lessonOrder: trainingLessonOrder,
    lessonQuery: trainingLessonQuery,
    lessonSearch: trainingLessonSearch,
    lessonStreet: trainingLessonStreet,
    loading: trainingProgressLoading,
    openDialog: openTrainingDialog,
    positionFilter: trainingPositionFilter,
    progress: trainingProgress,
    reviewCertainty: trainingReviewCertainty,
    reviewDifference: trainingReviewDifference,
    reviewHand: reviewTrainingHand,
    reviewJobId: trainingReviewJobId,
    reviewOrder: trainingReviewOrder,
    reviewPosition: trainingReviewPosition,
    reviewQueueJobId: trainingReviewQueueJobId,
    reviewStreet: trainingReviewStreet,
    selectView: selectTrainingProgressView,
    setDialogOpen: setTrainingDialogOpen,
    setLessonSearch: setTrainingLessonSearch,
    setProgress: setTrainingProgress,
    setReviewJobId: setTrainingReviewJobId,
    setReviewQueueJobId: setTrainingReviewQueueJobId,
    setView: setTrainingProgressView,
    solverFilter: trainingSolverFilter,
    streetFilter: trainingStreetFilter,
    updateCertaintyFilter: updateTrainingCertaintyFilter,
    updateLessonFilters: updateTrainingLessonFilters,
    updatePositionFilter: updateTrainingPositionFilter,
    updateReviewQueue: updateTrainingReviewQueue,
    updateSolverFilter: updateTrainingSolverFilter,
    updateStreetFilter: updateTrainingStreetFilter,
    view: trainingProgressView,
  } = useTrainingProgress({
    onError: setError,
    onOpenJob: upsertAndActivateJob,
  });
  const {
    capabilities: pipelineCapabilities,
    compatibleLayouts: compatiblePipelineLayouts,
    dialogOpen: pipelineDialogOpen,
    loading: pipelineLoading,
    loadCapabilities: loadPipelineCapabilities,
    openDialog: openPipelineDialog,
    providerLabel,
    selection: pipelineSelection,
    setDialogOpen: setPipelineDialogOpen,
    setSelection: setPipelineSelection,
    updateParserProvider,
    updateRecommendationProvider,
    updateSelection: updatePipelineSelection,
  } = usePipelineSelection({ onError: setError });
  const {
    captureFile: captureSharedScreenFile,
    files,
    inputMode,
    previewVisible: livePreviewVisible,
    screenSharing,
    setFiles,
    setInputMode,
    setPreviewVisible: setLivePreviewVisible,
    setShareMode,
    shareMode,
    sourceLabel: screenSourceLabel,
    startShare: onStartScreenShare,
    stopShare: onStopScreenShare,
    videoRef,
  } = useCaptureSource({ onError: setError });
  const {
    dialogOpen: automationDialogOpen,
    setDialogOpen: setAutomationDialogOpen,
    settings: automationSettings,
    update: updateAutomationSettings,
    updateAutoApprove: updateAutomationApprove,
  } = useAutomationSettings();
  const {
    closeDialog: closeInfoDialog,
    dialogOpen: infoDialogOpen,
    loading: systemInfoLoading,
    mcpTokenPending,
    openDialog: openInfoDialog,
    setMcpTokenPending,
    systemInfo,
  } = useSystemInfoDialog();
  const {
    close: closeScreenshotDetails,
    deleteArmed: screenshotDeleteArmed,
    deleting: screenshotDeleting,
    dismiss: dismissScreenshotDetails,
    job: managedJob,
    metadataSaving: screenshotMetadataSaving,
    notes: screenshotNotes,
    open: openScreenshotDetails,
    persisted: managedJobPersisted,
    setDeleteArmed: setScreenshotDeleteArmed,
    setDeleting: setScreenshotDeleting,
    setMetadataSaving: setScreenshotMetadataSaving,
    setNotes: setScreenshotNotes,
    setTagInput: setScreenshotTagInput,
    setTitle: setScreenshotTitle,
    syncFields: syncScreenshotDetails,
    tagInput: screenshotTagInput,
    title: screenshotTitle,
  } = useScreenshotDetails({
    history,
    historySearchResults,
    jobs,
    onError: setError,
  });
  const benchmarkDatasetInputRef = useRef<HTMLInputElement | null>(null);
  const jobsRef = useRef(jobs);
  const processingCacheInitializedRef = useRef(false);
  const processingMembershipGenerationRef = useRef(0);
  const processingMutationCountRef = useRef(0);
  const processingRemovalCandidateIdsRef = useRef(
    new Set(
      initialProcessingMutationLease?.kind === "archive"
        ? initialProcessingMutationLease.jobIds
        : [],
    ),
  );
  const processingUpdateCandidateIdsRef = useRef(new Set<string>());
  const processingMutationLeaseRef = useRef(initialProcessingMutationLease);
  const historyMutationGenerationRef = useRef(0);
  const historyMutationCountRef = useRef(0);
  const historyUpdateCandidateIdsRef = useRef(
    new Set(mutationLeaseJobIds(initialHistoryMutationLease)),
  );
  const historyMutationLeaseRef = useRef(initialHistoryMutationLease);
  const benchmarkImportRecoveryPending =
    benchmarkImportLeaseRequestId(
      mutationLeases.processing,
      mutationLeases.history,
    ) !== null;
  const {
    closeDialog: closeBenchmarkDialog,
    comparisonProgress: benchmarkComparisonProgress,
    comparisonReport: benchmarkComparisonReport,
    comparisonReportLoading: benchmarkComparisonReportLoading,
    datasetExportDisabled: benchmarkDatasetExportDisabled,
    dialogOpen: benchmarkDialogOpen,
    importing: benchmarkImporting,
    includedCases: benchmarkIncludedCases,
    loading: benchmarkLoading,
    openDialog: openBenchmarkDialog,
    operationsLocked: benchmarkOperationsLocked,
    overview: benchmarkOverview,
    parserPipelines: benchmarkParserPipelines,
    previousReport: previousBenchmarkReport,
    recentReports: recentBenchmarkReports,
    refreshOverview: refreshBenchmarkOverview,
    report: benchmarkReport,
    reportLoading: benchmarkReportLoading,
    reportParserLabel: benchmarkReportParserLabel,
    reportStale: benchmarkReportStale,
    reset: resetBenchmark,
    reviewCase: reviewBenchmarkCase,
    reviewJobId: benchmarkReviewJobId,
    run: onRunBenchmark,
    runComparison: onRunBenchmarkComparison,
    running: benchmarkRunning,
    selectParserPipeline: selectBenchmarkParserPipeline,
    selectReport: selectBenchmarkReport,
    setImporting: setBenchmarkImporting,
    setOverview: setBenchmarkOverview,
    setUpdating: setBenchmarkUpdating,
    targetLayoutLabel: benchmarkTargetLayoutLabel,
    targetLayoutProfile: benchmarkTargetLayoutProfile,
    updating: benchmarkUpdating,
  } = useBenchmarkController({
    busy,
    importRecoveryPending: benchmarkImportRecoveryPending,
    mutationRecoveryPending: () =>
      mutationRecoveryPending(["processing", "history"]),
    onError: setError,
    onOpenJob: upsertAndActivateJob,
    pipelineCapabilities,
    pipelineLoading,
    pipelineSelection,
    loadPipelineCapabilities,
    setPipelineSelection,
  });

  useAnalyzerRouteRestore({
    activateJob: (nextJob) => upsertAndActivateJob(nextJob, false),
    activeJobId,
    benchmarksOpen: benchmarkDialogOpen,
    closeBenchmarks: closeBenchmarkDialog,
    closeTraining: () => setTrainingDialogOpen(false),
    jobs,
    loadJob: (jobId) => fetchJobQuery(queryClient, jobId),
    onError: (routeError) =>
      setError(
        messageFromError(
          routeError,
          "The requested analyzer job could not load",
        ),
      ),
    onJobLoading: (jobId) => {
      alignWorkspaceToJob(null);
      selectActiveJob(jobId);
    },
    onJobUnavailable: () => {
      alignWorkspaceToJob(null);
      navigation.openWorkspace({ replace: true });
    },
    openBenchmarks: openBenchmarkDialog,
    openTraining: openTrainingDialog,
    route,
    restoreWorkspace: () => {
      const activeWorkspaceJob = jobsRef.current.find(
        (candidate) => candidate.id === activeJobIdRef.current,
      );
      const workspaceJob =
        activeWorkspaceJob && isLocalUploadError(activeWorkspaceJob)
          ? activeWorkspaceJob
          : (processingJobsForCache(jobsRef.current)[0] ?? null);
      if (activeJobIdRef.current !== (workspaceJob?.id ?? null)) {
        alignWorkspaceToJob(workspaceJob);
      }
    },
    trainingOpen: trainingDialogOpen,
  });

  useEffect(() => {
    appMountedRef.current = true;
    return () => {
      appMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    jobsRef.current = jobs;
    if (!processingCacheInitializedRef.current) {
      processingCacheInitializedRef.current = true;
      return;
    }
    writeProcessingQueue(jobs, !processingQueueSessionSynced());
  }, [jobs]);

  useEffect(() => {
    let restoreTimer: number | null = null;
    const onStorage = (event: StorageEvent) => {
      if (!isProcessingQueueStorageEvent(event)) {
        return;
      }
      markProcessingQueueSessionUnsynced();
      if (restoreTimer !== null) {
        window.clearTimeout(restoreTimer);
      }
      scheduleRecoveryRetry("processing");
      processingStorageRestoreScheduledRef.current = true;
      restoreTimer = window.setTimeout(() => {
        restoreTimer = null;
        processingStorageRestoreScheduledRef.current = false;
        if (processingMutationCountRef.current === 0) {
          scheduleProcessingQueueRestore();
        } else {
          processingRestoreRetryRequestedRef.current = true;
        }
      }, 25);
    };
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("storage", onStorage);
      if (restoreTimer !== null) {
        window.clearTimeout(restoreTimer);
      }
      processingStorageRestoreScheduledRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!jobs.some(isProcessingJobInProgress)) {
      return;
    }
    markProcessingQueueSessionUnsynced();
    scheduleRecoveryRetry("processing");
    const revalidationTimer = window.setTimeout(() => {
      if (processingMutationCountRef.current === 0) {
        scheduleProcessingQueueRestore();
      } else {
        processingRestoreRetryRequestedRef.current = true;
      }
    }, PROCESSING_QUEUE_REVALIDATION_INTERVAL_MS);
    return () => window.clearTimeout(revalidationTimer);
  }, [jobs]);

  useEffect(() => {
    if (
      processingMutationLeaseRef.current === null &&
      historyMutationLeaseRef.current === null
    ) {
      finishRecovery("mutationLease");
      return;
    }
    let retryTimer: number | null = null;
    let retryDelay = PROCESSING_QUEUE_REVALIDATION_INTERVAL_MS;
    let benchmarkImportRetryNotBefore = 0;
    const revalidateLeases = () => {
      retryTimer = null;
      startRecovery("mutationLease");
      let leasePending = false;
      const linkedArchiveLeases = matchingArchiveLeaseTargets(
        processingMutationLeaseRef.current,
        historyMutationLeaseRef.current,
      );
      const benchmarkImportRequestId = benchmarkImportLeaseRequestId(
        processingMutationLeaseRef.current,
        historyMutationLeaseRef.current,
      );
      if (
        benchmarkImportRequestId !== null &&
        benchmarkImportRecoveryPromiseRef.current === null &&
        Date.now() >= benchmarkImportRetryNotBefore
      ) {
        const recovery = fetchBenchmarkImportReceiptQuery(
          queryClient,
          benchmarkImportRequestId,
        )
          .then(async (receipt) => {
            benchmarkImportRetryNotBefore = 0;
            if (
              !appMountedRef.current ||
              benchmarkImportLeaseRequestId(
                processingMutationLeaseRef.current,
                historyMutationLeaseRef.current,
              ) !== benchmarkImportRequestId
            ) {
              return;
            }
            if (receipt.status === "pending") {
              markBenchmarkImportReceiptObserved(benchmarkImportRequestId);
              return;
            }
            if (receipt.status === "failed" || receipt.result === null) {
              clearBenchmarkImportLeases(benchmarkImportRequestId, true);
              setBenchmarkImporting(false);
              setError(
                humanReadableMessage(
                  receipt.error,
                  "Could not recover parser dataset import",
                ),
              );
              markProcessingQueueSessionUnsynced();
              scheduleProcessingQueueRestore();
              markHistorySessionUnsynced();
              void requestHistoryRestore(null, true);
              return;
            }
            setError(null);
            const readyCases = await applyBenchmarkDatasetImportResult(
              receipt.result,
            );
            if (
              !appMountedRef.current ||
              benchmarkImportLeaseRequestId(
                processingMutationLeaseRef.current,
                historyMutationLeaseRef.current,
              ) !== benchmarkImportRequestId
            ) {
              return;
            }
            clearBenchmarkImportLeases(benchmarkImportRequestId);
            setBenchmarkImporting(false);
            toast.success(
              `Dataset recovered: ${readyCases} ${readyCases === 1 ? "hand" : "hands"}`,
            );
            markProcessingQueueSessionUnsynced();
            scheduleProcessingQueueRestore();
            markHistorySessionUnsynced();
            void requestHistoryRestore(null, true);
          })
          .catch((recoveryError) => {
            if (
              recoveryError instanceof ApiResponseError &&
              recoveryError.status === 429 &&
              recoveryError.retryAfterSeconds !== null
            ) {
              benchmarkImportRetryNotBefore = Math.max(
                benchmarkImportRetryNotBefore,
                Date.now() + recoveryError.retryAfterSeconds * 1_000,
              );
              return;
            }
            if (
              recoveryError instanceof ApiResponseError &&
              recoveryError.status === 404
            ) {
              const importLeases = [
                processingMutationLeaseRef.current,
                historyMutationLeaseRef.current,
              ].flatMap((lease) =>
                isBenchmarkImportLease(lease, benchmarkImportRequestId)
                  ? [lease]
                  : [],
              );
              if (
                importLeases.length > 0 &&
                importLeases.every(
                  (lease) =>
                    !lease.benchmarkImportReceiptObserved &&
                    Date.now() >= lease.expiresAt,
                )
              ) {
                clearBenchmarkImportLeases(benchmarkImportRequestId, true);
                markProcessingQueueSessionUnsynced();
                scheduleProcessingQueueRestore();
                markHistorySessionUnsynced();
                void requestHistoryRestore(null, true);
              }
              return;
            }
            // Network failures remain recoverable for the lifetime of the lease.
          })
          .finally(() => {
            if (benchmarkImportRecoveryPromiseRef.current === recovery) {
              benchmarkImportRecoveryPromiseRef.current = null;
              if (appMountedRef.current) {
                if (
                  processingMutationLeaseRef.current !== null ||
                  historyMutationLeaseRef.current !== null
                ) {
                  scheduleRecoveryRetry("mutationLease");
                } else {
                  finishRecovery("mutationLease");
                }
              }
            }
          });
        benchmarkImportRecoveryPromiseRef.current = recovery;
      }
      const processingLease = processingMutationLeaseRef.current;
      if (processingLease !== null) {
        const retainedImportLease =
          benchmarkImportRequestId !== null &&
          isBenchmarkImportLease(processingLease, benchmarkImportRequestId) &&
          processingLease.benchmarkImportReceiptObserved;
        if (Date.now() >= processingLease.expiresAt && !retainedImportLease) {
          clearPersistedMutationLease("processing", mutationOwnerId);
          setRuntimeMutationLease("processing", null);
          markProcessingQueueSessionUnsynced();
          if (processingMutationCountRef.current === 0) {
            scheduleProcessingQueueRestore();
          } else {
            processingRestoreRetryRequestedRef.current = true;
          }
        } else {
          leasePending = true;
          markProcessingQueueSessionUnsynced();
          if (
            !isBenchmarkImportLease(
              processingLease,
              benchmarkImportRequestId ?? "",
            )
          ) {
            if (processingMutationCountRef.current === 0) {
              scheduleProcessingQueueRestore();
            } else {
              processingRestoreRetryRequestedRef.current = true;
            }
          }
        }
      }

      const historyLease = historyMutationLeaseRef.current;
      if (historyLease !== null) {
        const historyLeaseJobIds = mutationLeaseJobIds(historyLease);
        const retainedImportLease =
          benchmarkImportRequestId !== null &&
          isBenchmarkImportLease(historyLease, benchmarkImportRequestId) &&
          historyLease.benchmarkImportReceiptObserved;
        if (Date.now() >= historyLease.expiresAt && !retainedImportLease) {
          clearPersistedMutationLease("history", mutationOwnerId);
          setRuntimeMutationLease("history", null);
          for (const jobId of historyLeaseJobIds) {
            historyUpdateCandidateIdsRef.current.delete(jobId);
          }
          markHistorySessionUnsynced();
          if (linkedArchiveLeases) {
            void requestHistoryRestore(null, true);
          } else if (historyLeaseJobIds.length > 0) {
            requestHistoryJobRestore(historyLeaseJobIds);
          } else {
            void requestHistoryRestore(null, true);
          }
        } else {
          leasePending = true;
          markHistorySessionUnsynced();
          if (
            !linkedArchiveLeases &&
            !isBenchmarkImportLease(
              historyLease,
              benchmarkImportRequestId ?? "",
            )
          ) {
            if (historyLeaseJobIds.length > 0) {
              requestHistoryJobRestore(historyLeaseJobIds);
            } else {
              void requestHistoryRestore(null, true);
            }
          }
        }
      }

      if (leasePending) {
        retryDelay = Math.min(retryDelay * 2, 2_000);
        retryTimer = window.setTimeout(
          revalidateLeases,
          Math.max(retryDelay, benchmarkImportRetryNotBefore - Date.now()),
        );
        if (benchmarkImportRecoveryPromiseRef.current === null) {
          scheduleRecoveryRetry("mutationLease");
        }
      } else {
        finishRecovery("mutationLease");
      }
    };
    if (
      benchmarkImportRecoveryPromiseRef.current === null &&
      (processingMutationLeaseRef.current !== null ||
        historyMutationLeaseRef.current !== null)
    ) {
      scheduleRecoveryRetry("mutationLease");
    }
    retryTimer = window.setTimeout(revalidateLeases, retryDelay);
    return () => {
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
      }
    };
  }, [mutationLeaseRestoreRequest]);

  const filmstripCount = jobs.length > 0 ? jobs.length : files.length;
  const frameLabel = job
    ? screenshotLabel(job)
    : screenSharing
      ? `${screenSourceLabel ?? shareModeLabel(shareMode)} live preview`
      : "No table selected";
  const frameStreet = form.street === "" ? "No street" : form.street;
  const queueCount = jobs.length > 0 ? jobs.length : files.length;
  const liveStatusLabel = screenSharing
    ? `${screenSourceLabel ?? shareModeLabel(shareMode)} sharing`
    : inputMode === "upload"
      ? "Upload queue"
      : "Live capture";
  const automationEnabled = automationSettings.enabled;
  const automationApprove = automationSettings.autoApprove;
  const automationRecommend = automationSettings.autoRecommend;
  const automationAllowWarnings = automationSettings.allowWarnings;
  const clearableJobs = useMemo(() => jobs.filter(isHistoryReady), [jobs]);
  const historySearchActive = historySearchResults !== null;
  const visibleHistory = historySearchResults ?? history;
  const visibleHistoryTotal = historySearchActive
    ? historySearchTotal
    : historyTotal;
  const managedLocalUploadRecoveryPending = Boolean(
    managedJob &&
    !managedJobPersisted &&
    localUploadDeletionRequiresRecovery(managedJob),
  );
  const activeParserRouting = parserRoutingFromRaw(job?.parser_result?.raw);
  const activeParserProvider =
    activeParserRouting?.selectedProvider ??
    systemInfo?.parser_provider ??
    job?.parser_provider ??
    null;
  const activeRecommendationProvider =
    systemInfo?.recommendation_engine ??
    systemInfo?.recommendation_provider ??
    job?.recommendation_provider ??
    null;
  const activeInfoProviders =
    activeParserProvider && activeRecommendationProvider
      ? {
          recognition: providerLabel(activeParserProvider),
          recognitionFallbackFrom: activeParserRouting?.fallbackFrom
            ? providerLabel(activeParserRouting.fallbackFrom)
            : null,
          recognitionRoute: activeParserRouting
            ? providerLabel(activeParserRouting.provider)
            : null,
          recommendation: providerLabel(activeRecommendationProvider),
        }
      : null;
  const visibleTrainingHands =
    trainingProgressView === "review"
      ? (trainingProgress?.review_queue ?? [])
      : trainingProgressView === "lessons"
        ? (trainingProgress?.lesson_hands ?? [])
        : (trainingProgress?.recent_hands ?? []);
  const matchingTrainingLessons =
    trainingProgress?.lesson_matching_hands ??
    trainingProgress?.lesson_hands?.length ??
    0;
  const trainingLessonsExportDisabled =
    matchingTrainingLessons === 0 ||
    trainingProgressLoading ||
    trainingReviewJobId !== null ||
    busy;
  const nextReviewHand =
    trainingProgressView === "lessons" ||
    (trainingProgressView === "recent" &&
      (trainingSolverFilter ||
        trainingPositionFilter ||
        trainingStreetFilter ||
        trainingCertaintyFilter))
      ? null
      : (trainingProgress?.review_queue[0] ?? null);
  const reviewQueueStatus = trainingReviewQueueStatus(
    trainingProgress,
    trainingProgressView,
    trainingProgressLoading,
    trainingReviewOrder,
    trainingReviewStreet,
    trainingReviewDifference,
    trainingReviewCertainty,
    trainingReviewPosition,
    trainingLessonStreet,
    trainingLessonQuery,
    trainingLessonOrder,
    trainingSolverFilter,
    trainingPositionFilter,
    trainingStreetFilter,
    trainingCertaintyFilter,
  );
  const trainingFocus = trainingProgress
    ? suggestedTrainingFocus(trainingProgress)
    : null;
  const certaintyFocus = trainingProgress
    ? suggestedCertaintyFocus(trainingProgress)
    : null;
  const positionFocus = trainingProgress
    ? suggestedPositionFocus(trainingProgress)
    : null;
  const actionDifferenceFocus = trainingProgress
    ? suggestedActionDifferenceFocus(trainingProgress)
    : null;

  function setError(nextError: string | null) {
    setErrorMessage(nextError);
    setErrorSequence((current) => current + 1);
  }

  function scheduleProcessingQueueRestore() {
    processingRestoreRetryRequestedRef.current = false;
    processingRestorePromiseRef.current = null;
    requestProcessingRecovery();
  }

  function scheduleMutationLeaseRevalidation() {
    requestMutationLeaseRevalidation();
  }

  function setRuntimeMutationLease(
    scope: PersistedJobMutationScope,
    lease: PersistedMutationLease | null,
  ) {
    if (scope === "processing") {
      processingMutationLeaseRef.current = lease;
    } else {
      historyMutationLeaseRef.current = lease;
    }
    setWorkflowMutationLease(scope, lease);
  }

  function installMutationLease(
    scope: PersistedJobMutationScope,
    lease: PersistedMutationLease | null,
  ) {
    if (scope === "processing") {
      setRuntimeMutationLease(scope, lease);
      markProcessingQueueSessionUnsynced();
      return;
    }
    setRuntimeMutationLease(scope, lease);
    for (const jobId of mutationLeaseJobIds(lease)) {
      historyUpdateCandidateIdsRef.current.add(jobId);
    }
    markHistorySessionUnsynced();
  }

  function clearOwnedMutationLease(scope: PersistedJobMutationScope) {
    if (!appMountedRef.current) {
      return;
    }
    clearPersistedMutationLease(scope, mutationOwnerId);
    if (scope === "processing") {
      if (processingMutationLeaseRef.current?.ownerId === mutationOwnerId) {
        setRuntimeMutationLease(scope, null);
      }
      return;
    }
    const historyLease = historyMutationLeaseRef.current;
    if (historyLease?.ownerId === mutationOwnerId) {
      for (const jobId of mutationLeaseJobIds(historyLease)) {
        historyUpdateCandidateIdsRef.current.delete(jobId);
      }
      setRuntimeMutationLease(scope, null);
    }
  }

  function markBenchmarkImportReceiptObserved(requestId: string) {
    for (const scope of ["processing", "history"] as const) {
      const leaseRef =
        scope === "processing"
          ? processingMutationLeaseRef
          : historyMutationLeaseRef;
      const lease = leaseRef.current;
      if (!isBenchmarkImportLease(lease, requestId)) {
        continue;
      }
      const updatedLease: ProjectionMutationLease = {
        ...lease,
        benchmarkImportReceiptObserved: true,
        expiresAt: Date.now() + PERSISTED_MUTATION_LEASE_MS,
      };
      if (replacePersistedMutationLease(scope, lease, updatedLease)) {
        setRuntimeMutationLease(scope, updatedLease);
      }
    }
  }

  function clearBenchmarkImportLeases(
    requestId: string,
    releaseRemovalCandidates = false,
  ) {
    const processingLease = processingMutationLeaseRef.current;
    if (isBenchmarkImportLease(processingLease, requestId)) {
      if (releaseRemovalCandidates) {
        for (const jobId of processingLease.expectedRemovalJobIds) {
          processingRemovalCandidateIdsRef.current.delete(jobId);
        }
      }
      clearOwnedMutationLease("processing");
    }
    if (isBenchmarkImportLease(historyMutationLeaseRef.current, requestId)) {
      clearOwnedMutationLease("history");
    }
  }

  function mutationRecoveryPending(
    scopes: readonly PersistedJobMutationScope[],
  ): boolean {
    const pending = scopes.some((scope) =>
      scope === "processing"
        ? processingMutationLeaseRef.current !== null
        : historyMutationLeaseRef.current !== null,
    );
    if (!pending) {
      return false;
    }
    scheduleMutationLeaseRevalidation();
    setError(
      "Finishing recovery from a previous action. Try again in a moment.",
    );
    return true;
  }

  function mutationComposesWithActiveRecommendation(
    scope: PersistedJobMutationScope,
  ): boolean {
    const lease =
      scope === "processing"
        ? processingMutationLeaseRef.current
        : historyMutationLeaseRef.current;
    if (lease?.ownerId !== mutationOwnerId) {
      return false;
    }
    const activeRequests = [
      ...activeRecommendationRequestsRef.current.entries(),
    ].filter(([, request]) => request.mutationScope === scope);
    if (lease.kind === "job") {
      return activeRequests.some(([jobId]) => jobId === lease.jobId);
    }
    return (
      lease.kind === "projection" &&
      lease.benchmarkImportRequestId === null &&
      activeRequests.length > 0
    );
  }

  function localUploadDeletionRequiresRecovery(localJob: JobRecord): boolean {
    if (!isLocalUploadError(localJob) || !localJob.upload_request_id) {
      return false;
    }
    const lease = processingMutationLeaseRef.current;
    const expectedUpload =
      lease?.kind === "projection"
        ? lease.expectedUploads.find(
            (candidate) => candidate.requestId === localJob.upload_request_id,
          )
        : undefined;
    if (expectedUpload?.target === "failed") {
      return false;
    }
    return expectedUpload !== undefined || !processingQueueSessionSynced();
  }

  function trackExpectedUpload(
    requestId: string,
    target: ProjectionMutationTarget,
    recommendationRequestId: string | null,
  ): number | null {
    const lease = processingMutationLeaseRef.current;
    if (lease?.kind !== "projection") {
      return null;
    }
    const updatedLease: ProjectionMutationLease = {
      ...lease,
      expectedUploads: [
        ...lease.expectedUploads,
        { requestId, target, recommendationRequestId },
      ],
      expiresAt: Date.now() + PERSISTED_MUTATION_LEASE_MS,
    };
    if (replacePersistedMutationLease("processing", lease, updatedLease)) {
      setRuntimeMutationLease("processing", updatedLease);
      return updatedLease.expectedUploads.length - 1;
    }
    return null;
  }

  function updateExpectedUpload(
    expectedUploadIndex: number | null,
    target: ProjectionMutationTarget,
  ) {
    const lease = processingMutationLeaseRef.current;
    if (
      lease?.kind !== "projection" ||
      expectedUploadIndex === null ||
      lease.expectedUploads[expectedUploadIndex] === undefined
    ) {
      return;
    }
    const expectedUploads = [...lease.expectedUploads];
    expectedUploads[expectedUploadIndex] = {
      ...expectedUploads[expectedUploadIndex],
      target,
      recommendationRequestId:
        target === "recommended"
          ? expectedUploads[expectedUploadIndex].recommendationRequestId
          : null,
    };
    const updatedLease: ProjectionMutationLease = {
      ...lease,
      expectedUploads,
      expiresAt: Date.now() + PERSISTED_MUTATION_LEASE_MS,
    };
    if (replacePersistedMutationLease("processing", lease, updatedLease)) {
      setRuntimeMutationLease("processing", updatedLease);
    }
  }

  function settlePersistedMutationLease(
    scope: PersistedJobMutationScope,
    incomingJobs: readonly JobRecord[],
    completeProcessingProjection: boolean,
  ): boolean {
    const leaseRef =
      scope === "processing"
        ? processingMutationLeaseRef
        : historyMutationLeaseRef;
    const lease = leaseRef.current;
    if (lease === null) {
      return false;
    }
    const storedLease = readPersistedMutationLease(scope);
    if (
      storedLease === null ||
      storedLease.ownerId !== mutationOwnerId ||
      storedLease.kind !== lease.kind ||
      storedLease.expiresAt !== lease.expiresAt
    ) {
      setRuntimeMutationLease(scope, null);
      return false;
    }

    let settled = false;
    if (lease.kind === "job") {
      const incomingJob = incomingJobs.find(
        (candidate) => candidate.id === lease.jobId,
      );
      if (
        incomingJob !== undefined &&
        lease.expectedRecommendationRequestId !== null
      ) {
        settled =
          incomingJob.recommendation_request_id ===
            lease.expectedRecommendationRequestId &&
          !incomingJob.recommendation_pending;
      } else if (incomingJob !== undefined && lease.expectedMutation !== null) {
        settled = jobMutationExpectationReached(
          incomingJob,
          lease.expectedMutation,
        );
      } else {
        settled = false;
      }
    } else if (lease.kind === "projection") {
      if (lease.benchmarkImportRequestId !== null) {
        settled = false;
      } else if (lease.expectedUploads.length > 0) {
        const baselineIds = new Set(lease.baselineJobIds);
        const availableJobs = incomingJobs.filter(
          (job) => !baselineIds.has(job.id) && !isLocalUploadError(job),
        );
        settled = lease.expectedUploads.every((expectedUpload) => {
          if (expectedUpload.target === "failed") {
            return true;
          }
          const matchingIndex = availableJobs.findIndex(
            (job) =>
              job.upload_request_id === expectedUpload.requestId &&
              projectionMutationTargetReached(
                job,
                expectedUpload.target,
                expectedUpload.recommendationRequestId,
              ),
          );
          if (matchingIndex === -1) {
            return false;
          }
          availableJobs.splice(matchingIndex, 1);
          return true;
        });
      } else if (lease.expectedRemovalJobIds.length > 0) {
        const incomingIds = new Set(incomingJobs.map((job) => job.id));
        settled =
          completeProcessingProjection &&
          lease.expectedRemovalJobIds.every((jobId) => !incomingIds.has(jobId));
      }
    } else if (scope === "processing") {
      const incomingById = new Map(incomingJobs.map((job) => [job.id, job]));
      const confirmationIds = new Set(lease.confirmationJobIds);
      settled =
        completeProcessingProjection &&
        lease.jobIds.every((jobId) => {
          const incomingJob = incomingById.get(jobId);
          if (!confirmationIds.has(jobId)) {
            return incomingJob === undefined;
          }
          return (
            incomingJob !== undefined &&
            incomingJob.archived_at !== null &&
            incomingJob.updated_at !== lease.baselineUpdatedAt[jobId]
          );
        });
    } else {
      const incomingById = new Map(incomingJobs.map((job) => [job.id, job]));
      settled = lease.jobIds.every((jobId) => {
        const incomingJob = incomingById.get(jobId);
        return (
          incomingJob !== undefined &&
          incomingJob.archived_at !== null &&
          incomingJob.updated_at !== lease.baselineUpdatedAt[jobId]
        );
      });
    }
    if (!settled) {
      return false;
    }

    clearPersistedMutationLease(scope, mutationOwnerId);
    setRuntimeMutationLease(scope, null);
    const targetJobIds = mutationLeaseJobIds(lease);
    for (const jobId of targetJobIds) {
      processingUpdateCandidateIdsRef.current.delete(jobId);
    }
    if (scope === "history") {
      historyMutationGenerationRef.current += 1;
      for (const jobId of targetJobIds) {
        historyUpdateCandidateIdsRef.current.delete(jobId);
      }
    }
    if (
      scope === "processing" &&
      lease.kind === "archive" &&
      matchingArchiveLeaseTargets(lease, historyMutationLeaseRef.current)
    ) {
      clearPersistedMutationLease("history", mutationOwnerId);
      setRuntimeMutationLease("history", null);
      historyMutationGenerationRef.current += 1;
      for (const jobId of lease.jobIds) {
        historyUpdateCandidateIdsRef.current.delete(jobId);
      }
      markHistorySessionUnsynced();
      void requestHistoryRestore(null, true);
    }
    return true;
  }

  function requestHistoryRestore(
    jobIds: string[] | null = null,
    queueAfterActive = false,
  ): Promise<boolean> {
    const activeRestore = historyRestorePromiseRef.current;
    if (activeRestore) {
      if (queueAfterActive) {
        if (jobIds === null) {
          historyFullRestoreRequestedRef.current = true;
        }
        historyRestoreRetryRequestedRef.current = true;
      }
      return activeRestore;
    }

    if (jobIds === null) {
      historyFullRestoreRequestedRef.current = false;
    }
    historyRestoreRetryRequestedRef.current = false;
    const restore = syncHistory(jobIds, false);
    historyRestorePromiseRef.current = restore;
    void restore.finally(() => {
      if (historyRestorePromiseRef.current !== restore) {
        return;
      }
      historyRestorePromiseRef.current = null;
      if (
        historyRestoreRetryRequestedRef.current &&
        historyMutationCountRef.current === 0
      ) {
        historyRestoreRetryRequestedRef.current = false;
        requestDeferredHistoryRestore();
      }
    });
    return restore;
  }

  function requestDeferredHistoryRestore() {
    const targetJobIds = new Set([
      ...historyJobRestoreIdsRef.current,
      ...historyUpdateCandidateIdsRef.current,
    ]);
    if (targetJobIds.size > 0) {
      if (historyJobRestoreRetryTimerRef.current !== null) {
        if (historyFullRestoreRequestedRef.current) {
          historyFullRestoreRequestedRef.current = false;
          void requestHistoryRestore(null, true);
        }
        return;
      }
      if (historyFullRestoreRequestedRef.current) {
        historyRestoreRetryRequestedRef.current = true;
      }
      requestHistoryJobRestore([...targetJobIds]);
      return;
    }
    historyFullRestoreRequestedRef.current = false;
    void requestHistoryRestore(null, true);
  }

  function scheduleHistoryJobRestoreRetry() {
    if (historyJobRestoreRetryTimerRef.current !== null) {
      return;
    }
    historyJobRestoreRetryTimerRef.current = window.setTimeout(() => {
      historyJobRestoreRetryTimerRef.current = null;
      if (
        historyMutationCountRef.current > 0 ||
        historyRestorePromiseRef.current ||
        historyJobRestorePromiseRef.current
      ) {
        historyRestoreRetryRequestedRef.current = true;
        return;
      }
      requestDeferredHistoryRestore();
    }, PROCESSING_QUEUE_REVALIDATION_INTERVAL_MS);
  }

  function hasPendingHistoryJobRestore(
    resolvedJobIds: ReadonlySet<string>,
  ): boolean {
    return [
      ...historyUpdateCandidateIdsRef.current,
      ...historyJobRestoreIdsRef.current,
      ...historyJobRestoreActiveIdsRef.current,
    ].some((jobId) => !resolvedJobIds.has(jobId));
  }

  function requestHistoryJobRestore(jobIds: readonly string[]) {
    let queuedNewTarget = false;
    for (const jobId of jobIds) {
      if (
        !historyJobRestoreActiveIdsRef.current.has(jobId) &&
        !historyJobRestoreIdsRef.current.has(jobId)
      ) {
        historyJobRestoreIdsRef.current.add(jobId);
        queuedNewTarget = true;
      }
    }
    if (historyMutationCountRef.current > 0) {
      historyRestoreRetryRequestedRef.current = true;
      return;
    }
    if (historyJobRestorePromiseRef.current) {
      if (queuedNewTarget) {
        historyRestoreRetryRequestedRef.current = true;
      }
      return;
    }

    const requestedJobIds = [...historyJobRestoreIdsRef.current];
    if (requestedJobIds.length === 0) {
      return;
    }
    historyJobRestoreIdsRef.current.clear();
    historyJobRestoreActiveIdsRef.current = new Set(requestedJobIds);
    const restoreGeneration = historyMutationGenerationRef.current;
    const restore = Promise.all(
      requestedJobIds.map((jobId) => fetchJobQuery(queryClient, jobId)),
    )
      .then((incomingJobs) => {
        if (
          historyMutationGenerationRef.current !== restoreGeneration ||
          historyMutationCountRef.current > 0
        ) {
          for (const jobId of requestedJobIds) {
            historyJobRestoreIdsRef.current.add(jobId);
          }
          markHistorySessionUnsynced();
          historyRestoreRetryRequestedRef.current = true;
          return;
        }
        applyHistoryJobUpdates(incomingJobs);
      })
      .catch(() => {
        for (const jobId of requestedJobIds) {
          historyJobRestoreIdsRef.current.add(jobId);
        }
        markHistorySessionUnsynced();
        historyRestoreRetryRequestedRef.current =
          historyFullRestoreRequestedRef.current;
        scheduleHistoryJobRestoreRetry();
      });
    historyJobRestorePromiseRef.current = restore;
    void restore.finally(() => {
      if (historyJobRestorePromiseRef.current !== restore) {
        return;
      }
      historyJobRestorePromiseRef.current = null;
      historyJobRestoreActiveIdsRef.current.clear();
      if (
        historyRestoreRetryRequestedRef.current &&
        historyMutationCountRef.current === 0
      ) {
        historyRestoreRetryRequestedRef.current = false;
        requestDeferredHistoryRestore();
      }
    });
  }

  function beginHistoryMutation() {
    historyMutationCountRef.current += 1;
    historyMutationGenerationRef.current += 1;
    markHistorySessionUnsynced();
  }

  function endHistoryMutation(restoreAfterMutation = false) {
    historyMutationCountRef.current = Math.max(
      historyMutationCountRef.current - 1,
      0,
    );
    if (restoreAfterMutation) {
      historyRestoreRetryRequestedRef.current = true;
    }
    if (
      historyMutationCountRef.current === 0 &&
      historyRestoreRetryRequestedRef.current
    ) {
      historyRestoreRetryRequestedRef.current = false;
      requestDeferredHistoryRestore();
    }
  }

  function beginProcessingMembershipMutation(
    removalCandidateIds: readonly string[] = [],
    updateCandidateIds: readonly string[] = [],
  ) {
    for (const removalCandidateId of removalCandidateIds) {
      processingRemovalCandidateIdsRef.current.add(removalCandidateId);
    }
    for (const updateCandidateId of updateCandidateIds) {
      processingUpdateCandidateIdsRef.current.add(updateCandidateId);
    }
    processingMutationCountRef.current += 1;
    processingMembershipGenerationRef.current += 1;
    markProcessingQueueSessionUnsynced();
  }

  function endProcessingMembershipMutation(restoreAfterMutation = true) {
    processingMutationCountRef.current = Math.max(
      processingMutationCountRef.current - 1,
      0,
    );
    if (restoreAfterMutation) {
      processingRestoreRetryRequestedRef.current = true;
    }
    if (
      processingMutationCountRef.current === 0 &&
      processingRestoreRetryRequestedRef.current
    ) {
      scheduleProcessingQueueRestore();
    }
  }

  function beginPersistedJobMutation(
    persistedJob: JobRecord,
    expectedMutation: JobMutationExpectation | null,
    removalCandidateIds: readonly string[] = [],
  ): PersistedJobMutationScope {
    const scope = persistedJobMutationScope(persistedJob);
    const lease = startPersistedMutationLease(
      scope,
      mutationOwnerId,
      persistedJob,
      expectedMutation,
      removalCandidateIds.includes(persistedJob.id),
    );
    if (scope === "history") {
      setRuntimeMutationLease(scope, lease);
      beginHistoryMutation();
      return "history";
    }
    setRuntimeMutationLease(scope, lease);
    beginProcessingMembershipMutation(removalCandidateIds);
    return "processing";
  }

  function armPersistedRecommendationLease(
    mutationScope: PersistedJobMutationScope,
    jobId: string,
    recommendationRequestId: string,
  ): boolean {
    const leaseRef =
      mutationScope === "processing"
        ? processingMutationLeaseRef
        : historyMutationLeaseRef;
    const lease = leaseRef.current;
    if (lease === null) {
      return true;
    }
    if (
      lease.kind !== "job" ||
      lease.jobId !== jobId ||
      lease.ownerId !== mutationOwnerId
    ) {
      return false;
    }
    const armedLease: JobMutationLease = {
      ...lease,
      expectedRecommendationRequestId: recommendationRequestId,
      expectedMutation: null,
      expiresAt: Date.now() + PERSISTED_MUTATION_LEASE_MS,
    };
    if (!replacePersistedMutationLease(mutationScope, lease, armedLease)) {
      return false;
    }
    setRuntimeMutationLease(mutationScope, armedLease);
    return true;
  }

  function persistedJobMutationScope(
    persistedJob: JobRecord,
  ): PersistedJobMutationScope {
    return persistedJob.archived_at ? "history" : "processing";
  }

  function markPersistedJobMutationUncertain(
    mutationScope: PersistedJobMutationScope,
    persistedJobId: string,
  ) {
    if (mutationScope === "processing") {
      processingUpdateCandidateIdsRef.current.add(persistedJobId);
      return;
    }
    historyUpdateCandidateIdsRef.current.add(persistedJobId);
  }

  function endPersistedJobMutation(
    mutationScope: PersistedJobMutationScope,
    restoreAfterMutation: boolean,
  ) {
    if (!appMountedRef.current) {
      return;
    }
    const leaseRef =
      mutationScope === "processing"
        ? processingMutationLeaseRef
        : historyMutationLeaseRef;
    const lease = leaseRef.current;
    const updateCandidates =
      mutationScope === "processing"
        ? processingUpdateCandidateIdsRef.current
        : historyUpdateCandidateIdsRef.current;
    const retainUncertainLease = mutationLeaseJobIds(lease).some((jobId) =>
      updateCandidates.has(jobId),
    );
    if (retainUncertainLease) {
      scheduleMutationLeaseRevalidation();
    } else {
      clearPersistedMutationLease(mutationScope, mutationOwnerId);
      if (lease?.ownerId === mutationOwnerId) {
        setRuntimeMutationLease(mutationScope, null);
      }
    }
    if (mutationScope === "processing") {
      endProcessingMembershipMutation(restoreAfterMutation);
      return;
    }
    endHistoryMutation(restoreAfterMutation);
  }

  function markPersistedJobSessionUnsynced(persistedJob: JobRecord) {
    if (persistedJob.archived_at) {
      markHistorySessionUnsynced();
      return;
    }
    markProcessingQueueSessionUnsynced();
  }

  useEffect(() => {
    if (error) {
      toast.error(error, { id: ERROR_TOAST_ID });
      return;
    }
    toast.dismiss(ERROR_TOAST_ID);
  }, [error, errorSequence]);

  useEffect(() => {
    const cachedHistory = readHistory();
    if (
      historySessionSynced() &&
      readCachedHistoryTotal(cachedHistory) !== null
    ) {
      return;
    }

    const legacyJobs = (cachedHistory ?? []).filter(
      (item) =>
        item.job.archived_at == null && PERSISTED_JOB_ID_PATTERN.test(item.id),
    );
    const legacyJobIds = legacyJobs.map((item) => item.id);
    if (legacyJobIds.length > 0) {
      installMutationLease(
        "processing",
        startArchiveMutationLease(
          "processing",
          mutationOwnerId,
          legacyJobs.map((item) => item.job),
        ),
      );
      installMutationLease(
        "history",
        startArchiveMutationLease(
          "history",
          mutationOwnerId,
          legacyJobs.map((item) => item.job),
        ),
      );
      const migration = requestHistoryRestore(legacyJobIds);
      legacyHistoryArchivePromiseRef.current = migration;
      void migration;
      return;
    }
    void requestHistoryRestore();
  }, []);

  useEffect(
    () => () => {
      if (historyJobRestoreRetryTimerRef.current !== null) {
        window.clearTimeout(historyJobRestoreRetryTimerRef.current);
        historyJobRestoreRetryTimerRef.current = null;
      }
    },
    [],
  );

  useEffect(() => {
    const pendingArchivedJobIds = new Set([
      ...history.flatMap((item) =>
        item.job.recommendation_pending ? [item.id] : [],
      ),
      ...(historySearchResults ?? []).flatMap((item) =>
        item.job.recommendation_pending ? [item.id] : [],
      ),
      ...jobs.flatMap((candidate) =>
        candidate.archived_at && candidate.recommendation_pending
          ? [candidate.id]
          : [],
      ),
    ]);
    if (pendingArchivedJobIds.size === 0) {
      return;
    }
    markHistorySessionUnsynced();
    const revalidationTimer = window.setInterval(() => {
      requestHistoryJobRestore([...pendingArchivedJobIds]);
    }, PROCESSING_QUEUE_REVALIDATION_INTERVAL_MS);
    return () => window.clearInterval(revalidationTimer);
  }, [history, historySearchResults, jobs]);

  useEffect(() => {
    const cachedJobs = readProcessingQueue();
    const legacyHistoryArchive = legacyHistoryArchivePromiseRef.current;
    if (
      legacyHistoryArchive === null &&
      processingQueueSessionSynced() &&
      readCachedProcessingQueueTotal(cachedJobs) !== null &&
      !cachedJobs?.some(isProcessingJobInProgress)
    ) {
      if (processingStorageRestoreScheduledRef.current) {
        scheduleRecoveryRetry("processing");
      } else {
        finishRecovery("processing");
      }
      return;
    }
    startRecovery("processing");
    markProcessingQueueSessionUnsynced();

    const cachedIds = new Set(
      (cachedJobs ?? []).map((cachedJob) => cachedJob.id),
    );
    const restoreGeneration = processingMembershipGenerationRef.current;
    processingRestorePromiseRef.current ??= (async () => {
      if (legacyHistoryArchive !== null && !(await legacyHistoryArchive)) {
        throw new Error(
          "Could not migrate legacy history before restoring processing",
        );
      }
      const queue = await getProcessingQueueExtent(queryClient);
      const lease = processingMutationLeaseRef.current;
      if (
        lease?.kind === "job" &&
        !queue.jobs.some((candidate) => candidate.id === lease.jobId)
      ) {
        const leasedJob = await fetchJobQuery(queryClient, lease.jobId);
        return {
          ...queue,
          revalidatedLeaseJob: leasedJob,
        };
      }
      if (lease?.kind === "archive" && lease.confirmationJobIds.length > 0) {
        const queueIds = new Set(queue.jobs.map((candidate) => candidate.id));
        const confirmationJobs = await Promise.all(
          lease.confirmationJobIds
            .filter((jobId) => !queueIds.has(jobId))
            .map((jobId) => fetchJobQuery(queryClient, jobId)),
        );
        return {
          ...queue,
          revalidatedArchiveJobs: confirmationJobs,
        };
      }
      return queue;
    })();
    let active = true;
    let restoreRetryTimer: number | null = null;
    void processingRestorePromiseRef.current
      .then((queue) => {
        if (!active) {
          return;
        }
        if (processingMembershipGenerationRef.current !== restoreGeneration) {
          markProcessingQueueSessionUnsynced();
          processingRestoreRetryRequestedRef.current = true;
          if (processingMutationCountRef.current === 0) {
            scheduleProcessingQueueRestore();
          } else {
            scheduleRecoveryRetry("processing");
          }
          return;
        }
        const currentJobs = jobsRef.current;
        const currentJobsById = new Map(
          currentJobs.map((candidate) => [candidate.id, candidate]),
        );
        const projectionJobs = queue.jobs.map((candidate) =>
          preserveUploadRequestId(candidate, currentJobsById.get(candidate.id)),
        );
        const revalidatedLeaseJob = queue.revalidatedLeaseJob
          ? preserveUploadRequestId(
              queue.revalidatedLeaseJob,
              currentJobsById.get(queue.revalidatedLeaseJob.id),
            )
          : null;
        const settlementJobs = revalidatedLeaseJob
          ? [revalidatedLeaseJob, ...projectionJobs]
          : [...(queue.revalidatedArchiveJobs ?? []), ...projectionJobs];
        const incomingJobs =
          revalidatedLeaseJob?.archived_at === null &&
          processingMutationLeaseRef.current?.kind === "job" &&
          !processingMutationLeaseRef.current.expectsRemoval
            ? settlementJobs
            : projectionJobs;
        const processingLease = processingMutationLeaseRef.current;
        const authoritativeMutationJobIds = new Set(
          mutationLeaseJobIds(processingLease),
        );
        const mutationLeaseSettled = settlePersistedMutationLease(
          "processing",
          settlementJobs,
          true,
        );
        const currentActiveId = activeJobIdRef.current;
        const currentActiveJob =
          currentActiveId === null
            ? null
            : (currentJobs.find(
                (candidate) => candidate.id === currentActiveId,
              ) ?? null);
        let nextJobs = reconcileProcessingJobs(
          currentJobs,
          incomingJobs,
          cachedIds,
          processingRemovalCandidateIdsRef.current,
        );
        const nextJobsById = new Map(
          nextJobs.map((candidate) => [candidate.id, candidate]),
        );
        const recoveredAutomationIds = new Set(
          incomingJobs.flatMap((incomingJob) => {
            const currentJob = currentJobsById.get(incomingJob.id);
            const reconciledJob = nextJobsById.get(incomingJob.id);
            const reachedPersistedProjectionTarget =
              processingLease?.kind === "projection"
                ? projectionMutationLeaseTargetReached(
                    processingLease,
                    incomingJob,
                  )
                : null;
            const reachedCurrentAutomationTarget =
              incomingJob.approved_state !== null &&
              (!automationRecommend || incomingJob.recommendation !== null);
            const reachedAutomationTarget =
              incomingJob.error === null &&
              (reachedPersistedProjectionTarget ??
                reachedCurrentAutomationTarget);
            return currentJob &&
              reconciledJob !== currentJob &&
              reachedAutomationTarget
              ? [incomingJob.id]
              : [];
          }),
        );
        clearJobAttentionEntries(recoveredAutomationIds);
        const preservedMissingDirtyJob =
          formDirtyRef.current &&
          currentActiveJob !== null &&
          !processingRemovalCandidateIdsRef.current.has(currentActiveJob.id) &&
          !nextJobs.some((candidate) => candidate.id === currentActiveJob.id);
        if (preservedMissingDirtyJob) {
          nextJobs = [currentActiveJob, ...nextJobs];
        }
        const reconciledActiveJob =
          currentActiveId === null
            ? null
            : (nextJobs.find((candidate) => candidate.id === currentActiveId) ??
              null);
        const activeJobUpdatedAuthoritatively =
          currentActiveJob !== null &&
          reconciledActiveJob !== null &&
          (processingUpdateCandidateIdsRef.current.has(currentActiveJob.id) ||
            (mutationLeaseSettled &&
              authoritativeMutationJobIds.has(currentActiveJob.id))) &&
          reconciledActiveJob.updated_at !== currentActiveJob.updated_at;
        const preserveDirtyForm =
          formDirtyRef.current &&
          reconciledActiveJob !== null &&
          !activeJobUpdatedAuthoritatively;
        const currentRoute = routeRef.current;
        const pendingRouteJob =
          currentActiveId !== null &&
          currentActiveJob === null &&
          reconciledActiveJob === null &&
          currentRoute.surface === "job" &&
          currentRoute.jobId === currentActiveId;
        for (const removalCandidateId of processingRemovalCandidateIdsRef.current) {
          if (
            !mutationLeaseTargetsJob(
              processingMutationLeaseRef.current,
              removalCandidateId,
            )
          ) {
            processingRemovalCandidateIdsRef.current.delete(removalCandidateId);
          }
        }
        for (const updateCandidateId of processingUpdateCandidateIdsRef.current) {
          if (
            !mutationLeaseTargetsJob(
              processingMutationLeaseRef.current,
              updateCandidateId,
            )
          ) {
            processingUpdateCandidateIdsRef.current.delete(updateCandidateId);
          }
        }
        jobsRef.current = nextJobs;
        setJobs(nextJobs);
        if (!preserveDirtyForm && !pendingRouteJob) {
          const nextActiveJob = reconciledActiveJob ?? nextJobs[0] ?? null;
          alignWorkspaceToJob(nextActiveJob);
          if (
            currentActiveJob !== null &&
            currentActiveId !== null &&
            !nextJobs.some((candidate) => candidate.id === currentActiveId)
          ) {
            replaceRemovedJobRoute(currentActiveId, nextActiveJob);
          }
        }
        const processingInProgress = nextJobs.some(isProcessingJobInProgress);
        const authoritativeJobIds = new Set(
          incomingJobs.map((candidate) => candidate.id),
        );
        if (
          writeProcessingQueue(nextJobs, false, authoritativeJobIds) &&
          !preservedMissingDirtyJob &&
          !processingInProgress &&
          processingMutationLeaseRef.current === null
        ) {
          markProcessingQueueSessionSynced();
        } else {
          markProcessingQueueSessionUnsynced();
        }
        if (processingStorageRestoreScheduledRef.current) {
          scheduleRecoveryRetry("processing");
        } else {
          finishRecovery("processing");
        }
      })
      .catch((processingError) => {
        if (active) {
          setError(
            messageFromError(
              processingError,
              "Could not restore processing queue",
            ),
          );
          markProcessingQueueSessionUnsynced();
          restoreRetryTimer = window.setTimeout(() => {
            restoreRetryTimer = null;
            if (processingMutationCountRef.current === 0) {
              scheduleProcessingQueueRestore();
            } else {
              processingRestoreRetryRequestedRef.current = true;
            }
          }, PROCESSING_QUEUE_REVALIDATION_INTERVAL_MS);
          scheduleRecoveryRetry("processing");
        }
      });

    return () => {
      active = false;
      if (restoreRetryTimer !== null) {
        window.clearTimeout(restoreRetryTimer);
      }
    };
  }, [processingRestoreRequest]);

  function navigateToJobOrWorkspace(
    nextJob: JobRecord | null,
    navigationMode: Exclude<JobNavigationMode, false>,
  ) {
    if (!nextJob || isLocalUploadError(nextJob)) {
      navigation.openWorkspace({ replace: true });
      return;
    }
    navigation.openJob(nextJob.id, {
      replace: navigationMode === "replace",
    });
  }

  function replaceRemovedJobRoute(
    removedJobId: string,
    fallbackJob: JobRecord | null,
  ) {
    const currentRoute = routeRef.current;
    if (currentRoute.surface === "job" && currentRoute.jobId === removedJobId) {
      navigateToJobOrWorkspace(fallbackJob, "replace");
    }
  }

  function activateJob(
    nextJob: JobRecord,
    navigationMode: JobNavigationMode = "push",
  ) {
    alignWorkspaceToJob(nextJob);
    setLivePreviewVisible(false);
    setError(null);
    if (navigationMode) {
      navigateToJobOrWorkspace(nextJob, navigationMode);
    }
  }

  function updateJobs(updater: (current: JobRecord[]) => JobRecord[]) {
    const nextJobs = updater(jobsRef.current);
    jobsRef.current = nextJobs;
    setJobs(nextJobs);
  }

  function clearJobAttentionEntries(jobIds: ReadonlySet<string>) {
    if (jobIds.size === 0) {
      return;
    }
    clearWorkflowJobAttention([...jobIds]);
  }

  function clearJobAttention(jobId: string) {
    clearJobAttentionEntries(new Set([jobId]));
  }

  function replaceJob(updatedJob: JobRecord) {
    const currentJob = jobsRef.current.find(
      (candidate) => candidate.id === updatedJob.id,
    );
    const normalizedJob = preserveUploadRequestId(updatedJob, currentJob);
    updateJobs((current) =>
      current.map((candidate) =>
        candidate.id === normalizedJob.id ? normalizedJob : candidate,
      ),
    );
    clearJobAttention(updatedJob.id);
    updateHistoryJob(normalizedJob);
    activeJobIdRef.current = updatedJob.id;
    setActiveJobId(updatedJob.id);
  }

  function upsertAndActivateJob(
    nextJob: JobRecord,
    navigationMode: JobNavigationMode = "push",
  ) {
    updateJobs((current) => {
      const existing = current.some((candidate) => candidate.id === nextJob.id);
      return existing
        ? current.map((candidate) =>
            candidate.id === nextJob.id ? nextJob : candidate,
          )
        : [nextJob, ...current];
    });
    updateHistoryJob(nextJob, false);
    activateJob(nextJob, navigationMode);
  }

  function updateHistoryJob(updatedJob: JobRecord, revalidateSearch = true) {
    setHistory((current) => {
      if (!current.some((item) => item.id === updatedJob.id)) {
        return current;
      }
      const next = current.map((item) =>
        item.id === updatedJob.id ? { ...item, job: updatedJob } : item,
      );
      writeHistory(next);
      return next;
    });
    setHistorySearchResults(
      (current) =>
        current?.map((item) =>
          item.id === updatedJob.id ? { ...item, job: updatedJob } : item,
        ) ?? null,
    );
    if (
      revalidateSearch &&
      updatedJob.archived_at &&
      historySearchActive &&
      historySearchQuery
    ) {
      void revalidateHistorySearch(historySearchQuery);
    }
  }

  function applyHistoryJobUpdates(incomingJobs: JobRecord[]) {
    const settlingArchiveLease =
      historyMutationLeaseRef.current?.kind === "archive";
    const authoritativeMutationJobIds = new Set(
      mutationLeaseJobIds(historyMutationLeaseRef.current),
    );
    const mutationLeaseSettled = settlePersistedMutationLease(
      "history",
      incomingJobs,
      false,
    );
    const incomingJobsById = new Map(
      incomingJobs.map((incomingJob) => [incomingJob.id, incomingJob]),
    );
    const reconciledHistoryJob = (
      currentJob: JobRecord,
      incomingJob: JobRecord,
    ) =>
      mutationLeaseSettled && authoritativeMutationJobIds.has(incomingJob.id)
        ? incomingJob
        : newerHistoryJob(currentJob, incomingJob);
    const resolvedJobIds = new Set(incomingJobsById.keys());
    const currentActiveId = activeJobIdRef.current;
    const currentActiveJob =
      currentActiveId === null
        ? null
        : (jobsRef.current.find(
            (candidate) => candidate.id === currentActiveId,
          ) ?? null);
    const nextJobs = jobsRef.current.map((candidate) => {
      const incomingJob = incomingJobsById.get(candidate.id);
      return incomingJob
        ? reconciledHistoryJob(candidate, incomingJob)
        : candidate;
    });
    const reconciledActiveJob =
      currentActiveId === null
        ? null
        : (nextJobs.find((candidate) => candidate.id === currentActiveId) ??
          null);
    const activeJobUpdated =
      currentActiveJob !== null &&
      reconciledActiveJob !== null &&
      reconciledActiveJob !== currentActiveJob;
    if (
      nextJobs.some((candidate, index) => candidate !== jobsRef.current[index])
    ) {
      updateJobs(() => nextJobs);
    }
    if (
      activeJobUpdated &&
      (!formDirtyRef.current ||
        (currentActiveId !== null &&
          (historyUpdateCandidateIdsRef.current.has(currentActiveId) ||
            (mutationLeaseSettled &&
              authoritativeMutationJobIds.has(currentActiveId)))))
    ) {
      alignWorkspaceToJob(reconciledActiveJob);
    }

    setHistory((current) => {
      const next = current.map((item) => {
        const incomingJob = incomingJobsById.get(item.id);
        return incomingJob
          ? { ...item, job: reconciledHistoryJob(item.job, incomingJob) }
          : item;
      });
      const historyCached = writeHistory(next);
      const cachedHistory = historyCached ? readHistory() : null;
      const pendingSearchResult = (historySearchResults ?? []).some((item) => {
        const incomingJob = incomingJobsById.get(item.id);
        return (
          incomingJob ? reconciledHistoryJob(item.job, incomingJob) : item.job
        ).recommendation_pending;
      });
      const pendingWorkspaceJob = nextJobs.some(
        (candidate) =>
          candidate.archived_at && candidate.recommendation_pending,
      );
      if (
        historyCached &&
        readCachedHistoryTotal(cachedHistory) !== null &&
        !historyFullRestoreRequestedRef.current &&
        !hasPendingHistoryJobRestore(resolvedJobIds) &&
        !next.some((item) => item.job.recommendation_pending) &&
        !pendingSearchResult &&
        !pendingWorkspaceJob &&
        historyMutationLeaseRef.current === null
      ) {
        markHistorySessionSynced();
      } else {
        markHistorySessionUnsynced();
      }
      return next;
    });
    setHistorySearchResults(
      (current) =>
        current?.map((item) => {
          const incomingJob = incomingJobsById.get(item.id);
          return incomingJob
            ? { ...item, job: reconciledHistoryJob(item.job, incomingJob) }
            : item;
        }) ?? null,
    );
    for (const incomingJob of incomingJobs) {
      if (
        !mutationLeaseTargetsJob(
          historyMutationLeaseRef.current,
          incomingJob.id,
        )
      ) {
        historyUpdateCandidateIdsRef.current.delete(incomingJob.id);
      }
      historyJobRestoreIdsRef.current.delete(incomingJob.id);
    }
    if (mutationLeaseSettled && settlingArchiveLease) {
      void requestHistoryRestore(null, true);
    }
  }

  function applyHistoryPage(page: JobHistory, append = false) {
    const pageItems = historyItemsFromPage(page);
    const authoritativeMutationJobIds = new Set(
      mutationLeaseJobIds(historyMutationLeaseRef.current),
    );
    const mutationLeaseSettled = settlePersistedMutationLease(
      "history",
      pageItems.map((item) => item.job),
      false,
    );
    const resolvedJobIds = new Set(pageItems.map((item) => item.id));
    const incomingJobsById = new Map(
      pageItems.map((item) => [item.id, item.job]),
    );
    const currentActiveId = activeJobIdRef.current;
    const currentActiveJob =
      currentActiveId === null
        ? null
        : (jobsRef.current.find(
            (candidate) => candidate.id === currentActiveId,
          ) ?? null);
    const nextJobs = jobsRef.current.map((candidate) => {
      const incomingJob = incomingJobsById.get(candidate.id);
      return incomingJob
        ? mutationLeaseSettled &&
          authoritativeMutationJobIds.has(incomingJob.id)
          ? incomingJob
          : newerHistoryJob(candidate, incomingJob)
        : candidate;
    });
    const reconciledActiveJob =
      currentActiveId === null
        ? null
        : (nextJobs.find((candidate) => candidate.id === currentActiveId) ??
          null);
    const activeJobUpdated =
      currentActiveJob !== null &&
      reconciledActiveJob !== null &&
      reconciledActiveJob !== currentActiveJob;
    if (
      nextJobs.some((candidate, index) => candidate !== jobsRef.current[index])
    ) {
      updateJobs(() => nextJobs);
    }
    if (
      activeJobUpdated &&
      (!formDirtyRef.current ||
        (currentActiveId !== null &&
          (historyUpdateCandidateIdsRef.current.has(currentActiveId) ||
            (mutationLeaseSettled &&
              authoritativeMutationJobIds.has(currentActiveId)))))
    ) {
      alignWorkspaceToJob(reconciledActiveJob);
    }
    for (const item of pageItems) {
      if (!mutationLeaseTargetsJob(historyMutationLeaseRef.current, item.id)) {
        historyUpdateCandidateIdsRef.current.delete(item.id);
      }
      historyJobRestoreIdsRef.current.delete(item.id);
    }
    setHistoryTotal(page.total);
    setHistory((current) => {
      let items = append
        ? mergeHistoryItems(current, pageItems)
        : reconcileHistoryItems(current, pageItems);
      if (mutationLeaseSettled && authoritativeMutationJobIds.size > 0) {
        const authoritativeItems = new Map(
          pageItems
            .filter((item) => authoritativeMutationJobIds.has(item.id))
            .map((item) => [item.id, item]),
        );
        items = items.map((item) => authoritativeItems.get(item.id) ?? item);
      }
      const historyCached = writeHistory(items);
      const totalCached = writeHistoryTotal(page.total);
      if (
        historyCached &&
        totalCached &&
        !hasPendingHistoryJobRestore(resolvedJobIds) &&
        !items.some((item) => item.job.recommendation_pending) &&
        historyMutationLeaseRef.current === null
      ) {
        markHistorySessionSynced();
      } else {
        markHistorySessionUnsynced();
      }
      return items;
    });
  }

  function applyHistorySearchPage(page: JobHistory, append = false) {
    const pageItems = historyItemsFromPage(page);
    setHistorySearchTotal(page.total);
    setHistorySearchSnapshotVersion(page.snapshot_version ?? null);
    setHistorySearchResults((current) => {
      if (!append || current === null) {
        return reconcileHistoryItems(current ?? [], pageItems);
      }
      return mergeHistoryItems(current, pageItems);
    });
  }

  function clearHistorySearch() {
    historySearchRequestRef.current += 1;
    setHistorySearchOpen(false);
    setHistorySearchInput("");
    setHistorySearchQuery("");
    setHistorySearchResults(null);
    setHistorySearchTotal(0);
    setHistorySearchSnapshotVersion(null);
  }

  async function onSearchHistory() {
    const query = historySearchInput.trim();
    if (!query) {
      clearHistorySearch();
      return;
    }

    const requestId = ++historySearchRequestRef.current;
    setHistoryLoading(true);
    setError(null);
    try {
      const page = await fetchHistoryPageQuery(queryClient, 0, query);
      if (requestId !== historySearchRequestRef.current) {
        return;
      }
      setHistorySearchQuery(query);
      applyHistorySearchPage(page);
    } catch (historyError) {
      if (requestId === historySearchRequestRef.current) {
        setError(
          messageFromError(historyError, "Could not search saved history"),
        );
      }
    } finally {
      setHistoryLoading(false);
    }
  }

  async function revalidateHistorySearch(query: string) {
    const requestId = ++historySearchRequestRef.current;
    const loadedCount = Math.max(
      historySearchResults?.length ?? 0,
      HISTORY_CACHE_LIMIT,
    );
    try {
      const page = await getHistorySearchExtent(
        queryClient,
        query,
        loadedCount,
      );
      if (requestId === historySearchRequestRef.current) {
        applyHistorySearchPage(page);
      }
    } catch (historyError) {
      if (requestId === historySearchRequestRef.current) {
        setError(
          messageFromError(historyError, "Could not refresh history search"),
        );
      }
    }
  }

  async function refreshVisibleHistory() {
    if (!historySearchActive) {
      await syncHistory();
      return;
    }

    setHistoryLoading(true);
    setError(null);
    try {
      await revalidateHistorySearch(historySearchQuery);
    } finally {
      setHistoryLoading(false);
    }
  }

  async function loadOlderHistory() {
    if (historyLoading || visibleHistory.length >= visibleHistoryTotal) {
      return;
    }

    setHistoryLoading(true);
    setError(null);
    try {
      if (historySearchActive) {
        const requestId = ++historySearchRequestRef.current;
        const page = await fetchHistoryPageQuery(
          queryClient,
          visibleHistory.length,
          historySearchQuery,
        );
        if (requestId !== historySearchRequestRef.current) {
          return;
        }
        if (
          historySearchSnapshotVersion !== null &&
          page.snapshot_version === historySearchSnapshotVersion
        ) {
          applyHistorySearchPage(page, true);
          return;
        }
        if (page.total === 0) {
          applyHistorySearchPage(page);
          return;
        }
        const rebuiltPage = await getHistorySearchExtent(
          queryClient,
          historySearchQuery,
          Math.min(visibleHistory.length + HISTORY_CACHE_LIMIT, page.total),
        );
        if (requestId !== historySearchRequestRef.current) {
          return;
        }
        applyHistorySearchPage(rebuiltPage);
        return;
      }
      const page = await fetchHistoryPageQuery(queryClient, history.length);
      if (page.total !== historyTotal) {
        applyHistoryPage(await fetchHistoryPageQuery(queryClient));
        return;
      }
      applyHistoryPage(page, true);
    } catch (historyError) {
      setError(messageFromError(historyError, "Could not load older history"));
    } finally {
      setHistoryLoading(false);
    }
  }

  async function syncHistory(
    jobIds: string[] | null = null,
    reportErrors = true,
  ): Promise<boolean> {
    const restoreGeneration = historyMutationGenerationRef.current;
    setHistoryLoading(true);
    try {
      const page = jobIds
        ? (await archiveJobsCommand(queryClient, jobIds)).history
        : await fetchHistoryPageQuery(queryClient);
      if (
        historyMutationGenerationRef.current !== restoreGeneration ||
        historyMutationCountRef.current > 0
      ) {
        markHistorySessionUnsynced();
        if (jobIds === null) {
          historyFullRestoreRequestedRef.current = true;
        }
        historyRestoreRetryRequestedRef.current = true;
        if (
          historyMutationCountRef.current === 0 &&
          historyRestorePromiseRef.current === null
        ) {
          historyRestoreRetryRequestedRef.current = false;
          requestDeferredHistoryRestore();
        }
        return false;
      }
      applyHistoryPage(page);
      if (jobIds !== null) {
        clearOwnedMutationLease("processing");
        clearOwnedMutationLease("history");
      }
      return true;
    } catch (historyError) {
      if (jobIds !== null) {
        if (mutationFailureMayHavePersistedSideEffect(historyError)) {
          scheduleMutationLeaseRevalidation();
        } else {
          clearOwnedMutationLease("processing");
          clearOwnedMutationLease("history");
        }
      }
      if (reportErrors) {
        setError(
          messageFromError(historyError, "Could not load saved history"),
        );
      }
      return false;
    } finally {
      setHistoryLoading(false);
    }
  }

  function appendJob(created: JobRecord) {
    updateJobs((current) => [...current, created]);
    activateJob(created, "replace");
  }

  function applyApprovedJob(
    approved: JobRecord,
    fallbackState: CanonicalState,
  ) {
    const approvedState = approved.approved_state ?? {
      ...fallbackState,
      user_approved: true,
    };
    const approvedForm = stateToForm(approvedState);
    const previousJob = jobsRef.current.find(
      (candidate) => candidate.id === approved.id,
    );
    const benchmarkStateChanged =
      !previousJob?.benchmark_included ||
      !previousJob.approved_state ||
      benchmarkApprovalKey(previousJob.approved_state) !==
        benchmarkApprovalKey(approvedState);
    replaceJob(approved);
    formBaselineRef.current = approvedForm;
    formDirtyRef.current = false;
    setForm(approvedForm);
    setApprovedStateKey(approvalKey(approvedState));
    if (approved.benchmark_included) {
      setBenchmarkOverview((current) =>
        current
          ? {
              ...current,
              corpus_fingerprint: benchmarkStateChanged
                ? benchmarkCorpusFingerprintAfterLayoutMutation(
                    current.corpus_fingerprint,
                    approved.parser_layout_profile ??
                      current.default_layout_profile,
                    benchmarkTargetLayoutProfile,
                  )
                : current.corpus_fingerprint,
            }
          : current,
      );
    }
  }

  function preserveNewerScreenshotMetadata(incoming: JobRecord): JobRecord {
    const current = jobsRef.current.find(
      (candidate) => candidate.id === incoming.id,
    );
    const currentUpdatedAt = current
      ? Date.parse(current.updated_at)
      : Number.NaN;
    const incomingUpdatedAt = Date.parse(incoming.updated_at);
    return current &&
      Number.isFinite(currentUpdatedAt) &&
      (!Number.isFinite(incomingUpdatedAt) ||
        currentUpdatedAt > incomingUpdatedAt)
      ? {
          ...incoming,
          title: current.title ?? null,
          notes: current.notes ?? null,
          tags: screenshotTags(current),
          updated_at: current.updated_at,
        }
      : incoming;
  }

  function applyRecommendedJob(recommended: JobRecord) {
    const reconciled = preserveNewerScreenshotMetadata(recommended);
    replaceJob(reconciled);
    if (reconciled.approved_state) {
      setApprovedStateKey(approvalKey(reconciled.approved_state));
    }
  }

  async function runConfiguredAutomation(
    created: JobRecord,
    recommendationRequestId: string | null,
    signal?: AbortSignal,
  ): Promise<JobRecord> {
    if (!automationApprove) {
      return created;
    }
    if (signal?.aborted) {
      throw new DOMException("Aborted", "AbortError");
    }

    const approvalState = autoApprovalState(created, automationAllowWarnings);
    markPersistedJobSessionUnsynced(created);
    const approved = preserveUploadRequestId(
      (
        await approveStateCommand(queryClient, {
          jobId: created.id,
          state: approvalState,
          signal,
        })
      ).job,
      created,
    );
    applyApprovedJob(approved, approvalState);

    if (!automationRecommend) {
      return approved;
    }

    const recommendationController = new AbortController();
    const abortRecommendation = () => recommendationController.abort();
    if (signal?.aborted) {
      abortRecommendation();
    } else {
      signal?.addEventListener("abort", abortRecommendation, { once: true });
    }
    activeRecommendationRequestsRef.current.set(approved.id, {
      mutationScope: persistedJobMutationScope(approved),
      controller: recommendationController,
      ownsMutationLease: false,
    });
    markPersistedJobSessionUnsynced(approved);
    try {
      const recommended = preserveUploadRequestId(
        (
          await requestRecommendationCommand(queryClient, {
            jobId: approved.id,
            requestId: recommendationRequestId ?? createMutationRequestId(),
            signal: recommendationController.signal,
          })
        ).job,
        approved,
      );
      if (jobsRef.current.some((candidate) => candidate.id === approved.id)) {
        applyRecommendedJob(recommended);
      }
      return recommended;
    } finally {
      signal?.removeEventListener("abort", abortRecommendation);
      if (
        activeRecommendationRequestsRef.current.get(approved.id)?.controller ===
        recommendationController
      ) {
        activeRecommendationRequestsRef.current.delete(approved.id);
      }
    }
  }

  async function uploadSelectedFiles(
    runAutomation: boolean,
    expectedUploads: ProjectionMutationLease["expectedUploads"],
  ): Promise<JobRecord[]> {
    const selectedFiles = [...files];
    const controller = new AbortController();
    queueAbortControllerRef.current = controller;
    queueAbortRequestedRef.current = false;
    setQueueProgress({
      total: selectedFiles.length,
      completed: 0,
      failed: 0,
      skipped: 0,
      currentIndex: 0,
      currentFile: "",
      aborting: false,
    });

    const completedJobs: JobRecord[] = [];
    const attentionMessages: string[] = [];
    let completedCount = 0;
    let failedCount = 0;
    let skippedCount = 0;
    const discardUnstartedUploads = (startIndex: number) => {
      for (let index = startIndex; index < selectedFiles.length; index += 1) {
        updateExpectedUpload(index, "failed");
      }
    };

    for (const [index, selectedFile] of selectedFiles.entries()) {
      if (controller.signal.aborted) {
        skippedCount = selectedFiles.length - completedCount;
        discardUnstartedUploads(index);
        break;
      }
      setQueueProgress({
        total: selectedFiles.length,
        completed: completedCount,
        failed: failedCount,
        skipped: 0,
        currentIndex: index + 1,
        currentFile: selectedFile.name,
        aborting: false,
      });

      const expectedUploadIndex = index;
      const expectedUpload = expectedUploads[index];
      try {
        const { job: created } = await uploadScreenshotCommand(queryClient, {
          file: selectedFile,
          requestId: expectedUpload.requestId,
          signal: controller.signal,
          pipeline: pipelineSelection ?? undefined,
        });
        updateExpectedUpload(
          expectedUploadIndex,
          projectionMutationTarget(
            runAutomation,
            automationApprove,
            automationRecommend,
          ),
        );
        appendJob(created);
        let completed = created;
        let includeCompletedJob = true;
        if (runAutomation) {
          try {
            completed = await runConfiguredAutomation(
              created,
              expectedUpload.recommendationRequestId,
              controller.signal,
            );
          } catch (automationError) {
            const confirmedJob = jobsRef.current.find(
              (candidate) => candidate.id === created.id,
            );
            if (isAbortError(automationError) && controller.signal.aborted) {
              if (confirmedJob) {
                completedJobs.push(confirmedJob);
              }
              completedCount += 1;
              skippedCount = selectedFiles.length - completedCount;
              discardUnstartedUploads(index + 1);
              break;
            }
            if (!confirmedJob) {
              updateExpectedUpload(expectedUploadIndex, "failed");
              includeCompletedJob = false;
            } else if (
              !mutationFailureMayHavePersistedSideEffect(automationError)
            ) {
              updateExpectedUpload(
                expectedUploadIndex,
                confirmedJob.recommendation !== null
                  ? "recommended"
                  : confirmedJob.approved_state !== null
                    ? "approved"
                    : "parsed",
              );
            }
            if (confirmedJob) {
              const message = messageFromError(
                automationError,
                "Automation stopped for this screenshot",
              );
              markJobAttention(created.id, message);
              completed = confirmedJob;
              attentionMessages.push(`${selectedFile.name}: ${message}`);
              failedCount += 1;
            }
          }
        }
        if (includeCompletedJob) {
          completedJobs.push(completed);
        }
        completedCount += 1;
      } catch (uploadError) {
        if (isAbortError(uploadError)) {
          skippedCount = selectedFiles.length - completedCount;
          discardUnstartedUploads(index + 1);
          break;
        }
        if (
          uploadError instanceof ApiResponseError &&
          !mutationFailureMayHavePersistedSideEffect(uploadError)
        ) {
          updateExpectedUpload(expectedUploadIndex, "failed");
        }
        const message = messageFromError(uploadError, "Upload failed");
        const errorJob = createLocalErrorJob(
          selectedFile,
          message,
          index,
          expectedUpload.requestId,
        );
        appendJob(errorJob);
        completedJobs.push(errorJob);
        attentionMessages.push(`${selectedFile.name}: ${message}`);
        completedCount += 1;
        failedCount += 1;
      }
      setQueueProgress({
        total: selectedFiles.length,
        completed: completedCount,
        failed: failedCount,
        skipped: skippedCount,
        currentIndex: Math.min(index + 1, selectedFiles.length),
        currentFile: selectedFile.name,
        aborting: controller.signal.aborted,
      });
    }
    if (completedJobs.length > 1) {
      activateJob(completedJobs[0], "replace");
    }
    if (controller.signal.aborted || queueAbortRequestedRef.current) {
      setError(
        `Import aborted. ${skippedCount} unprocessed screenshot${skippedCount === 1 ? "" : "s"} discarded.`,
      );
    } else if (attentionMessages.length > 0) {
      setError(
        `${attentionMessages.length} screenshot${attentionMessages.length === 1 ? "" : "s"} need attention. Check the highlighted queue items.`,
      );
    }
    setFiles([]);
    setQueueProgress(null);
    queueAbortControllerRef.current = null;
    queueAbortRequestedRef.current = false;
    return completedJobs;
  }

  async function onUpload() {
    if (files.length === 0 || mutationRecoveryPending(["processing"])) {
      return;
    }
    setBusy(true);
    setError(null);
    beginProcessingMembershipMutation();
    const uploadTarget = projectionMutationTarget(
      automationEnabled,
      automationApprove,
      automationRecommend,
    );
    const expectedUploads = files.map(() => ({
      requestId: createMutationRequestId(),
      target: uploadTarget,
      recommendationRequestId:
        uploadTarget === "recommended" ? createMutationRequestId() : null,
    }));
    installMutationLease(
      "processing",
      startProjectionMutationLease(
        "processing",
        mutationOwnerId,
        processingJobsForCache(jobsRef.current),
        expectedUploads,
      ),
    );
    try {
      const completedJobs = await uploadSelectedFiles(
        automationEnabled,
        expectedUploads,
      );
      settlePersistedMutationLease("processing", completedJobs, false);
      if (processingMutationLeaseRef.current !== null) {
        scheduleMutationLeaseRevalidation();
      }
    } catch (uploadError) {
      scheduleMutationLeaseRevalidation();
      setError(messageFromError(uploadError, "Upload failed"));
    } finally {
      endProcessingMembershipMutation();
      setBusy(false);
    }
  }

  async function captureAndParseScreen(
    file: File,
    uploadRequestId: string,
  ): Promise<JobRecord> {
    const { job: created } = await uploadScreenshotCommand(queryClient, {
      file,
      requestId: uploadRequestId,
      pipeline: pipelineSelection ?? undefined,
    });
    appendJob(created);
    return created;
  }

  async function onCaptureScreen() {
    if (mutationRecoveryPending(["processing"])) {
      return;
    }
    setBusy(true);
    setError(null);
    beginProcessingMembershipMutation();
    let expectedUploadIndex: number | null = null;
    let capturedJobId: string | null = null;
    try {
      const captureFile = await captureSharedScreenFile();
      installMutationLease(
        "processing",
        startProjectionMutationLease(
          "processing",
          mutationOwnerId,
          processingJobsForCache(jobsRef.current),
        ),
      );
      const uploadTarget = projectionMutationTarget(
        automationEnabled,
        automationApprove,
        automationRecommend,
      );
      const uploadRequestId = createMutationRequestId();
      const recommendationRequestId =
        uploadTarget === "recommended" ? createMutationRequestId() : null;
      expectedUploadIndex = trackExpectedUpload(
        uploadRequestId,
        uploadTarget,
        recommendationRequestId,
      );
      const created = await captureAndParseScreen(captureFile, uploadRequestId);
      capturedJobId = created.id;
      updateExpectedUpload(expectedUploadIndex, uploadTarget);
      let completed = created;
      if (automationEnabled) {
        completed = await runConfiguredAutomation(
          created,
          recommendationRequestId,
        );
      }
      settlePersistedMutationLease("processing", [completed], false);
      if (processingMutationLeaseRef.current !== null) {
        scheduleMutationLeaseRevalidation();
      }
    } catch (captureError) {
      const confirmedJob =
        capturedJobId === null
          ? null
          : (jobsRef.current.find(
              (candidate) => candidate.id === capturedJobId,
            ) ?? null);
      const deletedDuringAutomation =
        capturedJobId !== null && confirmedJob === null;
      if (deletedDuringAutomation) {
        updateExpectedUpload(expectedUploadIndex, "failed");
        settlePersistedMutationLease("processing", jobsRef.current, false);
      } else if (
        !isAbortError(captureError) &&
        !mutationFailureMayHavePersistedSideEffect(captureError)
      ) {
        updateExpectedUpload(
          expectedUploadIndex,
          confirmedJob === null
            ? "failed"
            : confirmedJob.recommendation !== null
              ? "recommended"
              : confirmedJob.approved_state !== null
                ? "approved"
                : "parsed",
        );
      }
      if (processingMutationLeaseRef.current !== null) {
        scheduleMutationLeaseRevalidation();
      }
      if (!deletedDuringAutomation) {
        setError(messageFromError(captureError, "Screen capture failed"));
      }
    } finally {
      endProcessingMembershipMutation();
      setBusy(false);
    }
  }

  async function onApprove() {
    if (!job) {
      return;
    }
    if (!validation.state) {
      setError(
        validation.error ?? "Correct the detected state before approval",
      );
      return;
    }

    const changesProcessingMembership =
      job.benchmark_included &&
      job.parser_result === null &&
      !isPristineBenchmarkImport(job);
    if (mutationRecoveryPending([persistedJobMutationScope(job)])) {
      return;
    }
    const mutationScope = beginPersistedJobMutation(
      job,
      {
        kind: "approval",
        approvedStateKey: approvalKey(validation.state),
      },
      changesProcessingMembership ? [job.id] : [],
    );
    let restoreAfterMutation = changesProcessingMembership;
    setBusy(true);
    setError(null);
    try {
      const { job: approved } = await approveStateCommand(queryClient, {
        jobId: job.id,
        state: validation.state,
      });
      applyApprovedJob(approved, validation.state);
    } catch (approveError) {
      if (mutationFailureMayHavePersistedSideEffect(approveError)) {
        markPersistedJobMutationUncertain(mutationScope, job.id);
      }
      restoreAfterMutation = true;
      setError(messageFromError(approveError, "Approval failed"));
    } finally {
      endPersistedJobMutation(mutationScope, restoreAfterMutation);
      setBusy(false);
    }
  }

  async function onRecommend() {
    if (!job || !canRecommend) {
      return;
    }
    if (mutationRecoveryPending([persistedJobMutationScope(job)])) {
      return;
    }
    const changesProcessingMembership = isPristineBenchmarkImport(job);
    const recommendationRequestId = createMutationRequestId();
    let decisionExpectation: JobMutationExpectation | null = null;
    if (trainingAction) {
      const parsedSizing = parseTrainingSizing(trainingAction, trainingSizing);
      if (parsedSizing.error) {
        setError(parsedSizing.error);
        return;
      }
      const decisionChanged =
        !job.training_decision ||
        job.training_decision.action !== trainingAction ||
        job.training_decision.sizing !== parsedSizing.sizing ||
        (job.training_decision.certainty ?? null) !==
          (trainingCertainty || null);
      if (decisionChanged) {
        decisionExpectation = {
          kind: "training-decision",
          action: trainingAction,
          sizing: parsedSizing.sizing,
          certainty: trainingCertainty || null,
        };
      }
    }
    const mutationScope = beginPersistedJobMutation(job, decisionExpectation);
    const recommendationController = new AbortController();
    activeRecommendationRequestsRef.current.set(job.id, {
      mutationScope,
      controller: recommendationController,
      ownsMutationLease: true,
    });
    let recommendationStarted = false;
    let restoreAfterMutation = changesProcessingMembership;
    setBusy(true);
    setError(null);
    try {
      if (decisionExpectation?.kind === "training-decision") {
        const { job: decided } = await recordTrainingDecisionCommand(
          queryClient,
          {
            jobId: job.id,
            action: decisionExpectation.action,
            sizing: decisionExpectation.sizing,
            certainty: decisionExpectation.certainty,
          },
        );
        if (
          recommendationController.signal.aborted ||
          !jobsRef.current.some((candidate) => candidate.id === job.id)
        ) {
          return;
        }
        replaceJob(preserveNewerScreenshotMetadata(decided));
      }
      if (
        !armPersistedRecommendationLease(
          mutationScope,
          job.id,
          recommendationRequestId,
        )
      ) {
        return;
      }
      recommendationStarted = true;
      const { job: recommended } = await requestRecommendationCommand(
        queryClient,
        {
          jobId: job.id,
          requestId: recommendationRequestId,
          signal: recommendationController.signal,
        },
      );
      if (jobsRef.current.some((candidate) => candidate.id === job.id)) {
        applyRecommendedJob(recommended);
      }
    } catch (recommendError) {
      const jobStillPresent = jobsRef.current.some(
        (candidate) => candidate.id === job.id,
      );
      if (jobStillPresent) {
        if (
          recommendationStarted
            ? recommendationAttemptMayHavePersistedSideEffect(recommendError)
            : mutationFailureMayHavePersistedSideEffect(recommendError)
        ) {
          markPersistedJobMutationUncertain(mutationScope, job.id);
        }
        restoreAfterMutation = restoreAfterMutation || recommendationStarted;
        setError(messageFromError(recommendError, "Recommendation failed"));
      }
    } finally {
      if (
        activeRecommendationRequestsRef.current.get(job.id)?.controller ===
        recommendationController
      ) {
        activeRecommendationRequestsRef.current.delete(job.id);
      }
      endPersistedJobMutation(mutationScope, restoreAfterMutation);
      setBusy(false);
    }
  }

  async function onSaveTrainingDecision() {
    if (
      !job ||
      !currentStateApproved ||
      activeRecommendation ||
      !trainingAction
    ) {
      return;
    }
    const parsedSizing = parseTrainingSizing(trainingAction, trainingSizing);
    if (parsedSizing.error) {
      setError(parsedSizing.error);
      return;
    }
    if (mutationRecoveryPending([persistedJobMutationScope(job)])) {
      return;
    }

    const changesProcessingMembership = isPristineBenchmarkImport(job);
    const mutationScope = beginPersistedJobMutation(job, {
      kind: "training-decision",
      action: trainingAction,
      sizing: parsedSizing.sizing,
      certainty: trainingCertainty || null,
    });
    let restoreAfterMutation = changesProcessingMembership;
    setBusy(true);
    setError(null);
    try {
      const { job: decided } = await recordTrainingDecisionCommand(
        queryClient,
        {
          jobId: job.id,
          action: trainingAction,
          sizing: parsedSizing.sizing,
          certainty: trainingCertainty || null,
        },
      );
      replaceJob(decided);
      toast.success("Training answer locked");
    } catch (decisionError) {
      if (mutationFailureMayHavePersistedSideEffect(decisionError)) {
        markPersistedJobMutationUncertain(mutationScope, job.id);
      }
      restoreAfterMutation = true;
      setError(
        messageFromError(decisionError, "Could not save your training answer"),
      );
    } finally {
      endPersistedJobMutation(mutationScope, restoreAfterMutation);
      setBusy(false);
    }
  }

  async function onCompleteTrainingReview() {
    if (
      !job ||
      !activeTrainingDecision ||
      !activeRecommendation ||
      decisionComparison?.tone === "match"
    ) {
      return;
    }
    if (mutationRecoveryPending([persistedJobMutationScope(job)])) {
      return;
    }

    const continueReviewQueue = trainingReviewQueueJobId === job.id;
    const reviewNote = trainingReviewNote.trim() || null;
    const mutationScope = beginPersistedJobMutation(job, {
      kind: "training-review",
      reviewed: true,
      note: reviewNote,
    });
    let restoreAfterMutation = false;
    setBusy(true);
    setError(null);
    try {
      const { job: reviewedJob } = await completeTrainingReviewCommand(
        queryClient,
        { jobId: job.id, note: reviewNote },
      );
      replaceJob(reviewedJob);
      if (!continueReviewQueue) {
        toast.success("Training review completed");
        return;
      }

      try {
        const progress = await fetchTrainingProgressQuery(queryClient, {
          lessonOrder: trainingLessonOrder,
          lessonQuery: trainingLessonQuery,
          lessonStreet: trainingLessonStreet,
          reviewCertainty: trainingReviewCertainty,
          reviewDifference: trainingReviewDifference,
          reviewOrder: trainingReviewOrder,
          reviewPositionFilter: trainingReviewPosition,
          reviewStreet: trainingReviewStreet,
        });
        setTrainingProgress(progress);
        const nextHand = progress.review_queue[0] ?? null;
        if (!nextHand) {
          setTrainingReviewQueueJobId(null);
          setTrainingProgressView("review");
          setTrainingDialogOpen(true);
          navigation.openTraining();
          toast.success("Review queue completed");
          return;
        }

        const nextJob = await fetchJobQuery(queryClient, nextHand.job_id);
        upsertAndActivateJob(nextJob, "replace");
        setTrainingReviewQueueJobId(nextJob.id);
        toast.success("Training review completed. Next hand ready");
      } catch (continueError) {
        setTrainingReviewQueueJobId(null);
        setError(
          messageFromError(
            continueError,
            "Review completed, but the next training hand could not be loaded",
          ),
        );
      }
    } catch (reviewError) {
      if (mutationFailureMayHavePersistedSideEffect(reviewError)) {
        markPersistedJobMutationUncertain(mutationScope, job.id);
      }
      restoreAfterMutation = true;
      setError(
        messageFromError(reviewError, "Could not complete training review"),
      );
    } finally {
      endPersistedJobMutation(mutationScope, restoreAfterMutation);
      setBusy(false);
    }
  }

  async function onReopenTrainingReview() {
    if (
      !job ||
      !activeTrainingDecision ||
      !activeRecommendation ||
      decisionComparison?.tone === "match" ||
      !job.training_reviewed_at
    ) {
      return;
    }
    if (mutationRecoveryPending([persistedJobMutationScope(job)])) {
      return;
    }

    const mutationScope = beginPersistedJobMutation(job, {
      kind: "training-review",
      reviewed: false,
      note: null,
    });
    let restoreAfterMutation = false;
    setBusy(true);
    setError(null);
    try {
      const { job: reopenedJob } = await reopenTrainingReviewCommand(
        queryClient,
        { jobId: job.id },
      );
      replaceJob(reopenedJob);
      toast.success("Training review reopened");
    } catch (reviewError) {
      if (mutationFailureMayHavePersistedSideEffect(reviewError)) {
        markPersistedJobMutationUncertain(mutationScope, job.id);
      }
      restoreAfterMutation = true;
      setError(
        messageFromError(reviewError, "Could not reopen training review"),
      );
    } finally {
      endPersistedJobMutation(mutationScope, restoreAfterMutation);
      setBusy(false);
    }
  }

  async function onUpdateTrainingReviewNote() {
    if (
      !job ||
      !activeTrainingDecision ||
      !activeRecommendation ||
      decisionComparison?.tone === "match" ||
      !job.training_reviewed_at
    ) {
      return;
    }
    if (mutationRecoveryPending([persistedJobMutationScope(job)])) {
      return;
    }

    const note = trainingReviewNote.trim() || null;
    const mutationScope = beginPersistedJobMutation(job, {
      kind: "training-review",
      reviewed: true,
      note,
    });
    let restoreAfterMutation = false;
    setBusy(true);
    setError(null);
    try {
      const { job: updatedJob } = await completeTrainingReviewCommand(
        queryClient,
        { jobId: job.id, note },
      );
      replaceJob(updatedJob);
      setTrainingReviewNoteEditing(false);
      toast.success(note ? "Lesson note updated" : "Lesson note removed");
    } catch (reviewError) {
      if (mutationFailureMayHavePersistedSideEffect(reviewError)) {
        markPersistedJobMutationUncertain(mutationScope, job.id);
      }
      restoreAfterMutation = true;
      setError(messageFromError(reviewError, "Could not update lesson note"));
    } finally {
      endPersistedJobMutation(mutationScope, restoreAfterMutation);
      setBusy(false);
    }
  }

  async function reopenTrainingReviewFromProgress(jobId: string) {
    let persistedJob =
      jobsRef.current.find((candidate) => candidate.id === jobId) ??
      history.find((item) => item.id === jobId)?.job ??
      historySearchResults?.find((item) => item.id === jobId)?.job ??
      null;
    let mutationScope: PersistedJobMutationScope | null = null;
    let reviewPersisted = false;
    let restoreAfterMutation = false;
    setTrainingReviewJobId(jobId);
    setError(null);
    try {
      persistedJob ??= await fetchJobQuery(queryClient, jobId);
      if (mutationRecoveryPending([persistedJobMutationScope(persistedJob)])) {
        return;
      }
      mutationScope = beginPersistedJobMutation(persistedJob, {
        kind: "training-review",
        reviewed: false,
        note: null,
      });
      const { job: reopenedJob } = await reopenTrainingReviewCommand(
        queryClient,
        { jobId },
      );
      reviewPersisted = true;
      updateJobs((current) =>
        current.map((candidate) =>
          candidate.id === reopenedJob.id ? reopenedJob : candidate,
        ),
      );
      updateHistoryJob(reopenedJob);
      setTrainingProgress(
        await fetchTrainingProgressQuery(queryClient, {
          certaintyFilter: trainingCertaintyFilter,
          lessonOrder: trainingLessonOrder,
          lessonQuery: trainingLessonQuery,
          lessonStreet: trainingLessonStreet,
          positionFilter: trainingPositionFilter,
          reviewCertainty: trainingReviewCertainty,
          reviewDifference: trainingReviewDifference,
          reviewOrder: trainingReviewOrder,
          reviewPositionFilter: trainingReviewPosition,
          reviewStreet: trainingReviewStreet,
          solverFilter: trainingSolverFilter,
          streetFilter: trainingStreetFilter,
        }),
      );
      toast.success("Training review reopened");
    } catch (reviewError) {
      if (mutationScope !== null) {
        if (
          !reviewPersisted &&
          mutationFailureMayHavePersistedSideEffect(reviewError)
        ) {
          markPersistedJobMutationUncertain(mutationScope, jobId);
        }
        restoreAfterMutation = !reviewPersisted;
      }
      setError(
        messageFromError(reviewError, "Could not reopen training review"),
      );
    } finally {
      if (mutationScope !== null) {
        endPersistedJobMutation(mutationScope, restoreAfterMutation);
      }
      setTrainingReviewJobId(null);
    }
  }

  async function onApplicationBackupRestore(backupFile: File) {
    if (busy || backupRestoring) {
      return;
    }

    setBackupRestoring(true);
    setBusy(true);
    setError(null);
    try {
      const { result } = await restoreApplicationBackupCommand(queryClient, {
        file: backupFile,
      });
      resetBenchmark();
      setTrainingProgress(null);
      clearHistorySearch();
      markProcessingQueueSessionUnsynced();
      scheduleProcessingQueueRestore();
      markHistorySessionUnsynced();
      void requestHistoryRestore(null, true);

      const restoredItems =
        result.imported_jobs + result.imported_benchmark_reports;
      const reusedItems = result.reused_jobs + result.reused_benchmark_reports;
      const restoredParts = [
        result.imported_jobs > 0
          ? `${result.imported_jobs} new ${result.imported_jobs === 1 ? "hand" : "hands"}`
          : null,
        result.imported_benchmark_reports > 0
          ? `${result.imported_benchmark_reports} benchmark ${result.imported_benchmark_reports === 1 ? "report" : "reports"}`
          : null,
      ].filter((part): part is string => part !== null);
      toast.success(
        restoredItems > 0
          ? `Backup restored: ${restoredParts.join(", ")}`
          : `Backup already present: ${reusedItems} ${reusedItems === 1 ? "record" : "records"} verified`,
      );
    } catch (backupError) {
      setError(
        messageFromError(backupError, "Could not restore application backup"),
      );
    } finally {
      setBackupRestoring(false);
      setBusy(false);
    }
  }

  async function applyBenchmarkDatasetImportResult(
    result: BenchmarkDatasetImportResult,
  ): Promise<number> {
    const importedIds = new Set(result.job_ids);
    const dirtyActiveJobId = formDirtyRef.current
      ? activeJobIdRef.current
      : null;
    for (const removalCandidateId of processingRemovalCandidateIdsRef.current) {
      if (!importedIds.has(removalCandidateId)) {
        processingRemovalCandidateIdsRef.current.delete(removalCandidateId);
      }
    }
    const importedLayoutCounts = result.included_cases_by_layout;
    const hasImportedLayoutCounts = Boolean(
      importedLayoutCounts &&
      (result.included_cases === 0 ||
        Object.keys(importedLayoutCounts).length > 0),
    );
    const shouldRefreshOverview =
      !hasImportedLayoutCounts ||
      Boolean(benchmarkOverview?.corpus_fingerprint);
    setBenchmarkOverview((current) => {
      return {
        included_cases: result.included_cases,
        included_cases_by_layout: hasImportedLayoutCounts
          ? (importedLayoutCounts ?? undefined)
          : undefined,
        corpus_fingerprint: undefined,
        default_layout_profile: current?.default_layout_profile,
        latest_report: current?.latest_report ?? null,
        recent_reports: current?.recent_reports ?? [],
        parser_pipelines: current?.parser_pipelines ?? [],
      };
    });
    const nextJobs = jobsRef.current.flatMap((candidate) => {
      if (!importedIds.has(candidate.id)) {
        return [candidate];
      }
      const includedCandidate: JobRecord = {
        ...candidate,
        benchmark_included: true,
      };
      if (!isPristineBenchmarkImport(includedCandidate)) {
        return [includedCandidate];
      }
      if (candidate.id === dirtyActiveJobId) {
        processingRemovalCandidateIdsRef.current.delete(candidate.id);
        return [includedCandidate];
      }
      return [];
    });
    const removedActiveJobId = activeJobIdRef.current;
    const activeJobRemoved =
      removedActiveJobId !== null &&
      !nextJobs.some((candidate) => candidate.id === removedActiveJobId);
    updateJobs(() => nextJobs);
    if (activeJobRemoved) {
      const fallbackJob = nextJobs[0] ?? null;
      alignWorkspaceToJob(fallbackJob);
      replaceRemovedJobRoute(removedActiveJobId, fallbackJob);
    }
    setHistory((current) => {
      const next = current.map((item) =>
        importedIds.has(item.id)
          ? { ...item, job: { ...item.job, benchmark_included: true } }
          : item,
      );
      writeHistory(next);
      return next;
    });
    setHistorySearchResults(
      (current) =>
        current?.map((item) =>
          importedIds.has(item.id)
            ? { ...item, job: { ...item.job, benchmark_included: true } }
            : item,
        ) ?? null,
    );
    if (shouldRefreshOverview) {
      await refreshBenchmarkOverview({
        failureMessage:
          "Dataset imported, but benchmark counts could not be refreshed",
      });
    }
    return result.imported_cases + result.reused_cases;
  }

  async function onBenchmarkDatasetImport(
    event: ChangeEvent<HTMLInputElement>,
  ) {
    const input = event.currentTarget;
    const datasetFile = input.files?.[0];
    if (!datasetFile || benchmarkOperationsLocked) {
      input.value = "";
      return;
    }
    if (mutationRecoveryPending(["processing", "history"])) {
      input.value = "";
      return;
    }

    const removalCandidateIds = jobsRef.current
      .filter((candidate) =>
        isPristineBenchmarkImport({
          ...candidate,
          benchmark_included: true,
        }),
      )
      .map((candidate) => candidate.id);
    const benchmarkImportRequestId = createMutationRequestId();
    installMutationLease(
      "processing",
      startProjectionMutationLease(
        "processing",
        mutationOwnerId,
        processingJobsForCache(jobsRef.current),
        [],
        removalCandidateIds,
        benchmarkImportRequestId,
      ),
    );
    installMutationLease(
      "history",
      startProjectionMutationLease(
        "history",
        mutationOwnerId,
        history.map((item) => item.job),
        [],
        [],
        benchmarkImportRequestId,
      ),
    );
    beginProcessingMembershipMutation(removalCandidateIds);
    setBenchmarkImporting(true);
    setError(null);
    let restoreAfterImport = false;
    try {
      const { result } = await importBenchmarkDatasetCommand(queryClient, {
        file: datasetFile,
        requestId: benchmarkImportRequestId,
      });
      const readyCases = await applyBenchmarkDatasetImportResult(result);
      restoreAfterImport = true;
      clearOwnedMutationLease("processing");
      clearOwnedMutationLease("history");
      toast.success(
        `Dataset ready: ${readyCases} ${readyCases === 1 ? "hand" : "hands"}`,
      );
    } catch (benchmarkError) {
      const deterministicRejection =
        benchmarkError instanceof ApiResponseError &&
        benchmarkError.status >= 400 &&
        benchmarkError.status < 500 &&
        benchmarkError.status !== 408;
      if (deterministicRejection) {
        clearOwnedMutationLease("processing");
        clearOwnedMutationLease("history");
        for (const removalCandidateId of removalCandidateIds) {
          processingRemovalCandidateIdsRef.current.delete(removalCandidateId);
        }
        restoreAfterImport = true;
      } else {
        scheduleMutationLeaseRevalidation();
      }
      setError(
        messageFromError(benchmarkError, "Could not import parser dataset"),
      );
    } finally {
      input.value = "";
      endProcessingMembershipMutation(restoreAfterImport);
      setBenchmarkImporting(false);
    }
  }

  async function toggleBenchmarkInclusion() {
    if (!job || (!job.approved_state && !job.benchmark_included)) {
      return;
    }
    if (mutationRecoveryPending([persistedJobMutationScope(job)])) {
      return;
    }
    const included = !job.benchmark_included;
    const isCurrentlyPristine = isPristineBenchmarkImport(job);
    const willBePristine = isPristineBenchmarkImport({
      ...job,
      benchmark_included: included,
    });
    const changesProcessingMembership = isCurrentlyPristine !== willBePristine;
    const mutationScope = beginPersistedJobMutation(
      job,
      {
        kind: "benchmark-inclusion",
        included,
      },
      changesProcessingMembership && willBePristine ? [job.id] : [],
    );
    let restoreAfterMutation = changesProcessingMembership;
    setBenchmarkUpdating(true);
    setError(null);
    try {
      const { job: updated } = await setBenchmarkInclusionCommand(queryClient, {
        jobId: job.id,
        included,
      });
      replaceJob(updated);
      setBenchmarkOverview((current) => {
        const change = included ? 1 : -1;
        const layoutProfile =
          updated.parser_layout_profile ??
          current?.default_layout_profile ??
          null;
        const includedByLayout =
          layoutProfile && current?.included_cases_by_layout !== undefined
            ? {
                ...(current?.included_cases_by_layout ?? {}),
                [layoutProfile]: Math.max(
                  0,
                  (current?.included_cases_by_layout?.[layoutProfile] ?? 0) +
                    change,
                ),
              }
            : current?.included_cases_by_layout;
        const corpusFingerprint = benchmarkCorpusFingerprintAfterLayoutMutation(
          current?.corpus_fingerprint,
          layoutProfile,
          benchmarkTargetLayoutProfile,
        );
        return current
          ? {
              ...current,
              included_cases: Math.max(0, current.included_cases + change),
              included_cases_by_layout: includedByLayout,
              corpus_fingerprint: corpusFingerprint,
            }
          : {
              included_cases: included ? 1 : 0,
              included_cases_by_layout: includedByLayout,
              corpus_fingerprint: undefined,
              default_layout_profile: layoutProfile ?? undefined,
              latest_report: null,
              recent_reports: [],
            };
      });
    } catch (benchmarkError) {
      if (mutationFailureMayHavePersistedSideEffect(benchmarkError)) {
        markPersistedJobMutationUncertain(mutationScope, job.id);
      }
      restoreAfterMutation = true;
      setError(
        messageFromError(
          benchmarkError,
          "Could not update benchmark ground truth",
        ),
      );
    } finally {
      endPersistedJobMutation(mutationScope, restoreAfterMutation);
      setBenchmarkUpdating(false);
    }
  }

  function onAbortQueue() {
    queueAbortRequestedRef.current = true;
    queueAbortControllerRef.current?.abort();
    requestQueueAbort();
  }

  async function saveScreenshotMetadata() {
    if (
      !managedJob ||
      !managedJobPersisted ||
      screenshotMetadataSaving ||
      screenshotDeleting
    ) {
      return;
    }
    const mutationScope = persistedJobMutationScope(managedJob);
    const savingAlongsideRecommendation =
      mutationComposesWithActiveRecommendation(mutationScope);
    if (
      !savingAlongsideRecommendation &&
      mutationRecoveryPending([mutationScope])
    ) {
      return;
    }

    let tags: string[];
    try {
      tags = parseScreenshotTags(screenshotTagInput);
    } catch (metadataError) {
      setError(messageFromError(metadataError, "Check the screenshot tags"));
      return;
    }
    const title = screenshotTitle.trim() || null;
    const notes = screenshotNotes.trim() || null;
    const expectation: JobMutationExpectation = {
      kind: "metadata",
      title,
      notes,
      tags,
    };
    if (savingAlongsideRecommendation) {
      if (mutationScope === "processing") {
        beginProcessingMembershipMutation();
      } else {
        beginHistoryMutation();
      }
    } else {
      beginPersistedJobMutation(managedJob, expectation);
    }
    let restoreAfterMutation = false;
    let deletedRemotely = false;
    setScreenshotMetadataSaving(true);
    setError(null);
    try {
      const { job: updated } = await updateScreenshotMetadataCommand(
        queryClient,
        {
          jobId: managedJob.id,
          metadata: { title, notes, tags },
        },
      );
      const movedToHistory =
        mutationScope === "processing" && updated.archived_at !== null;
      if (movedToHistory) {
        removeJobFromProcessingProjection(updated.id);
        dismissScreenshotDetails();
        markHistorySessionUnsynced();
      } else {
        updateJobs((current) =>
          current.map((candidate) =>
            candidate.id === updated.id ? updated : candidate,
          ),
        );
      }
      updateHistoryJob(updated);
      if (!savingAlongsideRecommendation) {
        settlePersistedMutationLease(
          mutationScope,
          [updated],
          mutationScope === "processing",
        );
      }
      if (movedToHistory) {
        void requestHistoryRestore(null, true);
      }
      syncScreenshotDetails(updated);
      toast.success("Screenshot details saved");
    } catch (metadataError) {
      deletedRemotely =
        metadataError instanceof ApiResponseError &&
        metadataError.status === 404;
      if (deletedRemotely) {
        restoreAfterMutation = true;
        reconcileAuthoritativeScreenshotRemoval(managedJob, mutationScope);
        toast.warning("Screenshot was already deleted elsewhere");
      } else if (mutationFailureMayHavePersistedSideEffect(metadataError)) {
        markPersistedJobMutationUncertain(mutationScope, managedJob.id);
        restoreAfterMutation = true;
      }
      if (!deletedRemotely) {
        setError(
          messageFromError(metadataError, "Could not save screenshot details"),
        );
      }
    } finally {
      if (savingAlongsideRecommendation) {
        if (mutationScope === "processing") {
          endProcessingMembershipMutation(restoreAfterMutation);
        } else {
          endHistoryMutation(restoreAfterMutation);
        }
      } else {
        endPersistedJobMutation(mutationScope, deletedRemotely);
      }
      setScreenshotMetadataSaving(false);
    }
  }

  function removeJobFromProcessingProjection(jobId: string) {
    const currentJobs = jobsRef.current;
    const deletedIndex = currentJobs.findIndex(
      (candidate) => candidate.id === jobId,
    );
    const nextJobs = currentJobs.filter((candidate) => candidate.id !== jobId);
    updateJobs(() => nextJobs);
    clearJobAttention(jobId);
    if (activeJobIdRef.current === jobId) {
      const fallbackIndex = Math.min(
        Math.max(deletedIndex, 0),
        nextJobs.length - 1,
      );
      const fallbackJob = nextJobs[fallbackIndex] ?? null;
      alignWorkspaceToJob(fallbackJob);
      replaceRemovedJobRoute(jobId, fallbackJob);
    }
    if (writeProcessingQueue(nextJobs)) {
      markProcessingQueueSessionSynced();
    }
  }

  function removeScreenshotFromClient(deletedJob: JobRecord) {
    removeJobFromProcessingProjection(deletedJob.id);

    const removedFromSearch =
      historySearchResults?.some((item) => item.id === deletedJob.id) ?? false;
    setHistory((current) => {
      const next = current.filter((item) => item.id !== deletedJob.id);
      writeHistory(next);
      return next;
    });
    setHistorySearchResults(
      (current) => current?.filter((item) => item.id !== deletedJob.id) ?? null,
    );
    if (deletedJob.archived_at) {
      setHistoryTotal((current) => {
        const next = Math.max(0, current - 1);
        writeHistoryTotal(next);
        return next;
      });
    }
    if (removedFromSearch) {
      setHistorySearchTotal((current) => Math.max(0, current - 1));
    }
  }

  function reconcileAuthoritativeScreenshotRemoval(
    deletedJob: JobRecord,
    mutationScope: PersistedJobMutationScope,
  ) {
    const activeRecommendation = activeRecommendationRequestsRef.current.get(
      deletedJob.id,
    );
    if (
      activeRecommendation?.ownsMutationLease &&
      activeRecommendation.mutationScope === mutationScope
    ) {
      clearOwnedMutationLease(mutationScope);
    }
    if (mutationScope === "processing") {
      processingRemovalCandidateIdsRef.current.delete(deletedJob.id);
    }
    removeScreenshotFromClient(deletedJob);
    if (benchmarkOverview !== null || deletedJob.benchmark_included) {
      void refreshBenchmarkOverview({
        failureMessage:
          "Screenshot removed, but the benchmark count could not refresh",
      });
    }
    dismissScreenshotDetails();
    if (mutationScope === "processing") {
      markHistorySessionUnsynced();
      void requestHistoryRestore(null, true);
    } else {
      markProcessingQueueSessionUnsynced();
      scheduleProcessingQueueRestore();
    }
    if (activeRecommendation?.mutationScope === mutationScope) {
      activeRecommendation.controller.abort();
    }
  }

  async function permanentlyDeleteScreenshot() {
    if (!managedJob || screenshotMetadataSaving || screenshotDeleting) {
      return;
    }
    if (!managedJobPersisted) {
      if (localUploadDeletionRequiresRecovery(managedJob)) {
        markProcessingQueueSessionUnsynced();
        if (processingMutationLeaseRef.current !== null) {
          scheduleMutationLeaseRevalidation();
        } else {
          scheduleProcessingQueueRestore();
        }
        setError(
          "Checking whether this upload reached storage. Delete it after recovery finishes.",
        );
        return;
      }
      removeScreenshotFromClient(managedJob);
      dismissScreenshotDetails();
      toast.success("Failed upload removed from the queue");
      return;
    }

    const mutationScope = persistedJobMutationScope(managedJob);
    const deletingAlongsideRecommendation =
      mutationComposesWithActiveRecommendation(mutationScope);
    if (
      !deletingAlongsideRecommendation &&
      mutationRecoveryPending([mutationScope])
    ) {
      return;
    }
    if (mutationScope === "processing") {
      beginProcessingMembershipMutation([managedJob.id]);
    } else {
      beginHistoryMutation();
    }
    setScreenshotDeleting(true);
    setError(null);
    let restoreAfterMutation = false;
    try {
      await deleteScreenshotCommand(queryClient, managedJob.id);
      restoreAfterMutation = true;
      reconcileAuthoritativeScreenshotRemoval(managedJob, mutationScope);
      toast.success("Screenshot permanently deleted");
    } catch (deleteError) {
      restoreAfterMutation = true;
      setError(messageFromError(deleteError, "Could not delete screenshot"));
    } finally {
      if (mutationScope === "processing") {
        endProcessingMembershipMutation(restoreAfterMutation);
      } else {
        endHistoryMutation(restoreAfterMutation);
      }
      setScreenshotDeleting(false);
    }
  }

  function openHistory(item: HistoryItem) {
    updateJobs((current) => {
      const existing = current.some(
        (candidate) => candidate.id === item.job.id,
      );
      if (existing) {
        return current.map((candidate) =>
          candidate.id === item.job.id ? item.job : candidate,
        );
      }
      return [item.job, ...current];
    });
    activateJob(item.job);
  }

  async function clearReviewedToHistory() {
    const readyJobs = jobs.filter(isHistoryReady);
    if (
      readyJobs.length === 0 ||
      mutationRecoveryPending(["processing", "history"])
    ) {
      return;
    }

    setBusy(true);
    setError(null);
    installMutationLease(
      "processing",
      startArchiveMutationLease(
        "processing",
        mutationOwnerId,
        readyJobs,
        new Set(
          processingJobsForCache(jobsRef.current).map(
            (candidate) => candidate.id,
          ),
        ),
      ),
    );
    installMutationLease(
      "history",
      startArchiveMutationLease("history", mutationOwnerId, readyJobs),
    );
    beginProcessingMembershipMutation();
    beginHistoryMutation();
    let historyMutationActive = true;
    try {
      applyHistoryPage(
        (
          await archiveJobsCommand(
            queryClient,
            readyJobs.map((candidate) => candidate.id),
          )
        ).history,
      );
      clearOwnedMutationLease("processing");
      clearOwnedMutationLease("history");
      if (historySearchActive && historySearchQuery) {
        void revalidateHistorySearch(historySearchQuery);
      }
      const remainingJobs = jobs.filter(
        (candidate) => !isHistoryReady(candidate),
      );
      updateJobs(() => remainingJobs);
      if (remainingJobs.length > 0) {
        activateJob(
          remainingJobs.find((candidate) => candidate.id === activeJobId) ??
            remainingJobs[0],
          "replace",
        );
      } else {
        alignWorkspaceToJob(null);
        navigation.openWorkspace({ replace: true });
        setError(null);
      }
    } catch (historyError) {
      const archiveErrorMessage = messageFromError(
        historyError,
        "Could not save reviewed hands to history",
      );
      endHistoryMutation();
      historyMutationActive = false;
      const historyReconciled = await syncHistory(null, false);
      if (historyReconciled && historySearchActive && historySearchQuery) {
        await revalidateHistorySearch(historySearchQuery);
      } else if (!historyReconciled) {
        markHistorySessionUnsynced();
      }
      if (mutationFailureMayHavePersistedSideEffect(historyError)) {
        scheduleMutationLeaseRevalidation();
      } else {
        clearOwnedMutationLease("processing");
        clearOwnedMutationLease("history");
      }
      setError(archiveErrorMessage);
    } finally {
      if (historyMutationActive) {
        endHistoryMutation();
      }
      endProcessingMembershipMutation();
      setBusy(false);
    }
  }

  return {
    toolbar: {
      automationEnabled,
      busy,
      historyTotal,
      liveStatusLabel,
      onConfigureAutomation: () => setAutomationDialogOpen(true),
      onConfigurePipeline: openPipelineDialog,
      onOpenBenchmark: () => {
        openBenchmarkDialog();
        navigation.openBenchmarks();
      },
      onOpenHelp: () => setHelpDialogOpen(true),
      onOpenInfo: openInfoDialog,
      onOpenTraining: () => {
        openTrainingDialog();
        navigation.openTraining();
      },
      onToggleAutomation: () =>
        updateAutomationSettings((current) => ({
          ...current,
          enabled: !current.enabled,
        })),
      queueCount,
      screenSharing,
    },
    inputSource: {
      busy,
      files,
      inputMode,
      livePreviewVisible,
      onCapture: onCaptureScreen,
      onFilesChange: setFiles,
      onInputModeChange: setInputMode,
      onShareModeChange: setShareMode,
      onStartOrViewShare: () =>
        screenSharing ? setLivePreviewVisible(true) : onStartScreenShare(),
      onStopShare: onStopScreenShare,
      onUpload,
      screenSharing,
      screenSourceLabel,
      shareMode,
    },
    queue: {
      activeJobId: job?.id ?? null,
      attentionByJobId: jobAttention,
      busy,
      clearDisabled: historyLoading || busy || clearableJobs.length === 0,
      count: filmstripCount,
      jobs,
      onClearReviewed: clearReviewedToHistory,
      onManageJob: openScreenshotDetails,
      onOpenJob: activateJob,
      pendingFilesLabel: files.length > 0 ? selectedFilesLabel(files) : null,
    },
    history: {
      busy,
      items: visibleHistory,
      loading: historyLoading,
      onClearSearch: clearHistorySearch,
      onLoadOlder: () => void loadOlderHistory(),
      onManageJob: openScreenshotDetails,
      onOpenItem: openHistory,
      onOpenSearch: () => setHistorySearchOpen(true),
      onRefresh: () => void refreshVisibleHistory(),
      onSearch: () => void onSearchHistory(),
      onSearchInputChange: setHistorySearchInput,
      searchActive: historySearchActive,
      searchInput: historySearchInput,
      searchOpen: historySearchOpen,
      searchTotal: historySearchTotal,
      total: visibleHistoryTotal,
    },
    preview: {
      averageConfidence: confidenceSummary.averageConfidence,
      detectedFieldCount: confidenceSummary.detectedCount,
      fieldCount: confidenceSummary.fieldTotal,
      frameLabel,
      frameStreet,
      livePreviewVisible,
      ref: videoRef,
      reviewCount: confidenceSummary.reviewCount,
      screenSharing,
      screenshotUrl,
    },
    handReview: {
      busy,
      canApprove,
      canRecommend,
      currentStateApproved,
      decisionComparison,
      decisionEvidence,
      editor: {
        completedPostflopActionCounts,
        completedPostflopActionsAtLimit,
        confidences,
        disabled: busy,
        form,
        onAddCompletedPostflopAction: addCompletedPostflopAction,
        onAddPostflopAction: addPostflopAction,
        onAddPreflopAction: addPreflopAction,
        onChange: updateForm,
        onRemoveCompletedPostflopAction: removeCompletedPostflopAction,
        onRemovePostflopAction: removePostflopAction,
        onRemovePreflopAction: removePreflopAction,
        onUpdateCompletedPostflopAction: updateCompletedPostflopAction,
        onUpdatePostflopAction: updatePostflopAction,
        onUpdatePreflopAction: updatePreflopAction,
        warnings,
      },
      job,
      onApprove,
      onCancelTrainingReviewNoteEdit: cancelTrainingReviewNoteEdit,
      onCompleteTrainingReview,
      onRecommend,
      onReopenTrainingReview,
      onResetToParser: resetToParser,
      onSaveTrainingDecision,
      onStartTrainingReviewNoteEdit: startTrainingReviewNoteEdit,
      onTrainingActionChange: (action: typeof trainingAction) => {
        setTrainingAction(action);
        if (action !== "bet" && action !== "raise") {
          setTrainingSizing("");
        }
      },
      onTrainingCertaintyChange: (certainty: typeof trainingCertainty) =>
        setTrainingCertainty(trainingCertainty === certainty ? "" : certainty),
      onTrainingReviewNoteChange: setTrainingReviewNote,
      onTrainingSizingChange: setTrainingSizing,
      onUpdateTrainingReviewNote,
      recommendation: activeRecommendation,
      trainingAction,
      trainingCertainty,
      trainingDecision: activeTrainingDecision,
      trainingReviewNote,
      trainingReviewNoteEditing,
      trainingReviewQueueJobId,
      trainingSizing,
    },
    dialogs: {
      queueProcessing: queueProgress
        ? { onAbort: onAbortQueue, progress: queueProgress }
        : null,
      screenshotDetails: managedJob
        ? {
            deleteArmed: screenshotDeleteArmed,
            deleting: screenshotDeleting,
            job: managedJob,
            metadataSaving: screenshotMetadataSaving,
            notes: screenshotNotes,
            onClose: closeScreenshotDetails,
            onDelete: () => void permanentlyDeleteScreenshot(),
            onDeleteArmedChange: setScreenshotDeleteArmed,
            onNotesChange: setScreenshotNotes,
            onSave: () => void saveScreenshotMetadata(),
            onTagsChange: setScreenshotTagInput,
            onTitleChange: setScreenshotTitle,
            persisted: managedJobPersisted,
            recoveryPending: managedLocalUploadRecoveryPending,
            tags: screenshotTagInput,
            title: screenshotTitle,
          }
        : null,
      automation: automationDialogOpen
        ? {
            allowWarnings: automationAllowWarnings,
            autoApprove: automationApprove,
            autoRecommend: automationRecommend,
            enabled: automationEnabled,
            onAllowWarningsChange: (value: boolean) =>
              updateAutomationSettings((current) => ({
                ...current,
                allowWarnings: value,
              })),
            onAutoApproveChange: updateAutomationApprove,
            onAutoRecommendChange: (value: boolean) =>
              updateAutomationSettings((current) => ({
                ...current,
                autoRecommend: value,
              })),
            onClose: () => setAutomationDialogOpen(false),
          }
        : null,
      pipeline: pipelineDialogOpen
        ? {
            capabilities: pipelineCapabilities,
            compatibleLayouts: compatiblePipelineLayouts,
            loading: pipelineLoading,
            onClose: () => setPipelineDialogOpen(false),
            onParserChange: updateParserProvider,
            onParserLayoutChange: (value: string) =>
              updatePipelineSelection("parser_layout_profile", value),
            onRecommendationChange: updateRecommendationProvider,
            onRecommendationEngineChange: (value: string) =>
              updatePipelineSelection("recommendation_engine", value),
            selection: pipelineSelection,
          }
        : null,
      help: helpDialogOpen ? { onClose: () => setHelpDialogOpen(false) } : null,
      info: infoDialogOpen
        ? {
            backupDownloadUrl: applicationBackupUrl(),
            backupRestoring,
            busy,
            mcpTokenPending,
            onClose: () => closeInfoDialog(backupRestoring),
            onMcpTokenPendingChange: setMcpTokenPending,
            onRestoreBackup: (file: File) =>
              void onApplicationBackupRestore(file),
            providers: activeInfoProviders,
            systemInfoLoading,
          }
        : null,
      training: trainingDialogOpen
        ? {
            actionDifferenceFocus,
            busy,
            certaintyFilter: trainingCertaintyFilter,
            certaintyFocus,
            lessonOrder: trainingLessonOrder,
            lessonQuery: trainingLessonQuery,
            lessonSearch: trainingLessonSearch,
            lessonStreet: trainingLessonStreet,
            lessonsExportDisabled: trainingLessonsExportDisabled,
            nextReviewHand,
            onCertaintyFilterChange: updateTrainingCertaintyFilter,
            onClose: () => {
              setTrainingDialogOpen(false);
              navigation.closeSurface();
            },
            onFocusActionDifference: focusTrainingActionDifference,
            onFocusCertainty: focusTrainingReviewCertainty,
            onFocusPosition: focusTrainingReviewPosition,
            onFocusStreet: focusTrainingReviewStreet,
            onLessonFiltersChange: updateTrainingLessonFilters,
            onLessonSearchChange: setTrainingLessonSearch,
            onOpenHand: reviewTrainingHand,
            onPositionFilterChange: updateTrainingPositionFilter,
            onReopenHand: reopenTrainingReviewFromProgress,
            onReviewQueueChange: updateTrainingReviewQueue,
            onSolverFilterChange: updateTrainingSolverFilter,
            onStreetFilterChange: updateTrainingStreetFilter,
            onViewChange: selectTrainingProgressView,
            positionFilter: trainingPositionFilter,
            positionFocus,
            progress: trainingProgress,
            progressLoading: trainingProgressLoading,
            reviewCertainty: trainingReviewCertainty,
            reviewDifference: trainingReviewDifference,
            reviewJobId: trainingReviewJobId,
            reviewOrder: trainingReviewOrder,
            reviewPosition: trainingReviewPosition,
            reviewQueueStatus,
            reviewStreet: trainingReviewStreet,
            solverFilter: trainingSolverFilter,
            streetFilter: trainingStreetFilter,
            streetFocus: trainingFocus,
            view: trainingProgressView,
            visibleHands: visibleTrainingHands,
          }
        : null,
      benchmark: benchmarkDialogOpen
        ? {
            busy,
            comparisonProgress: benchmarkComparisonProgress,
            comparisonReport: benchmarkComparisonReport,
            comparisonReportLoading: benchmarkComparisonReportLoading,
            currentJob: job,
            datasetExportDisabled: benchmarkDatasetExportDisabled,
            datasetInputRef: benchmarkDatasetInputRef,
            importInProgress: benchmarkImporting,
            includedCases: benchmarkIncludedCases,
            loading: benchmarkLoading,
            onChooseDatasetImport: () =>
              benchmarkDatasetInputRef.current?.click(),
            onClose: () => {
              closeBenchmarkDialog();
              navigation.closeSurface();
            },
            onDatasetImport: onBenchmarkDatasetImport,
            onReviewCase: reviewBenchmarkCase,
            onRun: onRunBenchmark,
            onRunComparison: onRunBenchmarkComparison,
            onSelectPipeline: selectBenchmarkParserPipeline,
            onSelectReport: selectBenchmarkReport,
            onToggleInclusion: toggleBenchmarkInclusion,
            operationsLocked: benchmarkOperationsLocked,
            overview: benchmarkOverview,
            parserPipelines: benchmarkParserPipelines,
            pipelineCapabilities,
            pipelineLoading,
            pipelineSelection,
            previousReport: previousBenchmarkReport,
            recentReports: recentBenchmarkReports,
            report: benchmarkReport,
            reportLoading: benchmarkReportLoading,
            reportParserLabel: benchmarkReportParserLabel,
            reportStale: benchmarkReportStale,
            reviewJobId: benchmarkReviewJobId,
            running: benchmarkRunning,
            targetLayoutLabel: benchmarkTargetLayoutLabel,
            updating: benchmarkUpdating,
          }
        : null,
    },
  };
}
