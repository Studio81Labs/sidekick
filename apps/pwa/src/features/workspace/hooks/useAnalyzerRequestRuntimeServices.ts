import { useRef } from "react";

import type { ActiveRecommendationRequest } from "../lib/workflow";

export function useAnalyzerRequestRuntimeServices() {
  const activeRecommendationRequestsRef = useRef(
    new Map<string, ActiveRecommendationRequest>(),
  );
  const appMountedRef = useRef(true);
  const historySearchRequestRef = useRef(0);
  const queueAbortControllerRef = useRef<AbortController | null>(null);
  const queueAbortRequestedRef = useRef(false);

  return {
    activeRecommendationRequestsRef,
    appMountedRef,
    historySearchRequestRef,
    queueAbortControllerRef,
    queueAbortRequestedRef,
  };
}
