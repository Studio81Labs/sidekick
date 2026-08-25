import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { JobStatusBadge } from "./JobStatusBadge";
import type { JobRecord } from "../types/jobs";

afterEach(cleanup);

describe("JobStatusBadge", () => {
  it.each([
    ["created", "status-badge-neutral"],
    ["parsed", "status-badge-neutral"],
    ["approved", "status-badge-accent"],
    ["recommended", "status-badge-accent"],
    ["error", "status-badge-attention"],
  ] satisfies Array<[JobRecord["status"], string]>)(
    "maps %s jobs to the expected tone",
    (status, toneClassName) => {
      render(<JobStatusBadge status={status} />);

      expect(screen.getByText(status)).toHaveClass(
        "status-badge-uppercase",
        toneClassName,
      );
    },
  );
});
