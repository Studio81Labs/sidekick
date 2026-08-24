import {
  historySessionSynced,
  markHistorySessionSynced,
  markHistorySessionUnsynced,
  readCachedHistoryTotal,
  readHistory,
  readHistoryTotal,
  writeHistory,
  writeHistoryTotal,
} from "../lib/historyPersistence";
import {
  startArchiveMutationLease,
  startPersistedMutationLease,
  startProjectionMutationLease,
} from "../lib/mutationLeaseFactories";
import {
  claimPersistedMutationLease,
  clearPersistedMutationLease,
  readPersistedMutationLease,
  replacePersistedMutationLease,
} from "../lib/mutationLeaseStorage";
import {
  markProcessingQueueSessionSynced,
  markProcessingQueueSessionUnsynced,
  PROCESSING_QUEUE_STORAGE_KEY,
  PROCESSING_QUEUE_TOTAL_STORAGE_KEY,
  processingQueueSessionSynced,
  readCachedProcessingQueueTotal,
  readProcessingQueue,
  writeProcessingQueue,
} from "../lib/processingQueuePersistence";

export type AnalyzerWorkflowProjectionAdapters = {
  claimPersistedMutationLease: typeof claimPersistedMutationLease;
  clearPersistedMutationLease: typeof clearPersistedMutationLease;
  historySessionSynced: typeof historySessionSynced;
  isProcessingQueueStorageEvent: (event: StorageEvent) => boolean;
  markHistorySessionSynced: typeof markHistorySessionSynced;
  markHistorySessionUnsynced: typeof markHistorySessionUnsynced;
  markProcessingQueueSessionSynced: typeof markProcessingQueueSessionSynced;
  markProcessingQueueSessionUnsynced: typeof markProcessingQueueSessionUnsynced;
  processingQueueSessionSynced: typeof processingQueueSessionSynced;
  readCachedHistoryTotal: typeof readCachedHistoryTotal;
  readCachedProcessingQueueTotal: typeof readCachedProcessingQueueTotal;
  readHistory: typeof readHistory;
  readHistoryTotal: typeof readHistoryTotal;
  readPersistedMutationLease: typeof readPersistedMutationLease;
  readProcessingQueue: typeof readProcessingQueue;
  replacePersistedMutationLease: typeof replacePersistedMutationLease;
  startArchiveMutationLease: typeof startArchiveMutationLease;
  startPersistedMutationLease: typeof startPersistedMutationLease;
  startProjectionMutationLease: typeof startProjectionMutationLease;
  writeHistory: typeof writeHistory;
  writeHistoryTotal: typeof writeHistoryTotal;
  writeProcessingQueue: typeof writeProcessingQueue;
};

export const browserAnalyzerWorkflowProjections = {
  claimPersistedMutationLease,
  clearPersistedMutationLease,
  historySessionSynced,
  isProcessingQueueStorageEvent: (event: StorageEvent) =>
    typeof window !== "undefined" &&
    (event.key === PROCESSING_QUEUE_STORAGE_KEY ||
      event.key === PROCESSING_QUEUE_TOTAL_STORAGE_KEY) &&
    (event.storageArea === null || event.storageArea === window.localStorage),
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
} satisfies AnalyzerWorkflowProjectionAdapters;
