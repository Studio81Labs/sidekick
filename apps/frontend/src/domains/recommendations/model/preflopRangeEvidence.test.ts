import { describe, expect, it } from "vitest";

import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { appendPreflopRangeEvidence } from "./preflopRangeEvidence";

describe("preflop range evidence", () => {
  it("presents response, opening, sizing, and the highest-priority cap", () => {
    const details: RecommendationEvidenceDetail[] = [];

    appendPreflopRangeEvidence(
      {
        continue_fraction: 0.4,
        reraise_fraction: 0.12,
        four_bet_fraction: 0.06,
        five_bet_fraction: 0.02,
        open_fraction: 0.28,
        base_open_fraction: 0.32,
        target_open_size: 2.5,
        maximum_five_bet_total: 80,
        maximum_four_bet_total: 50,
        maximum_reraise_total: 30,
      },
      details,
    );

    expect(details).toEqual([
      {
        label: "Response range",
        value: "Continue 40% · Reraise 12% · Four-bet 6% · Five-bet 2%",
      },
      { label: "Opening range", value: "28% (base 32%)" },
      { label: "Open target", value: "2.5 BB" },
      { label: "All-in cap", value: "80 BB" },
    ]);
  });
});
