import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useAnalyzerRecoveryRuntimeServices } from "./useAnalyzerRecoveryRuntimeServices";

describe("analyzer recovery runtime services", () => {
  it("keeps recovery handles stable across renders", () => {
    const { result, rerender } = renderHook(() =>
      useAnalyzerRecoveryRuntimeServices(),
    );
    const initialServices = result.current;

    expect(initialServices.historyJobRestoreActiveIdsRef.current).toEqual(
      new Set(),
    );
    expect(initialServices.historyJobRestoreIdsRef.current).toEqual(new Set());
    expect(initialServices.historyJobRestoreRetryTimerRef.current).toBeNull();
    expect(initialServices.processingRestorePromiseRef.current).toBeNull();
    expect(initialServices.processingStorageRestoreScheduledRef.current).toBe(
      false,
    );

    rerender();

    for (const key of Object.keys(initialServices) as Array<
      keyof typeof initialServices
    >) {
      expect(result.current[key]).toBe(initialServices[key]);
    }
  });
});
