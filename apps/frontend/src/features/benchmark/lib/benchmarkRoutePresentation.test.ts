import { describe, expect, it } from "vitest";

import type { BenchmarkReport } from "../../../shared/types/benchmarks";
import { benchmarkParserRouteSummary } from "./benchmarkRoutePresentation";

const report: BenchmarkReport = {
  id: "report-1",
  parser_provider: "auto",
  layout_profile: "automatic",
  created_at: "2026-08-15T08:00:00Z",
  total_cases: 2,
  successful_cases: 1,
  failed_cases: 1,
  correct_fields: 3,
  evaluated_fields: 4,
  accuracy: 0.75,
  field_metrics: [],
  cases: [
    {
      job_id: "job-1",
      original_filename: "one.png",
      status: "completed",
      correct_fields: 2,
      evaluated_fields: 2,
      accuracy: 1,
      warnings: [],
      error: null,
      parser_routing: {
        provider: "auto",
        selected_provider: "ocr_cv",
        layout_profile: "automatic",
        fallback_from: null,
        fallback_reason: null,
      },
      comparisons: [],
    },
    {
      job_id: "job-2",
      original_filename: "two.png",
      status: "error",
      correct_fields: 1,
      evaluated_fields: 2,
      accuracy: 0.5,
      warnings: [],
      error: "Parser failed",
      parser_routing: {
        provider: "auto",
        selected_provider: "vision",
        layout_profile: "automatic",
        fallback_from: "ocr_cv",
        fallback_reason: "layout not calibrated",
      },
      comparisons: [],
    },
  ],
};

describe("benchmark parser route presentation", () => {
  it("aggregates attributed parser routes and fallback evidence", () => {
    expect(benchmarkParserRouteSummary(report)).toEqual({
      attributedCases: 2,
      routes: expect.arrayContaining([
        expect.objectContaining({
          provider: "ocr_cv",
          cases: 1,
          accuracy: 1,
        }),
        expect.objectContaining({
          provider: "vision",
          cases: 1,
          failedCases: 1,
          fallbackCases: 1,
          accuracy: 0.5,
        }),
      ]),
    });
  });

  it("does not attribute fixed-parser reports", () => {
    expect(
      benchmarkParserRouteSummary({ ...report, parser_provider: "ocr_cv" }),
    ).toEqual({ attributedCases: 0, routes: [] });
  });
});
