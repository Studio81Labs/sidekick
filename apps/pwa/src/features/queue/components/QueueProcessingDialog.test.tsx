import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  QueueProcessingDialog,
  type QueueProcessingDialogProps,
} from "./QueueProcessingDialog";

afterEach(cleanup);

function dialogProps(
  overrides: Partial<QueueProcessingDialogProps> = {},
): QueueProcessingDialogProps {
  return {
    onAbort: vi.fn(),
    progress: {
      aborting: false,
      completed: 1,
      currentFile: "second.png",
      currentIndex: 2,
      failed: 1,
      skipped: 0,
      total: 4,
    },
    ...overrides,
  };
}

describe("QueueProcessingDialog", () => {
  it("renders progress and delegates abort", async () => {
    const props = dialogProps();
    render(<QueueProcessingDialog {...props} />);

    expect(
      screen.getByRole("dialog", { name: "Processing queue" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Screenshot 2 of 4")).toBeInTheDocument();
    expect(screen.getByText("second.png")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(document.querySelector(".processing-progress > span")).toHaveStyle({
      width: "25%",
    });
    expect(
      screen.getByText("processed").previousElementSibling,
    ).toHaveTextContent("1");
    expect(
      screen.getByText("attention").previousElementSibling,
    ).toHaveTextContent("1");
    expect(
      screen.getByText("discarded").previousElementSibling,
    ).toHaveTextContent("0");

    await userEvent.click(
      screen.getByRole("button", { name: "Abort and discard unprocessed" }),
    );

    expect(props.onAbort).toHaveBeenCalledOnce();
  });

  it("renders preparation and stopping states", () => {
    const { rerender } = render(
      <QueueProcessingDialog
        {...dialogProps({
          progress: {
            aborting: false,
            completed: 0,
            currentFile: "",
            currentIndex: 0,
            failed: 0,
            skipped: 0,
            total: 3,
          },
        })}
      />,
    );

    expect(screen.getByText("Preparing 3 screenshots")).toBeInTheDocument();
    expect(screen.getByText("Preparing queue")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();

    rerender(
      <QueueProcessingDialog
        {...dialogProps({
          progress: {
            aborting: true,
            completed: 2,
            currentFile: "third.png",
            currentIndex: 3,
            failed: 0,
            skipped: 1,
            total: 3,
          },
        })}
      />,
    );

    expect(
      screen.getByRole("dialog", { name: "Stopping import" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Discarding unprocessed screenshots"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Abort and discard unprocessed" }),
    ).toBeDisabled();
  });

  it("keeps progress percentages finite for an empty snapshot", () => {
    render(
      <QueueProcessingDialog
        {...dialogProps({
          progress: {
            aborting: false,
            completed: 0,
            currentFile: "",
            currentIndex: 0,
            failed: 0,
            skipped: 0,
            total: 0,
          },
        })}
      />,
    );

    expect(screen.getByText("0%")).toBeInTheDocument();
    expect(document.querySelector(".processing-progress > span")).toHaveStyle({
      width: "0%",
    });
  });
});
