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
  metadataRecord,
  metadataStringList,
} from "./recommendationMetadata";

export function appendPostflopTreeEvidence(
  raw: Record<string, unknown>,
  details: RecommendationEvidenceDetail[],
): void {
  const heroPosition = metadataLabel(raw.hero_position);
  if (heroPosition && ["IP", "OOP"].includes(heroPosition)) {
    details.push({ label: "Position", value: heroPosition });
  }

  const modeledHistory = metadataStringList(raw.modeled_history);
  if (modeledHistory.length > 0) {
    details.push({
      label: "Modeled action",
      value: modeledHistory.join(" → "),
    });
  }

  const tree = metadataRecord(raw.tree);
  const startingPot = metadataNumber(tree?.starting_pot);
  const treeStack = metadataNumber(tree?.effective_stack);
  const treeParts: string[] = [];
  if (startingPot !== null && startingPot > 0) {
    treeParts.push(`${formatEvidenceBb(startingPot)} pot`);
  }
  if (treeStack !== null && treeStack >= 0) {
    treeParts.push(`${formatEvidenceBb(treeStack)} stack`);
  }
  if (treeParts.length > 0) {
    details.push({ label: "Tree", value: treeParts.join(" · ") });
  }

  const maxIterations = metadataNumber(tree?.max_iterations);
  const compressedMemoryMb = metadataNumber(tree?.compressed_memory_mb);
  const solveBudget: string[] = [];
  if (
    maxIterations !== null &&
    Number.isInteger(maxIterations) &&
    maxIterations > 0
  ) {
    solveBudget.push(`${maxIterations} iterations`);
  }
  if (compressedMemoryMb !== null && compressedMemoryMb >= 0) {
    solveBudget.push(`${formatEvidenceNumber(compressedMemoryMb)} MB estimate`);
  }
  if (solveBudget.length > 0) {
    details.push({ label: "Solve budget", value: solveBudget.join(" · ") });
  }

  const targetExploitability = metadataRatio(tree?.target_exploitability_ratio);
  if (targetExploitability !== null && targetExploitability > 0) {
    details.push({
      label: "Solve target",
      value: `${formatEvidenceRatio(targetExploitability)} pot exploitability`,
    });
  }
}
