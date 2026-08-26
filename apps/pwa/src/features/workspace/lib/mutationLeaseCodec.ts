import type {
  PersistedJobMutationScope,
  PersistedMutationLease,
} from "./mutationLeaseTypes";
import { isJobMutationExpectation } from "./mutationLeaseValidation";

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function applyLegacyDefaults(
  parsed: Record<string, unknown>,
  scope: PersistedJobMutationScope,
): void {
  if (
    parsed.kind === undefined &&
    typeof parsed.jobId === "string" &&
    typeof parsed.baselineUpdatedAt === "string"
  ) {
    parsed.kind = "job";
  }
  if (parsed.kind === "job" && parsed.expectsRemoval === undefined) {
    parsed.expectsRemoval = false;
  }
  if (
    parsed.kind === "job" &&
    parsed.expectedRecommendationRequestId === undefined
  ) {
    parsed.expectedRecommendationRequestId = null;
  }
  if (parsed.kind === "job" && parsed.expectedMutation === undefined) {
    parsed.expectedMutation = null;
  }
  if (parsed.kind === "archive" && parsed.confirmationJobIds === undefined) {
    parsed.confirmationJobIds = scope === "processing" ? parsed.jobIds : [];
  }
  if (parsed.kind === "projection" && Array.isArray(parsed.expectedUploads)) {
    for (const expectedUpload of parsed.expectedUploads) {
      const upload = recordValue(expectedUpload);
      if (upload && upload.recommendationRequestId === undefined) {
        upload.recommendationRequestId = null;
      }
    }
  }
  if (
    parsed.kind === "projection" &&
    parsed.benchmarkImportRequestId === undefined
  ) {
    parsed.benchmarkImportRequestId = null;
  }
  if (
    parsed.kind === "projection" &&
    parsed.benchmarkImportReceiptObserved === undefined
  ) {
    parsed.benchmarkImportReceiptObserved = false;
  }
}

function validJobLease(parsed: Record<string, unknown>): boolean {
  return (
    typeof parsed.jobId === "string" &&
    typeof parsed.baselineUpdatedAt === "string" &&
    typeof parsed.expectsRemoval === "boolean" &&
    (parsed.expectedRecommendationRequestId === null ||
      typeof parsed.expectedRecommendationRequestId === "string") &&
    (parsed.expectedMutation === null ||
      isJobMutationExpectation(parsed.expectedMutation))
  );
}

function validProjectionLease(parsed: Record<string, unknown>): boolean {
  const baselineJobIds = parsed.baselineJobIds;
  const expectedRemovalJobIds = parsed.expectedRemovalJobIds;
  const expectedUploads = parsed.expectedUploads;
  if (
    !Array.isArray(baselineJobIds) ||
    !baselineJobIds.every((value) => typeof value === "string") ||
    !Array.isArray(expectedRemovalJobIds) ||
    !expectedRemovalJobIds.every(
      (value) => typeof value === "string" && baselineJobIds.includes(value),
    ) ||
    !Array.isArray(expectedUploads) ||
    (parsed.benchmarkImportRequestId !== null &&
      typeof parsed.benchmarkImportRequestId !== "string") ||
    typeof parsed.benchmarkImportReceiptObserved !== "boolean"
  ) {
    return false;
  }
  return expectedUploads.every((value) => {
    const upload = recordValue(value);
    return (
      upload !== null &&
      typeof upload.requestId === "string" &&
      (upload.recommendationRequestId === null ||
        typeof upload.recommendationRequestId === "string") &&
      ["failed", "parsed", "approved", "recommended"].includes(
        String(upload.target),
      )
    );
  });
}

function validArchiveLease(parsed: Record<string, unknown>): boolean {
  const jobIds = parsed.jobIds;
  const confirmationJobIds = parsed.confirmationJobIds;
  const baselineUpdatedAt = recordValue(parsed.baselineUpdatedAt);
  return (
    Array.isArray(jobIds) &&
    jobIds.every((value) => typeof value === "string") &&
    baselineUpdatedAt !== null &&
    Object.values(baselineUpdatedAt).every(
      (value) => typeof value === "string",
    ) &&
    jobIds.every(
      (jobId) => typeof baselineUpdatedAt[String(jobId)] === "string",
    ) &&
    Array.isArray(confirmationJobIds) &&
    confirmationJobIds.every(
      (jobId) => typeof jobId === "string" && jobIds.includes(jobId),
    )
  );
}

export function decodePersistedMutationLease(
  value: unknown,
  scope: PersistedJobMutationScope,
): PersistedMutationLease | null {
  const parsed = recordValue(value);
  if (parsed === null) {
    return null;
  }
  applyLegacyDefaults(parsed, scope);
  if (
    typeof parsed.ownerId !== "string" ||
    typeof parsed.expiresAt !== "number" ||
    !Number.isFinite(parsed.expiresAt) ||
    !["job", "projection", "archive"].includes(String(parsed.kind))
  ) {
    return null;
  }
  if (parsed.kind === "job" && !validJobLease(parsed)) {
    return null;
  }
  if (parsed.kind === "projection" && !validProjectionLease(parsed)) {
    return null;
  }
  if (parsed.kind === "archive" && !validArchiveLease(parsed)) {
    return null;
  }
  return parsed as PersistedMutationLease;
}
