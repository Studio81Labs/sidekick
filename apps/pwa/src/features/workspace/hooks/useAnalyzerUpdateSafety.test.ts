import { describe, expect, it } from "vitest";

import {
  analyzerUpdateSafetyReasons,
  type AnalyzerUpdateSafetyInput,
} from "./useAnalyzerUpdateSafety";

const SAFE_INPUT: AnalyzerUpdateSafetyInput = {
  analyzerMutation: false,
  backupRestore: false,
  benchmarkOperation: false,
  detectedStateDraft: false,
  lessonNoteDraft: false,
  pendingScreenshotFiles: false,
  screenCapture: false,
  screenshotMetadataDraft: false,
  screenshotMutation: false,
  trainingAnswerDraft: false,
  trainingReviewMutation: false,
  upload: false,
};

describe("analyzer update safety inventory", () => {
  it.each([
    ["analyzerMutation", "analyzer mutation"],
    ["backupRestore", "backup restore"],
    ["benchmarkOperation", "benchmark operation"],
    ["screenCapture", "screen capture"],
    ["screenshotMutation", "screenshot mutation"],
    ["trainingReviewMutation", "training review mutation"],
    ["upload", "screenshot upload"],
  ] as const)("registers busy owner %s", (owner, reason) => {
    expect(
      analyzerUpdateSafetyReasons({ ...SAFE_INPUT, [owner]: true }),
    ).toEqual({ busy: [reason], dirty: [] });
  });

  it.each([
    ["detectedStateDraft", "detected-state corrections"],
    ["lessonNoteDraft", "lesson note"],
    ["pendingScreenshotFiles", "selected screenshot files"],
    ["screenshotMetadataDraft", "screenshot title, notes, or tags"],
    ["trainingAnswerDraft", "training answer"],
  ] as const)("registers dirty owner %s", (owner, reason) => {
    expect(
      analyzerUpdateSafetyReasons({ ...SAFE_INPUT, [owner]: true }),
    ).toEqual({ busy: [], dirty: [reason] });
  });

  it("is safe only when every registered owner is idle and clean", () => {
    expect(analyzerUpdateSafetyReasons(SAFE_INPUT)).toEqual({
      busy: [],
      dirty: [],
    });
  });
});
