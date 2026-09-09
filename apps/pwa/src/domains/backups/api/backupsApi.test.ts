import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "@poker-hero/openapi-client";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import {
  restoreApplicationBackup,
  toApplicationBackupRestoreResult,
} from "./backupsApi";

type ApplicationBackupRestoreResponse =
  components["schemas"]["ApplicationBackupRestoreResult"];

const restoreResponse = {
  imported_jobs: 2,
  reused_jobs: 1,
  imported_benchmark_reports: 1,
  reused_benchmark_reports: 0,
  total_jobs: 3,
  total_benchmark_reports: 1,
} satisfies ApplicationBackupRestoreResponse;

afterEach(resetApiMocks);

describe("backup API adapter", () => {
  it("preserves the generated response object and JSON shape", () => {
    expect(toApplicationBackupRestoreResult(restoreResponse)).toBe(
      restoreResponse,
    );
  });

  it("uploads the selected ZIP as multipart form data under the administrator credential", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(restoreResponse));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["backup"], "poker-hero-backup.zip", {
      type: "application/zip",
    });

    await expect(
      restoreApplicationBackup(file, "administrator-token"),
    ).resolves.toEqual(restoreResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/admin/ocr/backups/restore",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: { Authorization: "Bearer administrator-token" },
      }),
    );
    const form = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(form.get("file")).toBe(file);
  });
});
