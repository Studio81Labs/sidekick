import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { JobRecord } from "../../../shared/types/jobs";
import type { RecommendationResult } from "../../../shared/types/recommendations";
import {
  RecommendationPanel,
  type RecommendationPanelProps,
} from "./RecommendationPanel";

afterEach(cleanup);

const recommendation: RecommendationResult = {
  action: "raise",
  sizing: 7.5,
  confidence: 0.82,
  explanation: "Raise for value while keeping weaker hands in range.",
  raw: {},
};

function panelProps(
  overrides: Partial<RecommendationPanelProps> = {},
): RecommendationPanelProps {
  return {
    busy: false,
    decision: null,
    decisionComparison: null,
    evidence: null,
    job: {
      id: "job-1",
      training_reviewed_at: null,
      training_review_note: null,
    } as JobRecord,
    note: "",
    noteEditing: false,
    onCancelNoteEdit: vi.fn(),
    onCompleteReview: vi.fn(),
    onNoteChange: vi.fn(),
    onReopenReview: vi.fn(),
    onSaveNote: vi.fn(),
    onStartNoteEdit: vi.fn(),
    recommendation,
    reviewQueueJobId: null,
    ...overrides,
  };
}

describe("RecommendationPanel", () => {
  it("presents the recommended action, sizing, confidence, and explanation", () => {
    render(<RecommendationPanel {...panelProps()} />);

    const panel = screen.getByRole("region", { name: "Recommendation" });
    expect(panel).toHaveTextContent("raise");
    expect(panel).toHaveTextContent("7.5");
    expect(panel).toHaveTextContent("82% confidence");
    expect(panel).toHaveTextContent(recommendation.explanation);
  });
});
