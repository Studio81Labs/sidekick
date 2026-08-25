import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { getProcessingJobs } from "../../../domains/jobs/api/jobsApi";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { jobRecord } from "../../../test/analyzerHarness";
import {
  readCachedProcessingQueueTotal,
  readProcessingQueue,
  writeProcessingQueue,
} from "./processingQueuePersistence";
import { getProcessingQueueExtent } from "./queryReads";

vi.mock("../../../domains/jobs/api/jobsApi", () => ({
  getProcessingJobs: vi.fn(),
}));

const persistedJob = jobRecord({ id: "e".repeat(32) });

describe("processing queue persistence", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.mocked(getProcessingJobs).mockReset();
  });

  it("writes and reads a validated processing cache with its total", () => {
    expect(writeProcessingQueue([persistedJob])).toBe(true);

    const cached = readProcessingQueue();
    expect(cached).toEqual([persistedJob]);
    expect(readCachedProcessingQueueTotal(cached)).toBe(1);
  });

  it("drops malformed cached jobs", () => {
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([{ id: "not-a-job" }, persistedJob]),
    );

    expect(readProcessingQueue()).toEqual([persistedJob]);
  });

  it("retries a paginated load when the server snapshot changes", async () => {
    const queryClient = createQueryClient();
    const secondJob = jobRecord({ id: "f".repeat(32) });
    vi.mocked(getProcessingJobs)
      .mockResolvedValueOnce({
        total: 2,
        jobs: [persistedJob],
        snapshot_version: "first",
      })
      .mockResolvedValueOnce({
        total: 2,
        jobs: [secondJob],
        snapshot_version: "changed",
      })
      .mockResolvedValueOnce({
        total: 2,
        jobs: [persistedJob],
        snapshot_version: "stable",
      })
      .mockResolvedValueOnce({
        total: 2,
        jobs: [secondJob],
        snapshot_version: "stable",
      });

    await expect(getProcessingQueueExtent(queryClient)).resolves.toEqual({
      total: 2,
      jobs: [persistedJob, secondJob],
      snapshot_version: "stable",
    });
    expect(getProcessingJobs).toHaveBeenNthCalledWith(1, 0);
    expect(getProcessingJobs).toHaveBeenNthCalledWith(2, 1);
    expect(getProcessingJobs).toHaveBeenNthCalledWith(3, 0);
    expect(getProcessingJobs).toHaveBeenNthCalledWith(4, 1);
    expect(queryClient.getQueryData(jobQueryKeys.processingPage(0))).toEqual({
      total: 2,
      jobs: [persistedJob],
      snapshot_version: "stable",
    });
  });
});
