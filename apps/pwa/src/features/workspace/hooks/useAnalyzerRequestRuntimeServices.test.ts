import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useAnalyzerRequestRuntimeServices } from "./useAnalyzerRequestRuntimeServices";

describe("analyzer request runtime services", () => {
  it("keeps request handles stable across renders", () => {
    const { result, rerender } = renderHook(() =>
      useAnalyzerRequestRuntimeServices(),
    );
    const initialServices = result.current;
    const controller = new AbortController();

    expect(initialServices.activeRecommendationRequestsRef.current).toEqual(
      new Map(),
    );
    expect(initialServices.appMountedRef.current).toBe(true);
    expect(initialServices.historySearchRequestRef.current).toBe(0);
    expect(initialServices.queueAbortControllerRef.current).toBeNull();
    expect(initialServices.queueAbortRequestedRef.current).toBe(false);

    initialServices.queueAbortControllerRef.current = controller;
    initialServices.historySearchRequestRef.current = 2;
    rerender();

    expect(result.current.queueAbortControllerRef).toBe(
      initialServices.queueAbortControllerRef,
    );
    expect(result.current.queueAbortControllerRef.current).toBe(controller);
    expect(result.current.historySearchRequestRef).toBe(
      initialServices.historySearchRequestRef,
    );
    expect(result.current.historySearchRequestRef.current).toBe(2);
  });
});
