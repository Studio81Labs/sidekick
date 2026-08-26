import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  InputSourcePanel,
  type InputSourcePanelProps,
} from "./InputSourcePanel";

afterEach(cleanup);

function panelProps(
  overrides: Partial<InputSourcePanelProps> = {},
): InputSourcePanelProps {
  return {
    busy: false,
    files: [],
    inputMode: "live",
    livePreviewVisible: false,
    onCapture: vi.fn(),
    onFilesChange: vi.fn(),
    onInputModeChange: vi.fn(),
    onShareModeChange: vi.fn(),
    onStartOrViewShare: vi.fn(),
    onStopShare: vi.fn(),
    onUpload: vi.fn(),
    screenSharing: false,
    screenSourceLabel: null,
    shareMode: "window",
    ...overrides,
  };
}

describe("InputSourcePanel", () => {
  it("selects a share source and starts live sharing", async () => {
    const props = panelProps();
    render(<InputSourcePanel {...props} />);

    expect(screen.getByRole("button", { name: "Share window" })).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Capture and parse" }),
    ).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Tab" }));
    await userEvent.click(screen.getByRole("button", { name: "Share window" }));

    expect(props.onShareModeChange).toHaveBeenCalledWith("browser");
    expect(props.onStartOrViewShare).toHaveBeenCalledOnce();
  });

  it("shows active sharing controls and source context", async () => {
    const props = panelProps({
      screenSharing: true,
      screenSourceLabel: "PokerStars table",
      shareMode: "browser",
    });
    render(<InputSourcePanel {...props} />);

    expect(
      screen.getByText("PokerStars table sharing active"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View live tab" })).toBeEnabled();
    expect(
      within(
        screen.getByRole("group", { name: "Share source type" }),
      ).getByRole("button", { name: "Tab" }),
    ).toBeDisabled();
    await userEvent.click(
      screen.getByRole("button", { name: "Capture and parse" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Stop sharing" }));
    expect(props.onCapture).toHaveBeenCalledOnce();
    expect(props.onStopShare).toHaveBeenCalledOnce();
  });

  it("does not reopen a preview that is already visible", () => {
    render(
      <InputSourcePanel
        {...panelProps({ screenSharing: true, livePreviewVisible: true })}
      />,
    );

    expect(
      screen.getByRole("button", { name: "View live window" }),
    ).toBeDisabled();
  });

  it("normalizes selected files and uploads them", async () => {
    const props = panelProps({ inputMode: "upload" });
    const { rerender } = render(<InputSourcePanel {...props} />);
    const files = [
      new File(["one"], "flop.png", { type: "image/png" }),
      new File(["two"], "turn.png", { type: "image/png" }),
    ];

    expect(
      screen.getByRole("button", { name: "Upload and parse" }),
    ).toBeDisabled();
    await userEvent.upload(screen.getByLabelText("Choose screenshots"), files);
    expect(props.onFilesChange).toHaveBeenCalledWith(files);

    rerender(<InputSourcePanel {...props} files={files} />);
    expect(screen.getByText("2 screenshots selected")).toBeInTheDocument();
    expect(screen.getByText("2 selected for upload")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Upload and parse" }),
    );
    expect(props.onUpload).toHaveBeenCalledOnce();
  });
});
