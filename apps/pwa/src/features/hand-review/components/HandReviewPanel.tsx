import { Check, RefreshCcw } from "lucide-react";
import "./HandReviewPanel.css";

import { ButtonControl } from "../../../shared/components/FormControls";
import { HandStateEditor, type HandStateEditorProps } from "./HandStateEditor";
import { JobStatusBadge } from "../../../shared/components/JobStatusBadge";
import type { JobRecord } from "../../../shared/types/jobs";

export interface HandReviewPanelProps {
  busy: boolean;
  canApprove: boolean;
  editor: HandStateEditorProps;
  job: JobRecord | null;
  onApprove: () => void | Promise<void>;
  onResetToParser: () => void;
}

export function HandReviewPanel({
  busy,
  canApprove,
  editor,
  job,
  onApprove,
  onResetToParser,
}: HandReviewPanelProps) {
  return (
    <section className="review-column" aria-label="Hand review">
      <div className="panel-header">
        <h2>Detected state</h2>
        {job ? (
          <span className="panel-header-status">
            <JobStatusBadge status={job.status} />
          </span>
        ) : null}
      </div>

      <div className="review-scroll">
        <HandStateEditor {...editor} />
      </div>

      <div className="review-actions">
        <ButtonControl
          onClick={() => void onApprove()}
          disabled={!canApprove || busy}
          aria-label="Approve state"
        >
          <Check size={15} aria-hidden="true" />
          Approve
        </ButtonControl>
        <ButtonControl
          variant="ghost"
          iconOnly
          onClick={onResetToParser}
          disabled={!job?.parser_result || busy}
          title="Reset to parser"
          aria-label="Reset to parser"
        >
          <RefreshCcw size={14} aria-hidden="true" />
        </ButtonControl>
      </div>
    </section>
  );
}
