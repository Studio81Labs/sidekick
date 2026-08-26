import type {
  RecommendationEvidence,
  RecommendationEvidenceMetric,
} from "./recommendationEvidenceTypes";

export function formatEvidenceRatio(value: number): string {
  const percent = Number((value * 100).toFixed(1));
  return `${percent}%`;
}

export function formatEvidenceBb(value: number): string {
  return `${Number(value.toFixed(2))} BB`;
}

export function formatEvidenceNumber(value: number, precision = 1): string {
  return Number(value.toFixed(precision)).toString();
}

export function formatEvidenceMetric(
  metric: RecommendationEvidenceMetric,
): string {
  if (metric.unit === "percent") {
    return `${Math.round(metric.value * 100)}%`;
  }
  return `${Number(metric.value.toFixed(3))} BB`;
}

export function recommendationContextLabel(
  evidence: RecommendationEvidence,
): string {
  if (evidence.fallbackFrom) {
    return `${evidence.fallbackFrom} ${evidence.routed ? "route" : "fallback"}`;
  }
  return evidence.routed ? "Specialized route" : "Fallback used";
}
