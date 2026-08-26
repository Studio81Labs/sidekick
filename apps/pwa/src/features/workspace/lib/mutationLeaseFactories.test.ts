import { beforeEach, describe, expect, it, vi } from "vitest";

import { jobRecord } from "../../../test/analyzerHarness";
import {
  startArchiveMutationLease,
  startProjectionMutationLease,
} from "./mutationLeaseFactories";

describe("mutation lease factories", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.useRealTimers();
  });

  it("records projection baselines, removals, uploads, and benchmark identity", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-15T00:00:00Z"));
    const baseline = jobRecord({ id: "job-1" });

    expect(
      startProjectionMutationLease(
        "processing",
        "owner",
        [baseline],
        [
          {
            requestId: "upload-1",
            target: "recommended",
            recommendationRequestId: "recommendation-1",
          },
        ],
        ["job-1"],
        "benchmark-1",
      ),
    ).toMatchObject({
      kind: "projection",
      baselineJobIds: ["job-1"],
      expectedRemovalJobIds: ["job-1"],
      benchmarkImportRequestId: "benchmark-1",
      expectedUploads: [{ requestId: "upload-1", target: "recommended" }],
    });
  });

  it("requires processing-side confirmation only for jobs outside the queue", () => {
    const queued = jobRecord({ id: "job-1" });
    const historyOnly = jobRecord({ id: "job-2" });

    expect(
      startArchiveMutationLease(
        "processing",
        "owner",
        [queued, historyOnly],
        new Set(["job-1"]),
      ),
    ).toMatchObject({ confirmationJobIds: ["job-2"] });
  });
});
