import { getHistory } from "../../../domains/history/api/historyApi";
import type { JobHistory, JobRecord } from "../../../shared/types/jobs";
import type { HistoryItem } from "../../history/lib/historyPresentation";
import { readPersistedMutationLease } from "./mutationLeaseStorage";
import { newerHistoryItem } from "./reconciliation";

export const HISTORY_SESSION_SYNC_KEY = "poker-training-history-synced";
export const HISTORY_STORAGE_KEY = "poker-training-history-v1";
export const HISTORY_TOTAL_STORAGE_KEY = "poker-training-history-total-v1";
export const HISTORY_CACHE_LIMIT = 24;
export const HISTORY_SEARCH_PAGE_LIMIT = 100;
export const HISTORY_SNAPSHOT_RETRY_LIMIT = 3;

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

export async function getHistorySearchExtent(
  query: string,
  loadedCount: number,
): Promise<JobHistory> {
  for (let attempt = 0; attempt < HISTORY_SNAPSHOT_RETRY_LIMIT; attempt += 1) {
    const jobs: JobRecord[] = [];
    let snapshotVersion: string | null = null;
    let snapshotChanged = false;
    let total = 0;

    do {
      const page = await getHistory(
        jobs.length,
        query,
        Math.min(HISTORY_SEARCH_PAGE_LIMIT, loadedCount - jobs.length),
      );
      if (
        snapshotVersion !== null &&
        page.snapshot_version !== undefined &&
        page.snapshot_version !== snapshotVersion
      ) {
        snapshotChanged = true;
        break;
      }
      snapshotVersion ??= page.snapshot_version ?? null;
      total = page.total;
      jobs.push(...page.jobs);
      if (page.jobs.length === 0) {
        break;
      }
    } while (jobs.length < Math.min(loadedCount, total));

    if (!snapshotChanged) {
      return {
        total,
        jobs: jobs.slice(0, Math.min(loadedCount, total)),
        snapshot_version: snapshotVersion ?? undefined,
      };
    }
  }

  throw new Error("Saved history changed repeatedly while loading");
}
