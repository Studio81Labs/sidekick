import { createRef } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BenchmarkDialogActions,
  type BenchmarkDialogActionsProps,
} from "./BenchmarkDialogActions";

afterEach(cleanup);

function actionProps(
  overrides: Partial<BenchmarkDialogActionsProps> = {},
): BenchmarkDialogActionsProps {
  return {
    administrativeUnlocked: true,
    closeDisabled: false,
    datasetExportDisabled: false,
    datasetInputRef: createRef<HTMLInputElement>(),
    importInProgress: false,
    includedCases: 3,
    onChooseDatasetImport: vi.fn(),
    onClose: vi.fn(),
    onDatasetExport: vi.fn(),
    onDatasetImport: vi.fn(),
    onRun: vi.fn(),
    operationsLocked: false,
    pipelineSelection: null,
    running: false,
    targetLayoutLabel: "Fortuna",
    ...overrides,
  };
}

describe("BenchmarkDialogActions", () => {
  it("runs the benchmark and opens dataset import once unlocked", async () => {
    const props = actionProps();

    render(<BenchmarkDialogActions {...props} />);

    expect(screen.getByText("3").parentElement).toHaveTextContent(
      "3 ground-truth hands · Fortuna",
    );
    expect(
      screen.queryByText("Unlock administrator tools to import datasets."),
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Import dataset" }),
    );
    expect(props.onChooseDatasetImport).toHaveBeenCalledOnce();

    await userEvent.click(
      screen.getByRole("button", { name: "Run benchmark" }),
    );
    expect(props.onRun).toHaveBeenCalledOnce();
  });

  it("withholds dataset import while the administrator tools are locked", () => {
    render(
      <BenchmarkDialogActions
        {...actionProps({ administrativeUnlocked: false })}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Import dataset" }),
    ).toBeDisabled();
    expect(screen.getByLabelText("Parser dataset ZIP")).toBeDisabled();
    expect(
      screen.getByText("Unlock administrator tools to import datasets."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run benchmark" })).toBeEnabled();
  });
});
