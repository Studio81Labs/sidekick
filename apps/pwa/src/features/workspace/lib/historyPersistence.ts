import type { JobHistory } from "../../../shared/types/jobs";
import type { HistoryItem } from "../../../domains/history/model/historyItem";
import { readPersistedMutationLease } from "./mutationLeaseStorage";
import { newerHistoryItem } from "./reconciliation";

export const HISTORY_SESSION_SYNC_KEY = "poker-training-history-synced";
export const HISTORY_STORAGE_KEY = "poker-training-history-v1";
export const HISTORY_TOTAL_STORAGE_KEY = "poker-training-history-total-v1";
export const HISTORY_CACHE_LIMIT = 24;

export function readHistory(): HistoryItem[] | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(HISTORY_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as HistoryItem[]) : null;
  } catch {
    return null;
  }
}

export function writeHistory(items: HistoryItem[]): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    window.localStorage.setItem(
      HISTORY_STORAGE_KEY,
      JSON.stringify(items.slice(0, HISTORY_CACHE_LIMIT)),
    );
    return true;
  } catch {
    // Persisted history remains authoritative when the bounded browser cache is unavailable.
    markHistorySessionUnsynced();
    return false;
  }
}

export function readCachedHistoryTotal(
  cachedHistory: HistoryItem[] | null,
): number | null {
  if (cachedHistory === null || typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(HISTORY_TOTAL_STORAGE_KEY);
    if (raw === null) {
      return null;
    }
    const parsed = Number(raw);
    if (
      !Number.isSafeInteger(parsed) ||
      parsed < 0 ||
      cachedHistory.length !== Math.min(parsed, HISTORY_CACHE_LIMIT)
    ) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function readHistoryTotal(): number {
  const cachedHistory = readHistory();
  return readCachedHistoryTotal(cachedHistory) ?? cachedHistory?.length ?? 0;
}

export function writeHistoryTotal(total: number): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    window.localStorage.setItem(HISTORY_TOTAL_STORAGE_KEY, String(total));
    return true;
  } catch {
    // The server count remains authoritative when browser storage is unavailable.
    markHistorySessionUnsynced();
    return false;
  }
}

export function markHistorySessionSynced(): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    if (readPersistedMutationLease("history") !== null) {
      window.sessionStorage.removeItem(HISTORY_SESSION_SYNC_KEY);
      return;
    }
    window.sessionStorage.setItem(HISTORY_SESSION_SYNC_KEY, "true");
  } catch {
    // The persisted endpoint remains usable when browser storage is unavailable.
  }
}

export function markHistorySessionUnsynced(): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.sessionStorage.removeItem(HISTORY_SESSION_SYNC_KEY);
  } catch {
    // A blocked session store already forces the app to fetch history on reload.
  }
}

export function historySessionSynced(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    return window.sessionStorage.getItem(HISTORY_SESSION_SYNC_KEY) === "true";
  } catch {
    return false;
  }
}

export function historyItemsFromPage(page: JobHistory): HistoryItem[] {
  return page.jobs.map((job) => ({
    id: job.id,
    job,
    savedAt: job.archived_at ?? job.updated_at,
  }));
}
