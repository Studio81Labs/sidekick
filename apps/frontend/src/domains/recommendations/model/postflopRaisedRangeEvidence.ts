import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import {
  formatEvidenceBb,
  formatEvidenceRatio,
} from "./recommendationFormatting";
import {
  metadataLabel,
  metadataNumber,
  metadataRatio,
} from "./recommendationMetadata";

export function appendPostflopRaisedRangeEvidence(
  rangeSource: string | null,
  rangeContext: Record<string, unknown> | null,
  details: RecommendationEvidenceDetail[],
): void {
  if (rangeSource === "preflop_chart_single_raised_pot") {
    const rangeOpenerPosition = metadataLabel(rangeContext?.opener_position);
    const rangeCallerPosition = metadataLabel(rangeContext?.caller_position);
    const rangeOpeningSize = metadataNumber(rangeContext?.opening_size_bb);
    if (rangeOpenerPosition && rangeCallerPosition) {
      details.push({
        label: "Range actors",
        value: `${rangeOpenerPosition} opens${
          rangeOpeningSize !== null && rangeOpeningSize > 0
            ? ` ${formatEvidenceBb(rangeOpeningSize)}`
            : ""
        } · ${rangeCallerPosition} calls`,
      });
    }
    const rangeOpenerFraction = metadataRatio(rangeContext?.opener_fraction);
    const rangeCallerContinue = metadataRatio(
      rangeContext?.caller_continue_fraction,
    );
    const rangeCallerReraise = metadataRatio(
      rangeContext?.caller_reraise_fraction,
    );
    if (
      rangeOpenerFraction !== null &&
      rangeCallerContinue !== null &&
      rangeCallerReraise !== null &&
      rangeCallerReraise < rangeCallerContinue
    ) {
      details.push({
        label: "Range bands",
        value: `Open ${formatEvidenceRatio(rangeOpenerFraction)} · flat ${formatEvidenceRatio(
          rangeCallerReraise,
        )}-${formatEvidenceRatio(rangeCallerContinue)}`,
      });
    }
    return;
  }

  if (rangeSource === "preflop_chart_three_bet_pot") {
    const rangeOpenerPosition = metadataLabel(rangeContext?.opener_position);
    const rangeThreeBettorPosition = metadataLabel(
      rangeContext?.three_bettor_position,
    );
    const rangeOpeningSize = metadataNumber(rangeContext?.opening_size_bb);
    const rangeThreeBetSize = metadataNumber(rangeContext?.three_bet_size_bb);
    if (rangeOpenerPosition && rangeThreeBettorPosition) {
      details.push({
        label: "Range actors",
        value: `${rangeOpenerPosition} opens${
          rangeOpeningSize !== null && rangeOpeningSize > 0
            ? ` ${formatEvidenceBb(rangeOpeningSize)}`
            : ""
        } · ${rangeThreeBettorPosition} 3-bets${
          rangeThreeBetSize !== null && rangeThreeBetSize > 0
            ? ` ${formatEvidenceBb(rangeThreeBetSize)}`
            : ""
        } · ${rangeOpenerPosition} calls`,
      });
    }
    const rangeThreeBettorFraction = metadataRatio(
      rangeContext?.three_bettor_fraction,
    );
    const rangeOpenerContinue = metadataRatio(
      rangeContext?.opener_continue_fraction,
    );
    const rangeOpenerFourBet = metadataRatio(
      rangeContext?.opener_four_bet_fraction,
    );
    if (
      rangeThreeBettorFraction !== null &&
      rangeOpenerContinue !== null &&
      rangeOpenerFourBet !== null &&
      rangeOpenerFourBet < rangeOpenerContinue
    ) {
      details.push({
        label: "Range bands",
        value: `3-bet ${formatEvidenceRatio(rangeThreeBettorFraction)} · flat ${formatEvidenceRatio(
          rangeOpenerFourBet,
        )}-${formatEvidenceRatio(rangeOpenerContinue)}`,
      });
    }
    return;
  }

  if (rangeSource === "preflop_chart_cold_three_bet_pot") {
    const rangeFoldedOpenerPosition = metadataLabel(
      rangeContext?.folded_opener_position,
    );
    const rangeThreeBettorPosition = metadataLabel(
      rangeContext?.three_bettor_position,
    );
    const rangeColdCallerPosition = metadataLabel(
      rangeContext?.cold_caller_position,
    );
    const rangeOpeningSize = metadataNumber(rangeContext?.opening_size_bb);
    const rangeThreeBetSize = metadataNumber(rangeContext?.three_bet_size_bb);
    const rangeFoldedOpenerCommitment = metadataNumber(
      rangeContext?.folded_opener_commitment_bb,
    );
    if (
      rangeFoldedOpenerPosition &&
      rangeThreeBettorPosition &&
      rangeColdCallerPosition
    ) {
      details.push({
        label: "Range actors",
        value: `${rangeFoldedOpenerPosition} opens${
          rangeOpeningSize !== null && rangeOpeningSize > 0
            ? ` ${formatEvidenceBb(rangeOpeningSize)}`
            : ""
        } · ${rangeThreeBettorPosition} 3-bets${
          rangeThreeBetSize !== null && rangeThreeBetSize > 0
            ? ` ${formatEvidenceBb(rangeThreeBetSize)}`
            : ""
        } · ${rangeColdCallerPosition} cold-calls · ${rangeFoldedOpenerPosition} folds${
          rangeFoldedOpenerCommitment !== null &&
          rangeFoldedOpenerCommitment > 0
            ? ` ${formatEvidenceBb(rangeFoldedOpenerCommitment)} dead`
            : ""
        }`,
      });
    }
    const rangeThreeBettorFraction = metadataRatio(
      rangeContext?.three_bettor_fraction,
    );
    const rangeColdCallerContinue = metadataRatio(
      rangeContext?.cold_caller_continue_fraction,
    );
    const rangeColdCallerFourBet = metadataRatio(
      rangeContext?.cold_caller_four_bet_fraction,
    );
    if (
      rangeThreeBettorFraction !== null &&
      rangeColdCallerContinue !== null &&
      rangeColdCallerFourBet !== null &&
      rangeColdCallerFourBet < rangeColdCallerContinue
    ) {
      details.push({
        label: "Range bands",
        value: `3-bet ${formatEvidenceRatio(rangeThreeBettorFraction)} · cold-call ${formatEvidenceRatio(
          rangeColdCallerFourBet,
        )}-${formatEvidenceRatio(rangeColdCallerContinue)}`,
      });
    }
    return;
  }

  if (rangeSource === "preflop_chart_squeeze_pot") {
    const rangeFoldedOpenerPosition = metadataLabel(
      rangeContext?.folded_opener_position,
    );
    const rangeCallerPosition = metadataLabel(rangeContext?.caller_position);
    const rangeSqueezerPosition = metadataLabel(
      rangeContext?.squeezer_position,
    );
    const rangeOpeningSize = metadataNumber(rangeContext?.opening_size_bb);
    const rangeSqueezeSize = metadataNumber(rangeContext?.squeeze_size_bb);
    const rangeFoldedOpenerCommitment = metadataNumber(
      rangeContext?.folded_opener_commitment_bb,
    );
    if (
      rangeFoldedOpenerPosition &&
      rangeCallerPosition &&
      rangeSqueezerPosition
    ) {
      details.push({
        label: "Range actors",
        value: `${rangeFoldedOpenerPosition} opens${
          rangeOpeningSize !== null && rangeOpeningSize > 0
            ? ` ${formatEvidenceBb(rangeOpeningSize)}`
            : ""
        } · ${rangeCallerPosition} calls · ${rangeSqueezerPosition} squeezes${
          rangeSqueezeSize !== null && rangeSqueezeSize > 0
            ? ` ${formatEvidenceBb(rangeSqueezeSize)}`
            : ""
        } · ${rangeCallerPosition} calls · ${rangeFoldedOpenerPosition} folds${
          rangeFoldedOpenerCommitment !== null &&
          rangeFoldedOpenerCommitment > 0
            ? ` ${formatEvidenceBb(rangeFoldedOpenerCommitment)} dead`
            : ""
        }`,
      });
    }
    const rangeSqueezerFraction = metadataRatio(
      rangeContext?.squeezer_fraction,
    );
    const rangeCallerContinue = metadataRatio(
      rangeContext?.caller_continue_fraction,
    );
    const rangeCallerFourBet = metadataRatio(
      rangeContext?.caller_four_bet_fraction,
    );
    if (
      rangeSqueezerFraction !== null &&
      rangeCallerContinue !== null &&
      rangeCallerFourBet !== null &&
      rangeCallerFourBet < rangeCallerContinue
    ) {
      details.push({
        label: "Range bands",
        value: `Squeeze ${formatEvidenceRatio(rangeSqueezerFraction)} · call ${formatEvidenceRatio(
          rangeCallerFourBet,
        )}-${formatEvidenceRatio(rangeCallerContinue)}`,
      });
    }
    return;
  }

  if (rangeSource === "preflop_chart_cold_four_bet_pot") {
    const rangeFoldedOpenerPosition = metadataLabel(
      rangeContext?.folded_opener_position,
    );
    const rangeThreeBettorPosition = metadataLabel(
      rangeContext?.three_bettor_position,
    );
    const rangeColdFourBettorPosition = metadataLabel(
      rangeContext?.cold_four_bettor_position,
    );
    const rangeOpeningSize = metadataNumber(rangeContext?.opening_size_bb);
    const rangeThreeBetSize = metadataNumber(rangeContext?.three_bet_size_bb);
    const rangeFourBetSize = metadataNumber(rangeContext?.four_bet_size_bb);
    const rangeFoldedOpenerCommitment = metadataNumber(
      rangeContext?.folded_opener_commitment_bb,
    );
    if (
      rangeFoldedOpenerPosition &&
      rangeThreeBettorPosition &&
      rangeColdFourBettorPosition
    ) {
      details.push({
        label: "Range actors",
        value: `${rangeFoldedOpenerPosition} opens${
          rangeOpeningSize !== null && rangeOpeningSize > 0
            ? ` ${formatEvidenceBb(rangeOpeningSize)}`
            : ""
        } · ${rangeThreeBettorPosition} 3-bets${
          rangeThreeBetSize !== null && rangeThreeBetSize > 0
            ? ` ${formatEvidenceBb(rangeThreeBetSize)}`
            : ""
        } · ${rangeColdFourBettorPosition} cold 4-bets${
          rangeFourBetSize !== null && rangeFourBetSize > 0
            ? ` ${formatEvidenceBb(rangeFourBetSize)}`
            : ""
        } · ${rangeFoldedOpenerPosition} folds${
          rangeFoldedOpenerCommitment !== null &&
          rangeFoldedOpenerCommitment > 0
            ? ` ${formatEvidenceBb(rangeFoldedOpenerCommitment)} dead`
            : ""
        } · ${rangeThreeBettorPosition} calls`,
      });
    }
    const rangeColdFourBet = metadataRatio(
      rangeContext?.cold_four_bettor_four_bet_fraction,
    );
    const rangeThreeBettorContinue = metadataRatio(
      rangeContext?.three_bettor_continue_fraction,
    );
    const rangeThreeBettorFiveBet = metadataRatio(
      rangeContext?.three_bettor_five_bet_fraction,
    );
    if (
      rangeColdFourBet !== null &&
      rangeThreeBettorContinue !== null &&
      rangeThreeBettorFiveBet !== null &&
      rangeThreeBettorFiveBet < rangeThreeBettorContinue
    ) {
      details.push({
        label: "Range bands",
        value: `Cold 4-bet ${formatEvidenceRatio(rangeColdFourBet)} · flat ${formatEvidenceRatio(
          rangeThreeBettorFiveBet,
        )}-${formatEvidenceRatio(rangeThreeBettorContinue)}`,
      });
    }
    return;
  }

  if (rangeSource === "preflop_chart_four_bet_pot") {
    const rangeOpenerPosition = metadataLabel(rangeContext?.opener_position);
    const rangeThreeBettorPosition = metadataLabel(
      rangeContext?.three_bettor_position,
    );
    const rangeOpeningSize = metadataNumber(rangeContext?.opening_size_bb);
    const rangeThreeBetSize = metadataNumber(rangeContext?.three_bet_size_bb);
    const rangeFourBetSize = metadataNumber(rangeContext?.four_bet_size_bb);
    if (rangeOpenerPosition && rangeThreeBettorPosition) {
      details.push({
        label: "Range actors",
        value: `${rangeOpenerPosition} opens${
          rangeOpeningSize !== null && rangeOpeningSize > 0
            ? ` ${formatEvidenceBb(rangeOpeningSize)}`
            : ""
        } · ${rangeThreeBettorPosition} 3-bets${
          rangeThreeBetSize !== null && rangeThreeBetSize > 0
            ? ` ${formatEvidenceBb(rangeThreeBetSize)}`
            : ""
        } · ${rangeOpenerPosition} 4-bets${
          rangeFourBetSize !== null && rangeFourBetSize > 0
            ? ` ${formatEvidenceBb(rangeFourBetSize)}`
            : ""
        } · ${rangeThreeBettorPosition} calls`,
      });
    }
    const rangeOpenerFourBet = metadataRatio(
      rangeContext?.opener_four_bet_fraction,
    );
    const rangeThreeBettorContinue = metadataRatio(
      rangeContext?.three_bettor_continue_fraction,
    );
    const rangeThreeBettorFiveBet = metadataRatio(
      rangeContext?.three_bettor_five_bet_fraction,
    );
    if (
      rangeOpenerFourBet !== null &&
      rangeThreeBettorContinue !== null &&
      rangeThreeBettorFiveBet !== null &&
      rangeThreeBettorFiveBet < rangeThreeBettorContinue
    ) {
      details.push({
        label: "Range bands",
        value: `4-bet ${formatEvidenceRatio(rangeOpenerFourBet)} · flat ${formatEvidenceRatio(
          rangeThreeBettorFiveBet,
        )}-${formatEvidenceRatio(rangeThreeBettorContinue)}`,
      });
    }
  }
}
