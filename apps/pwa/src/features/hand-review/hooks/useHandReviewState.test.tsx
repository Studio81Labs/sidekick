import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiResponseError } from "../../../shared/api/core";
import type { JobRecord } from "../../../shared/types/jobs";
import { useHandReviewState } from "./useHandReviewState";

const ADMINISTRATOR_TOKEN = "administrator-token";

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function reviewOptions(
  jobs: JobRecord[],
  activeJobId = jobs[0]?.id ?? null,
  administratorToken = ADMINISTRATOR_TOKEN,
) {
  return {
    activeJobId,
    administratorToken,
    jobs,
    onActiveJobChange: vi.fn(),
    onAdministrativeDenial: vi.fn(() => false),
    onError: vi.fn(),
  };
}

function stubObjectUrls() {
  let count = 0;
  const createObjectURL = vi.fn(() => `blob:review-${++count}`);
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
  return { revokeObjectURL };
}

function imageJob(id: string, imageFilename = `${id}.png`) {
  return {
    id,
    status: "parsed",
    upload_request_id: null,
    original_filename: `${id}.png`,
    image_filename: imageFilename,
    parser_provider: "mock",
    parser_result: {
      state: {
        hero_cards: [
          { rank: "A", suit: "hearts" },
          { rank: "K", suit: "diamonds" },
        ],
        board_cards: [
          { rank: "Q", suit: "spades" },
          { rank: "J", suit: "clubs" },
          { rank: "2", suit: "hearts" },
        ],
        pot_size: 12.5,
        current_bet: 2.5,
        hero_stack: 97.5,
        effective_stack: 96,
        players_in_hand: 3,
        hero_position: "button",
        preflop_opener_position: null,
        preflop_open_size: null,
        street: "flop",
        facing_action: "bet",
        action_context: "Cutoff bet 2.5 into 12.5",
      },
      confidences: {},
      warnings: [],
      raw: {},
    },
    parser_auto_approval_eligible: true,
    approved_state: null,
    benchmark_included: false,
    archived_at: null,
    error: null,
    created_at: "2026-09-09T00:00:00Z",
    updated_at: "2026-09-09T00:00:00Z",
  } satisfies JobRecord;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("useHandReviewState screenshot loading", () => {
  it("keeps the preview and approval bound to the active image and revokes stale URLs", async () => {
    const firstImage = deferred<Response>();
    const secondImage = deferred<Response>();
    const first = imageJob("first");
    const second = imageJob("second");
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/jobs/first/image")) return firstImage.promise;
      if (url.endsWith("/jobs/second/image")) return secondImage.promise;
      throw new Error(`Unexpected image request: ${url}`);
    });
    vi.stubGlobal("fetch", fetch);
    const { revokeObjectURL } = stubObjectUrls();
    const options = reviewOptions([first, second]);
    const { result, rerender, unmount } = renderHook(
      (props) => useHandReviewState(props),
      { initialProps: options },
    );

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    act(() => result.current.alignWorkspaceToJob(first));
    expect(result.current.screenshotStatus).toBe("loading");
    expect(result.current.screenshotUrl).toBeNull();
    expect(result.current.canApprove).toBe(false);

    rerender({ ...options, activeJobId: second.id });
    act(() => result.current.alignWorkspaceToJob(second));

    expect(result.current.job?.id).toBe(second.id);
    expect(result.current.screenshotStatus).toBe("loading");
    expect(result.current.screenshotUrl).toBeNull();
    expect(result.current.canApprove).toBe(false);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));

    await act(async () => {
      secondImage.resolve(new Response("second image"));
    });
    await waitFor(() =>
      expect(result.current.screenshotUrl).toBe("blob:review-1"),
    );
    expect(result.current.canApprove).toBe(true);

    await act(async () => {
      firstImage.resolve(new Response("first image"));
    });
    await waitFor(() =>
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:review-2"),
    );
    expect(result.current.screenshotUrl).toBe("blob:review-1");

    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:review-1");
  });

  it("ignores a stale authorization denial after the active job changes", async () => {
    const firstImage = deferred<Response>();
    const secondImage = deferred<Response>();
    const first = imageJob("first");
    const second = imageJob("second");
    const onAdministrativeDenial = vi.fn(
      (failure: unknown) =>
        failure instanceof ApiResponseError && failure.status === 401,
    );
    const fetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/jobs/first/image")) return firstImage.promise;
      if (url.endsWith("/jobs/second/image")) return secondImage.promise;
      throw new Error(`Unexpected image request: ${url}`);
    });
    vi.stubGlobal("fetch", fetch);
    stubObjectUrls();
    const options = {
      ...reviewOptions([first, second]),
      onAdministrativeDenial,
    };
    const { result, rerender } = renderHook(
      (props) => useHandReviewState(props),
      { initialProps: options },
    );

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    rerender({ ...options, activeJobId: second.id });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));

    await act(async () => {
      firstImage.resolve(
        new Response(JSON.stringify({ detail: "denied" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      );
      secondImage.resolve(new Response("second image"));
    });
    await waitFor(() => expect(result.current.screenshotStatus).toBe("loaded"));
    expect(onAdministrativeDenial).not.toHaveBeenCalled();
  });

  it("reports current authorization denials and keeps non-auth failures retryable", async () => {
    const job = imageJob("current");
    const firstImage = deferred<Response>();
    const secondImage = deferred<Response>();
    const onAdministrativeDenial = vi.fn(
      (failure: unknown) =>
        failure instanceof ApiResponseError && failure.status === 403,
    );
    const fetch = vi
      .fn<(input: RequestInfo | URL) => Promise<Response>>()
      .mockReturnValueOnce(firstImage.promise)
      .mockRejectedValueOnce(new TypeError("Connection lost"))
      .mockReturnValueOnce(secondImage.promise);
    vi.stubGlobal("fetch", fetch);
    stubObjectUrls();
    const options = {
      ...reviewOptions([job]),
      onAdministrativeDenial,
    };
    const { result, rerender } = renderHook(
      (props) => useHandReviewState(props),
      { initialProps: options },
    );

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    act(() => result.current.alignWorkspaceToJob(job));
    await act(async () => {
      firstImage.resolve(
        new Response(JSON.stringify({ detail: "denied" }), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    await waitFor(() =>
      expect(onAdministrativeDenial).toHaveBeenCalledTimes(1),
    );
    expect(result.current.screenshotStatus).toBe("loading");

    rerender({ ...options, administratorToken: "replacement-token" });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(result.current.screenshotStatus).toBe("error"));
    expect(result.current.screenshotError).toBe("Connection lost");
    expect(result.current.canApprove).toBe(false);

    act(() => result.current.retryScreenshot());
    expect(result.current.screenshotStatus).toBe("loading");
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
    await act(async () => {
      secondImage.resolve(new Response("replacement image"));
    });
    await waitFor(() => expect(result.current.screenshotStatus).toBe("loaded"));
    expect(result.current.canApprove).toBe(true);
  });

  it("keeps deliberately source-less jobs approvable without fetching an image", () => {
    const job = imageJob("source-less", "");
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    stubObjectUrls();

    const { result } = renderHook(() =>
      useHandReviewState(reviewOptions([job])),
    );

    act(() => result.current.alignWorkspaceToJob(job));

    expect(result.current.screenshotStatus).toBe("missing");
    expect(result.current.canApprove).toBe(true);
    expect(fetch).not.toHaveBeenCalled();
  });
});
