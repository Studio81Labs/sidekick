import { beforeEach, describe, expect, it } from "vitest";

import { jobRecord } from "../../../test/analyzerHarness";
import { projectionMutationTargetReached } from "./mutationLeaseExpectations";
import { startPersistedMutationLease } from "./mutationLeaseFactories";
import {
  PROCESSING_MUTATION_LEASE_KEY,
  claimPersistedMutationLease,
  clearPersistedMutationLease,
  readPersistedMutationLease,
} from "./mutationLeaseStorage";

describe("workspace mutation leases", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("stores, claims, and clears a persisted job mutation lease", () => {
    const lease = startPersistedMutationLease(
      "processing",
      "first-owner",
      jobRecord({ id: "d".repeat(32) }),
      {
        kind: "metadata",
        title: "Study spot",
        notes: null,
        tags: ["river"],
      },
    );

    expect(lease?.ownerId).toBe("first-owner");
    expect(
      claimPersistedMutationLease("processing", "next-owner")?.ownerId,
    ).toBe("next-owner");

    clearPersistedMutationLease("processing", "first-owner");
    expect(readPersistedMutationLease("processing")).not.toBeNull();
    clearPersistedMutationLease("processing", "next-owner");
    expect(readPersistedMutationLease("processing")).toBeNull();
  });

  it("removes malformed persisted leases", () => {
    window.sessionStorage.setItem(
      PROCESSING_MUTATION_LEASE_KEY,
      JSON.stringify({ kind: "job", ownerId: 12 }),
    );

    expect(readPersistedMutationLease("processing")).toBeNull();
    expect(
      window.sessionStorage.getItem(PROCESSING_MUTATION_LEASE_KEY),
    ).toBeNull();
  });

  it("requires the matching recommendation request to settle a pending result", () => {
    const job = jobRecord({
      status: "approved",
      recommendation_pending: false,
      recommendation_request_id: "request-2",
    });

    expect(
      projectionMutationTargetReached(job, "recommended", "request-1"),
    ).toBe(false);
    expect(
      projectionMutationTargetReached(job, "recommended", "request-2"),
    ).toBe(true);
  });
});
