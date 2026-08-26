import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { appendPreflopContextEvidence } from "./preflopContextEvidence";
import { appendPreflopLimpEvidence } from "./preflopLimpEvidence";
import { appendPreflopRaisedEvidence } from "./preflopRaisedEvidence";
import { appendPreflopRangeEvidence } from "./preflopRangeEvidence";

export function appendPreflopEvidence(
  raw: Record<string, unknown>,
  details: RecommendationEvidenceDetail[],
): void {
  appendPreflopContextEvidence(raw, details);
  appendPreflopLimpEvidence(raw, details);
  appendPreflopRaisedEvidence(raw, details);
  appendPreflopRangeEvidence(raw, details);
}
