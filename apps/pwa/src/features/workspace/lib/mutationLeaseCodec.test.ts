import { describe, expect, it } from "vitest";

import { decodePersistedMutationLease } from "./mutationLeaseCodec";

const leaseBase = { ownerId: "owner", expiresAt: 100 };

describe("mutation lease codec", () => {
  it("upgrades the legacy job lease shape", () => {
    expect(
      decodePersistedMutationLease(
        {
          ...leaseBase,
          jobId: "job-1",
          baselineUpdatedAt: "2026-08-15T00:00:00Z",
        },
        "processing",
      ),
    ).toEqual({
      ...leaseBase,
      kind: "job",
      jobId: "job-1",
      baselineUpdatedAt: "2026-08-15T00:00:00Z",
      expectsRemoval: false,
      expectedRecommendationRequestId: null,
      expectedMutation: null,
    });
  });

  it("upgrades projection upload and benchmark defaults", () => {
    expect(
      decodePersistedMutationLease(
        {
          ...leaseBase,
          kind: "projection",
          baselineJobIds: ["job-1"],
          expectedRemovalJobIds: [],
          expectedUploads: [{ requestId: "upload-1", target: "approved" }],
        },
        "processing",
      ),
    ).toEqual({
      ...leaseBase,
      kind: "projection",
      baselineJobIds: ["job-1"],
      expectedRemovalJobIds: [],
      expectedUploads: [
        {
          requestId: "upload-1",
          target: "approved",
          recommendationRequestId: null,
        },
      ],
      benchmarkImportRequestId: null,
      benchmarkImportReceiptObserved: false,
    });
  });

  it("uses scope-specific legacy archive confirmation defaults", () => {
    const archive = {
      ...leaseBase,
      kind: "archive",
      jobIds: ["job-1"],
      baselineUpdatedAt: { "job-1": "2026-08-15T00:00:00Z" },
    };

    expect(
      decodePersistedMutationLease({ ...archive }, "processing"),
    ).toMatchObject({ confirmationJobIds: ["job-1"] });
    expect(
      decodePersistedMutationLease({ ...archive }, "history"),
    ).toMatchObject({ confirmationJobIds: [] });
  });

  it("rejects projection removals outside the baseline", () => {
    expect(
      decodePersistedMutationLease(
        {
          ...leaseBase,
          kind: "projection",
          baselineJobIds: ["job-1"],
          expectedRemovalJobIds: ["job-2"],
          expectedUploads: [],
          benchmarkImportRequestId: null,
          benchmarkImportReceiptObserved: false,
        },
        "processing",
      ),
    ).toBeNull();
  });
});
