import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BenchmarkPipelineComparison } from "./BenchmarkPipelineComparison";

afterEach(cleanup);

describe("BenchmarkPipelineComparison", () => {
  it("selects another available parser pipeline", async () => {
    const onSelectPipeline = vi.fn();
    const onRunComparison = vi.fn();

    render(
      <BenchmarkPipelineComparison
        comparisonProgress={null}
        includedCases={2}
        onRunComparison={onRunComparison}
        onSelectPipeline={onSelectPipeline}
        operationsLocked={false}
        overview={null}
        parserPipelines={[
          {
            parser: {
              id: "ocr_cv",
              label: "Local OCR",
              available: true,
              unavailable_reason: null,
            },
            layout_profile: "fortuna",
            latest_report: null,
          },
          {
            parser: {
              id: "vision",
              label: "Vision parser",
              available: true,
              unavailable_reason: null,
            },
            layout_profile: "automatic",
            latest_report: null,
          },
        ]}
        pipelineLoading={false}
        pipelineSelection={null}
        report={null}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", {
        name: "Use Vision parser benchmark pipeline",
      }),
    );
    expect(onSelectPipeline).toHaveBeenCalledWith("vision");

    await userEvent.click(
      screen.getByRole("button", { name: "Run comparison" }),
    );
    expect(onRunComparison).toHaveBeenCalledOnce();
  });
});
