import { act, renderHook } from "@testing-library/react";
import { createElement, type PropsWithChildren } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  AnalyzerWorkflowProvider,
  useAnalyzerActiveSelection,
  useAnalyzerMutationLeases,
  useAnalyzerQueueWorkflow,
  useAnalyzerRecoveryWorkflow,
} from "./useAnalyzerWorkflow";
import { browserAnalyzerWorkflowProjections } from "../services/browserAnalyzerWorkflowProjections";

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

  it("seeds and updates mutation leases through focused commands", () => {
    const lease = {
      kind: "job" as const,
      ownerId: "owner-1",
      expiresAt: 100,
      jobId: "job-1",
      baselineUpdatedAt: "2026-08-24T00:00:00Z",
      expectsRemoval: false,
      expectedRecommendationRequestId: null,
      expectedMutation: null,
    };
    const mutationLeaseWrapper = ({ children }: PropsWithChildren) =>
      createElement(
        AnalyzerWorkflowProvider,
        {
          initialMutationLeases: {
            processing: lease,
            history: null,
          },
        },
        children,
      );
    const { result } = renderHook(() => useAnalyzerMutationLeases(), {
      wrapper: mutationLeaseWrapper,
    });

    expect(result.current.mutationLeases.processing).toBe(lease);

    act(() => result.current.setMutationLease("processing", null));
    expect(result.current.mutationLeases).toEqual({
      processing: null,
      history: null,
    });
  });

  it("claims initial mutation leases through injected projections", () => {
    const lease = {
      kind: "job" as const,
      ownerId: "owner-2",
      expiresAt: 100,
      jobId: "job-2",
      baselineUpdatedAt: "2026-08-24T00:00:00Z",
      expectsRemoval: false,
      expectedRecommendationRequestId: null,
      expectedMutation: null,
    };
    const claimPersistedMutationLease = vi.fn((scope: string) =>
      scope === "processing" ? lease : null,
    );
    const projectionWrapper = ({ children }: PropsWithChildren) =>
      createElement(
        AnalyzerWorkflowProvider,
        {
          mutationOwnerId: "owner-2",
          projections: {
            ...browserAnalyzerWorkflowProjections,
            claimPersistedMutationLease,
          },
        },
        children,
      );
    const { result } = renderHook(() => useAnalyzerMutationLeases(), {
      wrapper: projectionWrapper,
    });

    expect(claimPersistedMutationLease).toHaveBeenNthCalledWith(
      1,
      "processing",
      "owner-2",
    );
    expect(claimPersistedMutationLease).toHaveBeenNthCalledWith(
      2,
      "history",
      "owner-2",
    );
    expect(result.current.mutationLeases).toEqual({
      processing: lease,
      history: null,
    });
  });

  it("advances recovery requests and phases through focused commands", () => {
    const { result } = renderHook(() => useAnalyzerRecoveryWorkflow(), {
      wrapper,
    });

    expect(result.current.mutationLeaseRestoreRequest).toBe(0);
    expect(result.current.processingRestoreRequest).toBe(0);
    expect(result.current.recoveryPhases).toEqual({
      mutationLease: "idle",
      processing: "idle",
    });

    act(() => {
      result.current.requestMutationLeaseRevalidation();
      result.current.requestProcessingRecovery();
    });
    expect(result.current.mutationLeaseRestoreRequest).toBe(1);
    expect(result.current.processingRestoreRequest).toBe(1);
    expect(result.current.recoveryPhases).toEqual({
      mutationLease: "requested",
      processing: "requested",
    });

    act(() => {
      result.current.scheduleRecoveryRetry("mutationLease");
      result.current.startRecovery("processing");
    });
    expect(result.current.recoveryPhases).toEqual({
      mutationLease: "retry-scheduled",
      processing: "running",
    });

    act(() => {
      result.current.finishRecovery("mutationLease");
      result.current.finishRecovery("processing");
    });
    expect(result.current.recoveryPhases).toEqual({
      mutationLease: "idle",
      processing: "idle",
    });
  });
});
