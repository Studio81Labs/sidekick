import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TextInput } from "../../../shared/components/FormControls";
import { DetectedStateField } from "./DetectedStateField";

afterEach(cleanup);

describe("DetectedStateField", () => {
  it.each([
    [0.69, "field-low", "69%"],
    [0.7, "field-medium", "70%"],
    [0.85, "field-high", "85%"],
  ])("renders the confidence tone for %s", (confidence, tone, text) => {
    render(
      <DetectedStateField label="Pot" confidence={confidence}>
        <TextInput defaultValue="12.5" />
      </DetectedStateField>,
    );

    const input = screen.getByRole("textbox", {
      name: new RegExp(`^Pot\\s*${text.replace("%", "\\%")}$`),
    });
    expect(input.closest("label")).toHaveClass("field", tone);
    expect(
      input.closest("label")?.querySelector(".confidence-track > span"),
    ).toHaveStyle({ width: text });
  });

  it("marks missing confidence without inventing a percentage", () => {
    render(
      <DetectedStateField label="Hero position">
        <TextInput />
      </DetectedStateField>,
    );

    const input = screen.getByRole("textbox", {
      name: /^Hero position\s*not detected$/,
    });
    expect(input.closest("label")).toHaveClass("field-missing");
    expect(
      input.closest("label")?.querySelector(".confidence-track > span"),
    ).toHaveStyle({ width: "0%" });
  });

  it("supports explicit labels for manually reviewed fields", () => {
    render(
      <DetectedStateField label="Opponent stack" confidenceText="manual">
        <TextInput />
      </DetectedStateField>,
    );

    expect(
      screen.getByRole("textbox", { name: /^Opponent stack\s*manual$/ }),
    ).toBeInTheDocument();
  });

  it("treats invalid confidence values as missing", () => {
    render(
      <DetectedStateField label="Street" confidence={Number.NaN}>
        <TextInput />
      </DetectedStateField>,
    );

    expect(
      screen.getByRole("textbox", { name: /^Street\s*not detected$/ }),
    ).toBeInTheDocument();
  });
});
