import type { TrainingTrend } from "../types/training";

export function formatCandidateValue(value: number): string {
  return Number(value.toFixed(3)).toString();
}

export function benchmarkPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function benchmarkFieldLabel(field: string): string {
  return field.replace(/_/g, " ");
}

export function formatEvLossBb(value: number): string {
  return `${formatCandidateValue(value)} BB`;
}

export function formatAccuracyDelta(value: number): string {
  const points = Math.round(value * 100);
  return `${points > 0 ? "+" : ""}${points} pts`;
}

export function formatEvLossDeltaBb(value: number): string {
  return `${value > 0 ? "+" : ""}${formatCandidateValue(value)} BB`;
}

export function trainingTrendWindowLabel(
  trend: Pick<TrainingTrend, "window_hands">,
): string {
  const hands = trend.window_hands === 1 ? "hand" : "hands";
  return `Last ${trend.window_hands} ${hands} vs previous ${trend.window_hands}`;
}

export function accessiblePointDelta(value: number): string {
  const points = Math.round(value * 100);
  const unit =
    Math.abs(points) === 1 ? "percentage point" : "percentage points";
  return `${points > 0 ? "+" : ""}${points} ${unit}`;
}

export function trainingTrendTone(
  delta: number,
  lowerIsBetter = false,
): "improving" | "declining" | "neutral" {
  const improvement = lowerIsBetter ? -delta : delta;
  if (improvement > 0) {
    return "improving";
  }
  if (improvement < 0) {
    return "declining";
  }
  return "neutral";
}
