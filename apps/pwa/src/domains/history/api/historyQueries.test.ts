import { createElement, type PropsWithChildren } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../../app/providers/AppProviders";
import { resetApiMocks } from "../../../test/api";
import {
  historyPageQueryOptions,
  historyQueryKeys,
  useHistoryPageQuery,
} from "./historyQueries";

afterEach(resetApiMocks);
const ADMINISTRATOR_TOKEN = "administrator-token";

function wrapper({ children }: PropsWithChildren) {
  return createElement(AppProviders, null, children);
}

describe("history query adapter", () => {
  it("builds stable keys from normalized page inputs", () => {
    expect(historyQueryKeys.page(24, "  turn bluff  ", 48)).toEqual([
      "history",
      "page",
      { offset: 24, query: "turn bluff", limit: 48 },
    ]);
    expect(historyPageQueryOptions(ADMINISTRATOR_TOKEN).queryKey).toEqual([
      "history",
      "page",
      { offset: 0, query: "", limit: null },
    ]);
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
      () => useHistoryPageQuery(ADMINISTRATOR_TOKEN, 24, "river", 24),
      { wrapper },
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());

    unmount();

    await waitFor(() => expect(abortListener).toHaveBeenCalledOnce());
  });
});
