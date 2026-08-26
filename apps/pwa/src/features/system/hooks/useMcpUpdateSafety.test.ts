import { describe, expect, it } from "vitest";

import {
  mcpUpdateSafetyReasons,
  type McpUpdateSafetyInput,
} from "./useMcpUpdateSafety";

const SAFE_INPUT: McpUpdateSafetyInput = {
  administratorSession: false,
  credentialDraft: false,
  operation: false,
  unacknowledgedCredential: false,
};

describe("agent access update safety inventory", () => {
  it.each([
    ["administratorSession", "agent access administrator session"],
    ["credentialDraft", "agent access credential draft"],
    ["unacknowledgedCredential", "unacknowledged one-time agent credential"],
  ] as const)("registers dirty owner %s", (owner, reason) => {
    expect(mcpUpdateSafetyReasons({ ...SAFE_INPUT, [owner]: true })).toEqual({
      busy: [],
      dirty: [reason],
    });
  });

  it("registers an active credential operation as busy", () => {
    expect(mcpUpdateSafetyReasons({ ...SAFE_INPUT, operation: true })).toEqual({
      busy: ["agent access operation"],
      dirty: [],
    });
  });
});
