import { createRef } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BenchmarkDialogActions } from "./BenchmarkDialogActions";

afterEach(cleanup);

describe("BenchmarkDialogActions", () => {
  it("runs the benchmark and opens dataset import", async () => {
    const onChooseDatasetImport = vi.fn();
    const onRun = vi.fn();

    render(
      <BenchmarkDialogActions
        closeDisabled={false}
        datasetExportDisabled={false}
        datasetInputRef={createRef<HTMLInputElement>()}
        importInProgress={false}
        includedCases={3}
        onChooseDatasetImport={onChooseDatasetImport}
        onClose={vi.fn()}
        onDatasetImport={vi.fn()}
        onRun={onRun}
        operationsLocked={false}
        pipelineSelection={null}
        running={false}
        targetLayoutLabel="Fortuna"
      />,
    );

    expect(screen.getByText("3").parentElement).toHaveTextContent(
      "3 ground-truth hands · Fortuna",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Import dataset" }),
    );
    expect(onChooseDatasetImport).toHaveBeenCalledOnce();

    await userEvent.click(
      screen.getByRole("button", { name: "Run benchmark" }),
    );
    expect(onRun).toHaveBeenCalledOnce();
  });
});
