import { createElement, type PropsWithChildren } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../../app/providers/AppProviders";
import { resetApiMocks } from "../../../test/api";
import {
  normalizeTrainingProgressQuery,
  trainingProgressQueryOptions,
  trainingQueryKeys,
  useTrainingProgressQuery,
} from "./trainingQueries";

afterEach(resetApiMocks);

function wrapper({ children }: PropsWithChildren) {
  return createElement(AppProviders, null, children);
}

describe("training query adapter", () => {
  it("normalizes defaults and trimmed search into a stable key", () => {
    const normalized = normalizeTrainingProgressQuery({
      lessonQuery: "  river call  ",
      reviewStreet: "river",
    });
    expect(normalized.lessonQuery).toBe("river call");
    expect(normalized.reviewStreet).toBe("river");
    expect(normalized.reviewOrder).toBe("recent");
    expect(trainingQueryKeys.progress(normalized)).toEqual(
      trainingProgressQueryOptions(normalized).queryKey,
    );
  });

  it("keeps configured retries for hooks and disables them for compatibility reads", () => {
    expect(trainingProgressQueryOptions().retry).toBeUndefined();
    expect(trainingProgressQueryOptions({}, false).retry).toBe(false);
  });

  it("aborts the transport request when its hook unmounts", async () => {
    const abortListener = vi.fn();
    const fetchMock = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            abortListener();
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { unmount } = renderHook(
      () => useTrainingProgressQuery({ reviewStreet: "turn" }),
      { wrapper },
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());

    unmount();

    await waitFor(() => expect(abortListener).toHaveBeenCalledOnce());
  });
});
