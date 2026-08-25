import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { appendPostflopLimpRangeEvidence } from "./postflopLimpRangeEvidence";
import { appendPostflopRaisedRangeEvidence } from "./postflopRaisedRangeEvidence";

export function appendPostflopRangeContextEvidence(
  rangeSource: string | null,
  rangeContext: Record<string, unknown> | null,
  details: RecommendationEvidenceDetail[],
): void {
  if (appendPostflopLimpRangeEvidence(rangeSource, rangeContext, details)) {
    return;
  }
  appendPostflopRaisedRangeEvidence(rangeSource, rangeContext, details);
}
