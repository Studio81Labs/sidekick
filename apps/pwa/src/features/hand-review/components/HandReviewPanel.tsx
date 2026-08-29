import { Check, Play, RefreshCcw } from "lucide-react";
import type { ReactNode } from "react";
import "./HandReviewPanel.css";

import { ButtonControl } from "../../../shared/components/FormControls";
import { HandStateEditor, type HandStateEditorProps } from "./HandStateEditor";
import { isAdministrativeTestJob } from "../../../shared/lib/jobInputContext";
import { JobInputContextBadge } from "../../../shared/components/JobInputContextBadge";
import { JobStatusBadge } from "../../../shared/components/JobStatusBadge";
import type { JobRecord } from "../../../shared/types/jobs";

export interface HandReviewPanelProps {
  busy: boolean;
  canApprove: boolean;
  canRecommend: boolean;
  children?: ReactNode;
  editor: HandStateEditorProps;
  job: JobRecord | null;
  onApprove: () => void | Promise<void>;
  onRecommend: () => void | Promise<void>;
  onResetToParser: () => void;
}

export function HandReviewPanel({
  busy,
  canApprove,
  canRecommend,
  children,
  editor,
  job,
  onApprove,
  onRecommend,
  onResetToParser,
}: HandReviewPanelProps) {
  return (
    <section className="review-column" aria-label="Hand review">
      <div className="panel-header">
        <h2>Detected state</h2>
        {job ? (
          <span className="panel-header-status">
            <JobInputContextBadge job={job} />
            <JobStatusBadge status={job.status} />
          </span>
        ) : null}
      </div>

      <div className="review-scroll">
        <HandStateEditor {...editor} />
        {children}
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
          variant="secondary"
          onClick={() => void onRecommend()}
          disabled={!canRecommend || busy}
          aria-label="Request recommendation"
        >
          <Play size={14} aria-hidden="true" />
          Recommend
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
      {job && isAdministrativeTestJob(job) ? (
        <p className="review-hint">
          {
            "Administrative test inputs never request recommendations or enter training."
          }
        </p>
      ) : null}
    </section>
  );
}
