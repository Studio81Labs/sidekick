import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InfoDialog, type InfoDialogProps } from "./InfoDialog";

afterEach(cleanup);

function dialogProps(
  overrides: Partial<InfoDialogProps> = {},
): InfoDialogProps {
  return {
    administrativeUnlocked: true,
    backupRestoring: false,
    busy: false,
    onClose: vi.fn(),
    onDownloadBackup: vi.fn(),
    onRestoreBackup: vi.fn(),
    providers: {
      recognition: "External vision model",
      recognitionFallbackFrom: "OCR + computer vision",
      recognitionRoute: "Automatic recognition",
    },
    systemInfoLoading: false,
    ...overrides,
  };
}

describe("InfoDialog", () => {
  it("renders active providers and delegates backup interactions", async () => {
    const props = dialogProps();
    render(<InfoDialog {...props} />);
    const dialog = screen.getByRole("dialog", {
      name: "About Poker Hero",
    });

    expect(
      within(dialog).getByText("External vision model"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "via Automatic recognition · fallback from OCR + computer vision",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByText("Recommendation"),
    ).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Agent access")).not.toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Back up screenshots, approved ground truth, and benchmark reports in one portable ZIP.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Download application backup",
      }),
    ).toBeEnabled();
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: "Download application backup",
      }),
    );

    const backup = new File(["backup"], "poker-hero-backup.zip", {
      type: "application/zip",
    });
    const input = within(dialog).getByLabelText("Application backup ZIP");
    await userEvent.upload(input, backup);
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Close app information" }),
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));

    expect(props.onRestoreBackup).toHaveBeenCalledWith(backup);
    expect(props.onDownloadBackup).toHaveBeenCalledOnce();
    expect(input).toHaveValue("");
    expect(props.onClose).toHaveBeenCalledTimes(2);
    expect(
      within(dialog).queryByText(
        "Unlock administrator tools to restore a backup.",
      ),
    ).not.toBeInTheDocument();
  });

  it("withholds the restore control while the administrator tools are locked", () => {
    render(<InfoDialog {...dialogProps({ administrativeUnlocked: false })} />);

    expect(
      screen.getByRole("button", { name: "Restore application backup" }),
    ).toBeDisabled();
    expect(screen.getByLabelText("Application backup ZIP")).toBeDisabled();
    expect(
      screen.getByText("Unlock administrator tools to restore a backup."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Download application backup" }),
    ).toBeEnabled();
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
      screen.getByRole("button", { name: "Download application backup" }),
    ).toBeDisabled();
    expect(screen.getByText("Restoring...")).toBeInTheDocument();
  });
});
