import { describe, expect, it } from "vitest";

import {
  administrativeAccessDenial,
  administrativeAccessDenialMessage,
  normalizeAdministratorToken,
  unlockFailureMessage,
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

  it("explains every way a server-verified unlock can fail", () => {
    expect(unlockFailureMessage("blank")).toBe(
      "Enter the administrative OCR test token.",
    );
    expect(unlockFailureMessage("unauthorized")).toBe(
      administrativeAccessDenialMessage("unauthorized"),
    );
    expect(unlockFailureMessage("disabled")).toBe(
      administrativeAccessDenialMessage("disabled"),
    );
    expect(unlockFailureMessage("unavailable")).toBe(
      "Could not verify the administrative OCR test token. Check the connection and try again.",
    );
  });
});
