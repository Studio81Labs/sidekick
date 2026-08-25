import { describe, expect, it } from "vitest";

import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { appendPostflopLimpRangeEvidence } from "./postflopLimpRangeEvidence";

describe("postflop limp range evidence", () => {
  it("presents limped-pot actors, model, and range bands", () => {
    const details: RecommendationEvidenceDetail[] = [];

    expect(
      appendPostflopLimpRangeEvidence(
        "preflop_chart_limped_pot",
        {
          limper_position: "button",
          big_blind_position: "big_blind",
          limp_size_bb: 1,
          limper_fraction: 0.5,
          big_blind_raise_fraction: 0.2,
          limper_range_model: "stack_adjusted_first_in_proxy",
        },
        details,
      ),
    ).toBe(true);
    expect(details).toEqual([
      {
        label: "Range actors",
        value: "Button limps 1 BB · Big blind checks",
      },
      {
        label: "Range model",
        value: "Limper uses stack-adjusted first-in proxy",
      },
      { label: "Range bands", value: "Entry 50% · BB check 20%-100%" },
    ]);
  });

  it("leaves raised-pot sources for the next presenter", () => {
    expect(
      appendPostflopLimpRangeEvidence("preflop_chart_three_bet_pot", {}, []),
    ).toBe(false);
  });
});
