import { describe, expect, it } from "vitest";

import type {
  BenchmarkCaseResult,
  BenchmarkReport,
} from "../../../shared/types/benchmarks";
import {
  benchmarkCaseChanges,
  benchmarkCaseTrend,
  benchmarkCaseTrendMap,
} from "./benchmarkCaseComparison";

function benchmarkCase(
  overrides: Partial<BenchmarkCaseResult> = {},
): BenchmarkCaseResult {
  return {
    job_id: "job-1",
    original_filename: "hand.png",
    status: "completed",
    correct_fields: 1,
    evaluated_fields: 2,
    accuracy: 0.5,
    warnings: [],
    error: null,
    comparisons: [
      {
        field: "pot_bb",
        expected: 10,
        detected: 8,
        matched: false,
        confidence: 0.8,
      },
    ],
    ...overrides,
  };
}

function report(id: string, currentCase: BenchmarkCaseResult): BenchmarkReport {
  return {
    id,
    parser_provider: "ocr_cv",
    layout_profile: "fortuna",
    corpus_fingerprint: "corpus-1",
    created_at: "2026-08-15T08:00:00Z",
    total_cases: 1,
    successful_cases: 1,
    failed_cases: 0,
    correct_fields: currentCase.correct_fields,
    evaluated_fields: currentCase.evaluated_fields,
    accuracy: currentCase.accuracy,
    field_metrics: [],
    cases: [currentCase],
  };
}

describe("benchmark case comparison", () => {
  it("identifies recovered fields and explains their value change", () => {
    const previous = benchmarkCase();
    const current = benchmarkCase({
      correct_fields: 2,
      accuracy: 1,
      comparisons: [
        {
          field: "pot_bb",
          expected: 10,
          detected: 10,
          matched: true,
          confidence: 0.95,
        },
      ],
    });

    expect(benchmarkCaseTrend(current, previous)).toBe("recovered");
    expect(benchmarkCaseChanges(current, previous)).toEqual([
      expect.objectContaining({
        key: "pot_bb",
        trend: "recovered",
        previousValue: 8,
        currentValue: 10,
      }),
    ]);
  });

  it("maps trends only between comparable reports", () => {
    const previousCase = benchmarkCase();
    const currentCase = benchmarkCase({ accuracy: 0.25 });

    expect(
      benchmarkCaseTrendMap(
        report("current", currentCase),
        report("previous", previousCase),
      ).get("job-1"),
    ).toBe("regressed");
    expect(
      benchmarkCaseTrendMap(
        report("same", currentCase),
        report("same", previousCase),
      ),
    ).toEqual(new Map());
  });
});
