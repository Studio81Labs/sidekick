import { describe, expect, it } from "vitest";

import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { appendPostflopRangeEvidence } from "./postflopRangeEvidence";

describe("postflop range evidence", () => {
  it("combines source, depth, verification, context, and exact ranges", () => {
    const details: RecommendationEvidenceDetail[] = [];
    const ranges: RecommendationEvidenceDetail[] = [];

    appendPostflopRangeEvidence(
      {
        range_source: "preflop_chart_single_raised_pot",
        range_context: {
          stack_depth_policy: "standard",
          starting_effective_stack_bb: 100,
          stack_depth_source: "reconstructed",
          decision_street: "turn",
          completed_street_count: 1,
          opener_position: "utg",
          caller_position: "ip",
          opening_size_bb: 2.5,
          opener_fraction: 0.2,
          caller_continue_fraction: 0.3,
          caller_reraise_fraction: 0.05,
        },
        ranges: { oop: "AA,KK", ip: "AKs,AQs" },
      },
      details,
      ranges,
    );

    expect(details).toEqual([
      {
        label: "Range source",
        value: "Preflop chart · single-raised pot",
      },
      { label: "Range depth", value: "Standard · 100 BB starting" },
      {
        label: "Range verification",
        value: "Turn · 1 completed street",
      },
      { label: "Range actors", value: "UTG opens 2.5 BB · IP calls" },
      { label: "Range bands", value: "Open 20% · flat 5%-30%" },
    ]);
    expect(ranges).toEqual([
      { label: "OOP", value: "AA,KK" },
      { label: "IP", value: "AKs,AQs" },
    ]);
  });

  it.each(["custom_ranges", "toString"])(
    "shows unknown source %s without trusting its context",
    (rangeSource) => {
      const details: RecommendationEvidenceDetail[] = [];

      appendPostflopRangeEvidence(
        {
          range_source: rangeSource,
          range_context: {
            stack_depth_policy: "deep",
            starting_effective_stack_bb: 200,
            stack_depth_source: "reconstructed",
          },
        },
        details,
        [],
      );

      expect(details).toEqual([
        {
          label: "Range source",
          value: rangeSource === "toString" ? "Tostring" : "Custom ranges",
        },
      ]);
    },
  );
});
