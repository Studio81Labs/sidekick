import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../shared/api/generated/openapi";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import {
  applicationBackupUrl,
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
  it("builds the deployment-aware backup download URL", () => {
    expect(applicationBackupUrl()).toBe(
      "http://localhost:8000/api/backups/export",
    );
  });

  it("preserves the generated response object and JSON shape", () => {
    expect(toApplicationBackupRestoreResult(restoreResponse)).toBe(
      restoreResponse,
    );
  });

  it("uploads the selected ZIP as multipart form data", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(restoreResponse));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["backup"], "poker-hero-backup.zip", {
      type: "application/zip",
    });

    await expect(restoreApplicationBackup(file)).resolves.toEqual(
      restoreResponse,
    );

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/backups/restore",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
    const form = fetchMock.mock.calls[0]?.[1]?.body as FormData;
    expect(form.get("file")).toBe(file);
  });
});
