import { approvalKey } from "../../../domains/poker/model/canonicalPokerState";
import { screenshotTags } from "../../../shared/lib/screenshotMetadata";
import type { JobRecord } from "../../../shared/types/jobs";
import type {
  JobMutationExpectation,
  ProjectionMutationLease,
  ProjectionMutationTarget,
} from "./mutationLeaseTypes";

export function projectionMutationTargetReached(
  job: JobRecord,
  target: ProjectionMutationTarget,
): boolean {
  if (target === "failed") {
    return false;
  }
  if (job.status === "error") {
    return true;
  }
  if (target === "approved") {
    return job.approved_state !== null;
  }
  return job.parser_result !== null || job.approved_state !== null;
}

export function projectionMutationLeaseTargetReached(
  lease: ProjectionMutationLease,
  job: JobRecord,
): boolean | null {
  const expectedUpload = lease.expectedUploads.find(
    (candidate) => job.upload_request_id === candidate.requestId,
  );
  return expectedUpload
    ? projectionMutationTargetReached(job, expectedUpload.target)
    : null;
}

export function jobMutationExpectationReached(
  job: JobRecord,
  expectation: JobMutationExpectation,
): boolean {
  if (expectation.kind === "approval") {
    return (
      job.approved_state !== null &&
      job.approved_state.user_approved &&
      approvalKey(job.approved_state) === expectation.approvedStateKey &&
      job.status === "approved" &&
      job.error === null
    );
  }
  if (expectation.kind === "metadata") {
    const tags = screenshotTags(job);
    return (
      (job.title ?? null) === expectation.title &&
      (job.notes ?? null) === expectation.notes &&
      tags.length === expectation.tags.length &&
      tags.every((tag, index) => tag === expectation.tags[index])
    );
  }
  return job.benchmark_included === expectation.included;
}
