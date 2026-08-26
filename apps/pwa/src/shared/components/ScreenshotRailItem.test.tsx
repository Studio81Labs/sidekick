import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ScreenshotRailItem } from "./ScreenshotRailItem";

describe("ScreenshotRailItem", () => {
  it("opens and manages a screenshot through separate labeled controls", async () => {
    const onManage = vi.fn();
    const onOpen = vi.fn();
    render(
      <ScreenshotRailItem
        active
        attention
        className="batch-item"
        data-job="job-1"
        manageLabel="Manage screenshot 1: table.png"
        onManage={onManage}
        onOpen={onOpen}
        openClassName="batch-item-open"
        openLabel="Open screenshot 1: table.png"
      >
        <span>Table 1</span>
      </ScreenshotRailItem>,
    );

    const item = screen.getByText("Table 1").closest(".screenshot-rail-item");
    expect(item).toHaveClass("active", "attention", "batch-item");
    expect(item).toHaveAttribute("data-job", "job-1");

    const openButton = screen.getByRole("button", {
      name: "Open screenshot 1: table.png",
    });
    expect(openButton).toHaveClass(
      "screenshot-rail-item-open",
      "batch-item-open",
      "active",
      "attention",
    );
    await userEvent.click(openButton);
    await userEvent.click(
      screen.getByRole("button", { name: "Manage screenshot 1: table.png" }),
    );
    expect(onOpen).toHaveBeenCalledOnce();
    expect(onManage).toHaveBeenCalledOnce();
  });

  it("supports independent disabled states for opening and management", () => {
    render(
      <ScreenshotRailItem
        openDisabled
        manageLabel="Manage history item 1: saved.png"
        onManage={vi.fn()}
        onOpen={vi.fn()}
        openLabel="Reopen history item 1"
      >
        <span>Saved hand</span>
      </ScreenshotRailItem>,
    );

    expect(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", {
        name: "Manage history item 1: saved.png",
      }),
    ).toBeEnabled();
  });
});
