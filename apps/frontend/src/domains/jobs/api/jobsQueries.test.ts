import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../../app/providers/AppProviders";
import { resetApiMocks } from "../../../test/api";
import {
  jobQueryKeys,
  jobQueryOptions,
  processingJobsQueryOptions,
  useJobQuery,
} from "./jobsQueries";

afterEach(resetApiMocks);

function wrapper({ children }: { children: ReactNode }) {
  return createElement(AppProviders, null, children);
}

describe("job query definitions", () => {
  it("uses stable domain-owned detail and processing-page keys", () => {
    expect(jobQueryKeys.detail("job-123")).toEqual([
      "jobs",
      "detail",
      "job-123",
    ]);
    expect(jobQueryKeys.processingPage(100)).toEqual([
      "jobs",
      "processing",
      { offset: 100 },
    ]);
    expect(jobQueryOptions("job-123").queryKey).toEqual(
      jobQueryKeys.detail("job-123"),
    );
    expect(processingJobsQueryOptions(100).queryKey).toEqual(
      jobQueryKeys.processingPage(100),
    );
    expect(jobQueryOptions("job-123").retry).toBeUndefined();
    expect(jobQueryOptions("job-123", false).retry).toBe(false);
    expect(processingJobsQueryOptions(100).retry).toBeUndefined();
    expect(processingJobsQueryOptions(100, false).retry).toBe(false);
  });

  it("cancels an in-flight job request when its observer unmounts", async () => {
    let signal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        (_url: string, init?: RequestInit) =>
          new Promise((_, reject) => {
            signal = init?.signal ?? undefined;
            signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          }),
      ),
    );

    const { unmount } = renderHook(() => useJobQuery("job-123", true), {
      wrapper,
    });

    await waitFor(() => expect(signal).toBeDefined());
    unmount();
    await waitFor(() => expect(signal?.aborted).toBe(true));
  });
});
