import { describe, expect, it } from "vitest";

import { jobRecord } from "../../../test/analyzerHarness";
import {
  jobMutationExpectationReached,
  projectionMutationLeaseTargetReached,
  projectionMutationTarget,
} from "./mutationLeaseExpectations";
import type { ProjectionMutationLease } from "./mutationLeaseTypes";

describe("mutation lease expectations", () => {
  it("derives the upload target from the enabled automation steps", () => {
    expect(projectionMutationTarget(false, true, true)).toBe("parsed");
    expect(projectionMutationTarget(true, false, true)).toBe("parsed");
    expect(projectionMutationTarget(true, true, false)).toBe("approved");
    expect(projectionMutationTarget(true, true, true)).toBe("recommended");
  });

  it("matches persisted screenshot metadata exactly and in order", () => {
    const job = jobRecord({
      title: "River bluff",
      notes: "Review blockers",
      tags: ["river", "bluff"],
    });

    expect(
      jobMutationExpectationReached(job, {
        kind: "metadata",
        title: "River bluff",
        notes: "Review blockers",
        tags: ["river", "bluff"],
      }),
    ).toBe(true);
    expect(
      jobMutationExpectationReached(job, {
        kind: "metadata",
        title: "River bluff",
        notes: "Review blockers",
        tags: ["bluff", "river"],
      }),
    ).toBe(false);
  });

  it("matches an upload by request id before checking its target", () => {
    const lease: ProjectionMutationLease = {
      kind: "projection",
      ownerId: "owner",
      expiresAt: 100,
      baselineJobIds: [],
      expectedRemovalJobIds: [],
      benchmarkImportRequestId: null,
      benchmarkImportReceiptObserved: false,
      expectedUploads: [
        {
          requestId: "upload-1",
          target: "approved",
          recommendationRequestId: null,
        },
      ],
    };

    expect(
      projectionMutationLeaseTargetReached(
        lease,
        jobRecord({ upload_request_id: "upload-1", approved_state: null }),
      ),
    ).toBe(false);
    expect(
      projectionMutationLeaseTargetReached(
        lease,
        jobRecord({ upload_request_id: "other" }),
      ),
    ).toBeNull();
  });
});
