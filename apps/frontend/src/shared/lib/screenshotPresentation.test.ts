import { describe, expect, it } from "vitest";

import { screenshotLabel } from "./screenshotPresentation";

describe("screenshotLabel", () => {
  it("prefers a normalized custom title", () => {
    expect(
      screenshotLabel({
        original_filename: "table.png",
        title: "  Button versus blind  ",
      }),
    ).toBe("Button versus blind");
  });

  it.each([null, undefined, "", "   "])(
    "falls back to the original filename for title %s",
    (title) => {
      expect(screenshotLabel({ original_filename: "table.png", title })).toBe(
        "table.png",
      );
    },
  );
});
