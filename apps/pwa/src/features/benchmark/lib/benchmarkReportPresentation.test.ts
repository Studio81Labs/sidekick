import { describe, expect, it } from "vitest";

import type {
  BenchmarkParserPipelineSummary,
  BenchmarkReport,
} from "../../../shared/types/benchmarks";
import {
  benchmarkCorpusFingerprintAfterLayoutMutation,
  benchmarkCorpusIsUnverified,
  benchmarkPipelinePointChange,
  benchmarkReportSummary,
  benchmarkReportsAreComparable,
  previousComparableBenchmarkReport,
} from "./benchmarkReportPresentation";

function report(overrides: Partial<BenchmarkReport> = {}): BenchmarkReport {
  return {
    id: "current",
    parser_provider: "ocr_cv",
    layout_profile: "fortuna",
    corpus_fingerprint: "corpus-1",
    created_at: "2026-08-15T08:00:00Z",
    total_cases: 2,
    successful_cases: 2,
    failed_cases: 0,
    correct_fields: 16,
    evaluated_fields: 16,
    accuracy: 1,
    field_metrics: [],
    cases: [],
    ...overrides,
  };
}

describe("benchmark report presentation", () => {
  it("summarizes reports and keeps corpus mutations scoped by layout", () => {
    const current = report();

    expect(benchmarkReportSummary(current)).toMatchObject({
      id: "current",
      accuracy: 1,
      field_metrics: [],
    });
    expect(benchmarkCorpusIsUnverified("corpus-1", "corpus-1")).toBe(false);
    expect(benchmarkCorpusIsUnverified(null, "corpus-1")).toBe(true);
    expect(
      benchmarkCorpusFingerprintAfterLayoutMutation(
        "corpus-1",
        "pokerstars",
        "fortuna",
      ),
    ).toBe("corpus-1");
    expect(
      benchmarkCorpusFingerprintAfterLayoutMutation(
        "corpus-1",
        "fortuna",
        "fortuna",
      ),
    ).toBeUndefined();
  });

  it("selects only a comparable previous report", () => {
    const current = report();
    const previous = benchmarkReportSummary(
      report({ id: "previous", accuracy: 0.75 }),
    );
    const wrongParser = {
      ...previous,
      id: "wrong-parser",
      parser_provider: "vision",
    };

    expect(
      previousComparableBenchmarkReport(
        current,
        [benchmarkReportSummary(current), wrongParser, previous],
        [],
      ),
    ).toEqual(previous);
    expect(
      benchmarkReportsAreComparable(
        current,
        report({ id: "previous", accuracy: 0.75 }),
      ),
    ).toBe(true);
    expect(
      benchmarkReportsAreComparable(
        current,
        report({ id: "stale", corpus_fingerprint: "corpus-2" }),
      ),
    ).toBe(false);
  });

  it("reports pipeline movement only for verified reports", () => {
    const latest = benchmarkReportSummary(report({ accuracy: 0.9 }));
    const previous = benchmarkReportSummary(
      report({ id: "previous", accuracy: 0.7 }),
    );
    const pipeline: BenchmarkParserPipelineSummary = {
      parser: {
        id: "ocr_cv",
        label: "Local OCR",
        available: true,
        unavailable_reason: null,
      },
      layout_profile: "fortuna",
      latest_report: latest,
      previous_report: previous,
    };

    expect(benchmarkPipelinePointChange(pipeline, "corpus-1")).toBe(20);
    expect(benchmarkPipelinePointChange(pipeline, "corpus-2")).toBeNull();
  });
});
