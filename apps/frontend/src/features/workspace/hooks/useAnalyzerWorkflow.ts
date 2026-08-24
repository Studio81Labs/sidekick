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
  attentionByJobId: Readonly<Record<string, string>>;
  queueProgress: AnalyzerQueueProgress | null;
  recoveryRequests: {
    mutationLease: number;
    processing: number;
  };
};

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
    };

export const initialAnalyzerWorkflowState: AnalyzerWorkflowState = {
  attentionByJobId: {},
  queueProgress: null,
  recoveryRequests: {
    mutationLease: 0,
    processing: 0,
  },
};

export function analyzerWorkflowReducer(
  state: AnalyzerWorkflowState,
  event: AnalyzerWorkflowEvent,
): AnalyzerWorkflowState {
  switch (event.type) {
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
      };
    }
    case "mutation-lease-revalidation-requested": {
      return {
        ...state,
        recoveryRequests: {
          ...state.recoveryRequests,
          mutationLease: state.recoveryRequests.mutationLease + 1,
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
