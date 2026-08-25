import { cleanup, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";

import { AppProviders } from "../app/providers/AppProviders";
import AnalyzerPage from "../pages/analyzer/AnalyzerPage";
import type { CanonicalState, DetectedState } from "../shared/types/poker";
import type { JobRecord } from "../shared/types/jobs";
import type { RecommendationResult } from "../shared/types/recommendations";

export function AnalyzerTestApp({ children }: { children?: ReactNode }) {
  return <AppProviders>{children ?? <AnalyzerPage />}</AppProviders>;
}

export const detectedState: DetectedState = {
  hero_cards: [
    { rank: "A", suit: "hearts" },
    { rank: "K", suit: "diamonds" },
  ],
  board_cards: [
    { rank: "Q", suit: "spades" },
    { rank: "J", suit: "clubs" },
    { rank: "2", suit: "hearts" },
  ],
  pot_size: 12.5,
  current_bet: 2.5,
  hero_stack: 97.5,
  effective_stack: 96,
  players_in_hand: 3,
  hero_position: "button",
  preflop_opener_position: null,
  preflop_open_size: null,
  street: "flop",
  facing_action: "bet",
  action_context: "Cutoff bet 2.5 into 12.5",
};

export const recommendation: RecommendationResult = {
  action: "raise",
  sizing: 7.5,
  confidence: 0.82,
  explanation: "Apply pressure with top pair and strong blockers.",
  raw: { provider: "mock" },
};

export const recommendationWithEvidence: RecommendationResult = {
  ...recommendation,
  explanation:
    "Solver compared candidate actions and selected the highest EV line.",
  raw: {
    provider: "local_solver",
    engine: "local_ev_solver_v1",
    requested_engine: "postflop_solver",
    fallback_reason:
      "the open-source engine supports heads-up postflop spots only",
    equity: { equity: 0.61 },
    realized_equity: 0.55,
    required_equity: 0.2,
    opponents_at_current_bet: 1,
    opponent_wager: 10,
    opponent_commitment_total: 13,
    hero_wager: 1,
    stack_depth_policy: 42,
    effective_stack: -1,
    opening_raise_size: "2.5",
    continue_fraction: 4,
    candidates: [
      { action: "fold", sizing: null, ev: 0 },
      { action: "call", sizing: null, ev: 3.1 },
      { action: "check", sizing: null, ev: 3 },
      { action: "bet", sizing: 2.5, ev: 2.9 },
      { action: "raise", sizing: 4, ev: 2.8 },
      {
        action: "raise",
        sizing: 7.5,
        ev: 2.4,
        frequency: 0.72,
        fold_equity: 0.09,
        per_opponent_fold_equity: 0.3,
      },
      { action: "invalid", sizing: -1, ev: "unknown" },
    ],
  },
};

export function canonicalState(
  overrides: Partial<CanonicalState> = {},
): CanonicalState {
  return {
    ...detectedState,
    user_approved: true,
    ...overrides,
  };
}

export function jobRecord(overrides: Partial<JobRecord> = {}): JobRecord {
  return {
    id: "job-123",
    status: "parsed",
    upload_request_id: null,
    original_filename: "table.png",
    image_filename: "job-123.png",
    parser_provider: "mock",
    recommendation_provider: "mock",
    parser_result: {
      state: detectedState,
      confidences: {
        hero_cards: 0.99,
        board_cards: 0.98,
        pot_size: 0.92,
        current_bet: 0.9,
        hero_stack: 0.89,
        effective_stack: 0.88,
        players_in_hand: 0.86,
        hero_position: 0.84,
        street: 1,
        facing_action: 0.9,
      },
      warnings: [],
      raw: { provider: "mock" },
    },
    parser_auto_approval_eligible: true,
    approved_state: null,
    training_decision: null,
    recommendation: null,
    recommendation_pending: false,
    recommendation_request_id: null,
    training_reviewed_at: null,
    training_review_note: null,
    benchmark_included: false,
    archived_at: null,
    error: null,
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:00:00Z",
    ...overrides,
  };
}

export function approvedJob(
  state: CanonicalState = canonicalState(),
): JobRecord {
  return jobRecord({
    status: "approved",
    approved_state: state,
    recommendation: null,
  });
}

export function recommendedJob(
  state: CanonicalState = canonicalState(),
): JobRecord {
  return jobRecord({
    status: "recommended",
    approved_state: state,
    recommendation,
  });
}

export function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function processingQueueResponse(
  jobs: JobRecord[],
  snapshotVersion = "test-processing-snapshot",
): Response {
  return jsonResponse({
    total: jobs.length,
    jobs,
    snapshot_version: snapshotVersion,
  });
}

export function benchmarkOverviewForJob(
  jobId: string,
  originalFilename: string,
) {
  return {
    included_cases: 1,
    latest_report: {
      id: `benchmark-${jobId}`,
      parser_provider: "ocr_cv",
      layout_profile: "fortuna",
      created_at: "2026-07-20T12:00:00Z",
      total_cases: 1,
      successful_cases: 1,
      failed_cases: 0,
      correct_fields: 10,
      evaluated_fields: 10,
      accuracy: 1,
      field_metrics: [{ field: "pot_size", correct: 1, total: 1, accuracy: 1 }],
      cases: [
        {
          job_id: jobId,
          original_filename: originalFilename,
          status: "completed",
          correct_fields: 10,
          evaluated_fields: 10,
          accuracy: 1,
          warnings: [],
          error: null,
          comparisons: [],
        },
      ],
    },
    recent_reports: [],
  };
}

export function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((resolvePromise) => {
    resolve = resolvePromise;
  });

  return { promise, resolve };
}

export function nextDeferredResponse(
  deferred: ReturnType<typeof deferredResponse>,
): Promise<Response> {
  return deferred.promise.then((response) => response.clone());
}

export function fetchMock() {
  return vi.mocked(fetch);
}

export function stubCanvasCapture() {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    drawImage: vi.fn(),
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(
    function toBlob(callback: BlobCallback) {
      callback(new Blob(["capture"], { type: "image/png" }));
    },
  );
}

export function stubDisplayMedia(displaySurface = "window") {
  const addEventListener = vi.fn();
  const removeEventListener = vi.fn();
  const stop = vi.fn();
  const getDisplayMedia = vi.fn().mockResolvedValue({
    getTracks: () => [{ addEventListener, removeEventListener, stop }],
    getVideoTracks: () => [{ getSettings: () => ({ displaySurface }) }],
  });
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getDisplayMedia },
  });

  return { addEventListener, getDisplayMedia, removeEventListener, stop };
}

export function setSharedPreviewSize() {
  const preview = screen.getByLabelText("Shared screen preview");
  Object.defineProperty(preview, "videoWidth", {
    configurable: true,
    value: 973,
  });
  Object.defineProperty(preview, "videoHeight", {
    configurable: true,
    value: 691,
  });
}

export async function switchToUploadMode(user = userEvent.setup()) {
  if (!screen.queryByLabelText("Choose screenshots")) {
    await user.click(screen.getByRole("button", { name: "Upload" }));
  }
  return user;
}

export async function disableAutomation(user = userEvent.setup()) {
  const automationButton = screen.queryByRole("button", {
    name: "Automation On",
  });
  if (automationButton) {
    await user.click(automationButton);
  }
  return user;
}

export async function uploadScreenshot(name = "table.png") {
  const user = userEvent.setup();
  await disableAutomation(user);
  await switchToUploadMode(user);
  const input = screen.getByLabelText("Choose screenshots");
  const file = new File(["not-real-image-bytes"], name, { type: "image/png" });

  await user.upload(input, file);
  await user.click(screen.getByRole("button", { name: "Upload and parse" }));

  return user;
}

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem("poker-training-processing-v1", "[]");
  window.localStorage.setItem("poker-training-processing-total-v1", "0");
  window.localStorage.setItem("poker-training-history-v1", "[]");
  window.localStorage.setItem("poker-training-history-total-v1", "0");
  window.sessionStorage.clear();
  window.sessionStorage.setItem("poker-training-processing-synced", "true");
  window.sessionStorage.setItem("poker-training-history-synced", "true");
  vi.stubGlobal("fetch", vi.fn());
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: undefined,
  });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
