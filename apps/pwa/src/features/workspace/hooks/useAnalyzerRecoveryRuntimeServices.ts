import { useRef } from "react";

import type { ProcessingQueueRestore } from "../lib/processingQueuePersistence";

export function useAnalyzerRecoveryRuntimeServices() {
  const benchmarkImportRecoveryPromiseRef = useRef<Promise<void> | null>(null);
  const historyFullRestoreRequestedRef = useRef(false);
  const historyJobRestoreActiveIdsRef = useRef(new Set<string>());
  const historyJobRestoreIdsRef = useRef(new Set<string>());
  const historyJobRestorePromiseRef = useRef<Promise<void> | null>(null);
  const historyJobRestoreRetryTimerRef = useRef<number | null>(null);
  const historyRestorePromiseRef = useRef<Promise<boolean> | null>(null);
  const historyRestoreRetryRequestedRef = useRef(false);
  const legacyHistoryArchivePromiseRef = useRef<Promise<boolean> | null>(null);
  const processingRestorePromiseRef =
    useRef<Promise<ProcessingQueueRestore> | null>(null);
  const processingRestoreRetryRequestedRef = useRef(false);
  const processingStorageRestoreScheduledRef = useRef(false);

  return {
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
  };
}
