import { describe, expect, it } from "vitest";

import {
  historyAction,
  historyCards,
  relativeTimeLabel,
} from "./historyPresentation";
import type { CanonicalState } from "../../../shared/types/poker";
import type { JobRecord } from "../../../shared/types/jobs";

const NOW = Date.parse("2026-08-13T12:00:00Z");

function jobRecord(overrides: Partial<JobRecord> = {}): JobRecord {
  return {
    id: "job-1",
    status: "parsed",
    original_filename: "table.png",
    image_filename: "job-1.png",
    parser_provider: "ocr_cv",
    recommendation_provider: "local_solver",
    parser_result: null,
    approved_state: null,
    training_decision: null,
    recommendation: null,
    recommendation_pending: false,
    training_reviewed_at: null,
    training_review_note: null,
    benchmark_included: false,
    archived_at: null,
    error: null,
    created_at: "2026-08-13T10:00:00Z",
    updated_at: "2026-08-13T10:00:00Z",
    ...overrides,
  };
}

function canonicalState(): CanonicalState {
  return {
    hero_cards: [
      { rank: "A", suit: "clubs" },
      { rank: "J", suit: "hearts" },
    ],
    board_cards: [],
    pot_size: 3,
    current_bet: 0,
    hero_stack: 97,
    effective_stack: 97,
    players_in_hand: 2,
    hero_position: "button",
    preflop_opener_position: null,
    preflop_open_size: null,
    street: "flop",
    facing_action: null,
    action_context: null,
    user_approved: true,
  };
}

describe("history presentation", () => {
  it("uses approved cards and recommendation action when available", () => {
    const job = jobRecord({
      approved_state: canonicalState(),
      recommendation: {
        action: "check",
        sizing: null,
        confidence: 0.82,
        explanation: "Check keeps weaker hands in.",
        raw: {},
      },
    });

    expect(historyCards(job)).toEqual(canonicalState().hero_cards);
    expect(historyAction(job)).toBe("check");
  });

  it("falls back from approved action to job status", () => {
    expect(historyAction(jobRecord({ approved_state: canonicalState() }))).toBe(
      "approved",
    );
    expect(historyAction(jobRecord({ status: "error" }))).toBe("error");
    expect(historyCards(jobRecord())).toEqual([]);
  });

  it.each([
    ["2026-08-13T12:00:05Z", "just now"],
    ["2026-08-13T11:55:00Z", "5 min ago"],
    ["2026-08-13T10:00:00Z", "2 hr ago"],
    ["2026-08-12T12:00:00Z", "1 day ago"],
    ["2026-08-10T12:00:00Z", "3 days ago"],
  ])("formats relative time for %s", (savedAt, label) => {
    expect(relativeTimeLabel(savedAt, NOW)).toBe(label);
  });
});
