import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ScreenshotDetailsDialog,
  type ScreenshotDetailsDialogProps,
} from "./ScreenshotDetailsDialog";
import type { JobRecord } from "../../../shared/types/jobs";

afterEach(cleanup);

function jobRecord(overrides: Partial<JobRecord> = {}): JobRecord {
  return {
    approved_state: null,
    archived_at: null,
    benchmark_included: false,
    created_at: "2026-08-14T10:00:00Z",
    error: null,
    id: "0123456789abcdef0123456789abcdef",
    image_filename: "table.png",
    original_filename: "table.png",
    parser_provider: "ocr_cv",
    parser_result: null,
    recommendation: null,
    recommendation_pending: false,
    recommendation_provider: "local_solver",
    status: "parsed",
    training_decision: null,
    training_review_note: null,
    training_reviewed_at: null,
    updated_at: "2026-08-14T10:00:00Z",
    ...overrides,
  };
}

function dialogProps(
  overrides: Partial<ScreenshotDetailsDialogProps> = {},
): ScreenshotDetailsDialogProps {
  return {
    deleteArmed: false,
    deleting: false,
    job: jobRecord(),
    metadataSaving: false,
    notes: "Review the river call.",
    onClose: vi.fn(),
    onDelete: vi.fn(),
    onDeleteArmedChange: vi.fn(),
    onNotesChange: vi.fn(),
    onSave: vi.fn(),
    onTagsChange: vi.fn(),
    onTitleChange: vi.fn(),
    persisted: true,
    recoveryPending: false,
    tags: "river, call",
    title: "River decision",
    ...overrides,
  };
}

describe("ScreenshotDetailsDialog", () => {
  it("renders persisted metadata and delegates edits and save", async () => {
    const props = dialogProps();
    render(<ScreenshotDetailsDialog {...props} />);

    expect(
      screen.getByRole("dialog", { name: "Screenshot details" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Processing queue")).toBeInTheDocument();
    expect(screen.getByDisplayValue("River decision")).toBeInTheDocument();
    expect(screen.getByDisplayValue("river, call")).toBeInTheDocument();

    await userEvent.clear(screen.getByRole("textbox", { name: "Title" }));
    await userEvent.type(
      screen.getByRole("textbox", { name: "Title" }),
      "Turn decision",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save details" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Delete screenshot" }),
    );

    expect(props.onTitleChange).toHaveBeenCalled();
    expect(props.onSave).toHaveBeenCalledOnce();
    expect(props.onDeleteArmedChange).toHaveBeenCalledWith(true);
  });

  it("shows the destructive confirmation and benchmark warning", async () => {
    const props = dialogProps({
      deleteArmed: true,
      job: jobRecord({ benchmark_included: true }),
    });
    render(<ScreenshotDetailsDialog {...props} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The image and all analysis data will be removed from the benchmark corpus too.",
    );
    expect(screen.getByText("Save details").closest("button")).toBeDisabled();
    fireEvent.submit(document.querySelector(".screenshot-details-form")!);

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Delete permanently" }),
    );

    expect(props.onDeleteArmedChange).toHaveBeenCalledWith(false);
    expect(props.onDelete).toHaveBeenCalledOnce();
    expect(props.onSave).not.toHaveBeenCalled();
  });

  it("explains and locks failed-upload deletion during recovery", () => {
    render(
      <ScreenshotDetailsDialog
        {...dialogProps({
          job: jobRecord({ id: "local-error-1", status: "error" }),
          persisted: false,
          recoveryPending: true,
        })}
      />,
    );

    expect(
      screen.getByText(
        "Checking whether this upload reached persistent storage before deletion.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: "Title" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Delete screenshot" }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Save details" }),
    ).not.toBeInTheDocument();
  });

  it("marks an administrative test job and leaves a legacy job unmarked", () => {
    const { rerender } = render(
      <ScreenshotDetailsDialog
        {...dialogProps({
          job: jobRecord({ input_context: "administrative_test" }),
        })}
      />,
    );

    expect(
      screen.getByLabelText("Administrative OCR test input"),
    ).toBeInTheDocument();

    rerender(<ScreenshotDetailsDialog {...dialogProps()} />);

    expect(
      screen.queryByLabelText("Administrative OCR test input"),
    ).not.toBeInTheDocument();
  });
});
