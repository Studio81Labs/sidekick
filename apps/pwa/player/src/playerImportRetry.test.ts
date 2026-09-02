import { beforeEach, describe, expect, it } from "vitest";

import {
  PLAYER_IMPORT_RETRY_STORAGE_KEY,
  clearPlayerImportRetry,
  preservePlayerImportRetry,
} from "./playerImportRetry";

describe("player import retry persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("reuses an identity only for the same ordered filenames and bytes", async () => {
    const originalRequestId = "11111111-1111-4111-8111-111111111111";
    const replacementRequestId = "22222222-2222-4222-8222-222222222222";
    const files = [
      new File(["first hand"], "first.txt", { type: "text/plain" }),
      new File(["second hand"], "second.txt", { type: "text/plain" }),
    ];

    expect(await preservePlayerImportRetry(files, originalRequestId)).toBe(
      originalRequestId,
    );
    expect(
      await preservePlayerImportRetry(
        [
          new File(["first hand"], "first.txt", { type: "text/plain" }),
          new File(["second hand"], "second.txt", { type: "text/plain" }),
        ],
        replacementRequestId,
      ),
    ).toBe(originalRequestId);
    expect(
      await preservePlayerImportRetry(
        [files[1] as File, files[0] as File],
        replacementRequestId,
      ),
    ).toBe(replacementRequestId);
  });

  it("does not reuse an identity for renamed or changed files", async () => {
    const originalRequestId = "33333333-3333-4333-8333-333333333333";
    const renamedRequestId = "44444444-4444-4444-8444-444444444444";
    const changedRequestId = "55555555-5555-4555-8555-555555555555";

    await preservePlayerImportRetry(
      [new File(["same bytes"], "hands.txt")],
      originalRequestId,
    );
    expect(
      await preservePlayerImportRetry(
        [new File(["same bytes"], "renamed.txt")],
        renamedRequestId,
      ),
    ).toBe(renamedRequestId);
    expect(
      await preservePlayerImportRetry(
        [new File(["changed bytes"], "renamed.txt")],
        changedRequestId,
      ),
    ).toBe(changedRequestId);
  });

  it("stores hashes instead of filenames or hand-history contents", async () => {
    const requestId = "66666666-6666-4666-8666-666666666666";
    await preservePlayerImportRetry(
      [new File(["private hand history"], "private-session.txt")],
      requestId,
    );

    const stored = localStorage.getItem(PLAYER_IMPORT_RETRY_STORAGE_KEY);
    expect(stored).toContain(requestId);
    expect(stored).not.toContain("private-session.txt");
    expect(stored).not.toContain("private hand history");

    clearPlayerImportRetry();
    expect(localStorage.getItem(PLAYER_IMPORT_RETRY_STORAGE_KEY)).toBeNull();
  });
});
