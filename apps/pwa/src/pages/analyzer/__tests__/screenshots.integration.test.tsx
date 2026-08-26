import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  AnalyzerTestApp as App,
  approvedJob,
  deferredResponse,
  disableAutomation,
  fetchMock,
  jobRecord,
  jsonResponse,
  processingQueueResponse,
  recommendation,
  recommendedJob,
  switchToUploadMode,
} from "../../../test/analyzerHarness";

describe("Analyzer screenshot management", () => {
  it("restores the processing queue immediately from the browser cache", async () => {
    const cachedJob = jobRecord({
      id: "a".repeat(32),
      original_filename: "cached-table.png",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([cachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");

    render(<App />);

    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 1: cached-table.png",
      }),
    ).toBeInTheDocument();
    expect(screen.getByDisplayValue("Ah Kd")).toBeInTheDocument();
    expect(fetchMock()).not.toHaveBeenCalled();
  });

  it("edits screenshot details from the processing queue", async () => {
    const cachedJob = jobRecord({
      id: "1".repeat(32),
      original_filename: "untitled-table.png",
    });
    const updatedJob = {
      ...cachedJob,
      title: "Turn bluff review",
      notes: "Check the smaller sizing.",
      tags: ["turn", "bluff"],
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([cachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockResolvedValueOnce(jsonResponse(updatedJob));
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: untitled-table.png",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Screenshot details" });
    await user.type(
      within(dialog).getByLabelText("Title"),
      "Turn bluff review",
    );
    await user.type(within(dialog).getByLabelText("Tags"), "turn, bluff, TURN");
    await user.type(
      within(dialog).getByLabelText("Notes"),
      "Check the smaller sizing.",
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Save details" }),
    );

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/jobs/${cachedJob.id}/metadata`,
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({
            title: "Turn bluff review",
            notes: "Check the smaller sizing.",
            tags: ["turn", "bluff"],
          }),
        }),
      ),
    );
    expect(await screen.findAllByText("Turn bluff review")).toHaveLength(2);
  });

  it("moves a metadata response archived by another client into history", async () => {
    const cachedJob = jobRecord({
      id: "4".repeat(32),
      original_filename: "cross-tab-table.png",
    });
    const archivedJob = {
      ...cachedJob,
      title: "Archived elsewhere",
      archived_at: "2026-07-10T00:02:00Z",
      updated_at: "2026-07-10T00:03:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([cachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(archivedJob))
      .mockResolvedValueOnce(
        jsonResponse({
          total: 1,
          jobs: [archivedJob],
          snapshot_version: "archived-metadata-snapshot",
        }),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: cross-tab-table.png",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Screenshot details" });
    await user.type(
      within(dialog).getByLabelText("Title"),
      "Archived elsewhere",
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Save details" }),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "Open screenshot 1: cross-tab-table.png",
        }),
      ).not.toBeInTheDocument(),
    );
    expect(
      await screen.findByRole("button", {
        name: "Manage history item 1: cross-tab-table.png",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("dialog", { name: "Screenshot details" }),
    ).not.toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledWith(
      "http://localhost:8000/api/history",
      { credentials: "include" },
    );
  });

  it("permanently removes an unarchivable screenshot from the queue", async () => {
    const failedJob = jobRecord({
      id: "2".repeat(32),
      status: "error",
      original_filename: "wrong-table.png",
      parser_result: null,
      error: "Table cards are missing",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([failedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockResolvedValueOnce(new Response(null, { status: 204 }));
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: wrong-table.png",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Screenshot details" });
    await user.click(
      within(dialog).getByRole("button", { name: "Delete screenshot" }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Delete permanently" }),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "Open screenshot 1: wrong-table.png",
        }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText("No screenshots uploaded or captured yet"),
    ).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledWith(
      `http://localhost:8000/api/jobs/${failedJob.id}`,
      { method: "DELETE", credentials: "include" },
    );
  });

  it("allows deleting a screenshot with an external recommendation pending", async () => {
    const pendingJob = approvedJob();
    pendingJob.id = "5".repeat(32);
    pendingJob.original_filename = "stuck-recommendation.png";
    pendingJob.recommendation_pending = true;
    pendingJob.recommendation_request_id = "external-request";
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([pendingJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(processingQueueResponse([pendingJob]))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    render(<App />);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
      ),
    );
    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: stuck-recommendation.png",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Screenshot details" });
    const armDelete = within(dialog).getByRole("button", {
      name: "Delete screenshot",
    });
    expect(armDelete).toBeEnabled();
    await user.click(armDelete);
    const confirmDelete = within(dialog).getByRole("button", {
      name: "Delete permanently",
    });
    expect(confirmDelete).toBeEnabled();
    await user.click(confirmDelete);

    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "Open screenshot 1: stuck-recommendation.png",
        }),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock()).toHaveBeenCalledWith(
      `http://localhost:8000/api/jobs/${pendingJob.id}`,
      { method: "DELETE", credentials: "include" },
    );
  });

  it("allows saving screenshot details with an external recommendation pending", async () => {
    const pendingJob = approvedJob();
    pendingJob.id = "6".repeat(32);
    pendingJob.original_filename = "pending-details.png";
    pendingJob.recommendation_pending = true;
    pendingJob.recommendation_request_id = "external-request";
    const updatedJob = {
      ...pendingJob,
      title: "Provider still running",
      updated_at: "2026-07-10T00:01:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([pendingJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(processingQueueResponse([pendingJob]))
      .mockResolvedValueOnce(jsonResponse(updatedJob));
    render(<App />);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
      ),
    );
    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: pending-details.png",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Screenshot details" });
    await user.type(
      within(dialog).getByLabelText("Title"),
      "Provider still running",
    );
    const saveDetails = within(dialog).getByRole("button", {
      name: "Save details",
    });
    expect(saveDetails).toBeEnabled();
    await user.click(saveDetails);

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/jobs/${pendingJob.id}/metadata`,
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({
            title: "Provider still running",
            notes: null,
            tags: [],
          }),
        }),
      ),
    );
  });

  it.each([
    { projection: "queue", archivedAt: null },
    { projection: "history", archivedAt: "2026-07-10T00:02:00Z" },
  ])(
    "removes a stale $projection screenshot after metadata returns 404",
    async ({ archivedAt }) => {
      const missingJob = approvedJob();
      missingJob.id = "5".repeat(32);
      missingJob.original_filename = "deleted-in-another-tab.png";
      missingJob.archived_at = archivedAt;
      if (archivedAt === null) {
        window.localStorage.setItem(
          "poker-training-processing-v1",
          JSON.stringify([missingJob]),
        );
        window.localStorage.setItem("poker-training-processing-total-v1", "1");
      } else {
        window.localStorage.setItem(
          "poker-training-history-v1",
          JSON.stringify([
            {
              id: missingJob.id,
              job: missingJob,
              savedAt: archivedAt,
            },
          ]),
        );
        window.localStorage.setItem("poker-training-history-total-v1", "1");
      }
      fetchMock().mockImplementation((url, options) => {
        if (
          url === `http://localhost:8000/api/jobs/${missingJob.id}/metadata`
        ) {
          return Promise.resolve(
            jsonResponse({ detail: "Job not found" }, 404),
          );
        }
        if (url === "http://localhost:8000/api/jobs") {
          return Promise.resolve(processingQueueResponse([]));
        }
        if (url === "http://localhost:8000/api/history") {
          return Promise.resolve(
            jsonResponse({
              total: 0,
              jobs: [],
              snapshot_version: "history-after-remote-delete",
            }),
          );
        }
        throw new Error(
          `Unexpected request: ${String(url)} ${String(options?.method)}`,
        );
      });
      render(<App />);
      const user = userEvent.setup();

      await user.click(
        screen.getByRole("button", {
          name:
            archivedAt === null
              ? "Manage screenshot 1: deleted-in-another-tab.png"
              : "Manage history item 1: deleted-in-another-tab.png",
        }),
      );
      const dialog = screen.getByRole("dialog", { name: "Screenshot details" });
      await user.type(within(dialog).getByLabelText("Title"), "Missing hand");
      await user.click(
        within(dialog).getByRole("button", { name: "Save details" }),
      );

      expect(
        await screen.findByText("Screenshot was already deleted elsewhere"),
      ).toBeInTheDocument();
      await waitFor(() =>
        expect(
          screen.queryByRole("dialog", {
            name: "Screenshot details",
          }),
        ).not.toBeInTheDocument(),
      );
      await waitFor(() =>
        expect(fetchMock()).toHaveBeenCalledWith(
          "http://localhost:8000/api/jobs",
          { credentials: "include" },
        ),
      );
      await waitFor(() =>
        expect(fetchMock()).toHaveBeenCalledWith(
          "http://localhost:8000/api/history",
          { credentials: "include" },
        ),
      );
      expect(
        screen.getByText("No screenshots uploaded or captured yet"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Cleared reviewed hands will appear here."),
      ).toBeInTheDocument();
    },
  );

  it("keeps queue and history management reachable during a recommendation request", async () => {
    const queueJob = approvedJob();
    queueJob.id = "7".repeat(32);
    queueJob.original_filename = "active-recommendation.png";
    const archivedJob = recommendedJob();
    archivedJob.id = "8".repeat(32);
    archivedJob.original_filename = "saved-during-recommendation.png";
    archivedJob.archived_at = "2026-07-10T00:02:00Z";
    const completedJob = {
      ...recommendedJob(),
      id: queueJob.id,
      original_filename: queueJob.original_filename,
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([queueJob]),
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
    const pendingRecommendation = deferredResponse();
    fetchMock().mockReturnValueOnce(pendingRecommendation.promise);
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/jobs/${queueJob.id}/recommend`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const manageQueue = screen.getByRole("button", {
      name: "Manage screenshot 1: active-recommendation.png",
    });
    const manageHistory = screen.getByRole("button", {
      name: "Manage history item 1: saved-during-recommendation.png",
    });
    expect(manageQueue).toBeEnabled();
    expect(manageHistory).toBeEnabled();

    await user.click(manageQueue);
    expect(
      screen.getByRole("dialog", { name: "Screenshot details" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.click(manageHistory);
    expect(
      screen.getByRole("dialog", { name: "Screenshot details" }),
    ).toBeInTheDocument();

    await act(async () => {
      pendingRecommendation.resolve(jsonResponse(completedJob));
      await pendingRecommendation.promise;
    });
  });

  it("saves metadata during a same-tab recommendation without losing it to a stale response", async () => {
    const queueJob = approvedJob();
    queueJob.id = "9".repeat(32);
    queueJob.original_filename = "edit-while-solving.png";
    queueJob.updated_at = "2026-07-10T00:01:00Z";
    const recommendationResponse = {
      ...recommendedJob(),
      id: queueJob.id,
      original_filename: queueJob.original_filename,
      title: null,
      notes: null,
      tags: [],
      updated_at: "2026-07-10T00:02:00Z",
    };
    const metadataResponse = {
      ...recommendationResponse,
      title: "Edited while solving",
      updated_at: "2026-07-10T00:03:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([queueJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    const pendingRecommendation = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingRecommendation.promise)
      .mockResolvedValueOnce(jsonResponse(metadataResponse));
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: edit-while-solving.png",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Screenshot details" });
    await user.type(
      within(dialog).getByLabelText("Title"),
      "Edited while solving",
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Save details" }),
    );

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/jobs/${queueJob.id}/metadata`,
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({
            title: "Edited while solving",
            notes: null,
            tags: [],
          }),
        }),
      ),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).not.toBeNull();

    await act(async () => {
      pendingRecommendation.resolve(jsonResponse(recommendationResponse));
      await pendingRecommendation.promise;
    });

    const queueItem = screen.getByRole("button", {
      name: "Open screenshot 1: edit-while-solving.png",
    });
    expect(
      within(queueItem).getByText("Edited while solving"),
    ).toBeInTheDocument();
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      )[0].title,
    ).toBe("Edited while solving");
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
  });

  it("deletes a screenshot during a same-tab recommendation and cancels its response", async () => {
    const queueJob = approvedJob();
    queueJob.id = "a".repeat(32);
    queueJob.original_filename = "delete-while-solving.png";
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([queueJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    let recommendationAborted = false;
    fetchMock()
      .mockImplementationOnce((_url, options) => {
        const signal = options?.signal as AbortSignal | undefined;
        return new Promise<Response>((_resolve, reject) => {
          if (signal?.aborted) {
            recommendationAborted = true;
            reject(new DOMException("Aborted", "AbortError"));
            return;
          }
          signal?.addEventListener(
            "abort",
            () => {
              recommendationAborted = true;
              reject(new DOMException("Aborted", "AbortError"));
            },
            { once: true },
          );
        });
      })
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: delete-while-solving.png",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Screenshot details" });
    await user.click(
      within(dialog).getByRole("button", { name: "Delete screenshot" }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Delete permanently" }),
    );

    await waitFor(() => expect(recommendationAborted).toBe(true));
    expect(
      screen.getByText("No screenshots uploaded or captured yet"),
    ).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledWith(
      `http://localhost:8000/api/jobs/${queueJob.id}`,
      { method: "DELETE", credentials: "include" },
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
    expect(
      screen.queryByText(
        "Finishing recovery from a previous action. Try again in a moment.",
      ),
    ).not.toBeInTheDocument();
  });

  it("preserves delete recovery until an unrelated recommendation finishes", async () => {
    const recommendationJob = approvedJob();
    recommendationJob.id = "b".repeat(32);
    recommendationJob.original_filename = "solver-still-running.png";
    const deletedJob = approvedJob();
    deletedJob.id = "d".repeat(32);
    deletedJob.original_filename = "delete-response-lost.png";
    const recommendedJobA = {
      ...recommendedJob(),
      id: recommendationJob.id,
      original_filename: recommendationJob.original_filename,
      updated_at: "2026-07-10T00:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([recommendationJob, deletedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "2");
    const pendingRecommendation = deferredResponse();
    fetchMock().mockImplementation((url, options) => {
      if (
        url ===
        `http://localhost:8000/api/jobs/${recommendationJob.id}/recommend`
      ) {
        return pendingRecommendation.promise;
      }
      if (
        url === `http://localhost:8000/api/jobs/${deletedJob.id}` &&
        options?.method === "DELETE"
      ) {
        return Promise.reject(new TypeError("Connection lost after delete"));
      }
      if (url === "http://localhost:8000/api/jobs") {
        return Promise.resolve(
          processingQueueResponse(
            [recommendedJobA],
            "queue-after-lost-delete-response",
          ),
        );
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 2: delete-response-lost.png",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Screenshot details" });
    await user.click(
      within(dialog).getByRole("button", { name: "Delete screenshot" }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Delete permanently" }),
    );

    expect(
      await screen.findByText("Connection lost after delete"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 2: delete-response-lost.png",
      }),
    ).toBeInTheDocument();

    await act(async () => {
      pendingRecommendation.resolve(jsonResponse(recommendedJobA));
      await pendingRecommendation.promise;
    });

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
      ),
    );
    await waitFor(() =>
      expect(
        screen.queryByText("delete-response-lost.png"),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Recommendation")).toBeInTheDocument();
  });

  it("reconciles an ambiguous upload before allowing permanent deletion", async () => {
    const persistedJob = jobRecord({
      id: "c".repeat(32),
      original_filename: "lost-upload-delete.png",
    });
    const pendingQueue = deferredResponse();
    let uploadRequestId = "";
    let persistedDeleted = false;
    fetchMock().mockImplementation((url, options) => {
      if (
        url === "http://localhost:8000/api/jobs" &&
        options?.method === "POST"
      ) {
        uploadRequestId = String(
          (options.body as FormData).get("upload_request_id"),
        );
        return Promise.reject(new TypeError("Connection lost after upload"));
      }
      if (url === "http://localhost:8000/api/jobs") {
        return persistedDeleted
          ? Promise.resolve(processingQueueResponse([]))
          : pendingQueue.promise;
      }
      if (
        url === `http://localhost:8000/api/jobs/${persistedJob.id}` &&
        options?.method === "DELETE"
      ) {
        persistedDeleted = true;
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      if (url === "http://localhost:8000/api/history") {
        return Promise.resolve(
          jsonResponse({
            total: 0,
            jobs: [],
            snapshot_version: "history-after-recovered-upload-delete",
          }),
        );
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });
    render(<App />);
    const user = userEvent.setup();

    await disableAutomation(user);
    await switchToUploadMode(user);
    await user.upload(
      screen.getByLabelText("Choose screenshots"),
      new File(["upload"], persistedJob.original_filename, {
        type: "image/png",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));

    await user.click(
      await screen.findByRole("button", {
        name: `Manage screenshot 1: ${persistedJob.original_filename}`,
      }),
    );
    let dialog = screen.getByRole("dialog", { name: "Screenshot details" });
    expect(
      within(dialog).getByText(
        "Checking whether this upload reached persistent storage before deletion.",
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Delete screenshot",
      }),
    ).toBeDisabled();
    expect(fetchMock()).not.toHaveBeenCalledWith(
      expect.stringContaining(persistedJob.id),
      expect.objectContaining({ method: "DELETE" }),
    );

    await act(async () => {
      pendingQueue.resolve(
        processingQueueResponse(
          [{ ...persistedJob, upload_request_id: uploadRequestId }],
          "recovered-upload-before-delete",
        ),
      );
      await pendingQueue.promise;
    });

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", {
          name: "Screenshot details",
        }),
      ).not.toBeInTheDocument(),
    );
    await user.click(
      screen.getByRole("button", {
        name: `Manage screenshot 1: ${persistedJob.original_filename}`,
      }),
    );
    dialog = screen.getByRole("dialog", { name: "Screenshot details" });
    expect(within(dialog).getByLabelText("Title")).toBeInTheDocument();
    await user.click(
      within(dialog).getByRole("button", { name: "Delete screenshot" }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Delete permanently" }),
    );

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/jobs/${persistedJob.id}`,
        { method: "DELETE", credentials: "include" },
      ),
    );
    expect(
      screen.getByText("No screenshots uploaded or captured yet"),
    ).toBeInTheDocument();
  });

  it("reconciles history after deleting a queue record archived by another tab", async () => {
    const jobId = "d".repeat(32);
    const staleQueueJob = recommendedJob();
    staleQueueJob.id = jobId;
    staleQueueJob.original_filename = "archived-during-delete.png";
    const archivedVersion = {
      ...staleQueueJob,
      archived_at: "2026-07-10T00:03:00Z",
      updated_at: "2026-07-10T00:03:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([staleQueueJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: jobId,
          job: archivedVersion,
          savedAt: archivedVersion.archived_at,
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    fetchMock().mockImplementation((url, options) => {
      if (
        url === `http://localhost:8000/api/jobs/${jobId}` &&
        options?.method === "DELETE"
      ) {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      if (url === "http://localhost:8000/api/history") {
        return Promise.resolve(
          jsonResponse({
            total: 0,
            jobs: [],
            snapshot_version: "history-after-concurrent-delete",
          }),
        );
      }
      if (url === "http://localhost:8000/api/jobs") {
        return Promise.resolve(processingQueueResponse([]));
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: archived-during-delete.png",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Screenshot details" });
    await user.click(
      within(dialog).getByRole("button", { name: "Delete screenshot" }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Delete permanently" }),
    );

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/history",
        { credentials: "include" },
      ),
    );
    await waitFor(() =>
      expect(
        window.localStorage.getItem("poker-training-history-total-v1"),
      ).toBe("0"),
    );
    expect(
      screen.getByText("No screenshots uploaded or captured yet"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Cleared reviewed hands will appear here."),
    ).toBeInTheDocument();
  });

  it("keeps the newest benchmark count after deleting labeled screenshots", async () => {
    const firstBenchmarkJob = approvedJob();
    firstBenchmarkJob.id = "d".repeat(32);
    firstBenchmarkJob.original_filename = "first-benchmark-label.png";
    firstBenchmarkJob.benchmark_included = true;
    const secondBenchmarkJob = approvedJob();
    secondBenchmarkJob.id = "e".repeat(32);
    secondBenchmarkJob.original_filename = "second-benchmark-label.png";
    secondBenchmarkJob.benchmark_included = true;
    const benchmarkJobs = [firstBenchmarkJob, secondBenchmarkJob];
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify(benchmarkJobs),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "2");
    const firstDeletionOverview = deferredResponse();
    const secondDeletionOverview = deferredResponse();
    const deletedIds = new Set<string>();
    let benchmarkReads = 0;
    fetchMock().mockImplementation((url, options) => {
      if (url === "http://localhost:8000/api/benchmarks") {
        benchmarkReads += 1;
        if (benchmarkReads === 1) {
          return Promise.resolve(
            jsonResponse({
              included_cases: 2,
              latest_report: null,
              recent_reports: [],
            }),
          );
        }
        return benchmarkReads === 2
          ? firstDeletionOverview.promise
          : secondDeletionOverview.promise;
      }
      const deletedJob = benchmarkJobs.find(
        (candidate) => url === `http://localhost:8000/api/jobs/${candidate.id}`,
      );
      if (deletedJob && options?.method === "DELETE") {
        deletedIds.add(deletedJob.id);
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      if (url === "http://localhost:8000/api/jobs") {
        return Promise.resolve(
          processingQueueResponse(
            benchmarkJobs.filter((candidate) => !deletedIds.has(candidate.id)),
          ),
        );
      }
      if (url === "http://localhost:8000/api/history") {
        return Promise.resolve(
          jsonResponse({
            total: 0,
            jobs: [],
            snapshot_version: "history-after-benchmark-delete",
          }),
        );
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const benchmarkDialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await waitFor(() =>
      expect(benchmarkDialog).toHaveTextContent("2 ground-truth hands"),
    );
    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: first-benchmark-label.png",
      }),
    );
    let detailsDialog = screen.getByRole("dialog", {
      name: "Screenshot details",
    });
    await user.click(
      within(detailsDialog).getByRole("button", {
        name: "Delete screenshot",
      }),
    );
    await user.click(
      within(detailsDialog).getByRole("button", {
        name: "Delete permanently",
      }),
    );
    await waitFor(() => expect(benchmarkReads).toBe(2));

    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: second-benchmark-label.png",
      }),
    );
    detailsDialog = screen.getByRole("dialog", { name: "Screenshot details" });
    await user.click(
      within(detailsDialog).getByRole("button", {
        name: "Delete screenshot",
      }),
    );
    await user.click(
      within(detailsDialog).getByRole("button", {
        name: "Delete permanently",
      }),
    );
    await waitFor(() => expect(benchmarkReads).toBe(3));

    secondDeletionOverview.resolve(
      jsonResponse({
        included_cases: 0,
        latest_report: null,
        recent_reports: [],
      }),
    );
    await secondDeletionOverview.promise;
    await waitFor(() =>
      expect(benchmarkDialog).toHaveTextContent("0 ground-truth hands"),
    );
    firstDeletionOverview.resolve(
      jsonResponse({
        included_cases: 1,
        latest_report: null,
        recent_reports: [],
      }),
    );
    await firstDeletionOverview.promise;

    expect(benchmarkDialog).toHaveTextContent("0 ground-truth hands");
    expect(benchmarkDialog).not.toHaveTextContent("1 ground-truth hand");
    expect(
      screen.getByText("No screenshots uploaded or captured yet"),
    ).toBeInTheDocument();
  });

  it("ignores a stale deletion refresh after the parser pipeline changes", async () => {
    const staleBenchmarkJob = approvedJob();
    staleBenchmarkJob.id = "e".repeat(32);
    staleBenchmarkJob.original_filename = "stale-delete-refresh.png";
    staleBenchmarkJob.benchmark_included = true;
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([staleBenchmarkJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    const deletionOverview = deferredResponse();
    const selectedOverview = deferredResponse();
    fetchMock().mockImplementation((url, options) => {
      if (url === "http://localhost:8000/api/benchmarks") {
        return deletionOverview.promise;
      }
      if (
        url ===
        "http://localhost:8000/api/benchmarks?parser_provider=ocr_cv&parser_layout_profile=fortuna"
      ) {
        return selectedOverview.promise;
      }
      if (url === "http://localhost:8000/api/pipeline") {
        return Promise.resolve(
          jsonResponse({
            defaults: {
              parser_provider: "mock",
              parser_layout_profile: "generic",
              recommendation_provider: "mock",
              recommendation_engine: null,
            },
            parser_providers: [
              {
                id: "mock",
                label: "Mock parser",
                available: true,
                unavailable_reason: null,
              },
              {
                id: "ocr_cv",
                label: "Template OCR",
                available: true,
                unavailable_reason: null,
              },
            ],
            parser_layout_profiles: [
              {
                id: "generic",
                label: "Generic",
                available: true,
                unavailable_reason: null,
              },
              {
                id: "fortuna",
                label: "Fortuna",
                available: true,
                unavailable_reason: null,
              },
            ],
            parser_layout_compatibility: {
              mock: ["generic", "fortuna"],
              ocr_cv: ["generic", "fortuna"],
            },
            recommendation_providers: [
              {
                id: "mock",
                label: "Mock recommendation",
                available: true,
                unavailable_reason: null,
              },
            ],
            recommendation_engines: [],
          }),
        );
      }
      if (
        url === `http://localhost:8000/api/jobs/${staleBenchmarkJob.id}` &&
        options?.method === "DELETE"
      ) {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      if (url === "http://localhost:8000/api/jobs") {
        return Promise.resolve(processingQueueResponse([]));
      }
      if (url === "http://localhost:8000/api/history") {
        return Promise.resolve(
          jsonResponse({
            total: 0,
            jobs: [],
            snapshot_version: "history-after-stale-benchmark-refresh",
          }),
        );
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: stale-delete-refresh.png",
      }),
    );
    const detailsDialog = screen.getByRole("dialog", {
      name: "Screenshot details",
    });
    await user.click(
      within(detailsDialog).getByRole("button", {
        name: "Delete screenshot",
      }),
    );
    await user.click(
      within(detailsDialog).getByRole("button", {
        name: "Delete permanently",
      }),
    );
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/benchmarks",
        { credentials: "include" },
      ),
    );

    await user.click(
      screen.getByRole("button", { name: "Configure analysis plugins" }),
    );
    const pipelineDialog = await screen.findByRole("dialog", {
      name: "Analysis plugins",
    });
    await user.selectOptions(
      within(pipelineDialog).getByLabelText("Recognition"),
      "ocr_cv",
    );
    await user.selectOptions(
      within(pipelineDialog).getByLabelText("Table layout"),
      "fortuna",
    );
    await user.click(
      within(pipelineDialog).getByRole("button", { name: "Done" }),
    );
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const benchmarkDialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });

    selectedOverview.resolve(
      jsonResponse({
        included_cases: 9,
        included_cases_by_layout: { fortuna: 9 },
        default_layout_profile: "generic",
        latest_report: null,
        recent_reports: [],
      }),
    );
    await waitFor(() =>
      expect(benchmarkDialog).toHaveTextContent("9 ground-truth hands"),
    );

    deletionOverview.resolve(
      jsonResponse({
        included_cases: 2,
        included_cases_by_layout: { generic: 2 },
        default_layout_profile: "generic",
        latest_report: null,
        recent_reports: [],
      }),
    );
    await deletionOverview.promise;
    expect(benchmarkDialog).toHaveTextContent("9 ground-truth hands");
    expect(benchmarkDialog).not.toHaveTextContent("2 ground-truth hands");
  });

  it("permanently removes a saved screenshot from history", async () => {
    const archivedJob = recommendedJob();
    archivedJob.id = "3".repeat(32);
    archivedJob.original_filename = "saved-table.png";
    archivedJob.archived_at = "2026-07-10T00:02:00Z";
    archivedJob.updated_at = "2026-07-10T00:02:00Z";
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
    fetchMock().mockResolvedValueOnce(new Response(null, { status: 204 }));
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", {
        name: "Manage history item 1: saved-table.png",
      }),
    );
    const dialog = screen.getByRole("dialog", { name: "Screenshot details" });
    await user.click(
      within(dialog).getByRole("button", { name: "Delete screenshot" }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Delete permanently" }),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: "Reopen history item 1",
        }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByText("Cleared reviewed hands will appear here."),
    ).toBeInTheDocument();
  });
});
