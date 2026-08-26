import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { CanonicalState } from "../../../shared/types/poker";
import type { JobRecord } from "../../../shared/types/jobs";
import {
  AnalyzerTestApp as App,
  approvedJob,
  canonicalState,
  deferredResponse,
  fetchMock,
  jobRecord,
  jsonResponse,
  recommendation,
  recommendedJob,
} from "../../../test/analyzerHarness";

describe("Analyzer history", () => {
  it("loads saved history and reopens a reviewed hand", async () => {
    const savedState = canonicalState({
      hero_cards: [
        { rank: "7", suit: "diamonds" },
        { rank: "A", suit: "hearts" },
      ],
      board_cards: [],
      pot_size: 3.5,
      street: "preflop",
    });
    delete (savedState as Partial<CanonicalState>).hero_stack;
    delete (savedState as Partial<CanonicalState>).facing_action;
    const savedJob: JobRecord = {
      ...recommendedJob(savedState),
      id: "history-job",
      original_filename: "history.png",
      image_filename: "history.png",
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: savedJob.id, job: savedJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    const historyItem = screen.getByRole("button", {
      name: "Reopen history item 1",
    });
    expect(within(historyItem).getByText("7♦")).toBeInTheDocument();

    await user.click(historyItem);

    expect(await screen.findByDisplayValue("7d Ah")).toBeInTheDocument();
    expect(screen.getByDisplayValue("3.5")).toBeInTheDocument();
    expect(screen.getByLabelText(/Hero stack/)).toHaveValue("");
    expect(screen.getByLabelText(/Facing action/)).toHaveValue("");
    expect(screen.getByLabelText("Recommendation")).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Decision evidence"),
    ).not.toBeInTheDocument();
  });

  it("updates persisted history immediately after a reopened hand is re-approved", async () => {
    const archivedAt = "2026-07-10T00:02:00Z";
    const savedJob: JobRecord = {
      ...recommendedJob(),
      archived_at: archivedAt,
    };
    const reapprovedJob: JobRecord = {
      ...approvedJob(),
      archived_at: archivedAt,
      updated_at: "2026-07-10T00:03:00Z",
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: savedJob.id,
          job: savedJob,
          savedAt: archivedAt,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    fetchMock().mockResolvedValueOnce(jsonResponse(reapprovedJob));
    render(<App />);
    const user = userEvent.setup();

    expect(
      within(
        screen.getByRole("button", {
          name: "Reopen history item 1",
        }),
      ).getByText("raise"),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: "Reopen history item 1",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Reset to parser" }));
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    const updatedHistoryItem = screen.getByRole("button", {
      name: "Reopen history item 1",
    });
    await waitFor(() =>
      expect(
        within(updatedHistoryItem).getByText("approved"),
      ).toBeInTheDocument(),
    );
    expect(
      within(updatedHistoryItem).queryByText("raise"),
    ).not.toBeInTheDocument();
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-history-v1")),
      )[0].job,
    ).toMatchObject({
      status: "approved",
      recommendation: null,
      updated_at: "2026-07-10T00:03:00Z",
    });
  });

  it("keeps a newer reopened hand when an older history refresh finishes", async () => {
    const archivedAt = "2026-07-10T00:02:00Z";
    const staleJob: JobRecord = {
      ...recommendedJob(),
      archived_at: archivedAt,
      updated_at: "2026-07-10T00:01:00Z",
    };
    const reapprovedJob: JobRecord = {
      ...approvedJob(),
      archived_at: archivedAt,
      updated_at: "2026-07-10T00:03:00Z",
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: staleJob.id,
          job: staleJob,
          savedAt: archivedAt,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-history-synced");
    const pendingHistory = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingHistory.promise)
      .mockResolvedValueOnce(jsonResponse(reapprovedJob));
    render(<App />);
    const user = userEvent.setup();

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
    await user.click(
      screen.getByRole("button", {
        name: "Reopen history item 1",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Reset to parser" }));
    await user.click(screen.getByRole("button", { name: "Approve state" }));
    await waitFor(() =>
      expect(
        within(
          screen.getByRole("button", {
            name: "Reopen history item 1",
          }),
        ).getByText("approved"),
      ).toBeInTheDocument(),
    );

    pendingHistory.resolve(
      jsonResponse({
        total: 1,
        jobs: [staleJob],
      }),
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Refresh saved history",
        }),
      ).toBeEnabled(),
    );
    const historyItem = screen.getByRole("button", {
      name: "Reopen history item 1",
    });
    expect(within(historyItem).getByText("approved")).toBeInTheDocument();
    expect(within(historyItem).queryByText("raise")).not.toBeInTheDocument();
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-history-v1")),
      )[0].job,
    ).toMatchObject({
      status: "approved",
      recommendation: null,
      updated_at: "2026-07-10T00:03:00Z",
    });
  });

  it("restores persisted history when the browser has no local cache", async () => {
    window.localStorage.removeItem("poker-training-history-v1");
    window.sessionStorage.removeItem("poker-training-history-synced");
    const savedJob: JobRecord = {
      ...recommendedJob(
        canonicalState({
          hero_cards: [
            { rank: "Q", suit: "clubs" },
            { rank: "Q", suit: "hearts" },
          ],
        }),
      ),
      id: "server-history-job",
      original_filename: "server-history.png",
      archived_at: "2026-07-10T00:02:00Z",
    };
    fetchMock().mockResolvedValueOnce(
      jsonResponse({
        total: 3,
        jobs: [savedJob],
      }),
    );

    render(<App />);

    const historyItem = await screen.findByRole("button", {
      name: "Reopen history item 1",
    });
    expect(within(historyItem).getByText("Q♣")).toBeInTheDocument();
    expect(
      within(screen.getByLabelText("Session status")).getByText("3"),
    ).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledWith(
      "http://localhost:8000/api/history",
      { credentials: "include" },
    );
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-history-v1")),
      ),
    ).toHaveLength(1);
  });

  it("preserves the complete persisted history count across same-tab reloads", async () => {
    window.localStorage.removeItem("poker-training-history-v1");
    window.sessionStorage.removeItem("poker-training-history-synced");
    const savedJobs = Array.from(
      { length: 24 },
      (_, index): JobRecord => ({
        ...recommendedJob(),
        id: `server-history-${index}`,
        original_filename: `server-history-${index}.png`,
        archived_at: `2026-07-10T00:${String(index).padStart(2, "0")}:00Z`,
      }),
    );
    fetchMock().mockResolvedValueOnce(
      jsonResponse({
        total: 31,
        jobs: savedJobs,
      }),
    );

    const firstRender = render(<App />);
    expect(
      await within(screen.getByLabelText("Session status")).findByText("31"),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem("poker-training-history-total-v1")).toBe(
      "31",
    );
    firstRender.unmount();

    render(<App />);

    expect(
      within(screen.getByLabelText("Session status")).getByText("31"),
    ).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(1);
  });

  it("loads older persisted history without expanding the local cache", async () => {
    window.localStorage.removeItem("poker-training-history-v1");
    window.sessionStorage.removeItem("poker-training-history-synced");
    const savedJobs = Array.from(
      { length: 31 },
      (_, index): JobRecord => ({
        ...recommendedJob(),
        id: `paged-history-${index}`,
        original_filename: `paged-history-${index}.png`,
        archived_at: `2026-07-${String(31 - index).padStart(2, "0")}T00:00:00Z`,
      }),
    );
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: 31,
          jobs: savedJobs.slice(0, 24),
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 31,
          jobs: savedJobs.slice(24),
        }),
      );
    render(<App />);
    const user = userEvent.setup();

    const loadOlder = await screen.findByRole("button", {
      name: "Load older history",
    });
    expect(loadOlder).toHaveTextContent("Load 7 older");
    await user.click(loadOlder);

    expect(
      await screen.findByRole("button", {
        name: "Reopen history item 31",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Load older history",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock()).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/api/history?offset=24",
      { credentials: "include" },
    );
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-history-v1")),
      ),
    ).toHaveLength(24);
  });

  it("searches and pages archived hands without replacing the newest-page cache", async () => {
    const archivedAt = "2026-07-10T00:02:00Z";
    const cachedJob: JobRecord = {
      ...recommendedJob(),
      id: "cached-history-job",
      archived_at: archivedAt,
    };
    const firstMatch: JobRecord = {
      ...recommendedJob(
        canonicalState({
          hero_cards: [
            { rank: "Q", suit: "clubs" },
            { rank: "Q", suit: "hearts" },
          ],
          street: "turn",
        }),
      ),
      id: "matching-history-1",
      original_filename: "turn-bluff-1.png",
      archived_at: "2026-07-09T00:00:00Z",
    };
    const secondMatch: JobRecord = {
      ...recommendedJob(
        canonicalState({
          hero_cards: [
            { rank: "7", suit: "diamonds" },
            { rank: "9", suit: "clubs" },
          ],
          street: "turn",
        }),
      ),
      id: "matching-history-2",
      original_filename: "turn-bluff-2.png",
      archived_at: "2026-07-08T00:00:00Z",
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: cachedJob.id,
          job: cachedJob,
          savedAt: archivedAt,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: 2,
          jobs: [firstMatch],
          snapshot_version: "stable-search",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 2,
          jobs: [secondMatch],
          snapshot_version: "stable-search",
        }),
      );
    render(<App />);
    const user = userEvent.setup();
    const historyPanel = screen.getByLabelText("Session history");

    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Search saved history",
      }),
    );
    await user.type(
      within(historyPanel).getByLabelText("History search query"),
      "turn bluff",
    );
    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Run history search",
      }),
    );

    expect(await within(historyPanel).findByText("Q♣")).toBeInTheDocument();
    expect(within(historyPanel).getByText(/2 matches/)).toBeInTheDocument();
    expect(
      within(historyPanel).getByRole("button", {
        name: "Load older history",
      }),
    ).toHaveTextContent("Load 1 older");
    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Load older history",
      }),
    );

    expect(await within(historyPanel).findByText("7♦")).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/api/history?query=turn+bluff",
      { credentials: "include" },
    );
    expect(fetchMock()).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/api/history?offset=1&query=turn+bluff",
      { credentials: "include" },
    );
    expect(
      within(screen.getByLabelText("Session status")).getByText("1"),
    ).toBeInTheDocument();
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-history-v1")),
      )[0].id,
    ).toBe(cachedJob.id);

    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Close history search",
      }),
    );

    expect(within(historyPanel).getByText("A♥")).toBeInTheDocument();
    expect(within(historyPanel).queryByText("Q♣")).not.toBeInTheDocument();
  });

  it("polls a pending archived recommendation returned only by history search", async () => {
    const cachedJob: JobRecord = {
      ...recommendedJob(),
      id: "cached-search-anchor",
      archived_at: "2026-07-10T00:00:00Z",
    };
    const pendingJob: JobRecord = {
      ...approvedJob(),
      id: "search-only-pending-job",
      original_filename: "search-only-pending.png",
      recommendation_pending: true,
      archived_at: "2026-06-01T00:00:00Z",
      updated_at: "2026-06-01T00:01:00Z",
    };
    const completedJob: JobRecord = {
      ...pendingJob,
      status: "recommended",
      recommendation_pending: false,
      recommendation,
      updated_at: "2026-06-01T00:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: cachedJob.id,
          job: cachedJob,
          savedAt: cachedJob.archived_at,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: 1,
          jobs: [pendingJob],
          snapshot_version: "pending-search-result",
        }),
      )
      .mockResolvedValueOnce(jsonResponse(completedJob));
    render(<App />);
    const user = userEvent.setup();
    const historyPanel = screen.getByLabelText("Session history");

    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Search saved history",
      }),
    );
    await user.type(
      within(historyPanel).getByLabelText("History search query"),
      "pending",
    );
    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Run history search",
      }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    );

    expect(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    ).toBeDisabled();
    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    expect(screen.getByText(recommendation.explanation)).toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/history?query=pending",
      `http://localhost:8000/api/jobs/${pendingJob.id}`,
    ]);
  });

  it("restores a lost archived write response by ID outside the newest history page", async () => {
    const cachedJob: JobRecord = {
      ...recommendedJob(),
      id: "newest-history-anchor",
      archived_at: "2026-07-10T00:00:00Z",
    };
    const targetJob = jobRecord({
      id: "older-search-write-target",
      original_filename: "older-search-write-target.png",
      archived_at: "2026-06-01T00:00:00Z",
      created_at: "2026-06-01T00:00:00Z",
      updated_at: "2026-06-01T00:01:00Z",
    });
    const persistedJob: JobRecord = {
      ...targetJob,
      status: "approved",
      approved_state: canonicalState({ pot_size: 20 }),
      updated_at: "2026-06-01T00:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: cachedJob.id,
          job: cachedJob,
          savedAt: cachedJob.archived_at,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: 1,
          jobs: [targetJob],
          snapshot_version: "older-write-target",
        }),
      )
      .mockRejectedValueOnce(
        new TypeError("Connection lost after archived approval"),
      )
      .mockRejectedValueOnce(
        new TypeError("Temporary archived job restore failure"),
      )
      .mockResolvedValueOnce(jsonResponse(persistedJob))
      .mockResolvedValueOnce(
        jsonResponse({
          total: 1,
          jobs: [cachedJob],
          snapshot_version: "newest-history-after-write",
        }),
      );
    render(<App />);
    const user = userEvent.setup();
    const historyPanel = screen.getByLabelText("Session history");

    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Search saved history",
      }),
    );
    await user.type(
      within(historyPanel).getByLabelText("History search query"),
      "older target",
    );
    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Run history search",
      }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    );
    const potInput = await screen.findByDisplayValue("12.5");
    await user.clear(potInput);
    await user.type(potInput, "20");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    expect(
      await screen.findByText("Connection lost after archived approval"),
    ).toBeInTheDocument();
    expect(await screen.findByDisplayValue("20")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Approve state",
        }),
      ).toBeDisabled(),
    );
    await waitFor(() =>
      expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
        "http://localhost:8000/api/history?query=older+target",
        `http://localhost:8000/api/jobs/${targetJob.id}/approve`,
        `http://localhost:8000/api/jobs/${targetJob.id}`,
        `http://localhost:8000/api/jobs/${targetJob.id}`,
        "http://localhost:8000/api/history",
      ]),
    );
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-history-v1")),
      )[0].id,
    ).toBe(cachedJob.id);
  });

  it("completes a queued full history restore after targeted archived recovery", async () => {
    const targetJob = jobRecord({
      id: "queued-full-restore-target",
      original_filename: "queued-full-restore-target.png",
      archived_at: "2026-06-01T00:00:00Z",
      created_at: "2026-06-01T00:00:00Z",
      updated_at: "2026-06-01T00:01:00Z",
    });
    const persistedTarget: JobRecord = {
      ...targetJob,
      status: "approved",
      approved_state: canonicalState({ pot_size: 20 }),
      updated_at: "2026-06-01T00:02:00Z",
    };
    const staleSibling: JobRecord = {
      ...recommendedJob(),
      id: "stale-history-sibling",
      original_filename: "stale-history-sibling.png",
      archived_at: "2026-07-10T00:00:00Z",
      updated_at: "2026-07-10T00:00:00Z",
    };
    const refreshedSibling: JobRecord = {
      ...staleSibling,
      original_filename: "refreshed-history-sibling.png",
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: targetJob.id,
          job: targetJob,
          savedAt: targetJob.archived_at,
        },
        {
          id: staleSibling.id,
          job: staleSibling,
          savedAt: staleSibling.archived_at,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "2");
    window.sessionStorage.removeItem("poker-training-history-synced");
    const pendingFullRestore = deferredResponse();
    const pendingTargetRestore = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingFullRestore.promise)
      .mockRejectedValueOnce(
        new TypeError("Connection lost after archived approval"),
      )
      .mockReturnValueOnce(pendingTargetRestore.promise)
      .mockResolvedValueOnce(
        jsonResponse({
          total: 2,
          jobs: [refreshedSibling, persistedTarget],
          snapshot_version: "reconciled-full-history",
        }),
      );
    render(<App />);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/history",
        { credentials: "include" },
      ),
    );
    await user.click(
      screen.getByRole("button", {
        name: "Reopen history item 1",
      }),
    );
    const potInput = await screen.findByDisplayValue("12.5");
    await user.clear(potInput);
    await user.type(potInput, "20");
    await user.click(screen.getByRole("button", { name: "Approve state" }));
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenNthCalledWith(
        3,
        `http://localhost:8000/api/jobs/${targetJob.id}`,
        { credentials: "include" },
      ),
    );

    await act(async () => {
      pendingFullRestore.resolve(
        jsonResponse({
          total: 1,
          jobs: [targetJob],
          snapshot_version: "invalidated-full-history",
        }),
      );
      await pendingFullRestore.promise;
    });
    expect(
      window.sessionStorage.getItem("poker-training-history-synced"),
    ).toBeNull();

    await act(async () => {
      pendingTargetRestore.resolve(jsonResponse(persistedTarget));
      await pendingTargetRestore.promise;
    });

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenNthCalledWith(
        4,
        "http://localhost:8000/api/history",
        { credentials: "include" },
      ),
    );
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-history-v1")),
        ).map((item: { job: JobRecord }) => item.job.original_filename),
      ).toEqual([
        "refreshed-history-sibling.png",
        "queued-full-restore-target.png",
      ]),
    );
    expect(window.sessionStorage.getItem("poker-training-history-synced")).toBe(
      "true",
    );
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/history",
      `http://localhost:8000/api/jobs/${targetJob.id}/approve`,
      `http://localhost:8000/api/jobs/${targetJob.id}`,
      "http://localhost:8000/api/history",
    ]);
  });

  it("revalidates the active history search after an archived hand changes", async () => {
    const archivedAt = "2026-07-10T00:02:00Z";
    const savedJob: JobRecord = {
      ...recommendedJob(),
      archived_at: archivedAt,
    };
    const reapprovedJob: JobRecord = {
      ...approvedJob(),
      archived_at: archivedAt,
      updated_at: "2026-07-10T00:03:00Z",
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: savedJob.id,
          job: savedJob,
          savedAt: archivedAt,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: 1,
          jobs: [savedJob],
          snapshot_version: "before-approval",
        }),
      )
      .mockResolvedValueOnce(jsonResponse(reapprovedJob))
      .mockResolvedValueOnce(
        jsonResponse({
          total: 0,
          jobs: [],
          snapshot_version: "after-approval",
        }),
      );
    render(<App />);
    const user = userEvent.setup();
    const historyPanel = screen.getByLabelText("Session history");

    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Search saved history",
      }),
    );
    await user.type(
      within(historyPanel).getByLabelText("History search query"),
      "raise",
    );
    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Run history search",
      }),
    );
    await user.click(
      await within(historyPanel).findByRole("button", {
        name: "Reopen history item 1",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Reset to parser" }));
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    expect(
      await within(historyPanel).findByText(
        "No saved hands match this search.",
      ),
    ).toBeInTheDocument();
    expect(within(historyPanel).getByText(/0 matches/)).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/api/history?query=raise&limit=24",
      { credentials: "include" },
    );
    const reviewedStat = within(screen.getByLabelText("Session status"))
      .getByText("reviewed")
      .closest(".toolbar-stat");
    expect(reviewedStat).not.toBeNull();
    expect(
      within(reviewedStat as HTMLElement).getByText("1"),
    ).toBeInTheDocument();
  });

  it("preserves loaded search pages when an archived hand changes", async () => {
    const savedJobs = Array.from(
      { length: 25 },
      (_, index): JobRecord => ({
        ...recommendedJob(),
        id: `searched-history-${index}`,
        original_filename: `searched-history-${index}.png`,
        archived_at: `2026-07-${String(25 - index).padStart(2, "0")}T00:00:00Z`,
      }),
    );
    const lastJob = savedJobs[24];
    const reapprovedLastJob: JobRecord = {
      ...approvedJob(),
      id: lastJob.id,
      original_filename: lastJob.original_filename,
      archived_at: lastJob.archived_at,
      updated_at: "2026-07-26T00:00:00Z",
    };
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: 25,
          jobs: savedJobs.slice(0, 24),
          snapshot_version: "before-approval",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 25,
          jobs: savedJobs.slice(24),
          snapshot_version: "before-approval",
        }),
      )
      .mockResolvedValueOnce(jsonResponse(reapprovedLastJob))
      .mockResolvedValueOnce(
        jsonResponse({
          total: 25,
          jobs: [...savedJobs.slice(0, 24), reapprovedLastJob],
          snapshot_version: "after-approval",
        }),
      );
    render(<App />);
    const user = userEvent.setup();
    const historyPanel = screen.getByLabelText("Session history");

    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Search saved history",
      }),
    );
    await user.type(
      within(historyPanel).getByLabelText("History search query"),
      "flop",
    );
    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Run history search",
      }),
    );
    await user.click(
      await within(historyPanel).findByRole("button", {
        name: "Load older history",
      }),
    );
    await user.click(
      await within(historyPanel).findByRole("button", {
        name: "Reopen history item 25",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Reset to parser" }));
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    const lastHistoryItem = await within(historyPanel).findByRole("button", {
      name: "Reopen history item 25",
    });
    expect(within(lastHistoryItem).getByText("approved")).toBeInTheDocument();
    expect(within(historyPanel).getByText(/25 matches/)).toBeInTheDocument();
    expect(
      within(historyPanel).queryByRole("button", {
        name: "Load older history",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock()).toHaveBeenNthCalledWith(
      4,
      "http://localhost:8000/api/history?query=flop&limit=25",
      { credentials: "include" },
    );
  });

  it("preserves loaded search pages when the matching total changes", async () => {
    const savedJobs = Array.from(
      { length: 50 },
      (_, index): JobRecord => ({
        ...recommendedJob(),
        id: `changing-search-history-${index}`,
        original_filename: `changing-search-history-${index}.png`,
        archived_at: `2026-07-25T00:${String(49 - index).padStart(2, "0")}:00Z`,
      }),
    );
    const newJob: JobRecord = {
      ...recommendedJob(),
      id: "new-search-history-job",
      original_filename: "new-search-history-job.png",
      archived_at: "2026-07-26T00:00:00Z",
    };
    const updatedJobs = [newJob, ...savedJobs];
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: 50,
          jobs: savedJobs.slice(0, 24),
          snapshot_version: "before-membership-change",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 50,
          jobs: savedJobs.slice(24, 48),
          snapshot_version: "before-membership-change",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 51,
          jobs: updatedJobs.slice(48),
          snapshot_version: "after-membership-change",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 51,
          jobs: updatedJobs,
          snapshot_version: "after-membership-change",
        }),
      );
    render(<App />);
    const user = userEvent.setup();
    const historyPanel = screen.getByLabelText("Session history");

    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Search saved history",
      }),
    );
    await user.type(
      within(historyPanel).getByLabelText("History search query"),
      "flop",
    );
    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Run history search",
      }),
    );
    await user.click(
      await within(historyPanel).findByRole("button", {
        name: "Load older history",
      }),
    );

    expect(
      await within(historyPanel).findByRole("button", {
        name: "Reopen history item 48",
      }),
    ).toBeInTheDocument();
    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Load older history",
      }),
    );

    expect(
      await within(historyPanel).findByRole("button", {
        name: "Reopen history item 51",
      }),
    ).toBeInTheDocument();
    expect(within(historyPanel).getByText(/51 matches/)).toBeInTheDocument();
    expect(
      within(historyPanel).queryByRole("button", {
        name: "Load older history",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock()).toHaveBeenNthCalledWith(
      4,
      "http://localhost:8000/api/history?query=flop&limit=51",
      { credentials: "include" },
    );
  });

  it("rebuilds loaded search pages when membership shifts at the same total", async () => {
    const savedJobs = Array.from(
      { length: 50 },
      (_, index): JobRecord => ({
        ...recommendedJob(),
        id: `stable-search-membership-${index}`,
        original_filename: `stable-search-membership-${index}.png`,
        archived_at: `2026-07-25T00:${String(49 - index).padStart(2, "0")}:00Z`,
      }),
    );
    const newMatch: JobRecord = {
      ...recommendedJob(
        canonicalState({
          hero_cards: [
            { rank: "Q", suit: "clubs" },
            { rank: "Q", suit: "hearts" },
          ],
        }),
      ),
      id: "new-search-membership",
      original_filename: "new-search-membership.png",
      archived_at: "2026-07-26T00:00:00Z",
    };
    const updatedJobs = [newMatch, ...savedJobs.slice(0, 49)];
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: 50,
          jobs: savedJobs.slice(0, 24),
          snapshot_version: "before-membership-change",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 50,
          jobs: updatedJobs.slice(24, 48),
          snapshot_version: "after-membership-change",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 50,
          jobs: updatedJobs.slice(0, 48),
          snapshot_version: "after-membership-change",
        }),
      );
    render(<App />);
    const user = userEvent.setup();
    const historyPanel = screen.getByLabelText("Session history");

    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Search saved history",
      }),
    );
    await user.type(
      within(historyPanel).getByLabelText("History search query"),
      "flop",
    );
    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Run history search",
      }),
    );
    await user.click(
      await within(historyPanel).findByRole("button", {
        name: "Load older history",
      }),
    );

    expect(await within(historyPanel).findByText("Q♣")).toBeInTheDocument();
    expect(
      within(historyPanel).getByRole("button", {
        name: "Reopen history item 48",
      }),
    ).toBeInTheDocument();
    expect(
      within(historyPanel).getByRole("button", {
        name: "Load older history",
      }),
    ).toHaveTextContent("Load 2 older");
    expect(fetchMock()).toHaveBeenCalledTimes(3);
    expect(fetchMock()).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/api/history?offset=24&query=flop",
      { credentials: "include" },
    );
    expect(fetchMock()).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/api/history?query=flop&limit=48",
      { credentials: "include" },
    );
  });

  it("clears a paged search when its changed snapshot has no matches", async () => {
    const savedJobs = Array.from(
      { length: 25 },
      (_, index): JobRecord => ({
        ...recommendedJob(),
        id: `removed-search-history-${index}`,
        original_filename: `removed-search-history-${index}.png`,
        archived_at: `2026-07-${String(25 - index).padStart(2, "0")}T00:00:00Z`,
      }),
    );
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: 25,
          jobs: savedJobs.slice(0, 24),
          snapshot_version: "before-removal",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 0,
          jobs: [],
          snapshot_version: "after-removal",
        }),
      );
    render(<App />);
    const user = userEvent.setup();
    const historyPanel = screen.getByLabelText("Session history");

    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Search saved history",
      }),
    );
    await user.type(
      within(historyPanel).getByLabelText("History search query"),
      "flop",
    );
    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Run history search",
      }),
    );
    await user.click(
      await within(historyPanel).findByRole("button", {
        name: "Load older history",
      }),
    );

    expect(
      await within(historyPanel).findByText(
        "No saved hands match this search.",
      ),
    ).toBeInTheDocument();
    expect(within(historyPanel).getByText(/0 matches/)).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(2);
    expect(fetchMock()).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/api/history?offset=24&query=flop",
      { credentials: "include" },
    );
  });

  it("restarts history pagination when the archived total changes between pages", async () => {
    window.localStorage.removeItem("poker-training-history-v1");
    window.sessionStorage.removeItem("poker-training-history-synced");
    const savedJobs = Array.from(
      { length: 31 },
      (_, index): JobRecord => ({
        ...recommendedJob(),
        id: `stable-history-${index}`,
        original_filename: `stable-history-${index}.png`,
        archived_at: `2026-07-${String(31 - index).padStart(2, "0")}T00:00:00Z`,
      }),
    );
    const newJob: JobRecord = {
      ...recommendedJob(),
      id: "new-history-job",
      original_filename: "new-history-job.png",
      archived_at: "2026-08-01T00:00:00Z",
    };
    const updatedJobs = [newJob, ...savedJobs];
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: 31,
          jobs: savedJobs.slice(0, 24),
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 32,
          jobs: updatedJobs.slice(24),
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 32,
          jobs: updatedJobs.slice(0, 24),
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 32,
          jobs: updatedJobs.slice(24),
        }),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("button", {
        name: "Load older history",
      }),
    );

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    expect(fetchMock()).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/api/history?offset=24",
      { credentials: "include" },
    );
    expect(fetchMock()).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/api/history",
      { credentials: "include" },
    );
    expect(
      screen.getByRole("button", {
        name: "Load older history",
      }),
    ).toHaveTextContent("Load 8 older");

    await user.click(
      screen.getByRole("button", {
        name: "Load older history",
      }),
    );

    expect(
      await screen.findByRole("button", {
        name: "Reopen history item 32",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Load older history",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock()).toHaveBeenNthCalledWith(
      4,
      "http://localhost:8000/api/history?offset=24",
      { credentials: "include" },
    );
  });

  it("reloads persisted history when local caching failed but session storage is available", async () => {
    window.localStorage.removeItem("poker-training-history-v1");
    window.sessionStorage.removeItem("poker-training-history-synced");
    const savedJob: JobRecord = {
      ...recommendedJob(),
      id: "quota-history-job",
      original_filename: "quota-history.png",
      archived_at: "2026-07-10T00:05:00Z",
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ total: 1, jobs: [savedJob] }))
      .mockResolvedValueOnce(jsonResponse({ total: 1, jobs: [savedJob] }));
    const originalSetItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function setItem(
      this: Storage,
      key: string,
      value: string,
    ) {
      if (this === window.localStorage) {
        throw new DOMException(
          "Local storage quota exceeded",
          "QuotaExceededError",
        );
      }
      originalSetItem.call(this, key, value);
    });

    const firstRender = render(<App />);
    expect(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    ).toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-history-synced"),
    ).toBeNull();
    firstRender.unmount();

    render(<App />);

    expect(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    ).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["missing", null],
    ["unreadable", "{not-json"],
  ])(
    "reloads persisted history when the local cache is %s",
    async (_label, cachedValue) => {
      if (cachedValue === null) {
        window.localStorage.removeItem("poker-training-history-v1");
      } else {
        window.localStorage.setItem("poker-training-history-v1", cachedValue);
      }
      window.localStorage.setItem("poker-training-history-total-v1", "1");
      window.sessionStorage.setItem("poker-training-history-synced", "true");
      const savedJob: JobRecord = {
        ...recommendedJob(),
        id: "recovered-history-job",
        original_filename: "recovered-history.png",
        archived_at: "2026-07-10T00:06:00Z",
      };
      fetchMock().mockResolvedValueOnce(
        jsonResponse({
          total: 1,
          jobs: [savedJob],
        }),
      );

      render(<App />);

      expect(
        await screen.findByRole("button", {
          name: "Reopen history item 1",
        }),
      ).toBeInTheDocument();
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/history",
        { credentials: "include" },
      );
    },
  );

  it("refreshes saved history from the backend", async () => {
    const savedJob: JobRecord = {
      ...recommendedJob(),
      id: "refreshed-history-job",
      original_filename: "refreshed.png",
      archived_at: "2026-07-10T00:03:00Z",
    };
    fetchMock().mockResolvedValueOnce(
      jsonResponse({
        total: 1,
        jobs: [savedJob],
      }),
    );
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Refresh saved history" }),
    );

    expect(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    ).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledWith(
      "http://localhost:8000/api/history",
      { credentials: "include" },
    );
  });

  it("migrates legacy local history into persisted history", async () => {
    const jobId = "a".repeat(32);
    const legacyJob: JobRecord = {
      ...recommendedJob(),
      id: jobId,
      original_filename: "legacy.png",
      archived_at: null,
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: jobId,
          job: legacyJob,
          savedAt: "2026-07-10T00:00:00Z",
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-history-synced");
    window.localStorage.removeItem("poker-training-processing-v1");
    window.localStorage.removeItem("poker-training-processing-total-v1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    const pendingMigration = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingMigration.promise)
      .mockResolvedValueOnce(
        jsonResponse({
          total: 0,
          jobs: [],
          snapshot_version: "post-migration-processing",
        }),
      );

    render(<App />);

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/history",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ job_ids: [jobId] }),
        }),
      ),
    );
    expect(fetchMock()).toHaveBeenCalledTimes(1);
    pendingMigration.resolve(
      jsonResponse({
        total: 1,
        jobs: [
          {
            ...legacyJob,
            archived_at: "2026-07-10T00:04:00Z",
          },
        ],
      }),
    );

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenNthCalledWith(
        2,
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
      ),
    );
    expect(
      screen.getByRole("button", {
        name: "Reopen history item 1",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: legacy.png",
      }),
    ).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem("poker-training-history-synced")).toBe(
      "true",
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
  });

  it("releases legacy archive leases after deterministic migration rejection", async () => {
    const jobId = "b".repeat(32);
    const legacyJob: JobRecord = {
      ...recommendedJob(),
      id: jobId,
      original_filename: "legacy-conflict.png",
      archived_at: null,
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: jobId,
          job: legacyJob,
          savedAt: "2026-07-10T00:00:00Z",
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-history-synced");
    fetchMock().mockResolvedValueOnce(
      jsonResponse(
        {
          detail:
            "Only successful approved or recommended jobs can be moved to history",
        },
        409,
      ),
    );

    render(<App />);

    expect(
      await screen.findByText(
        "Could not migrate legacy history before restoring processing",
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ).toBeNull(),
    );
    expect(
      window.sessionStorage.getItem("poker-training-history-mutation-v1"),
    ).toBeNull();
    expect(fetchMock()).toHaveBeenCalledTimes(1);
  });
});
