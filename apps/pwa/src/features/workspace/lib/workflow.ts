import type { JobRecord } from "../../../shared/types/jobs";
import { type PersistedJobMutationScope } from "./mutationLeaseTypes";

export type ActiveRecommendationRequest = {
  mutationScope: PersistedJobMutationScope;
  controller: AbortController;
  ownsMutationLease: boolean;
};

export function isHistoryReady(job: JobRecord): boolean {
  return (
    job.archived_at === null &&
    job.status !== "error" &&
    !job.recommendation_pending &&
    (job.status === "approved" ||
      job.status === "recommended" ||
      job.approved_state !== null ||
      job.recommendation !== null)
  );
}

export function isProcessingJobInProgress(job: JobRecord): boolean {
  return (
    job.archived_at === null &&
    (job.status === "created" || job.recommendation_pending)
  );
}

export function createLocalErrorJob(
  file: File,
  message: string,
  index: number,
  uploadRequestId: string,
): JobRecord {
  const timestamp = new Date().toISOString();
  return {
    id: `local-error-${Date.now()}-${index}`,
    status: "error",
    upload_request_id: uploadRequestId,
    original_filename: file.name,
    image_filename: "",
    parser_provider: "client",
    recommendation_provider: "none",
    parser_result: null,
    approved_state: null,
    training_decision: null,
    recommendation: null,
    recommendation_pending: false,
    training_reviewed_at: null,
    training_review_note: null,
    benchmark_included: false,
    archived_at: null,
    error: message,
    created_at: timestamp,
    updated_at: timestamp,
  };
}
