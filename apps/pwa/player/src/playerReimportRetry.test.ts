import { beforeEach, describe, expect, it } from "vitest";

import {
  PLAYER_REIMPORT_RETRY_STORAGE_KEY,
  clearPlayerHandReimportRetry,
  preservePlayerHandReimportRetry,
} from "./playerReimportRetry";

describe("deleted-hand reimport retry persistence", () => {
  beforeEach(() => localStorage.clear());

  it("reuses an identity only for the same record, filename, and bytes", async () => {
    const recordKey = "a".repeat(64);
    const firstId = "11111111-1111-4111-8111-111111111111";
    const secondId = "22222222-2222-4222-8222-222222222222";
    const file = new File(["private hand"], "hands.txt");

    expect(
      await preservePlayerHandReimportRetry(recordKey, file, firstId),
    ).toBe(firstId);
    expect(
      await preservePlayerHandReimportRetry(
        recordKey,
        new File(["private hand"], "hands.txt"),
        secondId,
      ),
    ).toBe(firstId);
    expect(
      await preservePlayerHandReimportRetry("b".repeat(64), file, secondId),
    ).toBe(secondId);
  });

  it("stores hashes instead of source names or contents", async () => {
    const requestId = "33333333-3333-4333-8333-333333333333";
    await preservePlayerHandReimportRetry(
      "c".repeat(64),
      new File(["private hand history"], "private-session.txt"),
      requestId,
    );

    const stored = localStorage.getItem(PLAYER_REIMPORT_RETRY_STORAGE_KEY);
    expect(stored).toContain(requestId);
    expect(stored).not.toContain("private-session.txt");
    expect(stored).not.toContain("private hand history");

    clearPlayerHandReimportRetry();
    expect(localStorage.getItem(PLAYER_REIMPORT_RETRY_STORAGE_KEY)).toBeNull();
  });
});
