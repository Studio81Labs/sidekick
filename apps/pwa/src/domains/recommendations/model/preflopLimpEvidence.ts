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

export function appendPreflopLimpEvidence(
  raw: Record<string, unknown>,
  details: RecommendationEvidenceDetail[],
): void {
  const isolationRaiserPosition = metadataLabel(raw.isolation_raiser_position);
  const limpReraiserPosition = metadataLabel(raw.limp_reraiser_position);
  const limperPositions = metadataStringList(raw.limper_positions, 5)
    .map((position) => metadataLabel(position))
    .filter((position): position is string => position !== null);
  if (limperPositions.length > 0) {
    details.push({ label: "Limpers", value: limperPositions.join(" · ") });
  }

  const limperPosition = metadataLabel(raw.limper_position);
  if (limperPosition) {
    details.push({
      label: isolationRaiserPosition
        ? "Hero limper"
        : limpReraiserPosition
          ? "Original limper"
          : "Limper",
      value: limperPosition,
    });
  }

  const limpSize = metadataNumber(raw.limp_size);
  if (limpSize !== null && limpSize > 0) {
    details.push({ label: "Limp size", value: formatEvidenceBb(limpSize) });
  }

  const limpResponsePolicy = metadataLabel(raw.limp_response_policy);
  if (limpResponsePolicy) {
    details.push({ label: "Limp policy", value: limpResponsePolicy });
  }

  if (isolationRaiserPosition) {
    details.push({ label: "Isolation raiser", value: isolationRaiserPosition });
  }

  const isolationRaiseSize = metadataNumber(raw.isolation_raise_size);
  const isolationRaiseRatio = metadataNumber(raw.isolation_raise_to_limp_ratio);
  const isolationSizePolicy = metadataLabel(raw.isolation_raise_size_policy);
  if (isolationRaiseSize !== null && isolationRaiseSize > 0) {
    let isolationValue = formatEvidenceBb(isolationRaiseSize);
    if (isolationRaiseRatio !== null && isolationRaiseRatio > 0) {
      isolationValue += ` · ${formatEvidenceNumber(isolationRaiseRatio)}x limp`;
    }
    if (isolationSizePolicy) {
      isolationValue += ` · ${isolationSizePolicy}`;
    }
    details.push({ label: "Isolation size", value: isolationValue });
  }

  const isolationResponsePolicy = metadataLabel(raw.isolation_response_policy);
  if (isolationResponsePolicy) {
    details.push({ label: "Isolation policy", value: isolationResponsePolicy });
  }

  const heroIsolationRaiseSize = metadataNumber(raw.hero_isolation_raise_size);
  if (heroIsolationRaiseSize !== null && heroIsolationRaiseSize > 0) {
    details.push({
      label: "Hero isolation",
      value: formatEvidenceBb(heroIsolationRaiseSize),
    });
  }

  if (limpReraiserPosition) {
    details.push({ label: "Limp reraiser", value: limpReraiserPosition });
  }

  const limpReraiseSize = metadataNumber(raw.limp_reraise_size);
  const limpReraiseRatio = metadataNumber(raw.limp_reraise_to_isolation_ratio);
  const limpReraiseSizePolicy = metadataLabel(raw.limp_reraise_size_policy);
  if (limpReraiseSize !== null && limpReraiseSize > 0) {
    let limpReraiseValue = formatEvidenceBb(limpReraiseSize);
    if (limpReraiseRatio !== null && limpReraiseRatio > 0) {
      limpReraiseValue += ` · ${formatEvidenceNumber(limpReraiseRatio, 2)}x isolation`;
    }
    if (limpReraiseSizePolicy) {
      limpReraiseValue += ` · ${limpReraiseSizePolicy}`;
    }
    details.push({ label: "Limp-reraise size", value: limpReraiseValue });
  }

  const limpReraiseResponsePolicy = metadataLabel(
    raw.limp_reraise_response_policy,
  );
  if (limpReraiseResponsePolicy) {
    details.push({
      label: "Limp-reraise policy",
      value: limpReraiseResponsePolicy,
    });
  }

  const limpRaiseFraction = metadataRatio(raw.limp_raise_fraction);
  const baseLimpRaiseFraction = metadataRatio(raw.base_limp_raise_fraction);
  if (limpRaiseFraction !== null) {
    let rangeValue = formatEvidenceRatio(limpRaiseFraction);
    if (
      baseLimpRaiseFraction !== null &&
      Math.abs(baseLimpRaiseFraction - limpRaiseFraction) >= 0.0005
    ) {
      rangeValue += ` (base ${formatEvidenceRatio(baseLimpRaiseFraction)})`;
    }
    details.push({ label: "Isolation range", value: rangeValue });
  }

  const targetLimpRaiseSize = metadataNumber(raw.target_limp_raise_size);
  if (targetLimpRaiseSize !== null && targetLimpRaiseSize > 0) {
    details.push({
      label: "Isolation target",
      value: formatEvidenceBb(targetLimpRaiseSize),
    });
  }

  const multiLimpResponsePolicy = metadataLabel(raw.multi_limp_response_policy);
  if (multiLimpResponsePolicy) {
    details.push({
      label: "Multi-limp policy",
      value: multiLimpResponsePolicy,
    });
  }

  const multiLimpRaiseFraction = metadataRatio(raw.multi_limp_raise_fraction);
  const baseMultiLimpRaiseFraction = metadataRatio(
    raw.base_multi_limp_raise_fraction,
  );
  if (multiLimpRaiseFraction !== null) {
    let rangeValue = formatEvidenceRatio(multiLimpRaiseFraction);
    if (
      baseMultiLimpRaiseFraction !== null &&
      Math.abs(baseMultiLimpRaiseFraction - multiLimpRaiseFraction) >= 0.0005
    ) {
      rangeValue += ` (base ${formatEvidenceRatio(baseMultiLimpRaiseFraction)})`;
    }
    details.push({ label: "Multi-limp isolation range", value: rangeValue });
  }

  const targetMultiLimpRaiseSize = metadataNumber(
    raw.target_multi_limp_raise_size,
  );
  if (targetMultiLimpRaiseSize !== null && targetMultiLimpRaiseSize > 0) {
    details.push({
      label: "Isolation target",
      value: formatEvidenceBb(targetMultiLimpRaiseSize),
    });
  }
}
