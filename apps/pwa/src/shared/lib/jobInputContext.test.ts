import { describe, expect, it } from "vitest";

import { isAdministrativeTestJob } from "./jobInputContext";

describe("isAdministrativeTestJob", () => {
  it("treats only administrative_test as administrative", () => {
    expect(
      isAdministrativeTestJob({ input_context: "administrative_test" }),
    ).toBe(true);
    expect(isAdministrativeTestJob({ input_context: "legacy_player" })).toBe(
      false,
    );
    expect(isAdministrativeTestJob({})).toBe(false);
  });
});
