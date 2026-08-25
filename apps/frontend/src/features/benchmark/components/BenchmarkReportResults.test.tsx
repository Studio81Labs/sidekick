import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BenchmarkReport } from "../../../shared/types/benchmarks";
import { BenchmarkReportResults } from "./BenchmarkReportResults";

afterEach(cleanup);

const report: BenchmarkReport = {
  id: "report-1",
  parser_provider: "auto",
  layout_profile: "automatic",
  created_at: "2026-08-15T08:00:00Z",
  total_cases: 1,
  successful_cases: 1,
  failed_cases: 0,
  correct_fields: 2,
  evaluated_fields: 2,
  accuracy: 1,
  field_metrics: [{ field: "hero_cards", correct: 1, total: 1, accuracy: 1 }],
  cases: [
    {
      job_id: "job-1",
      original_filename: "flop.png",
      status: "completed",
      correct_fields: 2,
      evaluated_fields: 2,
      accuracy: 1,
      warnings: [],
      error: null,
      parser_routing: {
        provider: "auto",
        selected_provider: "ocr_cv",
        layout_profile: "fortuna",
        fallback_from: null,
        fallback_reason: null,
      },
      comparisons: [],
    },
  ],
};

describe("BenchmarkReportResults", () => {
  it("renders parser attribution, field accuracy, and cases", () => {
    render(
      <BenchmarkReportResults
        comparisonReport={null}
        comparisonReportLoading={false}
        onReviewCase={vi.fn()}
        operationsLocked={false}
        previousReport={null}
        report={report}
        reviewJobId={null}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Parser routes" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Field accuracy" }),
    ).toBeInTheDocument();
    expect(screen.getByText("hero cards")).toBeInTheDocument();
    expect(screen.getByText("flop.png")).toBeInTheDocument();
  });
});
