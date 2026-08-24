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
    };

export const initialAnalyzerWorkflowState: AnalyzerWorkflowState = {
  attentionByJobId: {},
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
