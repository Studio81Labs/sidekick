import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../../app/providers/AppProviders";
import { createQueryClient } from "../../../app/providers/queryClient";
import { jobRecord } from "../../../test/analyzerHarness";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import {
  fetchJobQuery,
  jobQueryKeys,
  jobQueryOptions,
  processingJobsQueryOptions,
  useJobQuery,
} from "./jobsQueries";

afterEach(resetApiMocks);
const ADMINISTRATOR_TOKEN = "administrator-token";

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
    expect(jobQueryOptions("job-123", ADMINISTRATOR_TOKEN).queryKey).toEqual(
      jobQueryKeys.detail("job-123"),
    );
    expect(
      processingJobsQueryOptions(ADMINISTRATOR_TOKEN, 100).queryKey,
    ).toEqual(jobQueryKeys.processingPage(100));
  });

  it("keeps overlapping imperative reads independent and caches the newest", async () => {
    const queryClient = createQueryClient();
    const olderJob = jobRecord({
      id: "a".repeat(32),
      updated_at: "2026-08-24T08:00:00Z",
    });
    const newerJob = jobRecord({
      id: olderJob.id,
      updated_at: "2026-08-24T09:00:00Z",
    });
    let resolveOlder!: (response: Response) => void;
    let resolveNewer!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(
          () =>
            new Promise<Response>((resolve) => {
              resolveOlder = resolve;
            }),
        )
        .mockImplementationOnce(
          () =>
            new Promise<Response>((resolve) => {
              resolveNewer = resolve;
            }),
        ),
    );

    const olderRequest = fetchJobQuery(
      queryClient,
      olderJob.id,
      ADMINISTRATOR_TOKEN,
    );
    const newerRequest = fetchJobQuery(
      queryClient,
      newerJob.id,
      ADMINISTRATOR_TOKEN,
    );
    resolveNewer(jsonResponse(newerJob));
    await expect(newerRequest).resolves.toEqual(newerJob);
    resolveOlder(jsonResponse(olderJob));
    await expect(olderRequest).resolves.toEqual(olderJob);

    expect(queryClient.getQueryData(jobQueryKeys.detail(olderJob.id))).toEqual(
      newerJob,
    );
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

    const { unmount } = renderHook(
      () => useJobQuery("job-123", ADMINISTRATOR_TOKEN, true),
      {
        wrapper,
      },
    );

    await waitFor(() => expect(signal).toBeDefined());
    unmount();
    await waitFor(() => expect(signal?.aborted).toBe(true));
  });
});
