import { describe, expect, it } from "vitest";

import type {
  TrainingPositionFilter,
  TrainingProgress,
} from "../../../shared/types/training";
import {
  sameTrainingPositionFilter,
  trainingReviewQueueStatus,
} from "./trainingQueuePresentation";

function queueStatus(
  progress: TrainingProgress | null,
  view: "recent" | "review" | "lessons",
  loading = false,
): string {
  return trainingReviewQueueStatus(
    progress,
    view,
    loading,
    "recent",
    "all",
    null,
    "all",
    null,
    "all",
    "",
    "recent",
    null,
    null,
    null,
    null,
  );
}

describe("training queue presentation", () => {
  it("describes empty, loading, and automation-only views", () => {
    expect(queueStatus(null, "review")).toBe("No pending review hands.");
    expect(queueStatus(null, "review", true)).toBe("Updating review queue...");
    expect(queueStatus(null, "recent")).toBe(
      "Automation-only hands are not scored.",
    );
    expect(queueStatus(null, "lessons", true)).toBe("Reading saved lessons...");
  });

  it("compares position filters by semantic identity", () => {
    const button: TrainingPositionFilter = {
      kind: "position",
      position: "BTN",
      label: "Button",
    };
    expect(
      sameTrainingPositionFilter(button, {
        kind: "position",
        position: "BTN",
        label: "BTN",
      }),
    ).toBe(true);
    expect(
      sameTrainingPositionFilter(button, {
        kind: "position",
        position: "CO",
        label: "Cutoff",
      }),
    ).toBe(false);
    expect(
      sameTrainingPositionFilter(
        { kind: "unpositioned", label: "Missing" },
        { kind: "unpositioned", label: "Unpositioned" },
      ),
    ).toBe(true);
  });
});
