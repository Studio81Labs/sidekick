import { describe, expect, it } from "vitest";

import { shareModeLabel } from "./captureSource";

describe("shareModeLabel", () => {
  it.each([
    ["browser", "Tab"],
    ["window", "Window"],
    ["monitor", "Screen"],
  ] as const)("labels %s captures as %s", (mode, label) => {
    expect(shareModeLabel(mode)).toBe(label);
  });
});
