import { describe, expect, it } from "vitest";

import * as presentation from "./recommendationPresentation";

describe("recommendation presentation compatibility barrel", () => {
  it("keeps the established runtime export surface", () => {
    expect(Object.keys(presentation).sort()).toEqual(
      [
        "POSTFLOP_RANGE_SOURCE_LABELS",
        "candidateMatchesRecommendation",
        "formatEvidenceBb",
        "formatEvidenceMetric",
        "formatEvidenceNumber",
        "formatEvidenceRatio",
        "parserRoutingEvidence",
        "parserRoutingFromRaw",
        "rangeConditioningEvidence",
        "recommendationContextLabel",
        "recommendationEvidenceFromRaw",
      ].sort(),
    );
  });
});
