import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SummaryMetric } from "./SummaryMetric";

describe("SummaryMetric", () => {
  it("renders a value and label with forwarded container attributes", () => {
    render(
      <SummaryMetric
        className="toolbar-stat"
        data-metric="queue"
        label="in queue"
        value={4}
      />,
    );

    const metric = screen.getByText("in queue").closest("div");
    expect(metric).toHaveClass("summary-metric", "toolbar-stat");
    expect(metric).toHaveAttribute("data-metric", "queue");
    expect(metric).toHaveTextContent("4in queue");
  });

  it("supports nested values, small labels, and attention styling", () => {
    render(
      <SummaryMetric
        attention
        label="need review"
        labelElement="small"
        value={
          <>
            9<span>/12</span>
          </>
        }
      />,
    );

    expect(screen.getByText("9")).toHaveClass("needs-review");
    expect(screen.getByText("/12")).toBeInTheDocument();
    expect(screen.getByText("need review").tagName).toBe("SMALL");
  });
});
