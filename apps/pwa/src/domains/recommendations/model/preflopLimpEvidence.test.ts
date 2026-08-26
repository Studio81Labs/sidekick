import { describe, expect, it } from "vitest";

import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { appendPreflopLimpEvidence } from "./preflopLimpEvidence";

describe("preflop limp evidence", () => {
  it("presents isolation and limp-reraise context in solver order", () => {
    const details: RecommendationEvidenceDetail[] = [];

    appendPreflopLimpEvidence(
      {
        limper_positions: ["utg", "button"],
        limper_position: "small_blind",
        limp_size: 1,
        limp_response_policy: "button pressure",
        isolation_raiser_position: "big_blind",
        isolation_raise_size: 4.5,
        isolation_raise_to_limp_ratio: 4.5,
        isolation_raise_size_policy: "standard",
        hero_isolation_raise_size: 4.5,
        limp_reraiser_position: "small_blind",
        limp_reraise_size: 14,
        limp_reraise_to_isolation_ratio: 3.111,
        limp_reraise_size_policy: "polar",
        limp_raise_fraction: 0.22,
        base_limp_raise_fraction: 0.25,
        target_limp_raise_size: 5,
      },
      details,
    );

    expect(details).toEqual([
      { label: "Limpers", value: "UTG · Button" },
      { label: "Hero limper", value: "Small blind" },
      { label: "Limp size", value: "1 BB" },
      { label: "Limp policy", value: "Button pressure" },
      { label: "Isolation raiser", value: "Big blind" },
      { label: "Isolation size", value: "4.5 BB · 4.5x limp · Standard" },
      { label: "Hero isolation", value: "4.5 BB" },
      { label: "Limp reraiser", value: "Small blind" },
      {
        label: "Limp-reraise size",
        value: "14 BB · 3.11x isolation · Polar",
      },
      { label: "Isolation range", value: "22% (base 25%)" },
      { label: "Isolation target", value: "5 BB" },
    ]);
  });

  it("presents multi-limp policy without single-limp metadata", () => {
    const details: RecommendationEvidenceDetail[] = [];

    appendPreflopLimpEvidence(
      {
        multi_limp_response_policy: "three limpers",
        multi_limp_raise_fraction: 0.12,
        base_multi_limp_raise_fraction: 0.18,
        target_multi_limp_raise_size: 7,
      },
      details,
    );

    expect(details).toEqual([
      { label: "Multi-limp policy", value: "Three limpers" },
      { label: "Multi-limp isolation range", value: "12% (base 18%)" },
      { label: "Isolation target", value: "7 BB" },
    ]);
  });
});
