import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useAnalyzerWorkflowOwnerId } from "./useAnalyzerWorkflowOwnerId";

describe("useAnalyzerWorkflowOwnerId", () => {
  it("keeps one owner identity for the mounted workflow", () => {
    const { result, rerender } = renderHook(useAnalyzerWorkflowOwnerId);
    const ownerId = result.current;

    rerender();

    expect(ownerId).not.toBe("");
    expect(result.current).toBe(ownerId);
  });
});
