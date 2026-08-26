import type { JobRecord } from "../../../shared/types/jobs";
import {
  PERSISTED_MUTATION_LEASE_MS,
  writePersistedMutationLease,
} from "./mutationLeaseStorage";
import type {
  ArchiveMutationLease,
  JobMutationExpectation,
  PersistedJobMutationScope,
  PersistedMutationLease,
  ProjectionMutationLease,
} from "./mutationLeaseTypes";

export function mutationLeaseOwnerId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function createMutationRequestId(): string {
  return globalThis.crypto.randomUUID();
}

export function startPersistedMutationLease(
  scope: PersistedJobMutationScope,
  ownerId: string,
  job: JobRecord,
  expectedMutation: JobMutationExpectation | null,
  expectsRemoval = false,
): PersistedMutationLease | null {
  const lease: PersistedMutationLease = {
    kind: "job",
    ownerId,
    jobId: job.id,
    baselineUpdatedAt: job.updated_at,
    expectsRemoval,
    expectedRecommendationRequestId: null,
    expectedMutation,
    expiresAt: Date.now() + PERSISTED_MUTATION_LEASE_MS,
  };
  return writePersistedMutationLease(scope, lease) ? lease : null;
}

export function startProjectionMutationLease(
  scope: PersistedJobMutationScope,
  ownerId: string,
  baselineJobs: readonly JobRecord[],
  expectedUploads: ProjectionMutationLease["expectedUploads"] = [],
  expectedRemovalJobIds: readonly string[] = [],
  benchmarkImportRequestId: string | null = null,
): PersistedMutationLease | null {
  const lease: ProjectionMutationLease = {
    kind: "projection",
    ownerId,
    baselineJobIds: baselineJobs.map((job) => job.id),
    expectedRemovalJobIds: [...expectedRemovalJobIds],
    benchmarkImportRequestId,
    benchmarkImportReceiptObserved: false,
    expectedUploads: [...expectedUploads],
    expiresAt: Date.now() + PERSISTED_MUTATION_LEASE_MS,
  };
  return writePersistedMutationLease(scope, lease) ? lease : null;
}

export function startArchiveMutationLease(
  scope: PersistedJobMutationScope,
  ownerId: string,
  jobs: readonly JobRecord[],
  processingJobIds: ReadonlySet<string> = new Set(),
): PersistedMutationLease | null {
  const lease: ArchiveMutationLease = {
    kind: "archive",
    ownerId,
    jobIds: jobs.map((job) => job.id),
    baselineUpdatedAt: Object.fromEntries(
      jobs.map((job) => [job.id, job.updated_at]),
    ),
    confirmationJobIds:
      scope === "processing"
        ? jobs
            .filter((job) => !processingJobIds.has(job.id))
            .map((job) => job.id)
        : [],
    expiresAt: Date.now() + PERSISTED_MUTATION_LEASE_MS,
  };
  return writePersistedMutationLease(scope, lease) ? lease : null;
}
