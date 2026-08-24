import {
  createContext,
  createElement,
  type Dispatch,
  type PropsWithChildren,
  useContext,
  useMemo,
  useReducer,
} from "react";

export type AnalyzerWorkflowState = {
  activeJobId: string | null;
  attentionByJobId: Readonly<Record<string, string>>;
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
};

const AnalyzerWorkflowContext = createContext<AnalyzerWorkflowStore | null>(
  null,
);

export function AnalyzerWorkflowProvider({ children }: PropsWithChildren) {
  const [state, dispatch] = useReducer(
    analyzerWorkflowReducer,
    initialAnalyzerWorkflowState,
  );
  const store = useMemo(() => ({ state, dispatch }), [state]);

  return createElement(
    AnalyzerWorkflowContext.Provider,
    { value: store },
    children,
  );
}

export function useAnalyzerWorkflow(): AnalyzerWorkflowStore {
  const store = useContext(AnalyzerWorkflowContext);
  if (!store) {
    throw new Error(
      "useAnalyzerWorkflow must be used within AnalyzerWorkflowProvider",
    );
  }
  return store;
}
