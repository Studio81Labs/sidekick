import { describe, expect, it } from "vitest";

import {
  MAX_SCREENSHOT_TAG_LENGTH,
  MAX_SCREENSHOT_TAGS,
  parseScreenshotTags,
  screenshotTags,
} from "./screenshotMetadata";

describe("screenshot metadata", () => {
  it("normalizes comma-separated tags and removes case-insensitive duplicates", () => {
    expect(parseScreenshotTags(" turn, bluff, TURN, , river ")).toEqual([
      "turn",
      "bluff",
      "river",
    ]);
  });

  it("rejects tags that exceed the field limits", () => {
    expect(() =>
      parseScreenshotTags("x".repeat(MAX_SCREENSHOT_TAG_LENGTH + 1)),
    ).toThrow(`Tags can be at most ${MAX_SCREENSHOT_TAG_LENGTH} characters`);
    expect(() =>
      parseScreenshotTags(
        Array.from(
          { length: MAX_SCREENSHOT_TAGS + 1 },
          (_, index) => `tag-${index}`,
        ).join(","),
      ),
    ).toThrow(`Use no more than ${MAX_SCREENSHOT_TAGS} tags`);
  });

  it("reads only string tags from persisted jobs", () => {
    expect(
      screenshotTags({
        tags: ["turn", 5, null, "river"] as unknown as string[],
      }),
    ).toEqual(["turn", "river"]);
    expect(screenshotTags({ tags: undefined })).toEqual([]);
  });
});
