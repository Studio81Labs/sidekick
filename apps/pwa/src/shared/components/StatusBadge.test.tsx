import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders the neutral badge style by default", () => {
    render(<StatusBadge>Auto-saved</StatusBadge>);

    expect(screen.getByText("Auto-saved")).toHaveClass(
      "status-badge",
      "status-badge-neutral",
    );
  });

  it("applies tone, density, casing, and custom attributes", () => {
    render(
      <StatusBadge
        className="queue-status"
        data-state="approved"
        density="compact"
        tone="accent"
        uppercase
      >
        approved
      </StatusBadge>,
    );

    expect(screen.getByText("approved")).toHaveClass(
      "status-badge",
      "status-badge-accent",
      "status-badge-compact",
      "status-badge-uppercase",
      "queue-status",
    );
    expect(screen.getByText("approved")).toHaveAttribute(
      "data-state",
      "approved",
    );
  });
});
