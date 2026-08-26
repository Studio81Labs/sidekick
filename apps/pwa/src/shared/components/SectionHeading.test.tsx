import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SectionHeading } from "./SectionHeading";

describe("SectionHeading", () => {
  it("connects a semantic heading to its section", () => {
    render(
      <section aria-labelledby="coverage-title">
        <SectionHeading heading="Solver coverage" headingId="coverage-title" />
      </section>,
    );

    expect(
      screen.getByRole("region", { name: "Solver coverage" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: "Solver coverage" }),
    ).toHaveAttribute("id", "coverage-title");
  });

  it("renders trailing content and forwards container attributes", () => {
    render(
      <SectionHeading
        className="training-heading"
        data-section="street"
        heading="By street"
        headingId="street-title"
      >
        <button type="button">Focus flop</button>
      </SectionHeading>,
    );

    const heading = screen.getByRole("heading", { name: "By street" });
    expect(heading.parentElement).toHaveClass(
      "section-heading",
      "training-heading",
    );
    expect(heading.parentElement).toHaveAttribute("data-section", "street");
    expect(
      screen.getByRole("button", { name: "Focus flop" }),
    ).toBeInTheDocument();
  });
});
