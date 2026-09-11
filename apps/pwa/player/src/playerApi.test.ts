import { afterEach, describe, expect, it, vi } from "vitest";

import recordedHandState from "./fixtures/recordedHandState.json";
import {
  previewPlayerHandReview,
  type ImportedHandState,
  type PlayerHandReviewPreviewRequest,
} from "./playerApi";

const state = recordedHandState as ImportedHandState;
const credentials = {
  sessionToken: "session-token",
  csrfToken: "csrf-token",
};
const request: PlayerHandReviewPreviewRequest = {
  request_id: "33333333-3333-4333-8333-333333333333",
  draft_revision: 9,
  detection_id: "detection-1",
  approved_state: state,
  correction_reason: null,
  expected_record_version: "a".repeat(64),
  expected_lifecycle_status: "pending_review",
  expected_active_canonical_revision: null,
  expected_canonical_revision_count: 0,
  expected_deletion_generation: 0,
  expected_lifecycle_changed_at: "2026-09-11T12:00:00Z",
};

describe("previewPlayerHandReview", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends the exact preview precondition and preserves sanitized decimal strings", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          schema_version: "player-hand-review-preview/v1",
          request_id: request.request_id,
          draft_revision: request.draft_revision,
          record_key: "b".repeat(64),
          record_version: request.expected_record_version,
          detection_id: request.detection_id,
          valid: true,
          reviewed_state: state,
          warnings: [],
          field_errors: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const preview = await previewPlayerHandReview(
      credentials,
      "b".repeat(64),
      request,
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe(
      "/api/player/hands/" + "b".repeat(64) + "/review-preview",
    );
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Authorization")).toBe(
      "Bearer session-token",
    );
    expect(new Headers(init.headers).get("X-Poker-CSRF-Token")).toBe(
      "csrf-token",
    );
    expect(JSON.parse(String(init.body))).toEqual(request);
    expect(preview.valid).toBe(true);
    expect(preview.reviewed_state?.streets[0]?.actions[0]?.amount).toBe("0.5");
  });
});
