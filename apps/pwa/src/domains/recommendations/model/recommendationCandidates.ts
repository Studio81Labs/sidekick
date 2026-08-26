import type { RecommendationResult } from "../../../shared/types/recommendations";
import type { RecommendationEvidenceCandidate } from "./recommendationEvidenceTypes";
import {
  metadataNumber,
  metadataRatio,
  metadataRecord,
  metadataString,
} from "./recommendationMetadata";

export function recommendationCandidatesFromRaw(
  raw: Record<string, unknown>,
  recommendation: RecommendationResult,
): RecommendationEvidenceCandidate[] {
  const sortedCandidates = (Array.isArray(raw.candidates) ? raw.candidates : [])
    .flatMap((candidate): RecommendationEvidenceCandidate[] => {
      const record = metadataRecord(candidate);
      const action = metadataString(record?.action, 24);
      const ev = metadataNumber(record?.ev);
      const frequency = metadataRatio(record?.frequency);
      const foldEquity = metadataRatio(record?.fold_equity);
      const perOpponentFoldEquity = metadataRatio(
        record?.per_opponent_fold_equity,
      );
      const rawSizing = metadataNumber(record?.sizing);
      if (!record || !action || (ev === null && frequency === null)) {
        return [];
      }
      return [
        {
          action,
          sizing: rawSizing !== null && rawSizing >= 0 ? rawSizing : null,
          ev,
          frequency,
          foldEquity,
          perOpponentFoldEquity,
        },
      ];
    })
    .sort((left, right) => {
      if (left.ev !== null && right.ev !== null && left.ev !== right.ev) {
        return right.ev - left.ev;
      }
      if (left.ev === null && right.ev !== null) {
        return 1;
      }
      if (left.ev !== null && right.ev === null) {
        return -1;
      }
      return (right.frequency ?? 0) - (left.frequency ?? 0);
    });
  const chosenCandidateIndex = sortedCandidates.findIndex((candidate) =>
    candidateMatchesRecommendation(candidate, recommendation),
  );
  return chosenCandidateIndex >= 4
    ? [...sortedCandidates.slice(0, 3), sortedCandidates[chosenCandidateIndex]]
    : sortedCandidates.slice(0, 4);
}

export function candidateMatchesRecommendation(
  candidate: RecommendationEvidenceCandidate,
  recommendation: RecommendationResult,
): boolean {
  if (candidate.action !== recommendation.action) {
    return false;
  }
  if (recommendation.sizing === null) {
    return candidate.sizing === null;
  }
  return (
    candidate.sizing !== null &&
    Math.abs(candidate.sizing - recommendation.sizing) < 0.001
  );
}
