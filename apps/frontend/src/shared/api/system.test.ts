import { afterEach, describe, expect, it, vi } from "vitest";

import { restoreApplicationBackup as restoreDomainApplicationBackup } from "../../domains/backups/api/backupsApi";
import { jsonResponse, resetApiMocks } from "../../test/api";
import {
  applicationBackupUrl,
  getPipelineCapabilities,
  restoreApplicationBackup,
} from "./system";

afterEach(resetApiMocks);

describe("application backups", () => {
  it("preserves the domain restore adapter export identity", () => {
    expect(restoreApplicationBackup).toBe(restoreDomainApplicationBackup);
  });

  it("uses the same-origin API URL for backup downloads", () => {
    expect(applicationBackupUrl()).toBe(
      "http://localhost:8000/api/backups/export",
    );
  });

  it("uploads a selected ZIP to the restore endpoint", async () => {
    const result = {
      imported_jobs: 2,
      reused_jobs: 1,
      imported_benchmark_reports: 1,
      reused_benchmark_reports: 0,
      total_jobs: 3,
      total_benchmark_reports: 1,
    };
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(result));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["backup"], "poker-hero-backup.zip", {
      type: "application/zip",
    });

    await expect(restoreApplicationBackup(file)).resolves.toEqual(result);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/backups/restore",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
      }),
    );
    const request = fetchMock.mock.calls[0][1];
    expect(request.body).toBeInstanceOf(FormData);
    expect((request.body as FormData).get("file")).toBe(file);
  });
});

describe("getPipelineCapabilities", () => {
  it("reads the plugins advertised by the backend", async () => {
    const payload = {
      defaults: {
        parser_provider: "ocr_cv",
        parser_layout_profile: "fortuna_nations",
        recommendation_provider: "local_solver",
        recommendation_engine: "postflop_solver",
      },
      parser_providers: [],
      parser_layout_profiles: [],
      parser_layout_compatibility: {},
      recommendation_providers: [],
      recommendation_engines: [],
    };
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getPipelineCapabilities()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/pipeline",
      { credentials: "include" },
    );
  });
});
