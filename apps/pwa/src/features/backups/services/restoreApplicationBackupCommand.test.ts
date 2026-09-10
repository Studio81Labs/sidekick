import { afterEach, describe, expect, it, vi } from "vitest";

import { createQueryClient } from "../../../app/providers/queryClient";
import { benchmarkQueryKeys } from "../../../domains/benchmarks/api/benchmarksQueries";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import { systemQueryKeys } from "../../../domains/system/api/systemQueries";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { supersedeQueryAccessGeneration } from "../../../shared/api/queryCache";
import { restoreApplicationBackupCommand } from "./restoreApplicationBackupCommand";

afterEach(resetApiMocks);

const restoreResult = {
  imported_jobs: 1,
  reused_jobs: 2,
  imported_benchmark_reports: 1,
  reused_benchmark_reports: 0,
  total_jobs: 3,
  total_benchmark_reports: 1,
};

function seedWorkspaceCaches() {
  const queryClient = createQueryClient();
  const affected = [
    jobQueryKeys.processingPage(0),
    historyQueryKeys.page(),
    benchmarkQueryKeys.overview(),
    benchmarkQueryKeys.report("report-1"),
  ] as const;
  affected.forEach((queryKey) => queryClient.setQueryData(queryKey, {}));
  const systemKey = systemQueryKeys.information();
  const system = { status: "ok" };
  queryClient.setQueryData(systemKey, system);
  return { queryClient, affected, systemKey, system };
}

describe("restore application backup command", () => {
  it("returns the receipt and removes all restored workspace query families", async () => {
    const seeded = seedWorkspaceCaches();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(restoreResult));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["backup"], "backup.zip");

    const outcome = await restoreApplicationBackupCommand(seeded.queryClient, {
      administratorToken: "administrator-token",
      file,
    });

    expect(outcome).toEqual({
      result: restoreResult,
      cache: {
        removed: [
          jobQueryKeys.all,
          historyQueryKeys.all,
          benchmarkQueryKeys.all,
        ],
      },
    });
    seeded.affected.forEach((queryKey) =>
      expect(seeded.queryClient.getQueryState(queryKey)).toBeUndefined(),
    );
    expect(seeded.queryClient.getQueryData(seeded.systemKey)).toBe(
      seeded.system,
    );
    expect(fetchMock.mock.calls[0]?.[1]?.headers).toEqual({
      Authorization: "Bearer administrator-token",
    });
    const form = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(form.get("file")).toBe(file);
  });

  it("leaves caches untouched after failure and supports an idempotent retry", async () => {
    const seeded = seedWorkspaceCaches();
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValueOnce(jsonResponse(restoreResult));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["backup"], "backup.zip");

    await expect(
      restoreApplicationBackupCommand(seeded.queryClient, {
        administratorToken: "administrator-token",
        file,
      }),
    ).rejects.toThrow("offline");
    seeded.affected.forEach((queryKey) =>
      expect(seeded.queryClient.getQueryData(queryKey)).toEqual({}),
    );

    await expect(
      restoreApplicationBackupCommand(seeded.queryClient, {
        administratorToken: "administrator-token",
        file,
      }),
    ).resolves.toMatchObject({ result: restoreResult });
    seeded.affected.forEach((queryKey) =>
      expect(seeded.queryClient.getQueryState(queryKey)).toBeUndefined(),
    );
  });

  it("does not cancel current-session queries after a stale restore completes", async () => {
    const seeded = seedWorkspaceCaches();
    let resolveRestore!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            resolveRestore = resolve;
          }),
      ),
    );
    const cancelQueries = vi.spyOn(seeded.queryClient, "cancelQueries");

    const restoring = restoreApplicationBackupCommand(seeded.queryClient, {
      administratorToken: "administrator-token",
      file: new File(["backup"], "backup.zip"),
    });
    supersedeQueryAccessGeneration(seeded.queryClient);
    resolveRestore(jsonResponse(restoreResult));

    await expect(restoring).rejects.toThrow(
      "Administrator access changed before this operation completed",
    );
    expect(cancelQueries).not.toHaveBeenCalled();
    seeded.affected.forEach((queryKey) =>
      expect(seeded.queryClient.getQueryData(queryKey)).toEqual({}),
    );
  });
});
