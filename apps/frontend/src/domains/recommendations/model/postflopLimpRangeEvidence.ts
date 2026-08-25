import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import {
  formatEvidenceBb,
  formatEvidenceRatio,
} from "./recommendationFormatting";
import {
  metadataLabel,
  metadataNumber,
  metadataRatio,
  metadataString,
} from "./recommendationMetadata";

export function appendPostflopLimpRangeEvidence(
  rangeSource: string | null,
  rangeContext: Record<string, unknown> | null,
  details: RecommendationEvidenceDetail[],
): boolean {
  if (rangeSource === "preflop_chart_limped_pot") {
    const rangeLimperPosition = metadataLabel(rangeContext?.limper_position);
    const rangeBigBlindPosition = metadataLabel(
      rangeContext?.big_blind_position,
    );
    const rangeLimpSize = metadataNumber(rangeContext?.limp_size_bb);
    if (rangeLimperPosition && rangeBigBlindPosition) {
      details.push({
        label: "Range actors",
        value:
          rangeLimperPosition +
          " limps" +
          (rangeLimpSize !== null && rangeLimpSize > 0
            ? " " + formatEvidenceBb(rangeLimpSize)
            : "") +
          " · " +
          rangeBigBlindPosition +
          " checks",
      });
    }
    const rangeLimperFraction = metadataRatio(rangeContext?.limper_fraction);
    const rangeBigBlindRaise = metadataRatio(
      rangeContext?.big_blind_raise_fraction,
    );
    const rangeLimperModel = metadataString(
      rangeContext?.limper_range_model,
      80,
    );
    if (rangeLimperModel === "stack_adjusted_first_in_proxy") {
      details.push({
        label: "Range model",
        value: "Limper uses stack-adjusted first-in proxy",
      });
    }
    if (
      rangeLimperFraction !== null &&
      rangeBigBlindRaise !== null &&
      rangeBigBlindRaise < 1
    ) {
      details.push({
        label: "Range bands",
        value:
          "Entry " +
          formatEvidenceRatio(rangeLimperFraction) +
          " · BB check " +
          formatEvidenceRatio(rangeBigBlindRaise) +
          "-100%",
      });
    }
    return true;
  }

  if (rangeSource === "preflop_chart_isolation_raised_pot") {
    const rangeLimperPosition = metadataLabel(rangeContext?.limper_position);
    const rangeIsolationRaiserPosition = metadataLabel(
      rangeContext?.isolation_raiser_position,
    );
    const rangeLimpSize = metadataNumber(rangeContext?.limp_size_bb);
    const rangeIsolationRaiseSize = metadataNumber(
      rangeContext?.isolation_raise_size_bb,
    );
    if (rangeLimperPosition && rangeIsolationRaiserPosition) {
      details.push({
        label: "Range actors",
        value: `${rangeLimperPosition} limps${
          rangeLimpSize !== null && rangeLimpSize > 0
            ? ` ${formatEvidenceBb(rangeLimpSize)}`
            : ""
        } · ${rangeIsolationRaiserPosition} raises${
          rangeIsolationRaiseSize !== null && rangeIsolationRaiseSize > 0
            ? ` ${formatEvidenceBb(rangeIsolationRaiseSize)}`
            : ""
        } · ${rangeLimperPosition} calls`,
      });
    }
    const rangeIsolationFraction = metadataRatio(
      rangeContext?.isolation_raiser_fraction,
    );
    const rangeLimperContinue = metadataRatio(
      rangeContext?.limper_continue_fraction,
    );
    const rangeLimperReraise = metadataRatio(
      rangeContext?.limper_reraise_fraction,
    );
    if (
      rangeIsolationFraction !== null &&
      rangeLimperContinue !== null &&
      rangeLimperReraise !== null &&
      rangeLimperReraise < rangeLimperContinue
    ) {
      details.push({
        label: "Range bands",
        value: `BB isolate ${formatEvidenceRatio(rangeIsolationFraction)} · limper call ${formatEvidenceRatio(
          rangeLimperReraise,
        )}-${formatEvidenceRatio(rangeLimperContinue)}`,
      });
    }
    return true;
  }

  if (rangeSource === "preflop_chart_limp_reraised_pot") {
    const rangeLimperPosition = metadataLabel(rangeContext?.limper_position);
    const rangeIsolationRaiserPosition = metadataLabel(
      rangeContext?.isolation_raiser_position,
    );
    const rangeLimpSize = metadataNumber(rangeContext?.limp_size_bb);
    const rangeIsolationRaiseSize = metadataNumber(
      rangeContext?.isolation_raise_size_bb,
    );
    const rangeLimpReraiseSize = metadataNumber(
      rangeContext?.limp_reraise_size_bb,
    );
    if (rangeLimperPosition && rangeIsolationRaiserPosition) {
      details.push({
        label: "Range actors",
        value: `${rangeLimperPosition} limps${
          rangeLimpSize !== null && rangeLimpSize > 0
            ? ` ${formatEvidenceBb(rangeLimpSize)}`
            : ""
        } · ${rangeIsolationRaiserPosition} isolates${
          rangeIsolationRaiseSize !== null && rangeIsolationRaiseSize > 0
            ? ` ${formatEvidenceBb(rangeIsolationRaiseSize)}`
            : ""
        } · ${rangeLimperPosition} reraises${
          rangeLimpReraiseSize !== null && rangeLimpReraiseSize > 0
            ? ` ${formatEvidenceBb(rangeLimpReraiseSize)}`
            : ""
        } · ${rangeIsolationRaiserPosition} calls`,
      });
    }
    const rangeLimperReraise = metadataRatio(
      rangeContext?.limper_reraise_fraction,
    );
    const rangeIsolationRaiserContinue = metadataRatio(
      rangeContext?.isolation_raiser_continue_fraction,
    );
    const rangeIsolationRaiserFourBet = metadataRatio(
      rangeContext?.isolation_raiser_four_bet_fraction,
    );
    if (
      rangeLimperReraise !== null &&
      rangeIsolationRaiserContinue !== null &&
      rangeIsolationRaiserFourBet !== null &&
      rangeIsolationRaiserFourBet < rangeIsolationRaiserContinue
    ) {
      details.push({
        label: "Range bands",
        value: `Limper reraise ${formatEvidenceRatio(rangeLimperReraise)} · isolator call ${formatEvidenceRatio(
          rangeIsolationRaiserFourBet,
        )}-${formatEvidenceRatio(rangeIsolationRaiserContinue)}`,
      });
    }
    return true;
  }

  return false;
}
