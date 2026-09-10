import {
  createContext,
  createElement,
  type Dispatch,
  type PropsWithChildren,
  useCallback,
  useContext,
  useMemo,
  useReducer,
} from "react";

import type {
  PersistedJobMutationScope,
  PersistedMutationLease,
} from "../lib/mutationLeaseTypes";
import {
  browserAnalyzerWorkflowProjections,
  type AnalyzerWorkflowProjectionAdapters,
} from "../services/browserAnalyzerWorkflowProjections";

export type AnalyzerMutationLeases = Record<
  PersistedJobMutationScope,
  PersistedMutationLease | null
>;

export type AnalyzerWorkflowState = {
  activeJobId: string | null;
  attentionByJobId: Readonly<Record<string, string>>;
  mutationLeases: AnalyzerMutationLeases;
  queueProgress: AnalyzerQueueProgress | null;
  recoveryRequests: {
    mutationLease: number;
    processing: number;
  };
  recoveryPhases: Record<AnalyzerRecoveryKind, AnalyzerRecoveryPhase>;
};

export type AnalyzerRecoveryKind = "mutationLease" | "processing";

export type AnalyzerRecoveryPhase =
  | "idle"
  | "requested"
  | "running"
  | "retry-scheduled";

export type AnalyzerQueueProgress = {
  aborting: boolean;
  completed: number;
  currentFile: string;
  currentIndex: number;
  failed: number;
  skipped: number;
  total: number;
};

export type AnalyzerWorkflowEvent =
  | {
      type: "active-job-selected";
      jobId: string | null;
    }
  | {
      type: "job-attention-marked";
      jobId: string;
      message: string;
    }
  | {
      type: "job-attention-cleared";
      jobIds: readonly string[];
    }
  | {
      type: "mutation-lease-updated";
      scope: PersistedJobMutationScope;
      lease: PersistedMutationLease | null;
    }
  | {
      type: "queue-progress-updated";
      progress: AnalyzerQueueProgress;
    }
  | {
      type: "queue-abort-requested";
    }
  | {
      type: "queue-processing-finished";
    }
  | {
      type: "processing-recovery-requested";
    }
  | {
      type: "mutation-lease-revalidation-requested";
    }
  | {
      type:
        | "recovery-started"
        | "recovery-retry-scheduled"
        | "recovery-finished";
      recovery: AnalyzerRecoveryKind;
    };

export const initialAnalyzerWorkflowState: AnalyzerWorkflowState = {
  activeJobId: null,
  attentionByJobId: {},
  mutationLeases: {
    processing: null,
    history: null,
  },
  queueProgress: null,
  recoveryRequests: {
    mutationLease: 0,
    processing: 0,
  },
  recoveryPhases: {
    mutationLease: "idle",
    processing: "idle",
  },
};

export function analyzerWorkflowReducer(
  state: AnalyzerWorkflowState,
  event: AnalyzerWorkflowEvent,
): AnalyzerWorkflowState {
  switch (event.type) {
    case "active-job-selected": {
      if (state.activeJobId === event.jobId) {
        return state;
      }
      return { ...state, activeJobId: event.jobId };
    }
    case "job-attention-marked": {
      if (state.attentionByJobId[event.jobId] === event.message) {
        return state;
      }
      return {
        ...state,
        attentionByJobId: {
          ...state.attentionByJobId,
          [event.jobId]: event.message,
        },
      };
    }
    case "job-attention-cleared": {
      const matchingJobIds = event.jobIds.filter(
        (jobId) => jobId in state.attentionByJobId,
      );
      if (matchingJobIds.length === 0) {
        return state;
      }
      const attentionByJobId = { ...state.attentionByJobId };
      for (const jobId of matchingJobIds) {
        delete attentionByJobId[jobId];
      }
      return { ...state, attentionByJobId };
    }
    case "mutation-lease-updated": {
      if (state.mutationLeases[event.scope] === event.lease) {
        return state;
      }
      return {
        ...state,
        mutationLeases: {
          ...state.mutationLeases,
          [event.scope]: event.lease,
        },
      };
    }
    case "queue-progress-updated": {
      if (state.queueProgress === event.progress) {
        return state;
      }
      return { ...state, queueProgress: event.progress };
    }
    case "queue-abort-requested": {
      if (!state.queueProgress || state.queueProgress.aborting) {
        return state;
      }
      return {
        ...state,
        queueProgress: {
          ...state.queueProgress,
          aborting: true,
          skipped: Math.max(
            state.queueProgress.total - state.queueProgress.completed,
            0,
          ),
        },
      };
    }
    case "queue-processing-finished": {
      if (state.queueProgress === null) {
        return state;
      }
      return { ...state, queueProgress: null };
    }
    case "processing-recovery-requested": {
      return {
        ...state,
        recoveryRequests: {
          ...state.recoveryRequests,
          processing: state.recoveryRequests.processing + 1,
        },
        recoveryPhases: {
          ...state.recoveryPhases,
          processing:
            state.recoveryPhases.processing === "running"
              ? "running"
              : "requested",
        },
      };
    }
    case "mutation-lease-revalidation-requested": {
      return {
        ...state,
        recoveryRequests: {
          ...state.recoveryRequests,
          mutationLease: state.recoveryRequests.mutationLease + 1,
        },
        recoveryPhases: {
          ...state.recoveryPhases,
          mutationLease:
            state.recoveryPhases.mutationLease === "running"
              ? "running"
              : "requested",
        },
      };
    }
    case "recovery-started":
    case "recovery-retry-scheduled":
    case "recovery-finished": {
      const phase =
        event.type === "recovery-started"
          ? "running"
          : event.type === "recovery-retry-scheduled"
            ? "retry-scheduled"
            : "idle";
      if (state.recoveryPhases[event.recovery] === phase) {
        return state;
      }
      return {
        ...state,
        recoveryPhases: {
          ...state.recoveryPhases,
          [event.recovery]: phase,
        },
      };
    }
  }
}

type AnalyzerWorkflowStore = {
  state: AnalyzerWorkflowState;
  dispatch: Dispatch<AnalyzerWorkflowEvent>;
  projections: AnalyzerWorkflowProjectionAdapters;
};

const AnalyzerWorkflowContext = createContext<AnalyzerWorkflowStore | null>(
  null,
);

type AnalyzerWorkflowProviderProps = PropsWithChildren<{
  initialActiveJobId?: string | null;
  initialMutationLeases?: AnalyzerMutationLeases;
  mutationOwnerId?: string;
  projections?: AnalyzerWorkflowProjectionAdapters;
}>;

type AnalyzerWorkflowInitialization = {
  initialActiveJobId?: string | null;
  initialMutationLeases?: AnalyzerMutationLeases;
  mutationOwnerId?: string;
  projections: AnalyzerWorkflowProjectionAdapters;
};

function initializeAnalyzerWorkflowState({
  initialActiveJobId,
  initialMutationLeases,
  mutationOwnerId,
  projections,
}: AnalyzerWorkflowInitialization): AnalyzerWorkflowState {
  const mutationLeases =
    initialMutationLeases ??
    (mutationOwnerId
      ? {
          processing: projections.claimPersistedMutationLease(
            "processing",
            mutationOwnerId,
          ),
          history: projections.claimPersistedMutationLease(
            "history",
            mutationOwnerId,
          ),
        }
      : initialAnalyzerWorkflowState.mutationLeases);

  return {
    ...initialAnalyzerWorkflowState,
    activeJobId: initialActiveJobId ?? null,
    mutationLeases,
  };
}

export function AnalyzerWorkflowProvider({
  children,
  initialActiveJobId,
  initialMutationLeases,
  mutationOwnerId,
  projections = browserAnalyzerWorkflowProjections,
}: AnalyzerWorkflowProviderProps) {
  const [state, dispatch] = useReducer(
    analyzerWorkflowReducer,
    { initialActiveJobId, initialMutationLeases, mutationOwnerId, projections },
    initializeAnalyzerWorkflowState,
  );
  const store = useMemo(
    () => ({ state, dispatch, projections }),
    [projections, state],
  );

  return createElement(
    AnalyzerWorkflowContext.Provider,
    { value: store },
    children,
  );
}

function useAnalyzerWorkflowStore(): AnalyzerWorkflowStore {
  const store = useContext(AnalyzerWorkflowContext);
  if (!store) {
    throw new Error(
      "Analyzer workflow hooks must be used within AnalyzerWorkflowProvider",
    );
  }
  return store;
}

export function useAnalyzerWorkflowProjections() {
  return useAnalyzerWorkflowStore().projections;
}

export function useAnalyzerActiveSelection() {
  const {
    state: { activeJobId },
    dispatch,
  } = useAnalyzerWorkflowStore();
  const selectActiveJob = useCallback(
    (jobId: string | null) => dispatch({ type: "active-job-selected", jobId }),
    [dispatch],
  );

  return { activeJobId, selectActiveJob };
}

export function useAnalyzerQueueWorkflow() {
  const {
    state: { attentionByJobId, queueProgress },
    dispatch,
  } = useAnalyzerWorkflowStore();
  const markJobAttention = useCallback(
    (jobId: string, message: string) =>
      dispatch({ type: "job-attention-marked", jobId, message }),
    [dispatch],
  );
  const clearJobAttention = useCallback(
    (jobIds: readonly string[]) =>
      dispatch({ type: "job-attention-cleared", jobIds }),
    [dispatch],
  );
  const setQueueProgress = useCallback(
    (progress: AnalyzerQueueProgress | null) =>
      dispatch(
        progress
          ? { type: "queue-progress-updated", progress }
          : { type: "queue-processing-finished" },
      ),
    [dispatch],
  );
  const requestQueueAbort = useCallback(
    () => dispatch({ type: "queue-abort-requested" }),
    [dispatch],
  );

  return {
    attentionByJobId,
    clearJobAttention,
    markJobAttention,
    queueProgress,
    requestQueueAbort,
    setQueueProgress,
  };
}

export function useAnalyzerMutationLeases() {
  const {
    state: { mutationLeases },
    dispatch,
  } = useAnalyzerWorkflowStore();
  const setMutationLease = useCallback(
    (scope: PersistedJobMutationScope, lease: PersistedMutationLease | null) =>
      dispatch({ type: "mutation-lease-updated", scope, lease }),
    [dispatch],
  );

  return { mutationLeases, setMutationLease };
}

export function useAnalyzerRecoveryWorkflow() {
  const {
    state: { recoveryPhases, recoveryRequests },
    dispatch,
  } = useAnalyzerWorkflowStore();
  const requestProcessingRecovery = useCallback(
    () => dispatch({ type: "processing-recovery-requested" }),
    [dispatch],
  );
  const requestMutationLeaseRevalidation = useCallback(
    () => dispatch({ type: "mutation-lease-revalidation-requested" }),
    [dispatch],
  );
  const startRecovery = useCallback(
    (recovery: AnalyzerRecoveryKind) =>
      dispatch({ type: "recovery-started", recovery }),
    [dispatch],
  );
  const scheduleRecoveryRetry = useCallback(
    (recovery: AnalyzerRecoveryKind) =>
      dispatch({ type: "recovery-retry-scheduled", recovery }),
    [dispatch],
  );
  const finishRecovery = useCallback(
    (recovery: AnalyzerRecoveryKind) =>
      dispatch({ type: "recovery-finished", recovery }),
    [dispatch],
  );

  return {
    finishRecovery,
    mutationLeaseRestoreRequest: recoveryRequests.mutationLease,
    processingRestoreRequest: recoveryRequests.processing,
    recoveryPhases,
    requestMutationLeaseRevalidation,
    requestProcessingRecovery,
    scheduleRecoveryRetry,
    startRecovery,
  };
}
