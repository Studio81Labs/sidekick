import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { getHistory } from "../../../domains/history/api/historyApi";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { supersedeQueryAccessGeneration } from "../../../shared/api/queryCache";
import { jobRecord } from "../../../test/analyzerHarness";
import {
  HISTORY_CACHE_LIMIT,
  readCachedHistoryTotal,
  readHistory,
  writeHistory,
  writeHistoryTotal,
} from "./historyPersistence";
import { getHistorySearchExtent } from "./queryReads";

vi.mock("../../../domains/history/api/historyApi", () => ({
  getHistory: vi.fn(),
}));

describe("history persistence", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.mocked(getHistory).mockReset();
  });

  it("keeps the browser history cache bounded while retaining the server total", () => {
    const items = Array.from(
      { length: HISTORY_CACHE_LIMIT + 2 },
      (_, index) => {
        const job = jobRecord({
          id: index.toString(16).padStart(32, "0"),
          archived_at: "2026-07-10T00:00:00Z",
        });
        return { id: job.id, job, savedAt: job.archived_at! };
      },
    );

    expect(writeHistory(items)).toBe(true);
    expect(writeHistoryTotal(items.length)).toBe(true);
    const cached = readHistory();
    expect(cached).toHaveLength(HISTORY_CACHE_LIMIT);
    expect(readCachedHistoryTotal(cached)).toBe(items.length);
  });

  it("retries history pagination when the snapshot changes", async () => {
    const queryClient = createQueryClient();
    const firstJob = jobRecord({
      id: "1".repeat(32),
      archived_at: "2026-07-10T00:00:00Z",
    });
    const secondJob = jobRecord({
      id: "2".repeat(32),
      archived_at: "2026-07-10T00:00:00Z",
    });
    vi.mocked(getHistory)
      .mockResolvedValueOnce({
        total: 2,
        jobs: [firstJob],
        snapshot_version: "first",
      })
      .mockResolvedValueOnce({
        total: 2,
        jobs: [secondJob],
        snapshot_version: "changed",
      })
      .mockResolvedValueOnce({
        total: 2,
        jobs: [firstJob, secondJob],
        snapshot_version: "stable",
      });

    await expect(
      getHistorySearchExtent(queryClient, "administrator-token", "river", 2),
    ).resolves.toEqual({
      total: 2,
      jobs: [firstJob, secondJob],
      snapshot_version: "stable",
    });
    expect(getHistory).toHaveBeenNthCalledWith(
      1,
      "administrator-token",
      0,
      "river",
      2,
    );
    expect(getHistory).toHaveBeenNthCalledWith(
      2,
      "administrator-token",
      1,
      "river",
      1,
    );
    expect(getHistory).toHaveBeenNthCalledWith(
      3,
      "administrator-token",
      0,
      "river",
      2,
    );
    expect(
      queryClient.getQueryData(historyQueryKeys.page(0, "river", 2)),
    ).toEqual({
      total: 2,
      jobs: [firstJob, secondJob],
      snapshot_version: "stable",
    });
  });

  it("stops history rebuilding after administrator access is superseded", async () => {
    const queryClient = createQueryClient();
    const firstJob = jobRecord({
      id: "3".repeat(32),
      archived_at: "2026-07-10T00:00:00Z",
    });
    let resolveFirstPage!: (value: {
      total: number;
      jobs: (typeof firstJob)[];
      snapshot_version: string;
    }) => void;
    vi.mocked(getHistory).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirstPage = resolve;
        }),
    );

    const loading = getHistorySearchExtent(
      queryClient,
      "administrator-token",
      "river",
      2,
    );
    supersedeQueryAccessGeneration(queryClient);
    resolveFirstPage({
      total: 2,
      jobs: [firstJob],
      snapshot_version: "current",
    });

    await expect(loading).rejects.toThrow(
      "Administrator access changed before this operation completed",
    );
    expect(getHistory).toHaveBeenCalledOnce();
    expect(
      queryClient.getQueryData(historyQueryKeys.page(0, "river", 2)),
    ).toBeUndefined();
  });
});
