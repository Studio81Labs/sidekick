import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../../app/providers/AppProviders";
import { resetApiMocks } from "../../../test/api";
import {
  systemInfoQueryOptions,
  systemQueryKeys,
  useSystemInfoQuery,
} from "./systemQueries";

afterEach(resetApiMocks);

function wrapper({ children }: { children: ReactNode }) {
  return createElement(AppProviders, null, children);
}

describe("system query definitions", () => {
  it("uses a stable, domain-owned key", () => {
    expect(systemQueryKeys.information()).toEqual(["system", "information"]);
    expect(systemInfoQueryOptions().queryKey).toEqual(
      systemQueryKeys.information(),
    );
    expect(systemInfoQueryOptions()).toMatchObject({
      refetchOnReconnect: false,
      refetchOnWindowFocus: false,
      retry: false,
      staleTime: Number.POSITIVE_INFINITY,
    });
  });

  it("cancels an in-flight system information request when its observer unmounts", async () => {
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

    const { unmount } = renderHook(() => useSystemInfoQuery(true), { wrapper });

    await waitFor(() => expect(signal).toBeDefined());
    unmount();
    await waitFor(() => expect(signal?.aborted).toBe(true));
  });
});
