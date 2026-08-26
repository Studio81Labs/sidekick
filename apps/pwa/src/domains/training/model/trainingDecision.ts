import { formatCandidateValue } from "../../../shared/lib/metricPresentation";
import type {
  RecommendationAction,
  RecommendationResult,
} from "../../../shared/types/recommendations";
import type { TrainingCertainty } from "../../../shared/types/training";
import {
  metadataNumber,
  metadataRatio,
  metadataRecord,
} from "../../recommendations/model/recommendationMetadata";
import {
  MIN_SUPPORTED_FREQUENCY,
  SIZING_MATCH_TOLERANCE,
} from "./trainingOptions";

export type TrainingActionOption = "" | RecommendationAction;

export type TrainingCertaintyOption = "" | TrainingCertainty;

export function trainingDecisionLabel(
  action: RecommendationAction,
  sizing: number | null,
): string {
  const actionLabel = `${action.slice(0, 1).toUpperCase()}${action.slice(1)}`;
  return sizing === null
    ? actionLabel
    : `${actionLabel} ${formatCandidateValue(sizing)} BB`;
}

export function trainingCertaintyLabel(certainty: TrainingCertainty): string {
  return `${certainty.slice(0, 1).toUpperCase()}${certainty.slice(1)}`;
}

export function trainingDecisionComparison(
  action: RecommendationAction,
  sizing: number | null,
  recommendation: RecommendationResult,
): {
  label: string;
  tone: "match" | "partial" | "different";
  evLossBb: number | null;
} {
  const evLossBb = recommendationEvLossBb(action, sizing, recommendation);
  if (
    trainingLineMatches(
      action,
      sizing,
      recommendation.action,
      recommendation.sizing,
    )
  ) {
    return { label: "Matched solver", tone: "match", evLossBb };
  }
  const policySupport = recommendationPolicySupport(
    action,
    sizing,
    recommendation,
  );
  if (policySupport === "line") {
    return { label: "Solver-supported mix", tone: "match", evLossBb };
  }
  if (action === recommendation.action) {
    return { label: "Same action, different size", tone: "partial", evLossBb };
  }
  if (policySupport === "action") {
    return {
      label: "Solver-supported action, different size",
      tone: "partial",
      evLossBb,
    };
  }
  return { label: "Different action", tone: "different", evLossBb };
}

export function recommendationEvLossBb(
  action: RecommendationAction,
  sizing: number | null,
  recommendation: RecommendationResult,
): number | null {
  const candidates = Array.isArray(recommendation.raw.candidates)
    ? recommendation.raw.candidates
    : [];
  let bestEv: number | null = null;
  let decisionEv: number | null = null;
  let recommendationLineFound = false;
  const validActions = new Set<RecommendationAction>();
  const sizingBounds = new Map<
    RecommendationAction,
    { maximum: number; minimum: number }
  >();
  for (const candidate of candidates) {
    const record = metadataRecord(candidate);
    const candidateAction = recommendationAction(record?.action);
    if (
      !record ||
      !candidateAction ||
      !Object.prototype.hasOwnProperty.call(record, "sizing")
    ) {
      continue;
    }
    const candidateSizing = policyCandidateSizing(
      candidateAction,
      record.sizing,
    );
    const ev = metadataNumber(record.ev);
    if (!candidateSizing.valid || ev === null) {
      continue;
    }
    validActions.add(candidateAction);
    if (candidateSizing.value !== null) {
      const bounds = sizingBounds.get(candidateAction);
      sizingBounds.set(candidateAction, {
        maximum:
          bounds === undefined
            ? candidateSizing.value
            : Math.max(bounds.maximum, candidateSizing.value),
        minimum:
          bounds === undefined
            ? candidateSizing.value
            : Math.min(bounds.minimum, candidateSizing.value),
      });
    }
    bestEv = bestEv === null ? ev : Math.max(bestEv, ev);
    if (
      trainingLineMatches(
        recommendation.action,
        recommendation.sizing,
        candidateAction,
        candidateSizing.value,
      )
    ) {
      recommendationLineFound = true;
    }
    if (
      trainingLineMatches(
        action,
        sizing,
        candidateAction,
        candidateSizing.value,
      )
    ) {
      decisionEv = decisionEv === null ? ev : Math.max(decisionEv, ev);
    }
  }
  const hasDistinctLines =
    validActions.size > 1 ||
    Array.from(sizingBounds.values()).some(
      (bounds) => !trainingSizingMatches(bounds.minimum, bounds.maximum),
    );
  if (
    bestEv === null ||
    decisionEv === null ||
    !recommendationLineFound ||
    !hasDistinctLines
  ) {
    return null;
  }
  return Number(Math.max(0, bestEv - decisionEv).toFixed(6));
}

export function recommendationAction(
  value: unknown,
): RecommendationAction | null {
  if (
    value === "fold" ||
    value === "check" ||
    value === "call" ||
    value === "bet" ||
    value === "raise"
  ) {
    return value;
  }
  return null;
}

export function recommendationPolicySupport(
  action: RecommendationAction,
  sizing: number | null,
  recommendation: RecommendationResult,
): "line" | "action" | null {
  const candidates = Array.isArray(recommendation.raw.candidates)
    ? recommendation.raw.candidates
    : [];
  let actionSupported = false;
  for (const candidate of candidates) {
    const record = metadataRecord(candidate);
    if (!record || record.action !== action) {
      continue;
    }
    const frequency = metadataRatio(record.frequency);
    if (frequency === null || frequency < MIN_SUPPORTED_FREQUENCY) {
      continue;
    }
    const candidateSizing = policyCandidateSizing(action, record.sizing);
    if (!candidateSizing.valid) {
      continue;
    }
    actionSupported = true;
    if (trainingSizingMatches(sizing, candidateSizing.value)) {
      return "line";
    }
  }
  return actionSupported ? "action" : null;
}

export function policyCandidateSizing(
  action: RecommendationAction,
  value: unknown,
): { valid: boolean; value: number | null } {
  if (action === "bet" || action === "raise") {
    const sizing = metadataNumber(value);
    return sizing !== null && sizing > 0
      ? { valid: true, value: sizing }
      : { valid: false, value: null };
  }
  return value === null
    ? { valid: true, value: null }
    : { valid: false, value: null };
}

export function trainingLineMatches(
  leftAction: RecommendationAction,
  leftSizing: number | null,
  rightAction: RecommendationAction,
  rightSizing: number | null,
): boolean {
  return (
    leftAction === rightAction && trainingSizingMatches(leftSizing, rightSizing)
  );
}

export function decimalNumberParts(value: number): {
  coefficient: bigint;
  scale: number;
} {
  const [mantissa, exponentText] = value.toString().toLowerCase().split("e");
  const exponent =
    exponentText === undefined ? 0 : Number.parseInt(exponentText, 10);
  const negative = mantissa.startsWith("-");
  const unsignedMantissa = negative ? mantissa.slice(1) : mantissa;
  const [integerPart, fractionalPart = ""] = unsignedMantissa.split(".");
  const digits = `${integerPart}${fractionalPart}`;
  const coefficient = BigInt(digits) * (negative ? -1n : 1n);
  return {
    coefficient,
    scale: fractionalPart.length - exponent,
  };
}

export function decimalCoefficientAtScale(
  value: { coefficient: bigint; scale: number },
  scale: number,
): bigint {
  return value.coefficient * 10n ** BigInt(scale - value.scale);
}

export function trainingSizingMatches(
  left: number | null,
  right: number | null,
): boolean {
  if (left === null || right === null) {
    return left === right;
  }
  if (!Number.isFinite(left) || !Number.isFinite(right)) {
    return false;
  }
  const leftParts = decimalNumberParts(left);
  const rightParts = decimalNumberParts(right);
  const toleranceParts = decimalNumberParts(SIZING_MATCH_TOLERANCE);
  const commonScale = Math.max(
    leftParts.scale,
    rightParts.scale,
    toleranceParts.scale,
  );
  const leftCoefficient = decimalCoefficientAtScale(leftParts, commonScale);
  const rightCoefficient = decimalCoefficientAtScale(rightParts, commonScale);
  const toleranceCoefficient = decimalCoefficientAtScale(
    toleranceParts,
    commonScale,
  );
  const difference =
    leftCoefficient >= rightCoefficient
      ? leftCoefficient - rightCoefficient
      : rightCoefficient - leftCoefficient;
  return difference < toleranceCoefficient;
}

export function parseTrainingSizing(
  action: TrainingActionOption,
  rawSizing: string,
): { sizing: number | null; error: string | null } {
  if (action !== "bet" && action !== "raise") {
    return { sizing: null, error: null };
  }
  if (rawSizing.trim() === "") {
    return { sizing: null, error: null };
  }
  const sizing = Number(rawSizing);
  if (!Number.isFinite(sizing) || sizing <= 0) {
    return { sizing: null, error: "Enter a valid positive decision size" };
  }
  return { sizing, error: null };
}
