import { useRef } from "react";

export function useAnalyzerRequestRuntimeServices() {
  const appMountedRef = useRef(true);
  const historySearchRequestRef = useRef(0);
  const queueAbortControllerRef = useRef<AbortController | null>(null);
  const queueAbortRequestedRef = useRef(false);

  return {
    appMountedRef,
    historySearchRequestRef,
    queueAbortControllerRef,
    queueAbortRequestedRef,
  };
}
