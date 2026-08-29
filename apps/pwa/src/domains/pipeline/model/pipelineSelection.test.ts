import { describe, expect, it } from "vitest";

import type { PipelineCapabilities } from "../../../shared/types/pipeline";
import {
  compatiblePipelineLayouts,
  providerLabel,
  reconcilePipelineSelection,
} from "./pipelineSelection";

const capabilities = {
  defaults: {
    parser_layout_profile: "default_layout",
    parser_provider: "ocr_cv",
    recommendation_engine: "postflop_solver",
    recommendation_provider: "local_solver",
  },
  parser_layout_compatibility: {
    ocr_cv: ["default_layout"],
  },
  parser_layout_profiles: [
    {
      available: true,
      id: "default_layout",
      label: "Default layout",
      unavailable_reason: null,
    },
    {
      available: true,
      id: "alternate_layout",
      label: "Alternate layout",
      unavailable_reason: null,
    },
  ],
  parser_providers: [
    {
      available: true,
      id: "ocr_cv",
      label: "OCR",
      unavailable_reason: null,
    },
  ],
  administrative_ocr_test: { enabled: false },
  recommendation_engines: [
    {
      available: true,
      id: "postflop_solver",
      label: "Postflop solver",
      unavailable_reason: null,
    },
  ],
  recommendation_providers: [
    {
      available: true,
      id: "local_solver",
      label: "Local solver",
      unavailable_reason: null,
    },
    {
      available: true,
      id: "llm_advice",
      label: "LLM adviser",
      unavailable_reason: null,
    },
  ],
} as PipelineCapabilities;

describe("pipeline selection", () => {
  it("formats known and unknown provider identifiers", () => {
    expect(providerLabel("ocr_cv")).toBe("OCR + computer vision");
    expect(providerLabel("future_provider")).toBe("future provider");
  });

  it("returns only layouts compatible with the parser", () => {
    expect(compatiblePipelineLayouts(capabilities, "ocr_cv")).toEqual([
      capabilities.parser_layout_profiles[0],
    ]);
    expect(compatiblePipelineLayouts(capabilities, "future_provider")).toEqual(
      capabilities.parser_layout_profiles,
    );
  });

  it("reconciles unavailable choices and clears engines for remote providers", () => {
    expect(
      reconcilePipelineSelection(capabilities, {
        parser_layout_profile: "unavailable_layout",
        parser_provider: "unavailable_parser",
        recommendation_engine: "unavailable_engine",
        recommendation_provider: "llm_advice",
      }),
    ).toEqual({
      parser_layout_profile: "default_layout",
      parser_provider: "ocr_cv",
      recommendation_engine: null,
      recommendation_provider: "llm_advice",
    });
  });
});
