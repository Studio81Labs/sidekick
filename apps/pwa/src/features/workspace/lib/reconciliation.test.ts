import { describe, expect, it } from "vitest";

import { jobRecord } from "../../../test/analyzerHarness";
import {
  mergeHistoryItems,
  newerHistoryJob,
  newerJob,
  reconcileProcessingJobs,
} from "./reconciliation";

describe("workspace reconciliation", () => {
  it("retains the newer job revision", () => {
    const current = jobRecord({ updated_at: "2026-07-10T00:00:02Z" });
    const incoming = jobRecord({ updated_at: "2026-07-10T00:00:01Z" });

    expect(newerJob(current, incoming)).toBe(current);
  });

  it("accepts completed recommendation state over a pending local revision", () => {
    const current = jobRecord({
      recommendation_pending: true,
      updated_at: "2026-07-10T00:00:02Z",
    });
    const incoming = jobRecord({
      recommendation_pending: false,
      updated_at: "2026-07-10T00:00:01Z",
    });

    expect(newerHistoryJob(current, incoming)).toBe(incoming);
  });

  it("replaces a local upload error with its persisted upload", () => {
    const localError = jobRecord({
      id: "local-error-1",
      parser_provider: "client",
      status: "error",
      error: "Could not upload screenshot",
      upload_request_id: "upload-1",
    });
    const persisted = jobRecord({
      id: "b".repeat(32),
      upload_request_id: "upload-1",
    });

    expect(
      reconcileProcessingJobs([localError], [persisted], new Set(), new Set()),
    ).toEqual([persisted]);
  });

  it("merges newer history records without changing the existing order", () => {
    const older = jobRecord({
      id: "c".repeat(32),
      archived_at: "2026-07-10T00:00:00Z",
    });
    const newer = {
      ...older,
      title: "Reviewed hand",
      updated_at: "2026-07-10T00:00:01Z",
    };
    const currentItem = {
      id: older.id,
      job: older,
      savedAt: older.archived_at!,
    };
    const incomingItem = {
      id: newer.id,
      job: newer,
      savedAt: newer.archived_at!,
    };

    expect(mergeHistoryItems([currentItem], [incomingItem])).toEqual([
      incomingItem,
    ]);
  });
});
