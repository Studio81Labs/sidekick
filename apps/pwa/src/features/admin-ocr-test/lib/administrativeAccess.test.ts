import { describe, expect, it } from "vitest";

import {
  administrativeAccessDenial,
  administrativeAccessDenialMessage,
  normalizeAdministratorToken,
} from "./administrativeAccess";

describe("administrativeAccess", () => {
  it("normalizes surrounding whitespace only", () => {
    expect(normalizeAdministratorToken("  abc  ")).toBe("abc");
    expect(normalizeAdministratorToken("   ")).toBe("");
  });

  it("maps upload statuses to denials", () => {
    expect(administrativeAccessDenial(401)).toBe("unauthorized");
    expect(administrativeAccessDenial(403)).toBe("disabled");
    expect(administrativeAccessDenial(500)).toBeNull();
    expect(administrativeAccessDenial(429)).toBeNull();
  });

  it("describes each denial for the operator", () => {
    expect(administrativeAccessDenialMessage("disabled")).toBe(
      "Administrative OCR test mode is disabled on this deployment.",
    );
    expect(administrativeAccessDenialMessage("unauthorized")).toBe(
      "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
    );
  });
});
