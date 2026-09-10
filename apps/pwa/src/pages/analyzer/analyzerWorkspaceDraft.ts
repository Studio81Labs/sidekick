import type { HandReviewDraft } from "../../features/hand-review/hooks/useHandReviewState";
import type { ScreenshotDetailsDraft } from "../../features/screenshots/hooks/useScreenshotDetails";

export interface PendingUploadRequestId {
  file: File;
  requestId: string;
}

/**
 * Unsaved administrative work retained only while the access gate is locked.
 * It deliberately excludes the administrator credential and live media stream.
 */
export interface AnalyzerWorkspaceDraft {
  activeJobId: string | null;
  files: readonly File[];
  handReview: HandReviewDraft | null;
  pendingUploadRequestIds: readonly PendingUploadRequestId[];
  screenshotMetadata: ScreenshotDetailsDraft | null;
}
