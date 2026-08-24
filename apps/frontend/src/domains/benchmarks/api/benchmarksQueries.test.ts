import { createElement, type PropsWithChildren } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../../app/providers/AppProviders";
import { resetApiMocks } from "../../../test/api";
import {
  benchmarkImportReceiptQueryOptions,
  benchmarkOverviewQueryOptions,
  benchmarkQueryKeys,
  benchmarkReportQueryOptions,
  useBenchmarkReportQuery,
} from "./benchmarksQueries";

afterEach(resetApiMocks);

function wrapper({ children }: PropsWithChildren) {
  return createElement(AppProviders, null, children);
}

describe("benchmark query adapter", () => {
  it("builds stable resource keys", () => {
    const pipeline = {
      parser_provider: "ocr_cv",
      parser_layout_profile: "fortuna_nations",
    };
    expect(benchmarkOverviewQueryOptions(pipeline).queryKey).toEqual(
      benchmarkQueryKeys.overview(pipeline),
    );
    expect(benchmarkReportQueryOptions("report-1").queryKey).toEqual([
      "benchmarks",
      "report",
      "report-1",
    ]);
    expect(benchmarkImportReceiptQueryOptions("request-1").queryKey).toEqual([
      "benchmarks",
      "import",
      "request-1",
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

    const { unmount } = renderHook(() => useBenchmarkReportQuery("report-1"), {
      wrapper,
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());

    unmount();

    await waitFor(() => expect(abortListener).toHaveBeenCalledOnce());
  });
});
