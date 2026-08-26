import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StateMessage } from "./StateMessage";

describe("StateMessage", () => {
  it("renders a default message and forwards container attributes", () => {
    render(
      <StateMessage className="history-empty" data-state="empty">
        No saved hands
      </StateMessage>,
    );

    expect(screen.getByText("No saved hands")).toHaveClass(
      "state-message",
      "history-empty",
    );
    expect(screen.getByText("No saved hands")).toHaveAttribute(
      "data-state",
      "empty",
    );
  });

  it("supports semantic elements and visual variants", () => {
    render(
      <StateMessage as="p" centered framed size="compact" tone="inverse">
        Reading results
      </StateMessage>,
    );

    expect(screen.getByText("Reading results")).toHaveClass(
      "state-message",
      "state-message-compact",
      "state-message-inverse",
      "state-message-centered",
      "state-message-framed",
    );
    expect(screen.getByText("Reading results").tagName).toBe("P");
  });

  it("preserves inline placeholders", () => {
    render(<StateMessage as="span">No pending reviews</StateMessage>);

    expect(screen.getByText("No pending reviews").tagName).toBe("SPAN");
  });
});
