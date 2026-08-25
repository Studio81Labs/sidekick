import { describe, expect, it } from "vitest";

import { PERSISTED_JOB_ID_PATTERN } from "./jobIdentity";

describe("job identity", () => {
  it("accepts only lowercase 32-character persisted job ids", () => {
    expect(PERSISTED_JOB_ID_PATTERN.test("a".repeat(32))).toBe(true);
    expect(PERSISTED_JOB_ID_PATTERN.test("A".repeat(32))).toBe(false);
    expect(PERSISTED_JOB_ID_PATTERN.test("a".repeat(31))).toBe(false);
  });
});
