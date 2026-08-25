import type { CanonicalState } from "../../../shared/types/poker";
import { CONFIDENCE_KEYS } from "../../../domains/poker/model/pokerStateConstants";
import { requiresOpponentPosition } from "../../../domains/poker/model/pokerStateForm";

export function summarizeConfidences(
  confidences: Record<string, number>,
  warnings: string[],
  state: CanonicalState | null,
) {
  const confidenceKeys: string[] = [...CONFIDENCE_KEYS];
  if ((state?.current_bet ?? 0) > 0) {
    confidenceKeys.push("opponent_wager");
  }
  if (state && requiresOpponentPosition(state)) {
    confidenceKeys.push("opponent_position");
  }
  const values = confidenceKeys
    .map((key) => confidences[key])
    .filter((value): value is number => value !== undefined);
  const detectedCount = values.length;
  const averageConfidence =
    detectedCount === 0
      ? 0
      : Math.round(
          (values.reduce((sum, value) => sum + value, 0) / detectedCount) * 100,
        );
  const reviewCount =
    values.filter((value) => value < 0.7).length + warnings.length;

  return {
    averageConfidence,
    detectedCount,
    fieldTotal: confidenceKeys.length,
    reviewCount,
  };
}
