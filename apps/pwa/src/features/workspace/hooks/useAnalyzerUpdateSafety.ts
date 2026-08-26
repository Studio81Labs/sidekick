import { useUpdateSafetyRegistration } from "../../../shared/pwa/updateSafety";

export interface AnalyzerUpdateSafetyInput {
  analyzerMutation: boolean;
  backupRestore: boolean;
  benchmarkOperation: boolean;
  detectedStateDraft: boolean;
  lessonNoteDraft: boolean;
  pendingScreenshotFiles: boolean;
  screenCapture: boolean;
  screenshotMetadataDraft: boolean;
  screenshotMutation: boolean;
  trainingAnswerDraft: boolean;
  upload: boolean;
}

export function analyzerUpdateSafetyReasons({
  analyzerMutation,
  backupRestore,
  benchmarkOperation,
  detectedStateDraft,
  lessonNoteDraft,
  pendingScreenshotFiles,
  screenCapture,
  screenshotMetadataDraft,
  screenshotMutation,
  trainingAnswerDraft,
  upload,
}: AnalyzerUpdateSafetyInput) {
  return {
    busy: [
      analyzerMutation ? "analyzer mutation" : null,
      backupRestore ? "backup restore" : null,
      benchmarkOperation ? "benchmark operation" : null,
      screenCapture ? "screen capture" : null,
      screenshotMutation ? "screenshot mutation" : null,
      upload ? "screenshot upload" : null,
    ].filter((reason): reason is string => reason !== null),
    dirty: [
      detectedStateDraft ? "detected-state corrections" : null,
      lessonNoteDraft ? "lesson note" : null,
      pendingScreenshotFiles ? "selected screenshot files" : null,
      screenshotMetadataDraft ? "screenshot title, notes, or tags" : null,
      trainingAnswerDraft ? "training answer" : null,
    ].filter((reason): reason is string => reason !== null),
  };
}

export function useAnalyzerUpdateSafety(input: AnalyzerUpdateSafetyInput) {
  useUpdateSafetyRegistration(
    "analyzer-workspace",
    analyzerUpdateSafetyReasons(input),
  );
}
