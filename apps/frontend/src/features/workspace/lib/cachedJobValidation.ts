import type { JobRecord } from "../../../shared/types/jobs";
import {
  isCachedCanonicalState,
  isCachedDetectedState,
} from "./cachedPokerStateValidation";
import {
  isCachedRecommendation,
  isCachedTrainingDecision,
} from "./cachedRecommendationValidation";
import { PERSISTED_JOB_ID_PATTERN } from "../../../shared/lib/jobIdentity";
import { isSafeProcessingCacheTimestamp } from "./cacheValidationPrimitives";

export function isCachedParserResult(value: unknown): boolean {
  if (value === null) {
    return true;
  }
  if (typeof value !== "object") {
    return false;
  }
  const parserResult = value as Record<string, unknown>;
  return (
    isCachedDetectedState(parserResult.state) &&
    parserResult.confidences !== null &&
    typeof parserResult.confidences === "object" &&
    !Array.isArray(parserResult.confidences) &&
    Object.values(parserResult.confidences).every(
      (confidence) =>
        typeof confidence === "number" &&
        Number.isFinite(confidence) &&
        confidence >= 0 &&
        confidence <= 1,
    ) &&
    Array.isArray(parserResult.warnings) &&
    parserResult.warnings.every((warning) => typeof warning === "string") &&
    parserResult.raw !== null &&
    typeof parserResult.raw === "object" &&
    !Array.isArray(parserResult.raw)
  );
}

export function isCachedJobRecord(value: unknown): value is JobRecord {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const candidate = value as Partial<JobRecord>;
  return (
    typeof candidate.id === "string" &&
    PERSISTED_JOB_ID_PATTERN.test(candidate.id) &&
    (candidate.status === "created" ||
      candidate.status === "parsed" ||
      candidate.status === "approved" ||
      candidate.status === "recommended" ||
      candidate.status === "error") &&
    typeof candidate.original_filename === "string" &&
    typeof candidate.image_filename === "string" &&
    typeof candidate.parser_provider === "string" &&
    typeof candidate.recommendation_provider === "string" &&
    isCachedParserResult(candidate.parser_result) &&
    (candidate.parser_auto_approval_eligible === undefined ||
      candidate.parser_auto_approval_eligible === null ||
      typeof candidate.parser_auto_approval_eligible === "boolean") &&
    (candidate.approved_state === null ||
      isCachedCanonicalState(candidate.approved_state)) &&
    (candidate.recommendation === null ||
      isCachedRecommendation(candidate.recommendation)) &&
    typeof candidate.recommendation_pending === "boolean" &&
    (candidate.recommendation_request_id === undefined ||
      candidate.recommendation_request_id === null ||
      typeof candidate.recommendation_request_id === "string") &&
    (candidate.training_decision === null ||
      isCachedTrainingDecision(candidate.training_decision)) &&
    (candidate.training_reviewed_at === null ||
      typeof candidate.training_reviewed_at === "string") &&
    (candidate.training_review_note === null ||
      typeof candidate.training_review_note === "string") &&
    (candidate.error === null || typeof candidate.error === "string") &&
    typeof candidate.benchmark_included === "boolean" &&
    isSafeProcessingCacheTimestamp(candidate.created_at) &&
    isSafeProcessingCacheTimestamp(candidate.updated_at) &&
    candidate.archived_at === null
  );
}

export function isPristineBenchmarkImport(job: JobRecord): boolean {
  return (
    job.benchmark_included &&
    job.status === "approved" &&
    !job.recommendation_pending &&
    job.parser_result === null &&
    job.approved_state !== null &&
    job.training_decision === null &&
    job.recommendation === null &&
    job.recommendation_request_id === null &&
    job.training_reviewed_at === null &&
    job.training_review_note === null &&
    job.error === null
  );
}
