import type { RecommendationResult } from "../../../shared/types/recommendations";
import { providerLabel } from "../../pipeline/model/pipelineSelection";
import { appendPostflopEvidence } from "./postflopEvidence";
import { appendPreflopEvidence } from "./preflopEvidence";
import { recommendationCandidatesFromRaw } from "./recommendationCandidates";
import type {
  RecommendationEvidence,
  RecommendationEvidenceDetail,
  RecommendationEvidenceMetric,
} from "./recommendationEvidenceTypes";
import {
  metadataNumber,
  metadataRatio,
  metadataRecord,
  metadataString,
} from "./recommendationMetadata";

export function recommendationEvidenceFromRaw(
  raw: Record<string, unknown>,
  recommendation: RecommendationResult,
): RecommendationEvidence | null {
  const engine = metadataString(raw.engine, 80);
  const equity = metadataRecord(raw.equity);
  const rangeEquity = metadataRatio(equity?.equity ?? raw.equity);
  const realizedEquity = metadataRatio(raw.realized_equity);
  const requiredEquity = metadataRatio(raw.required_equity ?? raw.pot_odds);
  const exploitability = metadataRecord(raw.exploitability);
  const exploitabilityBb = metadataNumber(exploitability?.bb);
  const handTopFraction = metadataRatio(raw.hand_top_fraction);
  const policyFraction = metadataRatio(raw.policy_fraction);
  const metrics: RecommendationEvidenceMetric[] = [];
  const details: RecommendationEvidenceDetail[] = [];
  const ranges: RecommendationEvidenceDetail[] = [];

  if (rangeEquity !== null) {
    metrics.push({
      label: "Range equity",
      value: rangeEquity,
      unit: "percent",
    });
  }
  if (realizedEquity !== null) {
    metrics.push({ label: "Realized", value: realizedEquity, unit: "percent" });
  }
  if (requiredEquity !== null && requiredEquity > 0) {
    metrics.push({
      label: "Call price",
      value: requiredEquity,
      unit: "percent",
    });
  }
  if (exploitabilityBb !== null && exploitabilityBb >= 0) {
    metrics.push({
      label: "Exploitability",
      value: exploitabilityBb,
      unit: "bb",
    });
  }
  if (handTopFraction !== null) {
    metrics.push({
      label: "Hand rank",
      value: handTopFraction,
      unit: "percent",
    });
  }
  if (policyFraction !== null) {
    metrics.push({
      label: "Chart range",
      value: policyFraction,
      unit: "percent",
    });
  }

  appendPreflopEvidence(raw, details);
  appendPostflopEvidence(raw, engine, details, ranges);
  const candidates = recommendationCandidatesFromRaw(raw, recommendation);

  const fallbackFrom = metadataString(raw.requested_engine, 80);
  const routingReason = metadataString(raw.routing_reason);
  const fallbackReason = routingReason ?? metadataString(raw.fallback_reason);
  if (
    metrics.length === 0 &&
    details.length === 0 &&
    ranges.length === 0 &&
    candidates.length === 0 &&
    !fallbackReason
  ) {
    return null;
  }
  return {
    engine: engine ? providerLabel(engine) : null,
    fallbackFrom: fallbackFrom ? providerLabel(fallbackFrom) : null,
    fallbackReason,
    routed: routingReason !== null,
    metrics,
    details,
    ranges,
    candidates,
  };
}
