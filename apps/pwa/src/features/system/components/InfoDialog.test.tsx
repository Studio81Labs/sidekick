import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InfoDialog, type InfoDialogProps } from "./InfoDialog";

vi.mock("./McpAccessPanel", () => ({
  McpAccessPanel: ({
    onPendingTokenChange,
  }: {
    onPendingTokenChange?: (pending: boolean) => void;
  }) => (
    <button type="button" onClick={() => onPendingTokenChange?.(true)}>
      Simulate pending token
    </button>
  ),
}));

afterEach(cleanup);

function dialogProps(
  overrides: Partial<InfoDialogProps> = {},
): InfoDialogProps {
  return {
    backupDownloadUrl: "http://localhost:8000/api/backups/export",
    backupRestoring: false,
    busy: false,
    mcpTokenPending: false,
    onClose: vi.fn(),
    onMcpTokenPendingChange: vi.fn(),
    onRestoreBackup: vi.fn(),
    providers: {
      recognition: "External vision model",
      recognitionFallbackFrom: "OCR + computer vision",
      recognitionRoute: "Automatic recognition",
      recommendation: "Postflop solver",
    },
    systemInfoLoading: false,
    ...overrides,
  };
}

describe("InfoDialog", () => {
  it("renders active providers and delegates backup and MCP interactions", async () => {
    const props = dialogProps();
    render(<InfoDialog {...props} />);
    const dialog = screen.getByRole("dialog", {
      name: "About Poker Training Analyzer",
    });

    expect(
      within(dialog).getByText("External vision model"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "via Automatic recognition · fallback from OCR + computer vision",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Postflop solver")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("link", {
        name: "Download application backup",
      }),
    ).toHaveAttribute("href", props.backupDownloadUrl);

    const backup = new File(["backup"], "poker-hero-backup.zip", {
      type: "application/zip",
    });
    const input = within(dialog).getByLabelText("Application backup ZIP");
    await userEvent.upload(input, backup);
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Simulate pending token" }),
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Close app information" }),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));

    expect(props.onRestoreBackup).toHaveBeenCalledWith(backup);
    expect(input).toHaveValue("");
    expect(props.onMcpTokenPendingChange).toHaveBeenCalledWith(true);
    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  it("distinguishes loading from unavailable provider details", () => {
    const { rerender } = render(
      <InfoDialog
        {...dialogProps({ providers: null, systemInfoLoading: true })}
      />,
    );

    expect(
      screen.getByText("Reading backend configuration..."),
    ).toBeInTheDocument();

    rerender(
      <InfoDialog
        {...dialogProps({ providers: null, systemInfoLoading: false })}
      />,
    );

    expect(
      screen.getByText("Active engine details are unavailable."),
    ).toBeInTheDocument();
  });

  it("locks close and recovery controls while a restore is active", () => {
    render(
      <InfoDialog
        {...dialogProps({
          backupRestoring: true,
          busy: true,
          mcpTokenPending: true,
        })}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Close app information" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Done" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Restore application backup" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("link", { name: "Download application backup" }),
    ).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText("Restoring...")).toBeInTheDocument();
  });
});
