import {
  TRAINING_ACTIONS,
  TRAINING_CERTAINTIES,
} from "../../../domains/training/model/trainingOptions";
import { isCachedActionSizing } from "./cachedRecommendationValidation";
import type { JobMutationExpectation } from "./mutationLeaseTypes";

export function isJobMutationExpectation(
  value: unknown,
): value is JobMutationExpectation {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const expectation = value as Record<string, unknown>;
  if (expectation.kind === "approval") {
    return typeof expectation.approvedStateKey === "string";
  }
  if (expectation.kind === "training-decision") {
    return (
      typeof expectation.action === "string" &&
      TRAINING_ACTIONS.some((action) => action === expectation.action) &&
      isCachedActionSizing(expectation.action, expectation.sizing) &&
      (expectation.certainty === null ||
        (typeof expectation.certainty === "string" &&
          TRAINING_CERTAINTIES.some(
            (certainty) => certainty === expectation.certainty,
          )))
    );
  }
  if (expectation.kind === "training-review") {
    return (
      typeof expectation.reviewed === "boolean" &&
      (expectation.note === null || typeof expectation.note === "string")
    );
  }
  if (expectation.kind === "metadata") {
    return (
      (expectation.title === null || typeof expectation.title === "string") &&
      (expectation.notes === null || typeof expectation.notes === "string") &&
      Array.isArray(expectation.tags) &&
      expectation.tags.every((tag) => typeof tag === "string")
    );
  }
  return (
    expectation.kind === "benchmark-inclusion" &&
    typeof expectation.included === "boolean"
  );
}
