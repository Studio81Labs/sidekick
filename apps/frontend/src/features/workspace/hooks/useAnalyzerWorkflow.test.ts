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
});
