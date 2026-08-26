import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BenchmarkReport } from "../../../shared/types/benchmarks";
import { BenchmarkCaseResults } from "./BenchmarkCaseResults";

afterEach(cleanup);

const report: BenchmarkReport = {
  id: "current",
  parser_provider: "ocr_cv",
  layout_profile: "fortuna",
  created_at: "2026-08-15T08:00:00Z",
  total_cases: 1,
  successful_cases: 1,
  failed_cases: 0,
  correct_fields: 1,
  evaluated_fields: 2,
  accuracy: 0.5,
  field_metrics: [],
  cases: [
    {
      job_id: "job-1",
      original_filename: "river.png",
      status: "completed",
      correct_fields: 1,
      evaluated_fields: 2,
      accuracy: 0.5,
      warnings: [],
      error: null,
      comparisons: [
        {
          field: "pot_bb",
          expected: 12,
          detected: 10,
          matched: false,
          confidence: 0.8,
        },
      ],
    },
  ],
};

describe("BenchmarkCaseResults", () => {
  it("expands a mismatch and opens the source hand", async () => {
    const onReviewCase = vi.fn();
    render(
      <BenchmarkCaseResults
        comparisonReport={null}
        comparisonReportLoading={false}
        onReviewCase={onReviewCase}
        operationsLocked={false}
        previousReport={null}
        report={report}
        reviewJobId={null}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", {
        name: "Toggle river.png benchmark details",
      }),
    );
    expect(screen.getByText("Expected")).toBeInTheDocument();
    expect(screen.getByText("Detected")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Review hand" }));
    expect(onReviewCase).toHaveBeenCalledWith("job-1");
  });
});
