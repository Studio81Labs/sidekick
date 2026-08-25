import {
  ApiResponseError,
  humanReadableMessage,
} from "../../../shared/api/client";
import type { CanonicalState } from "../../../shared/types/poker";
import type { JobRecord } from "../../../shared/types/jobs";
import { type PersistedJobMutationScope } from "./mutationLeaseTypes";
import {
  formToCanonical,
  stateToForm,
  toCanonicalState,
} from "../../hand-review/lib/pokerState";

export type ActiveRecommendationRequest = {
  mutationScope: PersistedJobMutationScope;
  controller: AbortController;
  ownsMutationLease: boolean;
};

export const ERROR_TOAST_ID = "poker-training-error";

export const VALIDATION_TOAST_ID = "poker-training-validation";

export function messageFromError(error: unknown, fallback: string): string {
  return humanReadableMessage(
    error instanceof Error ? error.message : error,
    fallback,
  );
}

export function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

export function mutationFailureMayHavePersistedSideEffect(
  error: unknown,
): boolean {
  return (
    error instanceof TypeError ||
    (error instanceof ApiResponseError &&
      (error.status === 408 || error.status >= 500))
  );
}

export function recommendationAttemptMayHavePersistedSideEffect(
  error: unknown,
): boolean {
  return (
    mutationFailureMayHavePersistedSideEffect(error) ||
    (error instanceof ApiResponseError && error.status === 422)
  );
}

export function autoApprovalState(
  job: JobRecord,
  allowWarnings: boolean,
): CanonicalState {
  if (!job.parser_result) {
    throw new Error("Automation stopped: parser did not return a state");
  }
  if (!allowWarnings && job.parser_result.warnings.length > 0) {
    throw new Error("Automation stopped: parser warnings need manual review");
  }
  if (job.parser_auto_approval_eligible !== true) {
    throw new Error(
      job.parser_auto_approval_eligible === false
        ? "Automation stopped: parser confidence is below the configured auto-approval requirements"
        : "Automation stopped: parser confidence eligibility needs manual review",
    );
  }

  const state = formToCanonical(
    stateToForm(toCanonicalState(job.parser_result.state)),
  );
  if (state.hero_cards.length === 0 || !state.street) {
    throw new Error("Automation stopped: parser state needs manual review");
  }
  return state;
}

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
