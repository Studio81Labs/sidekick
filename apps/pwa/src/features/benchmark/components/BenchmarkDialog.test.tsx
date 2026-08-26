import { createRef } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BenchmarkDialog, type BenchmarkDialogProps } from "./BenchmarkDialog";

afterEach(cleanup);

function dialogProps(
  overrides: Partial<BenchmarkDialogProps> = {},
): BenchmarkDialogProps {
  return {
    busy: false,
    comparisonProgress: null,
    comparisonReport: null,
    comparisonReportLoading: false,
    currentJob: null,
    datasetExportDisabled: true,
    datasetInputRef: createRef<HTMLInputElement>(),
    importInProgress: false,
    includedCases: 0,
    loading: false,
    onClose: vi.fn(),
    onChooseDatasetImport: vi.fn(),
    onDatasetImport: vi.fn(),
    onReviewCase: vi.fn(),
    onRun: vi.fn(),
    onRunComparison: vi.fn(),
    onSelectPipeline: vi.fn(),
    onSelectReport: vi.fn(),
    onToggleInclusion: vi.fn(),
    operationsLocked: false,
    overview: null,
    parserPipelines: [],
    pipelineCapabilities: null,
    pipelineLoading: false,
    pipelineSelection: null,
    previousReport: null,
    recentReports: [],
    report: null,
    reportLoading: false,
    reportParserLabel: null,
    reportStale: false,
    reviewJobId: null,
    running: false,
    targetLayoutLabel: null,
    updating: false,
    ...overrides,
  };
}

describe("BenchmarkDialog", () => {
  it("renders its empty state and closes from the header", async () => {
    const props = dialogProps();
    render(<BenchmarkDialog {...props} />);

    expect(
      screen.getByRole("dialog", { name: "Parser benchmark" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No benchmark has been run yet."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Run benchmark" }),
    ).toBeDisabled();

    await userEvent.click(
      screen.getByRole("button", { name: "Close parser benchmark" }),
    );
    expect(props.onClose).toHaveBeenCalledOnce();
  });
});
