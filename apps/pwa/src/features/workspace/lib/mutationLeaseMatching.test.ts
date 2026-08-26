import { describe, expect, it } from "vitest";

import {
  benchmarkImportLeaseRequestId,
  matchingArchiveLeaseTargets,
  mutationLeaseJobIds,
  mutationLeaseTargetsJob,
} from "./mutationLeaseMatching";
import type {
  ArchiveMutationLease,
  ProjectionMutationLease,
} from "./mutationLeaseTypes";

const archiveLease = (jobIds: string[]): ArchiveMutationLease => ({
  kind: "archive",
  ownerId: "owner",
  expiresAt: 100,
  jobIds,
  baselineUpdatedAt: Object.fromEntries(jobIds.map((id) => [id, "updated"])),
  confirmationJobIds: [],
});

const projectionLease = (
  requestId: string | null,
): ProjectionMutationLease => ({
  kind: "projection",
  ownerId: "owner",
  expiresAt: 100,
  baselineJobIds: [],
  expectedRemovalJobIds: [],
  benchmarkImportRequestId: requestId,
  benchmarkImportReceiptObserved: false,
  expectedUploads: [],
});

describe("mutation lease matching", () => {
  it("extracts and matches persisted job targets", () => {
    const archive = archiveLease(["job-1", "job-2"]);

    expect(mutationLeaseJobIds(archive)).toEqual(["job-1", "job-2"]);
    expect(mutationLeaseTargetsJob(archive, "job-2")).toBe(true);
    expect(mutationLeaseJobIds(projectionLease(null))).toEqual([]);
  });

  it("matches archive targets independently of order", () => {
    expect(
      matchingArchiveLeaseTargets(
        archiveLease(["job-1", "job-2"]),
        archiveLease(["job-2", "job-1"]),
      ),
    ).toBe(true);
    expect(
      matchingArchiveLeaseTargets(
        archiveLease(["job-1"]),
        archiveLease(["job-2"]),
      ),
    ).toBe(false);
  });

  it("returns only a benchmark request shared by every active import lease", () => {
    expect(
      benchmarkImportLeaseRequestId(
        projectionLease("request-1"),
        projectionLease("request-1"),
      ),
    ).toBe("request-1");
    expect(
      benchmarkImportLeaseRequestId(
        projectionLease("request-1"),
        projectionLease("request-2"),
      ),
    ).toBeNull();
  });
});
