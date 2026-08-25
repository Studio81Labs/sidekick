import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import {
  formatEvidenceBb,
  formatEvidenceNumber,
  formatEvidenceRatio,
} from "./recommendationFormatting";
import {
  metadataLabel,
  metadataNumber,
  metadataRatio,
  metadataStringList,
} from "./recommendationMetadata";

export function appendPreflopRaisedEvidence(
  raw: Record<string, unknown>,
  details: RecommendationEvidenceDetail[],
): void {
  const openerPosition = metadataLabel(raw.opener_position);
  const openerOpenFraction = metadataRatio(raw.opener_open_fraction);
  const baseOpenerOpenFraction = metadataRatio(raw.base_opener_open_fraction);
  if (openerPosition) {
    let openerValue = openerPosition;
    if (openerOpenFraction !== null) {
      openerValue += ` · ${formatEvidenceRatio(openerOpenFraction)} modeled`;
      if (
        baseOpenerOpenFraction !== null &&
        Math.abs(baseOpenerOpenFraction - openerOpenFraction) >= 0.0005
      ) {
        openerValue += ` (base ${formatEvidenceRatio(baseOpenerOpenFraction)})`;
      }
    }
    details.push({ label: "Opener", value: openerValue });
  }

  const callerPositions = metadataStringList(raw.caller_positions, 4)
    .map((position) => metadataLabel(position))
    .filter((position): position is string => position !== null);
  if (callerPositions.length > 0) {
    details.push({
      label: callerPositions.length === 1 ? "Caller" : "Callers",
      value: callerPositions.join(" · "),
    });
  }

  const callerAdjustmentPolicy = metadataLabel(raw.caller_adjustment_policy);
  const squeezeOpenMultiple = metadataNumber(raw.squeeze_open_multiple);
  if (callerAdjustmentPolicy) {
    details.push({
      label: "Caller adjustment",
      value: `${callerAdjustmentPolicy}${
        squeezeOpenMultiple !== null && squeezeOpenMultiple > 0
          ? ` · ${formatEvidenceNumber(squeezeOpenMultiple)}x squeeze`
          : ""
      }`,
    });
  }

  const openingRaiseSize = metadataNumber(raw.opening_raise_size);
  const openSizePolicy = metadataLabel(raw.open_size_policy);
  if (openingRaiseSize !== null && openingRaiseSize >= 0) {
    details.push({
      label: "Opening size",
      value: `${formatEvidenceBb(openingRaiseSize)}${openSizePolicy ? ` · ${openSizePolicy}` : ""}`,
    });
  }

  const heroPriorCommitment = metadataNumber(raw.hero_prior_commitment);
  if (heroPriorCommitment !== null && heroPriorCommitment >= 0) {
    details.push({
      label: "Hero prior call",
      value: formatEvidenceBb(heroPriorCommitment),
    });
  }

  const squeezeResponsePolicy = metadataLabel(raw.squeeze_response_policy);
  const threeBettorPosition = metadataLabel(raw.three_bettor_position);
  if (threeBettorPosition) {
    details.push({
      label: squeezeResponsePolicy ? "Squeezer" : "3-bettor",
      value: threeBettorPosition,
    });
  }

  if (squeezeResponsePolicy) {
    details.push({ label: "Squeeze policy", value: squeezeResponsePolicy });
  }

  const coldThreeBetPolicy = metadataLabel(raw.cold_three_bet_policy);
  if (coldThreeBetPolicy) {
    details.push({ label: "Cold 3-bet policy", value: coldThreeBetPolicy });
  }

  const threeBetSize = metadataNumber(raw.three_bet_size);
  const threeBetRatio = metadataNumber(raw.three_bet_to_open_ratio);
  const threeBetSizePolicy = metadataLabel(raw.three_bet_size_policy);
  if (threeBetSize !== null && threeBetSize > 0) {
    const ratio =
      threeBetRatio !== null && threeBetRatio > 0
        ? ` · ${formatEvidenceNumber(threeBetRatio, 2)}x`
        : "";
    details.push({
      label: "3-bet size",
      value: `${formatEvidenceBb(threeBetSize)}${ratio}${threeBetSizePolicy ? ` · ${threeBetSizePolicy}` : ""}`,
    });
  }

  const fourBettorPosition = metadataLabel(raw.four_bettor_position);
  if (fourBettorPosition) {
    details.push({ label: "4-bettor", value: fourBettorPosition });
  }

  const coldFourBetPolicy = metadataLabel(raw.cold_four_bet_policy);
  if (coldFourBetPolicy) {
    details.push({ label: "Cold 4-bet policy", value: coldFourBetPolicy });
  }

  const fourBetSize = metadataNumber(raw.four_bet_size);
  const fourBetRatio = metadataNumber(raw.four_bet_to_three_bet_ratio);
  const fourBetSizePolicy = metadataLabel(raw.four_bet_size_policy);
  if (fourBetSize !== null && fourBetSize > 0) {
    const ratio =
      fourBetRatio !== null && fourBetRatio > 0
        ? ` · ${formatEvidenceNumber(fourBetRatio, 2)}x`
        : "";
    details.push({
      label: "4-bet size",
      value: `${formatEvidenceBb(fourBetSize)}${ratio}${fourBetSizePolicy ? ` · ${fourBetSizePolicy}` : ""}`,
    });
  }
}
