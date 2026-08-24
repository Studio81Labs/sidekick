import { describe, expect, it } from "vitest";

import {
  analyzerWorkflowReducer,
  initialAnalyzerWorkflowState,
} from "./useAnalyzerWorkflow";

describe("analyzer workflow reducer", () => {
  it("marks job attention without copying identical state", () => {
    const marked = analyzerWorkflowReducer(initialAnalyzerWorkflowState, {
      type: "job-attention-marked",
      jobId: "job-1",
      message: "Review parser warnings",
    });

    expect(marked.attentionByJobId).toEqual({
      "job-1": "Review parser warnings",
    });
    expect(
      analyzerWorkflowReducer(marked, {
        type: "job-attention-marked",
        jobId: "job-1",
        message: "Review parser warnings",
      }),
    ).toBe(marked);
  });

  it("clears only matching attention entries", () => {
    const marked = {
      ...initialAnalyzerWorkflowState,
      attentionByJobId: {
        "job-1": "Review parser warnings",
        "job-2": "Recommendation failed",
      },
    };

    expect(
      analyzerWorkflowReducer(marked, {
        type: "job-attention-cleared",
        jobIds: ["job-1", "missing-job"],
      }),
    ).toEqual({
      ...initialAnalyzerWorkflowState,
      attentionByJobId: {
        "job-2": "Recommendation failed",
      },
    });
    expect(
      analyzerWorkflowReducer(marked, {
        type: "job-attention-cleared",
        jobIds: ["missing-job"],
      }),
    ).toBe(marked);
  });

  it("tracks queue progress, derives abort state, and finishes cleanly", () => {
    const progress = {
      aborting: false,
      completed: 2,
      currentFile: "third.png",
      currentIndex: 3,
      failed: 1,
      skipped: 0,
      total: 5,
    };
    const started = analyzerWorkflowReducer(initialAnalyzerWorkflowState, {
      type: "queue-progress-updated",
      progress,
    });
    const aborting = analyzerWorkflowReducer(started, {
      type: "queue-abort-requested",
    });

    expect(aborting.queueProgress).toEqual({
      ...progress,
      aborting: true,
      skipped: 3,
    });
    expect(
      analyzerWorkflowReducer(aborting, {
        type: "queue-abort-requested",
      }),
    ).toBe(aborting);
    expect(
      analyzerWorkflowReducer(aborting, {
        type: "queue-processing-finished",
      }),
    ).toEqual(initialAnalyzerWorkflowState);
    expect(
      analyzerWorkflowReducer(initialAnalyzerWorkflowState, {
        type: "queue-processing-finished",
      }),
    ).toBe(initialAnalyzerWorkflowState);
  });

  it("increments recovery requests independently", () => {
    const processingRequested = analyzerWorkflowReducer(
      initialAnalyzerWorkflowState,
      { type: "processing-recovery-requested" },
    );
    const leaseRequested = analyzerWorkflowReducer(processingRequested, {
      type: "mutation-lease-revalidation-requested",
    });

    expect(processingRequested.recoveryRequests).toEqual({
      mutationLease: 0,
      processing: 1,
    });
    expect(processingRequested.recoveryPhases.processing).toBe("requested");
    expect(leaseRequested.recoveryRequests).toEqual({
      mutationLease: 1,
      processing: 1,
    });
    expect(leaseRequested.recoveryPhases).toEqual({
      mutationLease: "requested",
      processing: "requested",
    });
    expect(leaseRequested.attentionByJobId).toBe(
      processingRequested.attentionByJobId,
    );
    expect(leaseRequested.queueProgress).toBe(
      processingRequested.queueProgress,
    );
  });

  it("tracks recovery lifecycle phases without changing request generations", () => {
    const requested = analyzerWorkflowReducer(initialAnalyzerWorkflowState, {
      type: "processing-recovery-requested",
    });
    const running = analyzerWorkflowReducer(requested, {
      type: "recovery-started",
      recovery: "processing",
    });
    const retryScheduled = analyzerWorkflowReducer(running, {
      type: "recovery-retry-scheduled",
      recovery: "processing",
    });
    const finished = analyzerWorkflowReducer(retryScheduled, {
      type: "recovery-finished",
      recovery: "processing",
    });

    expect(running.recoveryPhases.processing).toBe("running");
    expect(
      analyzerWorkflowReducer(running, {
        type: "recovery-started",
        recovery: "processing",
      }),
    ).toBe(running);
    expect(retryScheduled.recoveryPhases.processing).toBe("retry-scheduled");
    expect(finished.recoveryPhases.processing).toBe("idle");
    expect(finished.recoveryRequests).toBe(requested.recoveryRequests);
    expect(
      analyzerWorkflowReducer(finished, {
        type: "recovery-finished",
        recovery: "processing",
      }),
    ).toBe(finished);
  });
});
