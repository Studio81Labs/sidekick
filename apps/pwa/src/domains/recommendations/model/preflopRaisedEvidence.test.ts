import { describe, expect, it } from "vitest";

import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { appendPreflopRaisedEvidence } from "./preflopRaisedEvidence";

describe("preflop raised-pot evidence", () => {
  it("presents opener, callers, squeeze, and four-bet context", () => {
    const details: RecommendationEvidenceDetail[] = [];

    appendPreflopRaisedEvidence(
      {
        opener_position: "utg",
        opener_open_fraction: 0.2,
        base_opener_open_fraction: 0.25,
        caller_positions: ["cutoff", "button"],
        caller_adjustment_policy: "two callers",
        squeeze_open_multiple: 5,
        opening_raise_size: 2.5,
        open_size_policy: "standard",
        hero_prior_commitment: 2.5,
        squeeze_response_policy: "button squeeze",
        three_bettor_position: "button",
        cold_three_bet_policy: "tight continue",
        three_bet_size: 11,
        three_bet_to_open_ratio: 4.4,
        three_bet_size_policy: "large",
        four_bettor_position: "small_blind",
        cold_four_bet_policy: "polar",
        four_bet_size: 27,
        four_bet_to_three_bet_ratio: 2.455,
        four_bet_size_policy: "compact",
      },
      details,
    );

    expect(details).toEqual([
      { label: "Opener", value: "UTG · 20% modeled (base 25%)" },
      { label: "Callers", value: "Cutoff · Button" },
      { label: "Caller adjustment", value: "Two callers · 5x squeeze" },
      { label: "Opening size", value: "2.5 BB · Standard" },
      { label: "Hero prior call", value: "2.5 BB" },
      { label: "Squeezer", value: "Button" },
      { label: "Squeeze policy", value: "Button squeeze" },
      { label: "Cold 3-bet policy", value: "Tight continue" },
      { label: "3-bet size", value: "11 BB · 4.4x · Large" },
      { label: "4-bettor", value: "Small blind" },
      { label: "Cold 4-bet policy", value: "Polar" },
      { label: "4-bet size", value: "27 BB · 2.46x · Compact" },
    ]);
  });
});
