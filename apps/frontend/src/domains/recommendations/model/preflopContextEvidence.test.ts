import { describe, expect, it } from "vitest";

import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { appendPreflopContextEvidence } from "./preflopContextEvidence";

describe("preflop context evidence", () => {
  it("presents stack depth and distinct current commitments", () => {
    const details: RecommendationEvidenceDetail[] = [];

    appendPreflopContextEvidence(
      {
        stack_depth_policy: "deep",
        effective_stack: 100,
        opponents_at_current_bet: 2,
        opponent_wager: 3,
        opponent_commitment_total: 7,
        hero_wager: 1,
      },
      details,
    );

    expect(details).toEqual([
      { label: "Stack depth", value: "Deep · 100 BB" },
      {
        label: "At current wager",
        value: "2 opponents · 3 BB each · 7 BB total · hero 1 BB",
      },
    ]);
  });

  it("does not repeat an aggregate equal to count times wager", () => {
    const details: RecommendationEvidenceDetail[] = [];

    appendPreflopContextEvidence(
      {
        opponents_at_current_bet: 2,
        opponent_wager: 4,
        opponent_commitment_total: 8,
      },
      details,
    );

    expect(details).toEqual([
      { label: "At current wager", value: "2 opponents · 4 BB each" },
    ]);
  });
});
