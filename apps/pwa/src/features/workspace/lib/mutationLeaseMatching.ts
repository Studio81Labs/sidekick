import type {
  PersistedMutationLease,
  ProjectionMutationLease,
} from "./mutationLeaseTypes";

export function mutationLeaseJobIds(
  lease: PersistedMutationLease | null,
): string[] {
  if (lease === null || lease.kind === "projection") {
    return [];
  }
  return lease.kind === "job" ? [lease.jobId] : lease.jobIds;
}

export function mutationLeaseTargetsJob(
  lease: PersistedMutationLease | null,
  jobId: string,
): boolean {
  return mutationLeaseJobIds(lease).includes(jobId);
}

export function matchingArchiveLeaseTargets(
  first: PersistedMutationLease | null,
  second: PersistedMutationLease | null,
): boolean {
  if (first?.kind !== "archive" || second?.kind !== "archive") {
    return false;
  }
  const secondIds = new Set(second.jobIds);
  return (
    first.jobIds.length === secondIds.size &&
    first.jobIds.every((jobId) => secondIds.has(jobId))
  );
}

export function benchmarkImportLeaseRequestId(
  first: PersistedMutationLease | null,
  second: PersistedMutationLease | null,
): string | null {
  const requestIds = [first, second].flatMap((lease) =>
    lease?.kind === "projection" && lease.benchmarkImportRequestId !== null
      ? [lease.benchmarkImportRequestId]
      : [],
  );
  return requestIds.length > 0 &&
    requestIds.every((requestId) => requestId === requestIds[0])
    ? requestIds[0]
    : null;
}

export function isBenchmarkImportLease(
  lease: PersistedMutationLease | null,
  requestId: string,
): lease is ProjectionMutationLease {
  return (
    lease?.kind === "projection" && lease.benchmarkImportRequestId === requestId
  );
}
