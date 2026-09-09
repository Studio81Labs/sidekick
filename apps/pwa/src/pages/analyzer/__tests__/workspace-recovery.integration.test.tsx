import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DetectedState } from "../../../shared/types/poker";
import type { JobRecord } from "../../../shared/types/jobs";
import type { AnalyzerRouteNavigation } from "../analyzerRouteState";
import {
  AnalyzerTestApp as App,
  VerifiedAnalyzerPage,
  approvedJob,
  benchmarkOverviewForJob,
  canonicalState,
  deferredResponse,
  detectedState,
  unlockAdministrativeAccess,
  fetchMock,
  jobRecord,
  jsonResponse,
  processingQueueResponse,
  switchToUploadMode,
} from "../../../test/analyzerHarness";

describe("Analyzer workspace recovery", () => {
  it("restores structured preflop history from the browser cache", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 12,
      current_bet: 5.5,
      hero_stack: 97.5,
      effective_stack: 92,
      players_in_hand: 2,
      hero_position: "cutoff",
      preflop_opener_position: "cutoff",
      preflop_open_size: 2.5,
      preflop_action_history: [
        { actor: "cutoff", action: "raise", amount: 2.5 },
        { actor: "button", action: "raise", amount: 8 },
      ],
      street: "preflop",
      facing_action: "raise",
      action_context: "Hero faces a 3-bet",
    };
    const cachedJob = jobRecord({
      id: "b".repeat(32),
      original_filename: "cached-three-bet.png",
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([cachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");

    render(<App />);

    expect(await screen.findByLabelText("Preflop action 1 actor")).toHaveValue(
      "cutoff",
    );
    expect(screen.getByLabelText("Preflop action 2 actor")).toHaveValue(
      "button",
    );
    expect(screen.getByLabelText("Preflop action 2 amount")).toHaveValue("8");
    expect(fetchMock()).not.toHaveBeenCalled();
  });

  it("does not overwrite a newer processing cache record from another tab", async () => {
    const jobId = "1".repeat(32);
    const staleJob = jobRecord({
      id: jobId,
      original_filename: "shared-cache.png",
    });
    const newerJob = {
      ...staleJob,
      status: "approved" as const,
      approved_state: canonicalState({ pot_size: 20 }),
      updated_at: "2026-07-10T00:01:00Z",
    };
    const archivedJob = jobRecord({
      id: "2".repeat(32),
      original_filename: "history-trigger.png",
      archived_at: "2026-07-10T00:02:00Z",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([staleJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: archivedJob.id,
          job: archivedJob,
          savedAt: archivedJob.archived_at,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([newerJob]),
    );
    await user.click(
      screen.getByRole("button", {
        name: "Reopen history item 1",
      }),
    );

    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([newerJob]),
    );
    expect(fetchMock()).not.toHaveBeenCalled();
  });

  it("preserves a dirty archived workspace during processing reconciliation", async () => {
    const processingJob = jobRecord({
      id: "3".repeat(32),
      original_filename: "processing-sibling.png",
    });
    const archivedJob = jobRecord({
      id: "4".repeat(32),
      original_filename: "archived-workspace.png",
      archived_at: "2026-07-10T00:02:00Z",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([processingJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: archivedJob.id,
          job: archivedJob,
          savedAt: archivedJob.archived_at,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    fetchMock().mockResolvedValueOnce(
      processingQueueResponse(
        [processingJob],
        "processing-refresh-with-archived-workspace",
      ),
    );
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", {
        name: "Reopen history item 1",
      }),
    );
    const heroCards = screen.getByLabelText(/Hero cards/);
    await user.clear(heroCards);
    await user.type(heroCards, "7d Ah");
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "poker-training-processing-v1",
        oldValue: "[]",
        newValue: JSON.stringify([processingJob]),
        storageArea: window.localStorage,
      }),
    );

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/jobs",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    expect(await screen.findByDisplayValue("7d Ah")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 2: archived-workspace.png",
      }),
    ).toHaveClass("active");
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([processingJob]);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
  });

  it("preserves a pristine benchmark workspace omitted from processing", async () => {
    const processingJob = jobRecord({
      id: "5".repeat(32),
      original_filename: "benchmark-processing-sibling.png",
    });
    const benchmarkJobId = "6".repeat(32);
    const pristineBenchmark = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "pristine-benchmark-workspace.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: true,
      parser_result: null,
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([processingJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse(
          benchmarkOverviewForJob(
            benchmarkJobId,
            pristineBenchmark.original_filename,
          ),
        ),
      )
      .mockResolvedValueOnce(jsonResponse(pristineBenchmark))
      .mockResolvedValueOnce(
        processingQueueResponse(
          [processingJob],
          "processing-with-omitted-pristine-workspace",
        ),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: `Toggle ${pristineBenchmark.original_filename} benchmark details`,
      }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Review hand" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Parser benchmark" }),
      ).not.toBeInTheDocument(),
    );

    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "poker-training-processing-v1",
        oldValue: "[]",
        newValue: JSON.stringify([processingJob]),
        storageArea: window.localStorage,
      }),
    );

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/jobs",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 2: pristine-benchmark-workspace.png",
      }),
    ).toHaveClass("active");
    expect(screen.getByDisplayValue("Ah Kd")).toBeInTheDocument();
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([processingJob]);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
  });

  it("does not duplicate a pristine benchmark workspace returned by processing", async () => {
    const processingJob = jobRecord({
      id: "7".repeat(32),
      original_filename: "benchmark-return-sibling.png",
    });
    const benchmarkJobId = "8".repeat(32);
    const pristineBenchmark = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "returning-benchmark-workspace.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: true,
      parser_result: null,
    };
    const promotedBenchmark: JobRecord = {
      ...pristineBenchmark,
      error: "Imported labels need review",
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([processingJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse(
          benchmarkOverviewForJob(
            benchmarkJobId,
            pristineBenchmark.original_filename,
          ),
        ),
      )
      .mockResolvedValueOnce(jsonResponse(pristineBenchmark))
      .mockResolvedValueOnce(
        processingQueueResponse(
          [processingJob, promotedBenchmark],
          "processing-with-promoted-benchmark",
        ),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: `Toggle ${pristineBenchmark.original_filename} benchmark details`,
      }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Review hand" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Parser benchmark" }),
      ).not.toBeInTheDocument(),
    );

    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "poker-training-processing-v1",
        oldValue: "[]",
        newValue: JSON.stringify([processingJob, promotedBenchmark]),
        storageArea: window.localStorage,
      }),
    );

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/jobs",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    expect(
      await screen.findAllByRole("button", {
        name: /Open screenshot \d+: returning-benchmark-workspace\.png/,
      }),
    ).toHaveLength(1);
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 2: returning-benchmark-workspace.png",
      }),
    ).toHaveClass("active");
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([processingJob, promotedBenchmark]);
  });

  it("reconciles processing when another tab changes the shared cache", async () => {
    const jobId = "3".repeat(32);
    const staleJob = jobRecord({
      id: jobId,
      original_filename: "cross-tab-update.png",
    });
    const newerJob = {
      ...staleJob,
      status: "approved" as const,
      approved_state: canonicalState({ pot_size: 20 }),
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([staleJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockResolvedValueOnce(
      processingQueueResponse([newerJob], "cross-tab-update-snapshot"),
    );
    render(<App />);

    const serializedNewerJob = JSON.stringify([newerJob]);
    window.localStorage.setItem(
      "poker-training-processing-v1",
      serializedNewerJob,
    );
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "poker-training-processing-v1",
        oldValue: JSON.stringify([staleJob]),
        newValue: serializedNewerJob,
        storageArea: window.localStorage,
      }),
    );

    expect(await screen.findByDisplayValue("20")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();
    expect(fetchMock()).toHaveBeenCalledTimes(1);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
  });

  it("does not replace a newer analyzer surface after delayed processing recovery", async () => {
    const removedJob = jobRecord({
      id: "9".repeat(32),
      original_filename: "removed-during-route-change.png",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([removedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    const pendingQueue = deferredResponse();
    fetchMock().mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith(`/api/admin/ocr/jobs/${removedJob.id}`)) {
        return Promise.resolve(jsonResponse(removedJob));
      }
      if (url.endsWith("/api/admin/ocr/jobs")) {
        return pendingQueue.promise;
      }
      return Promise.resolve(
        jsonResponse(
          benchmarkOverviewForJob(removedJob.id, removedJob.original_filename),
        ),
      );
    });
    const navigation: AnalyzerRouteNavigation = {
      closeSurface: vi.fn(),
      managed: true,
      openBenchmarks: vi.fn(),
      openJob: vi.fn(),
      openWorkspace: vi.fn(),
    };
    const view = render(
      <App>
        <VerifiedAnalyzerPage
          navigation={navigation}
          route={{ jobId: removedJob.id, surface: "job" }}
        />
      </App>,
    );

    expect(await screen.findByDisplayValue("Ah Kd")).toBeInTheDocument();
    view.rerender(
      <App>
        <VerifiedAnalyzerPage
          navigation={navigation}
          route={{ jobId: null, surface: "benchmarks" }}
        />
      </App>,
    );
    expect(
      await screen.findByRole("dialog", { name: "Parser benchmark" }),
    ).toBeInTheDocument();

    await act(async () => {
      pendingQueue.resolve(processingQueueResponse([], "removed-job"));
      await pendingQueue.promise;
    });
    await waitFor(() => expect(fetchMock()).toHaveBeenCalled());
    expect(navigation.openJob).not.toHaveBeenCalled();
    expect(navigation.openWorkspace).not.toHaveBeenCalled();
  });

  it("suspends a stale hand while an uncached job route loads", async () => {
    const cachedJob = jobRecord({
      id: "a".repeat(32),
      original_filename: "cached-route-hand.png",
    });
    const requestedJob = jobRecord({
      id: "b".repeat(32),
      original_filename: "requested-route-hand.png",
      parser_result: {
        ...jobRecord().parser_result!,
        state: {
          ...detectedState,
          hero_cards: [
            { rank: "7", suit: "clubs" },
            { rank: "6", suit: "diamonds" },
          ],
        },
      },
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([cachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    const pendingJob = deferredResponse();
    const pendingQueue = deferredResponse();
    fetchMock().mockImplementation((input) =>
      String(input).endsWith("/api/admin/ocr/jobs")
        ? pendingQueue.promise
        : pendingJob.promise,
    );
    const navigation: AnalyzerRouteNavigation = {
      closeSurface: vi.fn(),
      managed: true,
      openBenchmarks: vi.fn(),
      openJob: vi.fn(),
      openWorkspace: vi.fn(),
    };
    const view = render(
      <App>
        <VerifiedAnalyzerPage
          navigation={navigation}
          route={{ jobId: cachedJob.id, surface: "job" }}
        />
      </App>,
    );
    expect(await screen.findByDisplayValue("Ah Kd")).toBeInTheDocument();

    view.rerender(
      <App>
        <VerifiedAnalyzerPage
          navigation={navigation}
          route={{ jobId: requestedJob.id, surface: "job" }}
        />
      </App>,
    );
    await waitFor(() =>
      expect(screen.queryByDisplayValue("Ah Kd")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();

    await act(async () => {
      pendingQueue.resolve(
        processingQueueResponse([cachedJob], "pending-route-queue"),
      );
      await pendingQueue.promise;
    });
    expect(screen.queryByDisplayValue("Ah Kd")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();
    expect(navigation.openJob).not.toHaveBeenCalled();
    expect(navigation.openWorkspace).not.toHaveBeenCalled();

    await act(async () => {
      pendingJob.resolve(jsonResponse(requestedJob));
      await pendingJob.promise;
    });
    expect(await screen.findByDisplayValue("7c 6d")).toBeInTheDocument();
  });

  it("preserves dirty processing jobs removed by another tab", async () => {
    const removedJob = jobRecord({
      id: "0".repeat(32),
      original_filename: "archived-in-another-tab.png",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([removedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockResolvedValueOnce(
      processingQueueResponse([], "cross-tab-removal"),
    );
    render(<App />);
    const user = userEvent.setup();

    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 1: archived-in-another-tab.png",
      }),
    ).toBeInTheDocument();
    const heroCards = screen.getByLabelText(/Hero cards/);
    await user.clear(heroCards);
    await user.type(heroCards, "7d Ah");
    window.localStorage.setItem("poker-training-processing-v1", "[]");
    window.localStorage.setItem("poker-training-processing-total-v1", "0");
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "poker-training-processing-v1",
        oldValue: JSON.stringify([removedJob]),
        newValue: "[]",
        storageArea: window.localStorage,
      }),
    );

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 1: archived-in-another-tab.png",
      }),
    ).toHaveClass("active");
    expect(heroCards).toHaveValue("7d Ah");
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([removedJob]);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/admin/ocr/jobs",
    ]);
  });

  it("polls a parser job that was still running during reload", async () => {
    const jobId = "5".repeat(32);
    const createdJob = jobRecord({
      id: jobId,
      status: "created",
      original_filename: "parser-still-running.png",
      parser_result: null,
      updated_at: "2026-07-10T00:01:00Z",
    });
    const parsedJob = jobRecord({
      id: jobId,
      original_filename: "parser-still-running.png",
      updated_at: "2026-07-10T00:02:00Z",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([createdJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        processingQueueResponse([createdJob], "parser-still-running"),
      )
      .mockResolvedValueOnce(
        processingQueueResponse([parsedJob], "parser-completed"),
      );

    render(<App />);

    const queueItem = await screen.findByRole("button", {
      name: "Open screenshot 1: parser-still-running.png",
    });
    expect(
      within(queueItem).getByText("Parsing screenshot"),
    ).toBeInTheDocument();
    expect(await screen.findByDisplayValue("Ah Kd")).toBeInTheDocument();
    expect(
      within(queueItem).queryByText("Parsing screenshot"),
    ).not.toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(2);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([parsedJob]);
  });

  it("prefers terminal processing state over a slightly newer pending cache", async () => {
    const jobId = "9".repeat(32);
    const serverUpdatedAt = Date.now();
    const poisonedPendingJob = {
      ...jobRecord(),
      id: jobId,
      original_filename: "future-pending.png",
      status: "created" as const,
      parser_result: null,
      updated_at: new Date(serverUpdatedAt + 60_000).toISOString(),
    };
    const completedJob = {
      ...approvedJob(),
      id: jobId,
      original_filename: "future-pending.png",
      updated_at: new Date(serverUpdatedAt).toISOString(),
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([poisonedPendingJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockResolvedValueOnce(
      processingQueueResponse([completedJob], "future-pending-recovered"),
    );

    render(<App />);

    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([completedJob]),
    );
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 1: future-pending.png",
      }),
    ).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(1);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
  });

  it("lets authoritative processing state replace a future-dated ordinary cache", async () => {
    const jobId = "7".repeat(32);
    const futureCachedJob = jobRecord({
      id: jobId,
      original_filename: "future-ordinary.png",
      updated_at: "9999-01-01T00:00:00Z",
    });
    const approvedServerJob: JobRecord = {
      ...futureCachedJob,
      status: "approved",
      approved_state: canonicalState({ pot_size: 20 }),
      updated_at: "2026-07-10T00:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([futureCachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    fetchMock().mockResolvedValueOnce(
      processingQueueResponse([approvedServerJob], "future-ordinary-recovered"),
    );

    render(<App />);

    expect(await screen.findByDisplayValue("20")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();
    expect(fetchMock()).toHaveBeenCalledTimes(1);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([approvedServerJob]);
  });

  it("retries a failed authoritative restore for an ordinary cached job", async () => {
    const jobId = "6".repeat(32);
    const cachedJob = jobRecord({
      id: jobId,
      original_filename: "ordinary-restore-retry.png",
      updated_at: "2026-07-10T00:01:00Z",
    });
    const persistedJob: JobRecord = {
      ...cachedJob,
      status: "approved",
      approved_state: canonicalState({ pot_size: 20 }),
      updated_at: "2026-07-10T00:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([cachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    fetchMock()
      .mockRejectedValueOnce(new TypeError("Temporary queue restore failure"))
      .mockResolvedValueOnce(
        processingQueueResponse([persistedJob], "ordinary-restore-recovered"),
      );

    render(<App />);

    expect(await screen.findByDisplayValue("20")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();
    expect(fetchMock()).toHaveBeenCalledTimes(2);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([persistedJob]);
  });

  it("keeps unfinished benchmark imports in the cached processing queue", async () => {
    const failedImport = {
      ...approvedJob(),
      id: "e".repeat(32),
      status: "error" as const,
      original_filename: "failed-import.png",
      parser_result: null,
      benchmark_included: true,
      error: "provider exploded",
    };
    const pristineImport = {
      ...approvedJob(),
      id: "f".repeat(32),
      original_filename: "pristine-import.png",
      parser_result: null,
      benchmark_included: true,
    };
    const unapprovedImport = {
      ...jobRecord(),
      id: "a".repeat(32),
      original_filename: "unapproved-import.png",
      parser_result: null,
      benchmark_included: true,
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([failedImport, pristineImport, unapprovedImport]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "2");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    const pendingQueue = deferredResponse();
    fetchMock().mockReturnValueOnce(pendingQueue.promise);

    render(<App />);

    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 1: failed-import.png",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 2: unapproved-import.png",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /pristine-import\.png/,
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledWith(
      "http://localhost:8000/api/admin/ocr/jobs",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("reconciles malformed processing cache entries from the backend", async () => {
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([{ id: "c".repeat(32) }]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockResolvedValueOnce(
      jsonResponse({
        total: 0,
        jobs: [],
        snapshot_version: "empty-processing-snapshot",
      }),
    );

    render(<App />);

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/jobs",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    await waitFor(() =>
      expect(
        window.localStorage.getItem("poker-training-processing-total-v1"),
      ).toBe("0"),
    );
    expect(
      screen.queryByRole("button", {
        name: /Open screenshot/,
      }),
    ).not.toBeInTheDocument();
    expect(window.localStorage.getItem("poker-training-processing-v1")).toBe(
      "[]",
    );
  });

  it("rejects a cached processing job without an explicit archive state", async () => {
    const cachedJob = jobRecord({
      id: "7".repeat(32),
      original_filename: "missing-archive-state.png",
    });
    const { archived_at: _archivedAt, ...jobWithoutArchiveState } = cachedJob;
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([jobWithoutArchiveState]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockResolvedValueOnce(
      processingQueueResponse([], "missing-archive-state-reconciled"),
    );

    render(<App />);

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/jobs",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    expect(
      screen.queryByRole("button", {
        name: /missing-archive-state\.png/,
      }),
    ).not.toBeInTheDocument();
    expect(window.localStorage.getItem("poker-training-processing-v1")).toBe(
      "[]",
    );
    expect(
      window.localStorage.getItem("poker-training-processing-total-v1"),
    ).toBe("0");
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
  });

  it.each([
    {
      label: "missing",
      malformedJob: (() => {
        const { benchmark_included: _benchmarkIncluded, ...jobWithoutFlag } = {
          ...approvedJob(),
          id: "9".repeat(32),
          original_filename: "missing-benchmark-flag.png",
          parser_result: null,
          benchmark_included: true,
        };
        return jobWithoutFlag;
      })(),
    },
    {
      label: "non-boolean",
      malformedJob: {
        ...approvedJob(),
        id: "8".repeat(32),
        original_filename: "invalid-benchmark-flag.png",
        parser_result: null,
        benchmark_included: "true",
      },
    },
  ])(
    "rejects a $label cached benchmark flag and restores the backend projection",
    async ({ malformedJob }) => {
      window.localStorage.setItem(
        "poker-training-processing-v1",
        JSON.stringify([malformedJob]),
      );
      window.localStorage.setItem("poker-training-processing-total-v1", "1");
      fetchMock().mockResolvedValueOnce(
        processingQueueResponse([], "benchmark-filtered-snapshot"),
      );

      render(<App />);

      await waitFor(() =>
        expect(fetchMock()).toHaveBeenCalledWith(
          "http://localhost:8000/api/admin/ocr/jobs",
          expect.objectContaining({ credentials: "include" }),
        ),
      );
      expect(
        screen.queryByRole("button", {
          name: /benchmark-flag\.png/,
        }),
      ).not.toBeInTheDocument();
      await waitFor(() =>
        expect(
          window.localStorage.getItem("poker-training-processing-v1"),
        ).toBe("[]"),
      );
    },
  );

  it("rejects malformed cached cards and restores the backend record", async () => {
    const persistedJob = jobRecord({
      id: "c".repeat(32),
      original_filename: "restored-valid-table.png",
    });
    const malformedJob = {
      ...persistedJob,
      parser_result: {
        ...persistedJob.parser_result,
        state: {
          ...persistedJob.parser_result?.state,
          hero_cards: [null],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([malformedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockResolvedValueOnce(
      jsonResponse({
        total: 1,
        jobs: [persistedJob],
        snapshot_version: "valid-processing-snapshot",
      }),
    );

    render(<App />);

    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 1: restored-valid-table.png",
      }),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("Ah Kd")).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledWith(
      "http://localhost:8000/api/admin/ocr/jobs",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      )[0].parser_result.state.hero_cards,
    ).toEqual(detectedState.hero_cards);
  });

  it("rejects malformed cached errors and restores the backend record", async () => {
    const persistedJob = jobRecord({
      id: "f".repeat(32),
      original_filename: "restored-error-state.png",
    });
    const malformedJob = {
      ...persistedJob,
      status: "error",
      error: {},
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([malformedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockResolvedValueOnce(
      jsonResponse({
        total: 1,
        jobs: [persistedJob],
        snapshot_version: "valid-error-snapshot",
      }),
    );

    render(<App />);

    const restoredItem = await screen.findByRole("button", {
      name: "Open screenshot 1: restored-error-state.png",
    });
    expect(within(restoredItem).getByText("parsed")).toBeInTheDocument();
    expect(within(restoredItem).getByText("flop")).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledWith(
      "http://localhost:8000/api/admin/ocr/jobs",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("keeps unsaved form edits out of the processing cache", async () => {
    const persistedJob = {
      ...approvedJob(),
      id: "e".repeat(32),
      original_filename: "confirmed-approval.png",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([persistedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    const firstRender = render(<App />);
    const user = userEvent.setup();

    const potInput = await screen.findByLabelText(/Pot/);
    await user.clear(potInput);
    await user.type(potInput, "18");

    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      )[0],
    ).toMatchObject({
      status: "approved",
      approved_state: persistedJob.approved_state,
    });

    firstRender.unmount();
    render(<App />);

    expect(await screen.findByLabelText(/Pot/)).toHaveValue("12.5");
    expect(fetchMock()).not.toHaveBeenCalled();
  });

  it("restores persisted processing jobs when the browser cache is unavailable", async () => {
    const persistedJob = jobRecord({
      id: "b".repeat(32),
      original_filename: "persisted-table.png",
    });
    window.localStorage.removeItem("poker-training-processing-v1");
    window.localStorage.removeItem("poker-training-processing-total-v1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    fetchMock().mockResolvedValueOnce(
      jsonResponse({
        total: 1,
        jobs: [persistedJob],
        snapshot_version: "processing-snapshot",
      }),
    );

    render(<App />);

    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 1: persisted-table.png",
      }),
    ).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledWith(
      "http://localhost:8000/api/admin/ocr/jobs",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toHaveLength(1);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
  });

  it("realigns an untouched cached form with the reconciled active job", async () => {
    const cachedJob = jobRecord({
      id: "d".repeat(32),
      original_filename: "reconciled-table.png",
    });
    const reconciledState: DetectedState = {
      ...detectedState,
      hero_cards: [
        { rank: "Q", suit: "clubs" },
        { rank: "Q", suit: "hearts" },
      ],
    };
    const reconciledJob = jobRecord({
      ...cachedJob,
      parser_result: {
        ...cachedJob.parser_result!,
        state: reconciledState,
      },
      updated_at: "2026-07-10T00:01:00Z",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([cachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    const pendingQueue = deferredResponse();
    fetchMock().mockReturnValueOnce(pendingQueue.promise);

    render(<App />);

    expect(await screen.findByDisplayValue("Ah Kd")).toBeInTheDocument();
    pendingQueue.resolve(
      jsonResponse({
        total: 1,
        jobs: [reconciledJob],
        snapshot_version: "reconciled-snapshot",
      }),
    );

    expect(await screen.findByDisplayValue("Qc Qh")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Ah Kd")).not.toBeInTheDocument();
  });

  it("keeps an approval that completes while queue restoration is pending", async () => {
    const cachedJob = jobRecord({
      id: "a".repeat(32),
      original_filename: "approval-race.png",
    });
    const approved = {
      ...cachedJob,
      status: "approved" as const,
      approved_state: canonicalState(),
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([cachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    const pendingQueue = deferredResponse();
    const pendingApproval = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingQueue.promise)
      .mockReturnValueOnce(pendingApproval.promise)
      .mockResolvedValueOnce(
        processingQueueResponse([approved], "approved-after-stale-restore"),
      );
    render(<App />);

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/jobs",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    screen.getByRole("button", { name: "Approve state" }).click();
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenNthCalledWith(
        2,
        `http://localhost:8000/api/admin/ocr/jobs/${cachedJob.id}/approve`,
        expect.objectContaining({ method: "POST" }),
      ),
    );

    await act(async () => {
      pendingApproval.resolve(jsonResponse(approved));
      await pendingApproval.promise;
      await Promise.resolve();
      await Promise.resolve();
      pendingQueue.resolve(
        jsonResponse({
          total: 1,
          jobs: [cachedJob],
          snapshot_version: "stale-processing-snapshot",
        }),
      );
      await pendingQueue.promise;
    });

    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        )[0].status,
      ).toBe("approved"),
    );
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();
    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-synced"),
      ).toBe("true"),
    );
    expect(fetchMock()).toHaveBeenCalledTimes(3);
  });

  it("reloads backend state when an older restore finishes during an ordinary approval request", async () => {
    const jobId = "b".repeat(32);
    const initialJob = jobRecord({
      id: jobId,
      original_filename: "pending-approval.png",
    });
    const persistedJob: JobRecord = {
      ...initialJob,
      status: "approved",
      approved_state: canonicalState(),
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([initialJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    const pendingRestore = deferredResponse();
    const pendingMutation = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingRestore.promise)
      .mockReturnValueOnce(pendingMutation.promise)
      .mockResolvedValueOnce(
        processingQueueResponse([persistedJob], "pending-approval-snapshot"),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/jobs",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/admin/ocr/jobs/${jobId}/approve`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await act(async () => {
      pendingRestore.resolve(
        processingQueueResponse([initialJob], "stale-approval-snapshot"),
      );
      await pendingRestore.promise;
    });
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();
    expect(fetchMock()).toHaveBeenCalledTimes(2);

    firstRender.unmount();
    render(<App />);

    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([persistedJob]),
    );
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/admin/ocr/jobs",
      `http://localhost:8000/api/admin/ocr/jobs/${jobId}/approve`,
      "http://localhost:8000/api/admin/ocr/jobs",
    ]);
  });

  it("reloads archived approval state when an older history restore finishes during the request", async () => {
    const jobId = "f".repeat(32);
    const archivedAt = "2026-07-20T12:00:00Z";
    const initialJob = jobRecord({
      id: jobId,
      original_filename: "archived-pending-approval.png",
      archived_at: archivedAt,
    });
    const persistedJob: JobRecord = {
      ...initialJob,
      status: "approved",
      approved_state: canonicalState(),
      updated_at: "2026-07-20T12:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: jobId,
          job: initialJob,
          savedAt: archivedAt,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-history-synced");
    const pendingHistoryRestore = deferredResponse();
    const pendingMutation = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingHistoryRestore.promise)
      .mockReturnValueOnce(pendingMutation.promise)
      .mockResolvedValueOnce(
        processingQueueResponse([persistedJob], "archived-approval-completed"),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/history",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    await user.click(
      screen.getByRole("button", {
        name: "Reopen history item 1",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/admin/ocr/jobs/${jobId}/approve`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await act(async () => {
      pendingHistoryRestore.resolve(
        processingQueueResponse([initialJob], "stale-archived-approval"),
      );
      await pendingHistoryRestore.promise;
    });
    expect(
      window.sessionStorage.getItem("poker-training-history-synced"),
    ).toBeNull();
    expect(fetchMock()).toHaveBeenCalledTimes(2);

    firstRender.unmount();
    render(<App />);

    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-history-v1")),
        )[0].job,
      ).toEqual(persistedJob),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    );
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/admin/ocr/history",
      `http://localhost:8000/api/admin/ocr/jobs/${jobId}/approve`,
      "http://localhost:8000/api/admin/ocr/history",
    ]);
  });

  it("keeps processing unsynced when a reload races an ordinary write", async () => {
    const jobId = "4".repeat(32);
    const initialJob = jobRecord({
      id: jobId,
      original_filename: "reload-spanning-approval.png",
    });
    const persistedJob: JobRecord = {
      ...initialJob,
      status: "approved",
      approved_state: canonicalState(),
      updated_at: "2026-07-20T12:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([initialJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    const pendingMutation = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingMutation.promise)
      .mockResolvedValueOnce(
        processingQueueResponse([initialJob], "pre-commit-processing-snapshot"),
      )
      .mockResolvedValueOnce(
        processingQueueResponse(
          [persistedJob],
          "post-commit-processing-snapshot",
        ),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Approve state" }));
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/admin/ocr/jobs/${jobId}/approve`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
    firstRender.unmount();
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).not.toBeNull();
    render(<App />);
    await act(async () => {
      pendingMutation.resolve(jsonResponse(persistedJob));
      await pendingMutation.promise;
    });

    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([persistedJob]),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      `http://localhost:8000/api/admin/ocr/jobs/${jobId}/approve`,
      "http://localhost:8000/api/admin/ocr/jobs",
      "http://localhost:8000/api/admin/ocr/jobs",
    ]);
  });

  it("does not settle an approval lease from an unrelated cross-tab revision", async () => {
    const jobId = "7".repeat(32);
    const initialJob = {
      ...approvedJob(),
      id: jobId,
      original_filename: "cross-tab-approval.png",
    };
    const interveningJob: JobRecord = {
      ...initialJob,
      approved_state: canonicalState({ pot_size: 15 }),
      updated_at: "2026-07-20T12:01:00Z",
    };
    const correctedState = canonicalState({ pot_size: 20 });
    const persistedApproval: JobRecord = {
      ...interveningJob,
      status: "approved",
      approved_state: correctedState,
      updated_at: "2026-07-20T12:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([initialJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    const pendingApproval = deferredResponse();
    const pendingFinalQueue = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingApproval.promise)
      .mockResolvedValueOnce(
        processingQueueResponse(
          [interveningJob],
          "intervening-revision-snapshot",
        ),
      )
      .mockReturnValueOnce(pendingFinalQueue.promise);
    const firstRender = render(<App />);
    const user = userEvent.setup();

    const potInput = await screen.findByDisplayValue("12.5");
    await user.clear(potInput);
    await user.type(potInput, "20");
    await user.click(screen.getByRole("button", { name: "Approve state" }));
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/admin/ocr/jobs/${jobId}/approve`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
    firstRender.unmount();
    render(<App />);

    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([interveningJob]),
    );
    expect(
      JSON.parse(
        String(
          window.sessionStorage.getItem(
            "poker-training-processing-mutation-v1",
          ),
        ),
      ),
    ).toEqual(
      expect.objectContaining({
        kind: "job",
        jobId,
        expectedMutation: {
          kind: "approval",
          approvedStateKey: expect.any(String),
        },
      }),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    await act(async () => {
      pendingApproval.resolve(jsonResponse(persistedApproval));
      await pendingApproval.promise;
      pendingFinalQueue.resolve(
        processingQueueResponse(
          [persistedApproval],
          "persisted-approval-snapshot",
        ),
      );
      await pendingFinalQueue.promise;
    });

    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([persistedApproval]),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
  });

  it("does not settle a benchmark lease from an unrelated cross-tab revision", async () => {
    const jobId = "8".repeat(32);
    const initialJob = {
      ...approvedJob(),
      id: jobId,
      original_filename: "cross-tab-benchmark.png",
    };
    const interveningJob: JobRecord = {
      ...initialJob,
      title: "Cross-tab rename",
      updated_at: "2026-07-20T12:01:00Z",
    };
    const persistedInclusion: JobRecord = {
      ...interveningJob,
      benchmark_included: true,
      updated_at: "2026-07-20T12:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([initialJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.setItem(
      "poker-training-processing-mutation-v1",
      JSON.stringify({
        kind: "job",
        ownerId: "previous-page",
        jobId,
        baselineUpdatedAt: initialJob.updated_at,
        expectsRemoval: false,
        expectedMutation: {
          kind: "benchmark-inclusion",
          included: true,
        },
        expiresAt: Date.now() + 30_000,
      }),
    );
    fetchMock()
      .mockResolvedValueOnce(
        processingQueueResponse(
          [interveningJob],
          "intervening-revision-snapshot",
        ),
      )
      .mockResolvedValueOnce(
        processingQueueResponse(
          [persistedInclusion],
          "persisted-benchmark-snapshot",
        ),
      );

    render(<App />);

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([persistedInclusion]),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
  });

  it("retains a legacy ordinary mutation lease without specific evidence", async () => {
    const jobId = "e".repeat(32);
    const initialJob = jobRecord({
      id: jobId,
      original_filename: "legacy-reload-spanning-approval.png",
    });
    const persistedJob: JobRecord = {
      ...initialJob,
      status: "approved",
      approved_state: canonicalState(),
      updated_at: "2026-07-20T12:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([initialJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.setItem(
      "poker-training-processing-mutation-v1",
      JSON.stringify({
        ownerId: "previous-page",
        jobId,
        baselineUpdatedAt: initialJob.updated_at,
        expiresAt: Date.now() + 30_000,
      }),
    );
    const pendingRetry = deferredResponse();
    fetchMock()
      .mockResolvedValueOnce(
        processingQueueResponse([persistedJob], "legacy-lease-commit-snapshot"),
      )
      .mockReturnValue(pendingRetry.promise);

    render(<App />);

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Approve state" }),
      ).toBeDisabled(),
    );
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([persistedJob]);
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).not.toBeNull();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();
    expect(fetchMock().mock.calls[0]?.[0]).toBe(
      "http://localhost:8000/api/admin/ocr/jobs",
    );
  });

  it("does not replace a claimed recovery lease with a new mutation", async () => {
    const jobId = "9".repeat(32);
    const initialJob = jobRecord({
      id: jobId,
      original_filename: "pending-recovery.png",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([initialJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.setItem(
      "poker-training-processing-mutation-v1",
      JSON.stringify({
        kind: "job",
        ownerId: "previous-page",
        jobId,
        baselineUpdatedAt: initialJob.updated_at,
        expiresAt: Date.now() + 30_000,
      }),
    );
    const pendingQueue = deferredResponse();
    fetchMock().mockReturnValueOnce(pendingQueue.promise);
    render(<App />);
    const user = userEvent.setup();

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
    const claimedLease = JSON.parse(
      String(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    expect(
      await screen.findByText(
        "Finishing recovery from a previous action. Try again in a moment.",
      ),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/admin/ocr/jobs",
    ]);
    expect(
      JSON.parse(
        String(
          window.sessionStorage.getItem(
            "poker-training-processing-mutation-v1",
          ),
        ),
      ),
    ).toEqual(claimedLease);

    await act(async () => {
      pendingQueue.resolve(
        processingQueueResponse([initialJob], "unchanged-recovery-snapshot"),
      );
      await pendingQueue.promise;
    });
  });

  it("keeps history unsynced when a reload races an archived write", async () => {
    const jobId = "5".repeat(32);
    const archivedAt = "2026-07-20T12:00:00Z";
    const initialJob: JobRecord = {
      ...approvedJob(),
      id: jobId,
      original_filename: "reload-spanning-archived-approval.png",
      archived_at: archivedAt,
    };
    const interveningJob: JobRecord = {
      ...initialJob,
      benchmark_included: true,
      updated_at: "2026-07-20T12:01:30Z",
    };
    const persistedJob: JobRecord = {
      ...interveningJob,
      approved_state: canonicalState({ pot_size: 20 }),
      updated_at: "2026-07-20T12:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: jobId,
          job: initialJob,
          savedAt: archivedAt,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    const pendingMutation = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingMutation.promise)
      .mockResolvedValueOnce(
        processingQueueResponse(
          [interveningJob],
          "intervening-benchmark-snapshot",
        ),
      )
      .mockResolvedValueOnce(jsonResponse(persistedJob));
    const firstRender = render(<App />);
    const user = userEvent.setup();

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
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/admin/ocr/jobs/${jobId}/approve`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
    firstRender.unmount();
    render(<App />);

    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-history-v1")),
        )[0].job,
      ).toEqual(persistedJob),
    );
    expect(
      window.sessionStorage.getItem("poker-training-history-mutation-v1"),
    ).toBeNull();
    expect(window.sessionStorage.getItem("poker-training-history-synced")).toBe(
      "true",
    );
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      `http://localhost:8000/api/admin/ocr/jobs/${jobId}/approve`,
      "http://localhost:8000/api/admin/ocr/history",
      `http://localhost:8000/api/admin/ocr/jobs/${jobId}`,
    ]);
  });

  it("restores a committed ordinary approval after its response is lost", async () => {
    const parsedJob = jobRecord({
      id: "c".repeat(32),
      original_filename: "approval-response-lost.png",
    });
    const correctedState = canonicalState({ pot_size: 20 });
    const persistedApproval: JobRecord = {
      ...parsedJob,
      status: "approved",
      approved_state: correctedState,
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([parsedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockRejectedValueOnce(new TypeError("Connection lost after approval"))
      .mockResolvedValueOnce(
        processingQueueResponse([parsedJob], "stale-approval-snapshot"),
      )
      .mockResolvedValueOnce(
        processingQueueResponse(
          [persistedApproval],
          "persisted-approval-snapshot",
        ),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    const potInput = await screen.findByDisplayValue("12.5");
    await user.clear(potInput);
    await user.type(potInput, "20");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    expect(
      await screen.findByText("Connection lost after approval"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: "Approve state",
        }),
      ).toBeDisabled(),
    );
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([persistedApproval]);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");

    firstRender.unmount();
    render(<App />);

    expect(await screen.findByDisplayValue("20")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      `http://localhost:8000/api/admin/ocr/jobs/${parsedJob.id}/approve`,
      "http://localhost:8000/api/admin/ocr/jobs",
      "http://localhost:8000/api/admin/ocr/jobs",
    ]);
  });

  it("restores an upload that commits after a replacement page reads a stale queue", async () => {
    const created = jobRecord({
      id: "a".repeat(32),
      original_filename: "reload-spanning-upload.png",
    });
    window.localStorage.setItem("poker-training-processing-v1", "[]");
    window.localStorage.setItem("poker-training-processing-total-v1", "0");
    window.localStorage.setItem("poker-training-history-v1", "[]");
    window.localStorage.setItem("poker-training-history-total-v1", "0");
    window.sessionStorage.setItem("poker-training-processing-synced", "true");
    window.sessionStorage.setItem("poker-training-history-synced", "true");
    const pendingUpload = deferredResponse();
    let uploadRequestId = "";
    fetchMock()
      .mockImplementationOnce((_url, request) => {
        uploadRequestId = String(
          (request?.body as FormData).get("upload_request_id"),
        );
        return pendingUpload.promise;
      })
      .mockResolvedValueOnce(
        processingQueueResponse([], "stale-upload-snapshot"),
      )
      .mockImplementationOnce(() =>
        Promise.resolve(
          processingQueueResponse(
            [{ ...created, upload_request_id: uploadRequestId }],
            "committed-upload-snapshot",
          ),
        ),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await unlockAdministrativeAccess(user);
    await switchToUploadMode(user);
    await user.upload(
      screen.getByLabelText("Choose screenshots"),
      new File(["upload"], created.original_filename, { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
    expect(uploadRequestId).not.toBe("");
    firstRender.unmount();

    render(<App />);
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(2));
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).not.toBeNull();

    await act(async () => {
      pendingUpload.resolve(jsonResponse(created, 201));
      await pendingUpload.promise;
    });

    expect(
      await screen.findByRole("button", {
        name: `Open screenshot 1: ${created.original_filename}`,
      }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ).toBeNull(),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/admin/ocr/jobs",
      "http://localhost:8000/api/admin/ocr/jobs",
      "http://localhost:8000/api/admin/ocr/jobs",
    ]);
  });

  it("does not settle a reload-spanning upload from another job with the same filename", async () => {
    const filename = "duplicate-name.png";
    const created = jobRecord({
      id: "a".repeat(32),
      original_filename: filename,
    });
    const foreignJob = jobRecord({
      id: "b".repeat(32),
      original_filename: filename,
      upload_request_id: "foreign-upload-request",
    });
    window.localStorage.setItem("poker-training-processing-v1", "[]");
    window.localStorage.setItem("poker-training-processing-total-v1", "0");
    window.localStorage.setItem("poker-training-history-v1", "[]");
    window.localStorage.setItem("poker-training-history-total-v1", "0");
    window.sessionStorage.setItem("poker-training-processing-synced", "true");
    window.sessionStorage.setItem("poker-training-history-synced", "true");
    const pendingUpload = deferredResponse();
    let uploadRequestId = "";
    fetchMock()
      .mockImplementationOnce((_url, request) => {
        uploadRequestId = String(
          (request?.body as FormData).get("upload_request_id"),
        );
        return pendingUpload.promise;
      })
      .mockResolvedValueOnce(
        processingQueueResponse([foreignJob], "foreign-upload-snapshot"),
      )
      .mockImplementationOnce(() =>
        Promise.resolve(
          processingQueueResponse(
            [foreignJob, { ...created, upload_request_id: uploadRequestId }],
            "committed-upload-snapshot",
          ),
        ),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await unlockAdministrativeAccess(user);
    await switchToUploadMode(user);
    await user.upload(
      screen.getByLabelText("Choose screenshots"),
      new File(["upload"], filename, { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
    firstRender.unmount();

    render(<App />);
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(2));
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).not.toBeNull();

    await act(async () => {
      pendingUpload.resolve(jsonResponse(created, 201));
      await pendingUpload.promise;
    });

    await waitFor(() =>
      expect(
        screen.getAllByRole("button", {
          name: /Open screenshot \d+: duplicate-name\.png/,
        }),
      ).toHaveLength(2),
    );
    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ).toBeNull(),
    );
  });

  it("persists every selected file before starting a batch upload", async () => {
    const pendingUpload = deferredResponse();
    let followUpRequest = 0;
    fetchMock()
      .mockReturnValueOnce(pendingUpload.promise)
      .mockImplementation(() =>
        Promise.resolve(
          followUpRequest++ === 0
            ? jsonResponse({ detail: "Invalid screenshot" }, 422)
            : processingQueueResponse([], "failed-batch-snapshot"),
        ),
      );
    render(<App />);
    const user = userEvent.setup();

    await unlockAdministrativeAccess(user);
    await switchToUploadMode(user);
    await user.upload(screen.getByLabelText("Choose screenshots"), [
      new File(["first"], "batch-first.png", { type: "image/png" }),
      new File(["second"], "batch-second.png", { type: "image/png" }),
    ]);
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));

    expect(
      JSON.parse(
        String(
          window.sessionStorage.getItem(
            "poker-training-processing-mutation-v1",
          ),
        ),
      ).expectedUploads,
    ).toEqual([
      { requestId: expect.any(String), target: "parsed" },
      { requestId: expect.any(String), target: "parsed" },
    ]);

    await act(async () => {
      pendingUpload.resolve(
        jsonResponse({ detail: "Invalid screenshot" }, 422),
      );
      await pendingUpload.promise;
    });
    expect(
      await screen.findByText(
        "2 screenshots need attention. Check the failed queue items.",
      ),
    ).toBeInTheDocument();
  });

  it("does not let a replaced upload page reclaim its mutation lease", async () => {
    window.localStorage.setItem("poker-training-processing-v1", "[]");
    window.localStorage.setItem("poker-training-processing-total-v1", "0");
    window.localStorage.setItem("poker-training-history-v1", "[]");
    window.localStorage.setItem("poker-training-history-total-v1", "0");
    const pendingUpload = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingUpload.promise)
      .mockResolvedValue(
        processingQueueResponse([], "failed-upload-stale-snapshot"),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await unlockAdministrativeAccess(user);
    await switchToUploadMode(user);
    await user.upload(
      screen.getByLabelText("Choose screenshots"),
      new File(["invalid"], "reload-spanning-failure.png", {
        type: "image/png",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
    const originalLease = JSON.parse(
      String(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ),
    );
    firstRender.unmount();

    render(<App />);
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(2));
    const replacementLease = JSON.parse(
      String(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ),
    );
    expect(replacementLease.ownerId).not.toBe(originalLease.ownerId);

    await act(async () => {
      pendingUpload.resolve(
        jsonResponse({ detail: "Invalid screenshot" }, 422),
      );
      await pendingUpload.promise;
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });

    const retainedLease = JSON.parse(
      String(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ),
    );
    expect(retainedLease.ownerId).toBe(replacementLease.ownerId);
    expect(retainedLease.expectedUploads).toEqual([
      { requestId: expect.any(String), target: "parsed" },
    ]);
  });

  it("restores a batch archive after stale processing and history reloads", async () => {
    const readyJob = {
      ...approvedJob(),
      id: "b".repeat(32),
      original_filename: "reload-spanning-archive.png",
    };
    const archivedJob: JobRecord = {
      ...readyJob,
      archived_at: "2026-07-20T12:02:00Z",
      updated_at: "2026-07-20T12:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([readyJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.localStorage.setItem("poker-training-history-v1", "[]");
    window.localStorage.setItem("poker-training-history-total-v1", "0");
    window.sessionStorage.setItem("poker-training-processing-synced", "true");
    window.sessionStorage.setItem("poker-training-history-synced", "true");
    const pendingArchive = deferredResponse();
    let archiveCommitted = false;
    let processingReads = 0;
    let historyReads = 0;
    fetchMock().mockImplementation((url, init) => {
      if (
        url === "http://localhost:8000/api/admin/ocr/history" &&
        init?.method === "PUT"
      ) {
        return pendingArchive.promise;
      }
      if (url === "http://localhost:8000/api/admin/ocr/jobs") {
        processingReads += 1;
        return Promise.resolve(
          processingQueueResponse(
            archiveCommitted ? [] : [readyJob],
            `archive-processing-${processingReads}`,
          ),
        );
      }
      if (url === "http://localhost:8000/api/admin/ocr/history") {
        historyReads += 1;
        return Promise.resolve(
          jsonResponse({
            total: archiveCommitted ? 1 : 0,
            jobs: archiveCommitted ? [archivedJob] : [],
            snapshot_version: `archive-history-${historyReads}`,
          }),
        );
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Clear reviewed" }));
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/history",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    firstRender.unmount();
    render(<App />);

    await waitFor(() => expect(processingReads).toBeGreaterThanOrEqual(1));
    await waitFor(() => expect(historyReads).toBeGreaterThanOrEqual(1));
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).not.toBeNull();
    expect(
      window.sessionStorage.getItem("poker-training-history-mutation-v1"),
    ).not.toBeNull();

    archiveCommitted = true;
    await act(async () => {
      pendingArchive.resolve(
        jsonResponse({
          total: 1,
          jobs: [archivedJob],
          snapshot_version: "archive-commit-response",
        }),
      );
      await pendingArchive.promise;
    });

    await waitFor(() => expect(historyReads).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(processingReads).toBeGreaterThanOrEqual(2));
    expect(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: `Open screenshot 1: ${readyJob.original_filename}`,
        }),
      ).not.toBeInTheDocument(),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
    expect(
      window.sessionStorage.getItem("poker-training-history-mutation-v1"),
    ).toBeNull();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
    expect(window.sessionStorage.getItem("poker-training-history-synced")).toBe(
      "true",
    );
  });

  it("confirms an omitted benchmark hand before settling archive recovery", async () => {
    const readyJob = {
      ...approvedJob(),
      id: "c".repeat(32),
      original_filename: "queued-archive.png",
    };
    const benchmarkJobId = "d".repeat(32);
    const pristineBenchmark = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "omitted-benchmark.png",
      image_filename: `${benchmarkJobId}.png`,
      parser_result: null,
      benchmark_included: true,
    };
    const archivedReadyJob: JobRecord = {
      ...readyJob,
      archived_at: "2026-07-20T12:02:00Z",
      updated_at: "2026-07-20T12:02:00Z",
    };
    const archivedBenchmark: JobRecord = {
      ...pristineBenchmark,
      archived_at: "2026-07-20T12:02:00Z",
      updated_at: "2026-07-20T12:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([readyJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    const pendingArchive = deferredResponse();
    let archiveCommitted = false;
    let processingReads = 0;
    let benchmarkReads = 0;
    fetchMock().mockImplementation((url, init) => {
      if (url === "http://localhost:8000/api/admin/ocr/benchmarks") {
        return Promise.resolve(
          jsonResponse(
            benchmarkOverviewForJob(
              benchmarkJobId,
              pristineBenchmark.original_filename,
            ),
          ),
        );
      }
      if (
        url === `http://localhost:8000/api/admin/ocr/jobs/${benchmarkJobId}`
      ) {
        benchmarkReads += 1;
        return Promise.resolve(
          jsonResponse(
            archiveCommitted ? archivedBenchmark : pristineBenchmark,
          ),
        );
      }
      if (
        url === "http://localhost:8000/api/admin/ocr/history" &&
        init?.method === "PUT"
      ) {
        return pendingArchive.promise;
      }
      if (url === "http://localhost:8000/api/admin/ocr/jobs") {
        processingReads += 1;
        return Promise.resolve(
          processingQueueResponse(
            archiveCommitted ? [] : [readyJob],
            `omitted-archive-processing-${processingReads}`,
          ),
        );
      }
      if (url === "http://localhost:8000/api/admin/ocr/history") {
        return Promise.resolve(
          jsonResponse({
            total: archiveCommitted ? 2 : 0,
            jobs: archiveCommitted ? [archivedBenchmark, archivedReadyJob] : [],
            snapshot_version: archiveCommitted
              ? "omitted-archive-committed"
              : "omitted-archive-stale",
          }),
        );
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: `Toggle ${pristineBenchmark.original_filename} benchmark details`,
      }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Review hand" }),
    );
    await user.click(screen.getByRole("button", { name: "Clear reviewed" }));
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/history",
        expect.objectContaining({ method: "PUT" }),
      ),
    );
    firstRender.unmount();
    render(<App />);

    await waitFor(() => expect(processingReads).toBeGreaterThanOrEqual(1));
    await waitFor(() => expect(benchmarkReads).toBeGreaterThanOrEqual(2));
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).not.toBeNull();
    expect(
      window.sessionStorage.getItem("poker-training-history-mutation-v1"),
    ).not.toBeNull();

    archiveCommitted = true;
    await act(async () => {
      pendingArchive.resolve(
        jsonResponse({
          total: 2,
          jobs: [archivedBenchmark, archivedReadyJob],
          snapshot_version: "omitted-archive-response",
        }),
      );
      await pendingArchive.promise;
    });

    await waitFor(() => expect(processingReads).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(benchmarkReads).toBeGreaterThanOrEqual(3));
    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ).toBeNull(),
    );
    expect(
      window.sessionStorage.getItem("poker-training-history-mutation-v1"),
    ).toBeNull();
    expect(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    ).toBeInTheDocument();
  });

  it("restores an archived approval after its response is lost", async () => {
    const jobId = "9".repeat(32);
    const archivedAt = "2026-07-20T12:00:00Z";
    const initialJob = jobRecord({
      id: jobId,
      original_filename: "archived-approval-response-lost.png",
      image_filename: `${jobId}.png`,
      archived_at: archivedAt,
    });
    const persistedJob: JobRecord = {
      ...initialJob,
      status: "approved",
      approved_state: canonicalState({ pot_size: 20 }),
      updated_at: "2026-07-20T12:10:00Z",
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([{ id: jobId, job: initialJob, savedAt: archivedAt }]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    fetchMock()
      .mockRejectedValueOnce(
        new TypeError("Connection lost after archived approval"),
      )
      .mockResolvedValueOnce(jsonResponse(persistedJob));
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", {
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
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-history-v1")),
        )[0].job,
      ).toEqual(persistedJob),
    );
    expect(window.sessionStorage.getItem("poker-training-history-synced")).toBe(
      "true",
    );
    expect(await screen.findByDisplayValue("20")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();

    firstRender.unmount();
    render(<App />);
    await user.click(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    );

    expect(await screen.findByDisplayValue("20")).toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      `http://localhost:8000/api/admin/ocr/jobs/${jobId}/approve`,
      `http://localhost:8000/api/admin/ocr/jobs/${jobId}`,
    ]);
  });

  it("preserves ordinary approval edits when the failed write did not commit", async () => {
    const parsedJob = jobRecord({
      id: "d".repeat(32),
      original_filename: "approval-not-committed.png",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([parsedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockRejectedValueOnce(new TypeError("Approval request failed"))
      .mockResolvedValue(
        processingQueueResponse([parsedJob], "unchanged-approval-snapshot"),
      );
    render(<App />);
    const user = userEvent.setup();

    const potInput = await screen.findByDisplayValue("12.5");
    await user.clear(potInput);
    await user.type(potInput, "20");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    expect(
      await screen.findByText("Approval request failed"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/jobs",
        expect.anything(),
      ),
    );
    expect(potInput).toHaveValue("20");
    expect(screen.getByRole("button", { name: "Approve state" })).toBeEnabled();
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([parsedJob]);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();
    expect(
      JSON.parse(
        String(
          window.sessionStorage.getItem(
            "poker-training-processing-mutation-v1",
          ),
        ),
      ),
    ).toEqual(
      expect.objectContaining({
        kind: "job",
        jobId: parsedJob.id,
        baselineUpdatedAt: parsedJob.updated_at,
      }),
    );
  });

  it("preserves a dirty form while its active job is reconciled", async () => {
    const cachedJob = jobRecord({
      id: "e".repeat(32),
      original_filename: "edited-table.png",
    });
    const reconciledState: DetectedState = {
      ...detectedState,
      hero_cards: [
        { rank: "Q", suit: "clubs" },
        { rank: "Q", suit: "hearts" },
      ],
    };
    const reconciledJob = jobRecord({
      ...cachedJob,
      parser_result: {
        ...cachedJob.parser_result!,
        state: reconciledState,
      },
      updated_at: "2026-07-10T00:01:00Z",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([cachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    const pendingQueue = deferredResponse();
    fetchMock().mockReturnValueOnce(pendingQueue.promise);
    render(<App />);
    const user = userEvent.setup();
    const heroCards = await screen.findByLabelText(/Hero cards/);

    await user.clear(heroCards);
    await user.type(heroCards, "7d Ah");
    pendingQueue.resolve(
      jsonResponse({
        total: 1,
        jobs: [reconciledJob],
        snapshot_version: "reconciled-snapshot",
      }),
    );

    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        )[0].updated_at,
      ).toBe("2026-07-10T00:01:00Z"),
    );
    expect(heroCards).toHaveValue("7d Ah");
    expect(screen.queryByDisplayValue("Qc Qh")).not.toBeInTheDocument();
  });

  it("keeps a dirty cached job selected when reconciliation removes it", async () => {
    const cachedJob = jobRecord({
      id: "f".repeat(32),
      original_filename: "dirty-cached-table.png",
    });
    const incomingJob = jobRecord({
      id: "1".repeat(32),
      original_filename: "different-table.png",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([cachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    const pendingQueue = deferredResponse();
    fetchMock().mockReturnValueOnce(pendingQueue.promise);
    render(<App />);
    const user = userEvent.setup();
    const heroCards = await screen.findByLabelText(/Hero cards/);

    await user.clear(heroCards);
    await user.type(heroCards, "7d Ah");
    pendingQueue.resolve(
      jsonResponse({
        total: 1,
        jobs: [incomingJob],
        snapshot_version: "replacement-snapshot",
      }),
    );

    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 2: different-table.png",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 1: dirty-cached-table.png",
      }),
    ).toHaveClass("active");
    expect(heroCards).toHaveValue("7d Ah");
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();
  });

  it("ignores a stale restore after cached jobs move to history", async () => {
    const staleJob: JobRecord = {
      ...approvedJob(),
      id: "2".repeat(32),
      original_filename: "stale-processing.png",
      archived_at: null,
    };
    const archivedJob: JobRecord = {
      ...staleJob,
      archived_at: "2026-07-10T00:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([staleJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    const pendingRestore = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingRestore.promise)
      .mockResolvedValueOnce(
        jsonResponse({
          total: 1,
          jobs: [archivedJob],
          snapshot_version: "archived-snapshot",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 0,
          jobs: [],
          snapshot_version: "fresh-processing-snapshot",
        }),
      );
    render(<App />);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/jobs",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Clear reviewed" }));
    expect(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    ).toBeInTheDocument();

    await act(async () => {
      pendingRestore.resolve(
        jsonResponse({
          total: 1,
          jobs: [staleJob],
          snapshot_version: "stale-processing-snapshot",
        }),
      );
      await pendingRestore.promise;
    });

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenNthCalledWith(
        3,
        "http://localhost:8000/api/admin/ocr/jobs",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: stale-processing.png",
      }),
    ).not.toBeInTheDocument();
    expect(window.localStorage.getItem("poker-training-processing-v1")).toBe(
      "[]",
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
  });

  it("reconciles queues larger than the bounded browser cache", async () => {
    const persistedJobs = Array.from({ length: 101 }, (_, index) =>
      jobRecord({
        id: index.toString(16).padStart(32, "0"),
        original_filename: `persisted-${index + 1}.png`,
      }),
    );
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify(persistedJobs.slice(0, 100)),
    );
    window.localStorage.setItem(
      "poker-training-processing-total-v1",
      String(persistedJobs.length),
    );
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: persistedJobs.length,
          jobs: persistedJobs.slice(0, 100),
          snapshot_version: "processing-snapshot",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: persistedJobs.length,
          jobs: persistedJobs.slice(100),
          snapshot_version: "processing-snapshot",
        }),
      );

    render(<App />);

    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 101: persisted-101.png",
      }),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/admin/ocr/jobs",
      "http://localhost:8000/api/admin/ocr/jobs?offset=100",
    ]);
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toHaveLength(100);
    expect(
      window.localStorage.getItem("poker-training-processing-total-v1"),
    ).toBe("101");
  });

  it("preserves the known complete count while queue reconciliation is pending", async () => {
    const persistedJobs = Array.from({ length: 101 }, (_, index) =>
      jobRecord({
        id: index.toString(16).padStart(32, "0"),
        original_filename: `persisted-${index + 1}.png`,
      }),
    );
    const approved = {
      ...persistedJobs[0],
      status: "approved" as const,
      approved_state: canonicalState(),
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify(persistedJobs.slice(0, 100)),
    );
    window.localStorage.setItem(
      "poker-training-processing-total-v1",
      String(persistedJobs.length),
    );
    const pendingQueue = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingQueue.promise)
      .mockResolvedValueOnce(jsonResponse(approved));
    render(<App />);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/jobs",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    const approveButton = screen.getByRole("button", { name: "Approve state" });
    await waitFor(() => expect(approveButton).toBeEnabled());
    await user.click(approveButton);

    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        )[0].status,
      ).toBe("approved"),
    );
    expect(
      window.localStorage.getItem("poker-training-processing-total-v1"),
    ).toBe("101");
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();
  });

  it.each([
    {
      label: "persisted parser failure",
      filename: "parse-failed.png",
      status: "error" as const,
      persistedError: "Image could not be parsed",
      localError: "Image could not be parsed",
      responseLost: false,
    },
    {
      label: "persisted successful upload",
      filename: "parsed-response-lost.png",
      status: "parsed" as const,
      persistedError: null,
      localError: "Connection lost after upload",
      responseLost: true,
    },
  ])(
    "replaces a local placeholder with the $label during queue reconciliation",
    async ({ filename, localError, persistedError, responseLost, status }) => {
      window.sessionStorage.removeItem("poker-training-processing-synced");
      const pendingQueue = deferredResponse();
      const failedAt = new Date().toISOString();
      const persistedJob = jobRecord({
        id: "9".repeat(32),
        status,
        original_filename: filename,
        parser_result: status === "error" ? null : jobRecord().parser_result,
        error: persistedError,
        created_at: failedAt,
        updated_at: failedAt,
      });
      let uploadRequestId = "";
      fetchMock().mockReturnValueOnce(pendingQueue.promise);
      if (responseLost) {
        fetchMock().mockImplementationOnce((_url, request) => {
          uploadRequestId = String(
            (request?.body as FormData).get("upload_request_id"),
          );
          return Promise.reject(new TypeError(localError));
        });
      } else {
        fetchMock().mockImplementationOnce((_url, request) => {
          uploadRequestId = String(
            (request?.body as FormData).get("upload_request_id"),
          );
          return Promise.resolve(
            jsonResponse(
              {
                detail: localError,
              },
              502,
            ),
          );
        });
      }
      fetchMock().mockImplementationOnce(() =>
        Promise.resolve(
          jsonResponse({
            total: 1,
            jobs: [{ ...persistedJob, upload_request_id: uploadRequestId }],
            snapshot_version: "restored-upload",
          }),
        ),
      );
      render(<App />);
      const user = userEvent.setup();

      await waitFor(() =>
        expect(fetchMock()).toHaveBeenCalledWith(
          "http://localhost:8000/api/admin/ocr/jobs",
          expect.objectContaining({ credentials: "include" }),
        ),
      );
      await unlockAdministrativeAccess(user);
      await switchToUploadMode(user);
      await user.upload(
        screen.getByLabelText("Choose screenshots"),
        new File(["upload"], filename, { type: "image/png" }),
      );
      await user.click(
        screen.getByRole("button", { name: "Upload and parse" }),
      );

      await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
      await waitFor(() =>
        expect(
          screen.getAllByRole("button", {
            name: new RegExp(
              `Open screenshot \\d+: ${filename.replace(".", "\\.")}`,
            ),
          }),
        ).toHaveLength(1),
      );
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([{ ...persistedJob, upload_request_id: uploadRequestId }]);
      expect(
        window.sessionStorage.getItem("poker-training-processing-synced"),
      ).toBe("true");

      await act(async () => {
        pendingQueue.resolve(
          jsonResponse({
            total: 0,
            jobs: [],
            snapshot_version: "stale-empty-snapshot",
          }),
        );
      });
    },
  );

  it("reconciles a lost upload response after an already-synced mount", async () => {
    const persistedAt = new Date().toISOString();
    const persistedJob = jobRecord({
      id: "8".repeat(32),
      original_filename: "lost-after-sync.png",
      created_at: persistedAt,
      updated_at: persistedAt,
    });
    let uploadRequestId = "";
    fetchMock()
      .mockImplementationOnce((_url, request) => {
        uploadRequestId = String(
          (request?.body as FormData).get("upload_request_id"),
        );
        return Promise.reject(new TypeError("Connection lost after upload"));
      })
      .mockImplementationOnce(() =>
        Promise.resolve(
          jsonResponse({
            total: 1,
            jobs: [{ ...persistedJob, upload_request_id: uploadRequestId }],
            snapshot_version: "post-mutation-snapshot",
          }),
        ),
      );
    render(<App />);
    const user = userEvent.setup();

    expect(fetchMock()).not.toHaveBeenCalled();
    await unlockAdministrativeAccess(user);
    await switchToUploadMode(user);
    await user.upload(
      screen.getByLabelText("Choose screenshots"),
      new File(["upload"], "lost-after-sync.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        screen.getAllByRole("button", {
          name: /Open screenshot \d+: lost-after-sync\.png/,
        }),
      ).toHaveLength(1),
    );
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([{ ...persistedJob, upload_request_id: uploadRequestId }]);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
  });
});
