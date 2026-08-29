import { beforeEach, describe, expect, it } from "vitest";

import { canonicalState, jobRecord } from "../../../test/analyzerHarness";
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

  it("settles an upload only once its target state is reached", () => {
    const parsed = jobRecord({ status: "parsed" });
    const approved = jobRecord({
      status: "approved",
      approved_state: canonicalState(),
    });

    expect(projectionMutationTargetReached(parsed, "approved")).toBe(false);
    expect(projectionMutationTargetReached(approved, "approved")).toBe(true);
    expect(projectionMutationTargetReached(parsed, "parsed")).toBe(true);
    expect(projectionMutationTargetReached(parsed, "failed")).toBe(false);
  });
});
