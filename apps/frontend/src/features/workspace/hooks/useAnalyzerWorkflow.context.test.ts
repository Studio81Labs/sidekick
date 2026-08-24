import { act, renderHook } from "@testing-library/react";
import { createElement, type PropsWithChildren } from "react";
import { describe, expect, it } from "vitest";

import {
  AnalyzerWorkflowProvider,
  useAnalyzerActiveSelection,
  useAnalyzerQueueWorkflow,
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

  it("manages queue progress and attention through focused commands", () => {
    const { result } = renderHook(() => useAnalyzerQueueWorkflow(), {
      wrapper,
    });
    const progress = {
      aborting: false,
      completed: 1,
      currentFile: "turn.png",
      currentIndex: 2,
      failed: 0,
      skipped: 0,
      total: 3,
    };

    act(() => {
      result.current.markJobAttention("job-1", "Review parser warnings");
      result.current.setQueueProgress(progress);
    });
    expect(result.current.attentionByJobId).toEqual({
      "job-1": "Review parser warnings",
    });
    expect(result.current.queueProgress).toEqual(progress);

    act(() => result.current.requestQueueAbort());
    expect(result.current.queueProgress).toEqual({
      ...progress,
      aborting: true,
      skipped: 2,
    });

    act(() => {
      result.current.clearJobAttention(["job-1"]);
      result.current.setQueueProgress(null);
    });
    expect(result.current.attentionByJobId).toEqual({});
    expect(result.current.queueProgress).toBeNull();
  });
});
