import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PlayerApp from "./PlayerApp";
import {
  PLAYER_CSRF_STORAGE_KEY,
  PLAYER_SESSION_STORAGE_KEY,
} from "./playerApi";
import { PLAYER_IMPORT_RETRY_STORAGE_KEY } from "./playerImportRetry";
import { PLAYER_REIMPORT_RETRY_STORAGE_KEY } from "./playerReimportRetry";
import { PLAYER_ACTIVATE_UPDATE_MESSAGE } from "./playerUpdateProtocol";

class WaitingPlayerWorker extends EventTarget {
  readonly postMessage = vi.fn();
  state: ServiceWorkerState = "installed";
}

class WaitingPlayerRegistration extends EventTarget {
  installing: ServiceWorker | null = null;
  readonly update = vi.fn().mockResolvedValue(undefined);

  constructor(readonly waiting: ServiceWorker) {
    super();
  }
}

class PlayerServiceWorkerContainer extends EventTarget {
  controller = {} as ServiceWorker;
  readonly getRegistration = vi.fn();
  readonly register = vi.fn();
}

const originalServiceWorker = Object.getOwnPropertyDescriptor(
  navigator,
  "serviceWorker",
);

function installWaitingPlayerWorker(): WaitingPlayerWorker {
  const worker = new WaitingPlayerWorker();
  const registration = new WaitingPlayerRegistration(
    worker as unknown as ServiceWorker,
  );
  const container = new PlayerServiceWorkerContainer();
  container.register.mockResolvedValue(registration);
  container.getRegistration.mockResolvedValue(registration);
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: container,
  });
  return worker;
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const readyStorage = {
  status: "ready",
  storage: "player-local-file",
  layout_version: 1,
  data_directory: "/private/player-data",
  imported_hand_record_count: 3,
  recovery: { completed: [], quarantined: [], failed: [] },
};

function importOutcome(
  requestId: string,
  disposition = "created_pending_review",
  retryRequired = false,
) {
  return {
    request_id: requestId,
    files: [
      {
        file_slot: 1,
        filename: "hands.txt",
        status: "partial",
        hands: [
          {
            hand_ordinal: 1,
            source_hand_id: "900000000001",
            record_key: "8".repeat(64),
            disposition,
            parser_disposition: "clean",
            reconciliation_status: "pass",
            lifecycle_status: "pending_review",
            warning_count: 0,
          },
        ],
        diagnostics: [
          {
            code: retryRequired ? "storage_failure" : "unsupported_header",
            message: retryRequired
              ? "The local store could not confirm this hand."
              : "This hand format is outside the supported subset.",
            hand_ordinal: 2,
            source_hand_id: "900000000002",
            line_start: 17,
            line_end: null,
          },
        ],
      },
    ],
    summary: {
      files_received: 1,
      files_processed: 1,
      hands_succeeded: 1,
      diagnostic_count: 1,
      duplicate_requests: disposition === "duplicate_request" ? 1 : 0,
      retry_required: retryRequired,
    },
  };
}

const pendingHand = {
  record_key: "a".repeat(64),
  record_version: "9".repeat(64),
  identity: {
    namespace: "site-hand-id/v1",
    site: "pokerstars",
    source_hand_id: "123456789",
  },
  played_at: "2026-08-30T11:00:00Z",
  lifecycle_status: "pending_review",
  lifecycle_changed_at: "2026-08-30T12:00:00Z",
  active_canonical_revision: null,
  learning_eligible: false,
  deletion_generation: 0,
  raw_source_count: 3,
  detection_count: 3,
  warning_count: 4,
  unresolved_conflict_count: 0,
  canonical_revision_count: 0,
};

const pendingHandDetail = {
  summary: pendingHand,
  lifecycle: {
    status: "pending_review",
    active_canonical_revision: null,
    deletion_generation: 0,
    changed_at: "2026-08-30T12:00:00Z",
    reason: null,
    deletion_request: null,
  },
  raw_sources: [
    {
      raw_source_id: "file-1",
      chronology: {
        played_at: "2026-08-30T11:00:00Z",
        source_timezone: "Europe/Prague",
        source_session_id: "session-1",
        source_file_id: "file-1",
        hand_ordinal: 7,
      },
      provenance: {
        source_kind: "hand_history",
        import_id: "import-file-1",
        imported_at: "2026-08-30T12:00:00Z",
        adapter_id: "pokerstars",
        adapter_version: "1.0.0",
        format_revision: "pokerstars-text/v1",
        source_filename: "HH20260830.txt",
      },
      content_sha256: "b".repeat(64),
      reimports: [
        {
          raw_source_id: "file-1-reimport",
          chronology: {
            played_at: null,
            source_timezone: null,
            source_session_id: "session-2",
            source_file_id: "file-1-reimport",
            hand_ordinal: 9,
          },
          provenance: {
            source_kind: "hand_history",
            import_id: "import-file-1-reimport",
            imported_at: "2026-08-31T12:00:00Z",
            adapter_id: "pokerstars",
            adapter_version: "1.1.0",
            format_revision: "pokerstars-text/v1",
            source_filename: "HH20260831.txt",
          },
          detection_id: "detection-reimport-1",
          detected_semantic_sha256: "6".repeat(64),
        },
      ],
    },
    {
      raw_source_id: "file-2",
      chronology: {
        played_at: null,
        source_timezone: null,
        source_session_id: "session-1",
        source_file_id: "file-2",
        hand_ordinal: 8,
      },
      provenance: {
        source_kind: "hand_history",
        import_id: "import-file-2",
        imported_at: "2026-08-30T12:15:00Z",
        adapter_id: "pokerstars",
        adapter_version: "2.0.0",
        format_revision: "pokerstars-text/v1",
        source_filename: "HH20260830-corrected.txt",
      },
      content_sha256: "c".repeat(64),
      reimports: [],
    },
  ],
  detections: [
    {
      detection_id: "detection-1",
      raw_source_id: "file-1",
      detector_id: "pokerstars",
      detector_version: "1.0.0",
      detected_at: "2026-08-30T12:00:00Z",
      state: {
        identity: {
          namespace: "site-hand-id/v1",
          site: "pokerstars",
          source_hand_id: "123456789",
        },
        hero_player_id: null,
        hero_cards: [],
      },
      field_evidence: {
        "/hero_player_id": {
          confidence: "0.4",
          evidence: [
            {
              raw_source_id: "file-1",
              line_start: 1,
              line_end: 1,
              marker: "hero-line",
            },
            {
              raw_source_id: "file-1",
              line_start: null,
              line_end: null,
              marker: null,
            },
          ],
          warnings: ["Hero line was absent"],
        },
        "/streets/0/actions/0": {
          confidence: "1E-7",
          evidence: [
            {
              raw_source_id: "file-1",
              line_start: 2,
              line_end: 2,
              marker: "action-line",
            },
          ],
          warnings: [],
        },
      },
      warnings: ["Review hero identity"],
      content_sha256: "d".repeat(64),
      approval_eligible: true,
    },
    {
      detection_id: "detection-2",
      raw_source_id: "file-2",
      detector_id: "pokerstars",
      detector_version: "2.0.0",
      detected_at: "2026-08-30T12:15:00Z",
      state: {
        identity: {
          namespace: "site-hand-id/v1",
          site: "pokerstars",
          source_hand_id: "123456789",
        },
        hero_player_id: "hero",
        hero_cards: [],
      },
      field_evidence: {
        "/hero_player_id": {
          confidence: "0.95",
          evidence: [
            {
              raw_source_id: "file-2",
              line_start: 3,
              line_end: 4,
              marker: null,
            },
          ],
          warnings: [],
        },
      },
      warnings: [],
      content_sha256: "e".repeat(64),
      approval_eligible: true,
    },
    {
      detection_id: "detection-reimport-1",
      raw_source_id: "file-1-reimport",
      detector_id: "pokerstars",
      detector_version: "1.1.0",
      detected_at: "2026-08-31T12:00:00Z",
      state: {
        identity: {
          namespace: "site-hand-id/v1",
          site: "pokerstars",
          source_hand_id: "123456789",
        },
        hero_player_id: null,
        hero_cards: [],
      },
      field_evidence: {
        "/hero_player_id": {
          confidence: "0.7",
          evidence: [
            {
              raw_source_id: "file-1-reimport",
              line_start: 2,
              line_end: 2,
              marker: "reimport-hero-line",
            },
          ],
          warnings: ["Reimport hero evidence changed"],
        },
      },
      warnings: ["Review reimport hero evidence"],
      content_sha256: "7".repeat(64),
      approval_eligible: false,
    },
  ],
  conflicts: [
    {
      conflict_id: "conflict-1",
      raw_source_ids: ["file-1", "file-2"],
      detected_ids: ["detection-1", "detection-2"],
      active_canonical_revision_at_creation: 1,
      status: "resolved_use_source",
      selected_raw_source_id: "file-2",
      resolved_at: "2026-08-30T12:30:00Z",
    },
  ],
  canonical_revisions: [],
  deletion_receipt: null,
};

const activeHand = {
  ...pendingHand,
  lifecycle_status: "active",
  active_canonical_revision: 1,
  learning_eligible: true,
  canonical_revision_count: 1,
  raw_source_count: 2,
  detection_count: 1,
};

const activeHandDetail = {
  ...pendingHandDetail,
  summary: activeHand,
  lifecycle: {
    ...pendingHandDetail.lifecycle,
    status: "active",
    active_canonical_revision: 1,
  },
  raw_sources: pendingHandDetail.raw_sources.slice(0, 1),
  detections: pendingHandDetail.detections.slice(0, 1),
  conflicts: [],
  canonical_revisions: [
    {
      approval_id: null,
      revision: 1,
      detection_id: "detection-1",
      approved_at: "2026-08-30T12:00:00Z",
      state: {
        identity: {
          namespace: "site-hand-id/v1",
          site: "pokerstars",
          source_hand_id: "123456789",
        },
        hero_player_id: "hero",
        hero_cards: ["As", "Kh"],
      },
      corrections: [
        {
          field_pointer: "/hero_player_id",
          detected_value: null,
          approved_value: "hero",
          corrected_at: "2026-08-30T12:00:00Z",
          reason: "Confirmed from dealt-to evidence",
        },
      ],
    },
  ],
};

const conflictedActiveHand = {
  ...activeHand,
  raw_source_count: 3,
  detection_count: 3,
  unresolved_conflict_count: 1,
};

const conflictedActiveHandDetail = {
  ...activeHandDetail,
  summary: conflictedActiveHand,
  raw_sources: pendingHandDetail.raw_sources,
  detections: pendingHandDetail.detections,
  conflicts: [
    {
      conflict_id: "conflict-1",
      raw_source_ids: ["file-1", "file-2"],
      detected_ids: ["detection-1", "detection-2"],
      active_canonical_revision_at_creation: 1,
      status: "unresolved",
      selected_raw_source_id: null,
      resolved_at: null,
    },
  ],
};

function inactiveApprovedHandDetail(status: "withdrawn" | "rejected") {
  return {
    ...activeHandDetail,
    summary: {
      ...activeHand,
      lifecycle_status: status,
      active_canonical_revision: null,
      learning_eligible: false,
    },
    lifecycle: {
      ...activeHandDetail.lifecycle,
      status,
      active_canonical_revision: null,
      reason:
        status === "withdrawn"
          ? "player withdrew approval"
          : "not the hand I meant to import",
    },
  };
}

const failedDeletionHand = {
  ...pendingHand,
  lifecycle_status: "deletion_pending",
  deletion_generation: 2,
};

const failedDeletionHandDetail = {
  ...pendingHandDetail,
  summary: failedDeletionHand,
  lifecycle: {
    ...pendingHandDetail.lifecycle,
    status: "deletion_pending",
    deletion_generation: 2,
    reason: "delete requested",
    deletion_request: {
      generation: 2,
      requested_at: "2026-08-30T12:00:00Z",
      cleanup_status: "failed",
      last_error: "retained artifact cleanup failed",
    },
  },
};

const deletedHand = {
  ...pendingHand,
  identity: null,
  played_at: null,
  lifecycle_status: "deleted",
  deletion_generation: 3,
  raw_source_count: 0,
  detection_count: 0,
  warning_count: 0,
};

const deletedHandDetail = {
  summary: deletedHand,
  lifecycle: {
    status: "deleted",
    active_canonical_revision: null,
    deletion_generation: 3,
    changed_at: "2026-08-30T13:00:00Z",
    reason: "purged",
    deletion_request: null,
  },
  raw_sources: [],
  detections: [],
  conflicts: [],
  canonical_revisions: [],
  deletion_receipt: {
    receipt_id: "receipt-3",
    generation: 3,
    deleted_at: "2026-08-30T13:00:00Z",
    tombstone_sha256: "f".repeat(64),
  },
};

const reimportedHandDetail = {
  ...pendingHandDetail,
  summary: {
    ...pendingHand,
    record_version: "8".repeat(64),
    lifecycle_changed_at: "2026-08-30T14:00:00Z",
    deletion_generation: 4,
    raw_source_count: 1,
    detection_count: 1,
    warning_count: 1,
  },
  lifecycle: {
    ...pendingHandDetail.lifecycle,
    deletion_generation: 4,
    changed_at: "2026-08-30T14:00:00Z",
    reason: "authorized reimport",
  },
  raw_sources: pendingHandDetail.raw_sources.slice(0, 1),
  detections: pendingHandDetail.detections.slice(0, 1),
  conflicts: [],
  canonical_revisions: [],
  deletion_receipt: null,
};

describe("PlayerApp", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    if (originalServiceWorker) {
      Object.defineProperty(navigator, "serviceWorker", originalServiceWorker);
    } else {
      Reflect.deleteProperty(navigator, "serviceWorker");
    }
  });

  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    window.history.replaceState(null, "", "/");
    vi.restoreAllMocks();
  });

  it("erases and exchanges the launch fragment before loading local storage", async () => {
    window.location.hash = "#ticket=one-use-ticket";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);

    expect(
      await screen.findByText("Ready on this machine"),
    ).toBeInTheDocument();
    expect(screen.getByText("/private/player-data")).toBeInTheDocument();
    expect(screen.getByText("Storage layout")).toBeInTheDocument();
    expect(screen.getByText("Version 1")).toBeInTheDocument();
    expect(window.location.hash).toBe("");
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBe(
      "player-session",
    );
    expect(sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY)).toBe("csrf-token");
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/player/session",
      expect.objectContaining({
        method: "POST",
        headers: { Authorization: "Bearer one-use-ticket" },
      }),
    );
    const storageRequest = fetchMock.mock.calls[1];
    expect(storageRequest?.[0]).toBe("/api/player/storage");
    expect(new Headers(storageRequest?.[1]?.headers).get("Authorization")).toBe(
      "Bearer player-session",
    );
  });

  it("imports selected PokerStars files for review and refreshes local totals", async () => {
    const requestId = "55555555-5555-4555-8555-555555555555" as ReturnType<
      Crypto["randomUUID"]
    >;
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue(requestId);
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(jsonResponse(importOutcome(requestId)))
      .mockResolvedValueOnce(
        jsonResponse({ ...readyStorage, imported_hand_record_count: 4 }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    const input = screen.getByLabelText(
      "PokerStars hand-history files",
    ) as HTMLInputElement;
    await user.upload(
      input,
      new File(["PokerStars Hand"], "hands.txt", { type: "text/plain" }),
    );
    await user.click(screen.getByRole("button", { name: "Import for review" }));

    expect(
      await screen.findByText("Import finished with reviewable outcomes."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Hand #900000000001.*created pending review/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/unsupported header.*outside the supported subset/),
    ).toBeInTheDocument();
    expect(screen.getByText("4", { selector: "dd" })).toBeInTheDocument();
    expect(input.value).toBe("");
    expect(
      screen.getByRole("button", { name: "Import for review" }),
    ).toBeDisabled();

    const importRequest = fetchMock.mock.calls[1];
    expect(importRequest?.[0]).toBe("/api/player/imports");
    const headers = new Headers(importRequest?.[1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer stored-session");
    expect(headers.get("X-Poker-CSRF-Token")).toBe("stored-csrf");
    expect(headers.has("Content-Type")).toBe(false);
    const body = importRequest?.[1]?.body as FormData;
    expect(body.get("request_id")).toBe(requestId);
    expect((body.get("files") as File).name).toBe("hands.txt");
  });

  it("retains the exact request after a retryable storage diagnostic", async () => {
    const requestId = "88888888-8888-4888-8888-888888888888" as ReturnType<
      Crypto["randomUUID"]
    >;
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue(requestId);
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(jsonResponse(readyStorage))
        .mockResolvedValueOnce(
          jsonResponse(
            importOutcome(requestId, "created_pending_review", true),
          ),
        )
        .mockResolvedValueOnce(jsonResponse(readyStorage)),
    );
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    const input = screen.getByLabelText(
      "PokerStars hand-history files",
    ) as HTMLInputElement;
    await user.upload(
      input,
      new File(["PokerStars Hand"], "hands.txt", { type: "text/plain" }),
    );
    await user.click(screen.getByRole("button", { name: "Import for review" }));

    expect(
      await screen.findByText("Import needs a safe retry."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/same request ID and selected files remain ready/),
    ).toBeInTheDocument();
    expect(input.files).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: "Import for review" }),
    ).toBeEnabled();
    expect(localStorage.getItem(PLAYER_IMPORT_RETRY_STORAGE_KEY)).toContain(
      requestId,
    );
  });

  it("reuses a retained retry identity after recovery restarts the runtime", async () => {
    const retainedRequestId =
      "99999999-9999-4999-8999-999999999999" as ReturnType<
        Crypto["randomUUID"]
      >;
    const replacementRequestId =
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" as ReturnType<
        Crypto["randomUUID"]
      >;
    const randomUuid = vi
      .spyOn(window.crypto, "randomUUID")
      .mockReturnValueOnce(retainedRequestId)
      .mockReturnValueOnce(replacementRequestId);
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    const firstFetch = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Recovery required" }, 503),
      );
    vi.stubGlobal("fetch", firstFetch);
    const firstUser = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await firstUser.upload(
      screen.getByLabelText("PokerStars hand-history files"),
      new File(["PokerStars Hand"], "hands.txt", { type: "text/plain" }),
    );
    await firstUser.click(
      screen.getByRole("button", { name: "Import for review" }),
    );

    expect(
      await screen.findByText(
        /same files in the same order.*safe-retry identity/,
      ),
    ).toBeInTheDocument();
    expect(localStorage.getItem(PLAYER_IMPORT_RETRY_STORAGE_KEY)).toContain(
      retainedRequestId,
    );

    cleanup();
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "restarted-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "restarted-csrf");
    const secondFetch = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse(importOutcome(retainedRequestId, "duplicate_request")),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage));
    vi.stubGlobal("fetch", secondFetch);
    const secondUser = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await secondUser.upload(
      screen.getByLabelText("PokerStars hand-history files"),
      new File(["PokerStars Hand"], "hands.txt", { type: "text/plain" }),
    );
    await secondUser.click(
      screen.getByRole("button", { name: "Import for review" }),
    );

    await screen.findByText(/retry outcomes were already retained/);
    const retryBody = secondFetch.mock.calls[1]?.[1]?.body as FormData;
    expect(retryBody.get("request_id")).toBe(retainedRequestId);
    expect(randomUuid).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem(PLAYER_IMPORT_RETRY_STORAGE_KEY)).toBeNull();
  });

  it("retains files and request identity after an ambiguous import", async () => {
    const requestId = "66666666-6666-4666-8666-666666666666" as ReturnType<
      Crypto["randomUUID"]
    >;
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue(requestId);
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(
        jsonResponse({ ...readyStorage, imported_hand_record_count: 4 }),
      )
      .mockResolvedValueOnce(
        jsonResponse(importOutcome(requestId, "duplicate_request")),
      )
      .mockResolvedValueOnce(
        jsonResponse({ ...readyStorage, imported_hand_record_count: 4 }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    const input = screen.getByLabelText(
      "PokerStars hand-history files",
    ) as HTMLInputElement;
    await user.upload(
      input,
      new File(["PokerStars Hand"], "hands.txt", { type: "text/plain" }),
    );
    const importButton = screen.getByRole("button", {
      name: "Import for review",
    });
    await user.click(importButton);

    expect(
      await screen.findByText(
        /same request ID and selected files remain ready/,
      ),
    ).toBeInTheDocument();
    expect(input.files).toHaveLength(1);
    expect(importButton).toBeEnabled();
    await user.click(importButton);

    expect(
      await screen.findByText(/1 retry outcomes were already retained/),
    ).toBeInTheDocument();
    const firstBody = fetchMock.mock.calls[1]?.[1]?.body as FormData;
    const retryBody = fetchMock.mock.calls[3]?.[1]?.body as FormData;
    expect(firstBody.get("request_id")).toBe(requestId);
    expect(retryBody.get("request_id")).toBe(requestId);
    expect(input.value).toBe("");
  });

  it("treats an incomplete successful import response as ambiguous", async () => {
    const requestId = "77777777-7777-4777-8777-777777777777" as ReturnType<
      Crypto["randomUUID"]
    >;
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue(requestId);
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(jsonResponse(readyStorage))
        .mockResolvedValueOnce(jsonResponse(importOutcome(requestId)))
        .mockResolvedValueOnce(jsonResponse(readyStorage)),
    );
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    const input = screen.getByLabelText(
      "PokerStars hand-history files",
    ) as HTMLInputElement;
    await user.upload(input, [
      new File(["PokerStars Hand"], "hands.txt", { type: "text/plain" }),
      new File(["PokerStars Hand"], "more-hands.txt", {
        type: "text/plain",
      }),
    ]);
    await user.click(screen.getByRole("button", { name: "Import for review" }));

    expect(
      await screen.findByText(/import may have committed.*safe retry/),
    ).toBeInTheDocument();
    expect(input.files).toHaveLength(2);
    expect(
      screen.queryByText("Import finished with reviewable outcomes."),
    ).not.toBeInTheDocument();
  });

  it("defers a waiting player update through bootstrap, drafts, and restore", async () => {
    const user = userEvent.setup();
    const worker = installWaitingPlayerWorker();
    vi.stubEnv("PROD", true);
    window.location.hash = "#ticket=one-use-ticket";
    let resolveStorage!: (response: Response) => void;
    const storageResponse = new Promise<Response>((resolve) => {
      resolveStorage = resolve;
    });
    const restoreResponse = new Promise<Response>(() => undefined);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockReturnValueOnce(storageResponse)
      .mockReturnValueOnce(restoreResponse);
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);

    expect(
      await screen.findByText(/will wait for active work to finish/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Reload update" }),
    ).not.toBeInTheDocument();

    resolveStorage(jsonResponse(readyStorage));
    await screen.findByText("Ready on this machine");
    expect(screen.getByRole("button", { name: "Reload update" })).toBeEnabled();

    await user.upload(
      screen.getByLabelText("Player backup ZIP"),
      new File(["backup"], "player.zip", { type: "application/zip" }),
    );
    expect(
      await screen.findByText(/Finish your drafts or explicitly discard them/),
    ).toBeInTheDocument();

    const unload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unload);
    expect(unload.defaultPrevented).toBe(true);

    await user.click(screen.getByRole("button", { name: "Restore backup" }));
    expect(
      await screen.findByText(/will wait for active work to finish/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /reload/i }),
    ).not.toBeInTheDocument();
    expect(worker.postMessage).not.toHaveBeenCalled();
  });

  it("requires explicit confirmation before discarding a player draft", async () => {
    const user = userEvent.setup();
    const worker = installWaitingPlayerWorker();
    vi.stubEnv("PROD", true);
    window.location.hash = "#ticket=one-use-ticket";
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.upload(
      screen.getByLabelText("Player backup ZIP"),
      new File(["backup"], "player.zip", { type: "application/zip" }),
    );

    const discard = await screen.findByRole("button", {
      name: "Discard and reload",
    });
    await user.click(discard);
    expect(worker.postMessage).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    await user.click(discard);
    expect(confirm).toHaveBeenLastCalledWith(
      "Discard every unsaved local player draft and reload the update?",
    );
    expect(worker.postMessage).toHaveBeenCalledWith({
      type: PLAYER_ACTIVATE_UPDATE_MESSAGE,
    });
  });

  it("preserves an exchanged session when initial storage status is transient", async () => {
    window.location.hash = "#ticket=one-use-ticket";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Stable status unavailable" }, 409),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);

    expect(
      await screen.findByText("Stable status unavailable"),
    ).toBeInTheDocument();
    expect(window.location.hash).toBe("");
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBe(
      "player-session",
    );
    expect(sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY)).toBe("csrf-token");

    fetchMock.mockResolvedValueOnce(jsonResponse(readyStorage));
    cleanup();
    render(<PlayerApp />);

    expect(
      await screen.findByText("Ready on this machine"),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const retriedStorageRequest = fetchMock.mock.calls[2];
    expect(retriedStorageRequest?.[0]).toBe("/api/player/storage");
    expect(
      new Headers(retriedStorageRequest?.[1]?.headers).get("Authorization"),
    ).toBe("Bearer player-session");
  });

  it("loads retained hand summaries and audit detail without mutation credentials", async () => {
    const user = userEvent.setup();
    window.location.hash = "#ticket=one-use-ticket";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [pendingHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(pendingHandDetail));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);

    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    expect(
      await screen.findByText("site-hand-id/v1 · pokerstars #123456789"),
    ).toBeInTheDocument();
    expect(screen.getByText("Not used for learning")).toBeInTheDocument();

    const listRequest = fetchMock.mock.calls[2];
    expect(listRequest?.[0]).toBe("/api/player/hands?limit=25");
    expect(new Headers(listRequest?.[1]?.headers).get("Authorization")).toBe(
      "Bearer player-session",
    );
    expect(
      new Headers(listRequest?.[1]?.headers).has("X-Poker-CSRF-Token"),
    ).toBe(false);

    await user.click(screen.getByRole("button", { name: "View audit detail" }));
    expect(await screen.findByText("Audit detail")).toBeInTheDocument();
    expect(
      screen.getByText(/This record is not approved for learning/),
    ).toBeInTheDocument();
    expect(screen.getByText("Review hero identity")).toBeInTheDocument();
    expect(screen.getByText("Hero line was absent")).toBeInTheDocument();
    expect(screen.getAllByText("/hero_player_id")).toHaveLength(3);
    expect(screen.getByText(/40% confidence/)).toBeInTheDocument();
    expect(screen.getByText(/0.00001% confidence/)).toBeInTheDocument();
    expect(screen.getByText(/source file-1 · line 1/)).toBeInTheDocument();
    expect(screen.getByText("Detected proposals")).toBeInTheDocument();
    expect(screen.getAllByText(/"hero_player_id": null/)).toHaveLength(2);
    expect(screen.getAllByText(/Detection detection-1/).length).toBeGreaterThan(
      1,
    );
    expect(screen.getAllByText(/Detection detection-2/).length).toBeGreaterThan(
      1,
    );
    expect(
      screen.getAllByText(/Detection detection-reimport-1/).length,
    ).toBeGreaterThan(1);
    expect(screen.getByText(/reimport audit only/)).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: /detection-reimport-1/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/95% confidence/)).toBeInTheDocument();
    expect(screen.getByText(/70% confidence/)).toBeInTheDocument();
    expect(
      screen.getByText("Review reimport hero evidence"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Detection detection-1 · proposal warning/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Detection detection-1 · field \/hero_player_id/),
    ).toBeInTheDocument();
    expect(screen.getByText("Import conflict history")).toBeInTheDocument();
    expect(screen.getByText(/resolved use source/)).toBeInTheDocument();
    expect(screen.getByText(/Selected source: file-2/)).toBeInTheDocument();
    expect(screen.getByText(/HH20260830.txt/)).toBeInTheDocument();
    expect(
      screen.getByText(/source timezone Europe\/Prague/),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/source session session-1/)).toHaveLength(2);
    expect(screen.getByText(/source file file-1 ·/)).toBeInTheDocument();
    expect(screen.getByText(/hand ordinal 7/)).toBeInTheDocument();
    expect(screen.getByText(/2026-08-30T11:00:00Z/)).toBeInTheDocument();
    expect(screen.getByText("import-file-1")).toBeInTheDocument();
    expect(screen.getByText(/HH20260831.txt/)).toBeInTheDocument();
    expect(screen.getByText("import-file-1-reimport")).toBeInTheDocument();
    expect(screen.getByText(/source file file-1-reimport/)).toBeInTheDocument();
    expect(screen.getByText("6".repeat(64))).toBeInTheDocument();
    expect(screen.getAllByText(/format pokerstars-text\/v1/)).toHaveLength(3);
    expect(screen.getByText(/source excerpt redacted/)).toBeInTheDocument();
    expect(screen.getByText("d".repeat(64))).toBeInTheDocument();
    expect(screen.getByText("b".repeat(64))).toBeInTheDocument();
    expect(screen.getAllByText("a".repeat(64))).toHaveLength(2);

    const detailRequest = fetchMock.mock.calls[3];
    expect(detailRequest?.[0]).toBe(
      `/api/player/hands/${pendingHand.record_key}`,
    );
    expect(
      new Headers(detailRequest?.[1]?.headers).has("X-Poker-CSRF-Token"),
    ).toBe(false);
    expect(document.body).not.toHaveTextContent("PokerStars Hand #123456789");
  });

  it("requires restart recovery when loading an unresolved hand detail", async () => {
    const user = userEvent.setup();
    window.location.hash = "#ticket=one-use-ticket";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [activeHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          { detail: "This hand has an interrupted lifecycle write" },
          503,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );

    expect(
      await screen.findByText(
        /lifecycle outcome is unresolved.*Restart the local player runtime.*journal recovery can finish/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
    expect(
      screen.queryByText("site-hand-id/v1 · pokerstars #123456789"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Download backup" }),
    ).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY)).toBeNull();
  });

  it("renders the approved canonical state retained by an active revision", async () => {
    const user = userEvent.setup();
    window.location.hash = "#ticket=one-use-ticket";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [activeHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(activeHandDetail));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );

    expect(
      await screen.findByText(/Canonical revision 1 is active/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Revision 1 · detection detection-1/),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/"hero_player_id": "hero"/)).toHaveLength(2);
    expect(screen.getByText("User corrections")).toBeInTheDocument();
    expect(
      screen.getByText("Confirmed from dealt-to evidence"),
    ).toBeInTheDocument();
    expect(screen.getByText("Change approval state")).toBeInTheDocument();
    expect(
      (
        screen.getByRole("textbox", {
          name: "Reviewed canonical state (JSON)",
        }) as HTMLTextAreaElement
      ).value,
    ).toContain('"hero_cards": [\n    "As",');
  });

  it("allows same-source reapproval while blocking an unresolved source switch", async () => {
    const user = userEvent.setup();
    window.location.hash = "#ticket=one-use-ticket";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [conflictedActiveHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(conflictedActiveHandDetail));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );

    const approvalButton = screen.getByRole("button", {
      name: "Approve new canonical revision",
    });
    expect(approvalButton).toBeEnabled();
    expect(
      screen.getByText(/reapproval stays on the preserved canonical source/),
    ).toBeInTheDocument();

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Detection to review" }),
      "detection-2",
    );

    expect(approvalButton).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Resolve the retained source conflict before switching the canonical revision",
    );
  });

  it("keeps the preserved canonical source with exact conflict preconditions", async () => {
    const user = userEvent.setup();
    const committed = {
      ...conflictedActiveHandDetail,
      summary: {
        ...conflictedActiveHand,
        record_version: "8".repeat(64),
        lifecycle_changed_at: "2026-08-30T12:31:00Z",
        unresolved_conflict_count: 0,
      },
      lifecycle: {
        ...conflictedActiveHandDetail.lifecycle,
        changed_at: "2026-08-30T12:31:00Z",
      },
      conflicts: [
        {
          ...conflictedActiveHandDetail.conflicts[0],
          status: "resolved_keep_active",
          selected_raw_source_id: "file-1",
          resolved_at: "2026-08-30T12:31:00Z",
        },
      ],
    };
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [conflictedActiveHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(conflictedActiveHandDetail))
      .mockRejectedValueOnce(new TypeError("response interrupted"))
      .mockResolvedValueOnce(jsonResponse(committed));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.click(
      screen.getByRole("button", {
        name: "Keep preserved canonical state",
      }),
    );

    expect(
      await screen.findByText(
        /conflict resolution committed even though the original response was interrupted/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/resolved keep active/)).toBeInTheDocument();
    expect(screen.getByText(/Selected source: file-1/)).toBeInTheDocument();
    const request = fetchMock.mock.calls[4];
    expect(request?.[0]).toBe(
      `/api/player/hands/${pendingHand.record_key}/conflicts/conflict-1/resolve`,
    );
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      resolution: "keep_active",
      selected_raw_source_id: "file-1",
      expected_record_version: conflictedActiveHand.record_version,
      expected_lifecycle_status: "active",
      expected_active_canonical_revision: 1,
      expected_canonical_revision_count: 1,
      expected_deletion_generation: 0,
      expected_lifecycle_changed_at: conflictedActiveHand.lifecycle_changed_at,
    });
    expect(new Headers(request?.[1]?.headers).get("X-Poker-CSRF-Token")).toBe(
      "csrf-token",
    );
    expect(fetchMock.mock.calls[5]?.[0]).toBe(
      `/api/player/hands/${pendingHand.record_key}`,
    );
  });

  it("moves a selected conflict source to review without auto-approving it", async () => {
    const user = userEvent.setup();
    const committed = {
      ...conflictedActiveHandDetail,
      summary: {
        ...conflictedActiveHand,
        record_version: "8".repeat(64),
        lifecycle_status: "pending_review",
        lifecycle_changed_at: "2026-08-30T12:31:00Z",
        active_canonical_revision: null,
        learning_eligible: false,
        unresolved_conflict_count: 0,
      },
      lifecycle: {
        ...conflictedActiveHandDetail.lifecycle,
        status: "pending_review",
        active_canonical_revision: null,
        changed_at: "2026-08-30T12:31:00Z",
      },
      conflicts: [
        {
          ...conflictedActiveHandDetail.conflicts[0],
          status: "resolved_use_source",
          selected_raw_source_id: "file-2",
          resolved_at: "2026-08-30T12:31:00Z",
        },
      ],
    };
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [conflictedActiveHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(conflictedActiveHandDetail))
      .mockResolvedValueOnce(jsonResponse(committed));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Review source file-2" }),
    );

    expect(
      await screen.findByText(
        /Review and explicitly approve its detected state/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/This record is not approved for learning/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "Detection to review" }),
    ).toHaveValue("detection-2");
    expect(
      screen.getByRole("button", { name: "Approve new canonical revision" }),
    ).toBeEnabled();
    const request = fetchMock.mock.calls[4];
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({
      resolution: "use_source",
      selected_raw_source_id: "file-2",
      expected_record_version: conflictedActiveHand.record_version,
      expected_lifecycle_status: "active",
      expected_active_canonical_revision: 1,
      expected_canonical_revision_count: 1,
      expected_deletion_generation: 0,
      expected_lifecycle_changed_at: conflictedActiveHand.lifecycle_changed_at,
    });
  });

  it("approves an explicitly corrected detection with exact audit preconditions", async () => {
    const user = userEvent.setup();
    const requestId = "33333333-3333-4333-8333-333333333333" as ReturnType<
      Crypto["randomUUID"]
    >;
    const correctionReason = "Confirmed the hero from retained evidence";
    const approvedState = {
      ...pendingHandDetail.detections[0].state,
      hero_player_id: "hero",
    };
    const committed = {
      ...pendingHandDetail,
      summary: {
        ...pendingHand,
        record_version: "8".repeat(64),
        lifecycle_status: "active",
        lifecycle_changed_at: "2026-08-30T12:31:00Z",
        active_canonical_revision: 1,
        learning_eligible: true,
        canonical_revision_count: 1,
      },
      lifecycle: {
        ...pendingHandDetail.lifecycle,
        status: "active",
        active_canonical_revision: 1,
        changed_at: "2026-08-30T12:31:00Z",
      },
      canonical_revisions: [
        {
          approval_id: requestId,
          revision: 1,
          detection_id: "detection-1",
          approved_at: "2026-08-30T12:31:00Z",
          state: approvedState,
          corrections: [
            {
              field_pointer: "/hero_player_id",
              detected_value: null,
              approved_value: "hero",
              corrected_at: "2026-08-30T12:31:00Z",
              reason: correctionReason,
            },
          ],
        },
      ],
    };
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue(requestId);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [pendingHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(pendingHandDetail))
      .mockResolvedValueOnce(jsonResponse(committed));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Detection to review" }),
      "detection-1",
    );
    const editor = screen.getByRole("textbox", {
      name: "Reviewed canonical state (JSON)",
    });
    expect((editor as HTMLTextAreaElement).value).toContain(
      '"hero_player_id": null',
    );
    fireEvent.change(editor, {
      target: { value: JSON.stringify(approvedState, null, 2) },
    });
    await user.type(
      screen.getByRole("textbox", { name: "Correction reason" }),
      correctionReason,
    );
    await user.click(
      screen.getByRole("button", { name: "Approve canonical state" }),
    );

    expect(
      await screen.findByText(/Canonical revision 1 approved/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Canonical revision 1 is active/),
    ).toBeInTheDocument();
    expect(window.confirm).toHaveBeenCalledWith(
      expect.stringMatching(
        /explicit ground truth.*parser proposal remains retained/,
      ),
    );
    const approvalRequest = fetchMock.mock.calls[4];
    expect(approvalRequest?.[0]).toBe(
      `/api/player/hands/${pendingHand.record_key}/approve`,
    );
    expect(approvalRequest?.[1]?.method).toBe("POST");
    const approvalHeaders = new Headers(approvalRequest?.[1]?.headers);
    expect(approvalHeaders.get("Authorization")).toBe("Bearer player-session");
    expect(approvalHeaders.get("X-Poker-CSRF-Token")).toBe("csrf-token");
    expect(JSON.parse(String(approvalRequest?.[1]?.body))).toEqual({
      request_id: requestId,
      detection_id: "detection-1",
      approved_state: approvedState,
      correction_reason: correctionReason,
      expected_record_version: pendingHand.record_version,
      expected_lifecycle_status: "pending_review",
      expected_active_canonical_revision: null,
      expected_canonical_revision_count: 0,
      expected_deletion_generation: 0,
      expected_lifecycle_changed_at: "2026-08-30T12:00:00Z",
    });
  });

  it("keeps invalid or unexplained reviewed JSON local", async () => {
    const user = userEvent.setup();
    window.location.hash = "#ticket=one-use-ticket";
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [pendingHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(pendingHandDetail));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    const editor = screen.getByRole("textbox", {
      name: "Reviewed canonical state (JSON)",
    });
    fireEvent.change(editor, { target: { value: "{" } });
    await user.click(
      screen.getByRole("button", { name: "Approve canonical state" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "must be a valid JSON object",
    );

    fireEvent.change(editor, {
      target: {
        value: JSON.stringify(
          {
            ...pendingHandDetail.detections[1].state,
            hero_player_id: "villain",
          },
          null,
          2,
        ),
      },
    });
    await user.click(
      screen.getByRole("button", { name: "Approve canonical state" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Add a correction reason",
    );
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(confirm).not.toHaveBeenCalled();
  });

  it.each([
    [
      "attributes a lost approval response to the exact active approval id",
      "33333333-3333-4333-8333-333333333333",
      true,
    ],
    [
      "does not attribute another active approval to the lost request",
      "44444444-4444-4444-8444-444444444444",
      false,
    ],
  ] as const)("%s", async (_name, returnedApprovalId, exactMatch) => {
    const user = userEvent.setup();
    const requestId = "33333333-3333-4333-8333-333333333333" as ReturnType<
      Crypto["randomUUID"]
    >;
    const committed = {
      ...pendingHandDetail,
      summary: {
        ...pendingHand,
        lifecycle_status: "active",
        active_canonical_revision: 1,
        learning_eligible: true,
        canonical_revision_count: 1,
      },
      lifecycle: {
        ...pendingHandDetail.lifecycle,
        status: "active",
        active_canonical_revision: 1,
      },
      canonical_revisions: [
        {
          approval_id: returnedApprovalId,
          revision: 1,
          detection_id: "detection-2",
          approved_at: "2026-08-30T12:31:00Z",
          state: pendingHandDetail.detections[1].state,
          corrections: [],
        },
      ],
    };
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue(requestId);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [pendingHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(pendingHandDetail))
      .mockRejectedValueOnce(new TypeError("connection interrupted"))
      .mockResolvedValueOnce(jsonResponse(committed));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    if (!exactMatch) {
      fireEvent.change(
        screen.getByRole("textbox", {
          name: "Reviewed canonical state (JSON)",
        }),
        {
          target: {
            value: JSON.stringify(
              {
                ...pendingHandDetail.detections[1].state,
                hero_player_id: "villain",
              },
              null,
              2,
            ),
          },
        },
      );
      await user.type(
        screen.getByRole("textbox", { name: "Correction reason" }),
        "Keep this proposed correction",
      );
    }
    await user.click(
      screen.getByRole("button", { name: "Approve canonical state" }),
    );

    if (exactMatch) {
      expect(
        await screen.findByText(
          /committed even though the original response was interrupted/,
        ),
      ).toHaveTextContent("exact approval audit was refreshed");
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    } else {
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Canonical approval was not confirmed. The audit detail was refreshed.",
      );
      expect(
        screen.queryByText(
          /committed even though the original response was interrupted/,
        ),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("textbox", { name: "Correction reason" }),
      ).toHaveValue("Keep this proposed correction");
      expect(
        (
          screen.getByRole("textbox", {
            name: "Reviewed canonical state (JSON)",
          }) as HTMLTextAreaElement
        ).value,
      ).toContain('"hero_player_id": "villain"');
    }
    expect(fetchMock.mock.calls[5]?.[0]).toBe(
      `/api/player/hands/${pendingHand.record_key}`,
    );
  });

  it("requires runtime restart when canonical approval recovery is pending", async () => {
    const user = userEvent.setup();
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [pendingHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(pendingHandDetail))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Interrupted approval write" }, 503),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Approve canonical state" }),
    );

    expect(
      await screen.findByText(
        /lifecycle outcome is unresolved.*Restart the local player runtime/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY)).toBeNull();
  });

  it.each([
    ["withdraw", "Withdraw approval", "withdrawn", "Approval withdrawn"],
    ["reject", "Reject as incorrect", "rejected", "Hand rejected"],
  ] as const)(
    "%ss an active approval with CSRF and refreshes the retained audit",
    async (action, buttonName, status, notice) => {
      const user = userEvent.setup();
      const reason =
        action === "withdraw"
          ? "Remove this hand from my study set"
          : "The approved state is incorrect";
      const closedDetail = {
        ...inactiveApprovedHandDetail(status),
        summary: {
          ...inactiveApprovedHandDetail(status).summary,
          lifecycle_changed_at: "2026-08-30T12:30:00Z",
        },
        lifecycle: {
          ...inactiveApprovedHandDetail(status).lifecycle,
          changed_at: "2026-08-30T12:30:00Z",
          reason,
        },
      };
      window.location.hash = "#ticket=one-use-ticket";
      vi.spyOn(window, "confirm").mockReturnValue(true);
      const fetchMock = vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(
          jsonResponse({
            session_token: "player-session",
            csrf_token: "csrf-token",
            expires_in_seconds: 86400,
          }),
        )
        .mockResolvedValueOnce(jsonResponse(readyStorage))
        .mockResolvedValueOnce(
          jsonResponse({
            items: [activeHand],
            unreadable: [],
            next_cursor: null,
          }),
        )
        .mockResolvedValueOnce(jsonResponse(activeHandDetail))
        .mockResolvedValueOnce(jsonResponse(closedDetail));
      vi.stubGlobal("fetch", fetchMock);

      render(<PlayerApp />);
      await screen.findByText("Ready on this machine");
      await user.click(
        screen.getByRole("button", { name: "Load hand records" }),
      );
      await user.click(
        await screen.findByRole("button", { name: "View audit detail" }),
      );
      await user.type(screen.getByRole("textbox", { name: "Reason" }), reason);
      await user.click(screen.getByRole("button", { name: buttonName }));

      expect(await screen.findByText(new RegExp(notice))).toBeInTheDocument();
      expect(screen.getByText(status)).toBeInTheDocument();
      expect(
        screen.getByText(`Lifecycle reason: ${reason}`),
      ).toBeInTheDocument();
      expect(
        screen.queryByText("Change approval state"),
      ).not.toBeInTheDocument();
      expect(screen.getByText("Not used for learning")).toBeInTheDocument();
      const closeRequest = fetchMock.mock.calls[4];
      expect(closeRequest?.[0]).toBe(
        `/api/player/hands/${activeHand.record_key}/${action}`,
      );
      expect(closeRequest?.[1]?.method).toBe("POST");
      const closeHeaders = new Headers(closeRequest?.[1]?.headers);
      expect(closeHeaders.get("Authorization")).toBe("Bearer player-session");
      expect(closeHeaders.get("X-Poker-CSRF-Token")).toBe("csrf-token");
      expect(closeHeaders.get("Content-Type")).toBe("application/json");
      expect(JSON.parse(String(closeRequest?.[1]?.body))).toEqual({
        reason,
        expected_active_canonical_revision: 1,
        expected_deletion_generation: 0,
        expected_lifecycle_changed_at: "2026-08-30T12:00:00Z",
      });
    },
  );

  it("refreshes stale approval detail without overwriting the newer lifecycle", async () => {
    const user = userEvent.setup();
    const refreshed = {
      ...activeHandDetail,
      summary: {
        ...activeHand,
        lifecycle_changed_at: "2026-08-30T12:20:00Z",
      },
      lifecycle: {
        ...activeHandDetail.lifecycle,
        changed_at: "2026-08-30T12:20:00Z",
      },
    };
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [activeHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(activeHandDetail))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "The hand lifecycle changed" }, 409),
      )
      .mockResolvedValueOnce(jsonResponse(refreshed));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Reason" }),
      "Remove from study",
    );
    await user.click(screen.getByRole("button", { name: "Withdraw approval" }));

    expect(
      await screen.findByText(
        /Approval state was not changed.*audit detail was refreshed/,
      ),
    ).toHaveTextContent("The hand lifecycle changed");
    expect(
      screen.getByText(/Canonical revision 1 is active/),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Reason" })).toHaveValue(
      "Remove from study",
    );
    expect(fetchMock.mock.calls[5]?.[0]).toBe(
      `/api/player/hands/${activeHand.record_key}`,
    );
  });

  it("recognizes a committed withdrawal after an interrupted mutation response", async () => {
    const user = userEvent.setup();
    const reason = "Remove from study";
    const withdrawn = {
      ...inactiveApprovedHandDetail("withdrawn"),
      lifecycle: {
        ...inactiveApprovedHandDetail("withdrawn").lifecycle,
        reason,
      },
    };
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [activeHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(activeHandDetail))
      .mockRejectedValueOnce(new TypeError("connection interrupted"))
      .mockResolvedValueOnce(jsonResponse(withdrawn));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.type(screen.getByRole("textbox", { name: "Reason" }), reason);
    await user.click(screen.getByRole("button", { name: "Withdraw approval" }));

    expect(
      await screen.findByText(
        /withdrawn state committed.*response was interrupted/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/previously approved.*now withdrawn/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("requires restart recovery instead of refreshing a ready cascade", async () => {
    const user = userEvent.setup();
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [activeHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(activeHandDetail))
      .mockResolvedValueOnce(
        jsonResponse(
          { detail: "This hand has an interrupted lifecycle write" },
          503,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Reason" }),
      "Remove from study",
    );
    await user.click(screen.getByRole("button", { name: "Withdraw approval" }));

    expect(
      await screen.findByText(
        /lifecycle outcome is unresolved.*Restart the local player runtime.*journal recovery can finish/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Canonical revision 1 is active/),
    ).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(5);
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY)).toBeNull();
  });

  it("refuses a pre-replay detail after the mutation response is lost", async () => {
    const user = userEvent.setup();
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [activeHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(activeHandDetail))
      .mockRejectedValueOnce(new TypeError("connection interrupted"))
      .mockResolvedValueOnce(
        jsonResponse(
          { detail: "This hand has an interrupted lifecycle write" },
          503,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Reason" }),
      "Remove from study",
    );
    await user.click(screen.getByRole("button", { name: "Withdraw approval" }));

    expect(
      await screen.findByText(
        /connection interrupted.*lifecycle outcome is unresolved.*Restart the local player runtime/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Canonical revision 1 is active/),
    ).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(6);
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY)).toBeNull();
  });

  it.each(["canonical revision", "deletion generation"] as const)(
    "does not attribute another withdrawal with a newer %s to the stale request",
    async (mismatch) => {
      const user = userEvent.setup();
      const reason = "Remove from study";
      const inactive = inactiveApprovedHandDetail("withdrawn");
      const refreshed =
        mismatch === "canonical revision"
          ? {
              ...inactive,
              summary: {
                ...inactive.summary,
                canonical_revision_count: 2,
              },
              canonical_revisions: [
                ...inactive.canonical_revisions,
                {
                  ...inactive.canonical_revisions[0],
                  revision: 2,
                  approved_at: "2026-08-30T12:20:00Z",
                },
              ],
              lifecycle: { ...inactive.lifecycle, reason },
            }
          : {
              ...inactive,
              summary: {
                ...inactive.summary,
                deletion_generation: 1,
              },
              lifecycle: {
                ...inactive.lifecycle,
                deletion_generation: 1,
                reason,
              },
            };
      window.location.hash = "#ticket=one-use-ticket";
      vi.spyOn(window, "confirm").mockReturnValue(true);
      const fetchMock = vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(
          jsonResponse({
            session_token: "player-session",
            csrf_token: "csrf-token",
            expires_in_seconds: 86400,
          }),
        )
        .mockResolvedValueOnce(jsonResponse(readyStorage))
        .mockResolvedValueOnce(
          jsonResponse({
            items: [activeHand],
            unreadable: [],
            next_cursor: null,
          }),
        )
        .mockResolvedValueOnce(jsonResponse(activeHandDetail))
        .mockResolvedValueOnce(
          jsonResponse({ detail: "The hand lifecycle changed" }, 409),
        )
        .mockResolvedValueOnce(jsonResponse(refreshed));
      vi.stubGlobal("fetch", fetchMock);

      render(<PlayerApp />);
      await screen.findByText("Ready on this machine");
      await user.click(
        screen.getByRole("button", { name: "Load hand records" }),
      );
      await user.click(
        await screen.findByRole("button", { name: "View audit detail" }),
      );
      await user.type(screen.getByRole("textbox", { name: "Reason" }), reason);
      await user.click(
        screen.getByRole("button", { name: "Withdraw approval" }),
      );

      expect(
        await screen.findByText(
          /Approval state was not changed.*audit detail was refreshed/,
        ),
      ).toHaveTextContent("The hand lifecycle changed");
      expect(
        screen.queryByText(/state committed.*response was interrupted/),
      ).not.toBeInTheDocument();
      expect(
        screen.getByText(/previously approved.*now withdrawn/),
      ).toBeInTheDocument();
    },
  );

  it.each([
    ["withdrawn", /previously approved, but its approval is now withdrawn/],
    ["rejected", /previously approved, then rejected/],
  ] as const)(
    "describes a %s approved hand as retained but inactive",
    async (status, expectedCopy) => {
      const user = userEvent.setup();
      const detail = inactiveApprovedHandDetail(status);
      window.location.hash = "#ticket=one-use-ticket";
      const fetchMock = vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(
          jsonResponse({
            session_token: "player-session",
            csrf_token: "csrf-token",
            expires_in_seconds: 86400,
          }),
        )
        .mockResolvedValueOnce(jsonResponse(readyStorage))
        .mockResolvedValueOnce(
          jsonResponse({
            items: [detail.summary],
            unreadable: [],
            next_cursor: null,
          }),
        )
        .mockResolvedValueOnce(jsonResponse(detail));
      vi.stubGlobal("fetch", fetchMock);

      render(<PlayerApp />);
      await screen.findByText("Ready on this machine");
      await user.click(
        screen.getByRole("button", { name: "Load hand records" }),
      );
      await user.click(
        await screen.findByRole("button", { name: "View audit detail" }),
      );

      expect(await screen.findByText(expectedCopy)).toBeInTheDocument();
      expect(
        screen.queryByText(/proposal until a later review workflow/),
      ).not.toBeInTheDocument();
      expect(
        screen.getByText(
          new RegExp(`Lifecycle reason: ${detail.lifecycle.reason}`),
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByText("Change approval state"),
      ).not.toBeInTheDocument();
    },
  );

  it("permanently deletes an exact retained snapshot with CSRF protection", async () => {
    const user = userEvent.setup();
    const reason = "Remove all retained hand evidence";
    const requestId = "11111111-1111-4111-8111-111111111111" as ReturnType<
      Crypto["randomUUID"]
    >;
    const committed = {
      ...deletedHandDetail,
      summary: {
        ...deletedHand,
        record_version: "8".repeat(64),
        deletion_generation: 1,
        lifecycle_changed_at: "2026-08-30T12:30:00Z",
      },
      lifecycle: {
        ...deletedHandDetail.lifecycle,
        deletion_generation: 1,
        changed_at: "2026-08-30T12:30:00Z",
        reason,
      },
      deletion_receipt: {
        ...deletedHandDetail.deletion_receipt,
        receipt_id: requestId,
        generation: 1,
        deleted_at: "2026-08-30T12:30:00Z",
      },
    };
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue(requestId);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [activeHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(activeHandDetail))
      .mockResolvedValueOnce(jsonResponse(committed));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Permanent deletion reason" }),
      reason,
    );
    await user.click(
      screen.getByRole("button", { name: "Delete permanently" }),
    );

    expect(
      await screen.findByText(/Permanent deletion completed/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Deletion receipt 11111111/)).toHaveTextContent(
      "generation 1",
    );
    expect(window.confirm).toHaveBeenCalledWith(
      expect.stringMatching(/cannot be undone by restoring an older backup/),
    );
    const deleteRequest = fetchMock.mock.calls[4];
    expect(deleteRequest?.[0]).toBe(
      `/api/player/hands/${activeHand.record_key}/delete`,
    );
    expect(deleteRequest?.[1]?.method).toBe("POST");
    const deleteHeaders = new Headers(deleteRequest?.[1]?.headers);
    expect(deleteHeaders.get("Authorization")).toBe("Bearer player-session");
    expect(deleteHeaders.get("X-Poker-CSRF-Token")).toBe("csrf-token");
    expect(deleteHeaders.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(deleteRequest?.[1]?.body))).toEqual({
      request_id: requestId,
      reason,
      expected_record_version: activeHand.record_version,
      expected_lifecycle_status: "active",
      expected_active_canonical_revision: 1,
      expected_deletion_generation: 0,
      expected_lifecycle_changed_at: "2026-08-30T12:00:00Z",
    });
  });

  it("does not send permanent deletion when confirmation is cancelled", async () => {
    const user = userEvent.setup();
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [activeHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(activeHandDetail));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Permanent deletion reason" }),
      "Keep this after all",
    );
    await user.click(
      screen.getByRole("button", { name: "Delete permanently" }),
    );

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(
      screen.getByText(/Canonical revision 1 is active/),
    ).toBeInTheDocument();
  });

  it("refreshes and retries cleanup after the logical deletion already committed", async () => {
    const user = userEvent.setup();
    const reason = "Remove all retained hand evidence";
    const firstRequestId = "11111111-1111-4111-8111-111111111111" as ReturnType<
      Crypto["randomUUID"]
    >;
    const retryRequestId = "22222222-2222-4222-8222-222222222222" as ReturnType<
      Crypto["randomUUID"]
    >;
    const pendingCleanup = {
      ...failedDeletionHandDetail,
      summary: {
        ...failedDeletionHand,
        record_version: "8".repeat(64),
        deletion_generation: 1,
        lifecycle_changed_at: "2026-08-30T12:30:00Z",
      },
      lifecycle: {
        ...failedDeletionHandDetail.lifecycle,
        deletion_generation: 1,
        changed_at: "2026-08-30T12:30:00Z",
        reason,
        deletion_request: {
          generation: 1,
          requested_at: "2026-08-30T12:30:00Z",
          cleanup_status: "pending",
          last_error: null,
        },
      },
    };
    const committed = {
      ...deletedHandDetail,
      summary: {
        ...deletedHand,
        record_version: "7".repeat(64),
        deletion_generation: 1,
        lifecycle_changed_at: "2026-08-30T12:31:00Z",
      },
      lifecycle: {
        ...deletedHandDetail.lifecycle,
        deletion_generation: 1,
        changed_at: "2026-08-30T12:31:00Z",
        reason,
      },
      deletion_receipt: {
        ...deletedHandDetail.deletion_receipt,
        receipt_id: retryRequestId,
        generation: 1,
        deleted_at: "2026-08-30T12:31:00Z",
      },
    };
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window.crypto, "randomUUID")
      .mockReturnValueOnce(firstRequestId)
      .mockReturnValueOnce(retryRequestId);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [activeHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(activeHandDetail))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Retained artifact cleanup failed" }, 500),
      )
      .mockResolvedValueOnce(jsonResponse(pendingCleanup))
      .mockResolvedValueOnce(jsonResponse(committed));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Permanent deletion reason" }),
      reason,
    );
    await user.click(
      screen.getByRole("button", { name: "Delete permanently" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "deletion cleanup is pending",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Retained artifact cleanup failed",
    );
    expect(
      screen.getByRole("textbox", { name: "Permanent deletion reason" }),
    ).toHaveValue(reason);
    await user.click(
      screen.getByRole("button", { name: "Retry deletion cleanup" }),
    );

    expect(
      await screen.findByText(/Permanent deletion completed/),
    ).toBeInTheDocument();
    const retryRequest = fetchMock.mock.calls[6];
    expect(JSON.parse(String(retryRequest?.[1]?.body))).toEqual({
      request_id: retryRequestId,
      reason,
      expected_record_version: pendingCleanup.summary.record_version,
      expected_lifecycle_status: "deletion_pending",
      expected_active_canonical_revision: null,
      expected_deletion_generation: 1,
      expected_lifecycle_changed_at: "2026-08-30T12:30:00Z",
    });
  });

  it("recognizes an exact deletion receipt after the mutation response is lost", async () => {
    const user = userEvent.setup();
    const requestId = "11111111-1111-4111-8111-111111111111" as ReturnType<
      Crypto["randomUUID"]
    >;
    const committed = {
      ...deletedHandDetail,
      summary: {
        ...deletedHand,
        deletion_generation: 1,
      },
      lifecycle: {
        ...deletedHandDetail.lifecycle,
        deletion_generation: 1,
      },
      deletion_receipt: {
        ...deletedHandDetail.deletion_receipt,
        receipt_id: requestId,
        generation: 1,
      },
    };
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue(requestId);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [activeHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(activeHandDetail))
      .mockRejectedValueOnce(new TypeError("connection interrupted"))
      .mockResolvedValueOnce(jsonResponse(committed));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Permanent deletion reason" }),
      "Remove all retained hand evidence",
    );
    await user.click(
      screen.getByRole("button", { name: "Delete permanently" }),
    );

    expect(
      await screen.findByText(
        /Permanent deletion committed.*receipt was refreshed/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not attribute another deletion receipt to the interrupted request", async () => {
    const user = userEvent.setup();
    const requestId = "11111111-1111-4111-8111-111111111111" as ReturnType<
      Crypto["randomUUID"]
    >;
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue(requestId);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [activeHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(activeHandDetail))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "The retained hand changed" }, 409),
      )
      .mockResolvedValueOnce(jsonResponse(deletedHandDetail));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Permanent deletion reason" }),
      "Remove all retained hand evidence",
    );
    await user.click(
      screen.getByRole("button", { name: "Delete permanently" }),
    );

    expect(
      await screen.findByText(/Permanent deletion was not confirmed/),
    ).toHaveTextContent("The retained hand changed");
    expect(
      screen.queryByText(/Permanent deletion committed.*receipt was refreshed/),
    ).not.toBeInTheDocument();
  });

  it("requires restart recovery after an interrupted deletion cascade", async () => {
    const user = userEvent.setup();
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [activeHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(activeHandDetail))
      .mockResolvedValueOnce(
        jsonResponse(
          { detail: "This hand has an interrupted lifecycle write" },
          503,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Permanent deletion reason" }),
      "Remove all retained hand evidence",
    );
    await user.click(
      screen.getByRole("button", { name: "Delete permanently" }),
    );

    expect(
      await screen.findByText(
        /lifecycle outcome is unresolved.*Restart the local player runtime/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(5);
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY)).toBeNull();
  });

  it("surfaces a failed deletion cleanup instead of generic inactive copy", async () => {
    const user = userEvent.setup();
    window.location.hash = "#ticket=one-use-ticket";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [failedDeletionHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(failedDeletionHandDetail));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );

    expect(
      await screen.findByText(
        /Deletion cleanup failed: retained artifact cleanup failed/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("needs repair");
    expect(
      screen.getByText(/Lifecycle reason: delete requested/),
    ).toBeInTheDocument();
  });

  it("renders the complete retained deletion receipt", async () => {
    const user = userEvent.setup();
    window.location.hash = "#ticket=one-use-ticket";
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [deletedHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(deletedHandDetail));
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );

    expect(
      await screen.findByText(/Deletion receipt receipt-3/),
    ).toHaveTextContent("generation 3");
    expect(screen.getByText("f".repeat(64))).toBeInTheDocument();
  });

  it("explicitly reimports a tombstone as fresh pending-review evidence", async () => {
    const user = userEvent.setup();
    const requestId = "77777777-7777-4777-8777-777777777777" as ReturnType<
      Crypto["randomUUID"]
    >;
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue(requestId);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [deletedHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(deletedHandDetail))
      .mockResolvedValueOnce(
        jsonResponse({
          request_id: requestId,
          disposition: "restored_pending_review",
          parser_disposition: "clean",
          reconciliation_status: "pass",
          hand: reimportedHandDetail,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    const file = new File(["PokerStars Hand #123456789"], "hands.txt", {
      type: "text/plain",
    });
    await user.upload(
      screen.getByLabelText("PokerStars file containing this deleted hand"),
      file,
    );
    await user.click(
      screen.getByRole("button", { name: "Authorize reimport for review" }),
    );

    expect(window.confirm).toHaveBeenCalledWith(
      expect.stringMatching(/new deletion generation.*pending review/),
    );
    expect(
      await screen.findByText(/Authorized reimport completed/),
    ).toHaveTextContent("ineligible for learning");
    expect(
      screen.getByText(/Lifecycle reason: authorized reimport/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve canonical state" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Authorize reimport for review" }),
    ).not.toBeInTheDocument();
    expect(localStorage.getItem(PLAYER_REIMPORT_RETRY_STORAGE_KEY)).toBeNull();

    const reimportRequest = fetchMock.mock.calls[4];
    expect(reimportRequest?.[0]).toBe(
      `/api/player/hands/${deletedHand.record_key}/reimport`,
    );
    expect(reimportRequest?.[1]?.method).toBe("POST");
    const headers = new Headers(reimportRequest?.[1]?.headers);
    expect(headers.get("Authorization")).toBe("Bearer player-session");
    expect(headers.get("X-Poker-CSRF-Token")).toBe("csrf-token");
    const body = reimportRequest?.[1]?.body as FormData;
    expect(body.get("request_id")).toBe(requestId);
    expect(body.get("expected_record_version")).toBe(
      deletedHand.record_version,
    );
    expect(body.get("expected_lifecycle_status")).toBe("deleted");
    expect(body.get("expected_deletion_generation")).toBe("3");
    expect(body.get("expected_lifecycle_changed_at")).toBe(
      deletedHand.lifecycle_changed_at,
    );
    const uploadedFile = body.get("file") as File;
    expect(uploadedFile.name).toBe(file.name);
    expect(await uploadedFile.text()).toBe(await file.text());
  });

  it("retries the same authorized reimport after an ambiguous response", async () => {
    const user = userEvent.setup();
    const requestId = "77777777-7777-4777-8777-777777777777" as ReturnType<
      Crypto["randomUUID"]
    >;
    window.location.hash = "#ticket=one-use-ticket";
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue(requestId);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          session_token: "player-session",
          csrf_token: "csrf-token",
          expires_in_seconds: 86400,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [deletedHand],
          unreadable: [],
          next_cursor: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(deletedHandDetail))
      .mockRejectedValueOnce(new TypeError("connection reset"))
      .mockResolvedValueOnce(
        jsonResponse({
          request_id: requestId,
          disposition: "duplicate_request",
          parser_disposition: "clean",
          reconciliation_status: "pass",
          hand: reimportedHandDetail,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    await user.click(
      await screen.findByRole("button", { name: "View audit detail" }),
    );
    await user.upload(
      screen.getByLabelText("PokerStars file containing this deleted hand"),
      new File(["PokerStars Hand #123456789"], "hands.txt"),
    );
    await user.click(
      screen.getByRole("button", { name: "Authorize reimport for review" }),
    );

    expect(
      await screen.findByText(/authorized reimport had already committed/i),
    ).toHaveTextContent("without duplication");
    expect(fetchMock.mock.calls[4]?.[0]).toBe(fetchMock.mock.calls[5]?.[0]);
    const firstBody = fetchMock.mock.calls[4]?.[1]?.body as FormData;
    const retryBody = fetchMock.mock.calls[5]?.[1]?.body as FormData;
    expect(firstBody.get("request_id")).toBe(requestId);
    expect(retryBody.get("request_id")).toBe(requestId);
  });

  it("restores with session and CSRF headers, then refreshes storage", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse({
          imported_records: 2,
          reused_records: 1,
          skipped_stale_records: 0,
          imported_decision_artifacts: 2,
          reused_decision_artifacts: 1,
          removed_decision_artifacts: 0,
          imported_grade_artifacts: 1,
          reused_grade_artifacts: 0,
          removed_grade_artifacts: 0,
          total_records: 5,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ ...readyStorage, imported_hand_record_count: 5 }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    const backup = new File(["backup"], "player-backup.zip", {
      type: "application/zip",
    });
    await user.upload(screen.getByLabelText("Player backup ZIP"), backup);
    await user.click(screen.getByRole("button", { name: "Restore backup" }));

    expect(await screen.findByText("Restore committed.")).toBeInTheDocument();
    expect(
      screen.getByText(
        /2 decision artifacts imported, 1 already present, 0 removed by restored deletion evidence/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("5 local records now retained."),
    ).toBeInTheDocument();
    const restoreRequest = fetchMock.mock.calls[1];
    expect(restoreRequest?.[0]).toBe("/api/player/backups/restore");
    const restoreHeaders = new Headers(restoreRequest?.[1]?.headers);
    expect(restoreHeaders.get("Authorization")).toBe("Bearer stored-session");
    expect(restoreHeaders.get("X-Poker-CSRF-Token")).toBe("stored-csrf");
    expect(restoreHeaders.get("Content-Type")).toBe("application/zip");
    expect(restoreRequest?.[1]?.body).toBe(backup);
  });

  it("surfaces quarantined recovery evidence and disables import", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    const unreadableKey = "d".repeat(64);
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        jsonResponse({
          ...readyStorage,
          status: "attention_required",
          recovery: {
            completed: [],
            quarantined: ["cascade-one"],
            failed: ["cascade-two"],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          items: [pendingHand],
          unreadable: [
            {
              record_key: unreadableKey,
              detail: "Stored imported hand record could not be read safely",
            },
          ],
          next_cursor: null,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<PlayerApp />);

    expect(
      await screen.findByText("Recovery attention required"),
    ).toBeInTheDocument();
    expect(screen.getByText("2", { selector: "dd" })).toBeInTheDocument();
    expect(
      screen.getByText(
        /Bounded PokerStars text import.*Imported parser output remains pending review.*V2 learning loop is not enabled/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("PokerStars hand-history files"),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Import for review" }),
    ).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Load hand records" }));
    expect(
      await screen.findByText("site-hand-id/v1 · pokerstars #123456789"),
    ).toBeInTheDocument();
    expect(screen.getByText(unreadableKey).closest("li")).toHaveTextContent(
      "Stored imported hand record could not be read safely",
    );
  });

  it("clears an expired stored session when storage bootstrap is unauthorized", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "expired-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "expired-csrf");
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(jsonResponse({ detail: "Expired" }, 401)),
    );

    render(<PlayerApp />);

    expect(
      await screen.findByText(
        "The local player session expired. Start the runtime again to reconnect.",
      ),
    ).toBeInTheDocument();
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY)).toBeNull();
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
  });

  it("closes an expired session when restore is unauthorized", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(jsonResponse(readyStorage))
        .mockResolvedValueOnce(jsonResponse({ detail: "Expired" }, 401)),
    );
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.upload(
      screen.getByLabelText("Player backup ZIP"),
      new File(["backup"], "player-backup.zip", {
        type: "application/zip",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Restore backup" }));

    expect(
      await screen.findByText(
        "The local player session expired. Start the runtime again to reconnect.",
      ),
    ).toBeInTheDocument();
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY)).toBeNull();
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
  });

  it("preserves committed evidence but hides stale controls when refresh fails", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(jsonResponse(readyStorage))
        .mockResolvedValueOnce(
          jsonResponse({
            imported_records: 2,
            reused_records: 1,
            skipped_stale_records: 0,
            imported_decision_artifacts: 2,
            reused_decision_artifacts: 1,
            removed_decision_artifacts: 1,
            imported_grade_artifacts: 1,
            reused_grade_artifacts: 0,
            removed_grade_artifacts: 1,
            total_records: 5,
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({ detail: "Stable status unavailable" }, 409),
        ),
    );
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.upload(
      screen.getByLabelText("Player backup ZIP"),
      new File(["backup"], "player-backup.zip", {
        type: "application/zip",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Restore backup" }));

    expect(await screen.findByText("Restore committed.")).toBeInTheDocument();
    expect(
      screen.getAllByText(/1 removed by restored deletion evidence/),
    ).toHaveLength(2);
    expect(
      await screen.findByText(
        /Restore committed, but storage status could not be refreshed/,
      ),
    ).toBeInTheDocument();
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBe(
      "stored-session",
    );
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Download backup" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Restore backup" }),
    ).not.toBeInTheDocument();
  });

  it("treats an incomplete successful restore response as ambiguous", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        new Response("{", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ ...readyStorage, imported_hand_record_count: 5 }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    const backupInput = screen.getByLabelText(
      "Player backup ZIP",
    ) as HTMLInputElement;
    await user.upload(
      backupInput,
      new File(["backup"], "player-backup.zip", {
        type: "application/zip",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Restore backup" }));

    expect(
      await screen.findByText(
        /The restore may have committed, but the browser did not receive a complete response/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("5", { selector: "dd" })).toBeInTheDocument();
    expect(backupInput.value).toBe("");
    expect(
      screen.getByRole("button", { name: "Restore backup" }),
    ).toBeDisabled();
    expect(screen.queryByText("Restore committed.")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls[2]?.[0]).toBe("/api/player/storage");
  });

  it("treats a restore transport rejection as ambiguous", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(
        jsonResponse({ ...readyStorage, imported_hand_record_count: 5 }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    const backupInput = screen.getByLabelText(
      "Player backup ZIP",
    ) as HTMLInputElement;
    await user.upload(
      backupInput,
      new File(["backup"], "player-backup.zip", {
        type: "application/zip",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Restore backup" }));

    expect(
      await screen.findByText(
        /The restore may have committed, but the browser did not receive a complete response/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("5", { selector: "dd" })).toBeInTheDocument();
    expect(backupInput.value).toBe("");
    expect(
      screen.getByRole("button", { name: "Restore backup" }),
    ).toBeDisabled();
    expect(screen.queryByText("Restore committed.")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls[2]?.[0]).toBe("/api/player/storage");
  });

  it("hides stale storage when an ambiguous refresh fails", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        new Response("{", {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Stable storage snapshot unavailable" }, 409),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    const backupInput = screen.getByLabelText(
      "Player backup ZIP",
    ) as HTMLInputElement;
    await user.upload(
      backupInput,
      new File(["backup"], "player-backup.zip", {
        type: "application/zip",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Restore backup" }));

    expect(
      await screen.findByText(
        /A stable storage status could not be obtained. Restart the local player runtime before exporting a backup or retrying/,
      ),
    ).toBeInTheDocument();
    expect(backupInput.value).toBe("");
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Restore backup" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Restore committed.")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("requires restart recovery after a restore storage failure", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail:
              "Player backup restore did not complete; restart the local runtime before retrying so journal recovery can finish",
          },
          503,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    const backupInput = screen.getByLabelText(
      "Player backup ZIP",
    ) as HTMLInputElement;
    await user.upload(
      backupInput,
      new File(["backup"], "player-backup.zip", {
        type: "application/zip",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Restore backup" }));

    expect(
      await screen.findByText(
        /Restart the local player runtime so journal recovery can finish before exporting a backup or retrying/,
      ),
    ).toBeInTheDocument();
    expect(backupInput.value).toBe("");
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Restore backup" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Restore committed.")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY)).toBeNull();
  });

  it("downloads an authenticated backup without sending a CSRF header", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(
        new Response(new Blob(["backup"]), {
          headers: {
            "Content-Disposition": 'attachment; filename="player-safe.zip"',
            "Content-Type": "application/zip",
          },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const createObjectURL = vi.fn(() => "blob:player-backup");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal(
      "URL",
      class PlayerUrl extends URL {
        static createObjectURL = createObjectURL;
        static revokeObjectURL = revokeObjectURL;
      },
    );
    let clickedLink: HTMLAnchorElement | null = null;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clickedLink = this;
    });
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Download backup" }));

    await waitFor(() => expect(revokeObjectURL).toHaveBeenCalled());
    const exportRequest = fetchMock.mock.calls[1];
    expect(exportRequest?.[0]).toBe("/api/player/backups/export");
    expect(exportRequest?.[1]?.method).toBe("GET");
    const exportHeaders = new Headers(exportRequest?.[1]?.headers);
    expect(exportHeaders.get("Authorization")).toBe("Bearer stored-session");
    expect(exportHeaders.has("X-Poker-CSRF-Token")).toBe(false);
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(clickedLink).toMatchObject({
      href: "blob:player-backup",
      download: "player-safe.zip",
    });
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:player-backup");
  });

  it("revokes the session with CSRF protection and clears local credentials", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(readyStorage))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Close session" }));

    expect(
      await screen.findByText(
        "Session closed. Start the runtime again when you are ready.",
      ),
    ).toBeInTheDocument();
    const signOutRequest = fetchMock.mock.calls[1];
    expect(signOutRequest?.[0]).toBe("/api/player/session");
    expect(signOutRequest?.[1]?.method).toBe("DELETE");
    const signOutHeaders = new Headers(signOutRequest?.[1]?.headers);
    expect(signOutHeaders.get("Authorization")).toBe("Bearer stored-session");
    expect(signOutHeaders.get("X-Poker-CSRF-Token")).toBe("stored-csrf");
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY)).toBeNull();
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
  });

  it("clears the visible session when server revocation cannot be confirmed", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockResolvedValueOnce(jsonResponse(readyStorage))
        .mockResolvedValueOnce(
          jsonResponse({ detail: "Revocation unavailable" }, 503),
        ),
    );
    const user = userEvent.setup();

    render(<PlayerApp />);
    await screen.findByText("Ready on this machine");
    await user.click(screen.getByRole("button", { name: "Close session" }));

    expect(
      await screen.findByText(
        /Local credentials were cleared, but the runtime could not confirm session revocation/,
      ),
    ).toBeInTheDocument();
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBeNull();
    expect(sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY)).toBeNull();
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Download backup" }),
    ).not.toBeInTheDocument();
  });
});
