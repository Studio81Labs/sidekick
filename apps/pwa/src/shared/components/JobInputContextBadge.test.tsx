import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { JobInputContextBadge } from "./JobInputContextBadge";

afterEach(cleanup);

describe("JobInputContextBadge", () => {
  it("marks administrative test inputs", () => {
    render(
      <JobInputContextBadge job={{ input_context: "administrative_test" }} />,
    );

    expect(
      screen.getByLabelText("Administrative OCR test input"),
    ).toHaveTextContent("Admin test");
  });

  it("renders nothing for legacy player jobs", () => {
    const { container } = render(
      <JobInputContextBadge job={{ input_context: "legacy_player" }} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
