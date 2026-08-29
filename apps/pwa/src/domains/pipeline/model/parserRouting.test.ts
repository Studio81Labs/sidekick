import { describe, expect, it } from "vitest";

import { parserRoutingEvidence, parserRoutingFromRaw } from "./parserRouting";

describe("parser routing", () => {
  it("presents a complete parser route", () => {
    expect(
      parserRoutingFromRaw({
        parser_routing: {
          provider: "auto",
          selected_provider: "ocr_cv",
          layout_profile: "fortuna",
          fallback_from: "pokerstars_ocr",
          fallback_reason: "Layout confidence was too low",
        },
      }),
    ).toEqual({
      provider: "auto",
      selectedProvider: "ocr_cv",
      layoutProfile: "fortuna",
      fallbackFrom: "pokerstars_ocr",
      fallbackReason: "Layout confidence was too low",
    });
  });

  it("drops partial fallback metadata and rejects incomplete routes", () => {
    expect(
      parserRoutingEvidence({
        provider: "auto",
        selected_provider: "ocr_cv",
        layout_profile: "fortuna",
        fallback_from: "pokerstars_ocr",
      }),
    ).toMatchObject({ fallbackFrom: null, fallbackReason: null });
    expect(parserRoutingEvidence({ provider: "auto" })).toBeNull();
    expect(parserRoutingFromRaw([])).toBeNull();
  });

  it("truncates over-long routing metadata", () => {
    expect(
      parserRoutingEvidence({
        provider: "auto",
        selected_provider: "ocr_cv",
        layout_profile: "f".repeat(70),
        fallback_from: "pokerstars_ocr",
        fallback_reason: "r".repeat(400),
      }),
    ).toMatchObject({
      layoutProfile: `${"f".repeat(61)}...`,
      fallbackReason: `${"r".repeat(317)}...`,
    });
  });
});
