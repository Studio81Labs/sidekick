import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import {
  formatEvidenceNumber,
  formatEvidenceRatio,
} from "./recommendationFormatting";
import {
  metadataLabel,
  metadataNumber,
  metadataRatio,
  metadataRecord,
  metadataString,
  metadataStringList,
} from "./recommendationMetadata";

export function rangeConditioningEvidence(
  value: unknown,
): RecommendationEvidenceDetail[] {
  const conditioning = metadataRecord(value);
  const status = metadataString(conditioning?.status, 20);
  if (!conditioning || (status !== "applied" && status !== "skipped")) {
    return [];
  }

  const details: RecommendationEvidenceDetail[] = [];
  const statusParts = [status === "applied" ? "Applied" : "Skipped"];
  if (status === "applied") {
    const completedStreets = metadataStringList(
      conditioning.completed_streets,
      2,
    )
      .map((street) => metadataLabel(street))
      .filter((street): street is string => street !== null);
    const decisionStreet = metadataLabel(conditioning.decision_street);
    const streets = decisionStreet
      ? [...completedStreets, decisionStreet]
      : completedStreets;
    if (streets.length > 0) {
      statusParts.push(streets.join(" → "));
    }
  } else {
    const reason = metadataString(conditioning.reason, 160);
    if (reason) {
      statusParts.push(reason);
    }
  }
  details.push({ label: "Range conditioning", value: statusParts.join(" · ") });

  if (status === "skipped") {
    const estimatedMemory = metadataNumber(
      conditioning.estimated_compressed_memory_mb,
    );
    const memoryLimit = metadataNumber(conditioning.max_memory_mb);
    const limitParts: string[] = [];
    if (estimatedMemory !== null && estimatedMemory >= 0) {
      limitParts.push(`${formatEvidenceNumber(estimatedMemory)} MB estimate`);
    }
    if (memoryLimit !== null && memoryLimit > 0) {
      limitParts.push(`${formatEvidenceNumber(memoryLimit)} MB limit`);
    }
    if (limitParts.length > 0) {
      details.push({
        label: "Conditioning limit",
        value: limitParts.join(" · "),
      });
    }
    return details;
  }

  const modeledHistory = metadataStringList(conditioning.modeled_history, 12);
  if (modeledHistory.length > 0) {
    details.push({
      label: "Conditioning line",
      value: modeledHistory.join(" → "),
    });
  }

  const activeHands = metadataRecord(conditioning.active_hands);
  const oopHands = metadataNumber(activeHands?.oop);
  const ipHands = metadataNumber(activeHands?.ip);
  const heroLineReach = metadataRatio(conditioning.hero_line_reach);
  const reachParts: string[] = [];
  if (heroLineReach !== null) {
    reachParts.push(`Hero ${formatEvidenceRatio(heroLineReach)}`);
  }
  if (oopHands !== null && Number.isInteger(oopHands) && oopHands > 0) {
    reachParts.push(`OOP ${oopHands} combos`);
  }
  if (ipHands !== null && Number.isInteger(ipHands) && ipHands > 0) {
    reachParts.push(`IP ${ipHands} combos`);
  }
  if (reachParts.length > 0) {
    details.push({ label: "Posterior reach", value: reachParts.join(" · ") });
  }

  const downstreamTree = metadataLabel(conditioning.downstream_tree);
  const compressedMemory = metadataNumber(conditioning.compressed_memory_mb);
  const conditioningExploitability = metadataRecord(
    conditioning.exploitability,
  );
  const exploitabilityBb = metadataNumber(conditioningExploitability?.bb);
  const solveParts: string[] = [];
  if (downstreamTree) {
    solveParts.push(downstreamTree);
  }
  if (compressedMemory !== null && compressedMemory >= 0) {
    solveParts.push(`${formatEvidenceNumber(compressedMemory)} MB estimate`);
  }
  if (exploitabilityBb !== null && exploitabilityBb >= 0) {
    solveParts.push(
      `${formatEvidenceNumber(exploitabilityBb, 3)} BB exploitability`,
    );
  }
  if (solveParts.length > 0) {
    details.push({
      label: "Conditioning solve",
      value: solveParts.join(" · "),
    });
  }

  return details;
}
