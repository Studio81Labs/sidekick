import { Square } from "lucide-react";

import "./QueueProcessingDialog.css";
import { ButtonControl } from "../../../shared/components/FormControls";
import { SummaryMetric } from "../../../shared/components/SummaryMetric";

export interface QueueProgress {
  aborting: boolean;
  completed: number;
  currentFile: string;
  currentIndex: number;
  failed: number;
  skipped: number;
  total: number;
}

export interface QueueProcessingDialogProps {
  onAbort: () => void;
  progress: QueueProgress;
}

export function QueueProcessingDialog({
  onAbort,
  progress,
}: QueueProcessingDialogProps) {
  const progressPercent =
    progress.total > 0
      ? Math.min(
          100,
          Math.max(0, Math.round((progress.completed / progress.total) * 100)),
        )
      : 0;

  return (
    <section className="processing-backdrop">
      <div
        className="processing-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="processing-dialog-title"
      >
        <div className="processing-header">
          <div>
            <h2 id="processing-dialog-title">
              {progress.aborting ? "Stopping import" : "Processing queue"}
            </h2>
            <p>
              {progress.currentIndex > 0
                ? `Screenshot ${progress.currentIndex} of ${progress.total}`
                : `Preparing ${progress.total} screenshots`}
            </p>
          </div>
          <strong>{progressPercent}%</strong>
        </div>

        <div className="processing-progress" aria-hidden="true">
          <span style={{ width: `${progressPercent}%` }} />
        </div>

        <div className="processing-current">
          <span>
            {progress.aborting
              ? "Discarding unprocessed screenshots"
              : "Current screenshot"}
          </span>
          <strong>{progress.currentFile || "Preparing queue"}</strong>
        </div>

        <div className="processing-stats">
          <SummaryMetric label="processed" value={progress.completed} />
          <SummaryMetric label="attention" value={progress.failed} />
          <SummaryMetric label="discarded" value={progress.skipped} />
        </div>

        <ButtonControl
          variant="secondary"
          onClick={onAbort}
          disabled={progress.aborting}
        >
          <Square size={13} aria-hidden="true" />
          Abort and discard unprocessed
        </ButtonControl>
      </div>
    </section>
  );
}
