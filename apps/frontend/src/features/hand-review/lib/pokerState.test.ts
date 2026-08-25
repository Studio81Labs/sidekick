import { describe, expect, it } from "vitest";

import * as pokerState from "./pokerState";

describe("poker state compatibility barrel", () => {
  it("keeps the established runtime export surface", () => {
    expect(Object.keys(pokerState).sort()).toEqual(
      [
        "CONFIDENCE_KEYS",
        "EMPTY_STATE",
        "FACING_ACTIONS",
        "RANKS",
        "RANK_VALUES",
        "STREETS",
        "SUITS",
        "approvalKey",
        "benchmarkApprovalKey",
        "formToCanonical",
        "formatCards",
        "isRank",
        "parseCards",
        "parseOptionalInteger",
        "parseOptionalNumber",
        "stateFromJob",
        "stateToForm",
        "summarizeConfidences",
        "toCanonicalState",
        "validateCardState",
      ].sort(),
    );
  });
});
