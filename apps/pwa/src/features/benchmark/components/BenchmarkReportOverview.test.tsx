import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { BenchmarkReport } from "../../../shared/types/benchmarks";
import { BenchmarkReportOverview } from "./BenchmarkReportOverview";

afterEach(cleanup);

const report: BenchmarkReport = {
  id: "current",
  parser_provider: "ocr_cv",
  layout_profile: "fortuna",
  corpus_fingerprint: "current-corpus",
  created_at: "2026-08-15T08:00:00Z",
  total_cases: 2,
  successful_cases: 2,
  failed_cases: 0,
  correct_fields: 15,
  evaluated_fields: 16,
  accuracy: 0.9375,
  field_metrics: [],
  cases: [],
};

describe("BenchmarkReportOverview", () => {
  it("shows report status and selects an earlier report", async () => {
    const onSelectReport = vi.fn();
    const previousReport = {
      ...report,
      id: "previous",
      created_at: "2026-08-14T08:00:00Z",
      accuracy: 0.875,
    };

    render(
      <BenchmarkReportOverview
        onSelectReport={onSelectReport}
        operationsLocked={false}
        overview={null}
        pipelineCapabilities={null}
        previousReport={previousReport}
        recentReports={[report, previousReport]}
        report={report}
        reportStale
      />,
    );

    expect(screen.getByLabelText("Benchmark summary")).toHaveTextContent("94%");
    expect(screen.getByRole("status")).toHaveTextContent(
      "not verified against the current ground truth",
    );

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Benchmark report" }),
      "previous",
    );
    expect(onSelectReport).toHaveBeenCalledWith("previous");
  });
});
