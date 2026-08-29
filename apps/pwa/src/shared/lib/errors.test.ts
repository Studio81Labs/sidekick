import { describe, expect, it } from "vitest";

import {
  ERROR_TOAST_ID,
  VALIDATION_TOAST_ID,
  isAbortError,
  messageFromError,
  mutationFailureMayHavePersistedSideEffect,
} from "./errors";

describe("shared error primitives", () => {
  it("keeps stable toast IDs and readable fallback behavior", () => {
    expect(ERROR_TOAST_ID).toBe("poker-training-error");
    expect(VALIDATION_TOAST_ID).toBe("poker-training-validation");
    expect(messageFromError(new Error("offline"), "fallback")).toBe("offline");
    expect(messageFromError(null, "fallback")).toBe("fallback");
  });

  it("classifies aborts and uncertain network failures", () => {
    expect(isAbortError(new DOMException("cancelled", "AbortError"))).toBe(
      true,
    );
    expect(isAbortError(new Error("failed"))).toBe(false);
    expect(
      mutationFailureMayHavePersistedSideEffect(new TypeError("offline")),
    ).toBe(true);
    expect(mutationFailureMayHavePersistedSideEffect(new Error("no"))).toBe(
      false,
    );
  });
});
