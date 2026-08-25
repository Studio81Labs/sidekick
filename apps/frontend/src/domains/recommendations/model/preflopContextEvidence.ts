import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { formatEvidenceBb } from "./recommendationFormatting";
import { metadataLabel, metadataNumber } from "./recommendationMetadata";

export function appendPreflopContextEvidence(
  raw: Record<string, unknown>,
  details: RecommendationEvidenceDetail[],
): void {
  const stackPolicy = metadataLabel(raw.stack_depth_policy);
  const effectiveStack = metadataNumber(raw.effective_stack);
  if (stackPolicy && effectiveStack !== null && effectiveStack >= 0) {
    details.push({
      label: "Stack depth",
      value: `${stackPolicy} · ${formatEvidenceBb(effectiveStack)}`,
    });
  }

  const committedOpponents = metadataNumber(raw.opponents_at_current_bet);
  const opponentWager = metadataNumber(raw.opponent_wager);
  const opponentCommitmentTotal = metadataNumber(raw.opponent_commitment_total);
  const heroWager = metadataNumber(raw.hero_wager);
  const hasCommittedOpponentCount =
    committedOpponents !== null &&
    Number.isInteger(committedOpponents) &&
    committedOpponents > 0;
  const hasOpponentWager = opponentWager !== null && opponentWager > 0;
  const hasDistinctCommitmentTotal =
    opponentCommitmentTotal !== null &&
    opponentCommitmentTotal > 0 &&
    (!hasCommittedOpponentCount ||
      !hasOpponentWager ||
      Math.abs(opponentCommitmentTotal - committedOpponents * opponentWager) >
        0.001);
  const hasHeroWager = heroWager !== null && heroWager > 0;
  if (
    !hasCommittedOpponentCount &&
    !hasOpponentWager &&
    !hasDistinctCommitmentTotal &&
    !hasHeroWager
  ) {
    return;
  }

  const context: string[] = [];
  if (hasCommittedOpponentCount) {
    context.push(
      `${committedOpponents} ${committedOpponents === 1 ? "opponent" : "opponents"}`,
    );
  }
  if (hasOpponentWager) {
    context.push(
      hasCommittedOpponentCount && committedOpponents === 1
        ? `${formatEvidenceBb(opponentWager)} committed`
        : `${formatEvidenceBb(opponentWager)} each`,
    );
  }
  if (hasDistinctCommitmentTotal) {
    context.push(`${formatEvidenceBb(opponentCommitmentTotal)} total`);
  }
  if (hasHeroWager) {
    context.push(`hero ${formatEvidenceBb(heroWager)}`);
  }
  details.push({
    label:
      hasCommittedOpponentCount || hasOpponentWager
        ? "At current wager"
        : "Existing commitments",
    value: context.join(" · "),
  });
}
