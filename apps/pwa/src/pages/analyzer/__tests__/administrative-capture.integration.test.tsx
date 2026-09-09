import { act, render, screen, waitFor, within } from "@testing-library/react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AnalyzerPage from "../AnalyzerPage";
import { historyQueryKeys } from "../../../domains/history/api/historyQueries";
import { jobQueryKeys } from "../../../domains/jobs/api/jobsQueries";
import type { DetectedState } from "../../../shared/types/poker";
import type { JobRecord } from "../../../shared/types/jobs";
import { ApiResponseError } from "../../../shared/api/core";
import {
  ADMINISTRATOR_TOKEN,
  AnalyzerTestApp as App,
  UnverifiedAnalyzerTestApp,
  administratorVerificationMock,
  approvedJob,
  benchmarkOverviewForJob,
  canonicalState,
  deferredResponse,
  detectedState,
  fetchMock,
  jobRecord,
  jsonResponse,
  mockAdministratorVerification,
  processingQueueResponse,
  setSharedPreviewSize,
  stubCanvasCapture,
  stubDisplayMedia,
  switchToUploadMode,
  unlockAdministrativeAccess,
  uploadScreenshot,
} from "../../../test/analyzerHarness";

function QueryClientCapture({
  onCapture,
}: {
  onCapture: (queryClient: QueryClient) => void;
}) {
  onCapture(useQueryClient());
  return null;
}

describe("Analyzer administrative capture", () => {
  it("keeps the operator workspace behind administrator verification", async () => {
    render(<UnverifiedAnalyzerTestApp />);

    expect(
      screen.getByRole("dialog", { name: "Administrator tools" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Choose screenshots"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "Input mode" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Automation/ }),
    ).not.toBeInTheDocument();
    expect(fetchMock()).not.toHaveBeenCalled();
  });

  it("shows the administrative banner and capture controls only while unlocked", async () => {
    render(<UnverifiedAnalyzerTestApp />);
    const user = await unlockAdministrativeAccess();

    expect(
      screen.getByRole("note", { name: "Administrative OCR test mode" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: "Input mode" }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Lock administrator tools" }),
    );

    expect(
      screen.queryByRole("note", { name: "Administrative OCR test mode" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "Input mode" }),
    ).not.toBeInTheDocument();
  });

  it("fences an in-flight history read when the administrator locks", async () => {
    const pendingHistory = deferredResponse();
    let queryClient: QueryClient | null = null;
    fetchMock().mockReturnValueOnce(pendingHistory.promise);
    render(
      <UnverifiedAnalyzerTestApp>
        <QueryClientCapture
          onCapture={(capturedQueryClient) => {
            queryClient = capturedQueryClient;
          }}
        />
        <AnalyzerPage />
      </UnverifiedAnalyzerTestApp>,
    );
    const user = await unlockAdministrativeAccess();

    await user.click(
      screen.getByRole("button", { name: "Refresh saved history" }),
    );
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
    expect(queryClient).not.toBeNull();

    await user.click(
      screen.getByRole("button", { name: "Lock administrator session" }),
    );
    await act(async () => {
      pendingHistory.resolve(jsonResponse({ total: 1, jobs: [approvedJob()] }));
    });

    await waitFor(() =>
      expect(
        queryClient?.getQueryData(historyQueryKeys.page()),
      ).toBeUndefined(),
    );
  });

  it("ignores a delayed denial from a prior administrator session", async () => {
    const pendingHistory = deferredResponse();
    fetchMock().mockReturnValueOnce(pendingHistory.promise);
    render(<UnverifiedAnalyzerTestApp />);
    const user = await unlockAdministrativeAccess();

    await user.click(
      screen.getByRole("button", { name: "Refresh saved history" }),
    );
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));

    await user.click(
      screen.getByRole("button", { name: "Lock administrator session" }),
    );
    await unlockAdministrativeAccess(user);

    await act(async () => {
      pendingHistory.resolve(jsonResponse({ detail: "denied" }, 401));
    });

    await waitFor(() =>
      expect(
        screen.getByRole("note", { name: "Administrative OCR test mode" }),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Lock administrator session" }),
    ).toBeInTheDocument();
  });

  it("fences processing recovery when the administrator locks", async () => {
    const pendingQueue = deferredResponse();
    let queryClient: QueryClient | null = null;
    window.sessionStorage.removeItem("poker-training-processing-synced");
    fetchMock().mockReturnValueOnce(pendingQueue.promise);
    render(
      <UnverifiedAnalyzerTestApp>
        <QueryClientCapture
          onCapture={(capturedQueryClient) => {
            queryClient = capturedQueryClient;
          }}
        />
        <AnalyzerPage />
      </UnverifiedAnalyzerTestApp>,
    );
    const user = await unlockAdministrativeAccess();

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
    expect(queryClient).not.toBeNull();

    await user.click(
      screen.getByRole("button", { name: "Lock administrator session" }),
    );
    await act(async () => {
      pendingQueue.resolve(processingQueueResponse([]));
    });

    await waitFor(() =>
      expect(
        queryClient?.getQueryData(jobQueryKeys.processingPage(0)),
      ).toBeUndefined(),
    );
  });

  it("fences a completed mutation when a concurrent protected read locks the administrator", async () => {
    const currentJob = jobRecord({
      id: "d".repeat(32),
      original_filename: "fenced-metadata.png",
    });
    const pendingMetadata = deferredResponse();
    let queryClient: QueryClient | null = null;
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([currentJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockImplementation((url) => {
      if (
        url ===
        `http://localhost:8000/api/admin/ocr/jobs/${currentJob.id}/metadata`
      ) {
        return pendingMetadata.promise;
      }
      if (url === "http://localhost:8000/api/admin/ocr/history") {
        return Promise.resolve(jsonResponse({ detail: "denied" }, 401));
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });
    render(
      <UnverifiedAnalyzerTestApp>
        <QueryClientCapture
          onCapture={(capturedQueryClient) => {
            queryClient = capturedQueryClient;
          }}
        />
        <AnalyzerPage />
      </UnverifiedAnalyzerTestApp>,
    );
    const user = await unlockAdministrativeAccess();

    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: fenced-metadata.png",
      }),
    );
    const details = screen.getByRole("dialog", { name: "Screenshot details" });
    await user.type(within(details).getByLabelText("Title"), "Fenced");
    await user.click(
      within(details).getByRole("button", { name: "Save details" }),
    );
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));

    await user.click(
      screen.getByRole("button", { name: "Refresh saved history" }),
    );
    expect(
      await screen.findByText(
        "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
      ),
    ).toBeInTheDocument();

    await act(async () => {
      pendingMetadata.resolve(jsonResponse({ ...currentJob, title: "Fenced" }));
    });

    expect(queryClient).not.toBeNull();
    await waitFor(() =>
      expect(
        queryClient?.getQueryData(jobQueryKeys.detail(currentJob.id)),
      ).toBeUndefined(),
    );
  });

  it.each([
    [
      401,
      "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
    ],
    [403, "Administrative OCR test mode is disabled on this deployment."],
  ])(
    "locks when a protected history refresh returns %i",
    async (status, message) => {
      fetchMock().mockResolvedValueOnce(
        jsonResponse({ detail: "denied" }, status),
      );
      render(<UnverifiedAnalyzerTestApp />);
      const user = await unlockAdministrativeAccess();

      await user.click(
        screen.getByRole("button", { name: "Refresh saved history" }),
      );

      expect(await screen.findByText(message)).toBeInTheDocument();
      expect(
        screen.queryByRole("note", { name: "Administrative OCR test mode" }),
      ).not.toBeInTheDocument();
    },
  );

  it("locks when protected processing recovery rejects the administrator", async () => {
    const pendingQueue = deferredResponse();
    window.sessionStorage.removeItem("poker-training-processing-synced");
    fetchMock().mockReturnValueOnce(pendingQueue.promise);
    render(<UnverifiedAnalyzerTestApp />);

    await unlockAdministrativeAccess();
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
    await act(async () => {
      pendingQueue.resolve(jsonResponse({ detail: "denied" }, 401));
    });

    expect(
      await screen.findByText(
        "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("note", { name: "Administrative OCR test mode" }),
    ).not.toBeInTheDocument();
  });

  it("disables both administrator lock controls during screenshot metadata saves and locks on denial", async () => {
    const currentJob = jobRecord({
      id: "a".repeat(32),
      original_filename: "metadata-lock.png",
    });
    const pendingMetadata = deferredResponse();
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([currentJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockReturnValueOnce(pendingMetadata.promise);
    render(<UnverifiedAnalyzerTestApp />);
    const user = await unlockAdministrativeAccess();

    await user.click(
      screen.getByRole("button", {
        name: "Manage screenshot 1: metadata-lock.png",
      }),
    );
    const details = screen.getByRole("dialog", { name: "Screenshot details" });
    await user.type(within(details).getByLabelText("Title"), "Reviewed");
    await user.click(
      within(details).getByRole("button", { name: "Save details" }),
    );
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));

    expect(
      screen.getByRole("button", { name: "Lock administrator session" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Lock administrator tools" }),
    ).toBeDisabled();

    await act(async () => {
      pendingMetadata.resolve(jsonResponse({ detail: "denied" }, 401));
    });

    expect(
      await screen.findByText(
        "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("note", { name: "Administrative OCR test mode" }),
    ).not.toBeInTheDocument();
  });

  it("disables both administrator lock controls during benchmark inclusion and locks on denial", async () => {
    const currentJob = approvedJob();
    currentJob.id = "b".repeat(32);
    currentJob.original_filename = "benchmark-lock.png";
    currentJob.benchmark_included = false;
    const pendingInclusion = deferredResponse();
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([currentJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockImplementation((url) => {
      if (url === "http://localhost:8000/api/admin/ocr/benchmarks") {
        return Promise.resolve(
          jsonResponse(
            benchmarkOverviewForJob(
              currentJob.id,
              currentJob.original_filename,
            ),
          ),
        );
      }
      if (
        url ===
        `http://localhost:8000/api/admin/ocr/jobs/${currentJob.id}/benchmark`
      ) {
        return pendingInclusion.promise;
      }
      if (url === "http://localhost:8000/api/admin/ocr/jobs") {
        return Promise.resolve(processingQueueResponse([currentJob]));
      }
      if (url === "http://localhost:8000/api/admin/ocr/history") {
        return Promise.resolve(
          jsonResponse({ total: 0, jobs: [], snapshot_version: "history" }),
        );
      }
      throw new Error(`Unexpected request: ${String(url)}`);
    });
    render(<UnverifiedAnalyzerTestApp />);
    const user = await unlockAdministrativeAccess();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const benchmarkDialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await user.click(
      await within(benchmarkDialog).findByRole("switch", {
        name: /Use current hand as ground truth/,
      }),
    );
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/admin/ocr/jobs/${currentJob.id}/benchmark`,
        expect.objectContaining({ method: "PUT" }),
      ),
    );

    expect(
      screen.getByRole("button", { name: "Lock administrator session" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Lock administrator tools" }),
    ).toBeDisabled();

    await act(async () => {
      pendingInclusion.resolve(jsonResponse({ detail: "denied" }, 401));
    });

    expect(
      await screen.findByText(
        "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("note", { name: "Administrative OCR test mode" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    [
      401,
      "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
    ],
    [403, "Administrative OCR test mode is disabled on this deployment."],
  ])(
    "locks when an uncached routed job returns %i",
    async (status, message) => {
      const pendingJob = deferredResponse();
      fetchMock().mockReturnValueOnce(pendingJob.promise);
      render(
        <UnverifiedAnalyzerTestApp>
          <AnalyzerPage route={{ jobId: "c".repeat(32), surface: "job" }} />
        </UnverifiedAnalyzerTestApp>,
      );

      await unlockAdministrativeAccess();
      await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1));
      await act(async () => {
        pendingJob.resolve(jsonResponse({ detail: "denied" }, status));
      });

      expect(await screen.findByText(message)).toBeInTheDocument();
      expect(
        screen.queryByRole("note", { name: "Administrative OCR test mode" }),
      ).not.toBeInTheDocument();
    },
  );

  it.each([
    [
      401,
      "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
    ],
    [403, "Administrative OCR test mode is disabled on this deployment."],
  ])(
    "locks when a protected benchmark overview returns %i",
    async (status, message) => {
      fetchMock().mockResolvedValueOnce(
        jsonResponse({ detail: "denied" }, status),
      );
      render(<UnverifiedAnalyzerTestApp />);
      const user = await unlockAdministrativeAccess();

      await user.click(
        screen.getByRole("button", { name: "Parser benchmark" }),
      );

      expect(await screen.findByText(message)).toBeInTheDocument();
      expect(
        screen.queryByRole("note", { name: "Administrative OCR test mode" }),
      ).not.toBeInTheDocument();
    },
  );

  it("locks when approval loses administrator authorization", async () => {
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse({ detail: "denied" }, 401));
    render(<UnverifiedAnalyzerTestApp />);

    const user = await uploadScreenshot();
    await user.click(
      await screen.findByRole("button", { name: "Approve state" }),
    );

    expect(
      await screen.findByText(
        "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("note", { name: "Administrative OCR test mode" }),
    ).not.toBeInTheDocument();
  });

  it("sends the administrator credential with uploads", async () => {
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]));
    render(<App />);

    await uploadScreenshot();

    const [, init] = fetchMock().mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe(
      `Bearer ${ADMINISTRATOR_TOKEN}`,
    );
  });

  it.each([
    [
      401,
      "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
    ],
    [403, "Administrative OCR test mode is disabled on this deployment."],
  ])("locks again when the server answers %i", async (status, message) => {
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ detail: "denied" }, status))
      .mockResolvedValue(processingQueueResponse([]));
    render(<UnverifiedAnalyzerTestApp />);

    await uploadScreenshot();

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(
      screen.queryByRole("note", { name: "Administrative OCR test mode" }),
    ).not.toBeInTheDocument();
  });

  it("locks tools when the active screenshot image rejects the administrator", async () => {
    const created = jobRecord();
    const image = deferredResponse();
    const existingFetch = globalThis.fetch;
    const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith(`/jobs/${created.id}/image`)) {
        return image.promise;
      }
      return existingFetch(input, init);
    });
    vi.stubGlobal("fetch", fetch);
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]));
    render(<UnverifiedAnalyzerTestApp />);

    await uploadScreenshot();
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([input]) =>
          String(input).endsWith(`/jobs/${created.id}/image`),
        ),
      ).toBe(true),
    );
    await act(async () => {
      image.resolve(jsonResponse({ detail: "denied" }, 401));
    });

    expect(
      await screen.findByText(
        "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("note", { name: "Administrative OCR test mode" }),
    ).not.toBeInTheDocument();
  });

  it("verifies the typed token with the server before showing any control", async () => {
    const verification = administratorVerificationMock();
    render(<UnverifiedAnalyzerTestApp />);
    const user = userEvent.setup();

    await user.type(
      screen.getByLabelText("Administrative OCR test token"),
      `  ${ADMINISTRATOR_TOKEN}  `,
    );
    expect(
      screen.queryByRole("note", { name: "Administrative OCR test mode" }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Unlock" }));

    expect(
      await screen.findByRole("note", {
        name: "Administrative OCR test mode",
      }),
    ).toBeInTheDocument();
    expect(verification).toHaveBeenCalledWith(ADMINISTRATOR_TOKEN);
    expect(fetchMock()).not.toHaveBeenCalled();
  });

  it.each([
    [
      "a rejected token",
      new ApiResponseError("denied", 401),
      "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.",
    ],
    [
      "a disabled deployment",
      new ApiResponseError("disabled", 403),
      "Administrative OCR test mode is disabled on this deployment.",
    ],
    [
      "an unreachable server",
      new TypeError("offline"),
      "Could not verify the administrative OCR test token. Check the connection and try again.",
    ],
  ])("refuses to unlock on %s", async (_label, failure, message) => {
    mockAdministratorVerification(failure);
    render(<UnverifiedAnalyzerTestApp />);
    const user = userEvent.setup();

    await user.type(
      screen.getByLabelText("Administrative OCR test token"),
      "wrong-token",
    );
    await user.click(screen.getByRole("button", { name: "Unlock" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(
      screen.queryByRole("note", { name: "Administrative OCR test mode" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("group", { name: "Input mode" }),
    ).not.toBeInTheDocument();
    // The draft stays so the operator can correct a mistyped credential.
    expect(screen.getByLabelText("Administrative OCR test token")).toHaveValue(
      "wrong-token",
    );
    expect(fetchMock()).not.toHaveBeenCalled();
  });

  it("renders the administrator OCR workspace after access is verified", async () => {
    fetchMock().mockResolvedValueOnce(
      jsonResponse({
        status: "ok",
        parser_provider: "ocr_cv",
      }),
    );
    render(<App />);
    const user = userEvent.setup();

    expect(
      screen.getByRole("heading", { name: "Poker Hero" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Lock administrator session" }),
    ).toHaveClass("active");
    expect(screen.getByRole("button", { name: "Share window" })).toBeEnabled();
    expect(screen.getByLabelText("Screenshots queue")).toBeInTheDocument();
    expect(
      screen.getByText("No screenshots uploaded or captured yet"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "About this app" }));
    expect(
      screen.getByRole("dialog", { name: "About Poker Hero" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("OCR + computer vision"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/OCR and computer vision read the cards/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Back up screenshots, approved ground truth, and benchmark reports in one portable ZIP.",
      ),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls[0][0]).toBe(
      "http://localhost:8000/api/health",
    );
    await user.click(
      screen.getByRole("button", { name: "Close app information" }),
    );
    expect(
      screen.queryByRole("dialog", { name: "About Poker Hero" }),
    ).not.toBeInTheDocument();

    await switchToUploadMode(user);

    expect(
      screen.getByRole("button", { name: "Upload and parse" }),
    ).toBeDisabled();
    expect(
      screen.getByText("Choose screenshots to add them to the queue."),
    ).toBeInTheDocument();
  });

  it("opens the user guide and navigates feature topics", async () => {
    render(<App />);
    const user = userEvent.setup();

    const guideTrigger = screen.getByRole("button", {
      name: "How to use Poker Training Analyzer",
    });
    await user.click(guideTrigger);
    const dialog = screen.getByRole("dialog", {
      name: "How to use Poker Training Analyzer",
    });
    const playerWorkflowTopic = within(dialog).getByRole("button", {
      name: "Player workflow",
    });

    expect(playerWorkflowTopic).toHaveFocus();
    expect(
      within(dialog).getByRole("heading", {
        name: "Analyze imported hand histories",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        /Player analysis will be based on imported hand histories/i,
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "No previous topic",
      }),
    ).toBeDisabled();
    await user.click(
      within(dialog).getByRole("button", {
        name: "Input and queue",
      }),
    );
    expect(
      within(dialog).getByRole("heading", {
        name: "Administrator OCR test tools",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        /token is held in memory for this session only/i,
      ),
    ).toBeInTheDocument();
    const topicArticle = within(dialog).getByRole("article");
    topicArticle.scrollTop = 240;

    await user.click(
      within(dialog).getByRole("button", {
        name: "Parser benchmark",
      }),
    );
    expect(topicArticle.scrollTop).toBe(0);

    expect(
      within(dialog).getByRole("heading", {
        name: "Measure recognition accuracy",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(/Use current hand as ground truth/),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Next topic: History and files",
      }),
    ).toBeEnabled();

    const historyTopic = within(dialog).getByRole("button", {
      name: "History and files",
    });
    const scrollHistoryIntoView = vi.fn();
    Object.defineProperty(historyTopic, "scrollIntoView", {
      configurable: true,
      value: scrollHistoryIntoView,
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: "Next topic: History and files",
      }),
    );
    expect(scrollHistoryIntoView).toHaveBeenCalledWith({
      block: "nearest",
      inline: "nearest",
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: "Next topic: Plugins and data",
      }),
    );
    expect(
      within(dialog).getByRole("heading", {
        name: "Choose tools and protect your data",
      }),
    ).toBeInTheDocument();
    const closeButton = within(dialog).getByRole("button", {
      name: "Close user guide",
    });
    const doneButton = within(dialog).getByRole("button", { name: "Done" });
    doneButton.focus();
    await user.tab();
    expect(closeButton).toHaveFocus();
    await user.tab({ shift: true });
    expect(doneButton).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("dialog", {
        name: "How to use Poker Training Analyzer",
      }),
    ).not.toBeInTheDocument();
    expect(guideTrigger).toHaveFocus();
  });

  it("shows the parser selected by automatic routing for the active screenshot", async () => {
    const baseJob = jobRecord({ id: "a".repeat(32) });
    const routedJob = jobRecord({
      id: baseJob.id,
      parser_provider: "auto",
      parser_result: {
        ...baseJob.parser_result!,
        raw: {
          provider: "llm_vision",
          parser_routing: {
            provider: "auto",
            selected_provider: "llm_vision",
            layout_profile: "fortuna_nations",
            fallback_from: "ocr_cv",
            fallback_reason: "Capture geometry did not match the table profile",
          },
        },
      },
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([routedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/health")) {
        return Promise.resolve(
          jsonResponse({
            status: "ok",
            parser_provider: "auto",
          }),
        );
      }
      if (url.endsWith("/api/mcp/config")) {
        return Promise.resolve(
          jsonResponse({
            enabled: false,
            environment: "staging",
            endpoint: "http://localhost:8000/mcp",
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "About this app" }));
    const dialog = screen.getByRole("dialog", {
      name: "About Poker Hero",
    });

    expect(
      await within(dialog).findByText("External vision model"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "via Automatic recognition · fallback from OCR + computer vision",
      ),
    ).toBeInTheDocument();
  });

  it("keeps backend parser precedence when an active screenshot has no routing evidence", async () => {
    const cachedJob = jobRecord({
      id: "b".repeat(32),
      parser_provider: "mock",
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([cachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/health")) {
        return Promise.resolve(
          jsonResponse({
            status: "ok",
            parser_provider: "ocr_cv",
          }),
        );
      }
      if (url.endsWith("/api/mcp/config")) {
        return Promise.resolve(
          jsonResponse({
            enabled: false,
            environment: "staging",
            endpoint: "http://localhost:8000/mcp",
          }),
        );
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "About this app" }));
    const dialog = screen.getByRole("dialog", {
      name: "About Poker Hero",
    });

    expect(
      await within(dialog).findByText("OCR + computer vision"),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText("Demo engine")).not.toBeInTheDocument();
  });

  it("keeps the information dialog open until a one-time MCP token is stored", async () => {
    const issuance = deferredResponse();
    fetchMock().mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/health")) {
          return Promise.resolve(
            jsonResponse({
              status: "ok",
              environment: "staging",
              parser_provider: "ocr_cv",
            }),
          );
        }
        if (url.endsWith("/api/admin/ocr/backups/export")) {
          return Promise.resolve(
            new Response("backup archive", {
              headers: { "Content-Type": "application/zip" },
            }),
          );
        }
        if (url.endsWith("/api/mcp/config")) {
          return Promise.resolve(
            jsonResponse({
              enabled: true,
              environment: "staging",
              endpoint: "https://poker-staging.example/mcp",
            }),
          );
        }
        if (url.endsWith("/api/mcp/principals") && init?.method === "POST") {
          return issuance.promise;
        }
        if (url.endsWith("/api/mcp/principals")) {
          return Promise.resolve(jsonResponse({ principals: [] }));
        }
        return Promise.reject(
          new Error(`Unexpected request: ${url} ${init?.method ?? "GET"}`),
        );
      },
    );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "About this app" }));
    const dialog = screen.getByRole("dialog", {
      name: "About Poker Hero",
    });
    await user.type(
      await within(dialog).findByLabelText("Agent access admin token"),
      "admin-secret",
    );
    await user.click(
      within(dialog).getByRole("button", {
        name: "Unlock credential management",
      }),
    );
    await user.type(
      await within(dialog).findByLabelText("Credential name"),
      "Codex staging",
    );
    await user.click(
      within(dialog).getByRole("button", {
        name: "Create credential",
      }),
    );

    expect(
      within(dialog).getByRole("button", {
        name: "Close app information",
      }),
    ).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Done" })).toBeDisabled();

    issuance.resolve(
      jsonResponse({
        principal: {
          id: "mcp_00000000000000000000000000000001",
          name: "Codex staging",
          environment: "staging",
          token_prefix: "abcdefghijkl",
          status: "active",
          created_at: "2026-08-07T10:00:00Z",
          updated_at: "2026-08-07T10:00:00Z",
          expires_at: null,
          revoked_at: null,
          last_used_at: null,
        },
        token: "phmcp_one-time-token",
      }),
    );

    expect(
      await within(dialog).findByText("phmcp_one-time-token"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Close app information",
      }),
    ).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Done" })).toBeDisabled();

    await user.click(
      within(dialog).getByRole("button", { name: "I stored it" }),
    );

    expect(
      within(dialog).getByRole("button", {
        name: "Close app information",
      }),
    ).toBeEnabled();
    expect(within(dialog).getByRole("button", { name: "Done" })).toBeEnabled();
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    expect(
      screen.queryByRole("dialog", {
        name: "About Poker Hero",
      }),
    ).not.toBeInTheDocument();
  });

  it("downloads and restores full application backups from the info dialog", async () => {
    const restoredJob = approvedJob();
    fetchMock().mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/health")) {
          return Promise.resolve(
            jsonResponse({
              status: "ok",
              parser_provider: "ocr_cv",
            }),
          );
        }
        if (url.endsWith("/api/admin/ocr/backups/restore")) {
          return Promise.resolve(
            jsonResponse({
              imported_jobs: 1,
              reused_jobs: 0,
              imported_benchmark_reports: 1,
              reused_benchmark_reports: 0,
              total_jobs: 1,
              total_benchmark_reports: 1,
            }),
          );
        }
        if (url.endsWith("/api/admin/ocr/jobs")) {
          return Promise.resolve(processingQueueResponse([restoredJob]));
        }
        if (url.endsWith("/api/admin/ocr/history")) {
          return Promise.resolve(
            jsonResponse({
              total: 0,
              jobs: [],
              snapshot_version: "restored-history",
            }),
          );
        }
        return Promise.reject(
          new Error(`Unexpected request: ${url} ${init?.method ?? "GET"}`),
        );
      },
    );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "About this app" }));
    const dialog = screen.getByRole("dialog", {
      name: "About Poker Hero",
    });
    expect(
      within(dialog).getByRole("button", {
        name: "Restore application backup",
      }),
    ).toBeEnabled();
    expect(
      within(dialog).getByRole("button", {
        name: "Download application backup",
      }),
    ).toBeEnabled();
    await user.click(
      within(dialog).getByRole("button", {
        name: "Download application backup",
      }),
    );
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/admin/ocr/backups/export",
        expect.objectContaining({
          headers: { Authorization: `Bearer ${ADMINISTRATOR_TOKEN}` },
        }),
      ),
    );

    const file = new File(["backup"], "poker-hero-backup.zip", {
      type: "application/zip",
    });
    await user.upload(
      within(dialog).getByLabelText("Application backup ZIP"),
      file,
    );

    expect(
      await screen.findByText(
        "Backup restored: 1 new hand, 1 benchmark report",
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: /Open screenshot 1: table\.png/,
        }),
      ).toBeInTheDocument(),
    );
    const restoreCall = fetchMock().mock.calls.find(([input]) =>
      String(input).endsWith("/api/admin/ocr/backups/restore"),
    );
    expect(restoreCall).toBeDefined();
    expect(restoreCall?.[1]?.method).toBe("POST");
    expect(new Headers(restoreCall?.[1]?.headers).get("Authorization")).toBe(
      `Bearer ${ADMINISTRATOR_TOKEN}`,
    );
    expect(restoreCall?.[1]?.body).toBeInstanceOf(FormData);
    expect((restoreCall?.[1]?.body as FormData).get("file")).toBe(file);
    expect(
      fetchMock().mock.calls.some(([input]) =>
        String(input).endsWith("/api/admin/ocr/history"),
      ),
    ).toBe(true);
  });

  it("uploads a screenshot, populates parser state, and enables approval", async () => {
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]));
    render(<App />);

    const user = await uploadScreenshot();

    expect(await screen.findByDisplayValue("Ah Kd")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Qs Jc 2h")).toBeInTheDocument();
    expect(screen.getByDisplayValue("12.5")).toBeInTheDocument();
    expect(screen.getByLabelText(/Facing action/)).toHaveValue("bet");
    expect(screen.getByRole("button", { name: "Approve state" })).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: "Request recommendation" }),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByLabelText("Parser confidence summary")).getByText(
        "/12",
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "About this app" }));
    expect(screen.getAllByText("Demo engine")).toHaveLength(1);
  });

  it("reviews an opponent seat for heads-up postflop solver routing", async () => {
    const headsUpState: DetectedState = {
      ...detectedState,
      players_in_hand: 2,
      hero_position: "big_blind",
      opponent_position: null,
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: headsUpState,
      },
    });
    const approvedState = canonicalState({
      ...headsUpState,
      opponent_position: "button",
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob(approvedState)));
    render(<App />);

    const user = await uploadScreenshot();
    const opponentPosition = await screen.findByLabelText(/Opponent position/);
    expect(
      within(screen.getByLabelText("Parser confidence summary")).getByText(
        "/13",
      ),
    ).toBeInTheDocument();
    await user.type(opponentPosition, "button");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.hero_position).toBe("big_blind");
    expect(payload.opponent_position).toBe("button");
  });

  it("omits opponent-seat confidence when hero position already resolves postflop order", async () => {
    const headsUpState: DetectedState = {
      ...detectedState,
      players_in_hand: 2,
      hero_position: "IP",
      opponent_position: null,
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: headsUpState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]));
    render(<App />);

    await uploadScreenshot();

    expect(
      screen.queryByLabelText(/Opponent position/),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByLabelText("Parser confidence summary")).getByText(
        "/12",
      ),
    ).toBeInTheDocument();
  });

  it("records the reviewed committed-opponent count for multiway wagers", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 6.5,
      current_bet: 1.5,
      players_in_hand: 3,
      opponents_at_current_bet: null,
      opponent_wager: null,
      hero_position: "big_blind",
      street: "preflop",
      facing_action: "raise",
      action_context: "Cutoff opens to 2.5 BB and button calls",
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    const approvedState = canonicalState({
      ...preflopState,
      opponents_at_current_bet: 2,
      opponent_wager: 2.5,
      opponent_commitment_total: 5,
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob(approvedState)));
    render(<App />);

    const user = await uploadScreenshot();
    const committedInput = await screen.findByLabelText(/Opponents at wager/);
    await user.type(committedInput, "2");
    await user.type(screen.getByLabelText(/Opponent wager total/), "2.5");
    await user.type(screen.getByLabelText(/Opponent commitments total/), "5");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(fetchMock().mock.calls[2][0]).toBe(
      "http://localhost:8000/api/admin/ocr/jobs/job-123/approve",
    );
    expect(payload.opponents_at_current_bet).toBe(2);
    expect(payload.opponent_wager).toBe(2.5);
    expect(payload.opponent_commitment_total).toBe(5);
  });

  it("exposes the opponent wager when OCR cannot classify a postflop action", async () => {
    const postflopState: DetectedState = {
      ...detectedState,
      current_bet: 10,
      players_in_hand: 2,
      opponent_wager: null,
      street: "river",
      facing_action: null,
      action_context: "Hero faces 10 BB to call into 31.7 BB pot",
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: postflopState,
      },
    });
    const approvedState = canonicalState({
      ...postflopState,
      opponent_wager: 10,
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob(approvedState)));
    render(<App />);

    const user = await uploadScreenshot();
    const wagerInput = await screen.findByLabelText(/Opponent wager total/);
    expect(wagerInput.closest("label")).toHaveTextContent("not detected");
    await user.type(wagerInput, "10");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.opponent_wager).toBe(10);
  });

  it("shows OCR confidence for a recognized opponent wager", async () => {
    const postflopState: DetectedState = {
      ...detectedState,
      current_bet: 10,
      players_in_hand: 2,
      opponent_wager: 10,
      street: "river",
      facing_action: "bet",
      action_context: "Hero faces a 10 BB bet into 31.7 BB pot",
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: postflopState,
        confidences: {
          ...jobRecord().parser_result!.confidences,
          opponent_wager: 0.63,
        },
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]));
    render(<App />);

    await uploadScreenshot();

    const wagerInput = await screen.findByLabelText(/Opponent wager total/);
    expect(wagerInput.closest("label")).toHaveTextContent("63%");
    expect(
      within(screen.getByLabelText("Parser confidence summary")).getByText("1"),
    ).toBeInTheDocument();
  });

  it("clears an inferred wager when facing action is corrected to a raise", async () => {
    const postflopState: DetectedState = {
      ...detectedState,
      current_bet: 10,
      players_in_hand: 2,
      opponent_wager: 10,
      street: "flop",
      facing_action: "bet",
      action_context: "Hero faces a 10 BB bet into 31.7 BB pot",
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: postflopState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    expect(screen.getByLabelText(/Opponent wager total/)).toHaveValue("10");
    await user.selectOptions(screen.getByLabelText(/Facing action/), "raise");
    expect(screen.getByLabelText(/Opponent wager total/)).toHaveValue("");
    expect(screen.getByLabelText(/Action context/)).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "Add action" }));
    await user.selectOptions(screen.getByLabelText("Action 1 type"), "bet");
    const actionTypeSelect = screen.getByLabelText("Action 1 type");
    expect(actionTypeSelect.parentElement).toHaveClass("select-control");
    expect(
      actionTypeSelect.closest(".action-history-row")?.firstElementChild,
    ).toHaveClass("action-history-index");
    await user.type(screen.getByLabelText("Action 1 amount"), "5");
    await user.click(screen.getByRole("button", { name: "Add action" }));
    await user.selectOptions(screen.getByLabelText("Action 2 type"), "raise");
    await user.type(screen.getByLabelText("Action 2 amount"), "15");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.opponent_wager).toBeNull();
    expect(payload.postflop_action_history).toEqual([
      { actor: "oop", action: "bet", amount: 5 },
      { actor: "ip", action: "raise", amount: 15 },
    ]);
  });

  it("clears inferred action state when the current bet is corrected to zero", async () => {
    const postflopState: DetectedState = {
      ...detectedState,
      current_bet: 10,
      opponent_wager: 10,
      street: "river",
      facing_action: "bet",
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: postflopState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]));
    render(<App />);

    const user = await uploadScreenshot();
    const currentBetInput = screen.getByLabelText(/Current bet/);
    await user.clear(currentBetInput);
    await user.type(currentBetInput, "0");

    expect(
      screen.queryByLabelText(/Opponent wager total/),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Facing action/)).toHaveValue("");
    expect(screen.getByLabelText(/Action context/)).toHaveValue("");
  });

  it("clears a postflop inferred wager when the street is corrected to preflop", async () => {
    const postflopState: DetectedState = {
      ...detectedState,
      current_bet: 10,
      opponent_wager: 10,
      street: "flop",
      facing_action: "bet",
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: postflopState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]));
    render(<App />);

    const user = await uploadScreenshot();
    await user.selectOptions(screen.getByLabelText(/Street/), "preflop");

    expect(screen.getByLabelText(/Opponent wager total/)).toHaveValue("");
    expect(screen.getByLabelText(/Facing action/)).toHaveValue("");
    expect(screen.getByLabelText(/Action context/)).toHaveValue("");
  });

  it("excludes opponent-wager confidence from check spots", async () => {
    const checkState: DetectedState = {
      ...detectedState,
      current_bet: 0,
      opponent_wager: null,
      facing_action: null,
      action_context: "No bet to call; pot is 12.5 BB",
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: checkState,
        confidences: {
          ...jobRecord().parser_result!.confidences,
          action_context: 0.9,
        },
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]));
    render(<App />);

    await uploadScreenshot();

    expect(
      screen.queryByLabelText(/Opponent wager total/),
    ).not.toBeInTheDocument();
    expect(
      within(screen.getByLabelText("Parser confidence summary")).getByText(
        "/11",
      ),
    ).toBeInTheDocument();
  });

  it("clears multiway commitments when players in hand is corrected to heads-up", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 6.5,
      current_bet: 1.5,
      players_in_hand: 3,
      opponents_at_current_bet: 2,
      opponent_wager: 2.5,
      opponent_commitment_total: 5,
      hero_position: "big_blind",
      street: "preflop",
      facing_action: "raise",
      action_context: "Cutoff opens to 2.5 BB and button calls",
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    const approvedState = canonicalState({
      ...preflopState,
      players_in_hand: 2,
      opponents_at_current_bet: null,
      opponent_commitment_total: null,
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob(approvedState)));
    render(<App />);

    const user = await uploadScreenshot();
    const playersInput = screen.getByLabelText(/Players in hand/);
    expect(screen.getByLabelText(/Opponent commitments total/)).toHaveValue(
      "5",
    );
    await user.clear(playersInput);
    await user.type(playersInput, "2");
    expect(
      screen.queryByLabelText(/Opponent commitments total/),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.players_in_hand).toBe(2);
    expect(payload.opponents_at_current_bet).toBeNull();
    expect(payload.opponent_commitment_total).toBeNull();
  });

  it("rejects commitments above the latest wager across active opponents", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 10,
      current_bet: 1.5,
      players_in_hand: 3,
      opponents_at_current_bet: 1,
      opponent_wager: 2.5,
      opponent_commitment_total: 6,
      hero_position: "big_blind",
      street: "preflop",
      facing_action: "raise",
      action_context: "Cutoff opens to 2.5 BB",
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    expect(
      await screen.findByText(
        "Opponent commitments total cannot exceed the latest wager across active opponents",
      ),
    ).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(2);
  });

  it("validates commitment totals against current-street history only", async () => {
    const postflopState: DetectedState = {
      ...detectedState,
      pot_size: 30,
      current_bet: 15,
      players_in_hand: 3,
      opponents_at_current_bet: 1,
      opponent_wager: 15,
      opponent_commitment_total: null,
      preflop_action_history: [
        { actor: "button", action: "raise", amount: 25 },
      ],
      facing_action: "raise",
      postflop_action_history: [
        { actor: "oop", action: "bet", amount: 5 },
        { actor: "ip", action: "raise", amount: 15 },
      ],
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: postflopState,
      },
    });
    const approvedState = canonicalState({
      ...postflopState,
      opponent_commitment_total: 20,
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob(approvedState)));
    render(<App />);

    const user = await uploadScreenshot();
    await user.type(screen.getByLabelText(/Opponent commitments total/), "20");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.opponent_commitment_total).toBe(20);
  });

  it("validates commitments against a corrected wager instead of stale history", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 30,
      current_bet: 5,
      players_in_hand: 3,
      opponents_at_current_bet: 1,
      opponent_wager: 10,
      opponent_commitment_total: 15,
      hero_position: "big_blind",
      street: "preflop",
      facing_action: "raise",
      preflop_action_history: [
        { actor: "button", action: "raise", amount: 20 },
      ],
      action_context: "Reviewed wager corrects stale parsed history",
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    const approvedState = canonicalState(preflopState);
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob(approvedState)));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.opponent_wager).toBe(10);
    expect(payload.opponent_commitment_total).toBe(15);
  });

  it("preserves reviewed preflop commitments when there is no call amount", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 2.5,
      current_bet: 0,
      players_in_hand: 2,
      opponent_commitment_total: 1.5,
      hero_position: "button",
      street: "preflop",
      facing_action: null,
      action_context: "Folded dead money remains in the pot",
    };
    const created = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    const approvedState = canonicalState({
      ...preflopState,
      opponent_commitment_total: 1.25,
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob(approvedState)));
    render(<App />);

    const user = await uploadScreenshot();
    const commitmentInput = await screen.findByLabelText(
      /Opponent commitments total/,
    );
    expect(commitmentInput).toHaveValue("1.5");
    await user.clear(commitmentInput);
    await user.type(commitmentInput, "1.25");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.current_bet).toBe(0);
    expect(payload.opponent_commitment_total).toBe(1.25);
  });

  it("re-approves corrections to an approved-only imported job", async () => {
    const importedJob = {
      ...approvedJob(),
      id: "imported-job",
      original_filename: "imported.png",
      parser_result: null,
      benchmark_included: true,
    };
    const correctedState = canonicalState({ pot_size: 20 });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(importedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([importedJob]))
      .mockResolvedValueOnce(
        jsonResponse({ ...importedJob, approved_state: correctedState }),
      );
    render(<App />);

    const user = await uploadScreenshot("imported.png");
    expect(await screen.findByDisplayValue("12.5")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve state" }),
    ).toBeDisabled();

    const potInput = screen.getByDisplayValue("12.5");
    await user.clear(potInput);
    await user.type(potInput, "20");

    const approveButton = screen.getByRole("button", { name: "Approve state" });
    expect(approveButton).toBeEnabled();
    await user.click(approveButton);

    expect(fetchMock().mock.calls[2][0]).toBe(
      "http://localhost:8000/api/admin/ocr/jobs/imported-job/approve",
    );
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.pot_size).toBe(20);
    expect(payload.user_approved).toBe(true);
  });

  it("uploads multiple screenshots and switches between parsed jobs", async () => {
    const secondState: DetectedState = {
      ...detectedState,
      hero_cards: [
        { rank: "7", suit: "diamonds" },
        { rank: "A", suit: "hearts" },
      ],
      board_cards: [],
      pot_size: 3.5,
      current_bet: 1.5,
      hero_stack: 100.4,
      effective_stack: 100.4,
      players_in_hand: 2,
      street: "preflop",
      action_context: "Hero faces 1.5 BB to call into 3.5 BB pot",
    };
    const firstJob = jobRecord({ id: "job-1", original_filename: "first.png" });
    const secondJob = jobRecord({
      id: "job-2",
      original_filename: "second.png",
      parser_result: {
        state: secondState,
        confidences: { hero_cards: 0.91, street: 0.9 },
        warnings: [],
        raw: {},
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(firstJob, 201))
      .mockResolvedValueOnce(jsonResponse(secondJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([firstJob, secondJob]));
    render(<App />);
    const user = userEvent.setup();
    await unlockAdministrativeAccess(user);
    await switchToUploadMode(user);
    const input = screen.getByLabelText("Choose screenshots");

    await user.upload(input, [
      new File(["first"], "first.png", { type: "image/png" }),
      new File(["second"], "second.png", { type: "image/png" }),
    ]);
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));

    expect(
      await screen.findByLabelText("Screenshots queue"),
    ).toBeInTheDocument();
    expect(screen.getByText("2 screenshots")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Ah Kd")).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(3);

    await user.click(
      screen.getByRole("button", { name: "Open screenshot 2: second.png" }),
    );

    expect(screen.getByDisplayValue("7d Ah")).toBeInTheDocument();
    expect(screen.getByDisplayValue("3.5")).toBeInTheDocument();
    expect(screen.getByLabelText(/Street/)).toHaveValue("preflop");
  });

  it("continues a batch upload when one screenshot fails", async () => {
    const firstJob = jobRecord({ id: "job-1", original_filename: "first.png" });
    const thirdJob = jobRecord({ id: "job-3", original_filename: "third.png" });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(firstJob, 201))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Second image is unreadable" }, 400),
      )
      .mockResolvedValueOnce(jsonResponse(thirdJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([firstJob, thirdJob]));
    render(<App />);
    const user = userEvent.setup();
    await unlockAdministrativeAccess(user);
    await switchToUploadMode(user);

    await user.upload(screen.getByLabelText("Choose screenshots"), [
      new File(["first"], "first.png", { type: "image/png" }),
      new File(["second"], "second.png", { type: "image/png" }),
      new File(["third"], "third.png", { type: "image/png" }),
    ]);
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));

    expect(
      await screen.findByRole("button", {
        name: /Open screenshot \d+: third\.png/,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /Open screenshot \d+: first\.png/,
      }),
    ).toBeInTheDocument();
    const failedItem = screen.getByRole("button", {
      name: /Open screenshot \d+: second\.png/,
    });
    expect(within(failedItem).getByText("error")).toBeInTheDocument();
    expect(
      within(failedItem).getByText("Second image is unreadable"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        "1 screenshot need attention. Check the failed queue items.",
      ),
    ).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(4);
  });

  it("shows processing progress and aborts unprocessed screenshots", async () => {
    fetchMock().mockImplementation((url, options) => {
      if (
        url === "http://localhost:8000/api/admin/ocr/jobs" &&
        options?.method !== "POST"
      ) {
        return Promise.resolve(processingQueueResponse([]));
      }
      const signal = options?.signal as AbortSignal | undefined;
      return new Promise<Response>((_resolve, reject) => {
        if (signal?.aborted) {
          reject(new DOMException("Aborted", "AbortError"));
          return;
        }
        signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      });
    });
    render(<App />);
    const user = userEvent.setup();

    await unlockAdministrativeAccess(user);
    await switchToUploadMode(user);
    await user.upload(screen.getByLabelText("Choose screenshots"), [
      new File(["first"], "first.png", { type: "image/png" }),
      new File(["second"], "second.png", { type: "image/png" }),
      new File(["third"], "third.png", { type: "image/png" }),
    ]);
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));

    expect(
      await screen.findByRole("dialog", { name: "Processing queue" }),
    ).toBeInTheDocument();
    expect(screen.getByText("first.png")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Abort and discard unprocessed" }),
    );

    expect(
      await screen.findByText(
        "Import aborted. 3 unprocessed screenshots discarded.",
      ),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Stopping import" }),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock()).toHaveBeenCalledTimes(2);
    expect(
      screen.getByText("No screenshots uploaded or captured yet"),
    ).toBeInTheDocument();
  });

  it("reports when screen sharing is not available", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: undefined,
    });
    render(<App />);
    const user = await unlockAdministrativeAccess();

    await user.click(screen.getByRole("button", { name: "Share window" }));

    expect(
      await screen.findByText(
        "Screen sharing is not supported in this browser",
      ),
    ).toBeInTheDocument();
  });

  it("captures a shared screen frame and uploads it for parsing", async () => {
    const { addEventListener, getDisplayMedia } = stubDisplayMedia("browser");
    stubCanvasCapture();
    const created = jobRecord({ original_filename: "screen-capture.png" });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]));
    render(<App />);
    const user = userEvent.setup();
    await unlockAdministrativeAccess(user);

    await user.click(screen.getByRole("button", { name: "Tab" }));
    await user.click(screen.getByRole("button", { name: "Share tab" }));
    expect(await screen.findByText("Tab sharing active")).toBeInTheDocument();
    expect(screen.getByLabelText("Shared screen preview")).toHaveClass(
      "active",
    );
    setSharedPreviewSize();

    await user.click(screen.getByRole("button", { name: "Capture and parse" }));

    expect(await screen.findByDisplayValue("Ah Kd")).toBeInTheDocument();
    expect(
      screen.getByAltText("Uploaded poker table screenshot"),
    ).not.toHaveClass("hidden");
    expect(screen.getByLabelText("Shared screen preview")).not.toHaveClass(
      "active",
    );
    expect(screen.getByRole("button", { name: "View live tab" })).toBeEnabled();
    expect(screen.getByLabelText("Screenshots queue")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 1: screen-capture.png",
      }),
    ).toBeInTheDocument();
    expect(fetchMock()).toHaveBeenCalledTimes(2);
    expect(getDisplayMedia).toHaveBeenCalledWith({
      audio: false,
      monitorTypeSurfaces: "exclude",
      preferCurrentTab: false,
      selfBrowserSurface: "exclude",
      surfaceSwitching: "include",
      video: { frameRate: 8, displaySurface: "browser" },
    });
    expect(addEventListener).toHaveBeenCalledWith(
      "ended",
      expect.any(Function),
    );

    await user.click(screen.getByRole("button", { name: "View live tab" }));
    expect(screen.getByLabelText("Shared screen preview")).toHaveClass(
      "active",
    );
    expect(screen.getByAltText("Uploaded poker table screenshot")).toHaveClass(
      "hidden",
    );
  });

  it("invalidates an older history restore while clearing reviewed jobs", async () => {
    const readyJob: JobRecord = {
      ...approvedJob(),
      id: "7".repeat(32),
      original_filename: "archive-history-race.png",
      updated_at: "2026-07-10T00:01:00Z",
    };
    const archivedJob: JobRecord = {
      ...readyJob,
      archived_at: "2026-07-10T00:02:00Z",
      updated_at: "2026-07-10T00:02:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([readyJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    const pendingHistoryRestore = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingHistoryRestore.promise)
      .mockResolvedValueOnce(
        jsonResponse({
          total: 1,
          jobs: [archivedJob],
          snapshot_version: "archive-response",
        }),
      )
      .mockResolvedValueOnce(
        processingQueueResponse([], "archive-processing-empty"),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 1,
          jobs: [archivedJob],
          snapshot_version: "archive-history-reconciled",
        }),
      );
    render(<App />);

    const refreshButton = screen.getByRole("button", {
      name: "Refresh saved history",
    });
    const clearButton = screen.getByRole("button", { name: "Clear reviewed" });
    act(() => {
      refreshButton.click();
      clearButton.click();
    });
    expect(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    ).toBeInTheDocument();

    await act(async () => {
      pendingHistoryRestore.resolve(
        jsonResponse({
          total: 0,
          jobs: [],
          snapshot_version: "stale-pre-archive-history",
        }),
      );
      await pendingHistoryRestore.promise;
    });

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenNthCalledWith(
        4,
        "http://localhost:8000/api/admin/ocr/history",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
    expect(
      screen.getByRole("button", {
        name: "Reopen history item 1",
      }),
    ).toBeInTheDocument();
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-history-v1")),
      )[0].job,
    ).toEqual(archivedJob);
    expect(window.sessionStorage.getItem("poker-training-history-synced")).toBe(
      "true",
    );
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/admin/ocr/history",
      "http://localhost:8000/api/admin/ocr/history",
      "http://localhost:8000/api/admin/ocr/jobs",
      "http://localhost:8000/api/admin/ocr/history",
    ]);
    expect(fetchMock().mock.calls[1][1]?.method).toBe("PUT");
  });

  it("keeps completed jobs in processing when history persistence fails", async () => {
    const approvedUpload = {
      ...approvedJob(),
      original_filename: "retry.png",
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(approvedUpload, 201))
      .mockResolvedValueOnce(processingQueueResponse([approvedUpload]))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "History storage is unavailable" }, 500),
      )
      .mockResolvedValueOnce(
        jsonResponse({ detail: "History storage is unavailable" }, 500),
      )
      .mockResolvedValueOnce(processingQueueResponse([approvedUpload]));
    render(<App />);
    const user = userEvent.setup();

    await unlockAdministrativeAccess(user);
    await switchToUploadMode(user);
    await user.upload(
      screen.getByLabelText("Choose screenshots"),
      new File(["retry"], "retry.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));
    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 1: retry.png",
      }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear reviewed" }));

    expect(
      await screen.findByText("History storage is unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 1: retry.png",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Reopen history item 1",
      }),
    ).not.toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-history-synced"),
    ).toBeNull();
  });

  it("releases archive leases after a deterministic conflict", async () => {
    const readyJob: JobRecord = {
      ...approvedJob(),
      id: "6".repeat(32),
      original_filename: "archive-conflict.png",
    };
    const competingAttempt: JobRecord = {
      ...readyJob,
      status: "approved",
      updated_at: "2026-07-10T00:01:00Z",
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
    fetchMock().mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (
          url === "http://localhost:8000/api/admin/ocr/history" &&
          init?.method === "PUT"
        ) {
          return Promise.resolve(
            jsonResponse(
              {
                detail: "Only successful approved jobs can be moved to history",
              },
              409,
            ),
          );
        }
        if (url === "http://localhost:8000/api/admin/ocr/history") {
          return Promise.resolve(
            jsonResponse({
              total: 0,
              jobs: [],
              snapshot_version: "archive-conflict-history",
            }),
          );
        }
        if (url === "http://localhost:8000/api/admin/ocr/jobs") {
          return Promise.resolve(
            processingQueueResponse(
              [competingAttempt],
              "archive-conflict-processing",
            ),
          );
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Clear reviewed" }));

    expect(
      await screen.findByText(
        "Only successful approved jobs can be moved to history",
      ),
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
      window.sessionStorage.getItem("poker-training-history-mutation-v1"),
    ).toBeNull();
  });

  it("refreshes history when a later archive batch fails", async () => {
    window.sessionStorage.removeItem("poker-training-processing-synced");
    const readyJobs = Array.from({ length: 101 }, (_, index) => ({
      ...approvedJob(),
      id: index.toString(16).padStart(32, "0"),
      original_filename: `partial-archive-${index + 1}.png`,
    }));
    const archivedJobs = readyJobs.slice(0, 100).map((job) => ({
      ...job,
      archived_at: "2026-07-10T00:02:00Z",
    }));
    const firstHistoryPage = {
      total: 100,
      jobs: archivedJobs.slice(0, 24),
      snapshot_version: "partial-history-snapshot",
    };
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: 101,
          jobs: readyJobs.slice(0, 100),
          snapshot_version: "ready-processing-snapshot",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 101,
          jobs: readyJobs.slice(100),
          snapshot_version: "ready-processing-snapshot",
        }),
      )
      .mockResolvedValueOnce(jsonResponse(firstHistoryPage))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Final archive batch failed" }, 500),
      )
      .mockResolvedValueOnce(jsonResponse(firstHistoryPage))
      .mockResolvedValueOnce(
        processingQueueResponse(
          readyJobs.slice(100),
          "remaining-processing-snapshot",
        ),
      );
    render(<App />);
    const user = userEvent.setup();

    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 101: partial-archive-101.png",
      }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear reviewed" }));

    expect(
      await screen.findByText("Final archive batch failed"),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 1: partial-archive-101.png",
      }),
    ).toBeInTheDocument();
    expect(window.localStorage.getItem("poker-training-history-total-v1")).toBe(
      "100",
    );
    expect(
      window.sessionStorage.getItem("poker-training-history-synced"),
    ).toBeNull();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();
    expect(
      JSON.parse(
        String(
          window.sessionStorage.getItem("poker-training-history-mutation-v1"),
        ),
      ),
    ).toEqual(
      expect.objectContaining({
        kind: "archive",
        jobIds: readyJobs.map((job) => job.id),
      }),
    );
    const calls = fetchMock().mock.calls;
    const callIndexes = (url: string, method: string): number[] =>
      calls.flatMap(([requestUrl, options], index) =>
        requestUrl === url && (options?.method ?? "GET") === method
          ? [index]
          : [],
      );
    const queueReads = callIndexes(
      "http://localhost:8000/api/admin/ocr/jobs",
      "GET",
    );
    const nextQueuePage = callIndexes(
      "http://localhost:8000/api/admin/ocr/jobs?offset=100",
      "GET",
    );
    const archiveAttempts = callIndexes(
      "http://localhost:8000/api/admin/ocr/history",
      "PUT",
    );
    const historyRefreshes = callIndexes(
      "http://localhost:8000/api/admin/ocr/history",
      "GET",
    );

    expect(nextQueuePage).toHaveLength(1);
    expect(archiveAttempts).toHaveLength(2);
    expect(historyRefreshes).toHaveLength(1);
    expect(queueReads.length).toBeGreaterThanOrEqual(2);
    expect(queueReads[0]).toBeLessThan(nextQueuePage[0]);
    expect(nextQueuePage[0]).toBeLessThan(archiveAttempts[0]);
    expect(archiveAttempts[0]).toBeLessThan(archiveAttempts[1]);
    expect(archiveAttempts[1]).toBeLessThan(historyRefreshes[0]);
    expect(queueReads.some((index) => index > historyRefreshes[0])).toBe(true);
    expect(calls[historyRefreshes[0]][1]).toEqual(
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("clears persisted jobs when the bounded browser history cache is unavailable", async () => {
    const approvedUpload = {
      ...approvedJob(),
      original_filename: "storage-disabled.png",
    };
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(approvedUpload, 201))
      .mockResolvedValueOnce(processingQueueResponse([approvedUpload]))
      .mockResolvedValueOnce(
        jsonResponse({
          total: 1,
          jobs: [
            {
              ...approvedUpload,
              archived_at: "2026-07-10T00:01:00Z",
            },
          ],
        }),
      )
      .mockResolvedValueOnce(processingQueueResponse([]));
    render(<App />);
    const user = userEvent.setup();

    await unlockAdministrativeAccess(user);
    await switchToUploadMode(user);
    await user.upload(
      screen.getByLabelText("Choose screenshots"),
      new File(["storage-disabled"], "storage-disabled.png", {
        type: "image/png",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));
    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 1: storage-disabled.png",
      }),
    ).toBeInTheDocument();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Storage is disabled", "QuotaExceededError");
    });

    await user.click(screen.getByRole("button", { name: "Clear reviewed" }));

    expect(
      await screen.findByRole("button", {
        name: "Reopen history item 1",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: storage-disabled.png",
      }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Storage is disabled")).not.toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-history-synced"),
    ).toBeNull();
  });

  it("rejects a selected source that does not match the active share mode", async () => {
    const stop = vi.fn();
    const getDisplayMedia = vi.fn().mockResolvedValue({
      getTracks: () => [{ stop }],
      getVideoTracks: () => [
        { getSettings: () => ({ displaySurface: "window" }) },
      ],
    });
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getDisplayMedia },
    });
    render(<App />);
    const user = await unlockAdministrativeAccess();

    await user.click(screen.getByRole("button", { name: "Tab" }));
    await user.click(screen.getByRole("button", { name: "Share tab" }));

    expect(
      await screen.findByText(/Window was selected\. Choose a tab/),
    ).toBeInTheDocument();
    expect(stop).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: "Capture and parse" }),
    ).toBeDisabled();
  });

  it("marks the workspace administrative and offers no learning controls", async () => {
    const created = jobRecord();
    const approved = approvedJob();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approved));
    render(<App />);

    const user = await uploadScreenshot();
    expect(
      screen.getByRole("note", { name: "Administrative OCR test mode" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Administrative OCR test input"),
    ).not.toBeInTheDocument();
    await user.click(
      await screen.findByRole("button", { name: "Approve state" }),
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Approve state" }),
      ).toBeDisabled(),
    );
    expect(
      screen.queryByRole("button", { name: "Request recommendation" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Your training decision"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Training progress" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Administrator OCR test console for Texas Hold'em screenshots",
      ),
    ).toBeInTheDocument();
  });
});
