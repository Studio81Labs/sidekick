import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UserGuideDialog } from "./UserGuideDialog";

afterEach(cleanup);

describe("UserGuideDialog", () => {
  it("navigates between guide topics and closes", async () => {
    const onClose = vi.fn();
    render(<UserGuideDialog onClose={onClose} />);

    expect(
      screen.getByRole("dialog", {
        name: "How to use Poker Training Analyzer",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Analyze imported hand histories" }),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Next topic: Quick start" }),
    );
    expect(
      screen.getByRole("heading", { name: "Review your first hand" }),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Next topic: Input and queue" }),
    );
    expect(
      screen.getByRole("heading", { name: "Administrator OCR test tools" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Benchmark dataset import and application backup restore need the same credential/,
      ),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Close user guide" }),
    );
    expect(onClose).toHaveBeenCalledOnce();
  });
});
