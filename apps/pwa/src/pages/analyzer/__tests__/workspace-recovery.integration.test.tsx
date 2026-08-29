import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DetectedState } from "../../../shared/types/poker";
import type { JobRecord } from "../../../shared/types/jobs";
import AnalyzerPage from "../AnalyzerPage";
import type { AnalyzerRouteNavigation } from "../analyzerRouteState";
import {
  AnalyzerTestApp as App,
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
  recommendation,
  recommendedJob,
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
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
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
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
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
      status: "recommended",
      recommendation,
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
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
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
    expect(screen.getByLabelText("Recommendation")).toBeInTheDocument();
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
      if (url.endsWith(`/api/jobs/${removedJob.id}`)) {
        return Promise.resolve(jsonResponse(removedJob));
      }
      if (url.endsWith("/api/jobs")) {
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
      openTraining: vi.fn(),
      openWorkspace: vi.fn(),
    };
    const view = render(
      <App>
        <AnalyzerPage
          navigation={navigation}
          route={{ jobId: removedJob.id, surface: "job" }}
        />
      </App>,
    );

    expect(await screen.findByDisplayValue("Ah Kd")).toBeInTheDocument();
    view.rerender(
      <App>
        <AnalyzerPage
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
      String(input).endsWith("/api/jobs")
        ? pendingQueue.promise
        : pendingJob.promise,
    );
    const navigation: AnalyzerRouteNavigation = {
      closeSurface: vi.fn(),
      managed: true,
      openBenchmarks: vi.fn(),
      openJob: vi.fn(),
      openTraining: vi.fn(),
      openWorkspace: vi.fn(),
    };
    const view = render(
      <App>
        <AnalyzerPage
          navigation={navigation}
          route={{ jobId: cachedJob.id, surface: "job" }}
        />
      </App>,
    );
    expect(await screen.findByDisplayValue("Ah Kd")).toBeInTheDocument();

    view.rerender(
      <App>
        <AnalyzerPage
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
      "http://localhost:8000/api/jobs",
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

  it("polls a recommendation that was still running during reload", async () => {
    const jobId = "4".repeat(32);
    const pendingJob = {
      ...approvedJob(),
      id: jobId,
      original_filename: "pending-recommendation.png",
      recommendation_pending: true,
      updated_at: "2026-07-10T00:01:00Z",
    };
    const completedJob = {
      ...recommendedJob(),
      id: jobId,
      original_filename: "pending-recommendation.png",
      recommendation_pending: false,
      updated_at: "2026-07-10T00:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([pendingJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    const pendingCompletion = deferredResponse();
    fetchMock()
      .mockResolvedValueOnce(
        processingQueueResponse([pendingJob], "recommendation-still-running"),
      )
      .mockReturnValueOnce(pendingCompletion.promise);
    render(<App />);

    const queueItem = await screen.findByRole("button", {
      name: "Open screenshot 1: pending-recommendation.png",
    });
    expect(
      within(queueItem).getByText("Recommendation running"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    ).toBeDisabled();
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(2));
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();

    await act(async () => {
      pendingCompletion.resolve(
        processingQueueResponse([completedJob], "recommendation-completed"),
      );
      await pendingCompletion.promise;
    });

    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    expect(
      within(queueItem).queryByText("Recommendation running"),
    ).not.toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([completedJob]);
  });

  it("lets terminal history state replace a future-dated pending cache", async () => {
    const jobId = "8".repeat(32);
    const archivedAt = "2026-07-10T00:00:30Z";
    const pendingJob = {
      ...approvedJob(),
      id: jobId,
      original_filename: "archived-pending-recommendation.png",
      recommendation_pending: true,
      archived_at: archivedAt,
      updated_at: "9999-01-01T00:00:00Z",
    };
    const completedJob = {
      ...recommendedJob(),
      id: jobId,
      original_filename: "archived-pending-recommendation.png",
      recommendation_pending: false,
      archived_at: archivedAt,
      updated_at: "2026-07-10T00:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: jobId,
          job: pendingJob,
          savedAt: archivedAt,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    const pendingHistoryRestore = deferredResponse();
    fetchMock().mockReturnValueOnce(pendingHistoryRestore.promise);
    render(<App />);
    const user = userEvent.setup();

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
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/jobs/${jobId}`,
        { credentials: "include" },
      ),
    );
    expect(
      window.sessionStorage.getItem("poker-training-history-synced"),
    ).toBeNull();
    await act(async () => {
      pendingHistoryRestore.resolve(jsonResponse(completedJob));
      await pendingHistoryRestore.promise;
    });

    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    expect(screen.getByText(recommendation.explanation)).toBeInTheDocument();
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-history-v1")),
      )[0].job,
    ).toEqual(completedJob);
    expect(window.sessionStorage.getItem("poker-training-history-synced")).toBe(
      "true",
    );
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      `http://localhost:8000/api/jobs/${jobId}`,
    ]);
  });

  it("prefers terminal processing state over a slightly newer pending cache", async () => {
    const jobId = "9".repeat(32);
    const serverUpdatedAt = Date.now();
    const poisonedPendingJob = {
      ...approvedJob(),
      id: jobId,
      original_filename: "future-pending.png",
      recommendation_pending: true,
      updated_at: new Date(serverUpdatedAt + 60_000).toISOString(),
    };
    const completedJob = {
      ...recommendedJob(),
      id: jobId,
      original_filename: "future-pending.png",
      recommendation_pending: false,
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

    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    ).toBeDisabled();
    expect(fetchMock()).toHaveBeenCalledTimes(1);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([completedJob]);
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

  it("retries polling after a pending recommendation restore fails", async () => {
    const jobId = "5".repeat(32);
    const pendingJob = {
      ...approvedJob(),
      id: jobId,
      original_filename: "pending-retry.png",
      recommendation_pending: true,
      updated_at: "2026-07-10T00:01:00Z",
    };
    const completedJob = {
      ...recommendedJob(),
      id: jobId,
      original_filename: "pending-retry.png",
      recommendation_pending: false,
      updated_at: "2026-07-10T00:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([pendingJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        processingQueueResponse(
          [pendingJob],
          "pending-before-transient-failure",
        ),
      )
      .mockRejectedValueOnce(new TypeError("Network unavailable"))
      .mockResolvedValueOnce(
        processingQueueResponse([completedJob], "pending-retry-completed"),
      );

    render(<App />);

    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(3);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      ),
    ).toEqual([completedJob]);
  });

  it("keeps mutated or pending benchmark imports in the cached processing queue", async () => {
    const decisionImport = {
      ...approvedJob(),
      id: "d".repeat(32),
      original_filename: "decision-import.png",
      parser_result: null,
      benchmark_included: true,
      training_decision: {
        action: "call" as const,
        sizing: null,
        certainty: "medium" as const,
        recorded_at: "2026-07-10T00:01:00Z",
      },
    };
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
    const pendingImport = {
      ...approvedJob(),
      id: "a".repeat(32),
      original_filename: "pending-import.png",
      parser_result: null,
      benchmark_included: true,
      recommendation_pending: true,
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([
        decisionImport,
        failedImport,
        pristineImport,
        pendingImport,
      ]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "3");
    const pendingQueue = deferredResponse();
    fetchMock().mockReturnValueOnce(pendingQueue.promise);

    render(<App />);

    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 1: decision-import.png",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 2: failed-import.png",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 3: pending-import.png",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /pristine-import\.png/,
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledWith("http://localhost:8000/api/jobs", {
      credentials: "include",
    });
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
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
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
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
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
          "http://localhost:8000/api/jobs",
          { credentials: "include" },
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
    expect(fetchMock()).toHaveBeenCalledWith("http://localhost:8000/api/jobs", {
      credentials: "include",
    });
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      )[0].parser_result.state.hero_cards,
    ).toEqual(detectedState.hero_cards);
  });

  it.each([
    ["missing recommendation fields", {}],
    ["zero wager sizing", { ...recommendation, action: "raise", sizing: 0 }],
  ])(
    "rejects cached recommendations with %s and restores the backend record",
    async (_label, malformedRecommendation) => {
      const persistedJob = {
        ...recommendedJob(),
        id: "d".repeat(32),
        original_filename: "restored-recommendation.png",
      };
      const malformedJob = {
        ...persistedJob,
        recommendation: malformedRecommendation,
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
          snapshot_version: "valid-recommendation-snapshot",
        }),
      );

      render(<App />);

      expect(
        await screen.findByLabelText("Recommendation"),
      ).toBeInTheDocument();
      expect(screen.getByText(recommendation.explanation)).toBeInTheDocument();
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
      );
    },
  );

  it.each([
    {
      label: "training decision",
      invalidFields: {
        training_decision: {
          action: {},
          sizing: null,
          certainty: "medium",
          recorded_at: "2026-07-20T12:00:00Z",
        },
      },
    },
    {
      label: "zero-sized training decision",
      invalidFields: {
        training_decision: {
          action: "raise",
          sizing: 0,
          certainty: "medium",
          recorded_at: "2026-07-20T12:00:00Z",
        },
      },
    },
    {
      label: "training review note",
      invalidFields: {
        training_review_note: {},
      },
    },
  ])(
    "rejects malformed cached $label and restores the backend record",
    async ({ invalidFields }) => {
      const persistedJob = {
        ...recommendedJob(),
        id: "a".repeat(32),
        original_filename: "restored-training-metadata.png",
        training_decision: {
          action: "call" as const,
          sizing: null,
          certainty: "medium" as const,
          recorded_at: "2026-07-20T12:00:00Z",
        },
        training_reviewed_at: "2026-07-20T12:05:00Z",
        training_review_note: "Review the solver comparison.",
      };
      window.localStorage.setItem(
        "poker-training-processing-v1",
        JSON.stringify([{ ...persistedJob, ...invalidFields }]),
      );
      window.localStorage.setItem("poker-training-processing-total-v1", "1");
      fetchMock().mockResolvedValueOnce(
        jsonResponse({
          total: 1,
          jobs: [persistedJob],
          snapshot_version: "valid-training-metadata-snapshot",
        }),
      );

      render(<App />);

      const restoredItem = await screen.findByRole("button", {
        name: "Open screenshot 1: restored-training-metadata.png",
      });
      expect(within(restoredItem).getByText("recommended")).toBeInTheDocument();
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
      );
      await waitFor(() =>
        expect(
          JSON.parse(
            String(window.localStorage.getItem("poker-training-processing-v1")),
          )[0],
        ).toMatchObject({
          training_decision: persistedJob.training_decision,
          training_reviewed_at: persistedJob.training_reviewed_at,
          training_review_note: persistedJob.training_review_note,
        }),
      );
    },
  );

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
    expect(fetchMock()).toHaveBeenCalledWith("http://localhost:8000/api/jobs", {
      credentials: "include",
    });
  });

  it("keeps unsaved form edits out of the processing cache", async () => {
    const persistedJob = {
      ...recommendedJob(),
      id: "e".repeat(32),
      original_filename: "confirmed-recommendation.png",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([persistedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    const firstRender = render(<App />);
    const user = userEvent.setup();

    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    const potInput = screen.getByLabelText(/Pot/);
    await user.clear(potInput);
    await user.type(potInput, "18");

    expect(screen.queryByLabelText("Recommendation")).not.toBeInTheDocument();
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      )[0],
    ).toMatchObject({
      status: "recommended",
      approved_state: persistedJob.approved_state,
      recommendation: persistedJob.recommendation,
    });

    firstRender.unmount();
    render(<App />);

    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    expect(screen.getByLabelText(/Pot/)).toHaveValue("12.5");
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
    expect(fetchMock()).toHaveBeenCalledWith("http://localhost:8000/api/jobs", {
      credentials: "include",
    });
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
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
      ),
    );
    screen.getByRole("button", { name: "Approve state" }).click();
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenNthCalledWith(
        2,
        `http://localhost:8000/api/jobs/${cachedJob.id}/approve`,
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
    expect(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    ).toBeEnabled();
    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-synced"),
      ).toBe("true"),
    );
    expect(fetchMock()).toHaveBeenCalledTimes(3);
  });

  it.each(["approval", "recommendation", "decision"] as const)(
    "reloads backend state when an older restore finishes during an ordinary %s request",
    async (operation) => {
      const jobId = "b".repeat(32);
      const initialJob =
        operation === "approval"
          ? jobRecord({
              id: jobId,
              original_filename: `pending-${operation}.png`,
            })
          : {
              ...approvedJob(),
              id: jobId,
              original_filename: `pending-${operation}.png`,
            };
      const persistedJob: JobRecord =
        operation === "approval"
          ? {
              ...initialJob,
              status: "approved",
              approved_state: canonicalState(),
              updated_at: "2026-07-10T00:01:00Z",
            }
          : operation === "recommendation"
            ? {
                ...initialJob,
                status: "recommended",
                recommendation,
                updated_at: "2026-07-10T00:01:00Z",
              }
            : {
                ...initialJob,
                training_decision: {
                  action: "call",
                  sizing: null,
                  certainty: "medium",
                  recorded_at: "2026-07-10T00:01:00Z",
                },
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
          processingQueueResponse(
            [persistedJob],
            `pending-${operation}-snapshot`,
          ),
        );
      const firstRender = render(<App />);
      const user = userEvent.setup();

      await waitFor(() =>
        expect(fetchMock()).toHaveBeenCalledWith(
          "http://localhost:8000/api/jobs",
          { credentials: "include" },
        ),
      );
      if (operation === "approval") {
        await user.click(screen.getByRole("button", { name: "Approve state" }));
      } else if (operation === "recommendation") {
        await user.click(
          screen.getByRole("button", {
            name: "Request recommendation",
          }),
        );
      } else {
        const decisionPanel = await screen.findByLabelText(
          "Your training decision",
        );
        await user.click(
          within(decisionPanel).getByRole("button", { name: "call" }),
        );
        await user.click(
          within(decisionPanel).getByRole("button", { name: "medium" }),
        );
        await user.click(
          within(decisionPanel).getByRole("button", { name: "Lock answer" }),
        );
      }

      const mutationPath =
        operation === "approval"
          ? "approve"
          : operation === "decision"
            ? "decision"
            : "recommend";
      const mutationMethod = operation === "decision" ? "PUT" : "POST";
      await waitFor(() =>
        expect(fetchMock()).toHaveBeenCalledWith(
          `http://localhost:8000/api/jobs/${jobId}/${mutationPath}`,
          expect.objectContaining({ method: mutationMethod }),
        ),
      );
      await act(async () => {
        pendingRestore.resolve(
          processingQueueResponse([initialJob], `stale-${operation}-snapshot`),
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
      if (operation === "approval") {
        expect(
          screen.getByRole("button", { name: "Approve state" }),
        ).toBeDisabled();
      } else if (operation === "recommendation") {
        expect(
          await screen.findByLabelText("Recommendation"),
        ).toBeInTheDocument();
      } else {
        expect(
          await within(
            screen.getByLabelText("Your training decision"),
          ).findByText("Answer locked"),
        ).toBeInTheDocument();
      }
      expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
        "http://localhost:8000/api/jobs",
        `http://localhost:8000/api/jobs/${jobId}/${mutationPath}`,
        "http://localhost:8000/api/jobs",
      ]);
    },
  );

  it.each(["approval", "review"] as const)(
    "reloads archived %s state when an older history restore finishes during the request",
    async (operation) => {
      const jobId = "f".repeat(32);
      const archivedAt = "2026-07-20T12:00:00Z";
      const initialJob =
        operation === "approval"
          ? jobRecord({
              id: jobId,
              original_filename: `archived-pending-${operation}.png`,
              archived_at: archivedAt,
            })
          : {
              ...recommendedJob(),
              id: jobId,
              original_filename: `archived-pending-${operation}.png`,
              archived_at: archivedAt,
              training_decision: {
                action: "call" as const,
                sizing: null,
                certainty: "medium" as const,
                recorded_at: "2026-07-20T12:01:00Z",
              },
            };
      const persistedJob: JobRecord =
        operation === "approval"
          ? {
              ...initialJob,
              status: "approved",
              approved_state: canonicalState(),
              updated_at: "2026-07-20T12:02:00Z",
            }
          : {
              ...initialJob,
              training_reviewed_at: "2026-07-20T12:02:00Z",
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
          processingQueueResponse(
            [persistedJob],
            `archived-${operation}-completed`,
          ),
        );
      const firstRender = render(<App />);
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
      if (operation === "approval") {
        await user.click(screen.getByRole("button", { name: "Approve state" }));
      } else {
        await user.click(
          within(
            await screen.findByLabelText("Training decision comparison"),
          ).getByRole("button", { name: "Mark reviewed" }),
        );
      }

      const mutationPath =
        operation === "approval" ? "approve" : "training-review";
      const mutationMethod = operation === "approval" ? "POST" : "PUT";
      await waitFor(() =>
        expect(fetchMock()).toHaveBeenCalledWith(
          `http://localhost:8000/api/jobs/${jobId}/${mutationPath}`,
          expect.objectContaining({ method: mutationMethod }),
        ),
      );
      await act(async () => {
        pendingHistoryRestore.resolve(
          processingQueueResponse([initialJob], `stale-archived-${operation}`),
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
      if (operation === "approval") {
        expect(
          screen.getByRole("button", { name: "Approve state" }),
        ).toBeDisabled();
      } else {
        expect(
          within(
            await screen.findByLabelText("Training decision comparison"),
          ).getByText("Reviewed"),
        ).toBeInTheDocument();
      }
      expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
        "http://localhost:8000/api/history",
        `http://localhost:8000/api/jobs/${jobId}/${mutationPath}`,
        "http://localhost:8000/api/history",
      ]);
    },
  );

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
        `http://localhost:8000/api/jobs/${jobId}/approve`,
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
        screen.getByRole("button", {
          name: "Request recommendation",
        }),
      ).toBeEnabled(),
    );
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
      `http://localhost:8000/api/jobs/${jobId}/approve`,
      "http://localhost:8000/api/jobs",
      "http://localhost:8000/api/jobs",
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
      approved_state: canonicalState({ pot_size: 20 }),
      training_decision: {
        action: "call",
        sizing: null,
        certainty: "medium",
        recorded_at: "2026-07-20T12:01:00Z",
      },
      updated_at: "2026-07-20T12:01:00Z",
    };
    const correctedState = canonicalState({ pot_size: 20 });
    const persistedApproval: JobRecord = {
      ...interveningJob,
      status: "approved",
      approved_state: correctedState,
      training_decision: null,
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
          "intervening-decision-snapshot",
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
        `http://localhost:8000/api/jobs/${jobId}/approve`,
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
      training_decision: {
        action: "call",
        sizing: null,
        certainty: "medium",
        recorded_at: "2026-07-20T12:01:00Z",
      },
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
        expectedRecommendationRequestId: null,
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
          "intervening-decision-snapshot",
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
        screen.getByRole("button", {
          name: "Request recommendation",
        }),
      ).toBeEnabled(),
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
      "http://localhost:8000/api/jobs",
    );
  });

  it("restores and upgrades a legacy recommended upload lease", async () => {
    const uploadRequestId = "legacy-upload-request";
    const persistedJob = {
      ...recommendedJob(),
      id: "f".repeat(32),
      original_filename: "legacy-recommended-upload.png",
      upload_request_id: uploadRequestId,
      updated_at: "2026-07-20T12:02:00Z",
    };
    window.sessionStorage.setItem(
      "poker-training-processing-mutation-v1",
      JSON.stringify({
        kind: "projection",
        ownerId: "previous-page",
        baselineJobIds: [],
        expectedRemovalJobIds: [],
        expectedUploads: [
          {
            requestId: uploadRequestId,
            target: "recommended",
          },
        ],
        expiresAt: Date.now() + 30_000,
      }),
    );
    fetchMock().mockResolvedValueOnce(
      processingQueueResponse(
        [persistedJob],
        "legacy-recommended-upload-snapshot",
      ),
    );

    render(<App />);

    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 1: legacy-recommended-upload.png",
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Recommendation")).toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
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
      "http://localhost:8000/api/jobs",
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
      ...recommendedJob(),
      id: jobId,
      original_filename: "reload-spanning-review.png",
      archived_at: archivedAt,
      training_decision: {
        action: "call",
        sizing: null,
        certainty: "medium",
        recorded_at: "2026-07-20T12:01:00Z",
      },
    };
    const interveningJob: JobRecord = {
      ...initialJob,
      benchmark_included: true,
      updated_at: "2026-07-20T12:01:30Z",
    };
    const persistedJob: JobRecord = {
      ...interveningJob,
      training_reviewed_at: "2026-07-20T12:02:00Z",
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
    await user.click(
      within(
        await screen.findByLabelText("Training decision comparison"),
      ).getByRole("button", { name: "Mark reviewed" }),
    );
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/jobs/${jobId}/training-review`,
        expect.objectContaining({ method: "PUT" }),
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
      `http://localhost:8000/api/jobs/${jobId}/training-review`,
      "http://localhost:8000/api/history",
      `http://localhost:8000/api/jobs/${jobId}`,
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
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    ).toBeEnabled();
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
      `http://localhost:8000/api/jobs/${parsedJob.id}/approve`,
      "http://localhost:8000/api/jobs",
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("releases an approval lease after another tab starts a recommendation", async () => {
    const parsedJob = jobRecord({
      id: "d".repeat(32),
      original_filename: "approval-conflict.png",
    });
    const competingAttempt: JobRecord = {
      ...parsedJob,
      recommendation_pending: true,
      recommendation_request_id: "other-tab-attempt",
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([parsedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: "Recommendation is already running",
          },
          409,
        ),
      )
      .mockResolvedValueOnce(
        processingQueueResponse(
          [competingAttempt],
          "approval-conflict-snapshot",
        ),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Approve state" }));

    expect(
      await screen.findByText("Recommendation is already running"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([competingAttempt]),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
    expect(
      screen.getByRole("button", {
        name: "Approve state",
      }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    ).toBeDisabled();
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
      "http://localhost:8000/api/jobs",
      "http://localhost:8000/api/jobs",
      "http://localhost:8000/api/jobs",
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
      {
        requestId: expect.any(String),
        target: "parsed",
        recommendationRequestId: null,
      },
      {
        requestId: expect.any(String),
        target: "parsed",
        recommendationRequestId: null,
      },
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
      {
        requestId: expect.any(String),
        target: "parsed",
        recommendationRequestId: null,
      },
    ]);
  });

  it("restores a batch archive after stale processing and history reloads", async () => {
    const readyJob = {
      ...recommendedJob(),
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
        url === "http://localhost:8000/api/history" &&
        init?.method === "PUT"
      ) {
        return pendingArchive.promise;
      }
      if (url === "http://localhost:8000/api/jobs") {
        processingReads += 1;
        return Promise.resolve(
          processingQueueResponse(
            archiveCommitted ? [] : [readyJob],
            `archive-processing-${processingReads}`,
          ),
        );
      }
      if (url === "http://localhost:8000/api/history") {
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
        "http://localhost:8000/api/history",
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
      ...recommendedJob(),
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
      if (url === "http://localhost:8000/api/benchmarks") {
        return Promise.resolve(
          jsonResponse(
            benchmarkOverviewForJob(
              benchmarkJobId,
              pristineBenchmark.original_filename,
            ),
          ),
        );
      }
      if (url === `http://localhost:8000/api/jobs/${benchmarkJobId}`) {
        benchmarkReads += 1;
        return Promise.resolve(
          jsonResponse(
            archiveCommitted ? archivedBenchmark : pristineBenchmark,
          ),
        );
      }
      if (
        url === "http://localhost:8000/api/history" &&
        init?.method === "PUT"
      ) {
        return pendingArchive.promise;
      }
      if (url === "http://localhost:8000/api/jobs") {
        processingReads += 1;
        return Promise.resolve(
          processingQueueResponse(
            archiveCommitted ? [] : [readyJob],
            `omitted-archive-processing-${processingReads}`,
          ),
        );
      }
      if (url === "http://localhost:8000/api/history") {
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
        "http://localhost:8000/api/history",
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

  it("restores a persisted provider error after an ordinary recommendation failure", async () => {
    const recommendationRequestId = "11111111-1111-4111-8111-111111111111";
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      recommendationRequestId,
    );
    const approved = {
      ...approvedJob(),
      id: "5".repeat(32),
      original_filename: "ordinary-provider-failure.png",
    };
    const failedJob: JobRecord = {
      ...approved,
      status: "error",
      error: "provider exploded",
      recommendation_request_id: recommendationRequestId,
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([approved]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ detail: "provider exploded" }, 502))
      .mockResolvedValueOnce(
        processingQueueResponse(
          [failedJob],
          "ordinary-provider-failure-snapshot",
        ),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    );

    expect(await screen.findAllByText("provider exploded")).not.toHaveLength(0);
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([failedJob]),
    );
    expect(
      within(
        screen.getByRole("button", {
          name: "Open screenshot 1: ordinary-provider-failure.png",
        }),
      ).getByText("error"),
    ).toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");

    firstRender.unmount();
    render(<App />);

    expect(await screen.findAllByText("provider exploded")).not.toHaveLength(0);
    expect(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    ).toBeEnabled();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      `http://localhost:8000/api/jobs/${approved.id}/recommend`,
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("releases a recommendation lease after another tab wins the conflict", async () => {
    const recommendationRequestId = "44444444-4444-4444-8444-444444444444";
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      recommendationRequestId,
    );
    const approved = {
      ...approvedJob(),
      id: "a".repeat(32),
      original_filename: "competing-recommendation.png",
    };
    const competingAttempt: JobRecord = {
      ...approved,
      recommendation_pending: true,
      recommendation_request_id: "other-tab-attempt",
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([approved]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: "Recommendation is already running",
          },
          409,
        ),
      )
      .mockResolvedValue(
        processingQueueResponse(
          [competingAttempt],
          "competing-recommendation-snapshot",
        ),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    );

    expect(
      await screen.findByText("Recommendation is already running"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([competingAttempt]),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
    expect(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    ).toBeDisabled();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();
    expect(
      fetchMock()
        .mock.calls.slice(0, 2)
        .map(([url]) => url),
    ).toEqual([
      `http://localhost:8000/api/jobs/${approved.id}/recommend`,
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("restores an ordinary recommendation after its successful response is lost", async () => {
    const recommendationRequestId = "22222222-2222-4222-8222-222222222222";
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      recommendationRequestId,
    );
    const approved = {
      ...approvedJob(),
      id: "6".repeat(32),
      original_filename: "ordinary-recommendation-lost.png",
    };
    const persistedRecommendation: JobRecord = {
      ...approved,
      status: "recommended",
      recommendation,
      recommendation_request_id: recommendationRequestId,
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([approved]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockRejectedValueOnce(
        new TypeError("Connection lost after recommendation"),
      )
      .mockResolvedValueOnce(
        processingQueueResponse(
          [persistedRecommendation],
          "ordinary-recommendation-snapshot",
        ),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    );

    expect(
      await screen.findByText("Connection lost after recommendation"),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([persistedRecommendation]),
    );
    expect(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    ).toBeDisabled();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");

    firstRender.unmount();
    render(<App />);

    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    expect(screen.getByText(recommendation.explanation)).toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      `http://localhost:8000/api/jobs/${approved.id}/recommend`,
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("keeps a recommendation lease through an intermediate decision revision", async () => {
    const jobId = "8".repeat(32);
    const recommendationRequestId = "88888888-8888-4888-8888-888888888888";
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      recommendationRequestId,
    );
    const approved = {
      ...approvedJob(),
      id: jobId,
      original_filename: "decision-before-recommendation.png",
    };
    const trainingDecision = {
      action: "call" as const,
      sizing: null,
      certainty: "medium" as const,
      recorded_at: "2026-07-20T12:01:00Z",
    };
    const decisionSaved: JobRecord = {
      ...approved,
      training_decision: trainingDecision,
      updated_at: "2026-07-20T12:01:00Z",
    };
    const recommendationSaved: JobRecord = {
      ...decisionSaved,
      status: "recommended",
      recommendation,
      recommendation_request_id: recommendationRequestId,
      updated_at: "2026-07-20T12:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([approved]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    const pendingRecommendation = deferredResponse();
    const pendingFinalQueue = deferredResponse();
    let processingReads = 0;
    fetchMock().mockImplementation((url, init) => {
      if (url === `http://localhost:8000/api/jobs/${jobId}/decision`) {
        return Promise.resolve(jsonResponse(decisionSaved));
      }
      if (url === `http://localhost:8000/api/jobs/${jobId}/recommend`) {
        expect(init?.headers).toEqual({
          "X-Recommendation-Request-ID": recommendationRequestId,
        });
        return pendingRecommendation.promise;
      }
      if (url === "http://localhost:8000/api/jobs") {
        processingReads += 1;
        return processingReads === 1
          ? Promise.resolve(
              processingQueueResponse(
                [decisionSaved],
                "intermediate-decision-revision",
              ),
            )
          : pendingFinalQueue.promise;
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });
    const firstRender = render(<App />);
    const user = userEvent.setup();
    const decisionPanel = await screen.findByLabelText(
      "Your training decision",
    );

    await user.click(
      within(decisionPanel).getByRole("button", { name: "call" }),
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "medium" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/jobs/${jobId}/recommend`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
    firstRender.unmount();
    render(<App />);

    await waitFor(() => expect(processingReads).toBeGreaterThanOrEqual(2));
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).not.toBeNull();
    expect(screen.queryByLabelText("Recommendation")).not.toBeInTheDocument();

    await act(async () => {
      pendingFinalQueue.resolve(
        processingQueueResponse(
          [recommendationSaved],
          "completed-recommendation-revision",
        ),
      );
      pendingRecommendation.resolve(jsonResponse(recommendationSaved));
      await Promise.all([
        pendingFinalQueue.promise,
        pendingRecommendation.promise,
      ]);
    });

    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
  });

  it("does not arm or start a recommendation when its decision response is lost", async () => {
    const approved = {
      ...approvedJob(),
      id: "d".repeat(32),
      original_filename: "recommend-after-decision-lost.png",
    };
    const persistedDecision: JobRecord = {
      ...approved,
      training_decision: {
        action: "call",
        sizing: null,
        certainty: "medium",
        recorded_at: "2026-07-10T00:01:00Z",
      },
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([approved]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockRejectedValueOnce(
        new TypeError("Connection lost after saving answer"),
      )
      .mockResolvedValueOnce(
        processingQueueResponse(
          [persistedDecision],
          "decision-before-recommendation-snapshot",
        ),
      );
    render(<App />);
    const user = userEvent.setup();
    const decisionPanel = await screen.findByLabelText(
      "Your training decision",
    );

    await user.click(
      within(decisionPanel).getByRole("button", { name: "call" }),
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "medium" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );

    expect(
      await screen.findByText("Connection lost after saving answer"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([persistedDecision]),
    );
    expect(
      await within(screen.getByLabelText("Your training decision")).findByText(
        "Answer locked",
      ),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      `http://localhost:8000/api/jobs/${approved.id}/decision`,
      "http://localhost:8000/api/jobs",
    ]);
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
  });

  it("restores an ordinary training decision after its response is lost", async () => {
    const approved = {
      ...approvedJob(),
      id: "7".repeat(32),
      original_filename: "ordinary-decision-lost.png",
    };
    const persistedDecision: JobRecord = {
      ...approved,
      training_decision: {
        action: "call",
        sizing: null,
        certainty: "medium",
        recorded_at: "2026-07-10T00:01:00Z",
      },
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([approved]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockRejectedValueOnce(
        new TypeError("Connection lost after saving answer"),
      )
      .mockResolvedValueOnce(
        processingQueueResponse(
          [persistedDecision],
          "ordinary-decision-snapshot",
        ),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();
    const decisionPanel = await screen.findByLabelText(
      "Your training decision",
    );

    await user.click(
      within(decisionPanel).getByRole("button", { name: "call" }),
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "medium" }),
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "Lock answer" }),
    );

    expect(
      await screen.findByText("Connection lost after saving answer"),
    ).toBeInTheDocument();
    expect(
      await within(screen.getByLabelText("Your training decision")).findByText(
        "Answer locked",
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([persistedDecision]),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");

    firstRender.unmount();
    render(<App />);

    const restoredDecisionPanel = await screen.findByLabelText(
      "Your training decision",
    );
    expect(
      within(restoredDecisionPanel).getByText("Answer locked"),
    ).toBeInTheDocument();
    expect(
      within(restoredDecisionPanel).getByRole("button", {
        name: "medium",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      `http://localhost:8000/api/jobs/${approved.id}/decision`,
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("releases a training-decision lease after a deterministic conflict", async () => {
    const approved = {
      ...approvedJob(),
      id: "8".repeat(32),
      original_filename: "decision-conflict.png",
    };
    const competingRecommendation: JobRecord = {
      ...approved,
      status: "recommended",
      recommendation,
      recommendation_request_id: "other-tab-recommendation",
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([approved]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail:
              "Your decision must be recorded before revealing the recommendation",
          },
          409,
        ),
      )
      .mockResolvedValueOnce(
        processingQueueResponse(
          [competingRecommendation],
          "decision-conflict-snapshot",
        ),
      );
    render(<App />);
    const user = userEvent.setup();
    const decisionPanel = await screen.findByLabelText(
      "Your training decision",
    );

    await user.click(
      within(decisionPanel).getByRole("button", { name: "call" }),
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "medium" }),
    );
    await user.click(
      within(decisionPanel).getByRole("button", {
        name: "Lock answer",
      }),
    );

    expect(
      await screen.findByText(
        "Your decision must be recorded before revealing the recommendation",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByLabelText("Recommendation")).toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
  });

  it.each([{ scope: "processing" as const }, { scope: "history" as const }])(
    "releases a $scope review lease after a deterministic conflict",
    async ({ scope }) => {
      const jobId = scope === "processing" ? "3".repeat(32) : "4".repeat(32);
      const archivedAt = scope === "history" ? "2026-07-20T12:00:00Z" : null;
      const reviewedCandidate: JobRecord = {
        ...recommendedJob(),
        id: jobId,
        original_filename: `${scope}-review-conflict.png`,
        archived_at: archivedAt,
        training_decision: {
          action: "call",
          sizing: null,
          certainty: "medium",
          recorded_at: "2026-07-20T12:01:00Z",
        },
      };
      const competingApproval: JobRecord = {
        ...reviewedCandidate,
        status: "approved",
        approved_state: canonicalState({ pot_size: 20 }),
        recommendation: null,
        recommendation_request_id: null,
        training_decision: null,
        updated_at: "2026-07-20T12:02:00Z",
      };
      if (scope === "processing") {
        window.localStorage.setItem(
          "poker-training-processing-v1",
          JSON.stringify([reviewedCandidate]),
        );
        window.localStorage.setItem("poker-training-processing-total-v1", "1");
      } else {
        window.localStorage.setItem("poker-training-processing-v1", "[]");
        window.localStorage.setItem("poker-training-processing-total-v1", "0");
        window.sessionStorage.setItem(
          "poker-training-processing-synced",
          "true",
        );
        window.localStorage.setItem(
          "poker-training-history-v1",
          JSON.stringify([
            {
              id: jobId,
              job: reviewedCandidate,
              savedAt: archivedAt,
            },
          ]),
        );
        window.localStorage.setItem("poker-training-history-total-v1", "1");
      }
      fetchMock()
        .mockResolvedValueOnce(
          jsonResponse(
            {
              detail: "Approve the current state before completing review",
            },
            409,
          ),
        )
        .mockResolvedValueOnce(
          scope === "processing"
            ? processingQueueResponse(
                [competingApproval],
                "review-conflict-snapshot",
              )
            : jsonResponse({
                total: 1,
                jobs: [competingApproval],
                snapshot_version: "archived-review-conflict-snapshot",
              }),
        );
      render(<App />);
      const user = userEvent.setup();

      if (scope === "history") {
        await user.click(
          screen.getByRole("button", {
            name: "Reopen history item 1",
          }),
        );
      }
      const comparison = await screen.findByLabelText(
        "Training decision comparison",
      );
      await user.click(
        within(comparison).getByRole("button", {
          name: "Mark reviewed",
        }),
      );

      expect(
        await screen.findByText(
          "Approve the current state before completing review",
        ),
      ).toBeInTheDocument();
      const cacheKey =
        scope === "processing"
          ? "poker-training-processing-v1"
          : "poker-training-history-v1";
      await waitFor(() => {
        const cached = JSON.parse(
          String(window.localStorage.getItem(cacheKey)),
        );
        const cachedJob = scope === "processing" ? cached[0] : cached[0].job;
        expect(cachedJob).toEqual(competingApproval);
      });
      expect(
        window.sessionStorage.getItem(`poker-training-${scope}-mutation-v1`),
      ).toBeNull();
    },
  );

  it.each([
    { operation: "approval" as const },
    { operation: "recommendation" as const },
    { operation: "decision" as const },
    { operation: "review" as const },
  ])(
    "restores an archived $operation after its response is lost",
    async ({ operation }) => {
      const jobId = "9".repeat(32);
      const archivedAt = "2026-07-20T12:00:00Z";
      const trainingDecision = {
        action: "call" as const,
        sizing: null,
        certainty: "medium" as const,
        recorded_at: "2026-07-20T12:01:00Z",
      };
      const parsedArchivedJob = jobRecord({
        id: jobId,
        original_filename: `archived-${operation}-response-lost.png`,
        image_filename: `${jobId}.png`,
        archived_at: archivedAt,
      });
      const approvedArchivedJob: JobRecord = {
        ...approvedJob(),
        id: jobId,
        original_filename: parsedArchivedJob.original_filename,
        image_filename: `${jobId}.png`,
        archived_at: archivedAt,
      };
      const reviewedArchivedJob: JobRecord = {
        ...recommendedJob(),
        id: jobId,
        original_filename: parsedArchivedJob.original_filename,
        image_filename: `${jobId}.png`,
        training_decision: trainingDecision,
        archived_at: archivedAt,
      };
      let initialJob: JobRecord;
      let persistedJob: JobRecord;
      if (operation === "approval") {
        initialJob = parsedArchivedJob;
        persistedJob = {
          ...parsedArchivedJob,
          status: "approved",
          approved_state: canonicalState({ pot_size: 20 }),
          updated_at: "2026-07-20T12:10:00Z",
        };
      } else if (operation === "recommendation") {
        const recommendationRequestId = "33333333-3333-4333-8333-333333333333";
        vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
          recommendationRequestId,
        );
        initialJob = approvedArchivedJob;
        persistedJob = {
          ...approvedArchivedJob,
          status: "recommended",
          recommendation,
          recommendation_request_id: recommendationRequestId,
          updated_at: "2026-07-20T12:10:00Z",
        };
      } else if (operation === "decision") {
        initialJob = approvedArchivedJob;
        persistedJob = {
          ...approvedArchivedJob,
          training_decision: trainingDecision,
          updated_at: "2026-07-20T12:10:00Z",
        };
      } else {
        initialJob = reviewedArchivedJob;
        persistedJob = {
          ...reviewedArchivedJob,
          training_reviewed_at: "2026-07-20T12:10:00Z",
          training_review_note: "Persisted archived lesson.",
          updated_at: "2026-07-20T12:10:00Z",
        };
      }
      window.localStorage.setItem(
        "poker-training-history-v1",
        JSON.stringify([{ id: jobId, job: initialJob, savedAt: archivedAt }]),
      );
      window.localStorage.setItem("poker-training-history-total-v1", "1");
      fetchMock()
        .mockRejectedValueOnce(
          new TypeError(`Connection lost after archived ${operation}`),
        )
        .mockResolvedValueOnce(jsonResponse(persistedJob));
      const firstRender = render(<App />);
      const user = userEvent.setup();

      await user.click(
        screen.getByRole("button", {
          name: "Reopen history item 1",
        }),
      );
      if (operation === "approval") {
        const potInput = await screen.findByDisplayValue("12.5");
        await user.clear(potInput);
        await user.type(potInput, "20");
        await user.click(screen.getByRole("button", { name: "Approve state" }));
      } else if (operation === "recommendation") {
        await user.click(
          screen.getByRole("button", {
            name: "Request recommendation",
          }),
        );
      } else if (operation === "decision") {
        const decisionPanel = await screen.findByLabelText(
          "Your training decision",
        );
        await user.click(
          within(decisionPanel).getByRole("button", { name: "call" }),
        );
        await user.click(
          within(decisionPanel).getByRole("button", { name: "medium" }),
        );
        await user.click(
          within(decisionPanel).getByRole("button", { name: "Lock answer" }),
        );
      } else {
        const comparison = await screen.findByLabelText(
          "Training decision comparison",
        );
        await user.type(
          screen.getByLabelText("Training review note"),
          "Persisted archived lesson.",
        );
        await user.click(
          within(comparison).getByRole("button", {
            name: "Mark reviewed",
          }),
        );
      }

      expect(
        await screen.findByText(`Connection lost after archived ${operation}`),
      ).toBeInTheDocument();
      await waitFor(() =>
        expect(
          JSON.parse(
            String(window.localStorage.getItem("poker-training-history-v1")),
          )[0].job,
        ).toEqual(persistedJob),
      );
      expect(
        window.sessionStorage.getItem("poker-training-history-synced"),
      ).toBe("true");
      if (operation === "approval") {
        expect(await screen.findByDisplayValue("20")).toBeInTheDocument();
        expect(
          screen.getByRole("button", { name: "Approve state" }),
        ).toBeDisabled();
      } else if (operation === "recommendation") {
        expect(
          await screen.findByLabelText("Recommendation"),
        ).toBeInTheDocument();
      } else if (operation === "decision") {
        expect(
          await within(
            screen.getByLabelText("Your training decision"),
          ).findByText("Answer locked"),
        ).toBeInTheDocument();
      } else {
        const comparison = await screen.findByLabelText(
          "Training decision comparison",
        );
        expect(within(comparison).getByText("Reviewed")).toBeInTheDocument();
        expect(
          screen.getByLabelText("Saved training review note"),
        ).toHaveTextContent("Persisted archived lesson.");
      }

      firstRender.unmount();
      render(<App />);
      await user.click(
        await screen.findByRole("button", {
          name: "Reopen history item 1",
        }),
      );

      if (operation === "approval") {
        expect(await screen.findByDisplayValue("20")).toBeInTheDocument();
      } else if (operation === "recommendation") {
        expect(
          await screen.findByLabelText("Recommendation"),
        ).toBeInTheDocument();
      } else if (operation === "decision") {
        expect(
          await within(
            screen.getByLabelText("Your training decision"),
          ).findByText("Answer locked"),
        ).toBeInTheDocument();
      } else {
        expect(
          await screen.findByLabelText("Saved training review note"),
        ).toHaveTextContent("Persisted archived lesson.");
      }
      const mutationPath =
        operation === "approval"
          ? "approve"
          : operation === "decision"
            ? "decision"
            : operation === "review"
              ? "training-review"
              : "recommend";
      expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
        `http://localhost:8000/api/jobs/${jobId}/${mutationPath}`,
        `http://localhost:8000/api/jobs/${jobId}`,
      ]);
    },
  );

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
        "http://localhost:8000/api/jobs",
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
      ...recommendedJob(),
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
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
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
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
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
      "http://localhost:8000/api/jobs",
      "http://localhost:8000/api/jobs?offset=100",
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
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
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
          "http://localhost:8000/api/jobs",
          { credentials: "include" },
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
