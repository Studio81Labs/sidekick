import type { RecommendationResult } from "../../../shared/types/recommendations";
import {
  TRAINING_ACTIONS,
  TRAINING_CERTAINTIES,
} from "../../../domains/training/model/trainingOptions";

export function isCachedActionSizing(
  action: unknown,
  sizing: unknown,
): boolean {
  if (action === "bet" || action === "raise") {
    return (
      sizing === null ||
      (typeof sizing === "number" && Number.isFinite(sizing) && sizing > 0)
    );
  }
  return sizing === null;
}

export function isCachedRecommendation(
  value: unknown,
): value is RecommendationResult {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const recommendation = value as Record<string, unknown>;
  return (
    typeof recommendation.action === "string" &&
    TRAINING_ACTIONS.some((action) => action === recommendation.action) &&
    isCachedActionSizing(recommendation.action, recommendation.sizing) &&
    typeof recommendation.confidence === "number" &&
    Number.isFinite(recommendation.confidence) &&
    recommendation.confidence >= 0 &&
    recommendation.confidence <= 1 &&
    typeof recommendation.explanation === "string" &&
    recommendation.raw !== null &&
    typeof recommendation.raw === "object" &&
    !Array.isArray(recommendation.raw)
  );
}

export function isCachedTrainingDecision(value: unknown): boolean {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const decision = value as Record<string, unknown>;
  return (
    typeof decision.action === "string" &&
    TRAINING_ACTIONS.some((action) => action === decision.action) &&
    isCachedActionSizing(decision.action, decision.sizing) &&
    (decision.certainty === undefined ||
      decision.certainty === null ||
      (typeof decision.certainty === "string" &&
        TRAINING_CERTAINTIES.some(
          (certainty) => certainty === decision.certainty,
        ))) &&
    typeof decision.recorded_at === "string"
  );
}
