import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { JobRecord } from "../../shared/types";
import { analyzerRouteState } from "./analyzerRouteState";
import {
  type AnalyzerRouteRestoreOptions,
  useAnalyzerRouteRestore,
} from "./useAnalyzerRouteRestore";

function job(id: string): JobRecord {
  return { id } as JobRecord;
}

function options(
  overrides: Partial<AnalyzerRouteRestoreOptions> = {},
): AnalyzerRouteRestoreOptions {
  return {
    activateJob: vi.fn(),
    activeJobId: null,
    closeBenchmarks: vi.fn(),
    closeTraining: vi.fn(),
    jobs: [],
    loadJob: vi.fn(async (jobId) => job(jobId)),
    onError: vi.fn(),
    onJobUnavailable: vi.fn(),
    openBenchmarks: vi.fn(),
    openTraining: vi.fn(),
    route: analyzerRouteState("workspace"),
    ...overrides,
  };
}

describe("useAnalyzerRouteRestore", () => {
  it("opens only the durable training surface", () => {
    const current = options({ route: analyzerRouteState("training") });
    renderHook(() => useAnalyzerRouteRestore(current));

    expect(current.closeBenchmarks).toHaveBeenCalledOnce();
    expect(current.closeTraining).not.toHaveBeenCalled();
    expect(current.openTraining).toHaveBeenCalledOnce();
    expect(current.openBenchmarks).not.toHaveBeenCalled();
  });

  it("opens only the durable benchmark surface", () => {
    const current = options({ route: analyzerRouteState("benchmarks") });
    renderHook(() => useAnalyzerRouteRestore(current));

    expect(current.closeTraining).toHaveBeenCalledOnce();
    expect(current.closeBenchmarks).not.toHaveBeenCalled();
    expect(current.openBenchmarks).toHaveBeenCalledOnce();
    expect(current.openTraining).not.toHaveBeenCalled();
  });

  it("activates a cached durable job without loading it", () => {
    const cachedJob = job("job-123");
    const current = options({
      jobs: [cachedJob],
      route: analyzerRouteState("job", cachedJob.id),
    });
    renderHook(() => useAnalyzerRouteRestore(current));

    expect(current.activateJob).toHaveBeenCalledWith(cachedJob);
    expect(current.loadJob).not.toHaveBeenCalled();
  });

  it("loads and activates a missing durable job", async () => {
    const loadedJob = job("job-123");
    const current = options({
      loadJob: vi.fn().mockResolvedValue(loadedJob),
      route: analyzerRouteState("job", loadedJob.id),
    });
    renderHook(() => useAnalyzerRouteRestore(current));

    await waitFor(() =>
      expect(current.activateJob).toHaveBeenCalledWith(loadedJob),
    );
    expect(current.loadJob).toHaveBeenCalledWith(loadedJob.id);
  });

  it("surfaces a durable job load failure", async () => {
    const failure = new Error("missing job");
    const current = options({
      loadJob: vi.fn().mockRejectedValue(failure),
      route: analyzerRouteState("job", "job-123"),
    });
    renderHook(() => useAnalyzerRouteRestore(current));

    await waitFor(() => expect(current.onError).toHaveBeenCalledWith(failure));
    expect(current.onJobUnavailable).toHaveBeenCalledOnce();
    expect(current.activateJob).not.toHaveBeenCalled();
  });
});
