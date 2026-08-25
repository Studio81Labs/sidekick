import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import {
  formatEvidenceBb,
  formatEvidenceRatio,
} from "./recommendationFormatting";
import { metadataNumber, metadataRatio } from "./recommendationMetadata";

export function appendPreflopRangeEvidence(
  raw: Record<string, unknown>,
  details: RecommendationEvidenceDetail[],
): void {
  const continueFraction = metadataRatio(raw.continue_fraction);
  const reraiseFraction = metadataRatio(raw.reraise_fraction);
  const fourBetFraction = metadataRatio(raw.four_bet_fraction);
  const fiveBetFraction = metadataRatio(raw.five_bet_fraction);
  if (
    continueFraction !== null ||
    reraiseFraction !== null ||
    fourBetFraction !== null ||
    fiveBetFraction !== null
  ) {
    const responseParts: string[] = [];
    if (continueFraction !== null) {
      responseParts.push(`Continue ${formatEvidenceRatio(continueFraction)}`);
    }
    if (reraiseFraction !== null) {
      responseParts.push(`Reraise ${formatEvidenceRatio(reraiseFraction)}`);
    }
    if (fourBetFraction !== null) {
      responseParts.push(`Four-bet ${formatEvidenceRatio(fourBetFraction)}`);
    }
    if (fiveBetFraction !== null) {
      responseParts.push(`Five-bet ${formatEvidenceRatio(fiveBetFraction)}`);
    }
    details.push({ label: "Response range", value: responseParts.join(" · ") });
  }

  const openFraction = metadataRatio(raw.open_fraction);
  const baseOpenFraction = metadataRatio(raw.base_open_fraction);
  if (openFraction !== null) {
    let openValue = formatEvidenceRatio(openFraction);
    if (
      baseOpenFraction !== null &&
      Math.abs(baseOpenFraction - openFraction) >= 0.0005
    ) {
      openValue += ` (base ${formatEvidenceRatio(baseOpenFraction)})`;
    }
    details.push({ label: "Opening range", value: openValue });
  }

  const targetOpenSize = metadataNumber(raw.target_open_size);
  if (targetOpenSize !== null && targetOpenSize >= 0) {
    details.push({
      label: "Open target",
      value: formatEvidenceBb(targetOpenSize),
    });
  }

  const maximumRaiseTotal = metadataNumber(
    raw.maximum_five_bet_total ??
      raw.maximum_four_bet_total ??
      raw.maximum_reraise_total ??
      raw.maximum_multi_limp_raise_total ??
      raw.maximum_limp_raise_total,
  );
  if (maximumRaiseTotal !== null && maximumRaiseTotal >= 0) {
    details.push({
      label: "All-in cap",
      value: formatEvidenceBb(maximumRaiseTotal),
    });
  }
}
