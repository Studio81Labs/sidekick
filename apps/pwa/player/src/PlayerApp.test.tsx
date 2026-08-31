import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PlayerApp from "./PlayerApp";
import {
  PLAYER_CSRF_STORAGE_KEY,
  PLAYER_SESSION_STORAGE_KEY,
} from "./playerApi";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const readyStorage = {
  status: "ready",
  storage: "player-local-file",
  data_directory: "/private/player-data",
  imported_hand_record_count: 3,
  recovery: { completed: [], quarantined: [], failed: [] },
};

describe("PlayerApp", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    sessionStorage.clear();
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

  it("surfaces quarantined recovery evidence without enabling import", async () => {
    sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, "stored-session");
    sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, "stored-csrf");
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>().mockResolvedValueOnce(
        jsonResponse({
          ...readyStorage,
          status: "attention_required",
          recovery: {
            completed: [],
            quarantined: ["cascade-one"],
            failed: ["cascade-two"],
          },
        }),
      ),
    );

    render(<PlayerApp />);

    expect(
      await screen.findByText("Recovery attention required"),
    ).toBeInTheDocument();
    expect(screen.getByText("2", { selector: "dd" })).toBeInTheDocument();
    expect(
      screen.getByText(
        /Hand-history import, review, and learning are not enabled/,
      ),
    ).toBeInTheDocument();
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

  it("preserves committed restore evidence when its status refresh expires", async () => {
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
            total_records: 5,
          }),
        )
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

    expect(await screen.findByText("Restore committed.")).toBeInTheDocument();
    expect(
      screen.getByText(/1 removed by restored deletion evidence/),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        /Restore committed, but storage status could not be refreshed/,
      ),
    ).toBeInTheDocument();
    expect(sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY)).toBeNull();
    expect(screen.queryByText("Ready on this machine")).not.toBeInTheDocument();
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
