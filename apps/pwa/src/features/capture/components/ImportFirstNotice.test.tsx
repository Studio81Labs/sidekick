import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ImportFirstNotice } from "./ImportFirstNotice";

afterEach(cleanup);

describe("ImportFirstNotice", () => {
  it("explains the import-first player path without exposing capture controls", () => {
    render(<ImportFirstNotice />);

    expect(screen.getByRole("region", { name: "Input" })).toHaveTextContent(
      "Screenshot upload and live capture are administrator-only parser test tools",
    );
    expect(
      screen.queryByLabelText("Choose screenshots"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "Input mode" }),
    ).not.toBeInTheDocument();
  });
});
