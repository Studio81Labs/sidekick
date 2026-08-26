import { cleanup, render, screen, within } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { TablePreview, type TablePreviewProps } from "./TablePreview";

afterEach(cleanup);

function previewProps(
  overrides: Partial<TablePreviewProps> = {},
): TablePreviewProps {
  return {
    averageConfidence: 0,
    detectedFieldCount: 0,
    fieldCount: 12,
    frameLabel: "No table selected",
    frameStreet: "No street",
    livePreviewVisible: false,
    reviewCount: 0,
    screenSharing: false,
    screenshotUrl: null,
    ...overrides,
  };
}

describe("TablePreview", () => {
  it("renders the empty frame and confidence summary", () => {
    render(<TablePreview {...previewProps()} />);

    const preview = screen.getByRole("region", { name: "Poker table preview" });
    expect(preview).toHaveTextContent("No table selected");
    expect(preview).toHaveTextContent("No street");
    expect(screen.getByText("No screenshot uploaded")).toBeInTheDocument();
    const summary = screen.getByLabelText("Parser confidence summary");
    expect(
      within(summary).getByText("fields read").previousElementSibling,
    ).toHaveTextContent("0/12");
    expect(
      within(summary).getByText("avg confidence").previousElementSibling,
    ).toHaveTextContent("0%");
    expect(
      within(summary).getByText("need review").previousElementSibling,
    ).toHaveTextContent("0");
  });

  it("shows a parsed screenshot and review attention", () => {
    render(
      <TablePreview
        {...previewProps({
          averageConfidence: 76,
          detectedFieldCount: 9,
          frameLabel: "river-table.png",
          frameStreet: "river",
          reviewCount: 1,
          screenshotUrl: "/api/jobs/1/image",
        })}
      />,
    );

    const image = screen.getByRole("img", {
      name: "Uploaded poker table screenshot",
    });
    expect(image).toHaveAttribute("src", "/api/jobs/1/image");
    expect(image).not.toHaveClass("hidden");
    expect(screen.getByText("1")).toHaveClass("needs-review");
    expect(
      screen.queryByText("No screenshot uploaded"),
    ).not.toBeInTheDocument();
  });

  it("shows live video over a screenshot and forwards the video ref", () => {
    const videoRef = createRef<HTMLVideoElement>();
    render(
      <TablePreview
        {...previewProps({
          frameLabel: "PokerStars table live preview",
          livePreviewVisible: true,
          screenSharing: true,
          screenshotUrl: "/api/jobs/1/image",
        })}
        ref={videoRef}
      />,
    );

    expect(videoRef.current).toBe(
      screen.getByLabelText("Shared screen preview"),
    );
    expect(videoRef.current).toHaveClass("shared-preview", "active");
    expect(
      screen.getByRole("img", { name: "Uploaded poker table screenshot" }),
    ).toHaveClass("screenshot-preview", "hidden");
    expect(document.querySelector(".live-dot")).toHaveClass("active");
  });
});
