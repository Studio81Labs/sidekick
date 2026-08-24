import { act, renderHook } from "@testing-library/react";
import { createElement, type PropsWithChildren } from "react";
import { describe, expect, it } from "vitest";

import {
  AnalyzerWorkflowProvider,
  useAnalyzerActiveSelection,
} from "./useAnalyzerWorkflow";

function wrapper({ children }: PropsWithChildren) {
  return createElement(AnalyzerWorkflowProvider, null, children);
}

describe("analyzer workflow context", () => {
  it("selects and clears the active job through its command hook", () => {
    const { result } = renderHook(() => useAnalyzerActiveSelection(), {
      wrapper,
    });

    expect(result.current.activeJobId).toBeNull();

    act(() => result.current.selectActiveJob("job-1"));
    expect(result.current.activeJobId).toBe("job-1");

    act(() => result.current.selectActiveJob(null));
    expect(result.current.activeJobId).toBeNull();
  });
});
