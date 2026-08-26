import { createElement, type PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  benchmarkOverviewForJob,
  deferredResponse,
  fetchMock,
  jsonResponse,
} from "../../../test/analyzerHarness";
import type { BenchmarkOverview } from "../../../shared/types/benchmarks";
import { useBenchmarkReportState } from "./useBenchmarkReportState";

function wrapper({ children }: PropsWithChildren) {
  return createElement(AppProviders, null, children);
}

function overview(jobId: string): BenchmarkOverview {
  return benchmarkOverviewForJob(
    jobId,
    `${jobId}.png`,
  ) as unknown as BenchmarkOverview;
}

describe("benchmark report state", () => {
  beforeEach(() => {
    fetchMock().mockReset();
  });

  it("loads and selects the latest benchmark report", async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse(overview("job-1")));
    const onError = vi.fn();
    const { result } = renderHook(
      () => useBenchmarkReportState({ dialogOpen: false, onError }),
      { wrapper },
    );

    act(() => result.current.loadOverview(null));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.report?.id).toBe("benchmark-job-1");
    expect(result.current.recentReports).toHaveLength(1);
    expect(onError).not.toHaveBeenCalled();
  });

  it("ignores an older overview response after a newer request wins", async () => {
    const first = deferredResponse();
    fetchMock()
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce(jsonResponse(overview("job-2")));
    const { result } = renderHook(
      () => useBenchmarkReportState({ dialogOpen: false, onError: vi.fn() }),
      { wrapper },
    );

    act(() => {
      result.current.loadOverview(null);
      result.current.loadOverview(null);
    });
    await waitFor(() =>
      expect(result.current.report?.id).toBe("benchmark-job-2"),
    );
    await act(async () => {
      first.resolve(jsonResponse(overview("job-1")));
      await first.promise;
    });

    expect(result.current.report?.id).toBe("benchmark-job-2");
  });

  it("cancels pending overview state updates when the dialog closes", async () => {
    const pending = deferredResponse();
    fetchMock().mockImplementationOnce(() => pending.promise);
    const { result } = renderHook(
      () => useBenchmarkReportState({ dialogOpen: false, onError: vi.fn() }),
      { wrapper },
    );

    act(() => {
      result.current.loadOverview(null);
      result.current.cancelLoads();
    });
    await act(async () => {
      pending.resolve(jsonResponse(overview("job-1")));
      await pending.promise;
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.overview).toBeNull();
  });

  it("applies a completed report to an empty catalog", () => {
    const latestReport = overview("job-1").latest_report;
    expect(latestReport).not.toBeNull();
    const { result } = renderHook(
      () => useBenchmarkReportState({ dialogOpen: false, onError: vi.fn() }),
      { wrapper },
    );

    act(() => result.current.applyReport(latestReport!, true));

    expect(result.current.report?.id).toBe("benchmark-job-1");
    expect(result.current.overview?.included_cases).toBe(1);
    expect(result.current.recentReports[0]?.id).toBe("benchmark-job-1");
  });
});
import { AppProviders } from "../../../app/providers/AppProviders";
