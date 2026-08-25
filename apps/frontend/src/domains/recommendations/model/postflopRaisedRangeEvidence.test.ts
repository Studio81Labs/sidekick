import { describe, expect, it } from "vitest";

import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { appendPostflopRaisedRangeEvidence } from "./postflopRaisedRangeEvidence";

describe("postflop raised-pot range evidence", () => {
  it("presents cold four-bet actors, dead money, and continue bands", () => {
    const details: RecommendationEvidenceDetail[] = [];

    appendPostflopRaisedRangeEvidence(
      "preflop_chart_cold_four_bet_pot",
      {
        folded_opener_position: "utg",
        three_bettor_position: "cutoff",
        cold_four_bettor_position: "button",
        opening_size_bb: 2.5,
        three_bet_size_bb: 8,
        four_bet_size_bb: 20,
        folded_opener_commitment_bb: 2.5,
        cold_four_bettor_four_bet_fraction: 0.06,
        three_bettor_continue_fraction: 0.2,
        three_bettor_five_bet_fraction: 0.04,
      },
      details,
    );

    expect(details).toEqual([
      {
        label: "Range actors",
        value:
          "UTG opens 2.5 BB · Cutoff 3-bets 8 BB · Button cold 4-bets 20 BB · UTG folds 2.5 BB dead · Cutoff calls",
      },
      {
        label: "Range bands",
        value: "Cold 4-bet 6% · flat 4%-20%",
      },
    ]);
  });
});
