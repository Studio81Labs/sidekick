import { Archive } from "lucide-react";

import "./ScreenshotQueuePanel.css";
import { humanReadableMessage } from "../../../shared/api/core";
import { ButtonControl } from "../../../shared/components/FormControls";
import { JobInputContextBadge } from "../../../shared/components/JobInputContextBadge";
import { JobStatusBadge } from "../../../shared/components/JobStatusBadge";
import { ScreenshotRailItem } from "../../../shared/components/ScreenshotRailItem";
import { screenshotLabel } from "../../../shared/lib/screenshotPresentation";
import { StateMessage } from "../../../shared/components/StateMessage";
import type { JobRecord } from "../../../shared/types/jobs";

export interface ScreenshotQueuePanelProps {
  activeJobId: string | null;
  attentionByJobId: Readonly<Record<string, string | undefined>>;
  busy: boolean;
  clearDisabled: boolean;
  count: number;
  jobs: readonly JobRecord[];
  onClearReviewed: () => void;
  onManageJob: (job: JobRecord) => void;
  onOpenJob: (job: JobRecord) => void;
  pendingFilesLabel: string | null;
}

function queueDetail(job: JobRecord, attention: string | undefined): string {
  if (attention) {
    return attention;
  }
  if (job.status === "error") {
    return humanReadableMessage(job.error, "Needs attention");
  }
  if (job.status === "created") {
    return "Parsing screenshot";
  }
  if (job.recommendation_pending) {
    return "Recommendation running";
  }
  if (job.parser_result && job.parser_result.warnings.length > 0) {
    return "Review warnings";
  }
  return job.parser_result?.state.street ?? "No street";
}

export function ScreenshotQueuePanel({
  activeJobId,
  attentionByJobId,
  busy,
  clearDisabled,
  count,
  jobs,
  onClearReviewed,
  onManageJob,
  onOpenJob,
  pendingFilesLabel,
}: ScreenshotQueuePanelProps) {
  return (
    <section className="queue-panel" aria-label="Screenshots queue">
      <div className="rail-section-heading">
        <span>Queued frames</span>
        <span className="sr-only">{count} screenshots</span>
        <span className="queue-heading-actions">
          <strong>{count}</strong>
          <ButtonControl
            variant="ghost"
            iconOnly
            className="clear-reviewed-button"
            onClick={onClearReviewed}
            disabled={clearDisabled}
            title="Clear reviewed to history"
            aria-label="Clear reviewed"
          >
            <Archive size={13} aria-hidden="true" />
          </ButtonControl>
        </span>
      </div>
      {jobs.length > 0 ? (
        <div className="batch-list">
          {jobs.map((candidate, index) => {
            const attention = attentionByJobId[candidate.id];
            return (
              <ScreenshotRailItem
                active={candidate.id === activeJobId}
                attention={Boolean(attention)}
                className="batch-item"
                key={candidate.id}
                manageLabel={`Manage screenshot ${index + 1}: ${candidate.original_filename}`}
                onManage={() => onManageJob(candidate)}
                onOpen={() => onOpenJob(candidate)}
                openClassName="batch-item-open"
                openDisabled={busy}
                openLabel={`Open screenshot ${index + 1}: ${candidate.original_filename}`}
              >
                <span className="batch-number">{index + 1}</span>
                <span className="batch-text">
                  <span>{screenshotLabel(candidate)}</span>
                  <small>{queueDetail(candidate, attention)}</small>
                </span>
                <span className="batch-status">
                  <JobInputContextBadge density="compact" job={candidate} />
                  <JobStatusBadge status={candidate.status} />
                </span>
              </ScreenshotRailItem>
            );
          })}
        </div>
      ) : (
        <StateMessage centered className="pending-files" framed size="compact">
          {pendingFilesLabel ?? "No screenshots uploaded or captured yet"}
        </StateMessage>
      )}
    </section>
  );
}
