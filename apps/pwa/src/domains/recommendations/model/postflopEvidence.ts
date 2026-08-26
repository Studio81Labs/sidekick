import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { appendPostflopRangeEvidence } from "./postflopRangeEvidence";
import { appendPostflopTreeEvidence } from "./postflopTreeEvidence";

export function appendPostflopEvidence(
  raw: Record<string, unknown>,
  engine: string | null,
  details: RecommendationEvidenceDetail[],
  ranges: RecommendationEvidenceDetail[],
): void {
  if (engine !== "postflop_solver") {
    return;
  }

  appendPostflopTreeEvidence(raw, details);
  appendPostflopRangeEvidence(raw, details, ranges);
}
