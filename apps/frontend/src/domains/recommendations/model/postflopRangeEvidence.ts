import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { formatEvidenceBb } from "./recommendationFormatting";
import {
  metadataExactString,
  metadataLabel,
  metadataNumber,
  metadataRecord,
  metadataString,
} from "./recommendationMetadata";
import { appendPostflopRangeContextEvidence } from "./postflopRangeContextEvidence";
import {
  isContextualPostflopRangeSource,
  POSTFLOP_RANGE_SOURCE_LABELS,
} from "./postflopRangeSources";
import { rangeConditioningEvidence } from "./rangeConditioningPresentation";

export function appendPostflopRangeEvidence(
  raw: Record<string, unknown>,
  details: RecommendationEvidenceDetail[],
  ranges: RecommendationEvidenceDetail[],
): void {
  const rawRangeSource = metadataString(raw.range_source, 80);
  const rangeSource = metadataLabel(rawRangeSource);
  const contextualRangeSource = isContextualPostflopRangeSource(rawRangeSource);
  if (rangeSource) {
    details.push({
      label: "Range source",
      value: contextualRangeSource
        ? POSTFLOP_RANGE_SOURCE_LABELS[rawRangeSource]
        : rangeSource,
    });
  }
  details.push(...rangeConditioningEvidence(raw.range_conditioning));

  const rangeContext = contextualRangeSource
    ? metadataRecord(raw.range_context)
    : null;
  const rangeStackPolicy = metadataLabel(rangeContext?.stack_depth_policy);
  const rangeStartingStack = metadataNumber(
    rangeContext?.starting_effective_stack_bb,
  );
  const rangeStackSource = metadataString(rangeContext?.stack_depth_source, 40);
  if (
    rangeStackPolicy &&
    rangeStartingStack !== null &&
    rangeStartingStack > 0 &&
    (rangeStackSource === "reconstructed" ||
      rangeStackSource === "standard_assumption")
  ) {
    details.push({
      label: "Range depth",
      value: `${rangeStackPolicy} · ${formatEvidenceBb(rangeStartingStack)} ${
        rangeStackSource === "reconstructed" ? "starting" : "assumed"
      }`,
    });
  }
  const rangeDecisionStreet = metadataString(rangeContext?.decision_street, 20);
  const rangeCompletedStreetCount = metadataNumber(
    rangeContext?.completed_street_count,
  );
  if (
    (rangeDecisionStreet === "turn" || rangeDecisionStreet === "river") &&
    rangeCompletedStreetCount !== null &&
    Number.isInteger(rangeCompletedStreetCount) &&
    rangeCompletedStreetCount > 0
  ) {
    details.push({
      label: "Range verification",
      value: `${metadataLabel(rangeDecisionStreet)} · ${rangeCompletedStreetCount} completed ${
        rangeCompletedStreetCount === 1 ? "street" : "streets"
      }`,
    });
  }

  appendPostflopRangeContextEvidence(rawRangeSource, rangeContext, details);

  const rawRanges = metadataRecord(raw.ranges);
  const oopRange = metadataExactString(rawRanges?.oop);
  const ipRange = metadataExactString(rawRanges?.ip);
  if (oopRange) {
    ranges.push({ label: "OOP", value: oopRange });
  }
  if (ipRange) {
    ranges.push({ label: "IP", value: ipRange });
  }
}
